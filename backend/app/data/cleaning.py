"""Audit-trailed cleaning pipeline (M-11; PROJECT.md §12).

Every operation records rule, reason, and before/after counts. No path
removes rows without an audit entry: the operation registry is the only way
to alter data, and a meta-test asserts each registered operation emits one.
The cleaned dataset stays provenance-chained to the raw sources.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.core.errors import ConfigError
from app.core.logging import get_logger
from app.data.ingestion import CanonicalDataset
from app.data.schema import CanonicalSchema, VariableRole

_logger = get_logger("data.cleaning")


@dataclass(frozen=True)
class CleaningOperationRecord:
    rule: str
    reason: str
    rows_before: int
    rows_after: int

    @property
    def rows_removed(self) -> int:
        return self.rows_before - self.rows_after

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "reason": self.reason,
            "rows_before": self.rows_before,
            "rows_after": self.rows_after,
            "rows_removed": self.rows_removed,
        }


@dataclass
class CleaningAudit:
    operations: list[CleaningOperationRecord] = field(default_factory=list)

    @property
    def total_removed(self) -> int:
        return sum(op.rows_removed for op in self.operations)

    def arithmetic_holds(self) -> bool:
        """before - removed = after, per operation and in aggregate."""
        for op in self.operations:
            if op.rows_before - op.rows_removed != op.rows_after:
                return False
        for earlier, later in zip(self.operations, self.operations[1:], strict=False):
            if earlier.rows_after != later.rows_before:
                return False
        return True

    def as_dict(self) -> dict[str, Any]:
        return {
            "operations": [op.as_dict() for op in self.operations],
            "total_removed": self.total_removed,
            "arithmetic_holds": self.arithmetic_holds(),
        }


CleaningFunction = Callable[[pd.DataFrame, CanonicalSchema], pd.DataFrame]


@dataclass(frozen=True)
class CleaningOperation:
    name: str
    reason: str
    apply: CleaningFunction


def drop_unparseable_timestamps(frame: pd.DataFrame, schema: CanonicalSchema) -> pd.DataFrame:
    return frame[frame[schema.timestamp_name].notna()]


def drop_missing_all_targets(frame: pd.DataFrame, schema: CanonicalSchema) -> pd.DataFrame:
    targets = [v.name for v in schema.by_role(VariableRole.TARGET) if v.name in frame.columns]
    if not targets:
        return frame
    return frame[frame[targets].notna().any(axis=1)]


def drop_missing_any_target(frame: pd.DataFrame, schema: CanonicalSchema) -> pd.DataFrame:
    targets = [v.name for v in schema.by_role(VariableRole.TARGET) if v.name in frame.columns]
    if not targets:
        return frame
    return frame[frame[targets].notna().all(axis=1)]


def drop_missing_any_predictor(frame: pd.DataFrame, schema: CanonicalSchema) -> pd.DataFrame:
    predictors = [v.name for v in schema.by_role(VariableRole.PREDICTOR) if v.name in frame.columns]
    if not predictors:
        return frame
    return frame[frame[predictors].notna().all(axis=1)]


#: The only operations that may alter data. Each carries its audit reason.
OPERATION_REGISTRY: dict[str, CleaningOperation] = {
    "drop_unparseable_timestamps": CleaningOperation(
        "drop_unparseable_timestamps",
        "Timestamp could not be parsed; the row cannot be placed in time",
        drop_unparseable_timestamps,
    ),
    "drop_missing_all_targets": CleaningOperation(
        "drop_missing_all_targets",
        "No thermal target present; the row carries no modelling signal",
        drop_missing_all_targets,
    ),
    "drop_missing_any_target": CleaningOperation(
        "drop_missing_any_target",
        "At least one thermal target missing; multi-target fitting requires all",
        drop_missing_any_target,
    ),
    "drop_missing_any_predictor": CleaningOperation(
        "drop_missing_any_predictor",
        "At least one predictor missing; the model cannot score the row",
        drop_missing_any_predictor,
    ),
}


def clean(
    dataset: CanonicalDataset,
    schema: CanonicalSchema,
    operations: list[str],
) -> tuple[CanonicalDataset, CleaningAudit]:
    """Apply the named operations in order, recording every one."""
    unknown = [name for name in operations if name not in OPERATION_REGISTRY]
    if unknown:
        raise ConfigError("Unknown cleaning operation(s)", unknown=unknown)

    frame = dataset.frame
    audit = CleaningAudit()
    for name in operations:
        operation = OPERATION_REGISTRY[name]
        before = len(frame)
        frame = operation.apply(frame, schema)
        record = CleaningOperationRecord(
            rule=operation.name,
            reason=operation.reason,
            rows_before=before,
            rows_after=len(frame),
        )
        audit.operations.append(record)
        if record.rows_removed:
            _logger.info("Cleaning %s removed %d rows", operation.name, record.rows_removed)

    cleaned = dataset.with_frame(frame.reset_index(drop=True), stage="cleaned")
    return cleaned, audit
