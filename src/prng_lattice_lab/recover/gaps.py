"""
Unknown-gap recovery: recover state when the observed tokens sit at UNKNOWN positions in
the underlying draw stream, because some draws were consumed but never observed.

This is the shape of every rejection-sampling idiom:
  * Java `nextInt(bound)` for a non-power-of-two bound: the modulo-rejection loop discards
    a draw at an unknown position (rare -- ~2^-16 for bounds like 2^k-1).
  * Apache Commons `RandomStringUtils`: a character filter (letters/digits only over a
    wider range) redraws when a candidate character is out of class -- the elttam case.
    The observer sees the accepted characters; between them are unknown rejected draws.

The current `recover/residue` solver assumes a FIXED stride (consecutive accepted draws)
and EXCLUDES any window that contained a rejection. This wrapper SOLVES through the
rejections instead, so the RandomStringUtils demonstration matches the real library.

Method -- anchor + ordered gap search + replay verification:
  1. The base solver needs a short window (~8 observations for an 8-bit odd bound) to pin
     the state. Rejections are usually rare, so ENUMERATE gap patterns for that anchor
     window in order of FEWEST total extra state-steps first (all-consecutive first).
  2. For each pattern, positions are known, so the base solver runs at those exact
     positions (a certified lattice solve).
  3. Each candidate state is REPLAYED through the real generator (the base solver's own
     faithful rejection model), which reproduces the whole observed sequence if and only
     if the state is right -- and in doing so DISCOVERS the true full gap structure for
     free. A candidate that replays all observations is verified.

Gaps are measured in STATE STEPS (next(31) calls), so a `nextInt` internal modulo-reject
and a character-filter reject are the SAME kind of gap -- both are extra state steps
between observed values. That unifies the two rejection mechanisms in one search.

Honesty (rules 7/8):
  * The search is bounded. When rejections are frequent (a small accept set) the pattern
    count grows; past `budget` the wrapper reports `budget_exhausted` and NO recovery,
    an explicit INFEASIBLE outcome, never a guess.
  * Every returned state is replay-verified against ALL observations; more than one
    verified state is reported as ambiguity, never collapsed.

Scope. This anchor technique fits the LATTICE solvers (`recover/residue`), whose state
recovery needs only a small window. It does NOT fit the GF(2) MT19937 solver
(`recover/mt19937_gf2`), which needs ~700 observations for full rank: an anchor is too
large to gap-enumerate, so Python's rejection-sampled idioms (`random.choice`,
`randrange`) are out of scope for THIS technique and would need a different approach
(SAT / meet-in-the-middle). That boundary is disclosed, not silently unhandled.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Callable, Protocol

from prng_lattice_lab.lcg import JavaRandom
from prng_lattice_lab.recover import residue


class GapSolver(Protocol):
    """A base solver the unknown-gap wrapper drives. `solve_at_positions` recovers
    candidate pre-stream states for observations at known STATE-STEP positions;
    `replay` reproduces the accepted-value stream from a candidate (faithful rejection),
    for verification."""

    def solve_at_positions(self, values: list[int], positions: tuple[int, ...]) -> list[int]: ...

    def replay(self, pre_state: int, count: int) -> list[int] | None: ...


@dataclass(frozen=True)
class GapRecovery:
    states: list[int]              # replay-verified pre-stream states (complete within budget)
    unique: bool                   # exactly one verified state
    gap_pattern: tuple[int, ...] | None   # anchor state-step gaps of the unique state (else None)
    patterns_tried: int
    budget_exhausted: bool         # True + no state => INFEASIBLE within budget (disclosed)

    @property
    def recovered(self) -> bool:
        return self.unique


def _gap_patterns(width: int, max_gap: int, max_rejects: int):
    """Yield gap tuples of length `width-1`, each gap in [1, max_gap], ordered by total
    extra state-steps ascending (the all-consecutive pattern first). `max_rejects` caps
    the total extra steps considered."""
    slots = width - 1
    if slots == 0:
        yield ()
        return
    for extra in range(max_rejects + 1):
        for combo in itertools.product(range(max_gap), repeat=slots):
            if sum(combo) == extra:
                yield tuple(1 + c for c in combo)


def recover_unknown_gaps(
    observed: list[int],
    solver: GapSolver,
    *,
    anchor: int = 8,
    max_gap: int = 4,
    max_rejects: int = 8,
    budget: int = 4000,
    stop_on_first: bool = True,
) -> GapRecovery:
    """Recover a pre-stream state from `observed` accepted values whose stream positions
    are unknown (see module doc). `anchor` observations pin the state; gap patterns are
    tried in fewest-rejections order up to `budget`, each candidate replay-verified
    against ALL observations."""
    width = min(anchor, len(observed))
    window = observed[:width]
    verified: set[int] = set()
    verified_gap: dict[int, tuple[int, ...]] = {}
    tried = 0
    for gaps in _gap_patterns(width, max_gap, max_rejects):
        if tried >= budget:
            return GapRecovery(sorted(verified), len(verified) == 1,
                               verified_gap.get(next(iter(verified))) if len(verified) == 1 else None,
                               tried, budget_exhausted=True)
        tried += 1
        positions = [0]
        for g in gaps:
            positions.append(positions[-1] + g)
        try:
            candidates = solver.solve_at_positions(window, tuple(positions))
        except Exception:
            continue
        for s in candidates:
            if s in verified:
                continue
            replayed = solver.replay(s, len(observed))
            if replayed == observed:
                verified.add(s)
                verified_gap[s] = gaps
        if verified and stop_on_first:
            break
    unique = len(verified) == 1
    gp = verified_gap[next(iter(verified))] if unique else None
    return GapRecovery(sorted(verified), unique, gp, tried, budget_exhausted=False)


class ResidueGapSolver:
    """Unknown-gap solver for a filtered `nextInt(bound)` stream (odd bound): the
    RandomStringUtils character-filter idiom, and Java's own modulo-rejection.

    `bound` is the odd nextInt bound; `accept(value)` is True for an observed (kept)
    draw -- e.g. `lambda v: v < accept_count` for a character-class filter over the first
    `accept_count` code points, or `lambda v: True` for a pure modulo-rejection stream.
    The observed values are the ACCEPTED nextInt(bound) outputs.
    """

    def __init__(self, bound: int, accept: Callable[[int], bool] = lambda v: True):
        if bound <= 1 or bound % 2 == 0:
            raise ValueError("bound must be an odd integer > 1")
        self.bound = bound
        self.accept = accept

    def solve_at_positions(self, values: list[int], positions: tuple[int, ...]) -> list[int]:
        return residue.recover_pre_states_at_positions(values, self.bound, positions)

    def replay(self, pre_state: int, count: int, max_draws: int = 1_000_000) -> list[int] | None:
        gen = JavaRandom.from_internal_state(pre_state)
        out: list[int] = []
        for _ in range(max_draws):
            v = gen.next_int(self.bound)
            if self.accept(v):
                out.append(v)
                if len(out) == count:
                    return out
        return None
