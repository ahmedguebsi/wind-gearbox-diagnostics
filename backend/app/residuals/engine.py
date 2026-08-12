"""Residual generation (M-19a; PROJECT.md §21).

``residual = actual - expected_healthy_value`` per thermal target. The
:class:`ResidualFrame` preserves raw residuals permanently: raw values are
write-once — the stored frame is never handed out by reference, and
normalization produces a NEW frame whose raw column is verified unchanged
against the original's hash (M-19a acceptance 1).
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.core.errors import ConfigError
from app.data.schema import CanonicalSchema

#: Long-format ResidualFrame columns (one row per timestamp/turbine/target).
TIMESTAMP_COLUMN = "timestamp"
TURBINE_COLUMN = "turbine_id"
TARGET_COLUMN = "target"
ACTUAL_COLUMN = "actual"
PREDICTION_COLUMN = "prediction"
RAW_RESIDUAL_COLUMN = "raw_residual"
NORMALIZED_RESIDUAL_COLUMN = "normalized_residual"

REQUIRED_COLUMNS: tuple[str, ...] = (
    TIMESTAMP_COLUMN,
    TURBINE_COLUMN,
    TARGET_COLUMN,
    ACTUAL_COLUMN,
    PREDICTION_COLUMN,
    RAW_RESIDUAL_COLUMN,
    NORMALIZED_RESIDUAL_COLUMN,
)


def _raw_hash(frame: pd.DataFrame) -> str:
    hashed = pd.util.hash_pandas_object(frame[RAW_RESIDUAL_COLUMN], index=True).to_numpy()
    return hashlib.sha256(hashed.tobytes()).hexdigest()


@dataclass(frozen=True)
class ResidualFrame:
    """Long-format residual store; raw residuals are write-once.

    ``data`` returns a defensive copy, so external mutation cannot reach the
    stored frame; :meth:`with_normalized` is the only way to fill the
    normalized column and re-verifies the raw column hash before returning a
    new instance.
    """

    _frame: pd.DataFrame
    _raw_digest: str = field(default="")

    def __post_init__(self) -> None:
        missing = [c for c in REQUIRED_COLUMNS if c not in self._frame.columns]
        if missing:
            raise ConfigError("ResidualFrame is missing required columns", missing=missing)
        if not self._raw_digest:
            object.__setattr__(self, "_raw_digest", _raw_hash(self._frame))

    @property
    def data(self) -> pd.DataFrame:
        """A copy of the residual rows (mutating it cannot affect the store)."""
        return self._frame.copy()

    @property
    def targets(self) -> tuple[str, ...]:
        return tuple(sorted(self._frame[TARGET_COLUMN].unique()))

    def __len__(self) -> int:
        return len(self._frame)

    def with_normalized(self, normalized: pd.Series) -> ResidualFrame:
        """A new ResidualFrame with the normalized column filled.

        Raw residuals are verified bit-unchanged; a mismatch means something
        attempted to rewrite history and is a hard stop.
        """
        if len(normalized) != len(self._frame):
            raise ConfigError(
                "Normalized series length mismatch",
                expected=len(self._frame),
                received=len(normalized),
            )
        if _raw_hash(self._frame) != self._raw_digest:
            raise ConfigError("Raw residuals were mutated; raw residuals are write-once")
        frame = self._frame.copy()
        frame[NORMALIZED_RESIDUAL_COLUMN] = np.asarray(normalized, dtype=float)
        return ResidualFrame(frame, self._raw_digest)


def compute_residuals(
    frame: pd.DataFrame,
    predictions: pd.DataFrame,
    schema: CanonicalSchema,
    targets: Sequence[str],
) -> ResidualFrame:
    """Assemble the long-format ResidualFrame from actuals and predictions.

    ``frame`` supplies timestamps, turbine IDs, and actual target values;
    ``predictions`` is the wide model output aligned on the same index
    (one column per target).
    """
    missing_targets = [t for t in targets if t not in predictions.columns]
    if missing_targets:
        raise ConfigError("Predictions lack target columns", missing=missing_targets)
    if not frame.index.equals(predictions.index):
        raise ConfigError("Actuals and predictions are not aligned on the same index")

    parts: list[pd.DataFrame] = []
    for target in targets:
        actual = frame[target].astype(float)
        predicted = predictions[target].astype(float)
        parts.append(
            pd.DataFrame(
                {
                    TIMESTAMP_COLUMN: frame[schema.timestamp_name],
                    TURBINE_COLUMN: frame[schema.turbine_id_name],
                    TARGET_COLUMN: target,
                    ACTUAL_COLUMN: actual,
                    PREDICTION_COLUMN: predicted,
                    RAW_RESIDUAL_COLUMN: actual - predicted,
                    NORMALIZED_RESIDUAL_COLUMN: np.nan,
                }
            )
        )
    combined = pd.concat(parts, ignore_index=True)
    combined = combined.sort_values([TURBINE_COLUMN, TARGET_COLUMN, TIMESTAMP_COLUMN]).reset_index(
        drop=True
    )
    return ResidualFrame(combined)
