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


def build_basis(n: int, multiplier: int = A) -> list[list[int]]:
    """Basis rows for the n-observation lattice at a given per-step multiplier.

    Row 0:       (1, g, g^2, ..., g^(n-1))   -- exact integer powers of the per-step
                 multiplier g (large by design; LLL shrinks them). Reducing them mod
                 m would give the same lattice, since coords 1..n-1 carry a full m on
                 the diagonal.
    Rows 1..n-1: m on the diagonal (the modular wrap on each later coordinate).

    `multiplier` is the LCG multiplier between consecutive OBSERVED states: a for
    consecutive calls, a^stride for strided observations (call_stride>1). Omits the
    affine offset o_t; callers fold it into the box (see top_bits_bounds).
    """
    first = [1]
    acc = 1
    for _ in range(1, n):
        acc *= multiplier
        first.append(acc)
    rows: list[list[int]] = [first]
    for i in range(1, n):
        row = [0] * n
        row[i] = MODULUS
        rows.append(row)
    return rows


def strided_lcg(call_stride: int) -> tuple[int, int]:
    """(multiplier, addend) of java.util.Random's LCG advanced `call_stride` steps:
    state -> a^s * state + b*(a^(s-1) + ... + a + 1)  (mod 2**48). For call_stride=1
    this is exactly (A, B), so every strided path collapses to the consecutive one."""
    if call_stride < 1:
        raise ValueError("call_stride must be >= 1")
    addend = 0
    for _ in range(call_stride):
        addend = (A * addend + B) % MODULUS
    return pow(A, call_stride, MODULUS), addend


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


# --- reduced-basis cache (the reduced basis depends on n and the call stride) ---
_REDUCED: dict[tuple[int, int], list[list[int]]] = {}
_MINV: dict[tuple[int, int], np.ndarray] = {}


def reduced_basis(n: int, call_stride: int = 1) -> list[list[int]]:
    """LLL-reduced basis rows for n observations at the given call stride (cached)."""
    key = (n, call_stride)
    if key not in _REDUCED:
        multiplier, _ = strided_lcg(call_stride)
        _REDUCED[key] = reduce(build_basis(n, multiplier))
    return _REDUCED[key]


def _round_off_transform(n: int, call_stride: int = 1) -> np.ndarray:
    """M = (R^T)^-1 for the reduced basis R: the change into reduced-basis
    coordinates used by both the margin and Babai round-off (z = M @ target)."""
    key = (n, call_stride)
    if key not in _MINV:
        R = np.array(reduced_basis(n, call_stride), dtype=float)
        _MINV[key] = np.linalg.inv(R.T)
    return _MINV[key]


def affine_offsets(n: int, call_stride: int = 1) -> list[int]:
    """o_t for t=0..n-1 between OBSERVED states: o_0=0, o_t = g*o_{t-1} + c (mod
    2**48), where (g, c) is the LCG advanced `call_stride` steps. The offset folded
    out of coordinate t so the box sits on the pure g^t * x term."""
    multiplier, addend = strided_lcg(call_stride)
    offs = [0]
    for _ in range(1, n):
        offs.append((multiplier * offs[-1] + addend) % MODULUS)
    return offs


def top_bits_bounds(observations: list[int], bits_per_call: int,
                    call_stride: int = 1) -> list[tuple[int, int]]:
    """Per-coordinate half-open box [lo_t, hi_t) implied by a TOP_BITS leak.

    Coordinate t = s_{1+t*stride} - o_t, and top-k bits == observations[t] pins that
    state to [y*w, y*w + w) with w = 2**(48-k); subtracting the strided offset o_t
    gives the box.
    """
    w = 1 << (48 - bits_per_call)
    offs = affine_offsets(len(observations), call_stride)
    return [(y * w - offs[t], y * w - offs[t] + w) for t, y in enumerate(observations)]


def margin_top_bits(observations: list[int], bits_per_call: int,
                    call_stride: int = 1) -> float:
    """Generalised round-off safety margin ||M.e||_inf for a TOP_BITS measurement.

    Matches recover.roundoff.margin on the (24, 3) consecutive cell and extends it to
    any (bits_per_call, num_observations, call_stride). The <0.5 crossing is the
    round-off / enumeration boundary the sweep exists to draw.
    """
    n = len(observations)
    w = 1 << (48 - bits_per_call)
    half = 1 << (47 - bits_per_call)
    offs = affine_offsets(n, call_stride)
    target = np.array([y * w + half - offs[t] for t, y in enumerate(observations)], dtype=float)
    z = _round_off_transform(n, call_stride) @ target
    return float(np.max(np.abs(z - np.rint(z))))


def solve_box(
    bounds: list[tuple[int, int]],
    *,
    call_stride: int = 1,
    method: str = "auto",
    node_budget: int = 1_000_000,
) -> list[int]:
    """Given per-coordinate boxes [(lo0,hi0), ...], return the first coordinates
    (candidate x = s_1 states) of every lattice point consistent with all of them.

      * [] when no consistent point exists (garbage input),
      * one element when the box is tight (round-off regime),
      * several when the box admits collisions (starved / edge regime).

    `call_stride` selects the per-step multiplier (a^stride) so strided observations
    reuse the same machinery. method="roundoff" takes the single Babai round-off
    point (fast, no uniqueness guarantee); method="enumerate"/"auto" enumerates the
    box completely (and so can certify uniqueness vs. ambiguity). Raises
    recover.enumerate.BudgetExceeded if completeness cannot be certified.
    """
    n = len(bounds)
    rows = reduced_basis(n, call_stride)
    if method == "roundoff":
        centers = np.array([(lo + hi) / 2.0 for lo, hi in bounds], dtype=float)
        z = np.rint(_round_off_transform(n, call_stride) @ centers)
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
    call_stride: int = 1,
    node_budget: int = 1_000_000,
) -> list[int]:
    """Every pre-call state (s_0) consistent with a TOP_BITS leak, consecutive
    (call_stride=1) or strided (>1, i.e. every stride-th call observed).

    Complete: one element is a unique recovery; more than one flags genuine
    collisions (the leak does not distinguish those states). Each candidate is
    re-stepped through the LCG as a garbage guard -- advancing `call_stride` steps
    between observations -- before it is returned. The pre-call state is always one
    step back from the first observed state, regardless of stride.
    """
    bounds = top_bits_bounds(observations, bits_per_call, call_stride)
    shift = 48 - bits_per_call
    pre: set[int] = set()
    for x in solve_box(bounds, call_stride=call_stride, node_budget=node_budget):
        s = x
        ok = True
        for i, y in enumerate(observations):
            if (s >> shift) != y:
                ok = False
                break
            if i < len(observations) - 1:
                for _ in range(call_stride):
                    s = step(s)
        if ok:
            pre.add(step_back(x))
    return sorted(pre)
