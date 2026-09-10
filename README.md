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
pytest -q                                       # correctness gate
prng-lattice-lab validate                       # Randar published vector
prng-lattice-lab demo 7338710 7668738 5563335   # crack + predict next/prev tokens
prng-lattice-lab retro --total 20 --offset 10   # reconstruct a whole token stream from one captured window
prng-lattice-lab retro --total 30 --offset 12 --bound 255   # same for nextInt(odd) tokens (RandomStringUtils idiom)
prng-lattice-lab mt-demo --warmup 1000          # MT19937 contrast: clone Python's random from 624 outputs
prng-lattice-lab demonstrate nextint_odd --oracle jvm --out demo.json  # evidence artifact vs a REAL JVM (msb24|nextint_odd|seeded|mt19937)
prng-lattice-lab demonstrate --verify demo.json        # re-check a stored artifact (tamper + re-run)
prng-lattice-lab leaks --bits 8                 # characterise the 3 leak models, confirm H3
prng-lattice-lab sweep --trials 200             # run the phase-diagram grid (top-bits leak)
prng-lattice-lab sweep --model nextint_odd      # ... for the nextInt(odd) residue leak
prng-lattice-lab sweep --model bit_length       # ... for the starved bit-length leak (longer obs axis)
prng-lattice-lab report 1 --out report.md       # deterministic report from stored run
prng-lattice-lab report 1 --narrate             # + optional LLM prose (needs key; skip disclosed without)
```

## What works today vs pending
| piece | status |
|---|---|
| `java.util.Random` model + forward/back stepping | ✔ validated |
| 3×nextFloat round-off cracker (Randar core) | ✔ validated (published vector) |
| general-grid solver (fpylll box enumeration) | ✔ wired — full grid, complete enumeration |
| non-consecutive (`call_stride`) observations | ✔ wired |
| sweep + characterize + deterministic report | ✔ phase diagram, margin surface, exact-oracle calibration |
| retroactive token-stream reconstruction | ✔ verified (`retro`) |
| MT19937 comparison victim (exact untempering) | ✔ validated vs stdlib (`mt-demo`) |
| repoauditor `weak_rng_adapter` demonstration path | ✔ reuses validated cracker; artifacts carry a uniqueness/coincidence certificate + content hash |
| real-JVM oracle for demonstrations | ✔ `--oracle jvm` runs live OpenJDK `java.util.Random`; lab model matches it over random states (JDK optional) |
| seeded-constructor recovery (`new Random(seed)`) | ✔ `demonstrate seeded` recovers the constructor seed (e.g. a wall-clock creation time) |
| repoauditor `detect_in_source` (OPT-036) | ✔ merged (PR #129 detector, PR #130 plugin seam); `weak_rng` runs live in repoauditor |
| measurement-noise injection (third phase axis) | ✔ wired (`LeakProfile.noise`) |
| optional LLM narrative pass (`report --narrate`) | ✔ wired — key-gated, skip disclosed |
| odd-bound / bit-length leak models | ✔ generated + characterised (H3, `leaks`) **and recovered**: `recover/residue` (nextInt(odd), low-bit slicing, complete) · `recover/starved` (bit-length, subset lattice, complete); `sweep --model` draws each phase diagram |

Install the general solver with `pip install -e '.[lattice]'` (brings in
`fpylll` + `cysignals`). Without it the round-off anchor still scores and the
rest of the grid records honest capability gaps. The optional prose pass is
`pip install -e '.[narrative]'` + `ANTHROPIC_API_KEY`; without either, `--narrate`
discloses the skip in-report and the deterministic report stands as the report of record.

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
