"""
Leak models: how a run of the generator becomes a set of partial observations of
its internal state. This is the x-axis machinery of the phase diagram.

TOP_BITS is complete and validated (it is what the Randar path consumes).
NEXTINT_ODD and BIT_LENGTH are specified but not yet implemented -- they are the
routes to the elttam (odd-bound RandomStringUtils) and Minerva (bit-length) ends
of the family respectively.
"""
from __future__ import annotations

from prng_lattice_lab.config import LeakModel, LeakProfile
from prng_lattice_lab.lcg import JavaRandom


def observe(rng: JavaRandom, profile: LeakProfile) -> list[int]:
    """Draw `profile.num_observations` outputs and return the leaked integers.

    For TOP_BITS: returns the top `bits_per_call` bits of each successive state
    (the direct measurement the lattice consumes). call_stride>1 discards
    (stride-1) calls between observations.
    """
    if profile.model is LeakModel.TOP_BITS:
        out: list[int] = []
        for _ in range(profile.num_observations):
            val = rng.next(profile.bits_per_call)
            for _ in range(profile.call_stride - 1):
                rng.next(profile.bits_per_call)  # skipped (unobserved) calls
            out.append(val)
        return out
    if profile.model is LeakModel.NEXTINT_ODD:
        raise NotImplementedError(
            "Odd-bound nextInt leak model pending -- the elttam/RandomStringUtils "
            "case. Must model the modulo bias so the solver sees the correct "
            "surviving-bit constraints."
        )
    if profile.model is LeakModel.BIT_LENGTH:
        raise NotImplementedError(
            "Bit-length leak model pending -- the Minerva/HNP analogue. This is the "
            "starved-leak stretch goal that exercises recover.enumerate."
        )
    raise ValueError(f"unknown leak model {profile.model!r}")


# --- Randar item-drop reconstruction (complete) ---------------------------------

def item_drop_to_floats(drop_x: float, drop_y: float, drop_z: float) -> list[float] | None:
    """Invert the Minecraft item-drop transform to recover the three exact
    nextFloat outputs. offset = f*0.5F + 0.25 within the block.

    Returns None if the coordinates fall outside the valid (0,1) drop window,
    which flags a false positive (item dropped from an inventory, not mined) --
    the same guard the reference exploit uses.
    """
    import math

    def _inv(coord: float) -> float:
        return (float(coord - math.floor(coord) - 0.25)) * 2.0

    fx, fy, fz = _inv(drop_x), _inv(drop_y), _inv(drop_z)
    for f in (fx, fy, fz):
        if f <= 0.0 or f >= 1.0:
            return None
    return [fx, fy, fz]
