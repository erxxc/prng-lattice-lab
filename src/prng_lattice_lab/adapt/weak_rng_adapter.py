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
    WeakRngCandidateFinding,
)
from prng_lattice_lab.lcg import JavaRandom, step
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
        from prng_lattice_lab.lcg import step_back
        s = pre
        for _ in range(predict_k):
            s = step_back(s)
            predicted_prev.append(s >> 24)

    return RecoveryDemonstration(
        observations_used=3, recovered_state_present=True,
        predicted_next=predicted_next, predicted_prev=predicted_prev,
        verified=False,  # caller verifies against held-back outputs
    )


def build_finding(rule_id: str, trust_boundary: str, location_placeholder: str,
                  demonstration: RecoveryDemonstration | None) -> WeakRngCandidateFinding:
    """Assemble the candidate finding repoauditor's detect->triage flow consumes.

    Recoverability class is set from whether a live demonstration succeeded; it
    does NOT set severity (repoauditor owns that).
    """
    if demonstration and demonstration.recovered_state_present:
        rc = RecoverabilityClass.PROVEN
    else:
        rc = RecoverabilityClass.LIKELY
    return WeakRngCandidateFinding(
        rule_id=rule_id,
        message="Predictable RNG in a security context; internal state recoverable "
                "from observed outputs.",
        location_placeholder=location_placeholder,
        trust_boundary=trust_boundary,
        recoverability=rc,
        citations=[_RANDAR_CITE],
        demonstration=demonstration,
    )


def detect_in_source(repo_root: str) -> list[WeakRngCandidateFinding]:
    """DETECT half -- pending repoauditor retrieval integration."""
    raise NotImplementedError(
        "Source-level idiom detection depends on repoauditor's retrieval layer "
        "(tree-sitter JS/TS/Java/Ruby + Python ast). Build inside repoauditor "
        "against the live CandidateFinding contract; use adapt.contract as the spec."
    )
