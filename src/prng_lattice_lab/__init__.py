"""prng-lattice-lab: a closed harness for characterising the recoverability
boundary of java.util.Random under partial-state leakage.

Anchored on the Randar (Minecraft) truncated-LCG attack; generalised to a
(bits-leaked-per-call x number-of-observations) phase diagram, with a fold-in
path to repoauditor as a `weak_rng_adapter`.
"""
__version__ = "0.4.0"
