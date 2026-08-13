"""Dataset validation rule engine (M-10; PROJECT.md §11).

Findings are DATA, not exceptions: the pipeline reports them and lets
configuration decide consequences. Methodology violations raise; imperfect
data does not. Validation is strictly read-only — a test asserts the dataset
hash is unchanged across a run.

Step-change detection is included because a sensor replacement or
recalibration produces a sustained level shift that mimics or masks a fault.
Detected steps are reported with timestamp and magnitude and flagged for
healthy-state review; they are NEVER auto-corrected (PROJECT.md §11).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

import numpy as np
import pandas as pd

from app.core.config import ValidationConfig
from app.data.ingestion import CanonicalDataset
from app.data.schema import CanonicalSchema, VariableRole


class Level(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass(frozen=True)
class Finding:
    """One validation observation. Data, never an exception."""

    level: Level
    rule_id: str
    message: str
    affected_rows: int = 0
    context: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "rule_id": self.rule_id,
            "message": self.message,
            "affected_rows": self.affected_rows,
            "context": self.context,
        }


@dataclass(frozen=True)
class StepChange:
    """A sustained level shift in a channel (candidate recalibration)."""

    column: str
    turbine: str
    timestamp_utc: pd.Timestamp
    magnitude: float
    before_median: float
    after_median: float


@dataclass(frozen=True)
class DatasetReport:
    findings: list[Finding]
    n_rows: int
    n_columns: int
    date_range_utc: tuple[pd.Timestamp | None, pd.Timestamp | None]
    turbines: list[str]
    sampling_intervals: dict[str, int]
    step_changes: list[StepChange]

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level is Level.ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level is Level.WARNING]

    def as_dict(self) -> dict[str, Any]:
        return {
            "findings": [f.as_dict() for f in self.findings],
            "n_rows": self.n_rows,
            "n_columns": self.n_columns,
            "date_range_utc": [None if t is None else t.isoformat() for t in self.date_range_utc],
            "turbines": self.turbines,
            "sampling_intervals": self.sampling_intervals,
            "step_changes": [
                {
                    "column": s.column,
                    "turbine": s.turbine,
                    "timestamp_utc": s.timestamp_utc.isoformat(),
                    "magnitude": s.magnitude,
                    "before_median": s.before_median,
                    "after_median": s.after_median,
                }
                for s in self.step_changes
            ],
        }


class ValidationRule(Protocol):
    rule_id: str

    def check(self, dataset: CanonicalDataset, schema: CanonicalSchema) -> list[Finding]: ...


class TimestampRule:
    """Parsing failures, duplicates, ordering, irregular sampling, gaps."""

    rule_id = "TIMESTAMP"

    def check(self, dataset: CanonicalDataset, schema: CanonicalSchema) -> list[Finding]:
        frame, column = dataset.frame, schema.timestamp_name
        findings: list[Finding] = []
        stamps = frame[column]
        n_invalid = int(stamps.isna().sum())
        if n_invalid:
            findings.append(
                Finding(
                    Level.ERROR,
                    f"{self.rule_id}.UNPARSEABLE",
                    "Timestamps failed to parse",
                    n_invalid,
                )
            )
        if stamps.dt.tz is None:
            findings.append(
                Finding(
                    Level.ERROR,
                    f"{self.rule_id}.NAIVE",
                    "Timestamps are not timezone-aware after ingestion",
                )
            )
        turbine_column = schema.turbine_id_name
        subset = [turbine_column, column] if turbine_column in frame.columns else [column]
        n_dupes = int(frame.duplicated(subset=subset).sum())
        if n_dupes:
            findings.append(
                Finding(
                    Level.WARNING,
                    f"{self.rule_id}.DUPLICATE",
                    "Duplicate turbine/timestamp combinations remain after ingestion",
                    n_dupes,
                )
            )
        for turbine, group in _by_turbine(frame, turbine_column):
            ordered = group[column].sort_values()
            if not group[column].equals(ordered):
                findings.append(
                    Finding(
                        Level.INFO,
                        f"{self.rule_id}.ORDER",
                        "Rows are not in ascending time order",
                        context={"turbine": turbine},
                    )
                )
            deltas = ordered.diff().dropna()
            if deltas.empty:
                continue
            modal = deltas.mode().iloc[0]
            gaps = deltas[deltas > modal]
            if len(gaps):
                findings.append(
                    Finding(
                        Level.WARNING,
                        f"{self.rule_id}.GAP",
                        "Sampling gaps larger than the modal interval",
                        len(gaps),
                        {
                            "turbine": turbine,
                            "modal_interval": str(modal),
                            "largest_gap": str(gaps.max()),
                        },
                    )
                )
        return findings


class MissingValueRule:
    rule_id = "MISSING"

    def check(self, dataset: CanonicalDataset, schema: CanonicalSchema) -> list[Finding]:
        findings: list[Finding] = []
        for column in dataset.frame.columns:
            fraction = float(dataset.frame[column].isna().mean())
            if fraction > 0:
                level = Level.WARNING if fraction >= 0.5 else Level.INFO
                findings.append(
                    Finding(
                        level,
                        f"{self.rule_id}.NULLS",
                        f"Column has missing values ({fraction:.1%})",
                        int(dataset.frame[column].isna().sum()),
                        {"column": column, "null_fraction": round(fraction, 6)},
                    )
                )
        return findings


class ConstantColumnRule:
    rule_id = "CONSTANT"

    def check(self, dataset: CanonicalDataset, schema: CanonicalSchema) -> list[Finding]:
        findings: list[Finding] = []
        for column in dataset.frame.columns:
            series = dataset.frame[column].dropna()
            if series.empty:
                findings.append(
                    Finding(
                        Level.WARNING,
                        f"{self.rule_id}.EMPTY",
                        "Column is entirely missing",
                        context={"column": column},
                    )
                )
            elif series.nunique() == 1:
                findings.append(
                    Finding(
                        Level.INFO,
                        f"{self.rule_id}.SINGLE_VALUE",
                        "Column has a single distinct value",
                        context={"column": column},
                    )
                )
        return findings


class RangeRule:
    """Impossible values, per the bounds the schema declares per variable."""

    rule_id = "RANGE"

    def check(self, dataset: CanonicalDataset, schema: CanonicalSchema) -> list[Finding]:
        findings: list[Finding] = []
        for variable in schema.variables:
            if variable.plausible_range is None or variable.name not in dataset.frame.columns:
                continue
            column = variable.name
            low, high = variable.plausible_range
            series = dataset.frame[column]
            outside = int(((series < low) | (series > high)).sum())
            if outside:
                findings.append(
                    Finding(
                        Level.ERROR,
                        f"{self.rule_id}.IMPOSSIBLE",
                        "Values outside physically possible bounds",
                        outside,
                        {"column": column, "bounds": [low, high]},
                    )
                )
        return findings


class ResearchSchemaRule:
    """Required roles present: targets and configured predictors."""

    rule_id = "SCHEMA"

    def check(self, dataset: CanonicalDataset, schema: CanonicalSchema) -> list[Finding]:
        findings: list[Finding] = []
        for role in (VariableRole.TARGET, VariableRole.PREDICTOR):
            present = [v.name for v in schema.by_role(role) if v.name in dataset.frame.columns]
            if not present:
                findings.append(
                    Finding(
                        Level.ERROR,
                        f"{self.rule_id}.ROLE_ABSENT",
                        f"No {role.value} variables present in the dataset",
                        context={"role": role.value},
                    )
                )
        if dataset.schema_version != schema.schema_version:
            findings.append(
                Finding(
                    Level.WARNING,
                    f"{self.rule_id}.VERSION",
                    "Dataset was produced under a different schema version",
                    context={"dataset": dataset.schema_version, "current": schema.schema_version},
                )
            )
        return findings


class StepChangeRule:
    """Rolling-median change-point heuristic on thermal channels.

    A sustained shift in level — sensor replacement or recalibration — mimics
    or masks a fault. Detected windows are reported, never corrected.
    """

    rule_id = "STEP_CHANGE"

    def __init__(self, window: int | None = None, min_magnitude: float | None = None) -> None:
        # Parameter values live in ValidationConfig (provisional, LIM-014);
        # None resolves to the config defaults so there is a single source.
        defaults = ValidationConfig()
        self.window = window if window is not None else defaults.step_change_window_samples
        self.min_magnitude = (
            min_magnitude if min_magnitude is not None else defaults.step_change_min_magnitude_c
        )
        self.detected: list[StepChange] = []

    def check(self, dataset: CanonicalDataset, schema: CanonicalSchema) -> list[Finding]:
        self.detected = []
        findings: list[Finding] = []
        targets = [v.name for v in schema.by_role(VariableRole.TARGET)]
        columns = [c for c in targets if c in dataset.frame.columns]
        turbine_column = schema.turbine_id_name
        for turbine, group in _by_turbine(dataset.frame, turbine_column):
            ordered = group.sort_values(schema.timestamp_name)
            for column in columns:
                for step in self._detect(ordered, column, schema, turbine):
                    self.detected.append(step)
                    findings.append(
                        Finding(
                            Level.WARNING,
                            f"{self.rule_id}.SHIFT",
                            "Sustained level shift detected; flagged for healthy-state "
                            "review, not corrected",
                            context={
                                "column": column,
                                "turbine": turbine,
                                "timestamp_utc": step.timestamp_utc.isoformat(),
                                "magnitude": step.magnitude,
                            },
                        )
                    )
        return findings

    def _detect(
        self, frame: pd.DataFrame, column: str, schema: CanonicalSchema, turbine: str
    ) -> list[StepChange]:
        series = frame[column]
        if series.notna().sum() < 2 * self.window:
            return []
        before = series.rolling(self.window, min_periods=self.window // 2).median()
        after = series[::-1].rolling(self.window, min_periods=self.window // 2).median()[::-1]
        delta = (after - before).abs()
        candidates = delta > self.min_magnitude
        if not candidates.any():
            return []
        steps: list[StepChange] = []
        index = np.flatnonzero(candidates.to_numpy())
        groups = np.split(index, np.flatnonzero(np.diff(index) > self.window) + 1)
        for group in groups:
            if len(group) == 0:
                continue
            peak = group[int(np.argmax(delta.to_numpy()[group]))]
            steps.append(
                StepChange(
                    column=column,
                    turbine=turbine,
                    timestamp_utc=frame[schema.timestamp_name].iloc[peak],
                    magnitude=round(float(delta.iloc[peak]), 4),
                    before_median=round(float(before.iloc[peak]), 4),
                    after_median=round(float(after.iloc[peak]), 4),
                )
            )
        return steps


def _by_turbine(frame: pd.DataFrame, turbine_column: str) -> list[tuple[str, pd.DataFrame]]:
    if turbine_column not in frame.columns:
        return [("", frame)]
    return [(str(name), group) for name, group in frame.groupby(turbine_column, observed=True)]


def default_rules(validation: ValidationConfig | None = None) -> list[ValidationRule]:
    validation = validation if validation is not None else ValidationConfig()
    return [
        TimestampRule(),
        MissingValueRule(),
        ConstantColumnRule(),
        RangeRule(),
        ResearchSchemaRule(),
        StepChangeRule(
            window=validation.step_change_window_samples,
            min_magnitude=validation.step_change_min_magnitude_c,
        ),
    ]


def validate(
    dataset: CanonicalDataset,
    schema: CanonicalSchema,
    rules: list[ValidationRule] | None = None,
) -> DatasetReport:
    """Run every rule and assemble the report. Never mutates the dataset."""
    rules = rules if rules is not None else default_rules()
    findings: list[Finding] = []
    step_changes: list[StepChange] = []
    for rule in rules:
        findings.extend(rule.check(dataset, schema))
        if isinstance(rule, StepChangeRule):
            step_changes.extend(rule.detected)

    frame = dataset.frame
    stamps = frame[schema.timestamp_name].dropna()
    intervals: dict[str, int] = {}
    for _, group in _by_turbine(frame, schema.turbine_id_name):
        deltas = group[schema.timestamp_name].sort_values().diff().dropna()
        for value, count in deltas.value_counts().items():
            intervals[str(value)] = intervals.get(str(value), 0) + int(count)
    turbines = (
        sorted({str(t) for t in frame[schema.turbine_id_name].dropna().unique()})
        if schema.turbine_id_name in frame.columns
        else []
    )
    return DatasetReport(
        findings=findings,
        n_rows=len(frame),
        n_columns=frame.shape[1],
        date_range_utc=((stamps.min(), stamps.max()) if not stamps.empty else (None, None)),
        turbines=turbines,
        sampling_intervals=intervals,
        step_changes=step_changes,
    )
