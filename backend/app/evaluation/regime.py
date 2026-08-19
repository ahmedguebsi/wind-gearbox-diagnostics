"""Operating-regime split of error and detection figures (LIM-034 mitigation (a)).

LIM-034 measured that below the healthy-state active-power floor the thesis
NBM has mean residual -11.75 degC, and that those rows are 17.9% of the
monitoring stream but carry 50.4% of its residual variance. Above the floor
the same model is essentially unbiased (mean -0.09 degC, sigma 2.18).

The consequence recorded there is that no figure aggregated over the whole
monitoring stream is a statement about the model or the detector: it is a
mixture statistic over a regime the model was fitted on and a regime it never
saw. This module implements the mitigation LIM-034 recommends first — report
every figure SPLIT by regime — with no new modelling and no change to any
pre-registered criterion.

Two things it deliberately does NOT do:

- It does not gate detection on operating state. PROJECT.md §14 requires the
  TEST partition to stay unfiltered because anomalous rows there are the
  signal, and overriding that is a methodological ruling reserved to the
  author (PROJECT.md §34). Splitting the REPORT changes no partition.
- It does not re-derive the floor. The regime boundary IS
  ``HealthyStateConfig.minimum_active_power_kw`` — the same threshold that
  built the training population. A second, independently chosen boundary
  would measure something other than "inside vs outside the training
  support", which is the only question here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np
import pandas as pd

from app.core.errors import ConfigError
from app.models.metrics import MetricSet, compute_metrics, residual


class Regime(StrEnum):
    """Whether a row sits inside the operating support the NBM was fitted on."""

    IN_REGIME = "in_regime"
    OUT_OF_REGIME = "out_of_regime"


#: Where the boundary comes from. Named so no caller can silently substitute
#: its own threshold and still call the result a training-support split.
REGIME_BOUNDARY_SOURCE = "HealthyStateConfig.minimum_active_power_kw (PROJECT.md §13)"


def label_regime(active_power: pd.Series, floor_kw: float) -> pd.Series:
    """Label rows in/out of the fitted operating support.

    A missing power reading is OUT_OF_REGIME: the healthy-state builder
    excludes it (``below.fillna(value=True)``), so a row whose regime cannot
    be established was never in the training population either. Treating it
    as in-regime would quietly widen the very support this split exists to
    delimit.
    """
    if floor_kw <= 0.0:
        raise ConfigError("Regime floor must be positive", floor_kw=floor_kw)
    below = (active_power < floor_kw) | active_power.isna()
    return pd.Series(
        np.where(below, Regime.OUT_OF_REGIME.value, Regime.IN_REGIME.value),
        index=active_power.index,
        dtype="object",
    )


@dataclass(frozen=True)
class RegimeSlice:
    """Error behaviour of one model on one target within one regime."""

    regime: Regime
    n: int
    share: float
    metrics: MetricSet
    variance_share: float
    beyond_10c_fraction: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime.value,
            "n": self.n,
            "share": self.share,
            "variance_share": self.variance_share,
            "beyond_10c_fraction": self.beyond_10c_fraction,
            **self.metrics.as_dict(),
        }


def regime_slices(
    actual: pd.Series,
    predicted: pd.Series,
    regime: pd.Series,
) -> dict[str, RegimeSlice]:
    """One :class:`RegimeSlice` per regime present in ``regime``.

    ``variance_share`` is each regime's contribution to the TOTAL sum of
    squared residuals, which is the quantity LIM-034 reports: it is what makes
    "17.9% of rows, 50.4% of variance" a statement about leverage rather than
    about counts.
    """
    if not (len(actual) == len(predicted) == len(regime)):
        raise ConfigError(
            "Regime split inputs must be equal length",
            actual=len(actual),
            predicted=len(predicted),
            regime=len(regime),
        )
    if len(actual) == 0:
        raise ConfigError("Cannot split an empty series by regime")
    error = residual(actual.to_numpy(dtype=float), predicted.to_numpy(dtype=float))
    total_ss = float(np.sum(error**2))
    total_n = len(actual)
    out: dict[str, RegimeSlice] = {}
    labels = regime.astype(str)
    for label in sorted(set(labels)):
        # every label came from the series itself, so the mask is never empty
        mask = (labels == label).to_numpy(dtype=bool)
        subset_error = error[mask]
        out[label] = RegimeSlice(
            regime=Regime(label),
            n=int(mask.sum()),
            share=float(mask.sum()) / total_n,
            metrics=compute_metrics(actual[mask], predicted[mask]),
            variance_share=(float(np.sum(subset_error**2)) / total_ss if total_ss > 0.0 else 0.0),
            beyond_10c_fraction=float(np.mean(np.abs(subset_error) > 10.0)),
        )
    return out


@dataclass(frozen=True)
class Separation:
    """Chesterman et al. (2023) dual criterion, computed within one regime.

    A normal behaviour model is asked for two things at once: SMALL error on
    healthy data and LARGE error on unhealthy data. Accuracy alone scores only
    the first, which is why a model can look worse on a monitoring period
    precisely because it is doing its job.

    ``delta`` is RMSE(unhealthy) - RMSE(healthy). Larger is better.

    This is only interpretable WITHIN a regime. Computed across the whole
    monitoring stream it is dominated by extrapolation onto rows the model was
    never fitted on, and then a large delta means "fails on parked turbines",
    not "responds to degradation" (LIM-034).
    """

    regime: Regime
    n_healthy: int
    n_unhealthy: int
    rmse_healthy: float
    rmse_unhealthy: float
    delta: float
    ratio: float
    interpretable: bool
    caveat: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime.value,
            "n_healthy": self.n_healthy,
            "n_unhealthy": self.n_unhealthy,
            "rmse_healthy": self.rmse_healthy,
            "rmse_unhealthy": self.rmse_unhealthy,
            "delta": self.delta,
            "ratio": self.ratio,
            "interpretable": self.interpretable,
            "caveat": self.caveat,
        }


#: Below this many rows on either side, a delta is reported descriptively.
MIN_SEPARATION_ROWS = 1_000


def separation(
    actual: pd.Series,
    predicted: pd.Series,
    healthy: pd.Series,
    *,
    regime: Regime,
) -> Separation:
    """Delta-PE within one regime. ``healthy`` is a boolean membership mask."""
    if not (len(actual) == len(predicted) == len(healthy)):
        raise ConfigError("Separation inputs must be equal length")
    mask = healthy.to_numpy(dtype=bool)
    n_h, n_u = int(mask.sum()), int((~mask).sum())
    if n_h == 0 or n_u == 0:
        raise ConfigError(
            "Separation needs both healthy and unhealthy rows",
            n_healthy=n_h,
            n_unhealthy=n_u,
            regime=regime.value,
        )
    rmse_h = compute_metrics(actual[mask], predicted[mask]).rmse
    rmse_u = compute_metrics(actual[~mask], predicted[~mask]).rmse
    small = min(n_h, n_u) < MIN_SEPARATION_ROWS
    return Separation(
        regime=regime,
        n_healthy=n_h,
        n_unhealthy=n_u,
        rmse_healthy=rmse_h,
        rmse_unhealthy=rmse_u,
        delta=rmse_u - rmse_h,
        ratio=rmse_u / rmse_h if rmse_h > 0.0 else float("nan"),
        interpretable=not small,
        caveat=(
            f"Fewer than {MIN_SEPARATION_ROWS} rows on one side "
            f"(healthy {n_h}, unhealthy {n_u}); report descriptively."
            if small
            else None
        ),
    )


@dataclass(frozen=True)
class ExceedanceCensus:
    """Detection exceedances split by regime and by direction.

    LIM-026 recorded that the single EVENT-001 match is a cold-side (-1)
    excursion on a fault whose signature is a temperature rise, and LIM-034
    proposed the mechanism: below the floor the residual mean is strongly
    negative, so the untrained regime emits large NEGATIVE residuals. This
    census is what turns that proposal into a measurement.
    """

    regime: Regime
    n_points: int
    n_high: int
    n_low: int
    n_exceedances: int
    exceedance_rate: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime.value,
            "n_points": self.n_points,
            "n_high": self.n_high,
            "n_low": self.n_low,
            "n_exceedances": self.n_exceedances,
            "exceedance_rate": self.exceedance_rate,
        }


def exceedance_census(states: pd.Series, regime: pd.Series) -> dict[str, ExceedanceCensus]:
    """Split discrete detection states (-1 / 0 / +1) by regime."""
    if len(states) != len(regime):
        raise ConfigError(
            "State and regime series must be equal length",
            states=len(states),
            regime=len(regime),
        )
    values = states.to_numpy(dtype=int)
    labels = regime.astype(str).to_numpy()
    out: dict[str, ExceedanceCensus] = {}
    for label in sorted(set(labels)):
        mask = labels == label
        subset = values[mask]
        high = int(np.sum(subset > 0))
        low = int(np.sum(subset < 0))
        out[label] = ExceedanceCensus(
            regime=Regime(label),
            n_points=int(mask.sum()),
            n_high=high,
            n_low=low,
            n_exceedances=high + low,
            exceedance_rate=(high + low) / int(mask.sum()) if mask.any() else 0.0,
        )
    return out
