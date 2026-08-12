"""M-27 tests: event matching (ADR-017), small-n gate (ADR-014).

Fixtures are SYNTHETIC TEST DATA — NOT VALID THESIS EVIDENCE (LOCKED-08);
they exercise matching mechanics, never detection performance claims.
"""

import pandas as pd
import pytest

from app.core.errors import ConfigError
from app.evaluation.event_eval import (
    GRID_MINUTES,
    evaluate_events,
    match_event,
    persistent_detections,
    quantised_lead_minutes,
)
from app.evaluation.events import AlarmLevelEvent, EventType, StatusValue
from app.residuals.ewma import PRIMARY_EWMA_LABEL, DetectionSeries


def _detections(states, turbine="T1", start="2019-02-10 00:00:00") -> DetectionSeries:
    n = len(states)
    return DetectionSeries(
        turbine=turbine,
        target="gearbox_oil_temperature",
        timestamps=pd.Series(pd.date_range(start, periods=n, freq="10min", tz="UTC")),
        states=pd.Series(list(states)),
        method_label=PRIMARY_EWMA_LABEL,
    )


def _event(start="2019-02-24 16:46:28", end="2019-04-04 12:35:45", turbine="T1"):
    return AlarmLevelEvent(
        turbine=turbine,
        start_utc=pd.Timestamp(start, tz="UTC"),
        end_utc=pd.Timestamp(end, tz="UTC"),
        event_type=EventType.ALARM,
        code="1860",
        description="Oil filter gear choked",
        status=StatusValue.WARNING,
    )


class TestPersistenceQualification:
    def test_isolated_and_short_runs_never_count(self):
        """ADR-017(b)."""
        stream = _detections([0, 1, 0, 1, 1, 0])
        assert persistent_detections([stream], min_samples=3) == []

    def test_sustained_run_timestamped_at_first_sample(self):
        stream = _detections([0, 1, 1, 1, 0])
        (found,) = persistent_detections([stream], min_samples=3)
        assert found.first_timestamp_utc == pd.Timestamp("2019-02-10 00:10:00", tz="UTC")
        assert found.run_length == 3
        assert found.direction == 1

    def test_negative_runs_and_terminal_runs_count(self):
        stream = _detections([0, -1, -1, -1])
        (found,) = persistent_detections([stream], min_samples=3)
        assert found.direction == -1

    def test_direction_change_breaks_the_run(self):
        stream = _detections([1, 1, -1, -1, 0])
        assert persistent_detections([stream], min_samples=3) == []

    def test_min_samples_below_two_rejected(self):
        with pytest.raises(ConfigError, match="ADR-017"):
            persistent_detections([_detections([1, 1])], min_samples=1)


class TestMatchingWindow:
    def test_detection_inside_window_matches_with_positive_lead(self):
        """ADR-017(a): [event_start - 14 days, event_start]."""
        stream = _detections([0] + [1] * 6 + [0], start="2019-02-20 00:00:00")
        result = evaluate_events([_event()], [stream], window_days=14, min_samples=3)
        (match,) = result.matches
        assert match.matched
        assert match.detection_time_utc == pd.Timestamp("2019-02-20 00:10:00", tz="UTC")
        assert match.lead_time_minutes is not None and match.lead_time_minutes > 0
        assert match.lead_time_minutes % GRID_MINUTES == 0

    def test_detection_before_window_does_not_match(self):
        stream = _detections([1] * 6, start="2019-02-01 00:00:00")  # 23 days early
        result = evaluate_events([_event()], [stream], window_days=14, min_samples=3)
        assert result.matches[0].matched is False
        assert result.matches[0].lead_time_minutes is None

    def test_detection_after_event_start_does_not_match(self):
        stream = _detections([1] * 6, start="2019-02-25 00:00:00")
        result = evaluate_events([_event()], [stream], window_days=14, min_samples=3)
        assert result.matches[0].matched is False

    def test_window_days_boundary(self):
        event = _event()
        inside = persistent_detections(
            [_detections([1] * 3, start="2019-02-11 00:00:00")], min_samples=3
        )
        assert match_event(event, inside, window_days=14).matched
        assert not match_event(event, inside, window_days=7).matched

    def test_lead_time_quantised_to_grid(self):
        """ADR-017(c): second-resolution events, 10-minute detections."""
        event_start = pd.Timestamp("2019-02-24 16:46:28", tz="UTC")
        detection_time = pd.Timestamp("2019-02-21 16:40:00", tz="UTC")
        lead = quantised_lead_minutes(event_start, detection_time)
        assert lead % GRID_MINUTES == 0
        raw = (event_start - detection_time) / pd.Timedelta(minutes=1)
        assert lead <= raw < lead + GRID_MINUTES


class TestSmallNGate:
    def test_single_event_is_descriptive_only(self):
        """M-27 acceptance 1 / ADR-014: no detection-rate claims below the
        pre-committed threshold — structurally gated."""
        stream = _detections([1] * 6, start="2019-02-20 00:00:00")
        result = evaluate_events([_event()], [stream], window_days=14, min_samples=3)
        assert result.inferential_allowed is False
        with pytest.raises(ConfigError, match="DESCRIPTIVE"):
            result.detection_rate()
        assert "detection_rate" not in result.as_dict()

    def test_two_events_unlock_inferential_mode(self):
        stream = _detections([1] * 6, start="2019-02-20 00:00:00")
        events = [_event(), _event(start="2019-06-01 00:00:00", end="2019-06-02 00:00:00")]
        result = evaluate_events(events, [stream], window_days=14, min_samples=3)
        assert result.inferential_allowed is True
        assert result.detection_rate() == pytest.approx(0.5)
        assert result.as_dict()["detection_rate"] == pytest.approx(0.5)

    def test_no_events_rejected(self):
        with pytest.raises(ConfigError):
            evaluate_events([], [_detections([0])], window_days=14, min_samples=3)


class TestFalseAlarms:
    def test_runs_outside_event_envelopes_count(self):
        inside = _detections([1] * 6, start="2019-02-20 00:00:00")
        outside = _detections([1] * 6, start="2019-08-01 00:00:00")
        result = evaluate_events([_event()], [inside, outside], window_days=14, min_samples=3)
        assert result.matches[0].matched
        assert result.false_alarm_episodes == 1

    def test_runs_during_the_event_are_not_false_alarms(self):
        during = _detections([1] * 6, start="2019-03-10 00:00:00")
        result = evaluate_events([_event()], [during], window_days=14, min_samples=3)
        assert result.false_alarm_episodes == 0
