"""
Unknown-gap recovery (recover/gaps): recover java.util.Random state through
RandomStringUtils-style character-filter rejections by anchor + ordered gap search +
replay verification. Needs fpylll (the residue base solver); skipped without it.
"""
from __future__ import annotations

import random

import pytest

pytest.importorskip("fpylll")

from prng_lattice_lab.lcg import JavaRandom
from prng_lattice_lab.recover import residue
from prng_lattice_lab.recover.gaps import GapRecovery, ResidueGapSolver, recover_unknown_gaps


def _stream_and_truth(state, bound, accept, n):
    """(observed n kept values, pre-first-kept-draw state)."""
    gen = JavaRandom.from_internal_state(state)
    out, pre = [], None
    while len(out) < n:
        before = gen.seed
        v = gen.next_int(bound)
        if accept(v):
            if pre is None:
                pre = before
            out.append(v)
    return out, pre


def test_positions_solver_matches_consecutive_and_handles_gaps():
    st = random.Random(1).getrandbits(48)
    gen = JavaRandom.from_internal_state(st)
    seq = [gen.next_int(255) for _ in range(9)]
    assert st in residue.recover_pre_states_at_positions(seq[:8], 255, tuple(range(8)))
    # drop the draw at index 4 -> a gap of 2 there; still recovers the pre-stream state
    obs = seq[:4] + seq[5:9]
    assert st in residue.recover_pre_states_at_positions(obs, 255, (0, 1, 2, 3, 5, 6, 7, 8))


@pytest.mark.parametrize("accept_count,label", [(254, "rare"), (240, "light"), (200, "moderate")])
def test_recovers_through_character_rejections(accept_count, label):
    bound = 255
    accept = lambda v: v < accept_count
    solver = ResidueGapSolver(bound, accept)
    rng = random.Random(3)
    for _ in range(6):
        st = rng.getrandbits(48)
        allkept, pre = _stream_and_truth(st, bound, accept, 16)
        rec = recover_unknown_gaps(allkept[:10], solver, anchor=8, max_gap=4, max_rejects=8)
        assert isinstance(rec, GapRecovery)
        assert rec.unique and pre in rec.states, f"{label}: not uniquely recovered"
        # the recovered state replays the FULL kept stream (predicts held-out values)
        assert solver.replay(rec.states[0], 16) == allkept


def test_all_consecutive_is_the_first_pattern_tried():
    # with no rejections the very first (all-ones) pattern verifies -> patterns_tried == 1
    bound = 255
    solver = ResidueGapSolver(bound, lambda v: True)   # accept everything: never rejects
    st = random.Random(5).getrandbits(48)
    gen = JavaRandom.from_internal_state(st)
    obs = [gen.next_int(bound) for _ in range(10)]
    rec = recover_unknown_gaps(obs, solver, anchor=8)
    assert rec.unique and rec.patterns_tried == 1 and rec.gap_pattern == (1, 1, 1, 1, 1, 1, 1)


def test_high_rejection_reports_infeasible_not_a_guess():
    # a tiny accept set with a tight budget: the search is capped and reports infeasible,
    # never a fabricated state (rule 8).
    bound = 255
    accept = lambda v: v < 96            # ~62% rejection
    solver = ResidueGapSolver(bound, accept)
    st = random.Random(9).getrandbits(48)
    allkept, _ = _stream_and_truth(st, bound, accept, 10)
    rec = recover_unknown_gaps(allkept, solver, anchor=8, max_gap=6, max_rejects=12, budget=200)
    if not rec.states:
        assert rec.budget_exhausted            # honestly disclosed, no guess
    else:
        assert all(solver.replay(s, len(allkept)) == allkept for s in rec.states)


def test_even_bound_rejected():
    with pytest.raises(ValueError):
        ResidueGapSolver(256)
