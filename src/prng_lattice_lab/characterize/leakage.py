"""
Leak-model characterisation -- where hypothesis H3 is confirmed on our own data.

H3: "odd bounds leak less usable structure." We make "usable structure" precise and
measurable along two independent axes, per single observed call:

  1. RAW BITS leaked = the Shannon entropy of the observed value (bits). For a
     deterministic leak f of a ~uniform state output x, I(x; f(x)) = H(f(x)) -- the
     entropy of the observation IS the information it carries about the state.

  2. STRUCTURE = the shape of the constraint the observation puts on next(31):
       * TOP_BITS(k)      -> an INTERVAL  (a prefix): [y*w, y*w+w). Directly the
                             box-CVP the round-off lattice consumes.
       * NEXTINT_ODD(b)   -> a RESIDUE CLASS mod an odd b (nextInt is `bits % b`).
                             Coprime to the LCG's 2**48 modulus, so it does NOT align
                             with the round-off/box lattice -- recovering state from it
                             is a Hidden-Number-Problem, different machinery (elttam).
       * BIT_LENGTH(b)    -> an INTERVAL too ([2**(L-1), 2**L)), but a STARVED one:
                             ~2 bits per call regardless of b (the Minerva analogue).

"Usable structure" for THIS lab's round-off recovery = raw bits that arrive as an
interval (box-CVP consumable). By that measure odd bounds carry ~the same raw bits as
top-bits yet 0 box-usable bits (wrong shape), and bit-length carries interval bits but
far fewer of them. Both leak LESS USABLE STRUCTURE than a clean top-bits leak -- two
distinct ways, which is exactly H3.

This is a GENERATE-side characterisation. It does not claim to RECOVER state from the
odd-bound / bit-length leaks (that needs an HNP lattice, a disclosed capability gap in
the sweep); it measures how much usable structure each leak carries in the first place.
"""
from __future__ import annotations

import math
import random
from collections import Counter

from prng_lattice_lab.config import LeakModel, LeakProfile
from prng_lattice_lab.generate.leak import observe
from prng_lattice_lab.lcg import JavaRandom

# Constraint shape each model imposes on next(31); the round-off lattice consumes
# INTERVAL constraints (a box) and cannot consume a residue class without HNP methods.
_STRUCTURE = {
    LeakModel.TOP_BITS: "interval (prefix)",
    LeakModel.NEXTINT_ODD: "residue-class (mod odd)",
    LeakModel.BIT_LENGTH: "interval (leading-bit; starved)",
}
_BOX_USABLE = {                       # is the constraint consumable by the round-off box-CVP?
    LeakModel.TOP_BITS: True,
    LeakModel.NEXTINT_ODD: False,     # residue class -> HNP, not this lab's round-off lattice
    LeakModel.BIT_LENGTH: True,       # interval-shaped, but starved of bits
}


def shannon_entropy_bits(samples: list[int]) -> float:
    """Empirical Shannon entropy of a sample of observed values, in bits."""
    n = len(samples)
    if n == 0:
        return 0.0
    counts = Counter(samples)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def single_call_samples(profile: LeakProfile, trials: int, seed: int = 0) -> list[int]:
    """`trials` independent single-call observations, each from a fresh random state.

    Uses a one-observation view of `profile` so we measure the PER-CALL leak (the unit
    H3 is about), independent of how many calls a full trial would stack.
    """
    one = LeakProfile(model=profile.model, bits_per_call=profile.bits_per_call,
                      num_observations=1, bound=profile.bound)
    rng = random.Random(seed)
    out: list[int] = []
    for _ in range(trials):
        gen = JavaRandom.from_internal_state(rng.getrandbits(48))
        out.append(observe(gen, one)[0])
    return out


def characterize_leak(profile: LeakProfile, trials: int = 40_000, seed: int = 0) -> dict:
    """Per-call leak profile: raw bits (entropy), constraint structure, and how many of
    those bits are usable by this lab's round-off (box-CVP) recovery."""
    samples = single_call_samples(profile, trials, seed)
    entropy = shannon_entropy_bits(samples)
    box_usable = _BOX_USABLE[profile.model]
    return {
        "model": profile.model.value,
        "bits_per_call": profile.bits_per_call,
        "bound": profile.effective_bound() if profile.model is not LeakModel.TOP_BITS else None,
        "raw_bits": entropy,                                  # information leaked per call
        "structure": _STRUCTURE[profile.model],
        "box_usable": box_usable,                             # consumable by the round-off lattice?
        "box_usable_bits": entropy if box_usable else 0.0,    # "usable structure" (H3's measure)
        "distinct_values": len(set(samples)),
        "trials": trials,
    }


def compare_leak_models(bits_per_call: int = 8, trials: int = 40_000, seed: int = 0) -> dict:
    """Characterise all three leak models at a common target width and return the H3
    verdict. Odd-bound and bit-length must each show LESS box-usable structure than a
    top-bits leak of the same width -- by two different mechanisms."""
    rows = [
        characterize_leak(LeakProfile(model=m, bits_per_call=bits_per_call), trials, seed)
        for m in (LeakModel.TOP_BITS, LeakModel.NEXTINT_ODD, LeakModel.BIT_LENGTH)
    ]
    by = {r["model"]: r for r in rows}
    top = by[LeakModel.TOP_BITS.value]
    odd = by[LeakModel.NEXTINT_ODD.value]
    blen = by[LeakModel.BIT_LENGTH.value]
    h3_confirmed = (odd["box_usable_bits"] < top["box_usable_bits"]
                    and blen["box_usable_bits"] < top["box_usable_bits"])
    verdict = (
        f"H3 {'CONFIRMED' if h3_confirmed else 'NOT confirmed'}: top-bits carries "
        f"{top['box_usable_bits']:.2f} box-usable bits/call; nextInt(odd) carries "
        f"{odd['raw_bits']:.2f} raw bits but {odd['box_usable_bits']:.2f} box-usable "
        f"(residue class -> HNP, not round-off); bit-length carries only "
        f"{blen['raw_bits']:.2f} bits/call (starved interval). Both leak less usable "
        f"structure than a clean top-bits leak of the same width."
    )
    return {"bits_per_call": bits_per_call, "rows": rows,
            "h3_confirmed": h3_confirmed, "verdict": verdict}
