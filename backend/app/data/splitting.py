"""Chronological splitting and seasonal coverage (M-13; PROJECT.md §14).

Random shuffled splits are prohibited for thesis experiments (LOCKED-04);
`SplitPolicyGuard` (Guard 3) makes that unbypassable on thesis-flagged runs.

The seasonal coverage check exists because a training window shorter than a
year cannot represent the ambient conditions the test period contains, so
residual inflation in the test period may reflect seasonal covariate shift
rather than degradation (risk R2). Warnings are surfaced for LIMITATIONS.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any

import pandas as pd

from app.core.errors import SplitPolicyError
from app.core.logging import get_logger
from app.data.ingestion import CanonicalDataset
from app.data.schema import AMBIENT_TEMPERATURE, CanonicalSchema

_logger = get_logger("data.splitting")

MIN_TRAINING_MONTHS = 12


class SplitStrategy(StrEnum):
    CHRONOLOGICAL = "chronological"
    EXPLICIT_DATES = "explicit_dates"
    ROLLING_ORIGIN = "rolling_origin"
    #: Present so Guard 3 has something to reject; never valid for thesis runs.
    RANDOM = "random"


@dataclass(frozen=True)
class SplitSpec:
    strategy: SplitStrategy = SplitStrategy.CHRONOLOGICAL
    train_fraction: float = 0.70
    validation_fraction: float = 0.15
    test_fraction: float = 0.15
    train_end: date | None = None
    validation_end: date | None = None
    n_folds: int = 5

    def __post_init__(self) -> None:
        if self.strategy is SplitStrategy.CHRONOLOGICAL:
            total = self.train_fraction + self.validation_fraction + self.test_fraction
            if abs(total - 1.0) > 1e-9:
                raise SplitPolicyError("Split fractions must sum to 1", total=total)
        if self.strategy is SplitStrategy.EXPLICIT_DATES and (
            self.train_end is None or self.validation_end is None
        ):
            raise SplitPolicyError("Explicit-date splits require train_end and validation_end")
        if (
            self.train_end is not None
            and self.validation_end is not None
            and self.validation_end <= self.train_end
        ):
            raise SplitPolicyError(
                "Split periods overlap: validation_end must follow train_end",
                train_end=str(self.train_end),
                validation_end=str(self.validation_end),
            )


@dataclass(frozen=True)
class SeasonalCoverageReport:
    train_months: float
    train_calendar_months: list[int]
    test_calendar_months: list[int]
    months_in_test_absent_from_train: list[int]
    ambient_range_train: tuple[float, float] | None
    ambient_range_test: tuple[float, float] | None
    warnings: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "train_months": self.train_months,
            "train_calendar_months": self.train_calendar_months,
            "test_calendar_months": self.test_calendar_months,
            "months_in_test_absent_from_train": self.months_in_test_absent_from_train,
            "ambient_range_train": list(self.ambient_range_train)
            if self.ambient_range_train
            else None,
            "ambient_range_test": list(self.ambient_range_test)
            if self.ambient_range_test
            else None,
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class Split:
    train: pd.Index
    validation: pd.Index
    test: pd.Index
    spec: SplitSpec
    seasonal_coverage: SeasonalCoverageReport
    boundaries_utc: tuple[pd.Timestamp | None, pd.Timestamp | None]

    def disjoint(self) -> bool:
        return (
            len(self.train.intersection(self.validation)) == 0
            and len(self.validation.intersection(self.test)) == 0
            and len(self.train.intersection(self.test)) == 0
        )


@dataclass(frozen=True)
class ExperimentFlags:
    thesis_official: bool = True


class SplitPolicyGuard:
    """Guard 3: no random splitting on thesis-flagged experiments."""

    def validate(self, spec: SplitSpec, flags: ExperimentFlags) -> None:
        if flags.thesis_official and spec.strategy is SplitStrategy.RANDOM:
            raise SplitPolicyError(
                "Random splitting is prohibited for thesis experiments (LOCKED-04)",
                strategy=spec.strategy.value,
            )


def seasonal_coverage(
    frame: pd.DataFrame,
    schema: CanonicalSchema,
    train_index: pd.Index,
    test_index: pd.Index,
) -> SeasonalCoverageReport:
    timestamp = schema.timestamp_name
    train_times = frame.loc[train_index, timestamp].dropna()
    test_times = frame.loc[test_index, timestamp].dropna()
    warnings: list[str] = []

    months = 0.0
    if not train_times.empty:
        span = train_times.max() - train_times.min()
        months = round(span.days / 30.4375, 3)
    train_calendar = sorted({int(t.month) for t in train_times})
    test_calendar = sorted({int(t.month) for t in test_times})
    absent = sorted(set(test_calendar) - set(train_calendar))

    if months < MIN_TRAINING_MONTHS:
        warnings.append(
            f"Training window spans {months} months (< {MIN_TRAINING_MONTHS}); residual "
            "inflation in the test period may reflect seasonal covariate shift rather "
            "than degradation"
        )
    if absent:
        warnings.append(
            f"Calendar months present in test but absent from training: {absent}; residual "
            "inflation in those months may reflect seasonal covariate shift rather than "
            "degradation"
        )

    ambient = AMBIENT_TEMPERATURE
    train_range: tuple[float, float] | None = None
    test_range: tuple[float, float] | None = None
    if ambient in frame.columns:
        train_values = frame.loc[train_index, ambient].dropna()
        test_values = frame.loc[test_index, ambient].dropna()
        if not train_values.empty:
            train_range = (round(float(train_values.min()), 3), round(float(train_values.max()), 3))
        if not test_values.empty:
            test_range = (round(float(test_values.min()), 3), round(float(test_values.max()), 3))
        if (
            train_range
            and test_range
            and (test_range[0] < train_range[0] or test_range[1] > train_range[1])
        ):
            warnings.append(
                "Test ambient temperature extends beyond the training range "
                f"(train {train_range}, test {test_range}); the model extrapolates"
            )
    for warning in warnings:
        _logger.warning("Seasonal coverage: %s", warning)
    return SeasonalCoverageReport(
        train_months=months,
        train_calendar_months=train_calendar,
        test_calendar_months=test_calendar,
        months_in_test_absent_from_train=absent,
        ambient_range_train=train_range,
        ambient_range_test=test_range,
        warnings=warnings,
    )


def split_chronologically(
    dataset: CanonicalDataset,
    schema: CanonicalSchema,
    spec: SplitSpec,
    flags: ExperimentFlags | None = None,
) -> Split:
    """Chronological or explicit-date split with seasonal coverage reporting."""
    SplitPolicyGuard().validate(spec, flags or ExperimentFlags())

    timestamp = schema.timestamp_name
    ordered = dataset.frame.sort_values(timestamp)
    stamps = ordered[timestamp]
    n = len(ordered)
    if n == 0:
        raise SplitPolicyError("Cannot split an empty dataset")

    boundaries: tuple[pd.Timestamp | None, pd.Timestamp | None]
    if spec.strategy is SplitStrategy.EXPLICIT_DATES:
        # SplitSpec.__post_init__ guarantees both dates are present here.
        assert spec.train_end is not None and spec.validation_end is not None
        train_end = pd.Timestamp(spec.train_end, tz="UTC")
        validation_end = pd.Timestamp(spec.validation_end, tz="UTC")
        train_index = ordered.index[stamps < train_end]
        validation_index = ordered.index[(stamps >= train_end) & (stamps < validation_end)]
        test_index = ordered.index[stamps >= validation_end]
        boundaries = (train_end, validation_end)
    else:
        n_train = int(n * spec.train_fraction)
        n_validation = int(n * spec.validation_fraction)
        train_index = ordered.index[:n_train]
        validation_index = ordered.index[n_train : n_train + n_validation]
        test_index = ordered.index[n_train + n_validation :]
        boundaries = (
            stamps.iloc[n_train] if n_train < n else None,
            stamps.iloc[n_train + n_validation] if n_train + n_validation < n else None,
        )

    coverage = seasonal_coverage(ordered, schema, train_index, test_index)
    split = Split(
        train=train_index,
        validation=validation_index,
        test=test_index,
        spec=spec,
        seasonal_coverage=coverage,
        boundaries_utc=boundaries,
    )
    if not split.disjoint():
        raise SplitPolicyError("Split partitions overlap")
    return split


def rolling_origin_folds(
    dataset: CanonicalDataset, schema: CanonicalSchema, spec: SplitSpec
) -> list[tuple[pd.Index, pd.Index]]:
    """Blocked time-series folds: each training block precedes its test block."""
    ordered = dataset.frame.sort_values(schema.timestamp_name)
    n = len(ordered)
    if spec.n_folds < 2 or n < spec.n_folds + 1:
        raise SplitPolicyError("Too few observations for the requested folds", n_folds=spec.n_folds)
    block = n // (spec.n_folds + 1)
    folds: list[tuple[pd.Index, pd.Index]] = []
    for fold in range(1, spec.n_folds + 1):
        train_end = block * fold
        test_end = block * (fold + 1) if fold < spec.n_folds else n
        folds.append((ordered.index[:train_end], ordered.index[train_end:test_end]))
    return folds
