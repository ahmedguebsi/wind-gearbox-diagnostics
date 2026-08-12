"""NBM accuracy metrics (M-18; PROJECT.md §19-§20).

Exactly four metrics per thermal target: RMSE, MAE, R², bias. MAPE is
structurally absent — Celsius is an interval scale, so percentage error
relative to °C is physically meaningless and unstable near 0 °C
(PROJECT.md §19). A meta-test asserts no MAPE computation exists in this
layer, and :class:`MetricSet` exposes no field for it.

Condition-sliced diagnostics (error vs active power / wind speed / ambient
temperature) reveal whether model error changes by operating condition —
the heteroscedasticity check feeding normalization design (§20), with the
ambient slice doubling as the seasonal-shift diagnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.core.errors import ConfigError


@dataclass(frozen=True)
class MetricSet:
    """Exactly {rmse, mae, r2, bias} — no MAPE field exists (LOCKED via §19)."""

    rmse: float
    mae: float
    r2: float
    bias: float

    def as_dict(self) -> dict[str, float]:
        return {"rmse": self.rmse, "mae": self.mae, "r2": self.r2, "bias": self.bias}


def compute_metrics(actual: pd.Series, predicted: pd.Series) -> MetricSet:
    """RMSE/MAE/R²/bias on one target. Bias is mean(predicted - actual)."""
    if len(actual) != len(predicted):
        raise ConfigError(
            "Actual and predicted lengths differ", actual=len(actual), predicted=len(predicted)
        )
    if len(actual) == 0:
        raise ConfigError("Cannot compute metrics on empty series")
    a = actual.to_numpy(dtype=float)
    p = predicted.to_numpy(dtype=float)
    error = p - a
    ss_residual = float(np.sum((a - p) ** 2))
    ss_total = float(np.sum((a - np.mean(a)) ** 2))
    r2 = 1.0 - ss_residual / ss_total if ss_total > 0.0 else float("nan")
    return MetricSet(
        rmse=float(np.sqrt(np.mean(error**2))),
        mae=float(np.mean(np.abs(error))),
        r2=r2,
        bias=float(np.mean(error)),
    )


def compute_per_target(actual: pd.DataFrame, predicted: pd.DataFrame) -> dict[str, MetricSet]:
    """One MetricSet per thermal target (columns must match)."""
    if set(actual.columns) != set(predicted.columns):
        raise ConfigError(
            "Actual and predicted target columns differ",
            actual=sorted(map(str, actual.columns)),
            predicted=sorted(map(str, predicted.columns)),
        )
    return {
        str(target): compute_metrics(actual[target], predicted[target]) for target in actual.columns
    }


def condition_sliced(
    actual: pd.Series,
    predicted: pd.Series,
    condition: pd.Series,
    *,
    bins: int = 10,
) -> pd.DataFrame:
    """Per-bin error diagnostics along one operating-condition variable.

    Returns one row per condition bin: bin edges, count, and the four
    metrics. Bins with no observations are dropped (explicitly countable
    from the ``n`` column).
    """
    if not (len(actual) == len(predicted) == len(condition)):
        raise ConfigError("Metric inputs must be equal length")
    frame = pd.DataFrame(
        {"actual": actual.to_numpy(dtype=float), "predicted": predicted.to_numpy(dtype=float)}
    )
    frame["bin"] = pd.cut(condition.to_numpy(dtype=float), bins=bins)
    rows: list[dict[str, Any]] = []
    for interval, group in frame.groupby("bin", observed=True):
        metrics = compute_metrics(group["actual"], group["predicted"])
        edges: Any = interval
        rows.append(
            {
                "bin_left": float(edges.left),
                "bin_right": float(edges.right),
                "n": len(group),
                **metrics.as_dict(),
            }
        )
    return pd.DataFrame(rows)


def condition_diagnostics(
    actual: pd.Series,
    predicted: pd.Series,
    conditions: pd.DataFrame,
    *,
    bins: int = 10,
) -> dict[str, pd.DataFrame]:
    """§20 diagnostics across every supplied condition variable.

    Callers pass the three named condition variables (active power, wind
    speed, ambient temperature); the ambient slice doubles as the
    seasonal-shift diagnostic.
    """
    return {
        str(column): condition_sliced(actual, predicted, conditions[column], bins=bins)
        for column in conditions.columns
    }
