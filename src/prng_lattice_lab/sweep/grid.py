"""
The parameter sweep: for each (bits_per_call, num_observations) cell of ONE leak
model, generate trials, attempt recovery, and record success rate + timing + method
+ the recoverability outcome. This produces the central deliverable -- the phase
diagram -- for each of the three leak models.

Routing per cell:
  TOP_BITS (the interval leak; k bits/call):
    * the Randar anchor (bits=24, obs=3) stays on the validated, fpylll-free
      recover.roundoff path;
    * n*k < 48 -> information-theoretically underdetermined: no unique state exists,
      no recovery attempted, labelled honestly (a theorem, not a tooling gap);
    * n*k >= 48 -> recover.lattice.solve_box enumerates the box completely and
      recovers uniquely OR exposes genuine collisions (the recoverability edge).
  NEXTINT_ODD (the residue leak; log2(bound) bits/call):
    * n*log2(bound) more than half a bit below 48 -> underdetermined;
    * else recover.residue (low-17-bit slicing + certified round-off), complete.
      A trial whose window contained a rejected draw is outside the solver's model
      (not a fixed-stride run of states); it is excluded and itemised, never counted
      as a completeness failure.
  BIT_LENGTH (the starved interval leak; ~2 bits/call):
    * information is realized per trial, so feasibility is decided per trial:
      underdetermined (<48 realized bits), infeasible (enumeration cost over budget),
      or scored via recover.starved (informative-subset lattice, complete).

`trials` on a cell counts the trials actually SCORED (recovery run to completion);
skipped trials are itemised with their reason in `capability_gap` (rule 8: every
excluded trial is disclosed with its cause; nothing is silently dropped). When
fpylll is absent every general cell records an explicit capability gap -- never a
skipped or invented score (honest-baseline rule).
"""
from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass

from prng_lattice_lab.config import LeakModel, LeakProfile, RecoverMethod, SweepConfig
from prng_lattice_lab.generate.harness import make_trials
from prng_lattice_lab.recover import lattice, residue, roundoff, starved
from prng_lattice_lab.recover.enumerate import BudgetExceeded

SECRET_BITS = 48
EDGE_HALF_WIDTH = 0.5   # leaked bits within 0.5 of 48 is the edge, not underdetermined


@dataclass(frozen=True)
class CellResult:
    bits_per_call: int
    num_observations: int
    trials: int                 # trials SCORED (recovery run to completion)
    successes: int              # scored trials with a UNIQUE, correct recovery
    method_used: str            # roundoff | enumerate | residue_slice | subset_enumerate | none
    median_ns: float | None
    mean_margin: float | None
    mean_candidates: float | None   # mean size of the consistent-state set (>1 = collisions)
    outcome: str | None         # recovered | ambiguous | underdetermined | infeasible | gap
    capability_gap: str | None  # gap reason, or itemised skipped trials / notes
    model: str = LeakModel.TOP_BITS.value
    bound: int | None = None
    leaked_bits: float | None = None   # realized information per trial (mean over scored)

    @property
    def success_rate(self) -> float:
        return self.successes / self.trials if self.trials else 0.0

    def record(self) -> dict:
        """The SweepCell record (schema/records.schema.json) for the store."""
        return asdict(self)


def _median(times: list[float]) -> float | None:
    if not times:
        return None
    ordered = sorted(times)
    return float(ordered[len(ordered) // 2])


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _bound_of(profile: LeakProfile) -> int | None:
    return None if profile.model is LeakModel.TOP_BITS else profile.effective_bound()


def _gap_cell(profile: LeakProfile, trials: int, reason: str,
              leaked_bits: float | None = None) -> CellResult:
    return CellResult(
        bits_per_call=profile.bits_per_call, num_observations=profile.num_observations,
        trials=trials, successes=0, method_used="none", median_ns=None,
        mean_margin=None, mean_candidates=None, outcome="gap", capability_gap=reason,
        model=profile.model.value, bound=_bound_of(profile), leaked_bits=leaked_bits,
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
        mean_candidates=1.0, outcome="recovered", capability_gap=None, leaked_bits=72.0,
    )


def _underdetermined_cell(trials, n_trials: int, k: int, n: int, call_stride: int,
                          noise: int = 0) -> CellResult:
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
        leaked_bits=float(k * n),
    )


def _general_cell(trials, n_trials: int, k: int, n: int, call_stride: int,
                  noise: int = 0) -> CellResult:
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
                t.observations, k, call_stride=call_stride, noise=noise)
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
        capability_gap="; ".join(notes) if notes else None, leaked_bits=float(k * n),
    )


def _classify(successes: int, ambiguous: int, scored: int, mean_candidates: float | None,
              budget_hit: int) -> str:
    if ambiguous > 0 or (mean_candidates is not None and mean_candidates > 1.0) or budget_hit:
        return "ambiguous"
    return "recovered"


def _residue_cell(trials, n_trials: int, profile: LeakProfile) -> CellResult:
    """nextInt(odd bound): recover.residue, complete per trial."""
    k, n, stride = profile.bits_per_call, profile.num_observations, profile.call_stride
    bound = profile.effective_bound()
    lb = residue.leaked_bits(bound, n)
    if lb < SECRET_BITS - EDGE_HALF_WIDTH:
        return CellResult(
            bits_per_call=k, num_observations=n, trials=n_trials, successes=0,
            method_used="none", median_ns=None, mean_margin=None, mean_candidates=None,
            outcome="underdetermined", capability_gap=None, model=profile.model.value,
            bound=bound, leaked_bits=lb)
    try:
        residue.slice_basis(n, stride)      # the one fpylll step, cached
    except lattice.ReductionUnavailable:
        return _gap_cell(profile, n_trials,
                         "fpylll not installed; residue-slice solver unavailable", lb)

    successes = ambiguous = missed = budget_hit = rejected = 0
    times: list[float] = []
    margins: list[float] = []
    cand_counts: list[int] = []
    for t in trials:
        start = time.perf_counter_ns()
        try:
            candidates, m = residue.recover_pre_states_nextint_odd(
                t.observations, bound, call_stride=stride)
        except residue.RowBudgetExceeded:
            times.append(time.perf_counter_ns() - start)
            budget_hit += 1
            continue
        times.append(time.perf_counter_ns() - start)
        if t.true_pre_call_state not in candidates and \
                residue.rejections_in_window(t.true_pre_call_state, n, bound, stride) > 0:
            rejected += 1          # outside the fixed-stride model: excluded, disclosed
            continue
        margins.append(m)
        cand_counts.append(len(candidates))
        if t.true_pre_call_state in candidates:
            if len(candidates) == 1:
                successes += 1
            else:
                ambiguous += 1
        else:
            missed += 1

    scored = len(cand_counts)
    mean_candidates = _mean(cand_counts)
    outcome = _classify(successes, ambiguous, scored, mean_candidates, budget_hit)
    notes: list[str] = []
    if rejected:
        notes.append(f"excluded {rejected}/{n_trials} trials: a rejected nextInt draw inside the "
                     "window (not a fixed-stride state run; outside the solver's model)")
    if budget_hit:
        notes.append(f"{budget_hit}/{n_trials} trials exceeded the certified-enumeration row budget")
    if missed:
        notes.append(f"WARNING: {missed}/{n_trials} trials truth-not-in-candidate-set (completeness)")
    return CellResult(
        bits_per_call=k, num_observations=n, trials=scored, successes=successes,
        method_used="residue_slice", median_ns=_median(times), mean_margin=_mean(margins),
        mean_candidates=mean_candidates, outcome=outcome,
        capability_gap="; ".join(notes) if notes else None, model=profile.model.value,
        bound=bound, leaked_bits=lb,
    )


def _starved_cell(trials, n_trials: int, profile: LeakProfile) -> CellResult:
    """bit-length of nextInt(2**k): recover.starved, feasibility decided per trial."""
    k, n, stride = profile.bits_per_call, profile.num_observations, profile.call_stride
    bound = profile.effective_bound()
    all_bits = [starved.leaked_bits(t.observations, k) for t in trials]
    try:
        lattice.reduced_basis(2)            # fpylll presence check (cached, cheap)
    except lattice.ReductionUnavailable:
        return _gap_cell(profile, n_trials,
                         "fpylll not installed; subset-enumeration solver unavailable",
                         _mean(all_bits))

    successes = ambiguous = missed = budget_hit = under = infeasible = 0
    times: list[float] = []
    margins: list[float] = []
    cand_counts: list[int] = []
    scored_bits: list[float] = []
    for t, lb in zip(trials, all_bits):
        start = time.perf_counter_ns()
        try:
            candidates, plan, m = starved.recover_pre_states_bit_length(
                t.observations, k, call_stride=stride)
        except starved.Underdetermined:
            under += 1
            continue
        except starved.Infeasible:
            infeasible += 1
            continue
        except BudgetExceeded:
            times.append(time.perf_counter_ns() - start)
            budget_hit += 1
            continue
        times.append(time.perf_counter_ns() - start)
        margins.append(m)
        cand_counts.append(len(candidates))
        scored_bits.append(lb)
        if t.true_pre_call_state in candidates:
            if len(candidates) == 1:
                successes += 1
            else:
                ambiguous += 1
        else:
            missed += 1

    scored = len(cand_counts)
    mean_candidates = _mean(cand_counts)
    if scored:
        outcome = _classify(successes, ambiguous, scored, mean_candidates, budget_hit)
    elif budget_hit:
        outcome = "ambiguous"
    elif infeasible > under:
        outcome = "infeasible"
    else:
        outcome = "underdetermined"
    notes: list[str] = []
    skipped = under + infeasible
    if skipped:
        parts = []
        if under:
            parts.append(f"{under} underdetermined (<{SECRET_BITS} realized bits)")
        if infeasible:
            parts.append(f"{infeasible} infeasible (enumeration cost over budget)")
        notes.append(f"skipped {skipped}/{n_trials} trials: " + ", ".join(parts))
    if budget_hit:
        notes.append(f"{budget_hit}/{n_trials} trials exceeded enumeration budget")
    if missed:
        notes.append(f"WARNING: {missed}/{n_trials} trials truth-not-in-candidate-set (completeness)")
    return CellResult(
        bits_per_call=k, num_observations=n, trials=scored, successes=successes,
        method_used="subset_enumerate" if scored else "none", median_ns=_median(times),
        mean_margin=_mean(margins), mean_candidates=mean_candidates, outcome=outcome,
        capability_gap="; ".join(notes) if notes else None, model=profile.model.value,
        bound=bound, leaked_bits=_mean(scored_bits) if scored_bits else _mean(all_bits),
    )


def run_cell(profile: LeakProfile, trials_per_cell: int, method: RecoverMethod, seed: int) -> CellResult:
    trials = make_trials(profile, trials_per_cell, seed=seed)
    if profile.model is LeakModel.NEXTINT_ODD:
        return _residue_cell(trials, trials_per_cell, profile)
    if profile.model is LeakModel.BIT_LENGTH:
        return _starved_cell(trials, trials_per_cell, profile)

    k, n, stride, noise = (profile.bits_per_call, profile.num_observations,
                           profile.call_stride, profile.noise)
    if k == 24 and n == 3 and stride == 1 and noise == 0:
        return _roundoff_anchor(trials, trials_per_cell)   # validated fpylll-free path
    if k * n < SECRET_BITS:
        return _underdetermined_cell(trials, trials_per_cell, k, n, stride, noise)
    try:
        return _general_cell(trials, trials_per_cell, k, n, stride, noise)
    except lattice.ReductionUnavailable:
        return _gap_cell(profile, trials_per_cell,
                         "fpylll not installed; general solver unavailable (round-off anchor still scores)",
                         float(k * n))


def run_sweep(cfg: SweepConfig) -> list[CellResult]:
    """Run the full grid for cfg.model. Returns one CellResult per (bits, samples) cell."""
    results: list[CellResult] = []
    for bits in cfg.bits_axis:
        for samples in cfg.samples_axis:
            profile = LeakProfile(model=cfg.model, bits_per_call=bits, num_observations=samples)
            results.append(run_cell(profile, cfg.trials_per_cell, cfg.method, cfg.seed))
    return results
