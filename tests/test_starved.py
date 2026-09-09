"""
Correctness gate for the bit-length (starved interval) solver (recover.starved).

Needs fpylll (per-trial LLL + enumeration); skipped without it. Guardrails:
  * the interval/information accounting is exact (bit-length L pins the state to
    [2^(L-1) w, 2^L w), worth k-L+1 bits);
  * feasibility is decided honestly before any work: <48 realized bits raises
    Underdetermined, an unaffordable enumeration raises Infeasible;
  * the subset plan never buys a 1-bit observation (it cannot pay for its dimension);
  * completeness: whenever a trial is attempted the true state is in the set, and
    it is unique in the over-determined regime (n=48 at k=8);
  * strided observations recover through the same path.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fpylll")

from prng_lattice_lab.config import LeakModel, LeakProfile
from prng_lattice_lab.generate.harness import make_trials
from prng_lattice_lab.lcg import JavaRandom
from prng_lattice_lab.recover import starved
from prng_lattice_lab.recover.enumerate import BudgetExceeded


def test_interval_and_information_accounting():
    w = 1 << 40                                   # k = 8
    assert starved.interval(0, 8) == (0, w)
    assert starved.interval(1, 8) == (w, 2 * w)
    assert starved.interval(8, 8) == (128 * w, 256 * w)
    assert starved.info_bits(8, 8) == pytest.approx(1.0)      # top bit set: 1 bit
    assert starved.info_bits(5, 8) == pytest.approx(4.0)      # k - L + 1
    assert starved.info_bits(0, 8) == pytest.approx(8.0)
    # the leak really is what java produces: replay agrees with the interval
    gen = JavaRandom.from_internal_state(123456789)
    pre = gen.seed
    L = gen.next_int(256).bit_length()
    lo, hi = starved.interval(L, 8)
    assert lo <= gen.seed < hi


def test_plan_rejects_underdetermined_and_never_buys_one_bit_observations():
    with pytest.raises(starved.Underdetermined):
        starved.plan_subset([8] * 16, 8)                      # 16 bits total
    plan = starved.plan_subset([8] * 40 + [4] * 12, 8)        # 12 obs worth 5 bits each
    assert set(plan.indices) == set(range(40, 52))            # only the informative ones
    assert plan.subset_bits == pytest.approx(60.0)
    assert plan.total_bits == pytest.approx(100.0)


def test_plan_reports_infeasible_when_only_one_bit_observations_reach_48():
    # 1-bit observations alone: 60 bits of information, none of it affordable.
    with pytest.raises(starved.Infeasible):
        starved.plan_subset([8] * 60, 8)


def _run(k, n, count, seed, stride=1):
    prof = LeakProfile(model=LeakModel.BIT_LENGTH, bits_per_call=k, num_observations=n,
                       call_stride=stride)
    return make_trials(prof, count, seed=seed)


def test_overdetermined_run_recovers_uniquely_and_completely():
    hits = 0
    for t in _run(8, 48, 12, seed=1):
        pre, plan, margin = starved.recover_pre_states_bit_length(t.observations, 8)
        assert t.true_pre_call_state in pre, "completeness violated"
        assert pre == [t.true_pre_call_state]
        assert plan.dim <= 40 and plan.subset_bits >= 48
        hits += 1
    assert hits == 12


def test_marginal_run_is_complete_when_attempted():
    attempted = skipped = 0
    for t in _run(8, 32, 12, seed=2):
        try:
            pre, plan, _ = starved.recover_pre_states_bit_length(t.observations, 8)
        except (starved.Underdetermined, starved.Infeasible):
            skipped += 1
            continue
        except BudgetExceeded:
            skipped += 1
            continue
        attempted += 1
        assert t.true_pre_call_state in pre
    assert attempted > 0                       # some marginal trials are affordable
    assert attempted + skipped == 12


def test_strided_observations_recover():
    for t in _run(8, 48, 6, seed=3, stride=2):
        pre, _, _ = starved.recover_pre_states_bit_length(t.observations, 8, call_stride=2)
        assert pre == [t.true_pre_call_state]


def test_replay_filter_rejects_wrong_state():
    t = _run(8, 48, 1, seed=4)[0]
    assert starved.replays(t.true_pre_call_state, t.observations, 8)
    assert not starved.replays(t.true_pre_call_state ^ 1, t.observations, 8)
