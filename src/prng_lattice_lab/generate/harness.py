"""
Ground-truth trial generation. Draws a known internal state, runs the generator,
applies a leak profile, and hands back (true_state, observations) so the recover
stage can be scored against known truth.

Everything here is offline and self-contained: the lab attacks a generator it
instantiated itself. There is no network target and no third-party system.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from prng_lattice_lab.config import LeakProfile
from prng_lattice_lab.generate.leak import observe
from prng_lattice_lab.lcg import JavaRandom


@dataclass(frozen=True)
class Trial:
    true_pre_call_state: int   # internal state BEFORE the first observed call
    observations: list[int]    # leaked integers (per generate.leak.observe)
    profile: LeakProfile


def make_trials(profile: LeakProfile, n: int, seed: int = 0) -> list[Trial]:
    """Generate `n` reproducible trials for one leak profile."""
    rng = random.Random(seed)
    trials: list[Trial] = []
    for _ in range(n):
        state = rng.getrandbits(48)
        gen = JavaRandom.from_internal_state(state)
        obs = observe(gen, profile)
        trials.append(Trial(true_pre_call_state=state, observations=obs, profile=profile))
    return trials
