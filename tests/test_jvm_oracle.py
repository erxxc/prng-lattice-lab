"""
The real-JVM oracle (adapt.jvm_oracle): the lab's port of java.util.Random must match a
live OpenJDK across both idioms, not just the one pinned Randar vector. Skipped when no
JDK is on PATH (the whole point is that a JDK is optional).
"""
from __future__ import annotations

import random

import pytest

from prng_lattice_lab.adapt import jvm_oracle
from prng_lattice_lab.lcg import JavaRandom

pytestmark = pytest.mark.skipif(not jvm_oracle.available(), reason="no JDK on PATH")


def test_msb24_matches_lab_model_over_random_states():
    rng = random.Random(0)
    for _ in range(40):
        state = rng.getrandbits(48)
        jvm = jvm_oracle.emit(state, "msb24", 5)
        gen = JavaRandom.from_internal_state(state)
        assert jvm == [gen.next(24) for _ in range(5)]


@pytest.mark.parametrize("bound", [255, 91, 1000003, (1 << 24) - 1])
def test_nextint_matches_lab_model_including_rejection_bounds(bound):
    rng = random.Random(bound)
    for _ in range(30):
        state = rng.getrandbits(48)
        jvm = jvm_oracle.emit(state, "nextint", 6, bound)
        gen = JavaRandom.from_internal_state(state)
        assert jvm == [gen.next_int(bound) for _ in range(6)]


def test_constructor_unscramble_sets_the_internal_state():
    # emit uses new Random(state ^ MULT); token 0 must equal the lab model from `state`.
    for state in (0, 1, 123123123123123, (1 << 48) - 1):
        jvm = jvm_oracle.emit(state, "msb24", 1)[0]
        assert jvm == JavaRandom.from_internal_state(state).next(24)


def test_version_string_is_reported():
    assert "version" in (jvm_oracle.java_version() or "").lower()
