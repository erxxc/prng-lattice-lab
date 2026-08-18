"""
The repoauditor fold-in boundary.

This module mirrors -- deliberately, at arm's length -- the shape repoauditor's
detect stage expects from a deterministic adapter (its `CandidateFinding`, which
the sast/sca/secrets adapters satisfy). It does NOT import repoauditor. The lab
stays standalone; when this graduates, the real adapter is built inside
repoauditor against its own live, pydantic-validated contract, using this as the
spec.

VERIFIED 2026-08-18 against repoauditor `src/repoauditor/detect/ensemble.py`
(`CandidateFinding`) and `src/repoauditor/matching.py`. The earlier snapshot had
drifted; corrections applied here (tracked as repoauditor OPT-036,
`docs/optimizations/opt-036-weak-rng-adapter.md`):

  * The live `CandidateFinding` is a pydantic `BaseModel` with field validation;
    this dataclass is a standalone-runnable stand-in for it.
  * Location is CONCRETE (`file`, `line_start`, `line_end`, `citation_snippet`),
    not a single placeholder -- repoauditor's retrieval layer supplies it.
  * It carries `severity` (required). The previous "severity intentionally absent"
    reading was WRONG: deterministic adapters set a conservative INITIAL severity
    (SAST uses `sarif_severity`). What the adapter must not do is *upgrade* it --
    `normalize/adjudicate` owns upgrades, licensed by an independent corroborating
    source or a falsification pass. Here that corroborating source is the
    reproducible `RecoveryDemonstration`.
  * `identity_key` is matching.py's strongest signal ("natural_identity"); set it
    so dedup/corroboration behave.
  * `confidence` (0..1) and `source_tool` are required; `trust_boundary_ref` is an
    optional reference into the map, not a free-text label.

Non-negotiables this must still honour (repoauditor CLAUDE.md): every finding
carries a citation; severity is never upgraded without independent corroboration
or falsification; findings are ranked/suppressed, never deleted; no unsourced priors.

OPEN DESIGN DECISION (see OPT-036): the RNG-specific evidence below
(`recoverability`, `demonstration`, `citations`) has NO field on the upstream
`CandidateFinding`. It rides alongside here. In repoauditor it either compresses
into `rationale` + `confidence` with the demonstration persisted as a separate
evidence artifact (no schema change), or becomes a first-class store record via a
migration. Start with the former; propose the latter only if adjudication needs it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    """Mirror of repoauditor's `store.models.Severity` (a StrEnum upstream).
    The adapter proposes a conservative INITIAL value; normalize owns upgrades."""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RecoverabilityClass(str, Enum):
    """How exposed a located weak-RNG usage is. RNG-specific evidence, not a
    field of the upstream CandidateFinding."""
    PROVEN = "proven"            # state recovered + forward/backward tokens demonstrated
    LIKELY = "likely"            # idiom matches a known-recoverable pattern, no live demo run
    POSSIBLE = "possible"        # predictable generator in a security context, needs analyst review


@dataclass(frozen=True)
class Citation:
    """Everything a finding asserts must trace to a source."""
    source: str                  # e.g. "spawnmason/randar-explanation" or a demo-run id
    locator: str                 # section / URL / demonstration artifact path
    note: str = ""


@dataclass(frozen=True)
class RecoveryDemonstration:
    """The corroborating evidence that licenses a severity upgrade in normalize.
    Reproducible artifact, not an opinion: given N observed outputs, the recovered
    state predicts these next-K and prior-K outputs, verified against held-back
    ground truth."""
    observations_used: int
    recovered_state_present: bool
    predicted_next: list[int] = field(default_factory=list)
    predicted_prev: list[int] = field(default_factory=list)
    verified: bool = False       # matched held-back outputs


@dataclass(frozen=True)
class WeakRngCandidateFinding:
    """Mirror of repoauditor's `CandidateFinding` (detect/ensemble.py) plus the
    RNG-specific evidence payload.

    The first block mirrors the live contract field-for-field. The trailing block
    is RNG-specific evidence with no home on the upstream model (see OPT-036).
    """
    # --- mirror of the live CandidateFinding (required fields) ---
    title: str
    file: str
    line_start: int
    line_end: int
    citation_snippet: str
    confidence: float            # 0..1; proven demo -> high, pattern-only -> lower
    severity: Severity           # conservative INITIAL value; normalize owns upgrades
    # --- mirror (optional / defaulted) ---
    source_tool: str = "weak_rng"
    identity_key: str | None = None      # matching.py "natural_identity" -- set it
    trust_boundary_ref: str | None = None  # reference into the map, not free text
    rationale: str | None = None
    # --- RNG-specific evidence riding alongside (no upstream field; see OPT-036) ---
    recoverability: RecoverabilityClass = RecoverabilityClass.LIKELY
    demonstration: RecoveryDemonstration | None = None
    citations: list[Citation] = field(default_factory=list)
