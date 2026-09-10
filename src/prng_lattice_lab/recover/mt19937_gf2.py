"""
MT19937 state recovery from TRUNCATED outputs, by GF(2) linear algebra.

`mt19937.py` untempers 624 consecutive FULL 32-bit words -- the `getrandbits(32)` idiom.
But the common Python idioms never expose a whole word: `random.random()` reveals only
the top 27 bits of one output and the top 26 of the next (53 bits of a double), and
`getrandbits(k)` for k<32 reveals only the top k bits. Untempering needs the whole word,
so this module changes representation instead.

Every operation in MT19937 -- the twist (state transition) and the tempering (output
extraction) -- is LINEAR over GF(2). So each output bit is a fixed XOR of the 19937
effective state bits, and each observed bit is one linear equation in those unknowns.
Collect a full-rank system and solve by Gauss-Jordan over GF(2); the recovered state then
predicts every past and future output.

Method (all exact, no search):
  * A symbolic generator mirrors CPython's genrand_uint32 (twist + temper), carrying each
    live word-bit as a D=624*32-bit vector over the initial-state basis. Substituting a
    concrete state into these vectors reproduces the real generator bit-for-bit
    (tests/test_mt19937_gf2.py checks this against CPython itself -- Python is the oracle).
  * Each observed output contributes equations for the bits it reveals; observations are
    added until the system reaches full rank (19937) or a call budget is hit.
  * Online Gaussian elimination keeps a pivot per leading bit; `rank` is exact, so
    uniqueness is CERTIFIED (rank == 19937), not assumed. A rank-deficient system is
    reported as a solution-space dimension, never collapsed to a guess (rule 8).

Boundaries, disclosed:
  * Recovers the STATE, hence all outputs; it does NOT recover the seed (MT's seeding is
    non-linear). That is a separate, generally infeasible problem -- unlike java.util.
    Random, where the constructor seed IS recoverable (see adapt.evidence `seeded`).
  * Observations are assumed to begin at a generator's first output (a twist boundary),
    the common "seeded once at startup" case. Mid-stream alignment (a 624-way offset
    search) is a disclosed extension, not wired here.
  * The 31 low bits of the initial word 0 never affect any output, so the state is unique
    only modulo those irrelevant bits (they are set to 0); predictions are unaffected and
    their uniqueness is certified per output.

The whole module is stdlib + Python-int bit-vectors (no numpy, no fpylll): the linearity
does the work the lattice does for the LCG.
"""
from __future__ import annotations

from dataclasses import dataclass

N = 624
M = 397
MATRIX_A = 0x9908b0df
UPPER_MASK = 0x80000000
LOWER_MASK = 0x7fffffff
WORD_BITS = 32
STATE_BITS = N * WORD_BITS          # 19968 basis dimension
EFFECTIVE_BITS = N * WORD_BITS - 31  # 19937: word-0 low 31 bits never reach an output
_TEMPER = ((11, 0xffffffff, "r"), (7, 0x9d2c5680, "l"),
           (15, 0xefc60000, "l"), (18, 0xffffffff, "r"))


def _basis() -> list[list[int]]:
    """Symbolic initial state: bit j of word i is the basis vector e_{i*32+j}."""
    return [[1 << (i * WORD_BITS + j) for j in range(WORD_BITS)] for i in range(N)]


def _twist(mt: list[list[int]]) -> None:
    """Symbolic twist, mirroring CPython's in-place regeneration exactly."""
    for kk in range(N):
        nxt = mt[(kk + 1) % N]
        # y = (mt[kk] & UPPER_MASK) | (mt[kk+1] & LOWER_MASK)
        y = [nxt[j] for j in range(31)] + [mt[kk][31]]
        yshift = [y[j + 1] for j in range(31)] + [0]        # y >> 1
        src = mt[(kk + M) % N]
        res = [src[j] ^ yshift[j] for j in range(WORD_BITS)]
        v0 = y[0]                                            # y & 1
        for p in range(WORD_BITS):
            if (MATRIX_A >> p) & 1:
                res[p] ^= v0
        mt[kk] = res


def _temper(word: list[int]) -> list[int]:
    """Symbolic tempering, mirroring CPython (per-bit XOR of shifted, masked copies)."""
    y = list(word)
    for shift, mask, direction in _TEMPER:
        if direction == "r":
            y = [y[j] ^ ((y[j + shift] if j + shift < WORD_BITS else 0) if (mask >> j) & 1 else 0)
                 for j in range(WORD_BITS)]
        else:
            y = [y[j] ^ ((y[j - shift] if j - shift >= 0 else 0) if (mask >> j) & 1 else 0)
                 for j in range(WORD_BITS)]
    return y


class SymbolicMT:
    """A CPython-faithful MT19937 whose outputs are symbolic GF(2) vectors of the initial
    state. Start index N (a fresh, just-seeded generator: the first word triggers a twist)."""

    __slots__ = ("mt", "mti")

    def __init__(self, index: int = N):
        self.mt = _basis()
        self.mti = index

    def next_word(self) -> list[int]:
        if self.mti >= N:
            _twist(self.mt)
            self.mti = 0
        w = self.mt[self.mti]
        self.mti += 1
        return _temper(w)


class GF2System:
    """Online Gauss-Jordan over GF(2): a pivot row per leading bit. Exact rank."""

    __slots__ = ("_pivots",)

    def __init__(self) -> None:
        self._pivots: dict[int, tuple[int, int]] = {}

    def add(self, vec: int, rhs: int) -> None:
        """Add the equation vec . x == rhs (rhs in {0,1}). Raises on a contradiction."""
        while vec:
            p = vec.bit_length() - 1
            piv = self._pivots.get(p)
            if piv is None:
                self._pivots[p] = (vec, rhs & 1)
                return
            vec ^= piv[0]
            rhs ^= piv[1]
        if rhs & 1:
            raise ValueError("inconsistent GF(2) equation (observations not from one MT stream)")

    @property
    def rank(self) -> int:
        return len(self._pivots)

    def residual(self, vec: int) -> int:
        """Reduce vec by the pivots; 0 means vec lies in the row space (its value is
        determined regardless of any free variables)."""
        while vec:
            p = vec.bit_length() - 1
            piv = self._pivots.get(p)
            if piv is None:
                return vec
            vec ^= piv[0]
        return 0

    def particular_solution(self) -> int:
        """One state consistent with all equations (free variables set to 0)."""
        x = 0
        for p in sorted(self._pivots):
            vec, rhs = self._pivots[p]
            if rhs ^ (bin(vec & x).count("1") & 1):
                x |= 1 << p
        return x


def _parity(vec: int, x: int) -> int:
    return bin(vec & x).count("1") & 1


@dataclass(frozen=True)
class Recovery:
    """A recovered MT19937 state and the certificate behind it."""
    state: int                      # the initial-state bits (word-0 low bits irrelevant, =0)
    rank: int                       # GF(2) rank of the observation system
    unique: bool                    # rank == EFFECTIVE_BITS (state uniquely determined)
    observations_used: int          # generator outputs consumed to reach this
    _sym: SymbolicMT
    _sys: GF2System

    def concrete_state_words(self) -> list[int]:
        """The recovered mt[0..623] (word-0 low 31 bits are irrelevant / zero)."""
        return [(self.state >> (i * WORD_BITS)) & 0xffffffff for i in range(N)]

    def predict_next_words(self, count: int) -> tuple[list[int], bool]:
        """The next `count` full 32-bit tempered outputs, and whether all are uniquely
        determined by the recovered system (each output vector lies in the row space)."""
        out, certain = [], True
        for _ in range(count):
            w = self._sym.next_word()
            val = 0
            for j in range(WORD_BITS):
                if self._sys.residual(w[j]):
                    certain = False
                val |= _parity(w[j], self.state) << j
            out.append(val)
        return out, certain


def recover_from_random(doubles: list[float], predict_probe: int = 0) -> Recovery:
    """Recover MT19937 state from consecutive `random.random()` outputs.

    Each double reveals the top 27 bits of one output word and the top 26 of the next
    (53 bits). ~700 consecutive calls reach full rank (unique recovery); fewer leaves a
    reported solution-space dimension.
    """
    sym = SymbolicMT()
    sys_ = GF2System()
    for d in doubles:
        w1 = sym.next_word()
        w2 = sym.next_word()
        scaled = int(d * (1 << 53))
        a = scaled >> 26                       # top 27 bits -> word1 bits 5..31
        b = scaled & ((1 << 26) - 1)           # 26 bits    -> word2 bits 6..31
        for i in range(27):
            sys_.add(w1[5 + i], (a >> i) & 1)
        for i in range(26):
            sys_.add(w2[6 + i], (b >> i) & 1)
    return _finish(sym, sys_, observations=len(doubles) * 2)


def recover_from_getrandbits(values: list[int], bits: int) -> Recovery:
    """Recover MT19937 state from consecutive `random.getrandbits(bits)` outputs, for
    1 <= bits <= 32 (each reveals the top `bits` bits of one output word)."""
    if not 1 <= bits <= 32:
        raise ValueError("getrandbits recovery handles 1 <= bits <= 32 (one word per call)")
    sym = SymbolicMT()
    sys_ = GF2System()
    lo = WORD_BITS - bits
    for v in values:
        w = sym.next_word()
        for i in range(bits):
            sys_.add(w[lo + i], (v >> i) & 1)
    return _finish(sym, sys_, observations=len(values))


def _finish(sym: SymbolicMT, sys_: GF2System, observations: int) -> Recovery:
    x = sys_.particular_solution()
    return Recovery(state=x, rank=sys_.rank, unique=(sys_.rank == EFFECTIVE_BITS),
                    observations_used=observations, _sym=sym, _sys=sys_)


def calls_for_full_rank_random() -> int:
    """Empirical: consecutive random() calls that reach full rank (see the rank sweep in
    tests). A safe default with margin."""
    return 700
