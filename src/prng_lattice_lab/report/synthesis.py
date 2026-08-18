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

import json
from pathlib import Path

from prng_lattice_lab.characterize import calibration, margin


def _validate_cells(cells: list[dict], schema_path: str) -> None:
    """Re-validate every stored cell against SweepCell before it is trusted into a
    deliverable. The store validates on write; this is the read-side re-check the
    report contract promises, so a hand-edited DB cannot smuggle a malformed row
    into a report. Full validation via jsonschema when available; a required-field
    fallback (mirroring store/db.py) otherwise. Fails loud on the first bad cell.
    """
    with open(schema_path, "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    try:
        subschema = schema["$defs"]["SweepCell"]
    except KeyError as exc:
        raise ValueError(f"schema {schema_path} has no $defs.SweepCell") from exc

    try:
        import jsonschema
        validator = jsonschema.Draft202012Validator(subschema)
    except ImportError:
        validator = None
    required = subschema.get("required", [])

    for i, cell in enumerate(cells):
        label = (f"cell bits={cell['bits_per_call']} obs={cell['num_observations']}"
                 if isinstance(cell, dict) and "bits_per_call" in cell and "num_observations" in cell
                 else f"cell #{i}")
        if validator is not None:
            errors = sorted(validator.iter_errors(cell), key=lambda e: list(e.path))
            if errors:
                raise ValueError(f"{label} fails SweepCell schema: {errors[0].message}")
        else:
            missing = [k for k in required if k not in cell]
            if missing:
                raise ValueError(f"{label} missing required SweepCell fields: {missing}")


def render_markdown(cells: list[dict], *, schema_path: str, run_meta: dict) -> str:
    """Build the deterministic report body from stored cells. No model, no prose
    beyond fixed captions -- every number here traces to a SweepCell (re-validated
    against `schema_path` on entry, per the report's read-time contract)."""
    _validate_cells(cells, schema_path)
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

    lines.append(_boundary_section(cells))
    lines.append(_calibration_section(cells))

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


def _boundary_section(cells: list[dict]) -> str:
    """Recoverability vs. total leaked bits (H1) + the mean-margin boundary note (H2)."""
    rows = calibration.recovery_by_total_bits(cells)
    if not rows:
        return ""
    edge = next((r for r in rows if r["total_bits"] == calibration.SECRET_BITS), None)
    last_under = max((r["total_bits"] for r in rows if r["total_bits"] < calibration.SECRET_BITS),
                     default=None)
    first_full = min((r["total_bits"] for r in rows if r["mean_unique_recovery"] >= 0.999),
                     default=None)
    out = ["\n## Recoverability boundary (H1: total leaked bits)\n"]
    parts = []
    if last_under is not None:
        parts.append(f"0% unique recovery at or below n·k={last_under}")
    if edge is not None:
        parts.append(f"{edge['mean_unique_recovery']:.0%} at the n·k={calibration.SECRET_BITS} "
                     f"edge (mean {edge['mean_candidates']:.2f} consistent states)")
    if first_full is not None:
        parts.append(f"100% for n·k≥{first_full}")
    out.append("Unique recovery is governed by total leaked bits versus the 48-bit "
               "secret: " + "; ".join(parts) + ".\n")
    # The margin boundary (H2) -- honestly note where/whether it crosses 0.5.
    bounds = margin.roundoff_boundary(cells)
    surface = margin.margin_surface(cells)
    if bounds and surface and all(b["crossing_bits"] is None for b in bounds):
        max_margin = max(surface.values())
        if max_margin < margin.ROUNDOFF_SAFE:
            out.append(f"\n_Round-off margin (H2): mean ‖M·e‖∞ peaks at {max_margin:.3g} — below "
                       f"the 0.5 round-off-safety line across the entire measured grid — so the "
                       f"operative limiter is uniqueness (above), not round-off failure._\n")
    return "\n".join(out)


def _calibration_section(cells: list[dict]) -> str:
    """Exact-oracle coverage of the ideal-hash prediction against observed recovery."""
    cov = calibration.coverage(cells)
    if not cov["n_cells"]:
        return ""
    out = ["\n## Calibration: ideal-hash prediction vs. observed (exact-oracle coverage)\n"]
    out.append("The ideal-hash null predicts P(unique recovery)=0 for n·k<48 and "
               "exp(−2^(48−n·k)) above. Coverage = does that prediction fall inside a 95% "
               "Wilson interval for the observed rate? This is the closed-form oracle for the "
               "risk-quant coverage machinery.\n")
    regimes = cov["by_regime"]
    summary = " · ".join(f"{k} {v['covered']}/{v['n']}" for k, v in regimes.items())
    out.append(f"- Overall: **{cov['covered']}/{cov['n_cells']}** cells covered "
               f"({cov['coverage_fraction']:.0%}).")
    out.append(f"- By regime: {summary}.\n")
    misses = [c for c in cov["cells"] if not c["covered"]]
    if misses:
        out.append("The uncovered cells are exactly where the structured LCG departs from an "
                   "ideal hash — the recoverability edge:\n")
        rows = ["| bits | obs | n·k | predicted | observed | 95% CI |", "|---|---|---|---|---|---|"]
        for c in misses:
            rows.append(f"| {c['bits_per_call']} | {c['num_observations']} | {c['total_bits']} | "
                        f"{c['predicted']:.3f} | {c['observed']:.3f} | "
                        f"[{c['ci_low']:.3f}, {c['ci_high']:.3f}] |")
        out.append("\n".join(rows))
    return "\n".join(out)


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
