"""
The parameter sweep: for each (bits_per_call, num_observations) cell, generate
trials, attempt recovery, and record success rate + timing + method + the
recoverability outcome. This produces the central deliverable -- the phase diagram.

Routing per cell (consecutive TOP_BITS leak):
  * the Randar anchor (bits=24, obs=3) stays on the validated, fpylll-free
    recover.roundoff path;
  * n*k < 48 leaked bits  -> information-theoretically underdetermined: no unique
    state exists, so no recovery is attempted and the cell is labelled honestly
    (this is a theorem, not a tooling gap);
  * n*k >= 48             -> the general solver (recover.lattice.solve_box, which
    enumerates the box completely) recovers uniquely OR exposes genuine collisions
    (>1 java.util.Random state consistent with the leak -- the recoverability edge);
  * anything else (non-consecutive, or a non-TOP_BITS leak model) -> capability gap.

When fpylll is absent the general path is unavailable and those cells record an
explicit capability_gap -- never a skipped or invented score (honest-baseline rule).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from prng_lattice_lab.config import LeakModel, LeakProfile, RecoverMethod, SweepConfig
from prng_lattice_lab.generate.harness import make_trials
from prng_lattice_lab.recover import lattice, roundoff
from prng_lattice_lab.recover.enumerate import BudgetExceeded

SECRET_BITS = 48


@dataclass(frozen=True)
class CellResult:
    bits_per_call: int
    num_observations: int
    trials: int
    successes: int              # trials with a UNIQUE, correct recovery
    method_used: str            # roundoff | enumerate | none
    median_ns: float | None
    mean_margin: float | None
    mean_candidates: float | None   # mean size of the consistent-state set (>1 = collisions)
    outcome: str | None         # recovered | ambiguous | underdetermined | gap
    capability_gap: str | None  # populated instead of a score when a method is missing

    @property
    def success_rate(self) -> float:
        return self.successes / self.trials if self.trials else 0.0


def _median(times: list[float]) -> float | None:
    if not times:
        return None
    ordered = sorted(times)
    return float(ordered[len(ordered) // 2])


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _gap_cell(profile: LeakProfile, trials: int, reason: str) -> CellResult:
    return CellResult(
        bits_per_call=profile.bits_per_call, num_observations=profile.num_observations,
        trials=trials, successes=0, method_used="none", median_ns=None,
        mean_margin=None, mean_candidates=None, outcome="gap", capability_gap=reason,
    )


def _roundoff_anchor(trials, n_trials: int) -> CellResult:
    """The validated 3x24-bit Randar cell, via recover.roundoff (no fpylll)."""
    successes = 0
    times: list[float] = []
    margins: list[float] = []
    for t in trials:
        m1, m2, m3 = t.observations
        margins.append(roundoff.margin(m1, m2, m3))
        start = time.perf_counter_ns()
        recovered = roundoff.recover_pre_call_state(m1, m2, m3)
        times.append(time.perf_counter_ns() - start)
        if recovered == t.true_pre_call_state:
            successes += 1
    return CellResult(
        bits_per_call=24, num_observations=3, trials=n_trials, successes=successes,
        method_used="roundoff", median_ns=_median(times), mean_margin=_mean(margins),
        mean_candidates=1.0, outcome="recovered", capability_gap=None,
    )


def _underdetermined_cell(trials, n_trials: int, k: int, n: int, call_stride: int) -> CellResult:
    """n*k < 48: fewer leaked bits than the 48-bit secret, so by pigeonhole the
    leak does not determine a unique state. No recovery is attempted; the margin
    is still recorded (when fpylll is present) because it illustrates that a small
    margin is necessary but NOT sufficient without enough total bits."""
    try:
        margins = [lattice.margin_top_bits(t.observations, k, call_stride) for t in trials]
        mean_margin = _mean(margins)
    except lattice.ReductionUnavailable:
        mean_margin = None
    return CellResult(
        bits_per_call=k, num_observations=n, trials=n_trials, successes=0,
        method_used="none", median_ns=None, mean_margin=mean_margin,
        mean_candidates=None, outcome="underdetermined", capability_gap=None,
    )


def _general_cell(trials, n_trials: int, k: int, n: int, call_stride: int) -> CellResult:
    """n*k >= 48: enumerate the box completely per trial and classify."""
    successes = 0
    ambiguous = 0
    missed = 0          # truth not in the enumerated set -> would be a completeness bug
    budget_hit = 0
    times: list[float] = []
    margins: list[float] = []
    cand_counts: list[int] = []
    for t in trials:
        margins.append(lattice.margin_top_bits(t.observations, k, call_stride))
        start = time.perf_counter_ns()
        try:
            candidates = lattice.recover_pre_states_top_bits(
                t.observations, k, call_stride=call_stride)
        except BudgetExceeded:
            times.append(time.perf_counter_ns() - start)
            budget_hit += 1
            continue
        times.append(time.perf_counter_ns() - start)
        cand_counts.append(len(candidates))
        if t.true_pre_call_state in candidates:
            if len(candidates) == 1:
                successes += 1
            else:
                ambiguous += 1
        else:
            missed += 1

    mean_margin = _mean(margins)
    mean_candidates = _mean(cand_counts)
    is_ambiguous = ambiguous > 0 or (mean_candidates is not None and mean_candidates > 1.0)
    if is_ambiguous or budget_hit:
        outcome, method = "ambiguous", "enumerate"
    else:
        outcome = "recovered"
        method = "roundoff" if (mean_margin is not None and mean_margin < 0.5) else "enumerate"

    notes: list[str] = []
    if budget_hit:
        notes.append(f"{budget_hit}/{n_trials} trials exceeded enumeration budget")
    if missed:
        notes.append(f"WARNING: {missed}/{n_trials} trials truth-not-in-enumerated-set (completeness)")
    return CellResult(
        bits_per_call=k, num_observations=n, trials=n_trials, successes=successes,
        method_used=method, median_ns=_median(times), mean_margin=mean_margin,
        mean_candidates=mean_candidates, outcome=outcome,
        capability_gap="; ".join(notes) if notes else None,
    )


def run_cell(profile: LeakProfile, trials_per_cell: int, method: RecoverMethod, seed: int) -> CellResult:
    trials = make_trials(profile, trials_per_cell, seed=seed)
    if profile.model is not LeakModel.TOP_BITS:
        return _gap_cell(profile, trials_per_cell,
                         "only TOP_BITS wired (nextint_odd / bit_length leak models pending)")

    k, n, stride = profile.bits_per_call, profile.num_observations, profile.call_stride
    if k == 24 and n == 3 and stride == 1:
        return _roundoff_anchor(trials, trials_per_cell)   # validated fpylll-free path
    if k * n < SECRET_BITS:
        return _underdetermined_cell(trials, trials_per_cell, k, n, stride)
    try:
        return _general_cell(trials, trials_per_cell, k, n, stride)
    except lattice.ReductionUnavailable:
        return _gap_cell(profile, trials_per_cell,
                         "fpylll not installed; general solver unavailable (round-off anchor still scores)")


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
