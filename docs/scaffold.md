# scaffold.md — architecture source of truth

Read alongside `CLAUDE.md` at the start of every session. This file describes the
module contracts and data flow. When a contract here and the code disagree, decide
deliberately which to change; do not let them drift.

## Data flow

```
                    schema/records.schema.json  ← source of truth for record shapes
                                │ validates
                                ▼
config (typed)  ─▶  generate/  ─▶  recover/  ─▶  sweep/  ─▶  store/  ─▶  report/
  LeakProfile        harness       roundoff*      grid       db.py      synthesis
  SweepConfig        leak          lattice*                  (sole      (read
  GeneratorSpec                    enumerate*                 owner)     projection)
                                                                │
                                                                ▼
                                                             adapt/  ─▶  repoauditor
                                                          weak_rng_adapter  (external)
```

`*` complete + validated · `†` specified, not wired.

## Module contracts

### `lcg.py`  — CORRECTNESS-CRITICAL, complete
- `step` / `step_back` — forward/inverse LCG on the 48-bit state. Exact inverses.
- `JavaRandom` — bit-exact `java.util.Random`. `__init__` scrambles (mirrors
  `new Random(seed)`); `from_internal_state` sets the raw field (for reproducing a
  known state). `next(bits)` steps THEN reads (the ordering that makes the pre/post
  step distinction matter downstream).
- `next_int(bound)` models the rejection loop; power-of-two bounds leak clean top
  bits, odd bounds bias which bits survive (the elttam case).
- `floats_to_msb24` — recover the exact 24-bit measurements from nextFloat outputs.

### `recover/roundoff.py`  — complete + validated
- `crack_three_floats_msb(m1,m2,m3)` → post-first-step state, or `None` (garbage
  guard). Hard-codes the LLL-reduced basis + change-of-basis for `java.util.Random`.
- `recover_pre_call_state` → the state BEFORE the three calls (one `step_back`).
  This is the one to feed backward-stepping.
- `margin(...)` → ‖M·e‖∞ for a measurement. The <0.5 crossing is the whole
  experiment.

### `recover/lattice.py`  — complete
- `build_basis(n)` — n-observation lattice rows. `REDUCED_BASIS_3` is the validated
  reference (fpylll on `build_basis(3)` must reproduce it up to sign/permutation;
  pinned by `test_lattice`).
- `reduce` — LLL via fpylll; returns the reduced rows; raises `ReductionUnavailable`
  if fpylll absent (→ the sweep records a capability gap, never fakes). Reduced
  basis + round-off transform are cached per n.
- `affine_offsets` / `top_bits_bounds` — fold the LCG affine offset into the per-
  coordinate measurement box for a consecutive TOP_BITS leak.
- `margin_top_bits` — generalised `‖M·e‖∞`; matches `roundoff.margin` on (24,3) and
  extends to any (bits, obs). The <0.5 crossing is the round-off boundary.
- `solve_box(bounds, method=…)` — every lattice point in the box (via
  `enumerate_box`): [] = inconsistent, one = unique, several = collisions.
  `method="roundoff"` is the single Babai point (fast, no uniqueness guarantee).
- `recover_pre_states_top_bits` — pre-call states consistent with a leak; the entry
  the sweep uses. One element = unique recovery; more than one = genuine collisions.

### `recover/enumerate.py`  — complete
- `enumerate_box(reduced_basis, bounds, node_budget)` — COMPLETE enumeration of the
  lattice points in the box (search radius = box half-diagonal, so no in-box point
  is missed). Backed by fpylll's enumeration. Honours a node budget; raises
  `BudgetExceeded` (never a truncated set) when completeness can't be certified.

### `generate/`  — TOP_BITS complete
- `leak.observe(rng, profile)` — TOP_BITS complete; NEXTINT_ODD and BIT_LENGTH
  pending. `item_drop_to_floats` — Randar item-drop inversion, complete.
- `harness.make_trials` — reproducible `(true_pre_call_state, observations)` trials.

### `sweep/grid.py`  — complete; scores the whole grid
- `run_cell` routing: the 24×3 anchor → `roundoff` (validated, fpylll-free); a cell
  with n·k < 48 → `underdetermined` (no unique state, classified analytically, no
  recovery attempted); n·k ≥ 48 → the general solver, yielding `recovered` (unique)
  or `ambiguous` (collisions, with a `mean_candidates` range); a non-consecutive or
  non-TOP_BITS cell, or a missing fpylll → an honest `capability_gap`.
- `CellResult` now also carries `mean_candidates` and `outcome`. `run_sweep` returns
  one `CellResult` per grid cell.

### `characterize/`  — hooks in place, models pending
- `margin.margin_curve` — aggregates per-cell margins, locates the 0.5 crossing.
- `calibration.predict/coverage` — the exact-oracle calibration transfer target for
  repoauditor risk-quant session G. Pending.

### `store/db.py`  — sole DB owner, minimal but real
- SQLite. `record_sweep_run`, `record_cell`, `list_cells`. Validates every write
  against the schema (required-field check; upgrade to `jsonschema` is a drop-in).
- Migrations in `store/migrations/*.sql`, applied in order on connect.

### `report/synthesis.py`  — deterministic render complete; prose pending
- `render_markdown` — pure read projection over stored cells: phase grid (unique-
  recovery rate), margin grid, the recoverability-edge table (ambiguous cells and
  their candidate-count range), the underdetermined-region note, and disclosed gaps.
  No model, every number traces to a `SweepCell`.
- `synthesize_narrative(prompt_path=...)` — LLM prose hook; loads the versioned
  prompt, tags output with its version. Not wired (no key assumed).
- Takes `schema` and `prompt` as explicit inputs (the requested contract).

### `adapt/`  — contract complete; detect half pending
- `contract.py` — mirror of repoauditor's `CandidateFinding` + `RecoveryDemonstration`.
  Severity deliberately absent.
- `weak_rng_adapter.demonstrate_from_msb24` — complete (reuses validated roundoff),
  produces next/prev-token predictions as corroborating evidence.
- `weak_rng_adapter.detect_in_source` — pending; built inside repoauditor.

## Store schema (records)

Defined in `schema/records.schema.json`: `GeneratorSpec`, `LeakProfile`,
`SweepRun`, `SweepCell`, `RecoveryDemonstration`, `Citation`,
`WeakRngCandidateFinding`. `SweepCell.capability_gap` is the honest-baseline field:
populated instead of a score when a method is unavailable. `SweepCell.outcome`
(recovered / ambiguous / underdetermined / gap) and `SweepCell.mean_candidates`
(mean size of the consistent-state set; the rule-8 uncertainty-as-range field)
were added in migration `0002`; the store tracks applied migrations in a
`_migrations` table so append-only `ALTER TABLE`s run exactly once.

## Invariants enforced by tests

- Published Randar vector (`test_roundoff.py::test_published_vector`), and again
  through the general solver (`test_lattice.py::test_general_recovers_published_vector`).
- `step`/`step_back` mutual inverses over 10k random states (`test_lcg.py`).
- 3×24-bit exact-leak → 100% pre-call recovery over 3000 trials.
- Margin of the 3-float case < 0.01 (≈2⁻⁹); `margin_top_bits` matches `roundoff.margin`.
- fpylll reduces `build_basis(3)` to `REDUCED_BASIS_3` up to sign/permutation.
- Box enumeration is complete (truth always enumerated) and exposes real collisions
  at n·k=48; the node-budget guard raises rather than truncating.
- Grid classifies cells honestly and the store's migrations are idempotent
  (`test_sweep.py`, `test_store.py`).
