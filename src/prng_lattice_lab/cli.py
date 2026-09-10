"""
Thin CLI. Dispatch only -- all logic lives in the stage modules. No stage reaches
into another stage's internals; they compose through the store and typed configs.

Commands:
  validate     run the Randar test vector through the live cracker (fast sanity)
  sweep        run the (bits x samples) grid, persist run + cells
  report       render the deterministic report for a stored run
                 (takes --schema and --prompt as inputs)
  demo         one-shot: crack three nextFloat MSBs and show forward/back prediction
  retro        reconstruct a whole token stream from one captured window (nextFloat
                 tokens, or nextInt(odd bound) tokens with --bound)
  demonstrate  emit a schema-validated DemonstrationArtifact (msb24 | nextint_odd |
                 seeded | mt19937 | mt19937_truncated), optionally against a REAL JVM
                 (--oracle jvm); mt19937_truncated recovers MT state from truncated Python
                 outputs by GF(2) solve; --verify re-checks a stored artifact

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
from prng_lattice_lab.config import LeakModel, RecoverMethod, SweepConfig, default_samples_axis
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
    model = LeakModel(args.model)
    cfg = SweepConfig(trials_per_cell=args.trials, method=RecoverMethod.AUTO, seed=args.seed,
                      model=model, samples_axis=default_samples_axis(model))
    results = grid.run_sweep(cfg)
    store = Store(args.db)
    run_id = store.record_sweep_run({
        "config": {"model": model.value, "bits_axis": list(cfg.bits_axis),
                   "samples_axis": list(cfg.samples_axis),
                   "trials_per_cell": cfg.trials_per_cell, "seed": cfg.seed},
        "lab_version": __version__, "created_at": _now(),
    })
    tally: dict[str, int] = {}
    for c in results:
        store.record_cell(run_id, c.record())
        tally[c.outcome or "?"] = tally.get(c.outcome or "?", 0) + 1
    store.close()
    summary = ", ".join(f"{n} {k}" for k, n in sorted(tally.items()))
    print(f"run {run_id} [{model.value}]: {len(results)} cells ({summary}) -> {args.db}")
    return 0


def cmd_report(args) -> int:
    store = Store(args.db)
    cells = store.list_cells(args.run_id)
    if not cells:
        print(f"no cells for run {args.run_id}", file=sys.stderr)
        return 1
    stored = store.get_run(args.run_id) or {}
    run_meta = {"run_id": args.run_id, "lab_version": __version__, "created_at": _now(),
                "model": (stored.get("config") or {}).get("model", cells[0].get("model", "top_bits"))}
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
    if args.bound is None:
        window = 3
        token = "nextFloat top-24-bit"
    else:
        window = args.window or weak_rng_adapter.default_window_nextint_odd(args.bound)
        token = f"nextInt({args.bound})"
    if args.offset + window > args.total or args.offset < 0:
        print(f"offset must be >=0 and leave room for a {window}-token window "
              f"(offset+{window} <= total)", file=sys.stderr)
        return 2
    state = random.Random(args.seed).getrandbits(48)
    try:
        if args.bound is None:
            demo = weak_rng_adapter.demonstrate_retroactive(state, args.total, args.offset)
        else:
            demo = weak_rng_adapter.demonstrate_retroactive_nextint_odd(
                state, args.total, args.offset, args.bound, window)
    except weak_rng_adapter.AmbiguousRecovery as exc:
        # rule 8: an ambiguous window is reported as ambiguous, never resolved by a guess
        print(json.dumps({"token": token, "observations_used": window, "recovered": False,
                          "ambiguous": True, "consistent_states": exc.candidates}, indent=2))
        return 1
    print(json.dumps({
        "token": token,
        "observations_used": demo.observations_used,
        "recovered": demo.recovered_state_present,
        "verified": demo.verified,
        "retroactive_tokens_recovered": len(demo.predicted_prev),
        "forward_tokens_recovered": len(demo.predicted_next),
        "retroactive_sample": demo.predicted_prev[:5],
    }, indent=2))
    return 0 if (demo.recovered_state_present and demo.verified) else 1


def cmd_demonstrate(args) -> int:
    from prng_lattice_lab.adapt import evidence, jvm_oracle
    if args.verify:
        with open(args.verify, "r", encoding="utf-8") as fh:
            record = json.load(fh)
        ok, detail = evidence.verify_record(record)
        print(json.dumps({"verify": args.verify, "ok": ok, "detail": detail,
                          "oracle": record.get("oracle")}, indent=2))
        return 0 if ok else 1
    if args.kind is None:
        print("demonstrate: a KIND or --verify FILE is required", file=sys.stderr)
        return 2
    try:
        art = evidence.demonstrate(
            args.kind, seed=args.seed, total=args.total, offset=args.offset, bound=args.bound,
            window=args.window, warmup=args.warmup, predict=args.predict, oracle=args.oracle,
            mt_source=args.mt_source, mt_bits=args.mt_bits, mt_calls=args.mt_calls,
            rsu_bound=args.rsu_bound, rsu_accept=args.rsu_accept)
    except jvm_oracle.OracleUnavailable as exc:
        print(f"demonstrate: {exc}", file=sys.stderr)
        return 2
    record = art.to_record()
    evidence.validate_record(record, args.schema)      # schema-first: never emit unvalidated
    text = json.dumps(record, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {args.out}  (kind={art.kind}, oracle={art.oracle}, verified={art.verified})")
    else:
        print(text)
    return 0 if art.verified else 1


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


def cmd_leaks(args) -> int:
    from prng_lattice_lab.characterize import leakage
    res = leakage.compare_leak_models(bits_per_call=args.bits, trials=args.trials, seed=args.seed)
    print(json.dumps({
        "bits_per_call": res["bits_per_call"],
        "h3_confirmed": res["h3_confirmed"],
        "verdict": res["verdict"],
        "per_model": [{
            "model": r["model"], "bound": r["bound"], "raw_bits": round(r["raw_bits"], 3),
            "structure": r["structure"], "box_usable": r["box_usable"],
            "box_usable_bits": round(r["box_usable_bits"], 3),
        } for r in res["rows"]],
    }, indent=2))
    return 0 if res["h3_confirmed"] else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="prng-lattice-lab", description=__doc__)
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("validate", help="run the Randar published test vector")
    sp.set_defaults(func=cmd_validate)

    sp = sub.add_parser("sweep", help="run the (bits x samples) phase-diagram grid for one leak model")
    sp.add_argument("--model", choices=[m.value for m in LeakModel], default=LeakModel.TOP_BITS.value,
                    help="leak model to sweep: top_bits (nextFloat / pow2 nextInt), nextint_odd "
                         "(residue class; recover/residue), bit_length (starved; recover/starved, "
                         "uses a longer observation axis)")
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
    sp.add_argument("--bound", type=int, default=None,
                    help="tokens are nextInt(BOUND) with an ODD bound (RandomStringUtils-style) "
                         "instead of nextFloat; recovery routes through recover/residue")
    sp.add_argument("--window", type=int, default=None,
                    help="captured-window size for --bound (default: enough calls for ~56 bits)")
    sp.set_defaults(func=cmd_retro)

    sp = sub.add_parser("demonstrate", help="emit a self-contained, schema-validated recovery "
                                            "demonstration artifact (the corroborating evidence "
                                            "payload for a repoauditor weak_rng finding)")
    sp.add_argument("kind", nargs="?",
                    choices=["msb24", "nextint_odd", "seeded", "mt19937", "mt19937_truncated",
                             "randomstringutils"],
                    help="omit when using --verify")
    sp.add_argument("--seed", type=int, default=0)
    sp.add_argument("--total", type=int, default=20, help="tokens issued (msb24 / nextint_odd / seeded)")
    sp.add_argument("--offset", type=int, default=10, help="captured-window index (msb24 / nextint_odd)")
    sp.add_argument("--bound", type=int, default=255, help="odd nextInt bound (nextint_odd)")
    sp.add_argument("--window", type=int, default=None, help="window size (nextint_odd; default ~56 bits)")
    sp.add_argument("--warmup", type=int, default=1000, help="outputs skipped before capture (mt19937)")
    sp.add_argument("--predict", type=int, default=5, help="outputs predicted and checked (mt19937*)")
    sp.add_argument("--mt-source", choices=["random", "getrandbits"], default="random",
                    help="mt19937_truncated observation type: random() (53 bits/call) or getrandbits(k)")
    sp.add_argument("--mt-bits", type=int, default=32, help="k for mt19937_truncated --mt-source getrandbits")
    sp.add_argument("--mt-calls", type=int, default=None, help="observed calls (default: enough for full rank)")
    sp.add_argument("--rsu-bound", type=int, default=255, help="odd nextInt bound (randomstringutils)")
    sp.add_argument("--rsu-accept", type=int, default=200, help="in-class count: keep nextInt(bound) < this (randomstringutils)")
    sp.add_argument("--oracle", choices=["auto", "jvm", "lab_model"], default="auto",
                    help="token source for the java kinds: auto uses a real JVM when present, "
                         "jvm requires a JDK, lab_model forces the port")
    sp.add_argument("--verify", default=None, metavar="FILE",
                    help="re-verify a stored artifact (tamper + re-run) instead of emitting one")
    sp.add_argument("--schema", default="schema/records.schema.json")
    sp.add_argument("--out", default=None, help="write the JSON artifact here (else stdout)")
    sp.set_defaults(func=cmd_demonstrate)

    sp = sub.add_parser("mt-demo", help="MT19937 comparison: clone Python's random from "
                                        "624 outputs and predict the next (exact untempering)")
    sp.add_argument("--seed", type=int, default=0, help="seed for the stdlib MT19937 victim")
    sp.add_argument("--warmup", type=int, default=1000, help="outputs to advance before capture")
    sp.add_argument("--predict", type=int, default=5, help="how many next outputs to predict")
    sp.set_defaults(func=cmd_mt_demo)

    sp = sub.add_parser("leaks", help="characterise the three leak models and confirm H3 "
                                      "(odd bounds / bit-length leak less usable structure)")
    sp.add_argument("--bits", type=int, default=8, help="common target width per call")
    sp.add_argument("--trials", type=int, default=40000, help="single-call samples per model")
    sp.add_argument("--seed", type=int, default=0)
    sp.set_defaults(func=cmd_leaks)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
