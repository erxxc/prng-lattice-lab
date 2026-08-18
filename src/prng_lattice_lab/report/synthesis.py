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

    lines.append("## Phase diagram: unique-recovery rate by (bits per call × observations)\n")
    lines.append(_phase_table(cells))
    lines.append("\n_Legend: `x/y` unique recoveries / trials · `*` collisions present "
                 "(see recoverability edge) · `—` underdetermined (n·k<48, no unique state "
                 "exists) · `·` capability gap._\n")

    lines.append("\n## Round-off margin grid: mean ‖M·e‖∞\n")
    lines.append(_margin_grid(cells))
    lines.append("\n_The 0.5 crossing (`*` = ≥0.5) is the round-off → enumeration "
                 "boundary. A small margin is necessary but not sufficient: an "
                 "underdetermined cell can show a small margin yet have no unique state._\n")

    edge = _edge_table(cells)
    if edge:
        lines.append("\n## Recoverability edge: cells with genuine collisions\n")
        lines.append("_At n·k ≈ 48 the leak stops distinguishing every state; more than "
                     "one java.util.Random state is consistent. Reported as a range, not "
                     "collapsed to one answer._\n")
        lines.append(edge)

    under = sorted({(c["bits_per_call"], c["num_observations"])
                    for c in cells if c.get("outcome") == "underdetermined"})
    if under:
        lines.append(f"\n## Underdetermined region\n\n{len(under)} cells have n·k < 48 "
                     "leaked bits < the 48-bit secret, so no unique state exists "
                     "(≈2^(48−n·k) states share each observation vector). Not a solver "
                     "limitation — an information-theoretic floor; no recovery attempted.\n")

    gaps = [c for c in cells if c.get("capability_gap")]
    if gaps:
        lines.append("\n## Capability gaps (disclosed, not hidden)\n")
        for g in sorted({c["capability_gap"] for c in gaps}):
            n = sum(1 for c in gaps if c["capability_gap"] == g)
            lines.append(f"- {n} cells: {g}")

    lines.append("\n---\n_Deterministic report. Narrative prose (if any) is "
                 "appended separately and attributed to a versioned prompt._\n")
    return "\n".join(lines)


def _grid_axes(cells: list[dict]):
    bits = sorted({c["bits_per_call"] for c in cells})
    samples = sorted({c["num_observations"] for c in cells})
    idx = {(c["bits_per_call"], c["num_observations"]): c for c in cells}
    return bits, samples, idx


def _phase_table(cells: list[dict]) -> str:
    bits, samples, idx = _grid_axes(cells)
    rows = ["| bits\\obs | " + " | ".join(str(s) for s in samples) + " |",
            "|" + "---|" * (len(samples) + 1)]
    for b in bits:
        vals = []
        for s in samples:
            c = idx.get((b, s))
            outcome = c.get("outcome") if c else None
            if c is None or outcome == "gap":
                vals.append("·")
            elif outcome == "underdetermined":
                vals.append("—")
            else:
                mark = "*" if outcome == "ambiguous" else ""
                vals.append(f"{c['successes']}/{c['trials']}{mark}")
        rows.append(f"| {b} | " + " | ".join(vals) + " |")
    return "\n".join(rows)


def _fmt_margin(m: float) -> str:
    if m == 0:
        return "0"
    return f"{m:.2g}"


def _margin_grid(cells: list[dict]) -> str:
    bits, samples, idx = _grid_axes(cells)
    rows = ["| bits\\obs | " + " | ".join(str(s) for s in samples) + " |",
            "|" + "---|" * (len(samples) + 1)]
    for b in bits:
        vals = []
        for s in samples:
            c = idx.get((b, s))
            m = c.get("mean_margin") if c else None
            if m is None:
                vals.append("·")
            else:
                vals.append(_fmt_margin(m) + ("*" if m >= 0.5 else ""))
        rows.append(f"| {b} | " + " | ".join(vals) + " |")
    return "\n".join(rows)


def _edge_table(cells: list[dict]) -> str:
    edge = [c for c in cells if c.get("outcome") == "ambiguous"]
    if not edge:
        return ""
    edge.sort(key=lambda c: (c["bits_per_call"], c["num_observations"]))
    rows = ["| bits | obs | n·k | unique/trials | mean consistent states |",
            "|---|---|---|---|---|"]
    for c in edge:
        nk = c["bits_per_call"] * c["num_observations"]
        mc = c.get("mean_candidates")
        mc_s = f"{mc:.2f}" if mc is not None else "·"
        rows.append(f"| {c['bits_per_call']} | {c['num_observations']} | {nk} | "
                    f"{c['successes']}/{c['trials']} | {mc_s} |")
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
