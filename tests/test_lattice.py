"""
Correctness gate for the general lattice solver (recover.lattice + recover.enumerate).

These tests need fpylll and are skipped without it -- the round-off path
(test_roundoff.py, test_lcg.py) is the fpylll-free core gate. The guardrails here:

  * fpylll reduction of build_basis(3) reproduces the hard-coded REDUCED_BASIS_3
    (ties the general path to the validated round-off constants);
  * the general path reproduces the published Randar vector;
  * the box enumeration is COMPLETE (truth is always in the returned set) and
    exposes genuine collisions at the recoverability edge (rule 8: ambiguity is a
    range, never silently collapsed);
  * the budget guard raises rather than returning a truncated set.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fpylll")

from prng_lattice_lab.config import LeakModel, LeakProfile
from prng_lattice_lab.generate.harness import make_trials
from prng_lattice_lab.lcg import step
from prng_lattice_lab.recover import lattice, roundoff
from prng_lattice_lab.recover.enumerate import BudgetExceeded, enumerate_box

ANCHOR = [7338710, 7668738, 5563335]


def _rows_up_to_sign(rows):
    out = set()
    for r in rows:
        t = tuple(int(x) for x in r)
        out.add(min(t, tuple(-x for x in t)))
    return out


def test_fpylll_reproduces_reference_basis():
    reduced = lattice.reduce(lattice.build_basis(3))
    assert _rows_up_to_sign(reduced) == _rows_up_to_sign(lattice.REDUCED_BASIS_3)


def test_general_margin_matches_roundoff_on_anchor():
    assert lattice.margin_top_bits(ANCHOR, 24) == pytest.approx(roundoff.margin(*ANCHOR))


def test_general_recovers_published_vector():
    pre = lattice.recover_pre_states_top_bits(ANCHOR, 24)
    assert pre == [roundoff.recover_pre_call_state(*ANCHOR)]
    # unique, and re-steps to the published internal state
    assert len(pre) == 1
    assert step(pre[0]) == 123123123123123


def test_overdetermined_cell_recovers_uniquely():
    # n*k = 64 >> 48: every trial should resolve to a single correct state.
    trials = make_trials(LeakProfile(model=LeakModel.TOP_BITS, bits_per_call=8, num_observations=8),
                         50, seed=1)
    for t in trials:
        pre = lattice.recover_pre_states_top_bits(t.observations, 8)
        assert pre == [t.true_pre_call_state]


def test_edge_enumeration_is_complete_and_reveals_collisions():
    # n*k = 48 (exactly determined): enumeration must ALWAYS contain the truth
    # (completeness) and at least some trials must be genuinely ambiguous.
    trials = make_trials(LeakProfile(model=LeakModel.TOP_BITS, bits_per_call=16, num_observations=3),
                         40, seed=0)
    ambiguous = 0
    for t in trials:
        pre = lattice.recover_pre_states_top_bits(t.observations, 16)
        assert t.true_pre_call_state in pre, "completeness violated: truth not enumerated"
        if len(pre) > 1:
            ambiguous += 1
    assert ambiguous > 0, "expected genuine collisions at n*k=48"


def test_solve_box_roundoff_matches_enumerate_when_unique():
    trials = make_trials(LeakProfile(model=LeakModel.TOP_BITS, bits_per_call=12, num_observations=6),
                         20, seed=2)
    for t in trials:
        bounds = lattice.top_bits_bounds(t.observations, 12)
        assert lattice.solve_box(bounds, method="roundoff") == lattice.solve_box(bounds)


def test_budget_guard_raises_instead_of_truncating():
    # A wide box (k=2) over few observations holds astronomically many points;
    # a tiny budget must raise, never return a truncated (and thus incomplete) set.
    bounds = lattice.top_bits_bounds([0, 0], 2)
    reduced = lattice.reduced_basis(2)
    with pytest.raises(BudgetExceeded):
        enumerate_box(reduced, bounds, node_budget=8)


def test_stride_one_is_the_consecutive_path():
    # call_stride=1 must collapse exactly to the validated consecutive machinery.
    assert lattice.strided_lcg(1) == (lattice.A, lattice.B)
    assert lattice.margin_top_bits(ANCHOR, 24, 1) == lattice.margin_top_bits(ANCHOR, 24)
    assert lattice.recover_pre_states_top_bits(ANCHOR, 24, call_stride=1) == \
        lattice.recover_pre_states_top_bits(ANCHOR, 24)


def test_strided_observations_recover():
    # Observing every stride-th nextFloat still recovers the pre-call state:
    # the lattice just uses a^stride as the per-step multiplier.
    for stride in (2, 3, 5):
        trials = make_trials(
            LeakProfile(model=LeakModel.TOP_BITS, bits_per_call=16,
                        num_observations=4, call_stride=stride), 25, seed=stride)
        for t in trials:
            pre = lattice.recover_pre_states_top_bits(t.observations, 16, call_stride=stride)
            assert t.true_pre_call_state in pre


def _noisy_rows(k, n, noise, count=12):
    trials = make_trials(
        LeakProfile(model=LeakModel.TOP_BITS, bits_per_call=k, num_observations=n,
                    noise=noise), count, seed=2)
    return [(lattice.recover_pre_states_top_bits(t.observations, k, noise=noise),
             t.true_pre_call_state) for t in trials]


def test_noise_keeps_completeness():
    # Under measurement noise the box widens; the true state must STILL be enumerated
    # (completeness), it just may no longer be unique.
    for c, truth in _noisy_rows(16, 3, noise=2):
        assert truth in c


def test_over_determination_buys_noise_tolerance():
    # A far over-determined cell recovers uniquely even under noise the edge can't take.
    for c, truth in _noisy_rows(24, 4, noise=6):
        assert c == [truth]                       # unique + correct
    # The n*k=48 edge, same noise, degrades to genuine ambiguity (wider box, collisions).
    edge = _noisy_rows(16, 3, noise=2)
    assert any(len(c) > 1 for c, _ in edge)
