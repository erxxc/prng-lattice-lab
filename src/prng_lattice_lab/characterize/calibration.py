"""
Success-rate calibration and prediction-interval coverage over the sweep.

Intent (transfer target for repoauditor risk-quant session G): predict each cell's
UNIQUE-recovery probability from an information-theoretic model, then check the
observed rate against the prediction with a proper interval -- a coverage test with
an EXACT oracle. If the coverage code can't nail a boundary you can compute
analytically here, it won't nail a fuzzy security one.

The model (deliberately the ideal-hash null, so deviations are informative):
  * n*k < 48 leaked bits  -> no unique state exists            -> P(unique) = 0
  * n*k >= 48             -> unique unless another java.util.Random state collides.
    Treating the leak as an ideal hash, the expected number of OTHER consistent
    states is lambda = 2**(48 - n*k), and collisions are ~Poisson, so
        P(unique) = exp(-lambda).
    lambda = 1 at the n*k = 48 edge (P ~ 0.37), and vanishes as the leak grows.

Coverage then asks, per cell: does the modelled P fall inside a Wilson score
interval for the observed unique-recovery rate? The over-determined and
underdetermined regions are near-perfectly covered; the n*k = 48 edge is where the
ideal-hash null and the real (structured) LCG can disagree -- which is exactly the
kind of model misspecification a coverage procedure must catch. Uncertainty is
reported as a range (the interval), never collapsed to one number.

Pure READ projection over stored cells; accepts sweep `CellResult` objects or
`store.list_cells` dict rows. Wilson interval is closed-form (numpy/stdlib only).
"""
from __future__ import annotations

import math

SECRET_BITS = 48
_Z95 = 1.959963984540054  # standard normal quantile for a 95% two-sided interval


def _get(cell, key):
    return cell[key] if isinstance(cell, dict) else getattr(cell, key)


EDGE_HALF_WIDTH = 0.5  # |leaked bits - 48| below this counts as the edge (n*k=48 exactly for top-bits)


def _opt(cell, key):
    if isinstance(cell, dict):
        return cell.get(key)
    return getattr(cell, key, None)


def _total_bits(cell) -> float:
    """Information the cell's leak actually carried: the stored realized `leaked_bits`
    when present (nextint_odd: n*log2 b; bit_length: mean over the run), else the
    top-bits n*k. Integer-valued for the top-bits grid, so nothing there changes."""
    lb = _opt(cell, "leaked_bits")
    if lb is not None:
        return float(lb)
    return float(_get(cell, "bits_per_call") * _get(cell, "num_observations"))


def regime_of(cell) -> str:
    """Which side of the recoverability edge a cell sits on."""
    nk = _total_bits(cell)
    if nk < SECRET_BITS - EDGE_HALF_WIDTH:
        return "underdetermined"
    if nk < SECRET_BITS + EDGE_HALF_WIDTH:
        return "edge"
    return "overdetermined"


def predict(cell) -> float:
    """Modelled P(unique recovery) for a cell under the ideal-hash null (see module
    docstring). Deterministic; no peeking at the observed outcome."""
    nk = _total_bits(cell)
    if nk < SECRET_BITS - EDGE_HALF_WIDTH:
        return 0.0
    lam = 2.0 ** (SECRET_BITS - nk)   # expected colliding states
    return math.exp(-lam)


def wilson_interval(successes: int, trials: int, z: float = _Z95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (well-behaved at 0/1 and small n)."""
    if trials == 0:
        return (0.0, 1.0)
    p = successes / trials
    z2 = z * z
    denom = 1.0 + z2 / trials
    center = (p + z2 / (2 * trials)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / trials + z2 / (4 * trials * trials))
    return (max(0.0, center - half), min(1.0, center + half))


def _scored(cells):
    """Cells for which a recovery characterisation was actually produced (exclude
    capability gaps -- fpylll absent or an unwired leak model)."""
    for c in cells:
        if _get(c, "outcome") == "gap":
            continue
        if _get(c, "trials") in (None, 0):
            continue
        yield c


def coverage(cells, *, z: float = _Z95) -> dict:
    """Observed-vs-predicted coverage over the sweep.

    For each scored cell: observed unique-recovery rate + its Wilson interval, the
    modelled P, and whether the model falls inside the interval. Returns the overall
    coverage fraction, a per-regime breakdown, and the per-cell rows.
    """
    rows: list[dict] = []
    by_regime: dict[str, list[bool]] = {}
    for c in _scored(cells):
        trials = _get(c, "successes"), _get(c, "trials")
        succ, n = trials
        observed = succ / n
        lo, hi = wilson_interval(succ, n, z)
        pred = predict(c)
        # tolerance absorbs float round-off at the interval endpoints (e.g. the
        # Wilson lower bound for 0 successes is 0 only up to rounding).
        covered = lo - 1e-12 <= pred <= hi + 1e-12
        regime = regime_of(c)
        by_regime.setdefault(regime, []).append(covered)
        rows.append({
            "bits_per_call": _get(c, "bits_per_call"),
            "num_observations": _get(c, "num_observations"),
            "total_bits": round(_total_bits(c), 2),
            "regime": regime,
            "trials": n,
            "observed": observed,
            "ci_low": lo,
            "ci_high": hi,
            "predicted": pred,
            "covered": covered,
        })
    total = len(rows)
    covered_n = sum(r["covered"] for r in rows)
    return {
        "n_cells": total,
        "covered": covered_n,
        "coverage_fraction": (covered_n / total) if total else None,
        "by_regime": {
            k: {"covered": sum(v), "n": len(v), "fraction": sum(v) / len(v)}
            for k, v in sorted(by_regime.items())
        },
        "cells": sorted(rows, key=lambda r: (r["bits_per_call"], r["num_observations"])),
    }


def reliability_table(cells, bins: tuple[float, ...] = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0001)) -> list[dict]:
    """Reliability diagram (as a table): bin scored cells by predicted P, and report
    mean predicted vs mean observed per bin. A well-calibrated model tracks the
    diagonal; systematic gaps flag where the ideal-hash null misses."""
    scored = list(_scored(cells))
    out: list[dict] = []
    for lo, hi in zip(bins, bins[1:]):
        members = [c for c in scored if lo <= predict(c) < hi]
        if not members:
            continue
        mean_pred = sum(predict(c) for c in members) / len(members)
        mean_obs = sum(_get(c, "successes") / _get(c, "trials") for c in members) / len(members)
        out.append({
            "bin_low": lo,
            "bin_high": min(hi, 1.0),
            "n_cells": len(members),
            "mean_predicted": mean_pred,
            "mean_observed": mean_obs,
        })
    return out


def recovery_by_total_bits(cells) -> list[dict]:
    """Observed unique-recovery rate and mean candidate-set size as a function of
    total leaked bits n*k -- the empirical form of the recoverability edge (H1)."""
    groups: dict[float, list] = {}
    for c in _scored(cells):
        groups.setdefault(round(_total_bits(c), 1), []).append(c)
    out: list[dict] = []
    for nk in sorted(groups):
        members = groups[nk]
        obs_rate = sum(_get(c, "successes") / _get(c, "trials") for c in members) / len(members)
        cands = [_get(c, "mean_candidates") for c in members if _get(c, "mean_candidates") is not None]
        out.append({
            "total_bits": nk,
            "n_cells": len(members),
            "mean_unique_recovery": obs_rate,
            "mean_candidates": (sum(cands) / len(cands)) if cands else None,
        })
    return out


def recovery_boundary(cells, threshold: float = 0.99) -> list[dict]:
    """Per observation count, the minimum bits_per_call at which unique recovery
    reaches `threshold` -- the empirical phase boundary (which the default grid does
    cross, unlike the mean-margin 0.5 line). Reported with the last sub-threshold
    cell as the lower bracket, so the boundary is a range, not a point."""
    by_obs: dict[int, list] = {}
    for c in _scored(cells):
        by_obs.setdefault(_get(c, "num_observations"), []).append(c)
    out: list[dict] = []
    for o in sorted(by_obs):
        members = sorted(by_obs[o], key=lambda c: _get(c, "bits_per_call"))
        crossing = None
        below = None
        for c in members:
            rate = _get(c, "successes") / _get(c, "trials")
            if rate >= threshold:
                crossing = _get(c, "bits_per_call")
                break
            below = _get(c, "bits_per_call")
        out.append({
            "num_observations": o,
            "min_bits_recovered": crossing,
            "last_bits_below": below,
            "note": "" if crossing is not None else f"no cell reaches {threshold} at this obs count",
        })
    return out
