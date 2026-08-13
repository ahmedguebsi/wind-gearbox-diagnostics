"""Healthy-state construction (M-12; PROJECT.md §13).

Builds the population the NBM learns "normal" from, by exclusion. Exclusion
reasons are attributed disjointly: an observation excluded for several
reasons counts once, under the first reason in :data:`EXCLUSION_PRIORITY`,
so `accepted + excluded == total` holds exactly and reason counts sum to the
excluded total.

Guard 5: if a known-failure interval would enter the healthy population, a
WARNING finding is emitted rather than silent inclusion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pandas as pd

from app.core.config import HealthyStateConfig
from app.core.logging import get_logger
from app.data.ingestion import CanonicalDataset
from app.data.schema import ACTIVE_POWER, CanonicalSchema
from app.data.validation import Finding, Level, StepChange

_logger = get_logger("data.healthy_state")

#: Disjoint attribution order (PROJECT.md §13 requires a documented policy).
#: Earlier reasons win, so a row inside both a fault window and an alarm
#: window is attributed to the fault window only.
EXCLUSION_PRIORITY: tuple[str, ...] = (
    "known_fault_period",
    "pre_fault_window",
    "post_maintenance_window",
    "maintenance_period",
    "alarm_period",
    "shutdown_or_invalid_state",
    "sensor_failure_or_step_change",
    "curtailment",
    "below_minimum_active_power",
)


@dataclass(frozen=True)
class ExclusionWindow:
    """A period to exclude, with the reason it is excluded."""

    turbine: str
    start_utc: pd.Timestamp
    end_utc: pd.Timestamp
    reason: str


@dataclass(frozen=True)
class HealthyStateReport:
    total: int
    accepted: int
    excluded: int
    retention_pct: float
    exclusion_counts: dict[str, int]
    date_range_utc: tuple[pd.Timestamp | None, pd.Timestamp | None]
    turbines: list[str]
    findings: list[Finding]

    def accounting_holds(self) -> bool:
        return (
            self.accepted + self.excluded == self.total
            and sum(self.exclusion_counts.values()) == self.excluded
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "accepted": self.accepted,
            "excluded": self.excluded,
            "retention_pct": self.retention_pct,
            "exclusion_counts": self.exclusion_counts,
            "date_range_utc": [None if t is None else t.isoformat() for t in self.date_range_utc],
            "turbines": self.turbines,
            "findings": [f.as_dict() for f in self.findings],
            "accounting_holds": self.accounting_holds(),
        }


class HealthyStateBuilder:
    """Constructs the healthy population from exclusion windows and rules."""

    def __init__(self, config: HealthyStateConfig, schema: CanonicalSchema) -> None:
        self.config = config
        self.schema = schema

    def build(
        self,
        dataset: CanonicalDataset,
        *,
        fault_windows: list[ExclusionWindow] | None = None,
        alarm_windows: list[ExclusionWindow] | None = None,
        maintenance_windows: list[ExclusionWindow] | None = None,
        step_changes: list[StepChange] | None = None,
    ) -> tuple[CanonicalDataset, HealthyStateReport]:
        frame = dataset.frame
        timestamp = self.schema.timestamp_name
        turbine_column = self.schema.turbine_id_name
        total = len(frame)

        reasons = pd.Series("", index=frame.index, dtype="object")
        findings: list[Finding] = []

        def mark(mask: pd.Series, reason: str) -> None:
            unattributed = mask & (reasons == "")
            reasons.loc[unattributed] = reason

        windows: list[ExclusionWindow] = []
        for window in fault_windows or []:
            windows.append(window)
            if self.config.fault_pre_exclusion_days:
                windows.append(
                    ExclusionWindow(
                        window.turbine,
                        window.start_utc - timedelta(days=self.config.fault_pre_exclusion_days),
                        window.start_utc,
                        "pre_fault_window",
                    )
                )
        if self.config.exclude_alarm_periods:
            windows.extend(alarm_windows or [])
        for window in maintenance_windows or []:
            windows.append(window)
            if self.config.maintenance_post_exclusion_days:
                windows.append(
                    ExclusionWindow(
                        window.turbine,
                        window.end_utc,
                        window.end_utc
                        + timedelta(days=self.config.maintenance_post_exclusion_days),
                        "post_maintenance_window",
                    )
                )
        for step in step_changes or []:
            half = timedelta(days=self.config.step_change_exclusion_days)
            windows.append(
                ExclusionWindow(
                    step.turbine,
                    step.timestamp_utc - half,
                    step.timestamp_utc + half,
                    "sensor_failure_or_step_change",
                )
            )

        # Apply windows in priority order so attribution is deterministic.
        matched_rows: dict[int, int] = {}
        for reason in EXCLUSION_PRIORITY:
            for window in [w for w in windows if w.reason == reason]:
                mask = (frame[timestamp] >= window.start_utc) & (frame[timestamp] <= window.end_utc)
                if turbine_column in frame.columns and window.turbine:
                    mask &= frame[turbine_column].astype(str) == window.turbine
                matched_rows[id(window)] = int(mask.sum())
                mark(mask, reason)

        power_column = ACTIVE_POWER
        if power_column in frame.columns:
            below = frame[power_column] < self.config.minimum_active_power_kw
            mark(below.fillna(value=True), "below_minimum_active_power")

        excluded_mask = reasons != ""
        accepted_frame = frame[~excluded_mask]

        # Guard 5: a known failure interval must never remain in the healthy
        # set. The dangerous case is silent non-application — a window whose
        # turbine identifier matches no observation excludes nothing, and
        # without this warning the failure period would sit in training with
        # no indication that the exclusion did nothing.
        for window in [w for w in windows if w.reason == "known_fault_period"]:
            if matched_rows.get(id(window), 0) == 0:
                findings.append(
                    Finding(
                        Level.WARNING,
                        "GUARD5.WINDOW_MATCHED_NOTHING",
                        "Known failure window excluded no observations; check the turbine "
                        "identifier and window bounds — the exclusion had no effect",
                        0,
                        {
                            "turbine": window.turbine,
                            "start": window.start_utc.isoformat(),
                            "end": window.end_utc.isoformat(),
                        },
                    )
                )
            overlap = (accepted_frame[timestamp] >= window.start_utc) & (
                accepted_frame[timestamp] <= window.end_utc
            )
            if turbine_column in accepted_frame.columns and window.turbine:
                overlap &= accepted_frame[turbine_column].astype(str) == window.turbine
            if bool(overlap.any()):
                findings.append(
                    Finding(
                        Level.WARNING,
                        "GUARD5.FAILURE_IN_HEALTHY",
                        "Known failure interval overlaps the healthy population",
                        int(overlap.sum()),
                        {"turbine": window.turbine, "start": window.start_utc.isoformat()},
                    )
                )

        counts = {
            reason: int((reasons == reason).sum())
            for reason in EXCLUSION_PRIORITY
            if int((reasons == reason).sum()) > 0
        }
        stamps = accepted_frame[timestamp].dropna()
        report = HealthyStateReport(
            total=total,
            accepted=len(accepted_frame),
            excluded=int(excluded_mask.sum()),
            retention_pct=round(100.0 * len(accepted_frame) / total, 4) if total else 0.0,
            exclusion_counts=counts,
            date_range_utc=(stamps.min(), stamps.max()) if not stamps.empty else (None, None),
            turbines=(
                sorted({str(t) for t in accepted_frame[turbine_column].dropna().unique()})
                if turbine_column in accepted_frame.columns
                else []
            ),
            findings=findings,
        )
        _logger.info(
            "Healthy state: %d/%d retained (%.2f%%)",
            report.accepted,
            report.total,
            report.retention_pct,
        )
        healthy = dataset.with_frame(accepted_frame.reset_index(drop=True), stage="healthy")
        return healthy, report
