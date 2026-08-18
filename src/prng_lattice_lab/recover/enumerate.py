"""
Complete enumeration of the lattice points inside a measurement box, for the
regime where a single round-off is not guaranteed (margin approaches / exceeds
0.5 -- i.e. leak starved toward ~48 bits total, or genuine collisions at the
recoverability edge).

This is the bridge to the "hard" end of the family (Minerva/HNP-style marginal
leakage). It is deliberately a separate module from roundoff.py so the sweep can
attribute each cell's result to the method that actually solved it, and so the
report can show WHERE on the phase diagram the transition from round-off to
enumeration occurs -- and where recovery stops being UNIQUE (>1 consistent state).

Why enumeration and not just closest-vector: at total leak ~= 48 bits, the true
state is frequently NOT the closest lattice point, and more than one lattice
point lies in the box (distinct java.util.Random states producing identical
top-k observations). Reporting the closest one as "the" state would silently
collapse that ambiguity. Enumeration finds ALL of them, so ambiguity is reported
as a range (rule 8: uncertainty pauses, it does not self-resolve).

Correctness contract:
  enumerate_box(reduced_basis, bounds, node_budget) -> list[list[int]]
      Returns EVERY lattice vector of the given basis whose coordinates lie in
      the half-open box [lo_j, hi_j). The search radius is the box's half-
      diagonal, which provably bounds every in-box point, so the returned set is
      COMPLETE -- never a truncated prefix. If the number of candidates within
      radius reaches node_budget (completeness no longer certifiable) it raises
      BudgetExceeded rather than returning a partial set silently.

fpylll is an OPTIONAL dependency; the import is deferred so the validated round-
off path (recover.roundoff) runs without it. Its absence surfaces upstream as an
explicit capability gap, never a silent fallback to fake results.

Reference implementations studied (not vendored): mjtb49/LattiCG (inequality
system -> lattice -> enumeration), Earthcomputer/JavaRandomReverser.
"""
from __future__ import annotations


class BudgetExceeded(RuntimeError):
    """Node/solution budget hit before the box could be fully enumerated; the
    result set cannot be certified complete, so we raise instead of guessing."""


def enumerate_box(
    reduced_basis: list[list[int]],
    bounds: list[tuple[int, int]],
    *,
    node_budget: int = 1_000_000,
) -> list[list[int]]:
    """All lattice vectors of `reduced_basis` lying in the half-open box `bounds`.

    `reduced_basis` : n rows of an (already LLL-reduced) basis of the lattice.
    `bounds`        : per-coordinate (lo, hi); the box is [lo_j, hi_j).
    Returns canonical integer lattice vectors; [] if the box is empty.
    Raises BudgetExceeded if more than `node_budget` candidates fall within the
    bounding radius (cannot certify completeness).
    """
    try:
        from fpylll import GSO, Enumeration, EnumerationError, IntegerMatrix
    except ImportError as exc:  # pragma: no cover - environment dependent
        from prng_lattice_lab.recover.lattice import ReductionUnavailable
        raise ReductionUnavailable(
            "fpylll not installed; enumeration unavailable. Only the roundoff "
            "3-float path runs without it."
        ) from exc

    n = len(bounds)
    centers = [(lo + hi) / 2.0 for lo, hi in bounds]
    half2 = sum(((hi - lo) / 2.0) ** 2 for lo, hi in bounds)
    radius2 = half2 * (1.0 + 1e-6)  # box half-diagonal; bounds every in-box point

    mat = IntegerMatrix.from_matrix([[int(x) for x in row] for row in reduced_basis])
    gso = GSO.Mat(mat)
    gso.update_gso()

    enum = Enumeration(gso, nr_solutions=node_budget)
    target = gso.from_canonical(centers)
    try:
        solutions = enum.enumerate(0, n, radius2, 0, target=target)
    except EnumerationError as exc:  # pragma: no cover - budget dependent
        raise BudgetExceeded(
            f"enumeration exceeded node budget {node_budget} within the bounding radius"
        ) from exc
    if len(solutions) >= node_budget:
        raise BudgetExceeded(
            f"enumeration hit the {node_budget}-candidate cap; completeness not certifiable"
        )

    in_box: list[list[int]] = []
    for _dist, coeffs in solutions:
        c = [int(round(x)) for x in coeffs]
        vec = [sum(c[i] * int(mat[i, j]) for i in range(n)) for j in range(n)]
        if all(lo <= vec[j] < hi for j, (lo, hi) in enumerate(bounds)):
            in_box.append(vec)
    return in_box
