"""
The repoauditor fold-in boundary.

This module mirrors -- deliberately, at arm's length -- the shape repoauditor's
detect stage expects from a deterministic adapter (the CandidateFinding contract
its sast_adapter / sca_adapter / secrets_adapter satisfy). It does NOT import
repoauditor. The lab stays standalone; when this graduates, the real adapter is
built inside repoauditor against its own live contract, using this as the spec.

Why a mirror and not a dependency: keeps the weekend harness runnable on its own,
and forces the contract to be written down explicitly so drift is visible in
review. The repoauditor CLAUDE.md non-negotiables that this must honour:
  * every finding carries citations
  * severity is never upgraded without an independent corroborating source OR a
    falsification-confirmed result -- here, the corroborating source is a live
    recovery DEMONSTRATION (recover next/prev tokens), which is reproducible
    evidence, not a prior
  * findings are ranked/suppressed, never deleted
  * no unsourced priors

VERIFY BEFORE FOLD-IN: re-read repoauditor's actual CandidateFinding definition
and matching.py contract at graduation time; treat the fields below as a snapshot
that may be stale.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RecoverabilityClass(str, Enum):
    """How exposed a located weak-RNG usage is."""
    PROVEN = "proven"            # state recovered + forward/backward tokens demonstrated
    LIKELY = "likely"            # idiom matches a known-recoverable pattern, no live demo run
    POSSIBLE = "possible"        # predictable generator in a security context, needs analyst review


@dataclass(frozen=True)
class Citation:
    """Everything a finding asserts must trace to a source. Mirrors the
    citations repoauditor attaches to every finding."""
    source: str                  # e.g. "spawnmason/randar-explanation" or a demo-run id
    locator: str                 # section / URL / demonstration artifact path
    note: str = ""


@dataclass(frozen=True)
class RecoveryDemonstration:
    """The corroborating evidence that licenses a severity upgrade. This is a
    reproducible artifact, not an opinion: given N observed outputs, the recovered
    state predicts these next-K and prior-K outputs, verified against held-back
    ground truth."""
    observations_used: int
    recovered_state_present: bool
    predicted_next: list[int] = field(default_factory=list)
    predicted_prev: list[int] = field(default_factory=list)
    verified: bool = False       # matched held-back outputs


@dataclass(frozen=True)
class WeakRngCandidateFinding:
    """The record the fold-in emits into repoauditor's detect->triage flow.

    Mirror of repoauditor's CandidateFinding shape (rule id, location, message,
    trust-boundary tag, citations) plus the RNG-specific demonstration payload
    that acts as the corroborating source.
    """
    rule_id: str                 # e.g. "weak-rng/session-token-java-util-random"
    message: str
    # location is a placeholder in the standalone lab; repoauditor supplies the
    # real (path, line, snippet) from its retrieval layer.
    location_placeholder: str
    trust_boundary: str          # e.g. "auth", "reset-flow", "csrf-token"
    recoverability: RecoverabilityClass
    citations: list[Citation]
    demonstration: RecoveryDemonstration | None = None
    # severity is intentionally ABSENT: repoauditor's normalize/adjudicate owns
    # severity and its corroboration-licensing rule. The adapter proposes evidence,
    # it does not assign or upgrade severity.
