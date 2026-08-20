"""
Thin CLI. Dispatch only -- all logic lives in the stage modules. No stage reaches
into another stage's internals; they compose through the store and typed configs.

Commands:
  validate     run the Randar test vector through the live cracker (fast sanity)
  sweep        run the (bits x samples) grid, persist run + cells
  report       render the deterministic report for a stored run
                 (takes --schema and --prompt as inputs)
  demo         one-shot: crack three nextFloat MSBs and show forward/back prediction

Uses argparse (stdlib) to keep the scaffold dependency-light; swap for typer/click
if the CLI grows.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

from prng_lattice_lab import __version__
from prng_lattice_lab.config import RecoverMethod, SweepConfig
from prng_lattice_lab.recover import roundoff
from prng_lattice_lab.report import synthesis
from prng_lattice_lab.store.db import Store
from prng_lattice_lab.sweep import grid


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def cmd_validate(_args) -> int:
    got = roundoff.crack_three_floats_msb(7338710, 7668738, 5563335)
    expected = 123123123123123
    ok = got == expected
    print(f"crack(7338710, 7668738, 5563335) = {got}")
    print(f"expected                         = {expected}")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def cmd_sweep(args) -> int:
    cfg = SweepConfig(trials_per_cell=args.trials, method=RecoverMethod.AUTO, seed=args.seed)
    results = grid.run_sweep(cfg)
    store = Store(args.db)
    run_id = store.record_sweep_run({
        "config": {"bits_axis": list(cfg.bits_axis), "samples_axis": list(cfg.samples_axis),
                   "trials_per_cell": cfg.trials_per_cell, "seed": cfg.seed},
        "lab_version": __version__, "created_at": _now(),
    })
    tally: dict[str, int] = {}
    for c in results:
        store.record_cell(run_id, {
            "bits_per_call": c.bits_per_call, "num_observations": c.num_observations,
            "trials": c.trials, "successes": c.successes, "method_used": c.method_used,
            "median_ns": c.median_ns, "mean_margin": c.mean_margin,
            "mean_candidates": c.mean_candidates, "outcome": c.outcome,
            "capability_gap": c.capability_gap,
        })
        tally[c.outcome or "?"] = tally.get(c.outcome or "?", 0) + 1
    store.close()
    summary = ", ".join(f"{n} {k}" for k, n in sorted(tally.items()))
    print(f"run {run_id}: {len(results)} cells ({summary}) -> {args.db}")
    return 0


def cmd_report(args) -> int:
    store = Store(args.db)
    cells = store.list_cells(args.run_id)
    if not cells:
        print(f"no cells for run {args.run_id}", file=sys.stderr)
        return 1
    run_meta = {"run_id": args.run_id, "lab_version": __version__, "created_at": _now()}
    md = synthesis.render_markdown(cells, schema_path=args.schema, run_meta=run_meta)
    store.close()

    narrated = False
    if args.narrate:
        try:
            prose = synthesis.synthesize_narrative(
                md, prompt_path=args.prompt, run_meta=run_meta, model=args.model)
            md = f"{md}\n\n---\n\n{prose}\n"
            narrated = True
        except synthesis.NarrativeUnavailable as exc:
            # Rule 7/8: never fabricate prose. Disclose the skip in-report AND on stderr.
            md = (f"{md}\n\n---\n\n## Narrative (not generated)\n\n"
                  f"_Prose pass from prompt `{Path(args.prompt).stem}` was requested but "
                  f"skipped: {exc} The deterministic report above is complete and is the "
                  f"report of record._\n")
            print(f"narrative skipped: {exc}", file=sys.stderr)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(md)
        tag = (f"deterministic + narrative ({args.model})" if narrated
               else "deterministic" + (" (narrative skipped, gap disclosed)" if args.narrate else ""))
        print(f"wrote {args.out}  ({tag})")
    else:
        print(md)
    return 0


def cmd_demo(args) -> int:
    from prng_lattice_lab.adapt import weak_rng_adapter
    obs = [int(x) for x in args.msb]
    demo = weak_rng_adapter.demonstrate_from_msb24(obs)
    print(json.dumps({
        "observations_used": demo.observations_used,
        "recovered": demo.recovered_state_present,
        "predicted_next": demo.predicted_next,
        "predicted_prev": demo.predicted_prev,
    }, indent=2))
    return 0 if demo.recovered_state_present else 1


def cmd_retro(args) -> int:
    import random

    from prng_lattice_lab.adapt import weak_rng_adapter
    if args.offset + 3 > args.total or args.offset < 0:
        print("offset must be >=0 and leave room for a 3-token window (offset+3 <= total)",
              file=sys.stderr)
        return 2
    state = random.Random(args.seed).getrandbits(48)
    demo = weak_rng_adapter.demonstrate_retroactive(state, args.total, args.offset)
    print(json.dumps({
        "observations_used": demo.observations_used,
        "recovered": demo.recovered_state_present,
        "verified": demo.verified,
        "retroactive_tokens_recovered": len(demo.predicted_prev),
        "forward_tokens_recovered": len(demo.predicted_next),
        "retroactive_sample": demo.predicted_prev[:5],
    }, indent=2))
    return 0 if (demo.recovered_state_present and demo.verified) else 1


def cmd_mt_demo(args) -> int:
    import random

    from prng_lattice_lab import mt19937
    r = random.Random(args.seed)
    for _ in range(args.warmup):
        r.getrandbits(32)
    observed = [r.getrandbits(32) for _ in range(624)]
    predicted = mt19937.predict_next(observed, args.predict)
    actual = [r.getrandbits(32) for _ in range(args.predict)]
    print(json.dumps({
        "victim": "python stdlib random.Random (MT19937)",
        "observations_used": 624,
        "predicted_next": predicted,
        "verified": predicted == actual,
        "contrast": ("MT19937 needs 624 consecutive FULL 32-bit outputs, then exact "
                     "untempering; java.util.Random needs ~3 PARTIAL (top-24-bit) "
                     "outputs via lattice round-off"),
    }, indent=2))
    return 0 if predicted == actual else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="prng-lattice-lab", description=__doc__)
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("validate", help="run the Randar published test vector")
    sp.set_defaults(func=cmd_validate)

    sp = sub.add_parser("sweep", help="run the (bits x samples) phase-diagram grid")
    sp.add_argument("--trials", type=int, default=200)
    sp.add_argument("--seed", type=int, default=0)
    sp.add_argument("--db", default="data/lab.db")
    sp.set_defaults(func=cmd_sweep)

    sp = sub.add_parser("report", help="render the deterministic report for a run")
    sp.add_argument("run_id", type=int)
    sp.add_argument("--db", default="data/lab.db")
    sp.add_argument("--schema", default="schema/records.schema.json")
    sp.add_argument("--prompt", default="prompts/report_synthesis_v1.md")
    sp.add_argument("--out", default=None)
    sp.add_argument("--narrate", action="store_true",
                    help="append LLM prose from the versioned prompt (needs ANTHROPIC_API_KEY "
                         "+ the 'narrative' extra; absence is disclosed as a gap, never faked)")
    sp.add_argument("--model", default=synthesis.DEFAULT_NARRATIVE_MODEL,
                    help="model for the optional --narrate prose pass")
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("demo", help="crack three nextFloat MSBs and predict next/prev")
    sp.add_argument("msb", nargs=3, help="three top-24-bit measurements")
    sp.set_defaults(func=cmd_demo)

    sp = sub.add_parser("retro", help="retroactively reconstruct a whole token stream "
                                      "from one captured 3-token window (verified)")
    sp.add_argument("--total", type=int, default=20, help="tokens the generator issues")
    sp.add_argument("--offset", type=int, default=10, help="stream index of the captured window")
    sp.add_argument("--seed", type=int, default=0, help="seed picking the hidden internal state")
    sp.set_defaults(func=cmd_retro)

    sp = sub.add_parser("mt-demo", help="MT19937 comparison: clone Python's random from "
                                        "624 outputs and predict the next (exact untempering)")
    sp.add_argument("--seed", type=int, default=0, help="seed for the stdlib MT19937 victim")
    sp.add_argument("--warmup", type=int, default=1000, help="outputs to advance before capture")
    sp.add_argument("--predict", type=int, default=5, help="how many next outputs to predict")
    sp.set_defaults(func=cmd_mt_demo)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
