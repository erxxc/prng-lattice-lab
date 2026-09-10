"""
Demonstration artifacts: the corroborating-evidence payload for repoauditor.

repoauditor's normalize/adjudicate licenses a severity upgrade only when a SECOND,
independently produced source flags the same issue (matching.has_independent_
corroboration). The weak_rng detector is one source; a reproducible state-recovery
demonstration is the other. This module packages such a demonstration as a
self-contained, schema-validated `DemonstrationArtifact`: what it recovered, the exact
command that regenerates it, citations, and -- the point of the artifact -- the PROOFS
that make "verified" a quantified claim rather than a say-so.

Every artifact now carries:
  * oracle          -- "jvm" when the observed tokens came from a real OpenJDK
                       java.util.Random process (adapt.jvm_oracle), "lab_model" when
                       from the lab's port. A jvm artifact is evidence the lab's model
                       matches the real generator across the whole idiom, not just the
                       one pinned Randar vector.
  * certificate     -- the uniqueness / false-match bound behind `verified`:
                         candidates          how many states are consistent (complete
                                             solvers only; 1 == certified unique)
                         held_out_checked    tokens predicted and matched against
                                             held-back ground truth
                         coincidence_bound   P(a wrong state matches all held-out
                                             tokens by chance) ~= 2^(-bits*held_out)
                         certified_radius    the residue solver's round-off radius
  * content_sha256  -- sha256 over the canonical record (this field blanked), so
                       tampering is detectable and `demonstrate --verify` can confirm
                       the artifact was not edited after emission.

Kinds:
  msb24        nextFloat top-24-bit tokens (Randar path; java-util-random-ctor,
               math-random) -- recover/roundoff, 3-token window.
  nextint_odd  nextInt(odd bound) tokens (apache-randomstringutils) -- recover/residue,
               a complete solver, so this kind carries a real uniqueness certificate.
  seeded       new Random(seed) with a bounded (e.g. time-derived) seed: recover the
               CONSTRUCTOR seed from a few outputs (the seeded-ctor idiom). The recovered
               seed is itself the evidence -- often a wall-clock creation time.
  mt19937      full 32-bit outputs of Python's random.Random (py-random-*; exact
               untempering from 624 outputs) -- mt19937.py.

The claim boundary travels with every artifact: it proves the generator CLASS is
recoverable from the stated observations; it does not by itself prove that the flagged
code exposes those observations across a trust boundary.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass, field

from prng_lattice_lab import __version__
from prng_lattice_lab.adapt import jvm_oracle
from prng_lattice_lab.adapt import weak_rng_adapter as wra
from prng_lattice_lab.adapt.contract import Citation, RecoveryDemonstration
from prng_lattice_lab.lcg import JavaRandom, step_back

KINDS = ("msb24", "nextint_odd", "seeded", "mt19937")
MULT = jvm_oracle.MULT

_MT_CITE = Citation(
    source="Matsumoto & Nishimura (1998); tempering inversion",
    locator="https://en.wikipedia.org/wiki/Mersenne_Twister#Algorithmic_detail",
    note="MT19937 outputs untemper exactly; 624 consecutive words reconstruct the state.",
)

CLAIM_BOUNDARY = (
    "Proves the generator class is recoverable from the stated observations (state "
    "recovered from a captured window, then past/future outputs predicted and checked "
    "exactly against held-back ground truth). Does NOT by itself prove that the flagged "
    "code exposes such observations across a trust boundary; that link is the "
    "reviewer's to establish. Severity remains repoauditor's to adjudicate."
)


@dataclass(frozen=True)
class Certificate:
    method: str                    # roundoff | residue_slice | untemper | seed_unscramble
    candidates: int | None         # consistent-state count (complete solvers); None if not enumerated
    unique: bool | None            # candidates == 1 (None when not enumerated)
    held_out_checked: int          # tokens matched against held-back truth
    coincidence_bound: float       # P(a wrong state matches all held-out tokens by chance)
    coincidence_bound_log2: float  # log2 of the above (readable when the bound underflows)
    certified_radius: float | None = None


@dataclass(frozen=True)
class DemonstrationArtifact:
    kind: str
    victim: str
    oracle: str                    # "jvm" | "lab_model"
    oracle_detail: str | None
    idiom_ids: list[str]
    parameters: dict
    lab_version: str
    created_at: str
    reproduce: str
    demonstration: RecoveryDemonstration
    certificate: Certificate
    citations: list[Citation]
    verified: bool
    claim_boundary: str = CLAIM_BOUNDARY
    content_sha256: str = ""

    def to_record(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_record(), indent=2)


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _canonical_for_hash(record: dict) -> str:
    """Canonical JSON of a record with content_sha256 blanked, for hashing/verification."""
    r = {**record, "content_sha256": ""}
    return json.dumps(r, sort_keys=True, separators=(",", ":"))


def _seal(record: dict) -> dict:
    """Return the record with content_sha256 filled from its own canonical form."""
    return {**record, "content_sha256": hashlib.sha256(
        _canonical_for_hash(record).encode("utf-8")).hexdigest()}


def _coincidence(bits_per_token: float, held_out: int) -> tuple[float, float]:
    """(bound, log2 bound): chance a wrong state reproduces `held_out` tokens by luck."""
    log2 = -bits_per_token * held_out
    try:
        bound = 2.0 ** log2
    except OverflowError:  # pragma: no cover
        bound = 0.0
    return bound, log2


def _resolve_oracle(oracle: str) -> tuple[str, str | None]:
    """Map the requested oracle to (used, detail). "auto" prefers the JVM when present."""
    if oracle == "jvm" and not jvm_oracle.available():
        raise jvm_oracle.OracleUnavailable("JVM oracle requested but no usable JDK is on PATH")
    if oracle in ("jvm", "auto") and jvm_oracle.available():
        return "jvm", jvm_oracle.java_version()
    return "lab_model", None


def _issue_msb24(state: int, n: int, used: str) -> list[int]:
    if used == "jvm":
        return jvm_oracle.emit(state, "msb24", n)
    gen = JavaRandom.from_internal_state(state)
    return [gen.next(24) for _ in range(n)]


def _issue_nextint(state: int, n: int, bound: int, used: str) -> list[int]:
    if used == "jvm":
        return jvm_oracle.emit(state, "nextint", n, bound)
    gen = JavaRandom.from_internal_state(state)
    return [gen.next_int(bound) for _ in range(n)]


def demonstrate(kind: str, *, seed: int = 0, total: int = 20, offset: int = 10,
                bound: int = 255, window: int | None = None, warmup: int = 1000,
                predict: int = 5, oracle: str = "auto") -> DemonstrationArtifact:
    """Build one demonstration artifact of the given kind (see module doc).

    `oracle`: "auto" uses a real JVM for the java.util.Random kinds when a JDK is
    present, else the lab model; "jvm" requires a JDK (raises OracleUnavailable
    otherwise); "lab_model" forces the port. mt19937 ignores it (Python victim).
    Deterministic in `seed`, so `reproduce` regenerates the artifact exactly.
    """
    if kind == "msb24":
        return _demo_msb24(seed, total, offset, oracle)
    if kind == "nextint_odd":
        return _demo_nextint_odd(seed, total, offset, bound, window, oracle)
    if kind == "seeded":
        return _demo_seeded(seed, total, oracle)
    if kind == "mt19937":
        return _demo_mt19937(seed, warmup, predict)
    raise ValueError(f"unknown demonstration kind {kind!r}; expected one of {KINDS}")


def _demo_msb24(seed: int, total: int, offset: int, oracle: str) -> DemonstrationArtifact:
    used, detail = _resolve_oracle(oracle)
    state = random.Random(seed).getrandbits(48)
    window = 3
    issued = _issue_msb24(state, total, used)
    win = issued[offset:offset + window]
    recon = wra.reconstruct_stream(win, offset, total)
    ok = recon is not None
    demo = RecoveryDemonstration(
        observations_used=window, recovered_state_present=ok,
        predicted_prev=(recon[:offset] if ok else []),
        predicted_next=(recon[offset + window:] if ok else []),
        verified=bool(ok and recon == issued))
    held_out = (total - window) if demo.verified else 0
    cbound, clog2 = _coincidence(24.0, held_out)
    cert = Certificate(method="roundoff", candidates=None, unique=None,
                       held_out_checked=held_out, coincidence_bound=cbound,
                       coincidence_bound_log2=clog2)
    return _finish(
        kind="msb24", victim="java.util.Random", used=used, detail=detail,
        idiom_ids=["java-util-random-ctor", "math-random"],
        parameters={"total": total, "offset": offset, "window": window, "seed": seed},
        reproduce=f"prng-lattice-lab demonstrate msb24 --seed {seed} --total {total} "
                  f"--offset {offset} --oracle {used}",
        demo=demo, cert=cert, citations=[wra._RANDAR_CITE])


def _demo_nextint_odd(seed: int, total: int, offset: int, bound: int,
                      window: int | None, oracle: str) -> DemonstrationArtifact:
    from prng_lattice_lab.recover import residue
    used, detail = _resolve_oracle(oracle)
    window = window or wra.default_window_nextint_odd(bound)
    state = random.Random(seed).getrandbits(48)
    issued = _issue_nextint(state, total, bound, used)
    win = issued[offset:offset + window]
    candidates, radius = residue.recover_pre_states_nextint_odd(win, bound)
    ambiguous = len(candidates) if len(candidates) != 1 else None
    if len(candidates) == 1:
        s0 = candidates[0]
        # rewind to before the stream, replay the whole issued sequence
        s = s0
        for _ in range(offset):
            s = step_back(s)
        gen = JavaRandom.from_internal_state(s)
        recon = [gen.next_int(bound) for _ in range(total)]
        verified = recon == issued
        demo = RecoveryDemonstration(
            observations_used=window, recovered_state_present=True,
            predicted_prev=recon[:offset], predicted_next=recon[offset + window:],
            verified=verified)
    else:
        demo = RecoveryDemonstration(observations_used=window, recovered_state_present=False)
        verified = False
    held_out = (total - window) if demo.verified else 0
    cbound, clog2 = _coincidence(math.log2(bound), held_out)
    cert = Certificate(
        method="residue_slice", candidates=len(candidates),
        unique=(len(candidates) == 1), held_out_checked=held_out,
        coincidence_bound=cbound, coincidence_bound_log2=clog2, certified_radius=radius)
    params = {"bound": bound, "total": total, "offset": offset, "window": window,
              "seed": seed, "ambiguous_candidates": ambiguous}
    return _finish(
        kind="nextint_odd", victim="java.util.Random", used=used, detail=detail,
        idiom_ids=["apache-randomstringutils"], parameters=params,
        reproduce=f"prng-lattice-lab demonstrate nextint_odd --seed {seed} --bound {bound} "
                  f"--total {total} --offset {offset} --window {window} --oracle {used}",
        demo=demo, cert=cert, citations=[wra._ELTTAM_CITE, wra._RANDAR_CITE])


def _demo_seeded(seed: int, total: int, oracle: str) -> DemonstrationArtifact:
    """Recover the CONSTRUCTOR seed of new Random(S) from msb24 tokens. The chosen S is
    a plausible millisecond timestamp, so the recovered value is the RNG's wall-clock
    creation time -- the concrete harm of seeding from the clock."""
    used, detail = _resolve_oracle(oracle)
    # a millisecond epoch timestamp in a +-1 year window around a fixed reference (< 2**48)
    ref_ms = 1_780_000_000_000               # ~2026 in ms; fixed so the artifact is deterministic
    true_seed = ref_ms + (random.Random(seed).randrange(-31_536_000_000, 31_536_000_000))
    internal = (true_seed ^ MULT) & ((1 << 48) - 1)   # post-construction state
    window = 3
    issued = _issue_msb24(internal, total, used)
    pre = wra.reconstruct_stream(issued[:window], 0, total)   # recover from the first tokens
    s1 = None
    if pre is not None:
        from prng_lattice_lab.recover import roundoff
        s1 = roundoff.recover_pre_call_state(issued[0], issued[1], issued[2])
    recovered_seed = ((s1 ^ MULT) & ((1 << 48) - 1)) if s1 is not None else None
    verified = recovered_seed == (true_seed & ((1 << 48) - 1))
    demo = RecoveryDemonstration(
        observations_used=window, recovered_state_present=s1 is not None,
        predicted_prev=[], predicted_next=(pre[window:] if pre else []), verified=verified)
    held_out = (total - window) if (pre and pre == issued) else 0
    cbound, clog2 = _coincidence(24.0, max(held_out, window))   # window itself pins the 48-bit seed
    cert = Certificate(method="seed_unscramble", candidates=(1 if verified else None),
                       unique=(True if verified else None), held_out_checked=held_out,
                       coincidence_bound=cbound, coincidence_bound_log2=clog2)
    params = {"total": total, "window": window, "seed": seed,
              "recovered_seed": recovered_seed, "seed_is_timestamp_ms": True,
              "recovered_timestamp_utc": (
                  _dt.datetime.fromtimestamp(recovered_seed / 1000, _dt.timezone.utc).isoformat()
                  if recovered_seed is not None else None)}
    return _finish(
        kind="seeded", victim="java.util.Random", used=used, detail=detail,
        idiom_ids=["java-util-random-ctor"], parameters=params,
        reproduce=f"prng-lattice-lab demonstrate seeded --seed {seed} --total {total} "
                  f"--oracle {used}",
        demo=demo, cert=cert, citations=[wra._RANDAR_CITE])


def _demo_mt19937(seed: int, warmup: int, predict: int) -> DemonstrationArtifact:
    from prng_lattice_lab import mt19937
    r = random.Random(seed)
    for _ in range(warmup):
        r.getrandbits(32)
    observed = [r.getrandbits(32) for _ in range(624)]
    predicted = mt19937.predict_next(observed, predict)
    actual = [r.getrandbits(32) for _ in range(predict)]
    verified = predicted == actual
    demo = RecoveryDemonstration(observations_used=624, recovered_state_present=True,
                                 predicted_next=predicted, predicted_prev=[], verified=verified)
    held_out = predict if verified else 0
    cbound, clog2 = _coincidence(32.0, held_out)
    cert = Certificate(method="untemper", candidates=1, unique=True,
                       held_out_checked=held_out, coincidence_bound=cbound,
                       coincidence_bound_log2=clog2)
    return _finish(
        kind="mt19937", victim="python random.Random (MT19937)", used="lab_model", detail=None,
        idiom_ids=["py-random-getrandbits", "py-random-module"],
        parameters={"seed": seed, "warmup": warmup, "predict": predict,
                    "observation": "624 consecutive full 32-bit outputs (getrandbits(32))"},
        reproduce=f"prng-lattice-lab demonstrate mt19937 --seed {seed} --warmup {warmup} "
                  f"--predict {predict}",
        demo=demo, cert=cert, citations=[_MT_CITE])


def _finish(*, kind, victim, used, detail, idiom_ids, parameters, reproduce, demo, cert,
            citations) -> DemonstrationArtifact:
    art = DemonstrationArtifact(
        kind=kind, victim=victim, oracle=used, oracle_detail=detail, idiom_ids=idiom_ids,
        parameters=parameters, lab_version=__version__, created_at=_now(),
        reproduce=reproduce, demonstration=demo, certificate=cert, citations=list(citations),
        verified=demo.verified)
    sealed = _seal(art.to_record())
    return DemonstrationArtifact(**{**asdict(art), "certificate": cert,
                                    "demonstration": demo, "citations": list(citations),
                                    "content_sha256": sealed["content_sha256"]})


def verify_record(record: dict) -> tuple[bool, str]:
    """Re-verify a stored artifact WITHOUT trusting its `verified` flag.

    (1) recompute content_sha256 (tamper check); (2) re-run the demonstration from the
    recorded parameters and confirm the predictions and certificate match. Returns
    (ok, detail). This is what an evidence-intake path calls before letting an artifact
    corroborate anything.
    """
    stored_hash = record.get("content_sha256", "")
    recomputed = hashlib.sha256(_canonical_for_hash(record).encode("utf-8")).hexdigest()
    if stored_hash != recomputed:
        return False, f"content hash mismatch (tampered): stored {stored_hash[:12]}, got {recomputed[:12]}"
    kind = record.get("kind")
    p = record.get("parameters", {})
    oracle = record.get("oracle", "lab_model")
    try:
        fresh = demonstrate(
            kind, seed=p.get("seed", 0), total=p.get("total", 20), offset=p.get("offset", 10),
            bound=p.get("bound", 255), window=p.get("window"), warmup=p.get("warmup", 1000),
            predict=p.get("predict", 5), oracle=oracle)
    except (jvm_oracle.OracleUnavailable, ValueError) as exc:
        return False, f"could not re-run: {exc}"
    fd, sd = fresh.demonstration, record.get("demonstration", {})
    if fresh.verified != record.get("verified"):
        return False, "re-run verified flag differs from the artifact"
    if fd.predicted_next != sd.get("predicted_next") or fd.predicted_prev != sd.get("predicted_prev"):
        return False, "re-run predictions differ from the artifact"
    if fresh.certificate.held_out_checked != record.get("certificate", {}).get("held_out_checked"):
        return False, "re-run certificate differs from the artifact"
    return (fresh.verified,
            "re-run reproduces the artifact exactly" if fresh.verified
            else "re-run reproduces the artifact, but it is an unverified (honest-negative) result")


def validate_record(record: dict, schema_path: str) -> None:
    """Validate an artifact record against the DemonstrationArtifact schema (full
    jsonschema when installed, required-field check otherwise). Raises on failure."""
    with open(schema_path, "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    spec = schema["$defs"]["DemonstrationArtifact"]
    try:
        import jsonschema  # type: ignore
    except ImportError:  # pragma: no cover - optional dependency
        missing = [k for k in spec["required"] if k not in record]
        if missing:
            raise ValueError(f"DemonstrationArtifact missing required fields: {missing}")
        return
    resolver_schema = {"$defs": schema["$defs"], **spec}
    jsonschema.validate(record, resolver_schema)
