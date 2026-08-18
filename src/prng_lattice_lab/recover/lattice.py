"""
General lattice construction and reduction for arbitrary (num_observations,
bits_per_call). recover/roundoff.py is the hard-coded 3xnextFloat special case;
this module is what the sweep uses to reach the rest of the phase diagram.

Design:
  build_basis(n)      -> the n-dimensional basis rows [(1,a,...,a^(n-1)); m*I_(n-1)]
  reduce(basis)       -> LLL/BKZ reduced basis + unimodular transform (via fpylll)
  solve_box(...)      -> given per-coordinate [lo, hi] measurement bounds, return
                         the internal state(s) consistent with them:
                           * round-off when the reduced box is tiny (margin << 0.5)
                           * branch-and-bound (recover/enumerate.py) otherwise

fpylll is an OPTIONAL dependency. For the validated 3-float path the lab does not
need it (roundoff.py is self-contained). It becomes required only for the starved
-leak cells of the sweep. Import is therefore deferred and its absence is a
recorded capability limit, never a silent fallback to fake results.

CITATIONS:
  * LLL: Lenstra, Lenstra, Lovász (1982).
  * Application to java.util.Random: mjtb49/LattiCG; Earthcomputer/JavaRandomReverser.
  * Reduced-basis-as-round-off framing: spawnmason/randar-explanation, "Worked example".
"""
from __future__ import annotations

from prng_lattice_lab.lcg import A, MASK

# The LLL-reduced basis for the 3-float java.util.Random lattice, kept here in
# full (roundoff.py keeps only first components). Reference value; any fpylll run
# on build_basis(3) must reproduce an equivalent basis (up to sign/permutation).
REDUCED_BASIS_3 = (
    (1270789291, -2446815537, 2154219555),
    (-2355713969, 1026597795, 4110294631),
    (-3756485696, -2345310016, -2015749696),
)

MODULUS = MASK + 1  # 2**48


def build_basis(n: int) -> list[list[int]]:
    """Basis rows for the n-observation consecutive-call lattice.

    Row 0:   (1, a, a^2, ..., a^(n-1))
    Rows 1..n-1: m on the diagonal (the modular wrap on each later coordinate).

    This omits the affine offset o = (0, b, a*b+b, ...); callers subtract o from
    the measurement target before solving (see solve_box). Consecutive calls
    only (call_stride==1); strided/gapped observations compose a with itself
    `stride` times per step -- TODO when the sweep needs non-consecutive leaks.
    """
    rows: list[list[int]] = []
    first = [pow(A, k, MODULUS) if k > 0 else 1 for k in range(n)]
    # note: first row uses true a^k (not reduced) so the lattice is exact; the
    # entries are large by design and LLL shrinks them.
    first = [1]
    acc = 1
    for _k in range(1, n):
        acc = acc * A
        first.append(acc)
    rows.append(first)
    for i in range(1, n):
        row = [0] * n
        row[i] = MODULUS
        rows.append(row)
    return rows


def reduce(basis: list[list[int]]):
    """Return (reduced_basis, transform) via LLL. Requires fpylll.

    Raises ReductionUnavailable if fpylll is not installed, so the sweep records
    an explicit capability gap for the affected cells rather than inventing data.
    """
    try:
        from fpylll import IntegerMatrix, LLL  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ReductionUnavailable(
            "fpylll not installed; only the roundoff 3-float path is available. "
            "Install fpylll to characterise starved-leak cells."
        ) from exc
    mat = IntegerMatrix.from_matrix(basis)
    reduced = LLL.reduction(mat)
    return reduced, None


def solve_box(bounds: list[tuple[int, int]], method: str = "auto") -> list[int]:
    """Given per-coordinate measurement bounds [(lo0,hi0), ...], return internal
    states consistent with all of them.

    NOT YET IMPLEMENTED for the general case. The validated 3-float path lives in
    recover/roundoff.py; wire this to fpylll + recover/enumerate.py during the
    Sat-PM "generalise with a real lattice library" step. Contract:
      * returns [] when no consistent state exists (garbage input),
      * returns the unique state when the box is tight (round-off regime),
      * returns all candidates when the box admits several (starved regime).
    """
    raise NotImplementedError(
        "General box solver pending fpylll wiring. Use recover.roundoff for the "
        "3-consecutive-nextFloat case, which is complete and validated."
    )


class ReductionUnavailable(RuntimeError):
    """Raised when a lattice-reduction backend is required but not installed."""
