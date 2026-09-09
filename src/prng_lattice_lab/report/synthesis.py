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

render_markdown() produces the complete deterministic report unconditionally.
synthesize_narrative() adds prose when a model is reachable (the `anthropic` SDK
importable AND a key in the environment), and records which prompt version produced
it (reproducibility "as of" block). When no model is reachable it raises
NarrativeUnavailable -- a disclosed capability gap, never fabricated prose (rules 7
and 8: no faked results; uncertainty pauses rather than self-resolving).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from prng_lattice_lab.characterize import calibration, margin

# The narrative pass frames already-computed tables; a mid-tier model is plenty and
# keeps the optional prose cheap. Overridable at call time for reproducibility.
DEFAULT_NARRATIVE_MODEL = "claude-sonnet-5"


class NarrativeUnavailable(RuntimeError):
    """Raised when the optional LLM narrative pass cannot run (no SDK, no key, or
    the call failed). The deterministic report is always the report of record; this
    is disclosed as a capability gap, never papered over with invented prose."""


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
    model = run_meta.get("model") or _model_of(cells)
    lines: list[str] = []
    lines.append("# Recoverability of java.util.Random under partial-state leakage\n")
    lines.append(f"_Run {run_meta.get('run_id')} · lab v{run_meta.get('lab_version')} "
                 f"· generated {run_meta.get('created_at')} · leak model `{model}`: "
                 f"{_MODEL_BLURB.get(model, model)}_\n")

    lines.append("## Phase diagram: unique-recovery rate by (bits per call × observations)\n")
    lines.append(_phase_table(cells))
    lines.append("\n_Legend: `x/y` unique recoveries / SCORED trials · `*` collisions present "
                 "(see recoverability edge) · `—` underdetermined (leaked bits < 48, no unique "
                 "state exists) · `‡` infeasible within the enumeration budget (disclosed, not "
                 "attempted) · `·` capability gap. Trials skipped for a disclosed reason are "
                 "itemised under capability gaps._\n")

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
        lines.append(f"\n## Underdetermined region\n\n{len(under)} cells leak fewer than 48 "
                     "bits (n·k for top-bits, n·log2(bound) for nextInt(odd), the realized "
                     "sum of interval widths for bit-length) — less than the 48-bit secret, so "
                     "no unique state exists (≈2^(48−leaked) states share each observation "
                     "vector). Not a solver limitation — an information-theoretic floor; no "
                     "recovery attempted.\n")
    infeasible = sorted({(c["bits_per_call"], c["num_observations"])
                         for c in cells if c.get("outcome") == "infeasible"})
    if infeasible:
        lines.append(f"\n## Infeasible within budget\n\n{len(infeasible)} cells carry enough "
                     "information in principle but their complete enumeration would exceed the "
                     "budget (each lattice dimension multiplies the enumeration ball by ~2, and "
                     "a 1-bit observation cannot pay for its own dimension). Disclosed and not "
                     "attempted — a solver limit, distinct from the information floor.\n")

    gaps = [c for c in cells if c.get("capability_gap")]
    if gaps:
        lines.append("\n## Capability gaps and skipped trials (disclosed, not hidden)\n")
        for g in sorted({c["capability_gap"] for c in gaps}):
            n = sum(1 for c in gaps if c["capability_gap"] == g)
            lines.append(f"- {n} cells: {g}")

    lines.append("\n---\n_Deterministic report. Narrative prose (if any) is "
                 "appended separately and attributed to a versioned prompt._\n")
    return "\n".join(lines)


_MODEL_BLURB = {
    "top_bits": "top-k bits per call (nextFloat / power-of-two nextInt); solver = box lattice "
                "(round-off / complete enumeration)",
    "nextint_odd": "nextInt(odd bound) residue class, log2(bound) bits per call (the "
                   "RandomStringUtils idiom); solver = low-17-bit slicing + certified round-off "
                   "(recover/residue)",
    "bit_length": "bit-length of nextInt(2^k) only, ~2 bits per call (the Minerva analogue); "
                  "solver = informative-subset lattice + complete enumeration (recover/starved)",
}


def _model_of(cells: list[dict]) -> str:
    models = {c.get("model") or "top_bits" for c in cells}
    return models.pop() if len(models) == 1 else "mixed"


def _leaked(c: dict) -> float:
    lb = c.get("leaked_bits")
    return float(lb) if lb is not None else float(c["bits_per_call"] * c["num_observations"])


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
            elif outcome == "infeasible":
                vals.append("‡")
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
    rows = ["| bits | obs | leaked bits | unique/trials | mean consistent states |",
            "|---|---|---|---|---|"]
    for c in edge:
        nk = f"{_leaked(c):g}"
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
    out.append("The ideal-hash null predicts P(unique recovery)=0 below 48 leaked bits and "
               "exp(−2^(48−leaked)) above (leaked = n·k for top-bits, n·log2 b for nextInt(odd), "
               "the mean realized leak of scored trials for bit-length — a mean-field "
               "approximation there). Coverage = does that prediction fall inside a 95% "
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
        rows = ["| bits | obs | leaked bits | predicted | observed | 95% CI |", "|---|---|---|---|---|---|"]
        for c in misses:
            rows.append(f"| {c['bits_per_call']} | {c['num_observations']} | {c['total_bits']} | "
                        f"{c['predicted']:.3f} | {c['observed']:.3f} | "
                        f"[{c['ci_low']:.3f}, {c['ci_high']:.3f}] |")
        out.append("\n".join(rows))
    return "\n".join(out)


def _load_client():
    """Return (Anthropic client, resolved key source) or raise NarrativeUnavailable.

    The narrative pass is optional: the SDK is an optional dependency and the key is
    read from the environment. Either being absent is a disclosed gap, not an error
    in the pipeline -- the deterministic report stands on its own."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise NarrativeUnavailable(
            "ANTHROPIC_API_KEY not set; narrative prose skipped (deterministic report "
            "is complete and is the report of record)."
        )
    try:
        import anthropic  # optional dependency; deferred so the core path never needs it
    except ImportError as exc:
        raise NarrativeUnavailable(
            "anthropic SDK not installed; narrative prose skipped. "
            "Install the 'narrative' extra to enable it."
        ) from exc
    return anthropic.Anthropic(api_key=key)


def synthesize_narrative(
    deterministic_md: str,
    *,
    prompt_path: str,
    run_meta: dict,
    model: str = DEFAULT_NARRATIVE_MODEL,
    max_tokens: int = 2048,
) -> str:
    """LLM-authored prose over the already-computed deterministic report.

    Loads the VERSIONED prompt as the system instruction and passes the rendered
    deterministic report (which carries every table and disclosed gap) as the only
    evidence the model may cite -- the prompt forbids introducing any number not
    present in it. Returns the prose with a machine-checkable attribution line so the
    report records exactly which prompt version and model produced it.

    Raises NarrativeUnavailable when no model is reachable (no key / no SDK / API
    error). Callers disclose that as a capability gap; they never fabricate prose.
    """
    prompt_version = Path(prompt_path).stem
    system_prompt = Path(prompt_path).read_text(encoding="utf-8")
    client = _load_client()

    run_id = run_meta.get("run_id")
    user_content = (
        "Here is the complete DETERMINISTIC report for this run. It contains every "
        "table and every disclosed capability gap. Write only the narrative sections "
        "described in your instructions, citing only numbers that appear below. Do not "
        "restate the tables.\n\n"
        f"run_meta: {json.dumps(run_meta, default=str)}\n\n"
        "----- DETERMINISTIC REPORT -----\n"
        f"{deterministic_md}"
    )
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
    except Exception as exc:  # SDK/network/auth errors are all a disclosed gap, not a crash
        raise NarrativeUnavailable(f"narrative model call failed: {exc}") from exc

    prose = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text").strip()
    if not prose:
        raise NarrativeUnavailable("narrative model returned no text")

    # Guarantee the attribution line even if the model omits it, so the deliverable
    # always records the exact prompt version + model that produced its prose.
    attribution = f"_Narrative by {prompt_version} · model {model} · over run {run_id}._"
    first_line = prose.splitlines()[0] if prose.splitlines() else ""
    if prompt_version not in first_line:
        prose = f"{attribution}\n\n{prose}"
    return prose
