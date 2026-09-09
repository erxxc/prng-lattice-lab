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


PROMPT = str(Path(__file__).resolve().parents[1] / "prompts" / "report_synthesis_v1.md")


def test_narrative_without_key_is_a_disclosed_gap(monkeypatch):
    # Rule 7/8: with no key the prose pass must RAISE NarrativeUnavailable, never
    # fabricate prose or silently succeed. (Independent of whether the SDK is present.)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    md = synthesis.render_markdown(_VALID, schema_path=SCHEMA, run_meta=_META)
    with pytest.raises(synthesis.NarrativeUnavailable, match="ANTHROPIC_API_KEY"):
        synthesis.synthesize_narrative(md, prompt_path=PROMPT, run_meta=_META)


class _FakeBlock:
    type = "text"
    def __init__(self, text): self.text = text


class _FakeResp:
    def __init__(self, text): self.content = [_FakeBlock(text)]


def test_narrative_with_key_calls_model_and_attributes(monkeypatch):
    # Inject a fake `anthropic` SDK so the with-key branch is exercised end-to-end
    # without a network call: verify the versioned prompt is the system prompt, the
    # deterministic report is the only evidence passed, and the attribution is added.
    import sys
    import types

    captured = {}

    class _FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _FakeResp("The round-off boundary holds across the grid.")

    class _FakeClient:
        def __init__(self, api_key=None):
            captured["api_key"] = api_key
            self.messages = _FakeMessages()

    fake = types.ModuleType("anthropic")
    fake.Anthropic = _FakeClient
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    md = synthesis.render_markdown(_VALID, schema_path=SCHEMA, run_meta=_META)
    prose = synthesis.synthesize_narrative(md, prompt_path=PROMPT, run_meta=_META, model="claude-x")

    # attribution guaranteed even though the fake model omitted it
    assert prose.splitlines()[0] == "_Narrative by report_synthesis_v1 · model claude-x · over run 1._"
    assert "round-off boundary holds" in prose
    # versioned prompt IS the system prompt; deterministic report IS the evidence
    assert captured["system"].startswith("# report_synthesis — v1")
    assert "DETERMINISTIC REPORT" in captured["messages"][0]["content"]
    assert captured["model"] == "claude-x"
    assert captured["api_key"] == "sk-test"


def test_new_solver_methods_and_infeasible_outcome_render():
    cells = [
        {"bits_per_call": 8, "num_observations": 8, "trials": 10, "successes": 10,
         "method_used": "residue_slice", "median_ns": 1.0, "mean_margin": 0.1,
         "mean_candidates": 1.0, "outcome": "recovered", "capability_gap": None,
         "model": "nextint_odd", "bound": 255, "leaked_bits": 63.95},
        {"bits_per_call": 2, "num_observations": 32, "trials": 0, "successes": 0,
         "method_used": "none", "median_ns": None, "mean_margin": None,
         "mean_candidates": None, "outcome": "infeasible",
         "capability_gap": "skipped 10/10 trials: 10 infeasible (enumeration cost over budget)",
         "model": "bit_length", "bound": 4, "leaked_bits": 49.0},
    ]
    md = synthesis.render_markdown(cells, schema_path=SCHEMA,
                                   run_meta={**_META, "model": "nextint_odd"})
    assert "leak model `nextint_odd`" in md
    assert "‡" in md and "Infeasible within budget" in md
    assert "skipped 10/10 trials" in md
