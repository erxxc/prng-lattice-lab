# CLAUDE.md — prng-lattice-lab

Read this and `docs/scaffold.md` at the start of every build session. They are the
source of truth. If code and these docs disagree, the docs win — fix the code or
fix the docs, never silently diverge.

## What this is

A closed, offline harness that characterises the recoverability boundary of
`java.util.Random` under partial-state leakage. It attacks a generator it
instantiates itself — there is no network target and no third-party system in
scope. Anchored on the Randar (Minecraft) truncated-LCG attack; generalised to a
`(bits-leaked-per-call × number-of-observations)` phase diagram; with a fold-in
path to **repoauditor** as a `weak_rng_adapter`.

**Central research question.** For `java.util.Random`, where is the boundary in
(bits-per-call × observations) space between "state recovered instantly by
round-off" and "requires enumeration / infeasible", and which common Java
token-generation idioms fall on the exploitable side?

## Pipeline

```
generate/ ─▶ recover/ ─▶ sweep/ ─▶ characterize/ ─▶ (report/  | adapt/)
 leak models  lattice*    grid       margin+calib*    deterministic  repoauditor
 + harness    roundoff*   driver                       report        fold-in
              enumerate*
```

`*` complete and validated · `†` specified, not yet wired.

The general solver (`recover/lattice.solve_box` + `recover/enumerate.enumerate_box`)
is now wired: with `fpylll` present the sweep scores the whole grid, classifying
each cell as recovered / ambiguous (genuine collisions at the recoverability edge)
/ underdetermined (n·k < 48). Without `fpylll` only the round-off anchor scores and
the rest record honest capability gaps.

## Non-negotiables (inherited from repoauditor; keep them identical so the fold-in is native)

1. **Schema-first.** `schema/records.schema.json` is the source of truth for every
   persisted/emitted record. Code validates against it; never the reverse.
2. **Thin CLI.** `cli.py` dispatches only. All logic lives in stage modules.
   Stages compose through the store and typed configs, never by reaching into each
   other's internals.
3. **`store/` is the sole DB owner.** Every write goes through `store/db.py` and is
   validated before it lands. No other module opens the database.
4. **Versioned prompts, never edited in place.** A prompt change is a new file
   (`*_v2.md`) plus a `prompts/REGISTRY.md` row. A version is not "active" until it
   is benchmarked against the prior — exercised ≠ benchmarked.
5. **Findings carry citations.** Every `WeakRngCandidateFinding` needs ≥1 citation.
   The lattice method cites the Randar writeup; a live recovery cites its own
   demonstration artifact. No unsourced claims.
6. **Severity is not ours to set.** The adapter proposes evidence
   (`RecoveryDemonstration`), it never assigns or upgrades severity. repoauditor's
   `normalize/adjudicate` owns severity and its corroboration-licensing rule. A
   severity upgrade requires an independent corroborating source **or** a
   falsification-confirmed result — here, the corroborating source is a reproducible
   recovery demonstration, not a prior.
7. **No faked results; honest baselines only.** A cell with no wired method records
   an explicit `capability_gap`, never a skipped or invented score. With `fpylll`
   present the sweep now scores the whole grid (recovered / ambiguous /
   underdetermined, 0 gaps); without it only the round-off anchor scores and the
   rest are disclosed gaps. Both states are correct and honest — the gap is a
   function of the environment, never a hidden failure.
8. **Uncertainty pauses, it does not self-resolve.** Where a result is ambiguous
   (enumeration budget exhausted, multiple candidate states), raise rather than pick
   silently. Uncertainty is always reported as a range, never collapsed to one number.

## Correctness invariant (do not break)

`tests/test_lcg.py` and `tests/test_roundoff.py` pin the published Randar vector:

```
crack_three_floats_msb(7338710, 7668738, 5563335) == 123123123123123
```

`tests/test_lattice.py` pins it a second way — through the general solver — and
also pins two properties the general path must not break: `fpylll` on
`build_basis(3)` reproduces `REDUCED_BASIS_3` (so the general path stays tied to
the validated round-off constants), and box enumeration is **complete** (the true
state is always in the returned set; ambiguity is never silently collapsed).

Any change to `lcg.py` transition constants or bit-extraction, to
`recover/roundoff.py`'s reduced-basis constants, or to `recover/lattice.py`'s
construction (`build_basis` / offsets / the round-off transform), must keep these
passing. If you touch the lattice math, re-run `pytest` before anything else. The
round-trip property test (3000 trials, exact-leak → 100% recovery) is the other
guardrail. `test_lattice`/`test_sweep` skip without `fpylll`; `test_lcg`,
`test_roundoff`, `test_store` are the fpylll-free core gate.

## The repoauditor fold-in — rules of engagement

- `adapt/contract.py` is a **mirror** of repoauditor's `CandidateFinding` shape,
  not a dependency. This harness never imports repoauditor and repoauditor never
  imports this. Keeping them decoupled is deliberate: the lab must run standalone,
  and the contract must be written down so drift is caught in review.
- At graduation, **re-read repoauditor's real `CandidateFinding` and `matching.py`
  contract** — treat `adapt/contract.py` as a possibly-stale snapshot. **Done
  2026-08-18**: the re-read found real drift (concrete location, required `severity`,
  `identity_key`, `confidence`, `source_tool`); `adapt/contract.py` is corrected and
  the fold-in is proposed as repoauditor **OPT-036** (`docs/optimizations/opt-036-weak-rng-adapter.md`
  in that repo), deferred pending owner approval — not yet built, per repoauditor's
  scope governance. The DETECT half (`detect_in_source`) is built inside repoauditor
  against its live retrieval layer, using `adapt/contract.py` as the spec. The
  DEMONSTRATE half already reuses the validated `recover/roundoff` path, so the
  fold-in inherits the passing vector.
- The adapter's job is the middle branch of the taxonomy: a *shared/predictable
  generator crossing a trust boundary*. That is invisible to SAST, dependency
  scanning, and CVE feeds — the whole reason it is worth adding.

## Scope guard (read before expanding)

This is a **weekend harness with a clean fold-in seam**, not a second product.
Known temptations to defer, not chase mid-session:
- ~~Wiring `recover/lattice.solve_box` + `recover/enumerate` for the whole grid.~~
  **Done** (2026-08-18) — the general solver is wired and the sweep scores the full
  grid honestly. Enumeration is fpylll's complete box enumeration; the `nextint_odd`
  / `bit_length` leak models and non-consecutive (`call_stride>1`) geometries remain
  deferred.
- The `nextint_odd` (elttam) and `bit_length` (Minerva) leak models.
- Full Randar coordinate inversion (Woodland-region math) — out of scope unless the
  goal changes to a full reproduction.
- Live-model narrative synthesis in `report/synthesis.py`.

**repoauditor's own DoD/UAT completion gate takes priority over this.** The
`weak_rng_adapter` is a strong *post-DoD* first feature; building the harness
standalone keeps it from jumping repoauditor's queue. If a session starts drifting
into breadth, stop and record the item in `docs/RESEARCH.md` backlog instead.

## Definition of done (this POC)

1. Randar vector passes and stays passing.
2. The 3×24-bit cell recovers pre-call state at 100% over ≥1000 trials.
3. Sweep persists a run with honest per-cell outcomes (scored or gap-disclosed).
4. Deterministic report renders from stored records with gaps disclosed in-report.
5. `adapt/weak_rng_adapter.demonstrate_from_msb24` produces a verifiable
   next/prev-token demonstration for the clean case.

The general-grid solver (originally deferred beyond this DoD) is now wired — the
sweep draws the full phase boundary and reports the recoverability edge as a
candidate-count range. Non-consecutive observations (`call_stride>1`) are now wired
too. Still explicitly deferred: odd-bound & bit-length leak models, noise injection,
MT19937 comparison, live narrative synthesis.

## Commands

```
prng-lattice-lab validate                         # Randar vector sanity
prng-lattice-lab sweep --trials 200               # run the grid, persist run+cells
prng-lattice-lab report <run_id> --schema ... --prompt ... --out report.md
prng-lattice-lab demo 7338710 7668738 5563335     # crack + predict next/prev
prng-lattice-lab retro --total 20 --offset 10     # reconstruct a whole stream from one 3-token window
pytest -q                                         # correctness gate
```

## Environment

Python ≥3.11. Core path needs only `numpy` (and stdlib). `fpylll` is optional and
only required for starved-leak cells; its absence is a recorded capability gap,
never a silent fallback. `jsonschema` optional (store falls back to required-field
checks). No deep learning, no network calls in the core path.
