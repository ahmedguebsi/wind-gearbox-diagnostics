"""Orthogonal common/differential residual modes (ADR-035; protocol arm A6).

RQ2's coordination premise requires the monitored streams to carry different
information, and ADR-035 measured the two thermal residual channels at
r = 0.932-0.952: coordination over the raw channels compares nearly identical
streams. The rotation manufactures the independence the premise requires —
exactly on the partition whose statistics standardized the channels, and
approximately elsewhere. On per-channel standardized residuals, with the two
targets taken in sorted order (first, second):

    common       = (first + second) / sqrt(2)
    differential = (first - second) / sqrt(2)

Under the ADR-012 designation ``first`` is ``gearbox_bearing_temperature`` and
``second`` is ``gearbox_oil_temperature``, so a HIGH differential mode means
the bearing is hot RELATIVE TO ITS OWN OIL BATH — the bearing-specific
signature RQ2 was reaching for (ADR-035).

Binding conditions this module enforces or documents (ADR-035):

- (d) the rotation applies to the NORMALIZED residual column only; a frame
  whose normalized column is unfilled is refused. Rotating unnormalized
  channels mixes two different scales and the orthogonality does not hold.
- (a) the standardization statistics must come from TRAINING healthy data
  only. Statistic provenance is the caller's obligation (Guard 4 enforces it
  at every normalizer ``fit``); this module never fits statistics itself.

The mode values are emitted as the RAW residual of two pseudo-targets so the
frame flows through the IDENTICAL normalizer -> EWMA -> matched-FPR machinery
the NBM residual uses — the arms then differ only in the monitored quantity,
which is the question A6 asks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.core.errors import ConfigError
from app.residuals.engine import (
    ACTUAL_COLUMN,
    NORMALIZED_RESIDUAL_COLUMN,
    PREDICTION_COLUMN,
    RAW_RESIDUAL_COLUMN,
    TARGET_COLUMN,
    TIMESTAMP_COLUMN,
    TURBINE_COLUMN,
    ResidualFrame,
)

#: Pseudo-target names carried by the rotated frame.
MODE_COMMON = "mode_common"
MODE_DIFFERENTIAL = "mode_differential"

_SQRT2 = math.sqrt(2.0)


@dataclass(frozen=True)
class ModeRotationReport:
    """Alignment census + measured mode statistics of one rotation.

    The statistics exist so every rotation records the identities ADR-035
    predicts — ``sd(common) = sqrt(1+r)`` and ``sd(differential) = sqrt(1-r)``
    hold exactly only where the channels have exactly unit variance, i.e. on
    the partition that supplied the standardization statistics.
    """

    first_target: str
    second_target: str
    n_input_rows: int
    #: (turbine, timestamp) points carrying BOTH channels — the same
    #: inner-alignment rule CoordinatedPipeline applies: coordination is
    #: undefined where any channel is missing.
    n_aligned_points: int
    n_dropped_points: int
    channel_pearson: float
    mode_pearson: float
    sd_common: float
    sd_differential: float
    variance_share_common: float
    variance_share_differential: float
    lag1_common: float | None
    lag1_differential: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "first_target": self.first_target,
            "second_target": self.second_target,
            "n_input_rows": self.n_input_rows,
            "n_aligned_points": self.n_aligned_points,
            "n_dropped_points": self.n_dropped_points,
            "channel_pearson": self.channel_pearson,
            "mode_pearson": self.mode_pearson,
            "sd_common": self.sd_common,
            "sd_differential": self.sd_differential,
            "variance_share_common": self.variance_share_common,
            "variance_share_differential": self.variance_share_differential,
            "lag1_common": self.lag1_common,
            "lag1_differential": self.lag1_differential,
        }


def _pooled_lag1(values: pd.Series) -> float | None:
    """Point-count-weighted naive lag-1 autocorrelation across turbines.

    Naive by construction — consecutive rows are paired regardless of gaps —
    matching how ADR-035's recorded ``lag-1 phi`` figures were measured.
    Turbines with fewer than 3 points or zero spread contribute nothing;
    None when no turbine can contribute.
    """
    weighted: list[tuple[float, int]] = []
    for _, series in values.groupby(level=0):
        v = series.to_numpy(dtype=float)
        if len(v) < 3 or float(np.std(v[:-1])) == 0.0 or float(np.std(v[1:])) == 0.0:
            continue
        weighted.append((float(np.corrcoef(v[:-1], v[1:])[0, 1]), len(v)))
    if not weighted:
        return None
    total = sum(n for _, n in weighted)
    return float(sum(phi * n for phi, n in weighted) / total)


def rotate_to_modes(residuals: ResidualFrame) -> tuple[ResidualFrame, ModeRotationReport]:
    """Rotate a two-channel normalized ResidualFrame into orthogonal modes.

    Requires exactly two targets. Points are inner-aligned on
    (turbine, timestamp); a point where either channel is missing or
    unnormalized is dropped and counted, never silently filled.
    """
    targets = residuals.targets
    if len(targets) != 2:
        raise ConfigError(
            "The ADR-035 rotation is defined for exactly two channels",
            targets=list(targets),
        )
    frame = residuals.data
    if frame[NORMALIZED_RESIDUAL_COLUMN].isna().all():
        raise ConfigError(
            "Residuals are not normalized; the ADR-035 rotation applies AFTER "
            "normalization (binding condition d)"
        )
    try:
        wide = frame.pivot(
            index=[TURBINE_COLUMN, TIMESTAMP_COLUMN],
            columns=TARGET_COLUMN,
            values=NORMALIZED_RESIDUAL_COLUMN,
        )
    except ValueError as error:
        raise ConfigError(
            "Duplicate (turbine, timestamp, target) rows; rotation refuses to aggregate"
        ) from error
    wide = wide.sort_index()
    aligned = wide.dropna()
    if len(aligned) < 2:
        raise ConfigError("Too few aligned two-channel points to rotate", aligned=len(aligned))

    first, second = targets
    common = (aligned[first] + aligned[second]) / _SQRT2
    differential = (aligned[first] - aligned[second]) / _SQRT2

    variance_common = float(np.var(common.to_numpy(dtype=float), ddof=1))
    variance_differential = float(np.var(differential.to_numpy(dtype=float), ddof=1))
    variance_total = variance_common + variance_differential
    report = ModeRotationReport(
        first_target=first,
        second_target=second,
        n_input_rows=len(frame),
        n_aligned_points=len(aligned),
        n_dropped_points=len(wide) - len(aligned),
        channel_pearson=float(aligned[first].corr(aligned[second])),
        mode_pearson=float(common.corr(differential)),
        sd_common=math.sqrt(variance_common),
        sd_differential=math.sqrt(variance_differential),
        variance_share_common=variance_common / variance_total,
        variance_share_differential=variance_differential / variance_total,
        lag1_common=_pooled_lag1(common),
        lag1_differential=_pooled_lag1(differential),
    )

    parts: list[pd.DataFrame] = []
    for mode_name, values in ((MODE_COMMON, common), (MODE_DIFFERENTIAL, differential)):
        index = values.index.to_frame(index=False)
        parts.append(
            pd.DataFrame(
                {
                    TIMESTAMP_COLUMN: index[TIMESTAMP_COLUMN],
                    TURBINE_COLUMN: index[TURBINE_COLUMN],
                    TARGET_COLUMN: mode_name,
                    ACTUAL_COLUMN: values.to_numpy(dtype=float),
                    PREDICTION_COLUMN: 0.0,
                    RAW_RESIDUAL_COLUMN: values.to_numpy(dtype=float),
                    NORMALIZED_RESIDUAL_COLUMN: np.nan,
                }
            )
        )
    combined = pd.concat(parts, ignore_index=True)
    combined = combined.sort_values([TURBINE_COLUMN, TARGET_COLUMN, TIMESTAMP_COLUMN]).reset_index(
        drop=True
    )
    return ResidualFrame(combined), report
