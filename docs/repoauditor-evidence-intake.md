# Proposal: corroborating-evidence intake for weak-RNG findings (repoauditor)

_Status: proposal for owner scoping (a new repoauditor optimization; not built).
Written from the lab side because the lab owns the evidence format; repoauditor owns
the intake decision and the severity policy._

## Problem

repoauditor's `weak_rng` / `weak_rng_py` detectors emit syntactic candidates at an
initial `MEDIUM`. `normalize/adjudicate` upgrades severity only under a license, and
the relevant license is **independent corroboration**: two distinct deterministic tools,
or a tool plus a lens, flagging the same matched issue (`matching.has_independent_
corroboration`). A reproducible state-recovery demonstration is exactly the
corroborating evidence the OPT-036 design named — but today there is no path by which
such a demonstration becomes a *source* on the finding. The detector's rationale text is
digest-bound (OPT-036 result), and PR #130's doc states repoauditor does not ingest lab
artifacts. So the evidence exists (the lab emits it) but cannot license anything.

## What the lab provides (built)

`prng-lattice-lab demonstrate {msb24|nextint_odd|seeded|mt19937|mt19937_truncated}` emits a
`DemonstrationArtifact` (`schema/records.schema.json`): kind, victim, the repoauditor
idiom ids it corroborates, parameters, lab version, the exact reproduction command,
citations, the predictions, an **exact verification against held-back ground truth**,
and a claim boundary. It additionally carries three things that matter for intake:

* **`oracle`** — `jvm` when the observed tokens came from a REAL OpenJDK
  `java.util.Random` process, not the lab's port (`lab_model` otherwise). A `jvm`
  artifact is evidence the recovery works on the actual generator the detector flags.
* **`certificate`** — the proof behind `verified`: for complete solvers a consistent-state
  `candidates` count (1 == certified unique), plus a false-match `coincidence_bound`
  ~2^(-bits·held_out_checked) (e.g. ~2^-176 for a verified nextInt(255) window), so
  "verified" is a quantified claim.
* **`content_sha256`** — a tamper-evident hash over the canonical record. Intake can call
  `demonstrate --verify FILE`, which re-checks the hash and RE-RUNS the demonstration
  from its recorded parameters, so the intake never has to trust the artifact's own flag.

An unverified artifact is emitted honestly (an ambiguous window gives `recovered=false`
with the candidate count) but must not corroborate. Artifacts are deterministic in their
seed, so a reviewer regenerates and re-checks them in seconds.

## Proposed intake (for scoping; three options, least invasive first)

1. **Reviewer-attached evidence as a source.** A CLI/`review/` action attaches a
   verified `DemonstrationArtifact` to a finding by identity key. Intake validates the
   artifact against the schema, re-runs its `reproduce` command in a sandbox (or
   requires `verified: true` plus a reviewer attestation), and records a second
   `CandidateFinding`-shaped source `source_tool = "weak_rng_demonstration"` on the same
   file/line/identity with the severity the reviewer asserts. adjudicate then sees a
   conflicting, corroborated group and applies its existing cap-at-strongest rule. No
   change to matching or adjudicate; no automatic ingestion; the human remains the
   trust anchor and the boundary "repoauditor does not run the lab" holds if the
   attestation route is chosen.
2. **Falsification route.** Treat a verified artifact as a *falsification confirmation*
   (the other existing license) of the hypothesis "this generator is unpredictable".
   Semantically closest to the evidence, but it stretches the meaning of falsification
   in adjudicate's current framing.
3. **Automatic corroboration.** repoauditor runs the demonstration itself during detect.
   Rejected for now: detection is static, observed tokens are never available in a repo
   scan, and it would violate the stated non-ingestion boundary.

## Governance notes

- Any of these is a new optimization (the ledger is frozen at 36/36 by the OPT-036
  result; admission is the owner's workflow).
- Option 1 touches `review/` and the store (a new source kind), not the digest-bound
  scanner seam.
- The artifact's claim boundary must be carried verbatim into the finding: it proves
  the generator class is recoverable from the stated observations; it does not prove
  the flagged code exposes those observations. The reviewer supplies that link.
