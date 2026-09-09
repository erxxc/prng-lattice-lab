"""
Integration guardrail for the sweep wiring: the grid must classify cells honestly
(recovered / ambiguous / underdetermined), keep the Randar anchor at 100%, and
never silently drop a truth from an enumerated set. Needs fpylll for the general
cells; without it the grid records honest capability gaps instead (checked lightly
by the fpylll-free store test).
"""
from __future__ import annotations

import pytest

pytest.importorskip("fpylll")

from prng_lattice_lab.config import LeakModel, LeakProfile, RecoverMethod, SweepConfig
from prng_lattice_lab.sweep.grid import run_cell, run_sweep


def test_sweep_outcomes_are_honest():
    cells = run_sweep(SweepConfig(trials_per_cell=12))
    idx = {(c.bits_per_call, c.num_observations): c for c in cells}

    anchor = idx[(24, 3)]
    assert anchor.outcome == "recovered"
    assert anchor.successes == anchor.trials  # validated round-off path, 100%

    assert any(c.outcome == "ambiguous" and (c.mean_candidates or 0) > 1 for c in cells)
    assert any(c.outcome == "underdetermined" for c in cells)

    # completeness: no cell may flag a truth-not-in-enumerated-set warning
    assert all("WARNING" not in (c.capability_gap or "") for c in cells)

    # a "recovered" cell is 100% unique by construction
    for c in cells:
        if c.outcome == "recovered":
            assert c.successes == c.trials
        # every underdetermined cell really is below the 48-bit floor
        if c.outcome == "underdetermined":
            assert c.bits_per_call * c.num_observations < 48


def test_strided_cell_recovers_through_the_general_solver():
    # A non-consecutive (stride>1) cell no longer records a gap: it routes through
    # the general solver (not the consecutive round-off anchor) and recovers.
    cell = run_cell(
        LeakProfile(model=LeakModel.TOP_BITS, bits_per_call=24, num_observations=3, call_stride=3),
        20, RecoverMethod.AUTO, seed=0)
    assert cell.outcome == "recovered" and cell.successes == cell.trials
    assert cell.capability_gap is None


def test_nextint_odd_cells_route_through_residue_solver():
    # over-determined: unique; the 48-bit edge: complete + ambiguous; below: underdetermined
    over = run_cell(LeakProfile(model=LeakModel.NEXTINT_ODD, bits_per_call=8, num_observations=8),
                    15, RecoverMethod.AUTO, seed=0)
    assert over.outcome == "recovered" and over.successes == over.trials == 15
    assert over.method_used == "residue_slice" and over.model == "nextint_odd" and over.bound == 255
    assert over.leaked_bits == pytest.approx(8 * 7.994, abs=0.01)
    assert "WARNING" not in (over.capability_gap or "")

    edge = run_cell(LeakProfile(model=LeakModel.NEXTINT_ODD, bits_per_call=8, num_observations=6),
                    25, RecoverMethod.AUTO, seed=0)
    assert edge.outcome == "ambiguous" and (edge.mean_candidates or 0) > 1
    assert "WARNING" not in (edge.capability_gap or "")

    under = run_cell(LeakProfile(model=LeakModel.NEXTINT_ODD, bits_per_call=4, num_observations=12),
                     5, RecoverMethod.AUTO, seed=0)
    assert under.outcome == "underdetermined" and under.method_used == "none"
    assert under.leaked_bits < 47.5


def test_bit_length_cells_disclose_per_trial_feasibility():
    short = run_cell(LeakProfile(model=LeakModel.BIT_LENGTH, bits_per_call=8, num_observations=16),
                     6, RecoverMethod.AUTO, seed=0)
    assert short.outcome == "underdetermined" and short.trials == 0
    assert "skipped 6/6" in (short.capability_gap or "")

    long = run_cell(LeakProfile(model=LeakModel.BIT_LENGTH, bits_per_call=8, num_observations=48),
                    8, RecoverMethod.AUTO, seed=0)
    assert long.outcome == "recovered" and long.successes == long.trials == 8
    assert long.method_used == "subset_enumerate" and long.model == "bit_length" and long.bound == 256
    assert long.leaked_bits > 48 and "WARNING" not in (long.capability_gap or "")

    # k=2: every informative observation is worth 2 bits, which cannot pay for its
    # own lattice dimension within budget -> disclosed as infeasible, not faked.
    starved = run_cell(LeakProfile(model=LeakModel.BIT_LENGTH, bits_per_call=2, num_observations=32),
                       6, RecoverMethod.AUTO, seed=0)
    assert starved.outcome in ("infeasible", "underdetermined") and starved.trials == 0
    assert "skipped" in (starved.capability_gap or "")


def test_run_sweep_honours_the_model():
    cells = run_sweep(SweepConfig(trials_per_cell=3, model=LeakModel.NEXTINT_ODD,
                                  bits_axis=(8, 16), samples_axis=(3, 8)))
    assert {c.model for c in cells} == {"nextint_odd"}
    assert all(c.outcome != "gap" for c in cells)


def test_noisy_edge_cell_degrades_to_ambiguous():
    # Measurement noise widens the box; an n*k=48 edge cell degrades from (partly)
    # unique to ambiguous, and the enumeration stays complete (no completeness WARNING).
    cell = run_cell(
        LeakProfile(model=LeakModel.TOP_BITS, bits_per_call=16, num_observations=3, noise=2),
        12, RecoverMethod.AUTO, seed=0)
    assert cell.outcome == "ambiguous" and (cell.mean_candidates or 0) > 1
    assert "WARNING" not in (cell.capability_gap or "")
