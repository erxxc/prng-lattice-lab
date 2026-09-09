"""
Typed configuration objects. These are the in-memory contracts; the on-disk
source of truth for record shapes is schema/records.schema.json (schema-first:
code validates against it, never the reverse).

No behaviour lives here beyond validation -- these are frozen dataclasses so a
run's parameters are immutable once captured into the store.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LeakModel(str, Enum):
    """How each observation exposes part of the internal state."""
    TOP_BITS = "top_bits"          # top-k bits of the state (nextFloat=24, nextInt pow2=k)
    NEXTINT_ODD = "nextint_odd"    # value of nextInt(bound) for odd bound (biased leak)
    BIT_LENGTH = "bit_length"      # bit-length of the value only (the Minerva/HNP analogue)


class RecoverMethod(str, Enum):
    ROUNDOFF = "roundoff"          # Babai round-off (fast, needs generous over-determination)
    ENUMERATE = "enumerate"        # complete box enumeration over the reduced lattice
    RESIDUE_SLICE = "residue_slice"        # nextInt(odd): low-bit slicing + certified round-off
    SUBSET_ENUMERATE = "subset_enumerate"  # bit-length: informative-subset lattice + enumeration
    AUTO = "auto"                  # pick per-cell based on the leak model / predicted margin


@dataclass(frozen=True)
class GeneratorSpec:
    """Which generator produced the data, and how its state was initialised."""
    kind: str = "java.util.Random"
    seeded_via: str = "internal_state"   # "internal_state" | "constructor"
    # world/domain constants are only relevant when reproducing full Randar
    # coordinate inversion; left None for the pure state-recovery experiment.
    world_seed: int | None = None


@dataclass(frozen=True)
class LeakProfile:
    """One point on the x-axis of the phase diagram."""
    model: LeakModel = LeakModel.TOP_BITS
    bits_per_call: int = 24              # e.g. 24 for nextFloat, log2(bound) for pow2 nextInt
    num_observations: int = 3            # consecutive calls observed
    call_stride: int = 1                 # 1 = consecutive; >1 = known gaps between observed calls
    noise: int = 0                       # max |error| on each top-k observation (0 = exact);
                                         # recovery widens the box by this bound (see recover.lattice)
    bound: int | None = None             # nextInt bound for NEXTINT_ODD / BIT_LENGTH; None -> a
                                         # default derived from bits_per_call (see effective_bound)

    def effective_bound(self) -> int:
        """nextInt bound used by the NEXTINT_ODD / BIT_LENGTH leak models.

        Defaults to a canonical bound of the target width: the largest ODD value with
        `bits_per_call` bits for NEXTINT_ODD (worst case for a power-of-two-modulus
        lattice -- coprime to 2), and 2**bits_per_call for BIT_LENGTH. Ignored by
        TOP_BITS. An explicit `bound` overrides (e.g. elttam's RandomStringUtils bounds).
        """
        if self.bound is not None:
            return self.bound
        if self.model is LeakModel.NEXTINT_ODD:
            return (1 << self.bits_per_call) - 1     # largest odd of this bit width
        return 1 << self.bits_per_call               # BIT_LENGTH: a clean power-of-two range

    def total_leaked_bits(self) -> int:
        return self.bits_per_call * self.num_observations

    def is_overdetermined(self, secret_bits: int = 48) -> bool:
        return self.total_leaked_bits() >= secret_bits


DEFAULT_BITS_AXIS: tuple[int, ...] = (2, 4, 8, 12, 16, 20, 24)
DEFAULT_SAMPLES_AXIS: tuple[int, ...] = (2, 3, 4, 6, 8, 12, 16)
# The bit-length leak is starved (~2 bits/call regardless of width), so its grid needs
# far more observations to reach the 48-bit edge; n<=16 is underdetermined throughout.
BIT_LENGTH_SAMPLES_AXIS: tuple[int, ...] = (8, 16, 24, 32, 48, 64)


def default_samples_axis(model: LeakModel) -> tuple[int, ...]:
    """Observation-count axis appropriate to a leak model's information rate."""
    return BIT_LENGTH_SAMPLES_AXIS if model is LeakModel.BIT_LENGTH else DEFAULT_SAMPLES_AXIS


@dataclass(frozen=True)
class SweepConfig:
    """The full grid to characterise (one leak model per run)."""
    bits_axis: tuple[int, ...] = DEFAULT_BITS_AXIS
    samples_axis: tuple[int, ...] = DEFAULT_SAMPLES_AXIS
    trials_per_cell: int = 200
    method: RecoverMethod = RecoverMethod.AUTO
    seed: int = 0                        # RNG seed for reproducible ground-truth draws
    generator: GeneratorSpec = field(default_factory=GeneratorSpec)
    model: LeakModel = LeakModel.TOP_BITS   # which leak the grid observes
