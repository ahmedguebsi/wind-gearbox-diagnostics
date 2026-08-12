"""Comparator persistence rules — NON-PRIMARY, clearly labelled (M-21).

EWMA is the primary persistence/anomaly treatment (LOCKED-02); these rules
exist only for the comparison study (PROJECT.md §23) and every output
carries a ``COMPARATOR_*`` method label, so they are programmatically
distinguishable from primary outputs everywhere downstream. They can never
become the default: the detection config admits only ``ewma`` as method.

All windows are trailing (a centered window would read the future).
"""

from __future__ import annotations

from dataclasses import dataclass

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
from app.residuals.ewma import DetectionSeries

COMPARATOR_CONSECUTIVE_LABEL = "COMPARATOR_CONSECUTIVE_EXCEEDANCE"
COMPARATOR_ROLLING_COUNT_LABEL = "COMPARATOR_ROLLING_COUNT"
COMPARATOR_ROLLING_MEAN_LABEL = "COMPARATOR_ROLLING_MEAN"


def _streams(residuals: ResidualFrame) -> list[tuple[str, str, pd.Series, np.ndarray]]:
    frame = residuals.data
    if frame[NORMALIZED_RESIDUAL_COLUMN].isna().all():
        raise ConfigError("Comparators run on normalized residuals; none present")
    streams: list[tuple[str, str, pd.Series, np.ndarray]] = []
    for (turbine, target), group in frame.groupby([TURBINE_COLUMN, TARGET_COLUMN], observed=True):
        ordered = group.sort_values(TIMESTAMP_COLUMN)
        streams.append(
            (
                str(turbine),
                str(target),
                ordered[TIMESTAMP_COLUMN].reset_index(drop=True),
                ordered[NORMALIZED_RESIDUAL_COLUMN].to_numpy(dtype=float),
            )
        )
    return streams


def _rolling_sum(flags: np.ndarray, window: int) -> np.ndarray:
    """Trailing-window sum; positions before a full window count what exists."""
    cumulative = np.cumsum(flags.astype(int))
    shifted = np.concatenate([np.zeros(window, dtype=int), cumulative[:-window]])
    result: np.ndarray = cumulative - shifted
    return result


@dataclass(frozen=True)
class ConsecutiveExceedanceDetector:
    """State fires after N consecutive same-direction exceedances."""

    threshold: float = 3.0
    n_consecutive: int = 3

    def __post_init__(self) -> None:
        if self.threshold <= 0 or self.n_consecutive < 1:
            raise ConfigError(
                "Invalid comparator parameters",
                threshold=self.threshold,
                n_consecutive=self.n_consecutive,
            )

    def detect(self, residuals: ResidualFrame) -> list[DetectionSeries]:
        detections = []
        for turbine, target, timestamps, values in _streams(residuals):
            positive = _rolling_sum(values > self.threshold, self.n_consecutive)
            negative = _rolling_sum(values < -self.threshold, self.n_consecutive)
            states = np.zeros(len(values), dtype=int)
            states[positive >= self.n_consecutive] = 1
            states[negative >= self.n_consecutive] = -1
            detections.append(
                DetectionSeries(
                    turbine=turbine,
                    target=target,
                    timestamps=timestamps,
                    states=pd.Series(states),
                    method_label=COMPARATOR_CONSECUTIVE_LABEL,
                )
            )
        return detections


@dataclass(frozen=True)
class RollingCountDetector:
    """State fires on >= min_count exceedances within a trailing window."""

    threshold: float = 3.0
    window: int = 6
    min_count: int = 3

    def __post_init__(self) -> None:
        if self.threshold <= 0 or self.window < 1 or not 1 <= self.min_count <= self.window:
            raise ConfigError(
                "Invalid comparator parameters",
                threshold=self.threshold,
                window=self.window,
                min_count=self.min_count,
            )

    def detect(self, residuals: ResidualFrame) -> list[DetectionSeries]:
        detections = []
        for turbine, target, timestamps, values in _streams(residuals):
            positive = _rolling_sum(values > self.threshold, self.window)
            negative = _rolling_sum(values < -self.threshold, self.window)
            states = np.zeros(len(values), dtype=int)
            fire_positive = (positive >= self.min_count) & (positive >= negative)
            fire_negative = (negative >= self.min_count) & ~fire_positive
            states[fire_positive] = 1
            states[fire_negative] = -1
            detections.append(
                DetectionSeries(
                    turbine=turbine,
                    target=target,
                    timestamps=timestamps,
                    states=pd.Series(states),
                    method_label=COMPARATOR_ROLLING_COUNT_LABEL,
                )
            )
        return detections


@dataclass(frozen=True)
class RollingMeanDetector:
    """State fires when the trailing-window residual mean exceeds a threshold.

    No state is emitted before a full window exists (explicit warm-up, never
    a silent partial mean).
    """

    threshold: float = 1.5
    window: int = 6

    def __post_init__(self) -> None:
        if self.threshold <= 0 or self.window < 1:
            raise ConfigError(
                "Invalid comparator parameters", threshold=self.threshold, window=self.window
            )

    def detect(self, residuals: ResidualFrame) -> list[DetectionSeries]:
        detections = []
        for turbine, target, timestamps, values in _streams(residuals):
            means = (
                pd.Series(values).rolling(self.window, min_periods=self.window).mean().to_numpy()
            )
            states = np.zeros(len(values), dtype=int)
            with np.errstate(invalid="ignore"):
                states[means > self.threshold] = 1
                states[means < -self.threshold] = -1
            detections.append(
                DetectionSeries(
                    turbine=turbine,
                    target=target,
                    timestamps=timestamps,
                    states=pd.Series(states),
                    method_label=COMPARATOR_ROLLING_MEAN_LABEL,
                )
            )
        return detections
