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
    #: Operation-specific counts (e.g. values nullified per column) for
    #: operations whose effect is not captured by row counts alone.
    detail: dict[str, Any] = field(default_factory=dict)

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
            "detail": self.detail,
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


#: Operations return the new frame plus a detail dict for the audit record
#: (empty when row counts tell the whole story).
CleaningFunction = Callable[[pd.DataFrame, CanonicalSchema], tuple[pd.DataFrame, dict[str, Any]]]


@dataclass(frozen=True)
class CleaningOperation:
    name: str
    reason: str
    apply: CleaningFunction


def drop_unparseable_timestamps(
    frame: pd.DataFrame, schema: CanonicalSchema
) -> tuple[pd.DataFrame, dict[str, Any]]:
    return frame[frame[schema.timestamp_name].notna()], {}


def drop_missing_all_targets(
    frame: pd.DataFrame, schema: CanonicalSchema
) -> tuple[pd.DataFrame, dict[str, Any]]:
    targets = [v.name for v in schema.by_role(VariableRole.TARGET) if v.name in frame.columns]
    if not targets:
        return frame, {}
    return frame[frame[targets].notna().any(axis=1)], {}


def drop_missing_any_target(
    frame: pd.DataFrame, schema: CanonicalSchema
) -> tuple[pd.DataFrame, dict[str, Any]]:
    targets = [v.name for v in schema.by_role(VariableRole.TARGET) if v.name in frame.columns]
    if not targets:
        return frame, {}
    return frame[frame[targets].notna().all(axis=1)], {}


def drop_missing_any_predictor(
    frame: pd.DataFrame, schema: CanonicalSchema
) -> tuple[pd.DataFrame, dict[str, Any]]:
    predictors = [v.name for v in schema.by_role(VariableRole.PREDICTOR) if v.name in frame.columns]
    if not predictors:
        return frame, {}
    return frame[frame[predictors].notna().all(axis=1)], {}


def _impossible_predictor_cells(
    frame: pd.DataFrame, schema: CanonicalSchema
) -> dict[str, pd.Series]:
    """Per-predictor mask of values outside the schema's plausible_range
    (RangeRule semantics: strictly below low or strictly above high)."""
    masks: dict[str, pd.Series] = {}
    for variable in schema.by_role(VariableRole.PREDICTOR):
        if variable.plausible_range is None or variable.name not in frame.columns:
            continue
        low, high = variable.plausible_range
        series = frame[variable.name]
        outside = (series < low) | (series > high)
        if bool(outside.any()):
            masks[variable.name] = outside
    return masks


def impossible_predictor_rows(frame: pd.DataFrame, schema: CanonicalSchema) -> pd.Series:
    """Row mask: at least one predictor value the schema declares impossible."""
    mask = pd.Series(False, index=frame.index)
    for outside in _impossible_predictor_cells(frame, schema).values():
        mask |= outside
    return mask


def nullify_impossible_predictor_values(
    frame: pd.DataFrame, schema: CanonicalSchema
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """ADR-020: a value the schema declares physically impossible cannot
    serve as a model input anywhere. Set it to missing so the row is removed
    by ``drop_missing_any_predictor`` with its audit trail — in every
    partition, monitoring included."""
    cells = _impossible_predictor_cells(frame, schema)
    if not cells:
        return frame, {}
    frame = frame.copy()
    by_column: dict[str, int] = {}
    rows = pd.Series(False, index=frame.index)
    for column, outside in cells.items():
        by_column[column] = int(outside.sum())
        rows |= outside
        frame.loc[outside, column] = float("nan")
    return frame, {
        "rows_affected": int(rows.sum()),
        "values_nullified": int(sum(by_column.values())),
        "by_column": by_column,
    }


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
    "nullify_impossible_predictor_values": CleaningOperation(
        "nullify_impossible_predictor_values",
        "Predictor value outside the schema's physically possible bounds; "
        "set to missing so the row is dropped with an audit trail (ADR-020)",
        nullify_impossible_predictor_values,
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
    # ADR-020: nullified impossible values must not survive as inputs — the
    # drop rule has to follow, or the policy silently half-applies.
    if "nullify_impossible_predictor_values" in operations:
        index = operations.index("nullify_impossible_predictor_values")
        if "drop_missing_any_predictor" not in operations[index + 1 :]:
            raise ConfigError(
                "nullify_impossible_predictor_values requires "
                "drop_missing_any_predictor after it (ADR-020)"
            )

    frame = dataset.frame
    audit = CleaningAudit()
    for name in operations:
        operation = OPERATION_REGISTRY[name]
        before = len(frame)
        frame, detail = operation.apply(frame, schema)
        record = CleaningOperationRecord(
            rule=operation.name,
            reason=operation.reason,
            rows_before=before,
            rows_after=len(frame),
            detail=detail,
        )
        audit.operations.append(record)
        if record.rows_removed:
            _logger.info("Cleaning %s removed %d rows", operation.name, record.rows_removed)

    cleaned = dataset.with_frame(frame.reset_index(drop=True), stage="cleaned")
    return cleaned, audit
