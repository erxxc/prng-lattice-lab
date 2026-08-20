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

### `mt19937.py`  — comparison victim, complete
- MT19937 (Python `random`, Ruby, PHP) as the OPPOSITE corner of recoverability.
  `temper`/`untemper` (exact inverses), `recover_state` / `predict_next` — clone the
  generator from 624 CONSECUTIVE FULL 32-bit outputs by untempering, then run the
  twist recurrence forward. No lattice/fpylll. Validated against Python's stdlib MT
  (`test_mt19937.py`; `prng-lattice-lab mt-demo`). The contrast with the LCG (few
  partial outputs, graceful degradation) is the research point.

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
- `strided_lcg(stride)` / the `call_stride` parameter threaded through the recover path
  — non-consecutive observations (every stride-th call) reuse the same machinery with
  a^stride as the per-step multiplier; the reduced-basis cache keys on (n, stride).
  `call_stride=1` is byte-identical to the consecutive path.
- `noise` (on `LeakProfile`, `top_bits_bounds`, `recover_pre_states_top_bits`) — a
  bounded measurement error: the box widens by `noise`, recovery verifies within it.
  Completeness holds; ambiguity grows with noise, and over-determination buys tolerance.

### `recover/enumerate.py`  — complete
- `enumerate_box(reduced_basis, bounds, node_budget)` — COMPLETE enumeration of the
  lattice points in the box (search radius = box half-diagonal, so no in-box point
  is missed). Backed by fpylll's enumeration. Honours a node budget; raises
  `BudgetExceeded` (never a truncated set) when completeness can't be certified.

### `generate/`  — all three leak models wired
- `leak.observe(rng, profile)` — all three models produce real measurements:
  TOP_BITS (interval), NEXTINT_ODD (residue class mod odd bound), BIT_LENGTH (starved
  interval). All share the strided (`call_stride`) geometry via `_observe`.
  `item_drop_to_floats` — Randar item-drop inversion, complete.
- `harness.make_trials` — reproducible `(true_pre_call_state, observations)` trials,
  with optional measurement `noise`.

### `sweep/grid.py`  — complete; scores the whole grid
- `run_cell` routing: the 24×3 anchor → `roundoff` (validated, fpylll-free); a cell
  with n·k < 48 → `underdetermined` (no unique state, classified analytically, no
  recovery attempted); n·k ≥ 48 → the general solver, yielding `recovered` (unique)
  or `ambiguous` (collisions, with a `mean_candidates` range); a non-consecutive or
  non-TOP_BITS cell, or a missing fpylll → an honest `capability_gap`.
- `CellResult` now also carries `mean_candidates` and `outcome`. `run_sweep` returns
  one `CellResult` per grid cell.

### `characterize/`  — complete (read projections over stored cells)
- `margin.margin_surface` / `margin_curve` — the full 2-D margin surface (the old
  bits-only keying was lossy). `margin.roundoff_boundary` — locates the mean-margin
  0.5 crossing per observation count, and reports honestly when it does not cross
  within the measured grid (as on the default grid, where round-off is mean-safe
  throughout and uniqueness is the limiter).
- `calibration.predict` — modelled P(unique recovery) under the ideal-hash null
  (0 for n·k<48; exp(−2^(48−n·k)) above). `calibration.coverage` — the exact-oracle
  coverage test (Wilson interval; the transfer target for repoauditor risk-quant
  session G): the null covers the over/under-determined regions perfectly and the
  n·k=48 edge is where it and the structured LCG disagree. Plus `reliability_table`,
  `recovery_by_total_bits` (H1 edge), `recovery_boundary`. All accept `CellResult`
  objects or `store.list_cells` dict rows.
- `leakage.compare_leak_models` (`prng-lattice-lab leaks`) — confirms **H3** on our own
  data: per-call observation entropy (raw bits) + constraint structure (interval /
  residue-class / starved) + box-usable bits. Top-bits ≈ k usable bits; nextInt(odd)
  ≈ k raw bits but 0 box-usable (residue → HNP); bit-length ≈ 2 bits (starved).

### `store/db.py`  — sole DB owner, minimal but real
- SQLite. `record_sweep_run`, `record_cell`, `list_cells`. Validates every write
  against the schema (required-field check; upgrade to `jsonschema` is a drop-in).
- Migrations in `store/migrations/*.sql`, applied in order on connect.

### `report/synthesis.py`  — deterministic render + optional narrative, both wired
- `render_markdown` — pure read projection over stored cells: phase grid (unique-
  recovery rate), margin grid, the recoverability-edge table (ambiguous cells and
  their candidate-count range), the H1 recoverability boundary and the exact-oracle
  calibration/coverage section (both via `characterize/`), the underdetermined-region
  note, and disclosed gaps. No model, every number traces to a `SweepCell`.
- `synthesize_narrative(prompt_path=..., run_meta=..., model=...)` — LLM prose pass
  (`report --narrate`): loads the versioned prompt as the system instruction, passes
  the rendered deterministic report as the only citable evidence, and prefixes a
  machine-checkable attribution line (prompt version + model + run). Needs
  `ANTHROPIC_API_KEY` and the `narrative` extra; either absent raises
  `NarrativeUnavailable`, which the CLI discloses in-report — never faked prose
  (rules 7 & 8). Both branches are tested (fake-SDK injection for the with-key path).
- Takes `schema` and `prompt` as explicit inputs (the requested contract).

### `adapt/`  — contract complete; detect half pending
- `contract.py` — mirror of repoauditor's `CandidateFinding` + `RecoveryDemonstration`.
  **Verified against the live contract 2026-08-18** (repoauditor `detect/ensemble.py`
  + `matching.py`); corrections tracked as repoauditor OPT-036. Note the earlier
  "severity absent" premise was wrong: the adapter proposes a conservative INITIAL
  severity; repoauditor's normalize owns upgrades (licensed by the demonstration).
- `weak_rng_adapter.demonstrate_from_msb24` — complete (reuses validated roundoff),
  produces next/prev-token predictions as corroborating evidence.
- `weak_rng_adapter.reconstruct_stream` / `demonstrate_retroactive` — complete: a
  captured 3-token window reconstructs the ENTIRE issued stream (tokens before the
  window included), verified against ground truth (`prng-lattice-lab retro`).
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
- characterize: the ideal-hash null covers the over/under-determined regions exactly
  and the coverage test flags the n·k=48 edge deviation; margin surface/boundary and
  the H1 aggregates behave (`test_characterize.py`).
