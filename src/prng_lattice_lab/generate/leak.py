"""
Leak models: how a run of the generator becomes a set of partial observations of
its internal state. This is the x-axis machinery of the phase diagram.

Three models, faithful to real Java idioms:
  * TOP_BITS   -- the top k bits of each state (nextFloat=24, pow2 nextInt=log2 bound).
                  An INTERVAL constraint: directly the box-CVP the round-off lattice
                  consumes. Complete + validated (the Randar path).
  * NEXTINT_ODD -- nextInt(odd bound): the value survives a modulo, so the constraint
                  is a RESIDUE CLASS mod an odd bound, not an interval (the elttam /
                  RandomStringUtils case). Coprime to the LCG's power-of-two modulus, so
                  it does not align with the round-off lattice -- recovery is HNP.
  * BIT_LENGTH -- only the bit-length of nextInt(bound) (the Minerva analogue). An
                  interval, but a starved one: ~2 bits per observation regardless of
                  bound, so many observations are needed.

All three are wired on the GENERATE side (observe() produces real measurements),
characterised for how much usable structure each carries (characterize/leakage.py --
this is where H3 is confirmed on our own data), and RECOVERED: TOP_BITS by the box
lattice (recover/lattice), NEXTINT_ODD by low-bit slicing + certified round-off
(recover/residue), BIT_LENGTH by an informative-subset lattice + complete enumeration
(recover/starved). Each solver is complete for its model; infeasible or
underdetermined trials are disclosed per trial in the sweep, never faked.
"""
from __future__ import annotations

from prng_lattice_lab.config import LeakModel, LeakProfile
from prng_lattice_lab.lcg import JavaRandom


def observe(rng: JavaRandom, profile: LeakProfile) -> list[int]:
    """Draw `profile.num_observations` outputs and return the leaked integers.

    TOP_BITS returns the top `bits_per_call` bits of each successive state (the direct
    measurement the lattice consumes). NEXTINT_ODD returns nextInt(odd bound) values
    (a residue-class leak). BIT_LENGTH returns the bit-length of nextInt(bound) values
    (a starved interval leak). call_stride>1 discards (stride-1) calls between
    observations for every model.
    """
    if profile.model is LeakModel.TOP_BITS:
        return _observe(profile, lambda: rng.next(profile.bits_per_call))
    if profile.model is LeakModel.NEXTINT_ODD:
        bound = profile.effective_bound()
        if bound % 2 == 0:
            raise ValueError(f"NEXTINT_ODD needs an odd bound; got {bound}")
        return _observe(profile, lambda: rng.next_int(bound))
    if profile.model is LeakModel.BIT_LENGTH:
        bound = profile.effective_bound()
        return _observe(profile, lambda: rng.next_int(bound).bit_length())
    raise ValueError(f"unknown leak model {profile.model!r}")


def _observe(profile: LeakProfile, draw) -> list[int]:
    """Run `num_observations` draws, discarding (call_stride-1) draws between each so
    every model shares the strided-observation geometry."""
    out: list[int] = []
    for _ in range(profile.num_observations):
        val = draw()
        for _ in range(profile.call_stride - 1):
            draw()  # skipped (unobserved) calls
        out.append(val)
    return out


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
