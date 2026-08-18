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
    wired = 0
    for c in results:
        store.record_cell(run_id, {
            "bits_per_call": c.bits_per_call, "num_observations": c.num_observations,
            "trials": c.trials, "successes": c.successes, "method_used": c.method_used,
            "median_ns": c.median_ns, "mean_margin": c.mean_margin,
            "capability_gap": c.capability_gap,
        })
        if c.capability_gap is None:
            wired += 1
    store.close()
    print(f"run {run_id}: {len(results)} cells ({wired} wired, "
          f"{len(results) - wired} capability-gap) -> {args.db}")
    return 0


def cmd_report(args) -> int:
    store = Store(args.db)
    cells = store.list_cells(args.run_id)
    if not cells:
        print(f"no cells for run {args.run_id}", file=sys.stderr)
        return 1
    md = synthesis.render_markdown(
        cells, schema_path=args.schema,
        run_meta={"run_id": args.run_id, "lab_version": __version__, "created_at": _now()},
    )
    store.close()
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"wrote {args.out}  (deterministic; prompt '{args.prompt}' would add prose)")
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
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("demo", help="crack three nextFloat MSBs and predict next/prev")
    sp.add_argument("msb", nargs=3, help="three top-24-bit measurements")
    sp.set_defaults(func=cmd_demo)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
