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
    ENUMERATE = "enumerate"        # branch-and-bound over the reduced lattice (starved leak)
    AUTO = "auto"                  # pick per-cell based on predicted margin


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

    def total_leaked_bits(self) -> int:
        return self.bits_per_call * self.num_observations

    def is_overdetermined(self, secret_bits: int = 48) -> bool:
        return self.total_leaked_bits() >= secret_bits


@dataclass(frozen=True)
class SweepConfig:
    """The full grid to characterise."""
    bits_axis: tuple[int, ...] = (2, 4, 8, 12, 16, 20, 24)
    samples_axis: tuple[int, ...] = (2, 3, 4, 6, 8, 12, 16)
    trials_per_cell: int = 200
    method: RecoverMethod = RecoverMethod.AUTO
    seed: int = 0                        # RNG seed for reproducible ground-truth draws
    generator: GeneratorSpec = field(default_factory=GeneratorSpec)
