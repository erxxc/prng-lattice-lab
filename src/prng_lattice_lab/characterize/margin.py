"""
The round-off margin curve: ||M.e||_inf as a function of leak width.

This is the closed-form-checkable calibration exercise flagged as the transfer
into repoauditor's risk-quant calibration work -- here you know ground truth
exactly, so it is the clean oracle to validate coverage machinery against before
applying it to noisy real data.

recover.roundoff.margin() already returns the per-measurement margin for the
3-float case. This module aggregates it across a sweep axis and locates the
crossing of the 0.5 round-off-safety threshold.

NOT YET IMPLEMENTED beyond the 3-float aggregation hook -- extend once
recover.lattice exposes a general margin for other cell geometries.
"""
from __future__ import annotations


def margin_curve(cell_results) -> list[tuple[int, float]]:
    """(bits_per_call, mean_margin) for cells that produced a margin. The 0.5
    line is the round-off/enumeration boundary; below it, enumeration is required.
    """
    out = []
    for c in cell_results:
        if c.mean_margin is not None:
            out.append((c.bits_per_call, c.mean_margin))
    return sorted(set(out))
