"""
Real-JVM oracle: emit java.util.Random tokens from an actual OpenJDK process, so a
recovery demonstration can be checked against the generator it claims to attack rather
than only against the lab's own port of the LCG.

Everything else in the lab attacks `lcg.JavaRandom`, a bit-exact port pinned to one
published Randar vector. This module closes the last bit of trust: it compiles a tiny
Java emitter once, runs the real `java.util.Random`, and hands its tokens to the same
solvers. If the lab's model diverged from the JVM anywhere off the pinned vector, an
oracle-backed demonstration would fail to recover -- so a passing one is evidence the
model is faithful across the whole idiom, not just the anchor.

No reflection (JDK 17+ closes java.util to reflection): the public constructor scrambles
`this.seed = (arg ^ 0x5DEECE66D) & mask`, so `Random(state ^ 0x5DEECE66D)` sets the
internal seed to exactly `state`. That is the whole trick, and it is asserted against
the lab model on import-time-free demand (see tests/test_jvm_oracle.py).

A JDK is OPTIONAL. `available()` is False when `javac`/`java` are absent or too old, and
every caller degrades to the lab model with that fact recorded in the artifact
(`oracle: "lab_model"` vs `"jvm"`), never a silent substitution.
"""
from __future__ import annotations

import functools
import shutil
import subprocess
import tempfile
from pathlib import Path

MULT = 0x5DEECE66D  # java.util.Random multiplier; constructor scrambles by XOR with it

_EMITTER_SOURCE = r'''
import java.util.Random;

public class Emit {
    static final long MULT = 0x5DEECE66DL;
    public static void main(String[] a) {
        long state = Long.parseLong(a[0]);
        String kind = a[1];
        int n = Integer.parseInt(a[2]);
        Random r = new Random(state ^ MULT);
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < n; i++) {
            if (kind.equals("msb24")) {
                sb.append((int) (r.nextFloat() * (1 << 24)));
            } else if (kind.equals("nextint")) {
                int bound = Integer.parseInt(a[3]);
                sb.append(r.nextInt(bound));
            } else {
                throw new IllegalArgumentException("kind: " + kind);
            }
            sb.append('\n');
        }
        System.out.print(sb);
    }
}
'''


class OracleUnavailable(RuntimeError):
    """No usable JDK (javac/java missing, too old, or compilation/run failed)."""


@functools.lru_cache(maxsize=1)
def available() -> bool:
    """True iff a JDK that can compile and run the emitter is on PATH."""
    if not (shutil.which("javac") and shutil.which("java")):
        return False
    try:
        _classes_dir()
        return True
    except OracleUnavailable:
        return False


@functools.lru_cache(maxsize=1)
def java_version() -> str | None:
    """The `java -version` first line, or None when java is absent."""
    if not shutil.which("java"):
        return None
    try:
        out = subprocess.run(["java", "-version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    line = (out.stderr or out.stdout or "").splitlines()
    return line[0].strip() if line else None


@functools.lru_cache(maxsize=1)
def _classes_dir() -> Path:
    """Compile the emitter once per process into a temp dir; return the classpath root.
    Raises OracleUnavailable if javac is missing or compilation fails."""
    if not shutil.which("javac"):
        raise OracleUnavailable("javac not on PATH")
    out = Path(tempfile.mkdtemp(prefix="prng-lattice-jvm-"))
    (out / "Emit.java").write_text(_EMITTER_SOURCE, encoding="utf-8")
    try:
        proc = subprocess.run(["javac", "Emit.java"], cwd=out, capture_output=True,
                              text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise OracleUnavailable(f"javac failed to run: {exc}") from exc
    if proc.returncode != 0 or not (out / "Emit.class").is_file():
        raise OracleUnavailable(f"javac error: {proc.stderr.strip()[:200]}")
    return out


def emit(state: int, kind: str, n: int, bound: int | None = None) -> list[int]:
    """Run the real java.util.Random from internal `state` and return `n` tokens.

    kind="msb24" -> top 24 bits of successive nextFloat() outputs;
    kind="nextint" -> nextInt(bound) values (bound required).
    Raises OracleUnavailable if no JDK; ValueError on bad arguments.
    """
    if kind == "nextint" and (bound is None or bound < 1):
        raise ValueError("nextint oracle needs a positive bound")
    if kind not in ("msb24", "nextint"):
        raise ValueError(f"unknown oracle kind {kind!r}")
    classes = _classes_dir()
    args = ["java", "-cp", str(classes), "Emit", str(int(state) & ((1 << 48) - 1)), kind, str(n)]
    if kind == "nextint":
        args.append(str(bound))
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise OracleUnavailable(f"java failed to run: {exc}") from exc
    if proc.returncode != 0:
        raise OracleUnavailable(f"java error: {proc.stderr.strip()[:200]}")
    return [int(line) for line in proc.stdout.split()]
