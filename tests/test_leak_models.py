"""
Leak-model guardrail (fpylll-free): the NEXTINT_ODD and BIT_LENGTH leaks are wired on
the generate side and characterised for H3 ("odd bounds leak less usable structure").

What this pins:
  * observe() produces in-range values for all three models, and call_stride skips
    the right number of intermediate calls;
  * NEXTINT_ODD is a genuine RESIDUE-CLASS leak -- nextInt(odd) == next(31) % bound
    (proved from lcg.step, not from the generator under test);
  * H3, quantified: top-bits carries ~k box-usable bits/call; nextInt(odd) carries
    ~k RAW bits but 0 box-usable (residue class -> HNP); bit-length carries far fewer
    bits. Both leak less USABLE structure than a top-bits leak of the same width.
"""
from __future__ import annotations

import random

import pytest

from prng_lattice_lab.characterize import leakage
from prng_lattice_lab.config import LeakModel, LeakProfile
from prng_lattice_lab.generate.leak import observe
from prng_lattice_lab.lcg import JavaRandom, step


def test_topbits_observe_in_range():
    prof = LeakProfile(model=LeakModel.TOP_BITS, bits_per_call=8, num_observations=5)
    gen = JavaRandom.from_internal_state(random.Random(0).getrandbits(48))
    obs = observe(gen, prof)
    assert len(obs) == 5 and all(0 <= o < (1 << 8) for o in obs)


def test_nextint_odd_in_range_and_odd_bound_required():
    prof = LeakProfile(model=LeakModel.NEXTINT_ODD, bits_per_call=8, num_observations=6)
    bound = prof.effective_bound()
    assert bound % 2 == 1                                  # default is the largest odd of width k
    gen = JavaRandom.from_internal_state(random.Random(1).getrandbits(48))
    obs = observe(gen, prof)
    assert len(obs) == 6 and all(0 <= o < bound for o in obs)
    # an even bound is rejected: the model is specifically the odd (worst-shape) case
    with pytest.raises(ValueError, match="odd bound"):
        observe(gen, LeakProfile(model=LeakModel.NEXTINT_ODD, bits_per_call=8, bound=256))


def test_bit_length_in_range():
    prof = LeakProfile(model=LeakModel.BIT_LENGTH, bits_per_call=8, num_observations=6)
    gen = JavaRandom.from_internal_state(random.Random(2).getrandbits(48))
    obs = observe(gen, prof)
    assert len(obs) == 6 and all(0 <= o <= 8 for o in obs)   # bit-length of a value < 2**8


def test_nextint_odd_is_a_residue_class():
    # Prove the leak shape from first principles: nextInt(odd) == next(31) % bound,
    # where next(31) = (step(state) >> 17). This is the residue structure H3 is about
    # (coprime to the 2**48 modulus -> not a round-off interval).
    bound = 255
    rng = random.Random(7)
    checked = 0
    for _ in range(500):
        state = rng.getrandbits(48)
        first_next31 = step(state) >> 17
        # skip the (rare) values java's rejection loop would discard, so the identity
        # is between the ACCEPTED next31 and the output
        if first_next31 - (first_next31 % bound) + (bound - 1) >= 0x80000000:
            continue
        got = JavaRandom.from_internal_state(state).next_int(bound)
        assert got == first_next31 % bound
        checked += 1
    assert checked > 400                                     # the vast majority are non-rejected


def test_call_stride_skips_intermediate_calls():
    # observing every 3rd nextInt(odd) must equal taking calls 0, 3, 6, ... of a plain run
    bound = LeakProfile(model=LeakModel.NEXTINT_ODD, bits_per_call=8).effective_bound()
    state = random.Random(9).getrandbits(48)
    strided = observe(JavaRandom.from_internal_state(state),
                      LeakProfile(model=LeakModel.NEXTINT_ODD, bits_per_call=8,
                                  num_observations=4, call_stride=3))
    ref_gen = JavaRandom.from_internal_state(state)
    ref = [ref_gen.next_int(bound) for _ in range(4 * 3)]
    assert strided == ref[0:12:3]


def test_h3_odd_and_bitlength_leak_less_usable_structure():
    res = leakage.compare_leak_models(bits_per_call=8, trials=40_000, seed=0)
    by = {r["model"]: r for r in res["rows"]}
    top = by["top_bits"]; odd = by["nextint_odd"]; blen = by["bit_length"]

    # top-bits: a full ~k box-usable bits, interval-shaped
    assert top["raw_bits"] == pytest.approx(8.0, abs=0.05)
    assert top["box_usable"] and top["box_usable_bits"] == pytest.approx(8.0, abs=0.05)

    # odd bound: ~the SAME raw information, but ZERO box-usable (residue class -> HNP)
    assert odd["raw_bits"] == pytest.approx(8.0, abs=0.1)
    assert not odd["box_usable"] and odd["box_usable_bits"] == 0.0

    # bit-length: interval-shaped but STARVED -- far fewer bits than the width
    assert blen["box_usable"]
    assert blen["raw_bits"] < 3.0

    # H3: both non-top models carry strictly less USABLE structure than top-bits
    assert odd["box_usable_bits"] < top["box_usable_bits"]
    assert blen["box_usable_bits"] < top["box_usable_bits"]
    assert res["h3_confirmed"]
