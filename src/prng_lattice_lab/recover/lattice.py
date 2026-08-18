"""
General lattice construction and reduction for arbitrary (num_observations,
bits_per_call). recover/roundoff.py is the hard-coded 3xnextFloat special case;
this module is what the sweep uses to reach the rest of the phase diagram.

Geometry (consecutive TOP_BITS leak, call_stride==1):
  The unknown is x = s_1, the java.util.Random state immediately AFTER the first
  observed call (roundoff.py returns the same quantity; step_back(x) is the pre-
  call state). Successive states are s_{1+t} = a^t * x + o_t (mod 2**48), with the
  affine offset o_t = b*(a^{t-1}+...+a+1). Observing the top k bits of s_{1+t}
  pins s_{1+t} to an interval of width w = 2**(48-k); subtracting o_t moves that
  interval onto lattice coordinate t. Recovery is therefore a box-CVP on the
  lattice spanned by build_basis(n).

  build_basis(n)      -> rows [(1,a,...,a^(n-1)); m*I on coords 1..n-1]
  reduce(basis)       -> LLL-reduced rows (via fpylll)
  solve_box(bounds)   -> every lattice point in the per-coordinate box:
                           * one point  -> unique recovery (round-off regime)
                           * several    -> genuine collisions (recoverability edge)
                           * none       -> inconsistent (garbage guard)

fpylll is an OPTIONAL dependency. The validated 3-float path (roundoff.py) needs
neither fpylll nor this module. fpylll becomes required only for the rest of the
sweep; its import is deferred and its absence is a recorded capability gap, never
a silent fallback to fake results.

CITATIONS:
  * LLL: Lenstra, Lenstra, Lovasz (1982).
  * Application to java.util.Random: mjtb49/LattiCG; Earthcomputer/JavaRandomReverser.
  * Reduced-basis-as-round-off framing: spawnmason/randar-explanation, "Worked example".
"""
from __future__ import annotations

import numpy as np

from prng_lattice_lab.lcg import A, B, MASK, step, step_back
from prng_lattice_lab.recover.enumerate import enumerate_box

# The LLL-reduced basis for the 3-float java.util.Random lattice, kept here in
# full (roundoff.py keeps only first components). Reference value; any fpylll run
# on build_basis(3) must reproduce an equivalent basis (up to sign/permutation).
REDUCED_BASIS_3 = (
    (1270789291, -2446815537, 2154219555),
    (-2355713969, 1026597795, 4110294631),
    (-3756485696, -2345310016, -2015749696),
)

MODULUS = MASK + 1  # 2**48


class ReductionUnavailable(RuntimeError):
    """Raised when a lattice-reduction backend is required but not installed."""


def build_basis(n: int) -> list[list[int]]:
    """Basis rows for the n-observation consecutive-call lattice.

    Row 0:       (1, a, a^2, ..., a^(n-1))   -- exact integer powers (large by
                 design; LLL shrinks them). Reducing them mod m would give the
                 same lattice, since coords 1..n-1 carry a full m on the diagonal.
    Rows 1..n-1: m on the diagonal (the modular wrap on each later coordinate).

    Omits the affine offset o_t; callers fold it into the box (see top_bits_bounds).
    Consecutive calls only; strided observations would compose a with itself
    `stride` times per step -- deferred until the sweep needs non-consecutive leaks.
    """
    first = [1]
    acc = 1
    for _ in range(1, n):
        acc *= A
        first.append(acc)
    rows: list[list[int]] = [first]
    for i in range(1, n):
        row = [0] * n
        row[i] = MODULUS
        rows.append(row)
    return rows


def reduce(basis: list[list[int]]) -> list[list[int]]:
    """LLL-reduce a basis, returning its rows. Requires fpylll.

    Raises ReductionUnavailable if fpylll is not installed, so the sweep records
    an explicit capability gap for the affected cells rather than inventing data.
    """
    try:
        from fpylll import LLL, IntegerMatrix  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ReductionUnavailable(
            "fpylll not installed; only the roundoff 3-float path is available. "
            "Install fpylll to characterise the rest of the phase diagram."
        ) from exc
    mat = IntegerMatrix.from_matrix([[int(x) for x in row] for row in basis])
    LLL.reduction(mat)
    return [[int(mat[i, j]) for j in range(mat.ncols)] for i in range(mat.nrows)]


# --- reduced-basis cache (the reduced basis depends only on n) ------------------
_REDUCED: dict[int, list[list[int]]] = {}
_MINV: dict[int, np.ndarray] = {}


def reduced_basis(n: int) -> list[list[int]]:
    """LLL-reduced basis rows for n observations (cached)."""
    if n not in _REDUCED:
        _REDUCED[n] = reduce(build_basis(n))
    return _REDUCED[n]


def _round_off_transform(n: int) -> np.ndarray:
    """M = (R^T)^-1 for the reduced basis R: the change into reduced-basis
    coordinates used by both the margin and Babai round-off (z = M @ target)."""
    if n not in _MINV:
        R = np.array(reduced_basis(n), dtype=float)
        _MINV[n] = np.linalg.inv(R.T)
    return _MINV[n]


def affine_offsets(n: int) -> list[int]:
    """o_t for t=0..n-1: o_0=0, o_t = a*o_{t-1} + b (mod 2**48). The offset folded
    out of coordinate t so the box sits on the pure a^t * x term."""
    offs = [0]
    for _ in range(1, n):
        offs.append((A * offs[-1] + B) % MODULUS)
    return offs


def top_bits_bounds(observations: list[int], bits_per_call: int) -> list[tuple[int, int]]:
    """Per-coordinate half-open box [lo_t, hi_t) implied by a TOP_BITS leak.

    Coordinate t = s_{1+t} - o_t, and top-k bits == observations[t] pins
    s_{1+t} to [y*w, y*w + w) with w = 2**(48-k); subtracting o_t gives the box.
    """
    w = 1 << (48 - bits_per_call)
    offs = affine_offsets(len(observations))
    return [(y * w - offs[t], y * w - offs[t] + w) for t, y in enumerate(observations)]


def margin_top_bits(observations: list[int], bits_per_call: int) -> float:
    """Generalised round-off safety margin ||M.e||_inf for a TOP_BITS measurement.

    Matches recover.roundoff.margin on the (24, 3) cell and extends it to any
    (bits_per_call, num_observations). The <0.5 crossing is the round-off /
    enumeration boundary the sweep exists to draw.
    """
    n = len(observations)
    w = 1 << (48 - bits_per_call)
    half = 1 << (47 - bits_per_call)
    offs = affine_offsets(n)
    target = np.array([y * w + half - offs[t] for t, y in enumerate(observations)], dtype=float)
    z = _round_off_transform(n) @ target
    return float(np.max(np.abs(z - np.rint(z))))


def solve_box(
    bounds: list[tuple[int, int]],
    *,
    method: str = "auto",
    node_budget: int = 1_000_000,
) -> list[int]:
    """Given per-coordinate boxes [(lo0,hi0), ...], return the first coordinates
    (candidate x = s_1 states) of every lattice point consistent with all of them.

      * [] when no consistent point exists (garbage input),
      * one element when the box is tight (round-off regime),
      * several when the box admits collisions (starved / edge regime).

    method="roundoff" takes the single Babai round-off point (fast, no uniqueness
    guarantee); method="enumerate"/"auto" enumerates the box completely (and so
    can certify uniqueness vs. ambiguity). Raises recover.enumerate.BudgetExceeded
    if completeness cannot be certified within node_budget.
    """
    n = len(bounds)
    rows = reduced_basis(n)
    if method == "roundoff":
        centers = np.array([(lo + hi) / 2.0 for lo, hi in bounds], dtype=float)
        z = np.rint(_round_off_transform(n) @ centers)
        vec = [int(sum(int(z[i]) * rows[i][j] for i in range(n))) for j in range(n)]
        if all(lo <= vec[j] < hi for j, (lo, hi) in enumerate(bounds)):
            return [vec[0] & MASK]
        return []
    vecs = enumerate_box(rows, bounds, node_budget=node_budget)
    return sorted({v[0] & MASK for v in vecs})


def recover_pre_states_top_bits(
    observations: list[int],
    bits_per_call: int,
    *,
    node_budget: int = 1_000_000,
) -> list[int]:
    """Every pre-call state (s_0) consistent with a consecutive TOP_BITS leak.

    Complete: one element is a unique recovery; more than one flags genuine
    collisions (the leak does not distinguish those states). Each candidate is
    re-stepped through the LCG as a garbage guard before it is returned.
    """
    bounds = top_bits_bounds(observations, bits_per_call)
    shift = 48 - bits_per_call
    pre: set[int] = set()
    for x in solve_box(bounds, node_budget=node_budget):
        s = x
        ok = True
        for y in observations:
            if (s >> shift) != y:
                ok = False
                break
            s = step(s)
        if ok:
            pre.add(step_back(x))
    return sorted(pre)
