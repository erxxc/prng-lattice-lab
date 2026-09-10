"""
GF(2) MT19937 state recovery from TRUNCATED outputs (recover/mt19937_gf2). CPython's own
random is the oracle: the symbolic engine must match it bit-for-bit, and recovery must
reproduce/predict its outputs. No fpylll, no numpy -- pure GF(2) linear algebra.
"""
from __future__ import annotations

import random

import pytest

from prng_lattice_lab.recover import mt19937_gf2 as G


def _true_state_int(r: random.Random) -> int:
    mt = r.getstate()[1][:G.N]
    x = 0
    for i in range(G.N):
        x |= mt[i] << (i * G.WORD_BITS)
    return x


def test_symbolic_engine_matches_cpython_bit_for_bit():
    r = random.Random(0)
    x = _true_state_int(r)
    sym = G.SymbolicMT(index=r.getstate()[1][G.N])
    for _ in range(1000):
        vec_word = sym.next_word()
        got = sum((bin(vec_word[j] & x).count("1") & 1) << j for j in range(G.WORD_BITS))
        assert got == r.getrandbits(32)


def test_random_recovery_is_unique_and_predicts():
    victim = random.Random(20260910)
    doubles = [victim.random() for _ in range(G.calls_for_full_rank_random())]
    rec = G.recover_from_random(doubles)
    assert rec.rank == G.EFFECTIVE_BITS and rec.unique
    words, certain = rec.predict_next_words(8)
    assert certain
    pred = [((words[2 * k] >> 5) * (1 << 26) + (words[2 * k + 1] >> 6)) / (1 << 53) for k in range(4)]
    assert pred == [victim.random() for _ in range(4)]


def test_recovered_state_clones_the_generator_via_setstate():
    victim = random.Random(4242)
    idx0 = victim.getstate()[1][G.N]
    calls = G.calls_for_full_rank_random()
    doubles = [victim.random() for _ in range(calls)]
    rec = G.recover_from_random(doubles)
    clone = random.Random()
    clone.setstate((3, tuple(rec.concrete_state_words() + [idx0]), None))
    for _ in range(calls):                       # fast-forward clone past the observed window
        clone.random()
    assert [victim.random() for _ in range(50)] == [clone.random() for _ in range(50)]


def test_getrandbits_recovery_full_word_and_truncated():
    # full 32-bit words: full rank quickly
    victim = random.Random(7)
    rec = G.recover_from_getrandbits([victim.getrandbits(32) for _ in range(640)], 32)
    assert rec.unique
    words, certain = rec.predict_next_words(5)
    assert certain and [w for w in words] == [victim.getrandbits(32) for _ in range(5)]
    # truncated k=16: needs more calls, still unique
    victim = random.Random(8)
    n = (G.EFFECTIVE_BITS // 16) + 3 * G.N
    rec = G.recover_from_getrandbits([victim.getrandbits(16) for _ in range(n)], 16)
    assert rec.unique
    words, certain = rec.predict_next_words(5)
    assert certain and [w >> 16 for w in words] == [victim.getrandbits(16) for _ in range(5)]


def test_underdetermined_is_reported_not_guessed():
    # too few random() calls -> rank < 19937, unique False (never a silent guess, rule 8)
    victim = random.Random(1)
    rec = G.recover_from_random([victim.random() for _ in range(400)])
    assert rec.rank < G.EFFECTIVE_BITS and not rec.unique
    _, certain = rec.predict_next_words(4)
    assert not certain                            # predictions depend on free variables


def test_getrandbits_bits_bounds_validated():
    with pytest.raises(ValueError):
        G.recover_from_getrandbits([1, 2, 3], 33)
    with pytest.raises(ValueError):
        G.recover_from_getrandbits([1, 2, 3], 0)


def test_inconsistent_equations_raise():
    sysm = G.GF2System()
    sysm.add(0b101, 1)
    with pytest.raises(ValueError):
        sysm.add(0b101, 0)                        # same vector, contradictory rhs
