"""
Store guardrail (fpylll-free): the new ambiguity columns round-trip, and the
migration runner is idempotent -- reopening a database must not re-apply an
ALTER TABLE and crash.
"""
from __future__ import annotations

from prng_lattice_lab.store.db import Store

_CELL = {
    "bits_per_call": 16, "num_observations": 3, "trials": 10, "successes": 5,
    "method_used": "enumerate", "median_ns": 1.0, "mean_margin": 0.4,
    "mean_candidates": 1.5, "outcome": "ambiguous", "capability_gap": None,
}


def test_cell_roundtrip_and_migration_idempotent(tmp_path):
    db = tmp_path / "lab.db"
    store = Store(db)
    run_id = store.record_sweep_run(
        {"config": {}, "lab_version": "test", "created_at": "2026-01-01T00:00:00+00:00"})
    store.record_cell(run_id, _CELL)
    store.close()

    # Reopen: _migrate runs again and must be a no-op, not an error.
    store2 = Store(db)
    cells = store2.list_cells(run_id)
    store2.close()

    assert len(cells) == 1
    got = cells[0]
    assert got["mean_candidates"] == 1.5
    assert got["outcome"] == "ambiguous"
    assert got["successes"] == 5
