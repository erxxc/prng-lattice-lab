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

from prng_lattice_lab.config import SweepConfig
from prng_lattice_lab.sweep.grid import run_sweep


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
