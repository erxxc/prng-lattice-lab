"""
Residue-class (nextInt(odd bound)) state recovery: the elttam / RandomStringUtils
leak. This is the HNP-shaped end of the family that the round-off box cannot
consume directly (characterize/leakage.py: ~k raw bits per call, 0 box-usable).

Why the box fails, and what works instead
  nextInt(b) for odd b returns v = h mod b where h = next(31) = s >> 17 is the top 31
  bits of the 48-bit state s. The constraint "h ≡ v (mod b)" with b coprime to 2**48
  is a union of ~2**31/b thin intervals, not one interval, so it is not a box.

  Split the state s = 2**17 * X + r into its low 17 bits r and high 31 bits X. The low
  bits evolve as their OWN LCG mod 2**17 (a is odd, so g**t * s + o_t mod 2**17 depends
  only on r), and their carry into the high half is a KNOWN integer once r is fixed.
  Fix r (2**17 slices, vectorised in numpy) and the high half obeys

      h_t ≡ g**t * X + D_t(r)   (mod 2**31),      D_t(r) = ((g**t * r + o_t) mod 2**48) >> 17

  so with h_t = v_t + b*q_t and beta = b**-1 mod 2**31, the unknown quotients satisfy

      q_t ≡ g**t * X' + E_t(r)  (mod 2**31),  X' = beta*X,  E_t = beta*(D_t - v_t) mod 2**31

  with q_t in [0, Q), Q = floor(2**31 / b) (every ACCEPTED draw has h < b*Q -- Java's
  rejection loop guarantees it). That is exactly the truncated-LCG box problem of
  recover/lattice.py, in a 31-bit lattice with the same multiplier vector, and the
  slice leaks log2(b) bits per call. Per slice the box is far over-determined near
  the 48-bit edge (n*log2 b ≈ 48 bits of information against a 31-bit unknown), so a
  CERTIFIED round-off resolves it:

      rho_i = sum_j |M_ij| * (Q/2)     (M = (R^T)^-1 for the LLL-reduced basis R)

  bounds the displacement of ANY in-box lattice point from the box centre in reduced
  coordinates, independent of slice and observation. Every integer vector within rho
  of round-off(centre) is checked, so the returned set is COMPLETE (the true state is
  always in it; collisions at the recoverability edge surface as >1 candidate), never a
  single silently-picked answer (rule 8). When rho >= 0.5 the per-coordinate integer
  ranges branch and the work grows; a row budget raises rather than truncates.

Assumption (disclosed): observations are from consecutive (or fixed-stride) ACCEPTED
draws. A rejected draw inside the window consumes an extra unobserved state step; the
solver then finds no consistent state (the sweep detects and reports these trials
separately). For the canonical bounds 2**k - 1 the rejection rate is <= 2**-16.

fpylll is needed once per (n, stride) to LLL-reduce the 31-bit basis (cached);
everything else is numpy. Without fpylll this raises lattice.ReductionUnavailable and
the sweep records the gap.

CITATIONS: elttam, "Cracking Java's RandomStringUtils" (the residue leak);
  Frieze-Hastad-Kannan-Lagarias-Shamir (1988), truncated LCG reconstruction;
  spawnmason/randar-explanation (the round-off framing reused per slice).
"""
from __future__ import annotations

import math

import numpy as np

from prng_lattice_lab.lcg import MASK, JavaRandom, step_back
from prng_lattice_lab.recover import lattice

MOD31 = 1 << 31
LOW_BITS = 17
SLICES = 1 << LOW_BITS
M31_MASK = np.uint64(MOD31 - 1)
MASK_U = np.uint64(MASK)


class RowBudgetExceeded(RuntimeError):
    """Certified enumeration would need more branch rows than allowed; raised instead
    of returning an incomplete candidate set."""


_BASIS: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}


def slice_basis(n: int, call_stride: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """(R, M) for the n-observation 31-bit lattice at the given stride: R the
    LLL-reduced rows (int64), M = (R^T)^-1 (float). Cached; needs fpylll once."""
    key = (n, call_stride)
    if key not in _BASIS:
        g, _ = lattice.strided_lcg(call_stride)
        first = [pow(g, t, MOD31) for t in range(n)]
        rows = [first] + [[MOD31 if j == i else 0 for j in range(n)] for i in range(1, n)]
        reduced = lattice.reduce(rows)                 # raises ReductionUnavailable w/o fpylll
        R = np.array(reduced, dtype=np.int64)
        M = np.linalg.inv(R.astype(float).T)
        _BASIS[key] = (R, M)
    return _BASIS[key]


def leaked_bits(bound: int, num_observations: int) -> float:
    """Information a run of nextInt(bound) observations carries: n * log2(bound)."""
    return num_observations * math.log2(bound)


def certified_radius(n: int, bound: int, call_stride: int = 1) -> float:
    """max_i rho_i: the worst-case displacement (reduced coordinates) of any in-box
    lattice point from the box centre. < 0.5 => one round-off candidate per slice;
    >= 0.5 => the certified enumeration branches. Observation-independent."""
    _, M = slice_basis(n, call_stride)
    Q = MOD31 // bound
    return float((np.abs(M) @ np.full(n, Q / 2.0)).max())


def recover_post_states_nextint_odd(
    observations: list[int],
    bound: int,
    *,
    call_stride: int = 1,
    row_budget: int = 20_000_000,
) -> tuple[list[int], float]:
    """Every state s_1 (the state right AFTER the first observed call) consistent with
    the observed nextInt(bound) values, assuming consecutive/strided accepted draws.

    Returns (candidates, realized_margin): `candidates` is COMPLETE (see module doc);
    `realized_margin` is max over the candidates' slices of ||z - round(z)||_inf, the
    same round-off safety quantity recover.lattice.margin_top_bits reports (how close
    the solved slice came to a rounding ambiguity). Raises RowBudgetExceeded if the
    certified enumeration would exceed `row_budget` rows.
    """
    if bound <= 1 or bound % 2 == 0:
        raise ValueError(f"bound must be an odd integer > 1; got {bound}")
    n = len(observations)
    if n < 1:
        return [], 0.0
    g, c = lattice.strided_lcg(call_stride)
    R, M = slice_basis(n, call_stride)
    Q = MOD31 // bound
    beta = pow(bound, -1, MOD31)

    # Slice sweep: run the pure low-part LCG from every r in [0, 2**17) and read off
    # the carry D_t = sigma_t >> 17 (uint64 multiplication wraps mod 2**64, and 2**48
    # divides 2**64, so `& MASK` is exact).
    r0 = np.arange(SLICES, dtype=np.uint64)
    sigma = r0.copy()
    E = np.empty((SLICES, n), dtype=np.int64)
    g_u, c_u, beta_u = np.uint64(g), np.uint64(c), np.uint64(beta)
    for t in range(n):
        D = (sigma >> np.uint64(LOW_BITS)) & M31_MASK
        dv = (D - np.uint64(observations[t] % MOD31)) & M31_MASK
        E[:, t] = ((beta_u * dv) & M31_MASK).astype(np.int64)
        sigma = (sigma * g_u + c_u) & MASK_U

    lo = -E                                    # per-slice box [lo, hi) on q_t - E_t
    hi = Q - E
    center = (lo + hi) / 2.0
    rho = np.abs(M) @ np.full(n, Q / 2.0) * (1.0 + 1e-9) + 1e-9
    z = center @ M.T                           # (SLICES, n) reduced-coordinate targets
    zlo = np.ceil(z - rho).astype(np.int64)
    zhi = np.floor(z + rho).astype(np.int64)

    # Certified enumeration: every integer vector in [zlo, zhi] per slice. Expand
    # rows only where a coordinate admits more than one integer.
    rows = np.arange(SLICES)
    zint = zlo
    for i in range(n):
        extra = zhi[rows, i] - zint[:, i]
        kmax = int(extra.max()) if len(extra) else 0
        if kmax <= 0:
            continue
        idx_parts, z_parts = [rows], [zint]
        for k in range(1, kmax + 1):
            sel = extra >= k
            zz = zint[sel].copy()
            zz[:, i] += k
            idx_parts.append(rows[sel])
            z_parts.append(zz)
        rows = np.concatenate(idx_parts)
        zint = np.concatenate(z_parts)
        if len(rows) > row_budget:
            raise RowBudgetExceeded(
                f"certified enumeration needs {len(rows)} rows > budget {row_budget} "
                f"(rho_max={float(rho.max()):.3f})")

    p = zint @ R                               # exact int64 lattice points
    ok = np.all((p >= lo[rows]) & (p < hi[rows]), axis=1)
    hits = np.nonzero(ok)[0]
    candidates: set[int] = set()
    margin = 0.0
    for j in hits:
        slice_r = int(rows[j])
        x_prime = int(p[j, 0]) % MOD31
        X = (bound * x_prime) % MOD31
        candidates.add((X << LOW_BITS) | slice_r)
        zs = z[slice_r]
        margin = max(margin, float(np.max(np.abs(zs - np.rint(zs)))))
    return sorted(candidates), margin


def recover_pre_states_nextint_odd(
    observations: list[int],
    bound: int,
    *,
    call_stride: int = 1,
    row_budget: int = 20_000_000,
) -> tuple[list[int], float]:
    """Every PRE-call state consistent with a run of nextInt(bound) observations,
    re-checked by replaying java.util.Random's real nextInt (rejection loop included)
    as the garbage guard. One element = unique recovery; several = genuine collisions
    (the recoverability edge); none = no consistent consecutive run (garbage, or a
    rejected draw shifted the window)."""
    post, margin = recover_post_states_nextint_odd(
        observations, bound, call_stride=call_stride, row_budget=row_budget)
    pre: list[int] = []
    for x in post:
        s0 = step_back(x)
        if replays(s0, observations, bound, call_stride):
            pre.append(s0)
    return sorted(set(pre)), margin


def replays(pre_state: int, observations: list[int], bound: int, call_stride: int = 1) -> bool:
    """Does java.util.Random at `pre_state` reproduce `observations` as its next
    nextInt(bound) outputs (every call_stride-th call)?"""
    gen = JavaRandom.from_internal_state(pre_state)
    for i, v in enumerate(observations):
        if gen.next_int(bound) != v:
            return False
        if i < len(observations) - 1:
            for _ in range(call_stride - 1):
                gen.next_int(bound)
    return True


def rejections_in_window(pre_state: int, num_observations: int, bound: int,
                         call_stride: int = 1) -> int:
    """How many draws Java's nextInt rejection loop discarded while producing the
    observed window from `pre_state` (ground truth known). >0 means the window is
    not a fixed-stride run of states, which the solver's model excludes -- the sweep
    reports such trials separately, never as a completeness failure."""
    gen = JavaRandom.from_internal_state(pre_state)
    calls = (num_observations - 1) * call_stride + 1
    rejected = 0
    for _ in range(calls):
        before = gen.seed
        gen.next_int(bound)
        # count state steps taken: each next(31) advances the state once
        steps = 0
        s = before
        while s != gen.seed:
            s = (s * lattice.A + lattice.B) & MASK
            steps += 1
            if steps > 64:  # pragma: no cover - defensive
                break
        rejected += steps - 1
    return rejected


# --- unknown-gap support: observations at arbitrary state-step positions -------------

_BASIS_POS: dict[tuple, tuple] = {}


def slice_basis_positions(positions: tuple[int, ...]) -> tuple:
    """(R, M) for observations whose next(31) draws sit at the given STATE-STEP positions
    (positions[0] is the base, 0). Generalises `slice_basis` from a uniform stride to
    arbitrary per-step gaps -- the multiplier from the base to position p is a^p. Cached
    by the position tuple; needs fpylll once per distinct pattern."""
    key = tuple(positions)
    if key not in _BASIS_POS:
        g, _ = lattice.strided_lcg(1)
        p0 = positions[0]
        n = len(positions)
        first = [pow(g, p - p0, MOD31) for p in positions]
        rows = [first] + [[MOD31 if j == i else 0 for j in range(n)] for i in range(1, n)]
        reduced = lattice.reduce(rows)
        import numpy as _np
        R = _np.array(reduced, dtype=_np.int64)
        M = _np.linalg.inv(R.astype(float).T)
        _BASIS_POS[key] = (R, M)
    return _BASIS_POS[key]


def recover_pre_states_at_positions(values, bound: int, positions: tuple[int, ...]):
    """Every pre-stream state (before the first observed draw) consistent with `values`
    observed at the given STATE-STEP `positions` (positions[0] == 0). A generalisation of
    `recover_post_states_nextint_odd` to non-uniform gaps: the low 17 bits are enumerated
    as 2^17 slices advanced by each gap, the 31-bit top half is a certified round-off in
    the position-dependent lattice. Returns sorted candidate pre-stream states (COMPLETE;
    a garbage guard is applied by the caller's replay). fpylll required."""
    import numpy as _np
    if bound <= 1 or bound % 2 == 0:
        raise ValueError(f"bound must be an odd integer > 1; got {bound}")
    n = len(values)
    if n < 1 or positions[0] != 0:
        raise ValueError("positions must be non-empty with positions[0] == 0")
    A_u = _np.uint64(lattice.A); B_u = _np.uint64(lattice.B); MK = _np.uint64(MASK)
    R, M = slice_basis_positions(tuple(positions))
    Q = MOD31 // bound
    beta = pow(bound, -1, MOD31); beta_u = _np.uint64(beta); m31 = _np.uint64(MOD31 - 1)
    r0 = _np.arange(SLICES, dtype=_np.uint64)
    sig = r0.copy(); prev = 0
    E = _np.empty((SLICES, n), dtype=_np.int64)
    for t, pos in enumerate(positions):
        for _ in range(pos - prev):
            sig = (sig * A_u + B_u) & MK
        prev = pos
        D = (sig >> _np.uint64(LOW_BITS)) & m31
        dv = (D - _np.uint64(values[t] % MOD31)) & m31
        E[:, t] = ((beta_u * dv) & m31).astype(_np.int64)
    lo = -E; hi = Q - E
    center = (lo + hi) / 2.0
    rho = _np.abs(M) @ _np.full(n, Q / 2.0) * (1.0 + 1e-9) + 1e-9
    z = center @ M.T
    zint = _np.rint(z).astype(_np.int64)
    pts = zint @ R
    ok = _np.all((pts >= lo) & (pts < hi), axis=1)
    out = set()
    for j in _np.nonzero(ok)[0]:
        x_prime = int(pts[j, 0]) % MOD31
        X = (bound * x_prime) % MOD31
        s_first = (X << LOW_BITS) | int(r0[j])   # state AFTER the first observed draw
        out.add(step_back(s_first))              # pre-stream state (before the first draw)
    return sorted(out)
