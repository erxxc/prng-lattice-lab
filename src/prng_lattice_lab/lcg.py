"""
java.util.Random modelled exactly, plus forward/backward LCG stepping.

This is the ground-truth generator the whole lab attacks. It is a faithful
port of the OpenJDK `java.util.Random` LCG (the same one behind Minecraft's
`World.rand`, Apache Commons `RandomStringUtils`, and un-seeded `new Random()`
token generation).

Constants
    a  = 25214903917      (0x5DEECE66D)      multiplier
    b  = 11               (0xB)              addend
    m  = 2**48                               modulus
    a_inv = 246154705703781                  a^-1 mod 2**48  (a is odd => invertible)

Invariant: this module is CORRECTNESS-CRITICAL and covered by the Randar
published test vector (tests/test_lcg.py, tests/test_roundoff.py). Do not change
the transition constants or the bit-extraction semantics without re-validating
against that vector.
"""
from __future__ import annotations

MASK: int = (1 << 48) - 1
A: int = 25214903917
B: int = 11
A_INV: int = 246154705703781  # modular inverse of A mod 2**48


def step(state: int) -> int:
    """One forward LCG step: s -> (a*s + b) mod 2**48."""
    return (state * A + B) & MASK


def step_back(state: int) -> int:
    """One backward LCG step: s -> (s - b) * a^-1 mod 2**48. Exact inverse of step()."""
    return ((state - B) * A_INV) & MASK


class JavaRandom:
    """Bit-exact model of java.util.Random.

    Two construction paths, deliberately distinct:

    * ``JavaRandom(seed)``        -- mirrors ``new Random(seed)``; the public
      constructor SCRAMBLES via setSeed: this.seed = (seed ^ A) & MASK.
    * ``JavaRandom.from_internal_state(state)`` -- sets the raw 48-bit internal
      ``seed`` field directly, WITHOUT scrambling. Use this to reproduce a known
      internal state (e.g. the Randar worked example, internal state
      123123123123123).

    next(bits) advances the state BEFORE reading, then returns the top `bits`
    bits: (int)(seed >>> (48 - bits)). Every consumer (nextFloat, nextInt) is
    built on next(bits), so the "step-then-read" ordering matters for anyone
    reasoning about which state produced which output (see roundoff.py notes).
    """

    __slots__ = ("seed",)

    def __init__(self, seed: int):
        self.seed = (seed ^ A) & MASK

    @classmethod
    def from_internal_state(cls, state: int) -> "JavaRandom":
        r = cls.__new__(cls)
        r.seed = state & MASK
        return r

    def next(self, bits: int) -> int:
        self.seed = (self.seed * A + B) & MASK
        return self.seed >> (48 - bits)

    def next_int_pow2(self, log2_bound: int) -> int:
        """nextInt for a power-of-two bound == next(log2_bound). Clean bit leak."""
        return self.next(log2_bound)

    def next_int(self, bound: int) -> int:
        """Faithful java.util.Random.nextInt(bound), including the rejection loop.

        NOTE for the sweep: for a power-of-two `bound` this leaks the top
        log2(bound) bits cleanly. For a general (esp. ODD) `bound` the modulo
        biases which bits survive -- that is the elttam/RandomStringUtils case
        and is exactly what generate/leak.py must model precisely.
        """
        if bound <= 0:
            raise ValueError("bound must be positive")
        if (bound & (bound - 1)) == 0:  # power of two
            return (bound * self.next(31)) >> 31
        while True:
            bits = self.next(31)
            val = bits % bound
            if bits - val + (bound - 1) >= 0x80000000:
                continue  # rejection to remove modulo bias
            return val

    def next_float(self) -> float:
        """java.util.Random.nextFloat(): next(24) / 2**24, a value in [0, 1)."""
        return self.next(24) / float(1 << 24)


def floats_to_msb24(values: list[float]) -> list[int]:
    """Recover the top-24-bit integers that produced a list of nextFloat outputs.

    Reverses `randomInteger / 2**24`. Because multiplying a float by 0.5 only
    decrements the exponent (mantissa untouched) and widening float->double is
    lossless, an item-drop coordinate reconstructed from the wire yields the
    EXACT float, hence the exact 24-bit measurement. See generate/leak.py for
    the item-drop reconstruction that produces these `values`.
    """
    return [int(round(v * (1 << 24))) for v in values]
