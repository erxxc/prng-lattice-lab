# RESEARCH.md — plan, hypotheses, report skeleton, backlog

## Research question
For `java.util.Random`, where is the boundary in (bits-per-call × observations)
space between instant round-off recovery and enumeration/infeasibility, and which
common Java token-generation idioms fall on the exploitable side?

## Hypotheses
- **H1 — Free above the line.** Recovery is essentially free (round-off, no
  enumeration) whenever total leaked bits ≥ 48 + small margin, regardless of how
  bits split across calls. *Predicts the 24×3 = 72-bit cell is instant.* — the one
  wired cell confirms this (100% recovery, margin ≈0.0017).
- **H2 — The margin governs the boundary.** As bits-per-call drops, ‖M·e‖∞ rises;
  crossing 0.5 marks the transition from round-off to required enumeration, and the
  needed observation count climbs sharply near the line. *This is the phase
  boundary the sweep exists to draw.* — the wired grid confirms it: mean margin
  falls off a cliff (≈0.45 → ≈0.01) right along the n·k≈48 diagonal, and the 100%-
  recovery region is exactly the small-margin corner.
- **H4 — Collisions at the edge (found, not predicted).** At n·k ≈ 48 recovery is
  *not* the whole story: distinct `java.util.Random` states produce identical top-k
  observations, so the leak is genuinely ambiguous even with an exact solver. The
  complete box enumeration reports this as a candidate-count range (mean ≈1.4–2.0
  consistent states) rather than collapsing to one answer — the recoverability
  edge is a band of ambiguity, not a clean line.
- **H3 — Odd bounds leak less usable structure. ✔ CONFIRMED** (`prng-lattice-lab
  leaks`; `characterize/leakage.py`). Measured per single call at a common 8-bit
  width: top-bits carries ~8.0 box-usable bits (interval); `nextInt(odd 255)` carries
  ~8.0 RAW bits but **0** box-usable (a residue class mod an odd bound — coprime to the
  2⁴⁸ modulus, so it needs an HNP lattice, not the round-off box); bit-length carries
  only ~2.0 bits/call (a starved interval). Two distinct ways to leak less USABLE
  structure than a clean top-bits leak of the same width — exactly the elttam /
  Minerva ends of the family.

- **H5 — The information edge is shape-independent; only the price of reaching it
  differs. ✔ CONFIRMED (2026-09-09; `sweep --model nextint_odd` / `bit_length`, 200
  trials/cell, seed 0).** Once each leak shape has a solver that is complete for it,
  unique recovery is governed by *realized* leaked bits against the 48-bit secret in
  exactly the way top-bits is:
    * nextInt(odd) (`recover/residue`): 49 cells, 0 gaps, 0 completeness misses, no
      rejection-shifted windows. 100% unique wherever n·log2(b) ≥ 60; the four cells at
      the edge (47.97–48.0 bits: (8,6), (12,4), (16,3), (24,2)) recover uniquely in
      67/200, 88/200, 83/200, 84/200 trials with 2.19 / 1.92 / 1.81 / 1.84 mean consistent
      states — the same collision band top-bits shows at n·k = 48. Ideal-hash coverage
      48/49 (the one miss is an edge cell, as for top-bits). Cost: ~10–35 ms per trial
      (2^17 vectorised slices), except (4,16) where the certified radius exceeds 0.5
      (ρ ≈ 1.07) and branching costs ~3 s per trial.
    * bit-length (`recover/starved`): 42 cells (obs axis 8…64); every SCORED trial
      recovered uniquely (31 cells at 100%, coverage 31/31). The price is observations:
      n ≤ 16 is underdetermined throughout (~33 realized bits at n = 16); n = 24 scores
      only ~6% of trials, n = 32 ~50%, n = 48 ~98%, n = 64 ~99.5% — the rest are
      disclosed per trial as underdetermined (<48 realized bits) or infeasible (the
      complete enumeration's cost, ~2^1.05 per lattice dimension, cannot be paid by
      1-bit observations). k = 2 is the starved extreme: infeasible until n = 48
      (7/200 scored) and 132/200 at n = 64.
  So "less usable structure" (H3) does not move the recoverability edge — it moves the
  cost of reaching it: 2^17 slices per trial for the residue shape, ~2× the observations
  (and a per-trial feasibility gate) for the starved shape.

## Method
1. Model `java.util.Random` exactly (`lcg.py`). ✔ validated.
2. Recover state via LLL round-off for the over-determined regime
   (`recover/roundoff.py`). ✔ validated against the published Randar vector.
3. Generalise via fpylll box enumeration for the determined/edge regime
   (`recover/lattice.py`, `recover/enumerate.py`). ✔ wired; complete enumeration,
   budget-bounded. (Noise-injection / true starved-HNP enumeration still pending.)
4. Sweep the grid; record success rate, timing, method, margin, and candidate-count
   per cell (`sweep/grid.py` + `store/`). ✔ full grid scored.
5. Characterise: margin surface/boundary + calibration coverage against the exact
   oracle (`characterize/`). ✔ done. The ideal-hash null — P(unique)=0 for n·k<48,
   exp(−2^(48−n·k)) above — is covered (95% Wilson) for the whole over/under-determined
   grid; the only cells it misses are the n·k=48 edge, where the structured LCG
   collides differently than a random hash (k=16×3 recovers *more* than the null,
   k=24×2 *less*). Mean margin stays below 0.5 across the measured grid, so uniqueness
   (H1), not round-off (H2), is the operative recovery limiter there.
6. Applied layer: map the recoverable region to real Java idioms
   (session tokens, reset codes, CSRF/nonces) and, for the clean case, demonstrate
   next/prev token prediction (`adapt/weak_rng_adapter`). ✔ demonstration path; the
   RandomStringUtils idiom too (`retro --bound 255`: an 8-token nextInt(255) window
   reconstructs the whole stream, verified; an ambiguous window is refused, not guessed).
7. Recover the other two leak shapes with solvers complete for them
   (`recover/residue.py`: low-17-bit slicing + certified round-off; `recover/starved.py`:
   informative-subset lattice + complete enumeration + replay filter), sweep each
   model's grid, classify on realized leaked bits (`SweepCell.leaked_bits`). ✔ done;
   H5 above.

## Report skeleton
Abstract → threat model (structured generator + partial view across a trust
boundary + multiple correlated samples) → recovery method (LCG + lattice +
round-off, with the validated vector) → **results** (phase diagram + margin curve,
the core) → **applied** (Java idioms + samples-to-break) → mitigations + the
design-review questions → limitations (exact vs noisy leakage) → reproducibility
appendix (run id, seed, trial count, lab + prompt versions).

## Backlog (deferred deliberately; do not chase mid-session)
- ~~Wire `recover/lattice.solve_box` + `recover/enumerate` for the full grid.~~
  **Done 2026-08-18** (fpylll complete box enumeration; full grid scored, with the
  recoverability edge reported as a candidate-count range).
- ~~`nextint_odd` and `bit_length` leak models (elttam / Minerva ends of the family).~~
  **Done 2026-08-20** — both wired on the GENERATE side (`generate/leak.py`) and
  characterised (`characterize/leakage.py`, `prng-lattice-lab leaks`), confirming H3
  (see hypotheses). ~~Their RECOVERY stays a disclosed capability gap.~~ **Done
  2026-09-09** — `recover/residue.py` + `recover/starved.py`; both complete for their
  model; `sweep --model` scores each grid (H5). Remaining known limits, disclosed per
  trial rather than hidden: a rejected nextInt draw inside an odd-bound window (rate
  ≤ 2^-16 for bounds 2^k − 1; excluded and itemised), and bit-length trials whose
  complete enumeration is infeasible within budget (k = 2 below n = 48).
- ~~Non-consecutive observations (`call_stride>1`): compose `a` with itself per step.~~
  **Done 2026-08-19** (`recover.lattice.strided_lcg`; the whole recover path takes a
  `call_stride`, keying the reduced basis on (n, stride) and using a^stride as the
  per-step multiplier; the grid no longer gaps strided cells).
- ~~Noise injection → force enumeration → bridge to real side-channel data.~~
  **Done 2026-08-19** (`LeakProfile.noise`; recovery widens the box by the noise bound
  and verifies within it). Finding — noise is a third axis: over-determination buys
  noise tolerance. At the n·k=48 edge, noise=1 already blows candidates from ~1.5 to
  ~27; a far over-determined cell (n·k=96) stays uniquely recoverable at noise=12.
  Enumeration stays complete throughout (truth never dropped).
- ~~MT19937 comparison victim (624-output exact inversion; same capability, different math).~~
  **Done 2026-08-19** (`mt19937.py`: temper/untemper/predict_next; `prng-lattice-lab
  mt-demo`; validated against Python's stdlib MT19937). Finding — the two victims sit
  at opposite corners of recoverability: java.util.Random needs a FEW PARTIAL outputs
  (3 top-24-bit nextFloats, lattice round-off) and degrades gracefully with leak
  width; MT19937 needs 624 CONSECUTIVE FULL 32-bit outputs, then recovery is EXACT and
  algebraic (untempering), but partial (top-bits) leakage breaks it. "Few outputs,
  tolerant of partial width" vs "all-or-nothing on width, but many outputs."
- ~~Retroactive demonstration: recover "past" tokens from a captured sequence.~~
  **Done 2026-08-18** (`weak_rng_adapter.reconstruct_stream` /
  `demonstrate_retroactive`; `prng-lattice-lab retro` CLI). A captured 3-token window
  reconstructs the entire issued stream, tokens BEFORE the window included, verified
  against ground truth.
- ~~Live-model narrative synthesis (`report/synthesis.synthesize_narrative`).~~
  **Done 2026-08-20** (`prng-lattice-lab report --narrate`): the versioned prompt is
  the system instruction, the deterministic report is the only citable evidence, and
  a machine-checkable attribution line (prompt version + model + run) is prefixed.
  Without a key/SDK it raises `NarrativeUnavailable` and the CLI discloses the skip
  in-report — the deterministic report is always the report of record; prose is never
  faked (rules 7 & 8). Both branches tested (fake-SDK injection for the with-key path).
- Full Randar coordinate inversion (Woodland-region math) — only if the goal
  changes to a full reproduction.

## Fold-in transfer targets (into current projects)
- **repoauditor:** `weak_rng_adapter` as a deterministic detect-stage adapter whose
  live recovery demonstration is a corroborating source for severity licensing.
  **Landed** (PR #129 detector, PR #130 plugin-manifest seam; 2026-09-09). All three
  detector idioms now have a lab-side demonstration path (top-bits: `demo`/`retro`;
  RandomStringUtils: `retro --bound`; Python `random`: `mt19937`). `prng-lattice-lab
  demonstrate` emits the `DemonstrationArtifact` payload — now against a REAL OpenJDK
  `java.util.Random` (`--oracle jvm`; the lab model matches the live generator over random
  states, so the attack is confirmed on the true target, not only the port), with a
  uniqueness/coincidence certificate, a tamper-evident hash, self-verification
  (`demonstrate --verify`), and a `seeded` kind that recovers a `new Random(seed)`
  constructor seed (e.g. a creation timestamp). Intake proposed in
  `docs/repoauditor-evidence-intake.md`; the Python detector (`weak_rng_py`) is built as an
  additive plugin on a local repoauditor branch. **2026-09-10:** `recover/mt19937_gf2`
  recovers MT19937 STATE from TRUNCATED Python outputs (`random()` 53 bits/call,
  `getrandbits(k)` k bits/call) by GF(2) linear solve — ~700 `random()` calls reach full
  rank 19937 (certified unique) and clone the generator. This gives the Python detector's
  `py-random-module` idiom a verified demonstration (`demonstrate mt19937_truncated`),
  closing the gap noted earlier. Recovers state not seed (MT seeding non-linear); the
  rejection-sampled idioms (`choice`/`randrange`) share the variable-gap structure with
  RandomStringUtils and remain the next item. **2026-09-10:** the variable-gap model is
  built (`recover/gaps.py`): an unknown-gap wrapper over the residue solver recovers
  java.util.Random state THROUGH RandomStringUtils character-filter rejections (anchor +
  fewest-rejections gap search + replay verification; `demonstrate randomstringutils`),
  solving windows the fixed-stride residue path used to exclude -- fast at low reject
  rates, honest `infeasible` past a budget at high ones (rule 8). Gaps are counted in
  state steps, so nextInt modulo-rejection and char-filter rejection are one mechanism.
  DISCLOSED boundary: this anchor technique needs a small recovery window, so it does NOT
  extend to the GF(2) MT solver (~700 obs); Python `random.choice`/`randrange` rejection
  sampling would need a different technique (SAT / meet-in-the-middle), out of scope.
- **risk-quant calibration:** the margin curve is a closed-form-checkable oracle to
  validate prediction-interval coverage (session G) before applying it to noisy data.
  **Scoped 2026-09-09** as a repoauditor proposal (held branch
  `risk-quant-calibration-proposal`, `docs/optimizations/opt-037-calibration-evidence.md`
  there): lift `characterize/calibration.py` into an additive `analyze/calibration.py`,
  self-test it on the lab's exact oracle, then apply it to triage's persisted
  probabilities vs later labels and to the simulator's Monte Carlo quantiles vs their
  analytic values.
- **methodology note:** exact-vs-noisy leakage as the crisp instance of the
  parameter-vs-process uncertainty split (risk-quant session C).
