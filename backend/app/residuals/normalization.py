"""Residual normalization + Guard 4 (M-19b; PROJECT.md §22).

Normalization statistics come from HEALTHY partitions only — never from
fault or test periods. :class:`ThresholdProvenanceGuard` (Guard 4) enforces
this at every ``fit()``, and the source partition is recorded so experiment
metadata always names which healthy block produced the statistics (the
ADR-001 training-vs-validation enum; both branches exist as configuration
while the thesis decision stays in docs/DECISIONS.md).

Four normalizer families (sigma / MAD / percentile / condition-binned), all
per-target. The condition-binned variant exists for the case where the §20
heteroscedasticity diagnostics justify it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

import numpy as np
import pandas as pd

from app.core.config import NormalizationMethod, ThresholdStatsSource
from app.core.errors import ConfigError, ThresholdProvenanceError
from app.residuals.engine import (
    RAW_RESIDUAL_COLUMN,
    TARGET_COLUMN,
    ResidualFrame,
)

#: Consistency factor: MAD * 1.4826 estimates sigma under normality.
MAD_SIGMA_CONSISTENCY = 1.4826
#: Consistency factor: IQR / 1.349 estimates sigma under normality.
IQR_SIGMA_CONSISTENCY = 1.349


class PartitionRef(StrEnum):
    """Which data partition a statistic derives from (Guard 4 subject)."""

    HEALTHY_TRAINING = "healthy_training"
    HEALTHY_VALIDATION = "healthy_validation"
    TEST = "test"
    FAULT = "fault"


HEALTHY_PARTITIONS: tuple[PartitionRef, ...] = (
    PartitionRef.HEALTHY_TRAINING,
    PartitionRef.HEALTHY_VALIDATION,
)

#: ADR-001 config enum → partition reference.
_SOURCE_TO_PARTITION: dict[ThresholdStatsSource, PartitionRef] = {
    ThresholdStatsSource.TRAINING: PartitionRef.HEALTHY_TRAINING,
    ThresholdStatsSource.VALIDATION: PartitionRef.HEALTHY_VALIDATION,
}


def partition_for(source: ThresholdStatsSource) -> PartitionRef:
    return _SOURCE_TO_PARTITION[source]


class ThresholdProvenanceGuard:
    """Guard 4: normalization/threshold statistics from healthy data only."""

    def validate(self, source: PartitionRef) -> None:
        if source not in HEALTHY_PARTITIONS:
            raise ThresholdProvenanceError(
                "Guard 4: normalization/threshold statistics must derive from "
                "a healthy partition, never from fault or test periods "
                "(PROJECT.md §22)",
                source=source.value,
            )


@dataclass(frozen=True)
class TargetStats:
    """Per-target location/scale fitted on healthy residuals."""

    center: float
    scale: float


class ResidualNormalizer(Protocol):
    """M-19b contract (ARCHITECTURE.md §5.3)."""

    def fit(self, healthy: ResidualFrame, source: PartitionRef) -> None: ...

    def transform(self, residuals: ResidualFrame) -> ResidualFrame: ...

    def fitted_stats(self) -> dict[str, Any]: ...


class _ScaleNormalizer:
    """Shared mechanics: per-target center/scale from healthy residuals."""

    method: NormalizationMethod

    def __init__(self) -> None:
        self._stats: dict[str, TargetStats] = {}
        self._source: PartitionRef | None = None

    def _center_scale(self, values: np.ndarray) -> TargetStats:  # pragma: no cover
        raise NotImplementedError

    @property
    def source(self) -> PartitionRef:
        if self._source is None:
            raise ConfigError("Normalizer is not fitted; statistics source unknown")
        return self._source

    def fit(self, healthy: ResidualFrame, source: PartitionRef) -> None:
        ThresholdProvenanceGuard().validate(source)
        frame = healthy.data
        stats: dict[str, TargetStats] = {}
        for target, group in frame.groupby(TARGET_COLUMN, observed=True):
            values = group[RAW_RESIDUAL_COLUMN].to_numpy(dtype=float)
            values = values[~np.isnan(values)]
            if len(values) == 0:
                raise ConfigError("No healthy residuals to fit", target=str(target))
            fitted = self._center_scale(values)
            if fitted.scale == 0.0:
                raise ConfigError(
                    "Degenerate scale (zero spread) in healthy residuals", target=str(target)
                )
            stats[str(target)] = fitted
        self._stats = stats
        self._source = source

    def transform(self, residuals: ResidualFrame) -> ResidualFrame:
        if not self._stats:
            raise ConfigError("Normalizer is not fitted")
        frame = residuals.data
        missing = [t for t in residuals.targets if t not in self._stats]
        if missing:
            raise ConfigError("Normalizer was not fitted for target(s)", missing=missing)
        centers = frame[TARGET_COLUMN].map({t: s.center for t, s in self._stats.items()})
        scales = frame[TARGET_COLUMN].map({t: s.scale for t, s in self._stats.items()})
        normalized = (frame[RAW_RESIDUAL_COLUMN] - centers.astype(float)) / scales.astype(float)
        return residuals.with_normalized(normalized)

    def fitted_stats(self) -> dict[str, Any]:
        """Statistics record for experiment metadata; always names its source."""
        return {
            "method": self.method.value,
            "source": self.source.value,
            "per_target": {
                t: {"center": s.center, "scale": s.scale} for t, s in self._stats.items()
            },
        }


class SigmaNormalizer(_ScaleNormalizer):
    method = NormalizationMethod.SIGMA

    def _center_scale(self, values: np.ndarray) -> TargetStats:
        return TargetStats(center=float(np.mean(values)), scale=float(np.std(values, ddof=1)))


class MadNormalizer(_ScaleNormalizer):
    method = NormalizationMethod.MAD

    def _center_scale(self, values: np.ndarray) -> TargetStats:
        median = float(np.median(values))
        mad = float(np.median(np.abs(values - median)))
        return TargetStats(center=median, scale=MAD_SIGMA_CONSISTENCY * mad)


class PercentileNormalizer(_ScaleNormalizer):
    method = NormalizationMethod.PERCENTILE

    def __init__(self, lower: float = 25.0, upper: float = 75.0) -> None:
        super().__init__()
        if not 0.0 <= lower < upper <= 100.0:
            raise ConfigError("Invalid percentile bounds", lower=lower, upper=upper)
        self.lower = lower
        self.upper = upper

    def _center_scale(self, values: np.ndarray) -> TargetStats:
        low, high = np.percentile(values, [self.lower, self.upper])
        return TargetStats(
            center=float(np.median(values)),
            scale=float(high - low) / IQR_SIGMA_CONSISTENCY,
        )


class ConditionBinnedNormalizer:
    """Per-(target, condition-bin) MAD statistics (PROJECT.md §22).

    For use when §20 diagnostics show error spread varies by operating
    condition. Bin edges come from healthy-data quantiles of the declared
    condition column (which must be carried in the ResidualFrame rows);
    out-of-range values clip into the edge bins.
    """

    method = NormalizationMethod.CONDITION_BINNED

    def __init__(self, condition_column: str, n_bins: int = 5) -> None:
        if n_bins < 2:
            raise ConfigError("Condition binning needs at least 2 bins", n_bins=n_bins)
        self.condition_column = condition_column
        self.n_bins = n_bins
        self._edges: np.ndarray | None = None
        self._stats: dict[tuple[str, int], TargetStats] = {}
        self._fallback: dict[str, TargetStats] = {}
        self._source: PartitionRef | None = None

    @property
    def source(self) -> PartitionRef:
        if self._source is None:
            raise ConfigError("Normalizer is not fitted; statistics source unknown")
        return self._source

    def _bin_index(self, condition: pd.Series) -> np.ndarray:
        assert self._edges is not None
        indices = np.searchsorted(self._edges, condition.to_numpy(dtype=float), side="right") - 1
        clipped: np.ndarray = np.clip(indices, 0, self.n_bins - 1)
        return clipped

    def fit(self, healthy: ResidualFrame, source: PartitionRef) -> None:
        ThresholdProvenanceGuard().validate(source)
        frame = healthy.data
        if self.condition_column not in frame.columns:
            raise ConfigError(
                "ResidualFrame does not carry the condition column",
                condition_column=self.condition_column,
            )
        condition = frame[self.condition_column].to_numpy(dtype=float)
        quantiles = np.linspace(0.0, 1.0, self.n_bins + 1)
        self._edges = np.quantile(condition[~np.isnan(condition)], quantiles)
        bins = self._bin_index(frame[self.condition_column])
        stats: dict[tuple[str, int], TargetStats] = {}
        for group_key, group in frame.groupby(
            [TARGET_COLUMN, pd.Series(bins, index=frame.index, name="bin")], observed=True
        ):
            key: Any = group_key
            target, bin_id = key
            values = group[RAW_RESIDUAL_COLUMN].to_numpy(dtype=float)
            values = values[~np.isnan(values)]
            if len(values) < 2:
                continue
            median = float(np.median(values))
            mad = float(np.median(np.abs(values - median)))
            if mad > 0.0:
                stats[(str(target), int(bin_id))] = TargetStats(
                    center=median, scale=MAD_SIGMA_CONSISTENCY * mad
                )
        if not stats:
            raise ConfigError("No condition bin had enough healthy residuals to fit")
        self._fallback = self._global_stats(frame)
        self._stats = stats
        self._source = source

    @staticmethod
    def _global_stats(frame: pd.DataFrame) -> dict[str, TargetStats]:
        fallback: dict[str, TargetStats] = {}
        for target, group in frame.groupby(TARGET_COLUMN, observed=True):
            values = group[RAW_RESIDUAL_COLUMN].to_numpy(dtype=float)
            values = values[~np.isnan(values)]
            median = float(np.median(values))
            mad = float(np.median(np.abs(values - median)))
            if mad == 0.0:
                raise ConfigError("Degenerate global fallback scale", target=str(target))
            fallback[str(target)] = TargetStats(center=median, scale=MAD_SIGMA_CONSISTENCY * mad)
        return fallback

    def transform(self, residuals: ResidualFrame) -> ResidualFrame:
        if not self._stats or self._edges is None:
            raise ConfigError("Normalizer is not fitted")
        frame = residuals.data
        if self.condition_column not in frame.columns:
            raise ConfigError(
                "ResidualFrame does not carry the condition column",
                condition_column=self.condition_column,
            )
        bins = self._bin_index(frame[self.condition_column])
        normalized = np.empty(len(frame), dtype=float)
        raw = frame[RAW_RESIDUAL_COLUMN].to_numpy(dtype=float)
        target_values = frame[TARGET_COLUMN].astype(str).to_numpy()
        for i in range(len(frame)):
            stats = self._stats.get((target_values[i], int(bins[i])))
            if stats is None:
                stats = self._fallback[target_values[i]]
            normalized[i] = (raw[i] - stats.center) / stats.scale
        return residuals.with_normalized(pd.Series(normalized, index=frame.index))

    def fitted_stats(self) -> dict[str, Any]:
        assert self._edges is not None
        return {
            "method": self.method.value,
            "source": self.source.value,
            "condition_column": self.condition_column,
            "bin_edges": [float(e) for e in self._edges],
            "per_target_bin": {
                f"{target}|{bin_id}": {"center": s.center, "scale": s.scale}
                for (target, bin_id), s in self._stats.items()
            },
        }


def make_normalizer(
    method: NormalizationMethod,
    *,
    condition_column: str | None = None,
    n_bins: int = 5,
) -> ResidualNormalizer:
    """Config enum → normalizer instance (all four §22 families selectable)."""
    if method is NormalizationMethod.SIGMA:
        return SigmaNormalizer()
    if method is NormalizationMethod.MAD:
        return MadNormalizer()
    if method is NormalizationMethod.PERCENTILE:
        return PercentileNormalizer()
    if method is NormalizationMethod.CONDITION_BINNED:
        if condition_column is None:
            raise ConfigError("condition_binned normalization requires a condition column")
        return ConditionBinnedNormalizer(condition_column, n_bins)
    raise ConfigError("Unknown normalization method", method=str(method))
