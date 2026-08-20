"""
MT19937 comparison victim: exact recovery by untempering, validated against Python's
stdlib `random.Random` (which IS MT19937). No lattice / fpylll -- pure bit-twiddling,
so this runs in the core gate.
"""
from __future__ import annotations

import random

import pytest

from prng_lattice_lab import mt19937 as mt
from prng_lattice_lab.cli import main


def test_temper_untemper_are_exact_inverses():
    for x in (0, 1, 0xFFFFFFFF, 0x80000000, 0xDEADBEEF, 0x9908B0DF, 123456789):
        assert mt.untemper(mt.temper(x)) == x
    rng = random.Random(1)
    for _ in range(500):
        x = rng.getrandbits(32)
        assert mt.untemper(mt.temper(x)) == x


@pytest.mark.parametrize("warmup", [0, 1, 500, 1000])
def test_clone_and_predict_matches_stdlib_at_any_offset(warmup):
    # Python's random.Random is MT19937; getrandbits(32) is one tempered output.
    r = random.Random(20260819)
    for _ in range(warmup):
        r.getrandbits(32)
    observed = [r.getrandbits(32) for _ in range(624)]
    predicted = mt.predict_next(observed, 8)
    actual = [r.getrandbits(32) for _ in range(8)]
    assert predicted == actual


def test_recovery_needs_a_full_period():
    with pytest.raises(ValueError):
        mt.recover_state([1, 2, 3])
    with pytest.raises(ValueError):
        mt.predict_next(list(range(623)), 1)   # one short of 624


def test_cli_mt_demo_verifies_and_exits_zero():
    assert main(["mt-demo", "--seed", "7", "--warmup", "300", "--predict", "4"]) == 0
