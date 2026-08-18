"""
Branch-and-bound enumeration over the reduced lattice, for the regime where a
single round-off is not guaranteed (margin approaches / exceeds 0.5 -- i.e. leak
starved below ~48 bits total, or noisy observations).

This is the bridge to the "hard" end of the family (Minerva/HNP-style marginal
leakage). It is deliberately a separate module from roundoff.py so the sweep can
attribute each cell's result to the method that actually solved it, and so the
report can show WHERE on the phase diagram the transition from round-off to
enumeration occurs.

NOT YET IMPLEMENTED. Contract when built:
  enumerate_box(reduced_basis, transform, bounds, node_budget) ->
      Iterator[int]      # yields every internal state whose lattice point lies
                         # inside the measurement box, cheapest-first
  It must honour node_budget and, on exhaustion, raise BudgetExceeded rather than
  return a partial set silently (mirrors repoauditor: uncertainty pauses, never
  self-resolves).

Reference implementations to port from (do NOT vendor; study and reimplement):
  * mjtb49/LattiCG  (Java, inequality system -> lattice -> B&B)
  * rjb3977/lattice-c  (fast enumeration core)
"""
from __future__ import annotations


def enumerate_box(reduced_basis, transform, bounds, node_budget: int = 1_000_000):
    raise NotImplementedError(
        "Branch-and-bound enumeration pending. Fast path recover.roundoff covers "
        "the over-determined (round-off) regime; this module covers the starved "
        "regime and is the Sunday-stretch / Minerva-bridge work."
    )


class BudgetExceeded(RuntimeError):
    """Node budget hit before the box was fully enumerated."""
