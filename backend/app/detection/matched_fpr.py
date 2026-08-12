"""Matched false-alarm-rate comparison framework (M-23; PROJECT.md §25).

Comparing raw alarm counts at arbitrary thresholds is confounded by
threshold choice, so single-signal and coordinated pipelines are compared
AT MATCHED FALSE-ALARM OPERATING POINTS (equal false alarms per
turbine-year), and the FULL operating curves are always reported alongside
any matched-point table — never just one point (M-23 acceptance 2).

Fairness is structural, not aspirational: the framework applied to two
identical pipelines reports no difference (symmetry sanity check,
PROJECT.md §25; tested).

Event-level columns (detected/missed events, lead times) deliberately do
NOT live here: event-matching windows are decision-queue item D-06 (OPEN),
so they attach in M-27 once the author closes it — no default window is
baked in silently. Under ADR-014 these healthy-data operating curves are
fully quantitative and are the primary RQ2 evidence; EVENT-001 remains a
descriptive case study.

False-alarm counting: an alarm EVENT is a rising edge of the alarm flag
series (entry into alarm state) measured on healthy (non-event) periods —
the caller supplies EWMA streams built from healthy data. Rates are per
turbine-year of observed span.

Non-monotonicity caveat (measured, not assumed): the alarm-POINT fraction
is structurally non-increasing in the multiplier (a stricter limit alarms a
subset of points), but the alarm-EVENT rate need not be — at very loose
limits adjacent alarms merge into long runs, so counting entries can fall
as limits loosen further. ``matched_multiplier`` therefore never assumes a
monotone curve: it scans from the STRICTEST end and returns the strictest
multiplier achieving the target rate (the conservative operating point),
and unreachable targets are reported as unreachable, never clamped.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
import pandas as pd

from app.core.errors import ConfigError
from app.detection.single import states_at_multiplier
from app.residuals.ewma import EwmaSeries

DAYS_PER_YEAR = 365.25


class DetectionPipeline(Protocol):
    """A sweepable detection pipeline (ARCHITECTURE.md §5.4)."""

    @property
    def name(self) -> str: ...

    def alarm_flags(self, multiplier: float) -> dict[str, pd.Series]:
        """Per-turbine boolean alarm series indexed by UTC timestamp."""
        ...


class SingleSignalPipeline:
    """Baseline pipeline: one signal's EWMA stream monitored independently."""

    def __init__(self, name: str, series: Sequence[EwmaSeries], target: str) -> None:
        self._name = name
        self.target = target
        self._series = [s for s in series if s.target == target]
        if not self._series:
            raise ConfigError("No EWMA stream for the requested target", target=target)
        turbines = [s.turbine for s in self._series]
        if len(set(turbines)) != len(turbines):
            raise ConfigError("Multiple EWMA streams for one turbine/target", target=target)

    @property
    def name(self) -> str:
        return self._name

    def alarm_flags(self, multiplier: float) -> dict[str, pd.Series]:
        flags: dict[str, pd.Series] = {}
        for series in self._series:
            detection = states_at_multiplier(series, multiplier)
            flags[series.turbine] = pd.Series(
                (detection.states != 0).to_numpy(),
                index=pd.Index(detection.timestamps, name="timestamp"),
            )
        return flags


class CoordinatedPipeline:
    """Proposed pipeline: alarm when >= min_coordinated targets exceed in the
    SAME direction at the same timestamp.

    ``min_coordinated=None`` requires every target present in the stream set
    (the [HIGH, HIGH] coordination of PROJECT.md §24). Timestamps are
    inner-aligned across targets: coordination is undefined where any target
    is missing, and an undefined point never alarms.
    """

    def __init__(
        self, name: str, series: Sequence[EwmaSeries], min_coordinated: int | None = None
    ) -> None:
        self._name = name
        self._by_turbine: dict[str, list[EwmaSeries]] = {}
        for stream in series:
            self._by_turbine.setdefault(stream.turbine, []).append(stream)
        if not self._by_turbine:
            raise ConfigError("Coordinated pipeline requires at least one EWMA stream")
        n_targets = {len(streams) for streams in self._by_turbine.values()}
        if len(n_targets) != 1:
            raise ConfigError("Turbines carry different target sets", sets=sorted(n_targets))
        self.n_targets = n_targets.pop()
        self.min_coordinated = self.n_targets if min_coordinated is None else min_coordinated
        if not 1 <= self.min_coordinated <= self.n_targets:
            raise ConfigError(
                "min_coordinated out of range",
                min_coordinated=self.min_coordinated,
                n_targets=self.n_targets,
            )

    @property
    def name(self) -> str:
        return self._name

    def alarm_flags(self, multiplier: float) -> dict[str, pd.Series]:
        flags: dict[str, pd.Series] = {}
        for turbine, streams in self._by_turbine.items():
            state_frames = []
            for stream in streams:
                detection = states_at_multiplier(stream, multiplier)
                state_frames.append(
                    pd.DataFrame(
                        {stream.target: detection.states.to_numpy()},
                        index=pd.Index(detection.timestamps, name="timestamp"),
                    )
                )
            joined = pd.concat(state_frames, axis=1, join="inner").sort_index()
            high = (joined == 1).sum(axis=1) >= self.min_coordinated
            low = (joined == -1).sum(axis=1) >= self.min_coordinated
            flags[turbine] = high | low
        return flags


@dataclass(frozen=True)
class OperatingPoint:
    multiplier: float
    false_alarms_per_turbine_year: float
    alarm_fraction: float
    n_alarm_events: int
    n_points: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "multiplier": self.multiplier,
            "false_alarms_per_turbine_year": self.false_alarms_per_turbine_year,
            "alarm_fraction": self.alarm_fraction,
            "n_alarm_events": self.n_alarm_events,
            "n_points": self.n_points,
        }


@dataclass(frozen=True)
class OperatingCurve:
    """The FULL sweep for one pipeline — always reported (PROJECT.md §25)."""

    pipeline: str
    points: tuple[OperatingPoint, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"pipeline": self.pipeline, "points": [p.as_dict() for p in self.points]}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> OperatingCurve:
        return cls(
            pipeline=payload["pipeline"],
            points=tuple(OperatingPoint(**point) for point in payload["points"]),
        )


def _rising_edges(flags: pd.Series) -> int:
    values = flags.to_numpy(dtype=bool)
    if len(values) == 0:
        return 0
    previous = np.concatenate([[False], values[:-1]])
    return int((values & ~previous).sum())


def _turbine_years(flag_map: dict[str, pd.Series]) -> float:
    total = pd.Timedelta(0)
    for flags in flag_map.values():
        stamps = pd.Series(flags.index)
        if len(stamps) < 2:
            raise ConfigError("Cannot measure observation span from fewer than 2 points")
        interval = stamps.diff().dropna().median()
        total += (stamps.iloc[-1] - stamps.iloc[0]) + interval
    return float(total / pd.Timedelta(days=DAYS_PER_YEAR))


def sweep(pipeline: DetectionPipeline, grid: Sequence[float]) -> OperatingCurve:
    """Sweep the control-limit multiplier and measure false-alarm behaviour."""
    if not grid:
        raise ConfigError("Threshold grid is empty")
    points: list[OperatingPoint] = []
    for multiplier in sorted(grid):
        flag_map = pipeline.alarm_flags(multiplier)
        n_events = sum(_rising_edges(flags) for flags in flag_map.values())
        n_points = sum(len(flags) for flags in flag_map.values())
        n_alarmed = sum(int(flags.sum()) for flags in flag_map.values())
        years = _turbine_years(flag_map)
        points.append(
            OperatingPoint(
                multiplier=float(multiplier),
                false_alarms_per_turbine_year=n_events / years,
                alarm_fraction=n_alarmed / n_points if n_points else 0.0,
                n_alarm_events=n_events,
                n_points=n_points,
            )
        )
    return OperatingCurve(pipeline=pipeline.name, points=tuple(points))


def matched_multiplier(curve: OperatingCurve, fpr_target: float) -> float | None:
    """Multiplier at which the curve reaches the target false-alarm rate.

    Linear interpolation between grid points, scanning from the STRICTEST
    end of the grid, so where run-merging makes the event-rate curve
    non-monotone the strictest multiplier achieving the target wins (the
    conservative operating point). None when the target rate is unreachable
    on the swept grid (reported, never silently clamped).
    """
    if fpr_target < 0:
        raise ConfigError("FPR target must be non-negative", fpr_target=fpr_target)
    pairs = [(p.multiplier, p.false_alarms_per_turbine_year) for p in curve.points]
    if not pairs:
        return None
    for i in range(len(pairs) - 1, 0, -1):
        m_low, r_low = pairs[i - 1]
        m_high, r_high = pairs[i]
        if min(r_low, r_high) <= fpr_target <= max(r_low, r_high):
            if r_low == r_high:
                return m_high  # strictest end of a flat segment
            fraction = (r_low - fpr_target) / (r_low - r_high)
            return m_low + fraction * (m_high - m_low)
    if len(pairs) == 1 and pairs[0][1] == fpr_target:
        return pairs[0][0]
    return None


@dataclass(frozen=True)
class MatchedPoint:
    pipeline: str
    fpr_target: float
    multiplier: float | None
    reachable: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "pipeline": self.pipeline,
            "fpr_target": self.fpr_target,
            "multiplier": self.multiplier,
            "reachable": self.reachable,
        }


@dataclass(frozen=True)
class ComparisonReport:
    """Matched operating points PLUS the full curves, always together."""

    fpr_targets: tuple[float, ...]
    matched: tuple[MatchedPoint, ...]
    curves: dict[str, OperatingCurve]

    def as_dict(self) -> dict[str, Any]:
        return {
            "fpr_targets": list(self.fpr_targets),
            "matched": [m.as_dict() for m in self.matched],
            "curves": {name: curve.as_dict() for name, curve in self.curves.items()},
        }


def compare_at(curves: dict[str, OperatingCurve], fpr_targets: Sequence[float]) -> ComparisonReport:
    """Compare pipelines at matched false-alarm operating points.

    Event-level outcome columns attach in M-27 once D-06 closes; this report
    fixes each pipeline's operating point per target rate and always embeds
    the full curves.
    """
    if not fpr_targets:
        raise ConfigError("No FPR targets supplied")
    matched: list[MatchedPoint] = []
    for fpr_target in fpr_targets:
        for name, curve in sorted(curves.items()):
            multiplier = matched_multiplier(curve, fpr_target)
            matched.append(
                MatchedPoint(
                    pipeline=name,
                    fpr_target=float(fpr_target),
                    multiplier=multiplier,
                    reachable=multiplier is not None,
                )
            )
    return ComparisonReport(
        fpr_targets=tuple(float(t) for t in fpr_targets),
        matched=tuple(matched),
        curves=dict(curves),
    )
