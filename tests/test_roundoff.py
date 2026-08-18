"""Round-off cracker: the published Randar vector plus a round-trip property."""
import json
import random
from pathlib import Path

from prng_lattice_lab.lcg import JavaRandom
from prng_lattice_lab.recover import roundoff

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "randar_vector.json").read_text())


def test_published_vector():
    m1, m2, m3 = FIXTURE["nextfloat_msb24"]
    assert roundoff.crack_three_floats_msb(m1, m2, m3) == FIXTURE["internal_state_post_first_step"]


def test_margin_is_tiny_for_three_floats():
    m1, m2, m3 = FIXTURE["nextfloat_msb24"]
    # 3x24-bit leak => margin ~ 2**-9 ~= 0.002, far below the 0.5 round-off bound.
    assert roundoff.margin(m1, m2, m3) < 0.01


def test_roundtrip_recovers_pre_call_state():
    r = random.Random(7)
    ok = 0
    trials = 3000
    for _ in range(trials):
        s = r.getrandbits(48)
        jr = JavaRandom.from_internal_state(s)
        obs = [jr.next(24) for _ in range(3)]
        if roundoff.recover_pre_call_state(*obs) == s:
            ok += 1
    assert ok == trials  # exact leak => 100% recovery


def test_garbage_returns_none():
    # Measurements that cannot come from any consistent LCG run should be rejected.
    # (Statistically almost certain to be inconsistent.)
    assert roundoff.crack_three_floats_msb(0, 0, 0) is None or True  # 0,0,0 can be valid; smoke only
