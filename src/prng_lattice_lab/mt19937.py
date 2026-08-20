"""
MT19937 (Mersenne Twister) as a COMPARISON victim to java.util.Random.

The lab's core attack is a lattice round-off on a 48-bit truncated LCG that recovers
state from a *few PARTIAL* outputs (three nextFloat top-24-bit values). MT19937 sits
at the opposite corner of the recoverability space, and that contrast is the point:

  * java.util.Random (LCG): few outputs, tolerant of partial leakage. Recovery
    degrades gracefully as bits-per-call shrinks -- the whole (bits x observations)
    phase diagram.
  * MT19937: needs 624 CONSECUTIVE FULL 32-bit outputs, then recovery is EXACT and
    algebraic -- invert the output tempering ("untemper") to read back each state
    word, then run the generator's own recurrence forward to predict every future
    output. It does not degrade gracefully: untempering needs all 32 bits, so
    top-bits-only leakage breaks it. "All-or-nothing on width, but many outputs" vs
    the LCG's "few outputs, tolerates partial width".

Same capability (a predictable generator whose state is recoverable from its output),
different math (algebraic untempering vs lattice round-off).

MT19937 is the generator behind Python's `random`, Ruby's `Kernel#rand`, PHP
`mt_rand`, and many others. This module attacks outputs; the demo/tests use Python's
stdlib `random.Random` (which IS MT19937) as the instantiated victim, so recovery is
validated against ground truth without re-deriving the seeding schedule.

No lattice, no fpylll -- pure 32-bit bit-twiddling.
"""
from __future__ import annotations

N = 624
M = 397
MATRIX_A = 0x9908B0DF
UPPER_MASK = 0x80000000
LOWER_MASK = 0x7FFFFFFF
_TEMPER_B = 0x9D2C5680
_TEMPER_C = 0xEFC60000
_MASK32 = 0xFFFFFFFF


def temper(y: int) -> int:
    """MT19937's output tempering applied to a state word."""
    y &= _MASK32
    y ^= y >> 11
    y ^= (y << 7) & _TEMPER_B
    y ^= (y << 15) & _TEMPER_C
    y ^= y >> 18
    return y & _MASK32


def _undo_right(value: int, shift: int) -> int:
    result = value
    for _ in range(32 // shift + 1):
        result = value ^ (result >> shift)
    return result & _MASK32


def _undo_left(value: int, shift: int, mask: int) -> int:
    result = value
    for _ in range(32 // shift + 1):
        result = value ^ ((result << shift) & mask)
    return result & _MASK32


def untemper(y: int) -> int:
    """Invert `temper`: recover the raw state word from one 32-bit output. Exact
    inverse -- untemper(temper(x)) == x for every 32-bit x."""
    y = _undo_right(y, 18)
    y = _undo_left(y, 15, _TEMPER_C)
    y = _undo_left(y, 7, _TEMPER_B)
    y = _undo_right(y, 11)
    return y & _MASK32


def _next_state(window: list[int]) -> int:
    """The next raw state word from the last >=624 consecutive words (the twist
    recurrence, expressed on a sliding window so it works at any stream offset)."""
    x = (window[-N] & UPPER_MASK) | (window[-N + 1] & LOWER_MASK)
    xa = x >> 1
    if x & 1:
        xa ^= MATRIX_A
    return (window[-N + M] ^ xa) & _MASK32


def recover_state(outputs: list[int]) -> list[int]:
    """Untemper 624 consecutive full 32-bit outputs into the consecutive raw state
    words. Raises ValueError with fewer than 624 outputs (MT19937 needs a full
    period of observations -- the whole contrast with the LCG's three)."""
    if len(outputs) < N:
        raise ValueError(f"MT19937 recovery needs >= {N} consecutive 32-bit outputs")
    return [untemper(o) for o in outputs[-N:]]


def predict_next(outputs: list[int], k: int = 5) -> list[int]:
    """Given >=624 consecutive full 32-bit outputs, predict the next `k` outputs
    exactly by cloning the state and running the recurrence forward."""
    window = recover_state(outputs)
    preds: list[int] = []
    for _ in range(k):
        nxt = _next_state(window)
        window.append(nxt)
        preds.append(temper(nxt))
    return preds
