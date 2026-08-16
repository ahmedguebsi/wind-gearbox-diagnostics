"""Fleet-relative residuals (ADR-029 PROPOSED; docs/METHODOLOGY_REVIEW.md §5).

A turbine's thermal residual carries two components: behaviour idiosyncratic
to that machine, and behaviour common to the whole farm — weather, icing,
grid events, seasonal drift. Only the first is evidence about that machine's
gearbox. Subtracting the fleet median at each timestamp removes the common
component and leaves the idiosyncratic one (Chesterman et al., Wind Energy
Science 8(6):893, 2023, who apply the same idea to raw signals before
modelling rather than to residuals after it).

This bears directly on LIM-023: the single EVENT-001 detection coincided
with an excursion visible on ALL SIX turbines and BOTH thermal targets, and
was concluded to be a fleet-wide environmental response rather than a fault
signature. A fleet-relative residual is the quantity that would have been
insensitive to it.

LEAVE-ONE-OUT IS NOT OPTIONAL. If a turbine contributes to the median it is
compared against, its own excursion pulls the reference toward itself and
the adjusted residual is attenuated — most severely in the six-turbine case,
where one machine is a sixth of the reference. Every median here excludes
the turbine it is applied to.

WHAT THIS COSTS, STATED PLAINLY. Fleet-relative residuals use
CONTEMPORANEOUS cross-turbine information. That is legitimate for a fault
affecting one machine, and it is INVALID for a fault mode that affects the
whole farm at once — such a fault would be subtracted away along with the
weather. The distinction must be stated wherever this arm is reported; it is
a change in what is being detected, not a free improvement.

ADR-029 registers this as an ABLATION ARM, not a replacement for the
headline pipeline, with the expected direction of effect recorded before
execution: fewer false alarms, and a reduced or eliminated apparent lead on
EVENT-001. Adopting it as the headline after observing that the case study
failed would be post-hoc pipeline selection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.core.errors import ConfigError
from app.residuals.engine import (
    RAW_RESIDUAL_COLUMN,
    TARGET_COLUMN,
    TIMESTAMP_COLUMN,
    TURBINE_COLUMN,
    ResidualFrame,
)

#: A leave-one-out median needs at least this many peer turbines to be a
#: median rather than a single peer's value.
DEFAULT_MIN_PEERS = 2


@dataclass(frozen=True)
class FleetAdjustmentReport:
    """What the adjustment did, per target. Auditable like every other
    row-removing operation in the pipeline."""

    min_peers: int
    rows_before: int
    rows_after: int
    rows_dropped_insufficient_peers: int
    per_target_median_abs_adjustment: dict[str, float]

    @property
    def retention_pct(self) -> float:
        return round(100.0 * self.rows_after / self.rows_before, 4) if self.rows_before else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "min_peers": self.min_peers,
            "rows_before": self.rows_before,
            "rows_after": self.rows_after,
            "rows_dropped_insufficient_peers": self.rows_dropped_insufficient_peers,
            "retention_pct": self.retention_pct,
            "per_target_median_abs_adjustment": dict(self.per_target_median_abs_adjustment),
            "note": (
                "Leave-one-out fleet median subtracted per (timestamp, target). "
                "Uses contemporaneous cross-turbine information: valid for "
                "single-machine faults, invalid for farm-wide fault modes."
            ),
        }


def _leave_one_out_median(values: np.ndarray, min_peers: int) -> np.ndarray:
    """Row-wise leave-one-out median of a (n_timestamps, n_turbines) array.

    Entry [t, j] is the median of row t EXCLUDING column j, or NaN where
    fewer than ``min_peers`` peers are observed at that timestamp.
    """
    n_rows, n_cols = values.shape
    out = np.full((n_rows, n_cols), np.nan, dtype=float)
    for j in range(n_cols):
        peers = np.delete(values, j, axis=1)
        observed = np.count_nonzero(~np.isnan(peers), axis=1)
        qualifies = observed >= min_peers
        # Only rows that qualify are passed to nanmedian: an all-NaN slice
        # would warn, and the answer for those rows is NaN by definition.
        if bool(qualifies.any()):
            out[qualifies, j] = np.nanmedian(peers[qualifies], axis=1)
    return out


def fleet_relative_residuals(
    residuals: ResidualFrame, *, min_peers: int = DEFAULT_MIN_PEERS
) -> tuple[ResidualFrame, FleetAdjustmentReport]:
    """Subtract the leave-one-out fleet median from every raw residual.

    Returns a NEW ResidualFrame — the raw residuals of the input are never
    mutated (they are write-once by contract). The returned frame carries a
    different derived quantity and must be labelled as such wherever it is
    reported.

    Rows whose timestamp offers fewer than ``min_peers`` peer turbines are
    dropped and counted, rather than being adjusted against a degenerate
    reference.
    """
    if min_peers < 1:
        raise ConfigError("min_peers must be at least 1", min_peers=min_peers)
    frame = residuals.data
    turbines = sorted({str(t) for t in frame[TURBINE_COLUMN].unique()})
    if len(turbines) < min_peers + 1:
        raise ConfigError(
            "Too few turbines for a leave-one-out fleet median",
            n_turbines=len(turbines),
            min_peers=min_peers,
        )

    rows_before = len(frame)
    adjustments: dict[str, float] = {}
    parts: list[pd.DataFrame] = []

    for target in residuals.targets:
        block = frame[frame[TARGET_COLUMN] == target]
        wide = block.pivot(
            index=TIMESTAMP_COLUMN, columns=TURBINE_COLUMN, values=RAW_RESIDUAL_COLUMN
        )
        reference = _leave_one_out_median(wide.to_numpy(dtype=float), min_peers)
        reference_frame = pd.DataFrame(reference, index=wide.index, columns=wide.columns)
        long_reference = reference_frame.reset_index().melt(
            id_vars=TIMESTAMP_COLUMN,
            var_name=TURBINE_COLUMN,
            value_name="__fleet__",
        )
        merged = block.merge(long_reference, on=[TIMESTAMP_COLUMN, TURBINE_COLUMN], how="left")
        merged = merged[merged["__fleet__"].notna()]
        adjustments[str(target)] = round(float(merged["__fleet__"].abs().median()), 6)
        merged[RAW_RESIDUAL_COLUMN] = merged[RAW_RESIDUAL_COLUMN] - merged["__fleet__"]
        parts.append(merged.drop(columns=["__fleet__"]))

    adjusted = pd.concat(parts, ignore_index=True)
    adjusted = adjusted.sort_values([TURBINE_COLUMN, TARGET_COLUMN, TIMESTAMP_COLUMN]).reset_index(
        drop=True
    )

    report = FleetAdjustmentReport(
        min_peers=min_peers,
        rows_before=rows_before,
        rows_after=len(adjusted),
        rows_dropped_insufficient_peers=rows_before - len(adjusted),
        per_target_median_abs_adjustment=adjustments,
    )
    return ResidualFrame(adjusted), report
