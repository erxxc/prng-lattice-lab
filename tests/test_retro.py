"""
Retroactive-recovery demonstration: capturing a 3-token window exposes the whole
token stream, including tokens issued BEFORE the window. Uses the validated round-off
cracker (no fpylll). This is the concrete predictable-token threat, verified against
ground truth.
"""
from __future__ import annotations

import random

from prng_lattice_lab.adapt import weak_rng_adapter as wra
from prng_lattice_lab.cli import main
from prng_lattice_lab.lcg import JavaRandom


def _issued(seed: int, n: int) -> tuple[int, list[int]]:
    state = random.Random(seed).getrandbits(48)
    gen = JavaRandom.from_internal_state(state)   # one generator, n consecutive tokens
    return state, [gen.next(24) for _ in range(n)]


def test_reconstruct_full_stream_from_a_window():
    _, issued = _issued(42, 20)
    for offset in (0, 7, 12, 17):                 # start, middle, end (no retro / no forward)
        assert wra.reconstruct_stream(issued[offset:offset + 3], offset, 20) == issued


def test_reconstruct_rejects_inconsistent_window():
    assert wra.reconstruct_stream([1, 2, 3], 0, 10) is None          # not from consecutive calls
    _, issued = _issued(1, 10)
    assert wra.reconstruct_stream(issued[0:3], 0, 2) is None          # window past total_length
    assert wra.reconstruct_stream(issued[0:2], 0, 10) is None         # window too short


def test_demonstrate_retroactive_is_verified():
    state, _ = _issued(99, 25)
    demo = wra.demonstrate_retroactive(state, total_tokens=25, window_offset=15)
    assert demo.recovered_state_present and demo.verified
    assert len(demo.predicted_prev) == 15          # tokens issued BEFORE the window
    assert len(demo.predicted_next) == 25 - 15 - 3  # tokens issued AFTER it


def test_retroactive_tokens_match_ground_truth():
    state, issued = _issued(7, 18)
    demo = wra.demonstrate_retroactive(state, 18, window_offset=9)
    assert demo.predicted_prev == issued[:9]       # exact earlier tokens
    assert demo.predicted_next == issued[12:]


def test_cli_retro_verifies_and_exits_zero():
    assert main(["retro", "--total", "20", "--offset", "10", "--seed", "7"]) == 0
    assert main(["retro", "--total", "5", "--offset", "4", "--seed", "1"]) == 2  # no room for window
