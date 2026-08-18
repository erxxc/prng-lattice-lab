"""
Success-rate calibration and prediction-interval coverage over the sweep.

Intent (transfer target for repoauditor risk-quant session G): predict each
cell's recovery success probability from an information-theoretic model
(over-determination + margin), then check observed success against predicted --
a coverage test with an exact oracle. If the coverage code can't nail a boundary
you can compute analytically here, it won't nail a fuzzy security one.

NOT YET IMPLEMENTED. Contract:
  predict(profile) -> float                # modelled P(success) for a cell
  coverage(results, predictions) -> dict   # observed-vs-predicted, interval coverage
Uncertainty is always reported as a range; never collapse to a single number
(matches risk-quant-tooling design).
"""
from __future__ import annotations


def predict(profile) -> float:
    raise NotImplementedError("Calibration model pending -- see docs/RESEARCH.md hypothesis H2.")


def coverage(results, predictions) -> dict:
    raise NotImplementedError("Coverage test pending; depends on predict().")
