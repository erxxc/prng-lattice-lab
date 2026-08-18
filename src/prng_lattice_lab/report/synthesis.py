"""
Report synthesis. A pure READ projection over stored records -- report generation
never recomputes or mutates results (mirrors repoauditor: report is persist=False).

Split of responsibilities, matching repoauditor's report discipline:
  * DETERMINISTIC: the phase-diagram table, the margin curve, success rates,
    capability-gap disclosures. Built directly from stored SweepCell records. No
    model involved. These are the load-bearing quantitative claims.
  * NARRATIVE (prose only): rendered by an LLM from a VERSIONED prompt, given the
    already-computed deterministic tables. The prompt never computes numbers; it
    frames them.

INPUTS (as requested): this stage takes a `schema` and a `prompt` as explicit
inputs.
  * schema  -> schema/records.schema.json; records are validated against it before
               they are trusted into the report (store.db already validates on
               write; report re-checks on read so a hand-edited DB can't smuggle
               malformed records into a deliverable).
  * prompt  -> prompts/report_synthesis_v1.md (versioned; never edited in place --
               a new prompt is a new file + REGISTRY entry).

The LLM call is intentionally NOT implemented here (no key assumed in the
scaffold). render_markdown() produces the complete deterministic report today;
synthesize_narrative() is the hook that adds prose when a model is available, and
records which prompt version produced it (reproducibility "as of" block).
"""
from __future__ import annotations

from pathlib import Path


def render_markdown(cells: list[dict], *, schema_path: str, run_meta: dict) -> str:
    """Build the deterministic report body from stored cells. No model, no prose
    beyond fixed captions -- every number here traces to a SweepCell."""
    lines: list[str] = []
    lines.append("# Recoverability of java.util.Random under partial-state leakage\n")
    lines.append(f"_Run {run_meta.get('run_id')} · lab v{run_meta.get('lab_version')} "
                 f"· generated {run_meta.get('created_at')}_\n")
    lines.append("## Phase diagram: success rate by (bits per call × observations)\n")
    lines.append(_phase_table(cells))
    lines.append("\n## Round-off margin (where it exists)\n")
    lines.append(_margin_table(cells))
    gaps = [c for c in cells if c.get("capability_gap")]
    if gaps:
        lines.append("\n## Capability gaps (disclosed, not hidden)\n")
        seen = sorted({c["capability_gap"] for c in gaps})
        for g in seen:
            n = sum(1 for c in gaps if c["capability_gap"] == g)
            lines.append(f"- {n} cells: {g}")
    lines.append("\n---\n_Deterministic report. Narrative prose (if any) is "
                 "appended separately and attributed to a versioned prompt._\n")
    return "\n".join(lines)


def _phase_table(cells: list[dict]) -> str:
    bits = sorted({c["bits_per_call"] for c in cells})
    samples = sorted({c["num_observations"] for c in cells})
    idx = {(c["bits_per_call"], c["num_observations"]): c for c in cells}
    header = "| bits\\obs | " + " | ".join(str(s) for s in samples) + " |"
    sep = "|" + "---|" * (len(samples) + 1)
    rows = [header, sep]
    for b in bits:
        cellvals = []
        for s in samples:
            c = idx.get((b, s))
            if c is None or c.get("capability_gap"):
                cellvals.append("·")
            else:
                cellvals.append(f"{c['successes']}/{c['trials']}")
        rows.append(f"| {b} | " + " | ".join(cellvals) + " |")
    return "\n".join(rows)


def _margin_table(cells: list[dict]) -> str:
    rows = ["| bits per call | mean ‖M·e‖∞ | round-off safe (<0.5) |",
            "|---|---|---|"]
    seen = {}
    for c in cells:
        if c.get("mean_margin") is not None:
            seen[c["bits_per_call"]] = c["mean_margin"]
    for b in sorted(seen):
        m = seen[b]
        rows.append(f"| {b} | {m:.6f} | {'yes' if m < 0.5 else 'NO'} |")
    if len(rows) == 2:
        rows.append("| _(no cells produced a margin yet)_ | | |")
    return "\n".join(rows)


def synthesize_narrative(deterministic_md: str, *, prompt_path: str) -> str:
    """Hook for LLM-authored prose. Loads the versioned prompt, would call the
    model with the deterministic tables as context, and return prose tagged with
    the prompt version. Not wired in the scaffold (no key assumed)."""
    prompt_version = Path(prompt_path).stem
    raise NotImplementedError(
        f"Narrative synthesis pending model wiring. Would use prompt "
        f"'{prompt_version}' over the deterministic report. Deterministic "
        f"render_markdown() is complete and is the report of record until then."
    )
