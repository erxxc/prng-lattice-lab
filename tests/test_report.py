"""
Report guardrail: render_markdown re-validates stored cells against SweepCell on
read (the contract in synthesis.py's docstring), so a hand-edited/malformed DB row
cannot be smuggled into a deliverable. Also a smoke test that a well-formed set
renders.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from prng_lattice_lab.report import synthesis

SCHEMA = str(Path(__file__).resolve().parents[1] / "schema" / "records.schema.json")
_META = {"run_id": 1, "lab_version": "test", "created_at": "2026-01-01T00:00:00+00:00"}

_VALID = [
    {"bits_per_call": 24, "num_observations": 3, "trials": 10, "successes": 10,
     "method_used": "roundoff", "median_ns": 1.0, "mean_margin": 0.002,
     "mean_candidates": 1.0, "outcome": "recovered", "capability_gap": None},
    {"bits_per_call": 2, "num_observations": 2, "trials": 10, "successes": 0,
     "method_used": "none", "median_ns": None, "mean_margin": 0.3,
     "mean_candidates": None, "outcome": "underdetermined", "capability_gap": None},
]


def test_wellformed_cells_render():
    md = synthesis.render_markdown(_VALID, schema_path=SCHEMA, run_meta=_META)
    assert "Recoverability of java.util.Random" in md


def test_missing_required_field_is_rejected():
    bad = dict(_VALID[0])
    del bad["successes"]
    with pytest.raises(ValueError, match="successes|SweepCell"):
        synthesis.render_markdown([bad], schema_path=SCHEMA, run_meta=_META)


def test_out_of_enum_method_is_rejected():
    pytest.importorskip("jsonschema")  # enum enforcement needs full validation
    bad = dict(_VALID[0])
    bad["method_used"] = "bogus"
    with pytest.raises(ValueError, match="SweepCell schema"):
        synthesis.render_markdown([bad], schema_path=SCHEMA, run_meta=_META)
