"""M-24 tests: canonical events, two-tier ground truth, status parsing.

EVENT-001 constants are the ADR-013 designation (real, committed evidence);
parser fixtures are SYNTHETIC TEST DATA — NOT VALID THESIS EVIDENCE.
"""

from itertools import pairwise

import pandas as pd
import pytest

from app.core.errors import ConfigError, TimezoneError
from app.evaluation.events import (
    EVENT_001,
    EVENT_001_OCCURRENCES,
    AlarmLevelEvent,
    EventType,
    MechanismLevelEvent,
    OperationalEvent,
    StatusValue,
    parse_status_csv,
    parse_status_frame,
)


def _utc(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


class TestEvent001Designation:
    def test_matches_adr013_record(self):
        assert EVENT_001.code == "1860"
        assert EVENT_001.turbine == "Kelmarsh 1"
        assert EVENT_001.status is StatusValue.WARNING
        assert EVENT_001.start_utc == _utc("2019-02-24 16:46:28")
        assert EVENT_001.end_utc == _utc("2019-05-30 07:34:04")
        assert isinstance(EVENT_001, AlarmLevelEvent)
        assert not isinstance(EVENT_001, MechanismLevelEvent)

    def test_one_event_not_three(self):
        assert len(EVENT_001_OCCURRENCES) == 3
        gaps_days = [
            (b.start_utc - a.end_utc) / pd.Timedelta(days=1)
            for a, b in pairwise(EVENT_001_OCCURRENCES)
        ]
        assert gaps_days[0] == pytest.approx(4.898, abs=0.01)
        assert gaps_days[1] == pytest.approx(7.451, abs=0.01)
        span_days = (EVENT_001.end_utc - EVENT_001.start_utc) / pd.Timedelta(days=1)
        assert span_days == pytest.approx(94.6, abs=0.1)
        active_hours = sum(o.duration_hours for o in EVENT_001_OCCURRENCES)
        assert active_hours == pytest.approx(1974.4, abs=1.0)

    def test_occurrence_durations_match_evidence(self):
        durations = [o.duration_hours for o in EVENT_001_OCCURRENCES]
        assert durations[0] == pytest.approx(931.821, abs=0.01)
        assert durations[1] == pytest.approx(1007.956, abs=0.01)
        assert durations[2] == pytest.approx(34.639, abs=0.01)


class TestTierSeparation:
    def test_tiers_are_distinct_types(self):
        """M-24 acceptance 1: the tiers cannot be conflated."""
        alarm = AlarmLevelEvent(
            turbine="T1",
            start_utc=_utc("2020-01-01"),
            end_utc=None,
            event_type=EventType.ALARM,
            code="1",
            description="x",
        )
        assert isinstance(alarm, OperationalEvent)
        assert not isinstance(alarm, MechanismLevelEvent)

    def test_mechanism_tier_requires_confirmation_evidence(self):
        with pytest.raises(ConfigError, match="confirmation"):
            MechanismLevelEvent(
                turbine="T1",
                start_utc=_utc("2020-01-01"),
                end_utc=None,
                event_type=EventType.MAINTENANCE,
                code=None,
                description="x",
                confirmation_source="   ",
            )
        confirmed = MechanismLevelEvent(
            turbine="T1",
            start_utc=_utc("2020-01-01"),
            end_utc=None,
            event_type=EventType.REPLACEMENT,
            code=None,
            description="x",
            confirmation_source="work order WO-1 (synthetic fixture)",
        )
        assert isinstance(confirmed, MechanismLevelEvent)


class TestTimestampDiscipline:
    def test_naive_timestamp_rejected(self):
        with pytest.raises(TimezoneError):
            AlarmLevelEvent(
                turbine="T1",
                start_utc=pd.Timestamp("2020-01-01"),
                end_utc=None,
                event_type=EventType.ALARM,
                code="1",
                description="x",
            )

    def test_non_utc_timezone_rejected(self):
        with pytest.raises(TimezoneError):
            AlarmLevelEvent(
                turbine="T1",
                start_utc=pd.Timestamp("2020-01-01", tz="Europe/London"),
                end_utc=None,
                event_type=EventType.ALARM,
                code="1",
                description="x",
            )

    def test_end_before_start_rejected(self):
        with pytest.raises(ConfigError):
            AlarmLevelEvent(
                turbine="T1",
                start_utc=_utc("2020-01-02"),
                end_utc=_utc("2020-01-01"),
                event_type=EventType.ALARM,
                code="1",
                description="x",
            )


STATUS_ROWS = pd.DataFrame(
    {
        "Timestamp start": ["2020-03-01 10:00:00", "2020-03-02 11:30:00"],
        "Timestamp end": ["2020-03-01 12:00:00", "-"],
        "Status": ["Warning", "Informational"],
        "Code": ["1860", "6"],
        "Message": ["Oil filter gear choked", "System OK"],
    }
)


class TestStatusParsing:
    def test_parse_frame_utc_and_dash_handling(self):
        events = parse_status_frame(STATUS_ROWS, turbine="T1")
        assert len(events) == 2
        first, second = events
        assert first.status is StatusValue.WARNING
        assert first.duration_hours == pytest.approx(2.0)
        assert str(first.start_utc.tz) == "UTC"
        assert second.end_utc is None
        assert second.duration_hours is None
        assert all(isinstance(e, AlarmLevelEvent) for e in events)

    def test_unknown_status_value_rejected(self):
        frame = STATUS_ROWS.copy()
        frame.loc[0, "Status"] = "Error"
        with pytest.raises(ConfigError, match="vocabulary"):
            parse_status_frame(frame, turbine="T1")

    def test_missing_columns_rejected(self):
        with pytest.raises(ConfigError):
            parse_status_frame(STATUS_ROWS.drop(columns=["Code"]), turbine="T1")

    def test_parse_csv_captures_provenance(self, tmp_path):
        path = tmp_path / "status.csv"
        STATUS_ROWS.to_csv(path, index=False)
        events, record = parse_status_csv(path, turbine="T1", schema_version="1.2.0")
        assert len(events) == 2
        assert record.sha256
        assert record.source_timezone == "UTC"
        record.verify()
