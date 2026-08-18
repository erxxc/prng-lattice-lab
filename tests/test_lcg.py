"""LCG correctness. These are the correctness-critical invariants for the whole lab."""
import random
from prng_lattice_lab.lcg import JavaRandom, step, step_back, MASK, A, A_INV


def test_step_is_invertible():
    r = random.Random(1)
    for _ in range(10000):
        s = r.getrandbits(48)
        assert step_back(step(s)) == s
        assert step(step_back(s)) == s


def test_a_inverse():
    assert (A * A_INV) & MASK == 1


def test_from_internal_state_no_scramble():
    # from_internal_state sets the raw field; constructor scrambles. They differ.
    raw = JavaRandom.from_internal_state(123456789)
    ctor = JavaRandom(123456789)
    assert raw.seed != ctor.seed
    assert raw.seed == 123456789


def test_nextfloat_in_unit_interval():
    jr = JavaRandom(42)
    for _ in range(1000):
        f = jr.next_float()
        assert 0.0 <= f < 1.0
