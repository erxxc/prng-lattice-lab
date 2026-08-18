"""
The parameter sweep: for each (bits_per_call, num_observations) cell, generate
trials, attempt recovery, and record success rate + timing + method used. This
produces the central deliverable -- the recoverability phase diagram.

The 3-consecutive-nextFloat cell (bits=24, samples=3) is fully wired through
recover.roundoff and works today. Other cells depend on recover.lattice.solve_box
/ recover.enumerate and currently raise NotImplementedError; the driver records
that as an explicit `capability_gap` outcome for the cell rather than skipping or
faking it (honest-baseline rule).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from prng_lattice_lab.config import LeakModel, LeakProfile, RecoverMethod, SweepConfig
from prng_lattice_lab.generate.harness import make_trials
from prng_lattice_lab.recover import roundoff


@dataclass(frozen=True)
class CellResult:
    bits_per_call: int
    num_observations: int
    trials: int
    successes: int
    method_used: str
    median_ns: float | None
    mean_margin: float | None
    capability_gap: str | None   # populated instead of a score when a method is missing

    @property
    def success_rate(self) -> float:
        return self.successes / self.trials if self.trials else 0.0


def run_cell(profile: LeakProfile, trials_per_cell: int, method: RecoverMethod, seed: int) -> CellResult:
    trials = make_trials(profile, trials_per_cell, seed=seed)

    # Only the validated fast path is wired. Route to it when the cell matches;
    # otherwise record the gap honestly.
    is_roundoff_cell = (
        profile.model is LeakModel.TOP_BITS
        and profile.bits_per_call == 24
        and profile.num_observations == 3
        and profile.call_stride == 1
    )
    if not is_roundoff_cell:
        return CellResult(
            bits_per_call=profile.bits_per_call,
            num_observations=profile.num_observations,
            trials=trials_per_cell, successes=0, method_used="none",
            median_ns=None, mean_margin=None,
            capability_gap="general solver not wired (recover.lattice.solve_box / recover.enumerate pending)",
        )

    successes = 0
    times: list[float] = []
    margins: list[float] = []
    for t in trials:
        m1, m2, m3 = t.observations
        margins.append(roundoff.margin(m1, m2, m3))
        start = time.perf_counter_ns()
        recovered_pre = roundoff.recover_pre_call_state(m1, m2, m3)
        times.append(time.perf_counter_ns() - start)
        if recovered_pre == t.true_pre_call_state:
            successes += 1
    times.sort()
    median = times[len(times) // 2] if times else None
    mean_margin = sum(margins) / len(margins) if margins else None
    return CellResult(
        bits_per_call=24, num_observations=3, trials=trials_per_cell,
        successes=successes, method_used="roundoff", median_ns=median,
        mean_margin=mean_margin, capability_gap=None,
    )


def run_sweep(cfg: SweepConfig) -> list[CellResult]:
    """Run the full grid. Returns one CellResult per (bits, samples) cell."""
    results: list[CellResult] = []
    for bits in cfg.bits_axis:
        for samples in cfg.samples_axis:
            profile = LeakProfile(
                model=LeakModel.TOP_BITS, bits_per_call=bits, num_observations=samples
            )
            results.append(run_cell(profile, cfg.trials_per_cell, cfg.method, cfg.seed))
    return results
