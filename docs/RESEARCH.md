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
   next/prev token prediction (`adapt/weak_rng_adapter`). ✔ demonstration path.

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
  (see hypotheses). Their RECOVERY stays a disclosed capability gap: a residue class
  (odd bound) / starved interval (bit-length) needs an HNP lattice, not this lab's
  round-off box-CVP. The sweep records that gap explicitly for non-TOP_BITS cells.
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
- **risk-quant calibration:** the margin curve is a closed-form-checkable oracle to
  validate prediction-interval coverage (session G) before applying it to noisy data.
- **methodology note:** exact-vs-noisy leakage as the crisp instance of the
  parameter-vs-process uncertainty split (risk-quant session C).
