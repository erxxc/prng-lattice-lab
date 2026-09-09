"""
Starved-interval (bit-length) state recovery: the Minerva analogue. The leak is
only the bit-length L of nextInt(2**k) -- an INTERVAL on the state (so the box
machinery applies) that carries ~2 bits per call regardless of k. Half the
observations (L == k) carry a single bit; the informative ones (L < k) carry
k - L + 1 bits each, ~3 on average.

Method: informative-subset lattice + complete box enumeration + replay filter.
  1. Each observation pins the state s_{1+t*stride} to [2**(L-1)*w, 2**L*w) with
     w = 2**(48-k) (or [0, w) for L == 0). Information = 48 - log2(width).
  2. Every observation costs one lattice dimension, and complete enumeration inside
     a box's bounding ball visits ~2**(1.05*d) points per in-box point (the
     ball/cube volume ratio). So a 1-bit observation never pays for its dimension;
     the solver keeps only observations worth >= 2 bits, most informative first,
     until the predicted enumeration cost is negligible or `max_dim` is reached.
  3. The chosen observations sit at irregular indices, so the lattice generalises
     recover.lattice.build_basis to arbitrary step gaps (multiplier a**gap, its own
     affine offset), and columns are scaled by powers of two so the anisotropic box
     becomes a cube for the enumeration ball.
  4. recover.enumerate.enumerate_box returns EVERY lattice point in the subset box
     (complete). Each candidate is stepped back to the pre-call state and replayed
     against ALL observations -- so the final set is complete for the full leak, not
     just the subset (any state consistent with all is consistent with the subset).

Feasibility is decided per trial, honestly, before any work:
  * realized leak < 48 bits  -> UNDERDETERMINED (no unique state can exist);
  * predicted enumeration cost above budget -> INFEASIBLE within budget (reported as
    such, not attempted, never guessed);
  * otherwise the enumeration is run and may still raise BudgetExceeded.

Needs fpylll (LLL per trial -- the subset pattern differs trial to trial -- and the
enumeration); without it the sweep records the gap.

CITATIONS: Minerva (Jancar et al. 2020) for the bit-length leak class;
  Frieze et al. (1988) truncated LCG lattice; the box enumeration of
  recover/enumerate.py (mjtb49/LattiCG framing).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from prng_lattice_lab.lcg import A, B, MASK, JavaRandom, step_back
from prng_lattice_lab.recover import lattice
from prng_lattice_lab.recover.enumerate import enumerate_box

MODULUS = MASK + 1
SECRET_BITS = 48
BALL_COST_PER_DIM = 1.047     # log2 of the ball/cube volume ratio per dimension, d large
MIN_USEFUL_BITS = 2.0         # an observation must beat its dimension cost to be worth adding


class Infeasible(RuntimeError):
    """Predicted enumeration cost exceeds the budget; the trial is reported as
    infeasible-within-budget rather than attempted blindly."""


class Underdetermined(RuntimeError):
    """Realized leak < 48 bits: no unique state exists; nothing to enumerate."""


def interval(bit_length: int, bits_per_call: int) -> tuple[int, int]:
    """Half-open state interval implied by nextInt(2**k).bit_length() == L."""
    w = 1 << (SECRET_BITS - bits_per_call)
    if bit_length <= 0:
        return (0, w)
    return ((1 << (bit_length - 1)) * w, (1 << bit_length) * w)


def info_bits(bit_length: int, bits_per_call: int) -> float:
    """Bits of information one bit-length observation carries about the state."""
    lo, hi = interval(bit_length, bits_per_call)
    return SECRET_BITS - math.log2(hi - lo)


def leaked_bits(observations: list[int], bits_per_call: int) -> float:
    """Realized information in a whole observation run (sum over calls)."""
    return sum(info_bits(L, bits_per_call) for L in observations)


@dataclass(frozen=True)
class SubsetPlan:
    indices: tuple[int, ...]          # observation indices used in the lattice (sorted)
    subset_bits: float                # information carried by the subset
    total_bits: float                 # information carried by ALL observations
    predicted_log2_cost: float        # log2 of expected enumeration candidates

    @property
    def dim(self) -> int:
        return len(self.indices)


def plan_subset(observations: list[int], bits_per_call: int, *, max_dim: int = 40,
                node_budget: int = 1_000_000, target_log2_cost: float = 2.0) -> SubsetPlan:
    """Pick the observation subset for the lattice (see module doc). Raises
    Underdetermined if all observations together carry < 48 bits, Infeasible if even
    the best subset's predicted enumeration cost exceeds `node_budget`/2."""
    k = bits_per_call
    total = leaked_bits(observations, k)
    if total < SECRET_BITS:
        raise Underdetermined(f"realized leak {total:.1f} bits < {SECRET_BITS}")
    ranked = sorted(((info_bits(L, k), t) for t, L in enumerate(observations)),
                    key=lambda x: (-x[0], x[1]))
    chosen: list[int] = []
    acc = 0.0
    best: SubsetPlan | None = None
    for inf, t in ranked:
        if inf < MIN_USEFUL_BITS or len(chosen) >= max_dim:
            break
        chosen.append(t)
        acc += inf
        cost = BALL_COST_PER_DIM * len(chosen) - (acc - SECRET_BITS)
        plan = SubsetPlan(tuple(sorted(chosen)), acc, total, cost)
        if best is None or cost < best.predicted_log2_cost:
            best = plan
        if acc >= SECRET_BITS and cost <= target_log2_cost:
            break
    limit = math.log2(node_budget) - 1.0
    if best is None or best.subset_bits < SECRET_BITS:
        raise Infeasible(
            f"observations worth >= {MIN_USEFUL_BITS:g} bits carry only "
            f"{best.subset_bits if best else 0:.1f} bits within max_dim={max_dim} "
            f"(< {SECRET_BITS}); 1-bit observations cannot pay for their dimension")
    if best.predicted_log2_cost > limit:
        raise Infeasible(
            f"best subset dim={best.dim} bits={best.subset_bits:.1f} predicts "
            f"2^{best.predicted_log2_cost:.1f} enumeration candidates > budget 2^{limit:.1f}")
    return best


def _lcg_power(steps: int) -> tuple[int, int]:
    """(a**steps, offset) of the LCG advanced `steps` times (steps >= 0)."""
    g, c = 1, 0
    for _ in range(steps):
        c = (A * c + B) % MODULUS
        g = (g * A) % MODULUS
    return g, c


def recover_pre_states_bit_length(
    observations: list[int],
    bits_per_call: int,
    *,
    call_stride: int = 1,
    max_dim: int = 40,
    node_budget: int = 1_000_000,
) -> tuple[list[int], SubsetPlan, float]:
    """Every pre-call state consistent with a run of nextInt(2**k) bit-length
    observations (consecutive or strided), COMPLETE for the whole run.

    Returns (candidates, plan, margin): `plan` records which observations formed the
    lattice and the realized information; `margin` is ||z - round(z)||_inf of the
    subset box centre in reduced coordinates (the usual round-off safety figure).
    Raises Underdetermined / Infeasible (decided before any lattice work) or
    recover.enumerate.BudgetExceeded (completeness not certifiable).
    """
    k = bits_per_call
    plan = plan_subset(observations, k, max_dim=max_dim, node_budget=node_budget)
    idx = plan.indices
    m = len(idx)
    base = idx[0]
    mults, offs = zip(*[_lcg_power((j - base) * call_stride) for j in idx])
    rows = [list(mults)] + [[MODULUS if jj == i else 0 for jj in range(m)] for i in range(1, m)]
    bounds = []
    for j in range(m):
        lo, hi = interval(observations[idx[j]], k)
        bounds.append((lo - offs[j], hi - offs[j]))
    widths = [hi - lo for lo, hi in bounds]
    W = max(widths)
    scales = [W // w for w in widths]                    # powers of two: exact
    srows = [[r[j] * scales[j] for j in range(m)] for r in rows]
    sbounds = [(lo * scales[j], hi * scales[j]) for j, (lo, hi) in enumerate(bounds)]
    R = lattice.reduce(srows)
    Rf = np.array(R, dtype=float)
    M = np.linalg.inv(Rf.T)
    center = np.array([(lo + hi) / 2.0 for lo, hi in sbounds])
    z = M @ center
    margin = float(np.max(np.abs(z - np.rint(z))))
    vecs = enumerate_box(R, sbounds, node_budget=node_budget)
    firsts = sorted({(v[0] // scales[0]) & MASK for v in vecs})
    pre: set[int] = set()
    back = base * call_stride + 1
    for x in firsts:
        s = x
        for _ in range(back):
            s = step_back(s)
        if replays(s, observations, k, call_stride):
            pre.add(s)
    return sorted(pre), plan, margin


def replays(pre_state: int, observations: list[int], bits_per_call: int,
            call_stride: int = 1) -> bool:
    """Does java.util.Random at `pre_state` reproduce the observed bit-lengths of
    nextInt(2**k) (every call_stride-th call)?"""
    gen = JavaRandom.from_internal_state(pre_state)
    bound = 1 << bits_per_call
    for i, L in enumerate(observations):
        if gen.next_int(bound).bit_length() != L:
            return False
        if i < len(observations) - 1:
            for _ in range(call_stride - 1):
                gen.next_int(bound)
    return True
