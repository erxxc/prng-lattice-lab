"""
Guardrail for characterize/ (margin surface/boundary + calibration coverage).

The margin/calibration functions are pure read projections over stored cells, so
most tests run on synthetic cell dicts with no fpylll. One fpylll-guarded
integration test confirms they compose over a real sweep and reproduce the
information-theoretic structure (0% below n·k=48, an ambiguous edge at 48, 100%
above; ideal-hash coverage perfect off the edge).
"""
from __future__ import annotations

import math

import pytest

from prng_lattice_lab.characterize import calibration as cal
from prng_lattice_lab.characterize import margin


def _cell(bits, obs, trials, successes, *, mean_margin=None, mean_candidates=None,
          outcome="recovered", capability_gap=None):
    return {
        "bits_per_call": bits, "num_observations": obs, "trials": trials,
        "successes": successes, "method_used": "roundoff", "median_ns": 1.0,
        "mean_margin": mean_margin, "mean_candidates": mean_candidates,
        "outcome": outcome, "capability_gap": capability_gap,
    }


# --- predict / regime ----------------------------------------------------------
def test_predict_underdetermined_is_zero():
    assert cal.predict(_cell(2, 4, 100, 0, outcome="underdetermined")) == 0.0


def test_predict_edge_is_ideal_hash_null():
    assert cal.predict(_cell(16, 3, 100, 57)) == pytest.approx(math.exp(-1.0))


def test_predict_overdetermined_is_essentially_one():
    assert cal.predict(_cell(24, 3, 100, 100)) == pytest.approx(1.0, abs=1e-6)


def test_regime_boundaries():
    assert cal.regime_of(_cell(2, 4, 100, 0)) == "underdetermined"   # nk=8
    assert cal.regime_of(_cell(16, 3, 100, 57)) == "edge"            # nk=48
    assert cal.regime_of(_cell(24, 3, 100, 100)) == "overdetermined" # nk=72


# --- Wilson interval -----------------------------------------------------------
def test_wilson_interval_contains_zero_and_one_at_extremes():
    lo, hi = cal.wilson_interval(0, 100)
    assert lo == pytest.approx(0.0, abs=1e-12) and hi < 0.1
    lo, hi = cal.wilson_interval(100, 100)
    assert hi == pytest.approx(1.0, abs=1e-12) and lo > 0.9


# --- coverage ------------------------------------------------------------------
def _coverage_cellset():
    return [
        _cell(2, 4, 100, 0, mean_margin=0.3, outcome="underdetermined"),      # covered (0 in CI)
        _cell(24, 3, 100, 100, mean_margin=0.002, mean_candidates=1.0),       # covered (1 in CI)
        _cell(8, 6, 100, 37, mean_margin=0.4, mean_candidates=1.8, outcome="ambiguous"),  # edge, matches null
        _cell(24, 2, 100, 20, mean_margin=0.27, mean_candidates=1.9, outcome="ambiguous"),  # edge, deviates
        _cell(2, 2, 100, 0, mean_margin=None, outcome="gap", capability_gap="fpylll absent"),
    ]


def test_coverage_excludes_gaps_and_scores_regimes():
    cov = cal.coverage(_coverage_cellset())
    assert cov["n_cells"] == 4                      # the gap cell is excluded
    assert cov["by_regime"]["underdetermined"]["fraction"] == 1.0
    assert cov["by_regime"]["overdetermined"]["fraction"] == 1.0
    assert cov["by_regime"]["edge"] == {"covered": 1, "n": 2, "fraction": 0.5}
    assert cov["covered"] == 3 and cov["coverage_fraction"] == 0.75
    uncovered = [(c["bits_per_call"], c["num_observations"]) for c in cov["cells"] if not c["covered"]]
    assert uncovered == [(24, 2)]                   # the deviating edge cell


def test_reliability_table_tracks_predicted_vs_observed():
    table = cal.reliability_table(_coverage_cellset())
    by_bin = {(r["bin_low"], r["bin_high"]): r for r in table}
    # underdetermined bin: predicted 0, observed 0
    assert by_bin[(0.0, 0.2)]["mean_observed"] == 0.0
    # overdetermined bin: predicted ~1, observed 1
    assert by_bin[(0.8, 1.0)]["mean_observed"] == pytest.approx(1.0)


# --- margin surface / boundary -------------------------------------------------
def test_margin_surface_and_curve_are_not_lossy():
    cells = [_cell(2, 3, 100, 0, mean_margin=0.38, outcome="underdetermined"),
             _cell(4, 3, 100, 0, mean_margin=0.36, outcome="underdetermined")]
    surface = margin.margin_surface(cells)
    assert surface == {(2, 3): 0.38, (4, 3): 0.36}
    assert margin.margin_curve(cells, num_observations=3) == [(2, 0.38), (4, 0.36)]


def test_roundoff_boundary_interpolates_a_crossing():
    cells = [_cell(4, 3, 100, 0, mean_margin=0.6), _cell(8, 3, 100, 50, mean_margin=0.4)]
    (b,) = margin.roundoff_boundary(cells)
    assert b["bracket_low_bits"] == 4 and b["bracket_high_bits"] == 8
    assert b["crossing_bits"] == pytest.approx(6.0)  # 0.6->0.4 crosses 0.5 midway


def test_roundoff_boundary_reports_absence_of_crossing():
    cells = [_cell(4, 3, 100, 0, mean_margin=0.30), _cell(8, 3, 100, 50, mean_margin=0.10)]
    (b,) = margin.roundoff_boundary(cells)
    assert b["crossing_bits"] is None and "below 0.5" in b["note"]


# --- H1 aggregates -------------------------------------------------------------
def test_recovery_by_total_bits_shows_the_edge():
    cells = [_cell(8, 3, 100, 0, outcome="underdetermined"),   # nk=24
             _cell(16, 3, 100, 60, mean_candidates=1.5, outcome="ambiguous"),  # nk=48
             _cell(20, 3, 100, 100, mean_candidates=1.0)]      # nk=60
    rows = {r["total_bits"]: r for r in cal.recovery_by_total_bits(cells)}
    assert rows[24]["mean_unique_recovery"] == 0.0
    assert rows[48]["mean_unique_recovery"] == 0.60
    assert rows[60]["mean_unique_recovery"] == 1.0


# --- integration over a real sweep --------------------------------------------
def test_characterize_composes_over_a_real_sweep():
    pytest.importorskip("fpylll")
    from prng_lattice_lab.config import SweepConfig
    from prng_lattice_lab.sweep.grid import run_sweep

    cells = run_sweep(SweepConfig(trials_per_cell=60))
    cov = cal.coverage(cells)
    assert cov["by_regime"]["overdetermined"]["fraction"] == 1.0
    assert cov["by_regime"]["underdetermined"]["fraction"] == 1.0

    by_nk = {r["total_bits"]: r for r in cal.recovery_by_total_bits(cells)}
    assert by_nk[24]["mean_unique_recovery"] == 0.0          # underdetermined
    assert by_nk[72]["mean_unique_recovery"] == 1.0          # over-determined
    assert 0.0 < by_nk[48]["mean_unique_recovery"] < 1.0     # the ambiguous edge
