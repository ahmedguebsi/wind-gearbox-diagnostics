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
from dataclasses import dataclass, field
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
    timestamps and their difference, as facts.

    ``direction`` and ``window_direction_census`` exist because the matching
    rule is DIRECTION-AGNOSTIC (ADR-017 fixed it that way and it is not
    revised here), while thermal fault mechanisms are not. On EVENT-001 —
    code 1860, a choked gear-oil filter, whose physical signature is a
    temperature RISE — 72 of the 82 persistent detections inside the match
    window were abnormally LOW, including the matched one. Reporting the
    lead time without the direction states a detection the physics does not
    support. The verdict is unchanged; what changes is that the reader can
    see what was matched (ADR-037).
    """

    event_code: str | None
    turbine: str
    event_start_utc: pd.Timestamp
    detection_time_utc: pd.Timestamp | None
    matched: bool
    lead_time_minutes: float | None
    window_days: int
    grid_minutes: int = GRID_MINUTES
    #: Direction of the MATCHED detection: +1 abnormally high, -1 abnormally
    #: low, None when unmatched.
    direction: int | None = None
    #: Direction counts over every persistent detection in the match window,
    #: so a match cannot be read without its context.
    window_direction_census: dict[str, int] = field(default_factory=dict)

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
            "direction": self.direction,
            "direction_label": _DIRECTION_LABELS.get(self.direction, "none"),
            "window_direction_census": dict(self.window_direction_census),
        }


_DIRECTION_LABELS: dict[int | None, str] = {1: "high", -1: "low", 0: "normal", None: "none"}


def match_event(
    event: AlarmLevelEvent,
    detections: list[PersistentDetection],
    *,
    window_days: int,
    expected_direction: int | None = None,
) -> EventMatch:
    """ADR-017(a): first persistent exceedance within the pre-event window.

    ``expected_direction`` defaults to None — the ADR-017 rule, unchanged, so
    every pre-registered result is reproduced exactly. Supplying +1 or -1
    restricts matching to detections of that sign, which is what a
    mechanism-aware evaluation requires; it is offered as an option for the
    author to register, never applied by default (PROJECT.md §34).
    """
    window_start = event.start_utc - pd.Timedelta(days=window_days)
    in_window = [
        d
        for d in detections
        if d.turbine == event.turbine and window_start <= d.first_timestamp_utc <= event.start_utc
    ]
    census = {
        "high": sum(1 for d in in_window if d.direction > 0),
        "low": sum(1 for d in in_window if d.direction < 0),
        "total": len(in_window),
    }
    eligible = (
        in_window
        if expected_direction is None
        else [d for d in in_window if d.direction == expected_direction]
    )
    if not eligible:
        return EventMatch(
            event_code=event.code,
            turbine=event.turbine,
            event_start_utc=event.start_utc,
            detection_time_utc=None,
            matched=False,
            lead_time_minutes=None,
            window_days=window_days,
            direction=None,
            window_direction_census=census,
        )
    first = min(eligible, key=lambda d: d.first_timestamp_utc)
    return EventMatch(
        event_code=event.code,
        turbine=event.turbine,
        event_start_utc=event.start_utc,
        detection_time_utc=first.first_timestamp_utc,
        matched=True,
        lead_time_minutes=quantised_lead_minutes(event.start_utc, first.first_timestamp_utc),
        window_days=window_days,
        direction=first.direction,
        window_direction_census=census,
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
    #: Direction breakdown of the false-alarm episodes. A detector whose
    #: false alarms are predominantly LOW is responding to something other
    #: than the heat-generating mechanisms the FMEA layer describes, and that
    #: is not visible from a single episode count (ADR-037).
    false_alarm_direction_census: dict[str, int] = field(default_factory=dict)

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
            "false_alarm_direction_census": dict(self.false_alarm_direction_census),
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
    expected_direction: int | None = None,
) -> EvaluationResult:
    """Event-level evaluation under the ADR-017 matching rule.

    False-alarm episodes are persistent detections whose first timestamp
    falls outside every event's [window_start, event_end] envelope (an
    endless event's envelope closes at its start).

    ``expected_direction`` is passed through to :func:`match_event` and
    defaults to None (the unmodified ADR-017 rule).
    """
    if not events:
        raise ConfigError("No events supplied; event evaluation is undefined")
    persistent = persistent_detections(detections, min_samples=min_samples)
    matches = tuple(
        match_event(e, persistent, window_days=window_days, expected_direction=expected_direction)
        for e in events
    )

    envelopes = [
        (
            e.turbine,
            e.start_utc - pd.Timedelta(days=window_days),
            e.end_utc if e.end_utc is not None else e.start_utc,
        )
        for e in events
    ]
    outside = [
        d
        for d in persistent
        if not any(
            d.turbine == turbine and start <= d.first_timestamp_utc <= end
            for turbine, start, end in envelopes
        )
    ]
    return EvaluationResult(
        matches=matches,
        false_alarm_episodes=len(outside),
        inferential_allowed=len(events) >= min_events_for_inferential,
        false_alarm_direction_census={
            "high": sum(1 for d in outside if d.direction > 0),
            "low": sum(1 for d in outside if d.direction < 0),
            "total": len(outside),
        },
    )
