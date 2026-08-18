"""
weak_rng_adapter: the repoauditor fold-in.

Two responsibilities, matching how repoauditor's deterministic adapters work:
  1. DETECT (deterministic, pending): pattern-match predictable-RNG idioms in the
     target's source -- un-seeded `new Random()` / `Math.random()` /
     `RandomStringUtils.random*` feeding a security context (session tokens, reset
     codes, CSRF/nonce values). This half needs repoauditor's retrieval layer and
     is stubbed here.
  2. DEMONSTRATE (complete for the 3-float / clean top-bits case): when observed
     outputs are available, actually recover the state and produce a
     RecoveryDemonstration -- the corroborating evidence that licenses a severity
     upgrade under repoauditor's rules.

The demonstration half reuses the VALIDATED recover.roundoff path directly, so
the fold-in inherits the passing Randar test vector. That is the whole point of
building the lab against this contract from the start.
"""
from __future__ import annotations

from prng_lattice_lab.adapt.contract import (
    Citation,
    RecoverabilityClass,
    RecoveryDemonstration,
    Severity,
    WeakRngCandidateFinding,
)
from prng_lattice_lab.lcg import JavaRandom, step, step_back
from prng_lattice_lab.recover import roundoff

_RANDAR_CITE = Citation(
    source="spawnmason/randar-explanation",
    locator="https://github.com/spawnmason/randar-explanation#lattice-reduction",
    note="Truncated-LCG state recovery via LLL round-off; method basis.",
)


def demonstrate_from_msb24(observations: list[int], predict_k: int = 3) -> RecoveryDemonstration:
    """Given >=3 top-24-bit observations from consecutive nextFloat calls, recover
    the state and predict the next/prev K outputs. This is reproducible evidence.

    Only the 3-consecutive case is wired (uses the validated cracker). Longer
    observation runs and other widths route through recover.lattice once built.
    """
    if len(observations) < 3:
        return RecoveryDemonstration(observations_used=len(observations),
                                     recovered_state_present=False)
    m1, m2, m3 = observations[:3]
    post_first = roundoff.crack_three_floats_msb(m1, m2, m3)
    if post_first is None:
        return RecoveryDemonstration(observations_used=3, recovered_state_present=False)

    # Forward prediction: continue stepping from the state after the 3rd observation.
    fwd = JavaRandom.from_internal_state(step(step(post_first)))  # state after m3
    predicted_next = [fwd.next(24) for _ in range(predict_k)]

    # Backward prediction: step the pre-call state backwards.
    pre = roundoff.recover_pre_call_state(m1, m2, m3)
    predicted_prev = []
    if pre is not None:
        s = pre
        for _ in range(predict_k):
            s = step_back(s)
            predicted_prev.append(s >> 24)

    return RecoveryDemonstration(
        observations_used=3, recovered_state_present=True,
        predicted_next=predicted_next, predicted_prev=predicted_prev,
        verified=False,  # caller verifies against held-back outputs
    )


def reconstruct_stream(window: list[int], offset: int, total_length: int) -> list[int] | None:
    """Reconstruct an ENTIRE stream of nextFloat top-24-bit tokens from a 3-token
    window captured at position `offset`.

    `window` are three consecutive observed tokens; token at stream index `offset`
    is `window[0]`. Returns the full `[token_0, ..., token_{total_length-1}]`,
    including every token issued BEFORE the window (retroactive recovery) and after
    it. Returns None if the window is inconsistent with any LCG run (garbage guard).

    This is the concrete predictable-token threat: capturing a handful of consecutive
    tokens exposes the whole history and future of the generator. Uses the validated
    round-off cracker, so it needs no lattice backend.
    """
    if len(window) < 3 or offset < 0 or offset + 3 > total_length:
        return None
    s1 = roundoff.crack_three_floats_msb(window[0], window[1], window[2])
    if s1 is None:  # inconsistent window (e.g. not from consecutive nextFloat calls)
        return None
    recon = [0] * total_length
    # s1 is the state AFTER the call that produced window[0] (== token at `offset`).
    s = s1
    for i in range(offset, total_length):     # the window onward
        recon[i] = s >> 24
        s = step(s)
    s = s1
    for i in range(offset - 1, -1, -1):        # everything issued earlier
        s = step_back(s)
        recon[i] = s >> 24
    return recon


def demonstrate_retroactive(true_pre_stream_state: int, total_tokens: int,
                            window_offset: int, window_size: int = 3) -> RecoveryDemonstration:
    """Self-contained, VERIFIED retroactive demonstration.

    A java.util.Random at a known internal state issues `total_tokens` nextFloat
    top-24-bit tokens. An attacker who captures only a `window_size`-token window at
    `window_offset` recovers the state and reconstructs every token -- crucially the
    ones issued BEFORE the window. `verified` is set from an exact check against the
    issued stream, so this is reproducible evidence, not a claim.

    `predicted_prev` carries the retroactively recovered earlier tokens (in stream
    order); `predicted_next` the later ones.
    """
    gen = JavaRandom.from_internal_state(true_pre_stream_state)
    issued = [gen.next(24) for _ in range(total_tokens)]
    window = issued[window_offset:window_offset + window_size]
    recon = reconstruct_stream(window, window_offset, total_tokens)
    if recon is None:
        return RecoveryDemonstration(observations_used=window_size, recovered_state_present=False)
    return RecoveryDemonstration(
        observations_used=window_size,
        recovered_state_present=True,
        predicted_prev=recon[:window_offset],                       # issued BEFORE the window
        predicted_next=recon[window_offset + window_size:],         # issued AFTER the window
        verified=(recon == issued),
    )


def build_finding(*, title: str, file: str, line_start: int, line_end: int,
                  citation_snippet: str, trust_boundary_ref: str | None = None,
                  identity_key: str | None = None,
                  demonstration: RecoveryDemonstration | None = None) -> WeakRngCandidateFinding:
    """Assemble the candidate finding repoauditor's detect->triage flow consumes,
    in the corrected CandidateFinding shape (concrete location, source_tool,
    confidence, identity_key).

    The adapter proposes a conservative INITIAL severity; it never upgrades it --
    repoauditor's normalize/adjudicate owns upgrades, and the RecoveryDemonstration
    is offered as the independent corroborating source that may license one.
    """
    proven = bool(demonstration and demonstration.recovered_state_present)
    return WeakRngCandidateFinding(
        title=title,
        file=file,
        line_start=line_start,
        line_end=line_end,
        citation_snippet=citation_snippet,
        confidence=0.9 if proven else 0.5,
        severity=Severity.MEDIUM,          # conservative initial; normalize owns upgrades
        source_tool="weak_rng",
        identity_key=identity_key,
        trust_boundary_ref=trust_boundary_ref,
        rationale=("Predictable RNG in a security context; internal state recoverable "
                   "from observed outputs."
                   + (" Recovery demonstrated (next/prev tokens predicted)." if proven else "")),
        recoverability=RecoverabilityClass.PROVEN if proven else RecoverabilityClass.LIKELY,
        demonstration=demonstration,
        citations=[_RANDAR_CITE],
    )


def detect_in_source(repo_root: str) -> list[WeakRngCandidateFinding]:
    """DETECT half -- pending repoauditor retrieval integration."""
    raise NotImplementedError(
        "Source-level idiom detection depends on repoauditor's retrieval layer "
        "(tree-sitter JS/TS/Java/Ruby + Python ast). Build inside repoauditor "
        "against the live CandidateFinding contract; use adapt.contract as the spec."
    )
