"""
Correctness gate for the nextInt(odd bound) residue-class solver (recover.residue).

Needs fpylll (one cached LLL of the 31-bit basis); skipped without it. Guardrails:
  * completeness: over many trials at several cells the true pre-call state is ALWAYS
    in the returned set (never silently dropped);
  * uniqueness where the leak is over-determined (n*log2 b >= ~56): exactly one state;
  * genuine collisions surface at the 48-bit edge as >1 candidate (rule 8), never a
    single silently-picked answer;
  * the leak model is honoured: strided observations recover; the rejection-loop
    detector counts exactly the extra state steps Java's nextInt took;
  * garbage input (not a consecutive run) yields no candidate;
  * the row budget raises rather than truncating.
"""
from __future__ import annotations

import random

import pytest

pytest.importorskip("fpylll")

from prng_lattice_lab.config import LeakModel, LeakProfile
from prng_lattice_lab.generate.harness import make_trials
from prng_lattice_lab.lcg import JavaRandom
from prng_lattice_lab.recover import residue


def _cell(bits, n, count, seed, stride=1):
    prof = LeakProfile(model=LeakModel.NEXTINT_ODD, bits_per_call=bits,
                       num_observations=n, call_stride=stride)
    return prof.effective_bound(), make_trials(prof, count, seed=seed)


@pytest.mark.parametrize("bits,n", [(8, 8), (12, 6), (16, 4), (24, 3)])
def test_overdetermined_cells_recover_uniquely(bits, n):
    bound, trials = _cell(bits, n, 30, seed=bits)
    for t in trials:
        pre, margin = residue.recover_pre_states_nextint_odd(t.observations, bound)
        assert pre == [t.true_pre_call_state]
        assert 0.0 <= margin < 0.5           # certified round-off regime


@pytest.mark.parametrize("bits,n", [(8, 6), (12, 4), (16, 3), (24, 2)])
def test_edge_is_complete_and_reveals_collisions(bits, n):
    # n*log2(2^k - 1) ~= 48: the truth must ALWAYS be enumerated, and some trials
    # must be genuinely ambiguous (distinct states with identical nextInt outputs).
    bound, trials = _cell(bits, n, 40, seed=100 + bits)
    ambiguous = 0
    for t in trials:
        pre, _ = residue.recover_pre_states_nextint_odd(t.observations, bound)
        assert t.true_pre_call_state in pre, "completeness violated"
        ambiguous += len(pre) > 1
    assert ambiguous > 0


def test_leaked_bits_and_certified_radius():
    assert residue.leaked_bits(255, 6) == pytest.approx(6 * 7.994, abs=0.01)
    # the radius is observation-independent and tightens with over-determination
    assert residue.certified_radius(8, 255) < residue.certified_radius(6, 255) < 0.5


def test_strided_observations_recover():
    for stride in (2, 3):
        bound, trials = _cell(8, 8, 15, seed=stride, stride=stride)
        for t in trials:
            pre, _ = residue.recover_pre_states_nextint_odd(t.observations, bound, call_stride=stride)
            assert pre == [t.true_pre_call_state]


def test_non_canonical_odd_bound_recovers():
    # RandomStringUtils-style small odd bound (not 2^k - 1); ~6.5 bits/call.
    bound = 91
    rng = random.Random(5)
    for _ in range(10):
        state = rng.getrandbits(48)
        gen = JavaRandom.from_internal_state(state)
        obs = [gen.next_int(bound) for _ in range(10)]
        if residue.rejections_in_window(state, 10, bound):
            continue                                        # outside the model, by design
        pre, _ = residue.recover_pre_states_nextint_odd(obs, bound)
        assert pre == [state]


def test_rejection_counter_matches_java_loop():
    # Construct states whose next(31) is in nextInt's rejection zone for a bound
    # just under 2^31 (rejection probability ~1/2), and check the counter sees them.
    bound = (1 << 30) + 1                                     # odd, just over 2^30: ~50% rejection
    rng = random.Random(11)
    seen_rejection = False
    for _ in range(200):
        state = rng.getrandbits(48)
        gen = JavaRandom.from_internal_state(state)
        before = gen.seed
        gen.next_int(bound)
        steps = 0
        s = before
        while s != gen.seed:
            s = (s * residue.lattice.A + residue.lattice.B) & residue.MASK
            steps += 1
        assert residue.rejections_in_window(state, 1, bound) == steps - 1
        seen_rejection |= steps > 1
    assert seen_rejection


def test_garbage_window_has_no_candidate():
    pre, _ = residue.recover_pre_states_nextint_odd([1, 2, 3, 4, 5, 6, 7, 8], 255)
    assert pre == []


def test_even_bound_is_rejected():
    with pytest.raises(ValueError):
        residue.recover_pre_states_nextint_odd([1, 2, 3], 256)


def test_row_budget_raises_instead_of_truncating():
    bound, trials = _cell(4, 16, 1, seed=0)                  # rho > 1: branching needed
    with pytest.raises(residue.RowBudgetExceeded):
        residue.recover_post_states_nextint_odd(trials[0].observations, bound, row_budget=200_000)
