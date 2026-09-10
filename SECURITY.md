# Security policy

## Scope and nature of this project

prng-lattice-lab is a **closed, offline security-research harness**. It attacks a
pseudo-random generator (`java.util.Random`, and Python's MT19937 as a contrast) that
**it instantiates itself**. There is no network client, no server, no live target, and no
third-party system in scope. It exists to *detect and demonstrate* predictable-token
weaknesses in code under review (the fold-in to
[RepoAuditor](https://github.com/erxxc/repoauditor) as a `weak_rng_adapter`).

## Reporting a vulnerability

Report suspected vulnerabilities **in this tool** privately, not in public issues:

- Preferred: GitHub **private security advisories** — the repository's *Security* tab →
  *Report a vulnerability*.
- Alternatively, contact the maintainer privately. <!-- TODO(before production DOI):
     add a monitored security contact email if you want one beyond GitHub advisories. -->

Please include a minimal reproduction and the affected version/commit. There is no bounty;
this is a research tool.

## Responsible use

The demonstrations recover the internal state of a generator **you control** (seeded by the
lab or by your own test) and predict its outputs. That is the point: it turns "this token
looks predictable" into reproducible evidence.

- Do **not** use this against systems you do not own or are not explicitly authorized to
  test. Predicting another party's session tokens, reset codes, nonces, or identifiers
  without authorization is likely illegal and is not endorsed here.
- What is **demonstrated** is state recovery from observations of a generator under the
  stated conditions. It is **not** a claim that any specific deployed system exposes those
  observations across a trust boundary — establishing that link is the reviewer's job. Each
  emitted `DemonstrationArtifact` carries this claim boundary explicitly.

## Supported versions

This is research software released for citation and reuse; only the latest tagged release
is "supported". Fixes land on `main` and are picked up by the next tag.
