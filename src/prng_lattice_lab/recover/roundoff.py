"""
Babai round-off recovery for the 3-consecutive-nextFloat case (the Randar core).

This is the FAST path: when total leaked bits comfortably exceed the 48-bit
secret (three nextFloat calls leak 3*24 = 72 bits), the LLL-reduced lattice is
so well-conditioned that recovery is a single change-of-basis + round-to-nearest,
with no enumeration. Runs in ~microseconds.

The nine change-of-basis constants and the three first-components below are, for
java.util.Random's specific (a, b, m), the entries of

    Inverse[Transpose[LatticeReduce[{{1, a, a^2}, {0, m, 0}, {0, 0, m}}]]]

and the first coordinates of the three LLL-reduced basis vectors, respectively.
They are hard-coded here (ported verbatim from spawnmason/randar-explanation) so
this path has zero dependency on a lattice library. recover/lattice.py holds the
same reduced basis symbolically and is what generalises to other call counts /
leak widths via fpylll.

CITATION: spawnmason/randar-explanation (leijurv, n0pf0x et al., 2024),
sections "Lattice reduction" and "Worked example".

SEMANTICS (important, and easy to get wrong):
`crack_three_floats_msb` returns the internal `seed` field state S such that
S >> 24 == m1 -- i.e. the state IMMEDIATELY AFTER the call that produced m1
(java.util.Random steps before reading). To obtain the state that existed
BEFORE the three calls -- the one you would step backwards to reach a reseed
event -- apply lcg.step_back(S) once. `recover_pre_call_state` does this for you.
"""
from __future__ import annotations

import math

from prng_lattice_lab.lcg import MASK, A, B, step_back

# First components of the three LLL-reduced basis vectors.
_U0 = 1270789291
_U1 = -2355713969
_U2 = -3756485696

# Rows of (B'^T)^-1 -- the change of basis into reduced-basis coordinates.
_M = (
    (9.555378710501827e-11, -2.5481838861196593e-10, 1.184083942007419e-10),
    (-1.2602185961441137e-10, 6.980727107475104e-11, 1.5362999761237006e-10),
    (-1.5485213111787743e-10, -1.2997958265259513e-10, -5.6285642813236336e-11),
)

# Cube-centre offsets: 2**23 (half a 24-bit ULP) minus the affine offset o=(0,b,a*b+b).
_OFF_X = 8388608           # 2**23
_OFF_Y = 8388597           # 2**23 - b
_OFF_Z = -277355554490     # 2**23 - (a*b + b)


def _round_half_up(x: float) -> int:
    # Java Math.round is half-up; fractional parts here are ~0.002 or ~0.998 so
    # the tie rule never actually bites, but we match Java to stay faithful.
    return math.floor(x + 0.5)


def crack_three_floats_msb(m1: int, m2: int, m3: int) -> int | None:
    """Recover java.util.Random state from the top 24 bits of 3 consecutive
    nextFloat outputs. Returns the post-first-step internal state, or None if the
    inputs are inconsistent with any LCG run (garbage-in guard -- e.g. an item
    that was dropped from an inventory rather than mined).
    """
    cx = (m1 << 24) + _OFF_X
    cy = (m2 << 24) + _OFF_Y
    cz = (m3 << 24) + _OFF_Z
    c0 = _M[0][0] * cx + _M[0][1] * cy + _M[0][2] * cz
    c1 = _M[1][0] * cx + _M[1][1] * cy + _M[1][2] * cz
    c2 = _M[2][0] * cx + _M[2][1] * cy + _M[2][2] * cz
    seed = (
        _round_half_up(c0) * _U0
        + _round_half_up(c1) * _U1
        + _round_half_up(c2) * _U2
    ) & MASK
    nxt = (seed * A + B) & MASK
    nxtnxt = (nxt * A + B) & MASK
    if ((seed >> 24) ^ m1) | ((nxt >> 24) ^ m2) | ((nxtnxt >> 24) ^ m3):
        return None
    return seed


def recover_pre_call_state(m1: int, m2: int, m3: int) -> int | None:
    """As crack_three_floats_msb, but returns the state BEFORE the three calls
    (one step_back applied). This is the state to feed into backward-stepping /
    reseed search (see sweep + the repoauditor adapter's demonstration path).
    """
    s = crack_three_floats_msb(m1, m2, m3)
    return None if s is None else step_back(s)


def margin(m1: int, m2: int, m3: int) -> float:
    """The rounding safety margin ||M.e||_inf for this measurement.

    e is the offset of the true point from the box centre (bounded by the box
    half-width 2**23). If this is comfortably < 0.5, round-off is guaranteed to
    land on the correct lattice point. Characterise/margin.py sweeps this as leak
    width shrinks -- the whole point of the experiment is to watch it cross 0.5.
    Here (3x24-bit leak) it sits around 2**-9 ~= 0.002.
    """
    cx = (m1 << 24) + _OFF_X
    cy = (m2 << 24) + _OFF_Y
    cz = (m3 << 24) + _OFF_Z
    coeffs = (
        _M[0][0] * cx + _M[0][1] * cy + _M[0][2] * cz,
        _M[1][0] * cx + _M[1][1] * cy + _M[1][2] * cz,
        _M[2][0] * cx + _M[2][1] * cy + _M[2][2] * cz,
    )
    return max(abs(c - round(c)) for c in coeffs)
