"""
Demonstration artifacts (adapt/evidence): schema-validated, reproducible, verified,
with a uniqueness/coincidence certificate and tamper-evident content hash. Oracle-backed
paths use a real JVM when present and are otherwise forced to the lab model, so the
fpylll-free / JDK-free core still runs.
"""
from __future__ import annotations

import json

import pytest

from prng_lattice_lab.adapt import evidence
from prng_lattice_lab.adapt import jvm_oracle
from prng_lattice_lab.cli import main

SCHEMA = "schema/records.schema.json"


@pytest.mark.parametrize("kind", ["msb24", "mt19937"])
def test_artifact_is_verified_reproducible_valid_and_sealed(kind):
    a = evidence.demonstrate(kind, seed=3, oracle="lab_model")
    b = evidence.demonstrate(kind, seed=3, oracle="lab_model")
    assert a.verified and a.demonstration.recovered_state_present
    assert a.demonstration.predicted_next == b.demonstration.predicted_next  # deterministic in seed
    assert a.reproduce.startswith(f"prng-lattice-lab demonstrate {kind} --seed 3")
    assert a.citations and a.claim_boundary.startswith("Proves the generator class")
    assert a.content_sha256 and len(a.content_sha256) == 64
    evidence.validate_record(a.to_record(), SCHEMA)


def test_certificate_quantifies_verification():
    a = evidence.demonstrate("msb24", seed=1, total=20, offset=5, oracle="lab_model")
    c = a.certificate
    assert c.method == "roundoff"
    assert c.held_out_checked == 20 - 3                      # every non-window token predicted
    assert c.coincidence_bound_log2 == pytest.approx(-24.0 * (20 - 3))
    assert c.coincidence_bound < 1e-100                      # astronomically unlikely by chance
    m = evidence.demonstrate("mt19937", seed=1, predict=5)
    assert m.certificate.method == "untemper" and m.certificate.unique is True
    assert m.certificate.coincidence_bound_log2 == pytest.approx(-32.0 * 5)


def test_verify_record_detects_tampering():
    a = evidence.demonstrate("mt19937", seed=2)
    rec = a.to_record()
    ok, detail = evidence.verify_record(rec)
    assert ok and "reproduces the artifact exactly" in detail
    rec["demonstration"]["predicted_next"][0] ^= 1           # edit a prediction
    ok, detail = evidence.verify_record(rec)
    assert not ok and "tampered" in detail                   # hash catches it before re-run
    # edit a field but fix the hash: the re-run must still catch the divergence
    rec2 = a.to_record()
    rec2["parameters"] = {**rec2["parameters"], "seed": 999}
    rec2 = evidence._seal(rec2)
    ok, detail = evidence.verify_record(rec2)
    assert not ok


def test_seeded_recovers_the_constructor_seed_as_a_timestamp():
    a = evidence.demonstrate("seeded", seed=7, total=12, oracle="lab_model")
    assert a.verified and a.kind == "seeded"
    assert a.idiom_ids == ["java-util-random-ctor"]
    assert a.parameters["recovered_seed"] is not None
    assert a.parameters["recovered_timestamp_utc"].startswith("20")   # a real wall-clock time
    evidence.validate_record(a.to_record(), SCHEMA)


def test_nextint_odd_artifact_is_verified_and_certified():
    pytest.importorskip("fpylll")
    a = evidence.demonstrate("nextint_odd", seed=5, bound=255, total=30, offset=12,
                             oracle="lab_model")
    assert a.verified and a.parameters["window"] == 8
    assert a.certificate.method == "residue_slice"
    assert a.certificate.candidates == 1 and a.certificate.unique is True
    assert a.certificate.certified_radius is not None and a.certificate.certified_radius < 0.5
    evidence.validate_record(a.to_record(), SCHEMA)


def test_ambiguous_window_yields_unverified_artifact_not_a_guess():
    pytest.importorskip("fpylll")
    for seed in range(40):
        a = evidence.demonstrate("nextint_odd", seed=seed, bound=(1 << 24) - 1, total=10,
                                 offset=0, window=2, oracle="lab_model")
        if a.parameters["ambiguous_candidates"]:
            assert not a.verified and not a.demonstration.recovered_state_present
            assert a.certificate.candidates > 1 and a.certificate.unique is False
            break
    else:
        pytest.fail("expected at least one ambiguous 2-token window in 40 seeds")


def test_invalid_record_is_rejected():
    rec = evidence.demonstrate("mt19937", seed=1).to_record()
    del rec["certificate"]
    with pytest.raises(Exception):
        evidence.validate_record(rec, SCHEMA)


def test_cli_demonstrate_and_verify_roundtrip(tmp_path):
    out = tmp_path / "demo.json"
    assert main(["demonstrate", "msb24", "--seed", "7", "--oracle", "lab_model",
                 "--out", str(out)]) == 0
    rec = json.loads(out.read_text())
    assert rec["kind"] == "msb24" and rec["verified"] is True and rec["oracle"] == "lab_model"
    assert rec["demonstration"]["predicted_prev"]           # retroactive tokens present
    assert main(["demonstrate", "--verify", str(out)]) == 0
    # tamper on disk -> verify exits non-zero
    rec["verified"] = True
    rec["demonstration"]["predicted_next"][0] ^= 1
    out.write_text(json.dumps(rec))
    assert main(["demonstrate", "--verify", str(out)]) == 1


@pytest.mark.skipif(not jvm_oracle.available(), reason="no JDK for the JVM oracle")
def test_jvm_oracle_backed_artifact_records_the_real_jvm():
    a = evidence.demonstrate("nextint_odd", seed=5, bound=255, total=30, offset=12, oracle="jvm")
    assert a.oracle == "jvm" and a.oracle_detail and "version" in a.oracle_detail.lower()
    assert a.verified                                        # lab solvers recover REAL JVM tokens
    ok, _ = evidence.verify_record(a.to_record())
    assert ok


def test_jvm_requested_without_jdk_is_explicit_not_silent(monkeypatch):
    monkeypatch.setattr(jvm_oracle, "available", lambda: False)
    with pytest.raises(jvm_oracle.OracleUnavailable):
        evidence.demonstrate("msb24", seed=1, oracle="jvm")
    # auto degrades to the lab model, recorded honestly
    a = evidence.demonstrate("msb24", seed=1, oracle="auto")
    assert a.oracle == "lab_model"
