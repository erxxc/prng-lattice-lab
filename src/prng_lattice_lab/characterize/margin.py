"""
The round-off margin surface: mean ||M.e||_inf across the (bits x observations) grid,
and where it crosses the 0.5 round-off-safety threshold.

This is the closed-form-checkable calibration exercise flagged as the transfer into
repoauditor's risk-quant calibration work -- here you know ground truth exactly, so
it is the clean oracle to validate coverage machinery against before applying it to
noisy real data (see characterize/calibration.py).

recover.roundoff.margin() / recover.lattice.margin_top_bits() produce the per-
measurement margin; the sweep aggregates it to a per-cell mean. This module is a
pure READ projection over those stored cells (no re-running of trials): it exposes
the full 2-D surface (the old version keyed by bits alone, which was lossy since the
margin depends on BOTH axes) and locates the threshold crossing per observation
count.

Accepts either sweep `CellResult` objects or `store.list_cells` dict rows.
"""
from __future__ import annotations

ROUNDOFF_SAFE = 0.5  # ||M.e||_inf < 0.5  => Babai round-off lands on the true lattice point


def _get(cell, key):
    return cell[key] if isinstance(cell, dict) else getattr(cell, key)


def margin_surface(cells) -> dict[tuple[int, int], float]:
    """{(bits_per_call, num_observations): mean_margin} for cells that produced one."""
    return {
        (_get(c, "bits_per_call"), _get(c, "num_observations")): _get(c, "mean_margin")
        for c in cells
        if _get(c, "mean_margin") is not None
    }


def margin_curve(cells, num_observations: int | None = None):
    """Margin as a function of leak width.

    With `num_observations`: the `[(bits, margin), ...]` slice for that observation
    count, ascending in bits (a single monotone curve). Without it: the full surface
    as sorted `[((bits, obs), margin), ...]`. Either way non-lossy -- unlike the
    earlier bits-only keying, which silently collapsed every observation count.
    """
    surface = margin_surface(cells)
    if num_observations is not None:
        return sorted((b, m) for (b, o), m in surface.items() if o == num_observations)
    return sorted(surface.items())


def roundoff_boundary(cells, threshold: float = ROUNDOFF_SAFE) -> list[dict]:
    """Locate the margin=threshold crossing along the bits axis, per observation count.

    For a fixed observation count the mean margin falls as bits_per_call rises, so the
    crossing (if any) is the bits value where mean margin drops below `threshold` --
    the round-off/enumeration boundary H2 predicts. When the mean margin stays below
    `threshold` across the whole measured range (as it does on the default grid, where
    round-off is mean-safe everywhere and uniqueness -- not round-off -- is the real
    limiter), that is reported explicitly rather than invented.

    Reports the crossing as a bracket (rule 8: a range, never a single fabricated
    number): the two measured bits values that straddle it, plus a linear-interpolated
    estimate between them.
    """
    by_obs: dict[int, list[tuple[int, float]]] = {}
    for (b, o), m in margin_surface(cells).items():
        by_obs.setdefault(o, []).append((b, m))

    out: list[dict] = []
    for o in sorted(by_obs):
        pts = sorted(by_obs[o])  # ascending bits; margin descends across it
        crossing = low = high = None
        note = ""
        for (b0, m0), (b1, m1) in zip(pts, pts[1:]):
            if m0 >= threshold > m1:
                frac = (m0 - threshold) / (m0 - m1) if m0 != m1 else 0.0
                crossing = b0 + frac * (b1 - b0)
                low, high = b0, b1
                break
        if crossing is None:
            max_margin = max(m for _, m in pts)
            if max_margin < threshold:
                note = (f"mean margin stays below {threshold} across all measured bits "
                        f"(max {max_margin:.3g}); round-off mean-safe throughout this range")
            else:
                note = (f"mean margin stays at/above {threshold} across all measured bits "
                        f"(min {min(m for _, m in pts):.3g}); enumeration-dominated range")
        out.append({
            "num_observations": o,
            "crossing_bits": crossing,
            "bracket_low_bits": low,
            "bracket_high_bits": high,
            "note": note,
        })
    return out
