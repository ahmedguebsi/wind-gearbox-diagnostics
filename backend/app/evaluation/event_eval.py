"""Event-based evaluation (M-27; PROJECT.md §27.2; ADR-014/016/017).

Matching follows ADR-017: a detection matches an event when its FIRST
PERSISTENT exceedance falls within [event_start - window, event_start];
isolated single-sample crossings never count. Detections live on the
10-minute SCADA grid while event timestamps are second-resolution, so lead
times are quantised to 10 minutes and reported as such (ADR-017c).

Small-n policy (PROJECT.md §7.5, §27.2; ADR-014): below the pre-committed
two-event threshold, ``inferential_allowed`` is False and the detection-rate
accessor RAISES — no code path emits detection-rate confidence intervals or
significance claims (M-27 acceptance 1). Event metrics are then descriptive:
per-event matched/missed facts and the ADR-016 secondary criterion's two
timestamps and their difference.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.core.errors import ConfigError
from app.evaluation.events import AlarmLevelEvent
from app.residuals.ewma import DetectionSeries

#: ADR-017(c): the SCADA grid detections resolve to.
GRID_MINUTES = 10


@dataclass(frozen=True)
class PersistentDetection:
    """The first sample of a sustained exceedance run (ADR-017b)."""

    turbine: str
    first_timestamp_utc: pd.Timestamp
    run_length: int
    direction: int


def persistent_detections(
    detections: list[DetectionSeries], *, min_samples: int
) -> list[PersistentDetection]:
    """Sustained same-direction runs of length >= min_samples, per stream.

    A qualifying detection is timestamped at the FIRST sample of its run.
    """
    if min_samples < 2:
        raise ConfigError(
            "Persistence requires min_samples >= 2; isolated single-sample "
            "crossings never count as detections (ADR-017b)",
            min_samples=min_samples,
        )
    found: list[PersistentDetection] = []
    for stream in detections:
        states = stream.states.to_numpy()
        timestamps = stream.timestamps.reset_index(drop=True)
        run_start = 0
        run_value = 0
        for i in range(len(states) + 1):
            value = states[i] if i < len(states) else 0
            if value == run_value:
                continue
            if run_value != 0 and i - run_start >= min_samples:
                found.append(
                    PersistentDetection(
                        turbine=stream.turbine,
                        first_timestamp_utc=pd.Timestamp(timestamps.iloc[run_start]),
                        run_length=i - run_start,
                        direction=int(run_value),
                    )
                )
            run_start = i
            run_value = int(value)
    return sorted(found, key=lambda d: (d.turbine, d.first_timestamp_utc))


def quantised_lead_minutes(event_start: pd.Timestamp, detection_time: pd.Timestamp) -> float:
    """Lead time (positive = early detection), floored to the 10-min grid."""
    raw_minutes = (event_start - detection_time) / pd.Timedelta(minutes=1)
    return float(math.floor(raw_minutes / GRID_MINUTES) * GRID_MINUTES)


@dataclass(frozen=True)
class EventMatch:
    """One event's matching outcome — the ADR-016 secondary criterion's two
    timestamps and their difference, as facts."""

    event_code: str | None
    turbine: str
    event_start_utc: pd.Timestamp
    detection_time_utc: pd.Timestamp | None
    matched: bool
    lead_time_minutes: float | None
    window_days: int
    grid_minutes: int = GRID_MINUTES

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_code": self.event_code,
            "turbine": self.turbine,
            "event_start_utc": self.event_start_utc.isoformat(),
            "detection_time_utc": (
                None if self.detection_time_utc is None else self.detection_time_utc.isoformat()
            ),
            "matched": self.matched,
            "lead_time_minutes": self.lead_time_minutes,
            "window_days": self.window_days,
            "lead_time_quantisation_minutes": self.grid_minutes,
        }


def match_event(
    event: AlarmLevelEvent,
    detections: list[PersistentDetection],
    *,
    window_days: int,
) -> EventMatch:
    """ADR-017(a): first persistent exceedance within the pre-event window."""
    window_start = event.start_utc - pd.Timedelta(days=window_days)
    in_window = [
        d
        for d in detections
        if d.turbine == event.turbine and window_start <= d.first_timestamp_utc <= event.start_utc
    ]
    if not in_window:
        return EventMatch(
            event_code=event.code,
            turbine=event.turbine,
            event_start_utc=event.start_utc,
            detection_time_utc=None,
            matched=False,
            lead_time_minutes=None,
            window_days=window_days,
        )
    first = min(d.first_timestamp_utc for d in in_window)
    return EventMatch(
        event_code=event.code,
        turbine=event.turbine,
        event_start_utc=event.start_utc,
        detection_time_utc=first,
        matched=True,
        lead_time_minutes=quantised_lead_minutes(event.start_utc, first),
        window_days=window_days,
    )


@dataclass(frozen=True)
class EvaluationResult:
    """Event-level outcomes with the structural small-n gate (M-27).

    There is deliberately NO stored detection-rate field: the accessor
    computes it and RAISES below the pre-committed threshold, so inferential
    claims are unreachable in descriptive mode (ADR-014).
    """

    matches: tuple[EventMatch, ...]
    false_alarm_episodes: int
    inferential_allowed: bool

    @property
    def n_events(self) -> int:
        return len(self.matches)

    @property
    def detected(self) -> int:
        return sum(1 for m in self.matches if m.matched)

    @property
    def missed(self) -> int:
        return self.n_events - self.detected

    def detection_rate(self) -> float:
        if not self.inferential_allowed:
            raise ConfigError(
                "Detection-rate claims are gated off: fewer events than the "
                "pre-committed Phase 0.5 threshold — the evaluation is "
                "DESCRIPTIVE (ADR-014; PROJECT.md §7.5)",
                n_events=self.n_events,
            )
        return self.detected / self.n_events

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "events": [m.as_dict() for m in self.matches],
            "detected": self.detected,
            "missed": self.missed,
            "false_alarm_episodes": self.false_alarm_episodes,
            "inferential_allowed": self.inferential_allowed,
        }
        if self.inferential_allowed:
            payload["detection_rate"] = self.detection_rate()
        return payload


def evaluate_events(
    events: list[AlarmLevelEvent],
    detections: list[DetectionSeries],
    *,
    window_days: int,
    min_samples: int,
    min_events_for_inferential: int = 2,
) -> EvaluationResult:
    """Event-level evaluation under the ADR-017 matching rule.

    False-alarm episodes are persistent detections whose first timestamp
    falls outside every event's [window_start, event_end] envelope (an
    endless event's envelope closes at its start).
    """
    if not events:
        raise ConfigError("No events supplied; event evaluation is undefined")
    persistent = persistent_detections(detections, min_samples=min_samples)
    matches = tuple(match_event(e, persistent, window_days=window_days) for e in events)

    envelopes = [
        (
            e.turbine,
            e.start_utc - pd.Timedelta(days=window_days),
            e.end_utc if e.end_utc is not None else e.start_utc,
        )
        for e in events
    ]
    false_alarms = sum(
        1
        for d in persistent
        if not any(
            d.turbine == turbine and start <= d.first_timestamp_utc <= end
            for turbine, start, end in envelopes
        )
    )
    return EvaluationResult(
        matches=matches,
        false_alarm_episodes=false_alarms,
        inferential_allowed=len(events) >= min_events_for_inferential,
    )
