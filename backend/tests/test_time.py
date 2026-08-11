"""M-02 tests: UTC utilities and DST anomaly primitives.

Fixtures use Europe/London 2016 transitions (matching the candidate Kelmarsh
dataset year): spring forward 2016-03-27 01:00 GMT → 02:00 BST, fall back
2016-10-30 02:00 BST → 01:00 GMT.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.core.errors import TimezoneError
from app.core.time import (
    DstAnomalyKind,
    ensure_utc,
    find_dst_anomalies,
    get_zone,
    is_ambiguous_local,
    is_nonexistent_local,
    localize_to_utc,
    utc_now,
)

LONDON = "Europe/London"


class TestEnsureUtc:
    def test_naive_datetime_rejected(self):
        with pytest.raises(TimezoneError):
            ensure_utc(datetime(2016, 6, 1, 12, 0))

    def test_aware_datetime_converted(self):
        cet = timezone(timedelta(hours=2))
        result = ensure_utc(datetime(2016, 6, 1, 12, 0, tzinfo=cet))
        assert result == datetime(2016, 6, 1, 10, 0, tzinfo=UTC)
        assert result.tzinfo == UTC

    def test_utc_now_is_aware_utc(self):
        assert utc_now().tzinfo == UTC


class TestGetZone:
    def test_unknown_zone_raises(self):
        with pytest.raises(TimezoneError):
            get_zone("Mars/Olympus")

    def test_known_zone_resolves(self):
        assert get_zone(LONDON).key == LONDON


class TestLocalizeToUtc:
    def test_winter_london_equals_utc(self):
        result = localize_to_utc(datetime(2016, 1, 15, 12, 0), LONDON)
        assert result == datetime(2016, 1, 15, 12, 0, tzinfo=UTC)

    def test_summer_london_is_utc_plus_one(self):
        result = localize_to_utc(datetime(2016, 7, 15, 12, 0), LONDON)
        assert result == datetime(2016, 7, 15, 11, 0, tzinfo=UTC)

    def test_fold_selects_autumn_duplicate_instant(self):
        ambiguous = datetime(2016, 10, 30, 1, 30)
        first = localize_to_utc(ambiguous, LONDON, fold=0)
        second = localize_to_utc(ambiguous, LONDON, fold=1)
        assert first == datetime(2016, 10, 30, 0, 30, tzinfo=UTC)  # still BST
        assert second == datetime(2016, 10, 30, 1, 30, tzinfo=UTC)  # back to GMT

    def test_aware_input_rejected(self):
        with pytest.raises(TimezoneError):
            localize_to_utc(datetime(2016, 1, 15, 12, 0, tzinfo=UTC), LONDON)


class TestDstBoundaries:
    def test_spring_gap_identified_with_exact_boundaries(self):
        assert is_nonexistent_local(datetime(2016, 3, 27, 1, 0), LONDON)
        assert is_nonexistent_local(datetime(2016, 3, 27, 1, 30), LONDON)
        assert is_nonexistent_local(datetime(2016, 3, 27, 1, 59, 59), LONDON)
        assert not is_nonexistent_local(datetime(2016, 3, 27, 0, 59, 59), LONDON)
        assert not is_nonexistent_local(datetime(2016, 3, 27, 2, 0), LONDON)

    def test_autumn_fold_identified_with_exact_boundaries(self):
        assert is_ambiguous_local(datetime(2016, 10, 30, 1, 0), LONDON)
        assert is_ambiguous_local(datetime(2016, 10, 30, 1, 30), LONDON)
        assert is_ambiguous_local(datetime(2016, 10, 30, 1, 59, 59), LONDON)
        assert not is_ambiguous_local(datetime(2016, 10, 30, 0, 59, 59), LONDON)
        assert not is_ambiguous_local(datetime(2016, 10, 30, 2, 0), LONDON)

    def test_ordinary_timestamps_are_neither(self):
        ordinary = datetime(2016, 6, 15, 14, 20)
        assert not is_ambiguous_local(ordinary, LONDON)
        assert not is_nonexistent_local(ordinary, LONDON)

    def test_aware_input_rejected(self):
        aware = datetime(2016, 10, 30, 1, 30, tzinfo=UTC)
        with pytest.raises(TimezoneError):
            is_ambiguous_local(aware, LONDON)
        with pytest.raises(TimezoneError):
            is_nonexistent_local(aware, LONDON)


class TestFindDstAnomalies:
    def test_mixed_sequence_classified_in_order(self):
        timestamps = [
            datetime(2016, 3, 27, 0, 50),  # normal
            datetime(2016, 3, 27, 1, 30),  # spring gap
            datetime(2016, 6, 15, 12, 0),  # normal
            datetime(2016, 10, 30, 1, 30),  # fold duplicate
        ]
        anomalies = find_dst_anomalies(timestamps, LONDON)
        assert [a.kind for a in anomalies] == [
            DstAnomalyKind.SPRING_GAP,
            DstAnomalyKind.FOLD_DUPLICATE,
        ]
        assert anomalies[0].local_time == datetime(2016, 3, 27, 1, 30)
        assert anomalies[1].local_time == datetime(2016, 10, 30, 1, 30)
        assert all(a.source_timezone == LONDON for a in anomalies)

    def test_clean_sequence_yields_nothing(self):
        clean = [datetime(2016, 6, 15, h, 0) for h in range(6)]
        assert find_dst_anomalies(clean, LONDON) == []
