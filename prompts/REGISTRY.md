# Prompt registry

Versioned prompts are append-only. Never edit a prompt in place; supersede it with
a new version and record the change here. The report attributes its prose to the
prompt version that produced it.

| version | file | status | notes |
|---|---|---|---|
| report_synthesis v1 | report_synthesis_v1.md | active | initial narrative prompt; deterministic tables in, prose out, no numbers invented |

## Change discipline
- A new prompt version is a new file (`*_v2.md`) + a row here. The old file stays.
- Benchmark a new version against the prior on a fixed run before making it active
  (mirror repoauditor: prompt versions are not "active" until benchmarked, not just
  exercised).
