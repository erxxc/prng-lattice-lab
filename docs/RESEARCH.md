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
- **H3 — Odd bounds leak less usable structure.** `nextInt(odd)` yields weaker
  per-call constraints than power-of-two bounds (the elttam / `RandomStringUtils`
  result). *Confirm on our own data.*

## Method
1. Model `java.util.Random` exactly (`lcg.py`). ✔ validated.
2. Recover state via LLL round-off for the over-determined regime
   (`recover/roundoff.py`). ✔ validated against the published Randar vector.
3. Generalise via fpylll box enumeration for the determined/edge regime
   (`recover/lattice.py`, `recover/enumerate.py`). ✔ wired; complete enumeration,
   budget-bounded. (Noise-injection / true starved-HNP enumeration still pending.)
4. Sweep the grid; record success rate, timing, method, margin, and candidate-count
   per cell (`sweep/grid.py` + `store/`). ✔ full grid scored.
5. Characterise: margin curve + calibration coverage against the exact oracle
   (`characterize/`). ☐ models pending.
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
- `nextint_odd` and `bit_length` leak models (elttam / Minerva ends of the family).
- Non-consecutive observations (`call_stride>1`): compose `a` with itself per step.
- Noise injection → force enumeration → bridge to real side-channel data.
- MT19937 comparison victim (624-output exact inversion; same capability, different math).
- Retroactive demonstration: recover "past" tokens from a captured sequence.
- Full Randar coordinate inversion (Woodland-region math) — only if the goal
  changes to a full reproduction.

## Fold-in transfer targets (into current projects)
- **repoauditor:** `weak_rng_adapter` as a deterministic detect-stage adapter whose
  live recovery demonstration is a corroborating source for severity licensing.
- **risk-quant calibration:** the margin curve is a closed-form-checkable oracle to
  validate prediction-interval coverage (session G) before applying it to noisy data.
- **methodology note:** exact-vs-noisy leakage as the crisp instance of the
  parameter-vs-process uncertainty split (risk-quant session C).
