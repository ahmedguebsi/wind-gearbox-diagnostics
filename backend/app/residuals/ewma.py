"""EWMA smoothing + control limits — the PRIMARY detector (M-20; LOCKED-02).

EWMA of normalized residuals with control-chart limits is the thesis Phase 3
persistence/anomaly treatment (PROJECT.md §23). Both standard limit
formulations exist (steady-state and time-varying), and because 10-minute
thermal residuals are serially correlated, the effective in-control
false-alarm behaviour is measured EMPIRICALLY on healthy validation data —
the i.i.d. theoretical ARL is never assumed to hold. A materially inflated
empirical rate produces a ready-to-append LIMITATIONS.md entry
(:meth:`InControlReport.limitations_entry`), which the runner records when
the detector joins the pipeline.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np
import pandas as pd

from app.core.errors import ConfigError
from app.residuals.engine import (
    NORMALIZED_RESIDUAL_COLUMN,
    TARGET_COLUMN,
    TIMESTAMP_COLUMN,
    TURBINE_COLUMN,
    ResidualFrame,
)
from app.residuals.normalization import PartitionRef, ThresholdProvenanceGuard

#: Method label carried by every primary detection output (M-21 comparators
#: will label theirs COMPARATOR_*; the two are distinguishable everywhere).
PRIMARY_EWMA_LABEL = "PRIMARY_EWMA"


class ControlLimitFormulation(StrEnum):
    """Standard EWMA control-chart limit variants (PROJECT.md §23)."""

    STEADY_STATE = "steady_state"
    TIME_VARYING = "time_varying"


@dataclass(frozen=True)
class ControlLimitSpec:
    sigma_multiplier: float = 3.0
    formulation: ControlLimitFormulation = ControlLimitFormulation.STEADY_STATE


@dataclass(frozen=True)
class EwmaSeries:
    """EWMA values + control limits for one (turbine, target) stream."""

    turbine: str
    target: str
    timestamps: pd.Series
    values: pd.Series
    upper: pd.Series
    lower: pd.Series
    lam: float
    spec: ControlLimitSpec


@dataclass(frozen=True)
class DetectionSeries:
    """Discrete per-point states for one stream; label is mandatory."""

    turbine: str
    target: str
    timestamps: pd.Series
    states: pd.Series  # -1 abnormally low | 0 normal | +1 abnormally high
    method_label: str

    def __post_init__(self) -> None:
        if not self.method_label.strip():
            raise ConfigError("DetectionSeries requires a method label")


@dataclass(frozen=True)
class InControlReport:
    """Empirical in-control false-alarm characterization (PROJECT.md §23)."""

    n_points: int
    n_exceedances: int
    empirical_rate: float
    theoretical_rate: float
    inflation_ratio: float
    material_inflation_threshold: float

    @property
    def materially_inflated(self) -> bool:
        return self.inflation_ratio > self.material_inflation_threshold

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_points": self.n_points,
            "n_exceedances": self.n_exceedances,
            "empirical_rate": self.empirical_rate,
            "theoretical_rate": self.theoretical_rate,
            "inflation_ratio": self.inflation_ratio,
            "material_inflation_threshold": self.material_inflation_threshold,
            "materially_inflated": self.materially_inflated,
        }

    def limitations_entry(self) -> str | None:
        """LIMITATIONS.md entry text when inflation is material, else None."""
        if not self.materially_inflated:
            return None
        return (
            "EWMA in-control false-alarm inflation: empirical rate "
            f"{self.empirical_rate:.5f} vs i.i.d. theoretical "
            f"{self.theoretical_rate:.5f} ({self.inflation_ratio:.1f}x) on the "
            "healthy validation block — serial correlation invalidates the "
            "theoretical ARL (risk R4); control limits may require widening."
        )


def _gaussian_two_sided_rate(multiplier: float) -> float:
    """Pointwise exceedance probability for i.i.d. Gaussian input."""
    return float(2.0 * (1.0 - 0.5 * (1.0 + math.erf(multiplier / math.sqrt(2.0)))))


def ewma_recursion(values: np.ndarray, lam: float) -> np.ndarray:
    """z_t = lam * x_t + (1 - lam) * z_(t-1), z_0 = 0 (normalized residuals)."""
    smoothed = np.empty(len(values), dtype=float)
    previous = 0.0
    for i, x in enumerate(values):
        previous = lam * x + (1.0 - lam) * previous
        smoothed[i] = previous
    return smoothed


class EwmaDetector:
    """LOCKED-02 primary treatment (ARCHITECTURE.md §5.3)."""

    def __init__(
        self,
        lam: float,
        spec: ControlLimitSpec,
        *,
        material_inflation_threshold: float = 2.0,
    ) -> None:
        if not 0.0 < lam <= 1.0:
            raise ConfigError("EWMA lambda must be in (0, 1]", lam=lam)
        if spec.sigma_multiplier <= 0.0:
            raise ConfigError("Control-limit multiplier must be positive")
        self.lam = lam
        self.spec = spec
        self.material_inflation_threshold = material_inflation_threshold
        self._sigma: dict[str, float] = {}
        self._source: PartitionRef | None = None

    @property
    def source(self) -> PartitionRef:
        if self._source is None:
            raise ConfigError("Control limits are not fitted; statistics source unknown")
        return self._source

    def fit_control_limits(self, healthy: ResidualFrame, source: PartitionRef) -> None:
        """Per-target sigma of normalized healthy residuals (Guard 4 applies)."""
        ThresholdProvenanceGuard().validate(source)
        frame = healthy.data
        sigma: dict[str, float] = {}
        for target, group in frame.groupby(TARGET_COLUMN, observed=True):
            values = group[NORMALIZED_RESIDUAL_COLUMN].to_numpy(dtype=float)
            values = values[~np.isnan(values)]
            if len(values) < 2:
                raise ConfigError("Too few normalized healthy residuals", target=str(target))
            spread = float(np.std(values, ddof=1))
            if spread == 0.0:
                raise ConfigError("Degenerate normalized spread", target=str(target))
            sigma[str(target)] = spread
        self._sigma = sigma
        self._source = source

    def _limit_profile(self, sigma: float, n: int) -> np.ndarray:
        """Control-limit magnitude at each point (PROJECT.md §23)."""
        factor = self.lam / (2.0 - self.lam)
        if self.spec.formulation is ControlLimitFormulation.STEADY_STATE:
            return np.full(n, self.spec.sigma_multiplier * sigma * math.sqrt(factor))
        t = np.arange(1, n + 1, dtype=float)
        variance_fraction = factor * (1.0 - (1.0 - self.lam) ** (2.0 * t))
        limits: np.ndarray = self.spec.sigma_multiplier * sigma * np.sqrt(variance_fraction)
        return limits

    def detect(self, residuals: ResidualFrame) -> tuple[list[EwmaSeries], list[DetectionSeries]]:
        """EWMA + limits + discrete states per (turbine, target) stream."""
        if not self._sigma:
            raise ConfigError("Control limits are not fitted")
        frame = residuals.data
        if frame[NORMALIZED_RESIDUAL_COLUMN].isna().all():
            raise ConfigError("Residuals are not normalized; EWMA runs on normalized residuals")
        ewma_series: list[EwmaSeries] = []
        detections: list[DetectionSeries] = []
        for (turbine, target), group in frame.groupby(
            [TURBINE_COLUMN, TARGET_COLUMN], observed=True
        ):
            key = str(target)
            if key not in self._sigma:
                raise ConfigError("Control limits were not fitted for target", target=key)
            ordered = group.sort_values(TIMESTAMP_COLUMN)
            values = ordered[NORMALIZED_RESIDUAL_COLUMN].to_numpy(dtype=float)
            smoothed = ewma_recursion(np.nan_to_num(values, nan=0.0), self.lam)
            limits = self._limit_profile(self._sigma[key], len(smoothed))
            states = np.zeros(len(smoothed), dtype=int)
            states[smoothed > limits] = 1
            states[smoothed < -limits] = -1
            timestamps = ordered[TIMESTAMP_COLUMN].reset_index(drop=True)
            ewma_series.append(
                EwmaSeries(
                    turbine=str(turbine),
                    target=key,
                    timestamps=timestamps,
                    values=pd.Series(smoothed),
                    upper=pd.Series(limits),
                    lower=pd.Series(-limits),
                    lam=self.lam,
                    spec=self.spec,
                )
            )
            detections.append(
                DetectionSeries(
                    turbine=str(turbine),
                    target=key,
                    timestamps=timestamps,
                    states=pd.Series(states),
                    method_label=PRIMARY_EWMA_LABEL,
                )
            )
        return ewma_series, detections

    def characterize_in_control(self, healthy_validation: ResidualFrame) -> InControlReport:
        """Measured false-alarm behaviour on healthy data (never assumed).

        Serial correlation inflates EWMA variance beyond the i.i.d. formula,
        so the empirical rate is the number that matters (risk R4).
        """
        _, detections = self.detect(healthy_validation)
        n_points = sum(len(d.states) for d in detections)
        n_exceedances = sum(int((d.states != 0).sum()) for d in detections)
        if n_points == 0:
            raise ConfigError("No points to characterize")
        empirical = n_exceedances / n_points
        theoretical = _gaussian_two_sided_rate(self.spec.sigma_multiplier)
        return InControlReport(
            n_points=n_points,
            n_exceedances=n_exceedances,
            empirical_rate=empirical,
            theoretical_rate=theoretical,
            inflation_ratio=empirical / theoretical if theoretical > 0 else float("inf"),
            material_inflation_threshold=self.material_inflation_threshold,
        )
