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

### `recover/gaps.py`  — unknown-gap recovery (built)
- Recovers state when observed tokens sit at UNKNOWN stream positions because some draws
  were rejected and never observed (Java `nextInt` modulo-reject; RandomStringUtils
  character-filter reject). `recover_unknown_gaps(observed, solver, ...)`: an anchor window
  is gap-searched in fewest-rejections order (all-consecutive first), each candidate is
  REPLAY-verified against ALL observations (which discovers the true gaps), so a verified
  state is certain. Gaps are counted in STATE STEPS, unifying both rejection kinds.
  `GapSolver` protocol; `ResidueGapSolver(bound, accept)` wraps `recover/residue`
  (`residue.recover_pre_states_at_positions`, a positions-aware lattice solve). Bounded:
  past `budget` it reports `budget_exhausted` = INFEASIBLE, never a guess (rule 8);
  >1 verified state is reported as ambiguity. Scope: fits the small-window LATTICE solvers,
  NOT the GF(2) MT solver (needs ~700 obs, too large to gap-enumerate) -- Python
  `choice`/`randrange` rejection is disclosed out of scope for this technique.

### `recover/mt19937_gf2.py`  — MT19937 from TRUNCATED outputs, GF(2) (built)
- `SymbolicMT` mirrors CPython's twist+temper carrying each word-bit as a D=624·32-bit
  vector over the initial-state basis; substituting a concrete state reproduces CPython
  bit-for-bit (`test_mt19937_gf2.py`, Python as oracle). `GF2System` is online Gauss-Jordan
  (exact `rank`). `recover_from_random(doubles)` / `recover_from_getrandbits(values, bits)`
  add equations from the observable top bits and solve; `Recovery.unique` is `rank ==
  EFFECTIVE_BITS` (19937) — a CERTIFIED uniqueness, not assumed. `predict_next_words` /
  `concrete_state_words` predict forward or clone via `random.setstate`. ~700 `random()`
  calls reach full rank (~0.5 s). Recovers STATE not seed (MT seeding is non-linear);
  assumes observations start at a generator's first output (mid-stream offset search
  deferred); word-0 low 31 bits are irrelevant and set 0. Serves the `py-random-module` /
  `py-random-getrandbits` idioms the full-word `mt19937.py` untemper cannot.

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

### `recover/residue.py`  — complete (nextInt(odd bound), the residue-class leak)
- The state is split `s = 2^17·X + r`. The low 17 bits `r` run their own LCG mod 2^17
  (a is odd), so for each of the 2^17 values of `r` (vectorised in numpy, uint64
  wrap-around arithmetic exact mod 2^48) the carry into the top half is known and the
  top 31 bits obey `q_t ≡ g^t·X' + E_t(r) (mod 2^31)` with `q_t ∈ [0, ⌊2^31/b⌋)` — the
  truncated-LCG box problem of `lattice.py` in a 31-bit lattice with the same multiplier
  vector. `Q = ⌊2^31/b⌋` is exact for ACCEPTED draws (Java's rejection loop).
- `slice_basis(n, stride)` — LLL of the 31-bit basis (fpylll, cached; the only
  non-numpy step). `certified_radius(n, b, stride)` — `max_i Σ_j |M_ij|·Q/2`, a
  worst-case bound on any in-box point's displacement in reduced coordinates,
  observation-independent. `< 0.5` ⇒ one round-off candidate per slice.
- `recover_post_states_nextint_odd` — every consistent `s_1` (COMPLETE: all integer
  vectors within the certified radius are checked; branches where `ρ ≥ 0.5`; raises
  `RowBudgetExceeded` rather than truncating). Returns the realized round-off margin of
  the solved slice, the same figure `margin_top_bits` reports.
- `recover_pre_states_nextint_odd` — steps back and replays Java's real `nextInt`
  (rejection loop included) as the garbage guard. `rejections_in_window` lets the sweep
  detect (from ground truth) a rejected draw inside the window — outside the fixed-
  stride model, excluded and itemised, never counted as a completeness failure.
- `leaked_bits(b, n) = n·log2 b` — the classification uses realized information.

### `recover/starved.py`  — complete (bit-length of nextInt(2^k), the starved leak)
- `interval(L, k)` / `info_bits(L, k)` — bit-length `L` pins the state to
  `[2^(L−1)·w, 2^L·w)`, `w = 2^(48−k)`, worth `k−L+1` bits (`k` for `L = 0`); ~2 bits
  per call on average, half the observations worth exactly one.
- `plan_subset` — keeps only observations worth ≥2 bits, most informative first: every
  lattice dimension multiplies the complete enumeration's ball by ~2^1.05, so a 1-bit
  observation cannot pay for itself. Stops when the predicted cost is negligible or at
  `max_dim=40`. Raises `Underdetermined` (<48 realized bits) or `Infeasible` (predicted
  cost over budget) BEFORE any lattice work — the per-trial feasibility the sweep
  discloses.
- `recover_pre_states_bit_length` — irregular-gap lattice over the chosen indices
  (multiplier `a^gap` + its own affine offset per column), columns scaled by powers of
  two so the anisotropic box is a cube, `enumerate_box` (COMPLETE), then each candidate
  is stepped back and replay-filtered against ALL observations — complete for the whole
  run, not just the subset. Returns the plan and the subset round-off margin.

### `generate/`  — all three leak models wired
- `leak.observe(rng, profile)` — all three models produce real measurements:
  TOP_BITS (interval), NEXTINT_ODD (residue class mod odd bound), BIT_LENGTH (starved
  interval). All share the strided (`call_stride`) geometry via `_observe`.
  `item_drop_to_floats` — Randar item-drop inversion, complete.
- `harness.make_trials` — reproducible `(true_pre_call_state, observations)` trials,
  with optional measurement `noise`.

### `sweep/grid.py`  — complete; scores the whole grid, one leak model per run
- `run_cell` routing, TOP_BITS: the 24×3 anchor → `roundoff` (validated, fpylll-free);
  n·k < 48 → `underdetermined` (no unique state, classified analytically, no recovery
  attempted); n·k ≥ 48 → the general solver, yielding `recovered` (unique) or
  `ambiguous` (collisions, with a `mean_candidates` range); missing fpylll → an honest
  `capability_gap`.
- NEXTINT_ODD: `n·log2(bound)` more than half a bit below 48 → `underdetermined`; else
  `recover/residue` per trial (`method_used = residue_slice`). A trial whose window held
  a rejected draw is excluded and itemised in `capability_gap`.
- BIT_LENGTH: feasibility per trial via `recover/starved` — `Underdetermined` /
  `Infeasible` trials are skipped and itemised; scored trials use
  `subset_enumerate`. A cell with no scorable trial is `underdetermined` or
  `infeasible` (a solver limit, disclosed as distinct from the information floor).
- `CellResult.trials` counts SCORED trials; `model`, `bound`, `leaked_bits` (realized
  information, mean over scored trials) make each cell self-describing.
  `CellResult.record()` is the SweepCell record. `run_sweep(cfg)` iterates
  `cfg.bits_axis × cfg.samples_axis` for `cfg.model`; `config.default_samples_axis`
  gives BIT_LENGTH its longer observation axis (8…64).

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

### `adapt/jvm_oracle.py`  — real-JVM oracle (built; JDK optional)
- Compiles a tiny Java emitter once (`_classes_dir`, cached) and runs a live
  `java.util.Random`; `emit(state, kind, n, bound)` returns `msb24` / `nextint` tokens.
  No reflection: `new Random(state ^ 0x5DEECE66D)` sets the internal seed to `state`.
  `available()` / `java_version()` gate it; absence degrades to the lab model, recorded.
  Matches the lab model over random states on both idioms (`test_jvm_oracle.py`).

### `adapt/evidence.py`  — demonstration artifacts (built)
- `demonstrate(kind, ..., oracle=)` → `DemonstrationArtifact` for `msb24` (roundoff),
  `nextint_odd` (recover/residue), `seeded` (recover the `new Random(seed)` constructor
  seed — often a wall-clock time — via roundoff + unscramble) or `mt19937` (exact
  untempering). Each artifact carries: `oracle` (`jvm` real OpenJDK vs `lab_model`), a
  `Certificate` (complete-solver candidate count + a false-match `coincidence_bound`
  ~2^(-bits·held_out) + the residue radius), a tamper-evident `content_sha256`, the
  reproduction command, citations, predictions, exact verification, claim boundary.
  Deterministic in `seed`. `verify_record` re-checks the hash then re-runs; `validate_record`
  checks the schema before the CLI emits. An ambiguous window yields `recovered=false` with
  the candidate count, never a guess. See `docs/repoauditor-evidence-intake.md` for intake.

### `adapt/`  — contract complete; detect half landed in repoauditor
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
were added in migration `0002`; `SweepCell.model`, `bound` and `leaked_bits`
(realized information; drives the underdetermined/edge classification and the
ideal-hash null instead of n·k) in migration `0003`, alongside the `infeasible`
outcome and the `residue_slice` / `subset_enumerate` methods. `Store.get_run`
returns the run config (which carries the sweep's leak model). The store tracks
applied migrations in a `_migrations` table so append-only `ALTER TABLE`s run
exactly once; rows without a `model` are read as `top_bits`.

## Invariants enforced by tests

- Published Randar vector (`test_roundoff.py::test_published_vector`), and again
  through the general solver (`test_lattice.py::test_general_recovers_published_vector`).
- `step`/`step_back` mutual inverses over 10k random states (`test_lcg.py`).
- 3×24-bit exact-leak → 100% pre-call recovery over 3000 trials.
- Margin of the 3-float case < 0.01 (≈2⁻⁹); `margin_top_bits` matches `roundoff.margin`.
- fpylll reduces `build_basis(3)` to `REDUCED_BASIS_3` up to sign/permutation.
- Box enumeration is complete (truth always enumerated) and exposes real collisions
  at n·k=48; the node-budget guard raises rather than truncating.
- `recover/residue`: unique recovery on over-determined odd-bound cells, completeness +
  collisions at the 48-bit edge, strided and non-canonical (91) bounds, the rejection
  counter matches Java's loop, garbage → no candidate, row budget raises
  (`test_residue.py`).
- `recover/starved`: exact interval/information accounting, feasibility refusals
  (`Underdetermined` / `Infeasible`), the plan never buys 1-bit observations, complete +
  unique on the over-determined run, strided recovery (`test_starved.py`).
- Sweep routes the two models through their solvers with honest outcomes and
  itemised skips; the store persists `model`/`bound`/`leaked_bits`; calibration
  classifies on realized bits; the report renders the new methods/outcomes; the
  odd-bound `retro --bound` demonstration verifies and refuses to guess when ambiguous
  (`test_sweep.py`, `test_store.py`, `test_characterize.py`, `test_report.py`,
  `test_retro.py`).
- Grid classifies cells honestly and the store's migrations are idempotent
  (`test_sweep.py`, `test_store.py`).
- characterize: the ideal-hash null covers the over/under-determined regions exactly
  and the coverage test flags the n·k=48 edge deviation; margin surface/boundary and
  the H1 aggregates behave (`test_characterize.py`).
