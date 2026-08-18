# prng-lattice-lab

A closed, offline harness for characterising the recoverability boundary of
`java.util.Random` under partial-state leakage. Anchored on the **Randar**
(Minecraft) truncated-LCG attack; generalised to a *(bits-leaked-per-call ×
number-of-observations)* phase diagram; with a fold-in seam to **repoauditor** as
a `weak_rng_adapter`.

It attacks a generator it instantiates itself — no network target, no third-party
system. This is a diligence/defensive research tool: the point is to detect and
demonstrate predictable-token weaknesses in code under review.

## Quick start
```bash
pip install -e .
pytest -q                                       # correctness gate (8 tests)
prng-lattice-lab validate                       # Randar published vector
prng-lattice-lab demo 7338710 7668738 5563335   # crack + predict next/prev tokens
prng-lattice-lab retro --total 20 --offset 10   # reconstruct a whole token stream from one captured window
prng-lattice-lab sweep --trials 200             # run the phase-diagram grid
prng-lattice-lab report 1 --out report.md       # deterministic report from stored run
```

## What works today vs pending
| piece | status |
|---|---|
| `java.util.Random` model + forward/back stepping | ✔ validated |
| 3×nextFloat round-off cracker (Randar core) | ✔ validated (published vector) |
| general-grid solver (fpylll box enumeration) | ✔ wired — full grid, complete enumeration |
| sweep + store + deterministic report | ✔ recovered / ambiguous / underdetermined, 0 gaps with fpylll |
| repoauditor `weak_rng_adapter` demonstration path | ✔ reuses validated cracker |
| odd-bound / bit-length leak models, non-consecutive leaks | ☐ specified |
| detect-in-source half of the adapter | ☐ built inside repoauditor |

Install the general solver with `pip install -e '.[lattice]'` (brings in
`fpylll` + `cysignals`). Without it the round-off anchor still scores and the
rest of the grid records honest capability gaps.

See `CLAUDE.md` and `docs/scaffold.md` for the contracts, `docs/RESEARCH.md` for
the plan and hypotheses.

## Layout
```
CLAUDE.md              build-session source of truth (read first)
docs/scaffold.md       module contracts + data flow
docs/RESEARCH.md       plan, hypotheses, report skeleton, backlog
schema/                records.schema.json — schema-first source of truth
prompts/               versioned report prompts (never edited in place)
src/prng_lattice_lab/  lcg · generate · recover · sweep · characterize · store · adapt · report
tests/                 correctness gate incl. the Randar vector
```
