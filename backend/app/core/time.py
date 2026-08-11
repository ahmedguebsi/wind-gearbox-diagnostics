"""UTC utilities and DST anomaly primitives (M-02; PROJECT.md §8, §11).

The UTC-everywhere rule: timezone conversion happens exactly once, at
ingestion, using the mapping config's declared ``source_timezone``. Every
internal API operates on UTC-aware datetimes; naive datetimes are rejected
with :class:`~app.core.errors.TimezoneError`.

The DST primitives in this module intentionally accept *naive local*
timestamps: they exist to inspect raw source data **before** UTC conversion,
identifying autumn fold-back duplicates and spring-forward gaps so ingestion
can report them (never silently drop them).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.errors import TimezoneError

__all__ = [
    "UTC",
    "DstAnomaly",
    "DstAnomalyKind",
    "ensure_utc",
    "find_dst_anomalies",
    "get_zone",
    "is_ambiguous_local",
    "is_nonexistent_local",
    "localize_to_utc",
    "utc_now",
]


def get_zone(name: str) -> ZoneInfo:
    """Resolve an IANA timezone name, raising ``TimezoneError`` if unknown."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise TimezoneError(
            "Unknown source timezone; ingestion must stop and ask (PROJECT.md §8)",
            timezone=name,
        ) from exc


def ensure_utc(value: datetime) -> datetime:
    """Return ``value`` converted to UTC; reject naive datetimes.

    This is the chokepoint through which every internal timestamp passes:
    no internal API accepts naive datetimes.
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise TimezoneError("Naive datetime rejected: internal APIs are UTC-aware only")
    return value.astimezone(UTC)


def utc_now() -> datetime:
    """Current time as a UTC-aware datetime."""
    return datetime.now(tz=UTC)


def localize_to_utc(
    local_naive: datetime,
    source_timezone: str,
    *,
    fold: Literal[0, 1] = 0,
) -> datetime:
    """Convert a naive source-local timestamp to UTC (ingestion-time only).

    ``fold`` selects which of the two possible instants an autumn fold-back
    duplicate refers to (0 = first occurrence, 1 = second); it follows PEP 495
    semantics. Aware input is rejected — an aware timestamp must go through
    :func:`ensure_utc` instead, so the declared source timezone can never
    silently disagree with an embedded offset.
    """
    if local_naive.tzinfo is not None:
        raise TimezoneError(
            "localize_to_utc expects a naive source-local timestamp; "
            "aware timestamps must use ensure_utc"
        )
    zone = get_zone(source_timezone)
    return local_naive.replace(tzinfo=zone, fold=fold).astimezone(UTC)


def is_ambiguous_local(local_naive: datetime, source_timezone: str) -> bool:
    """True if the naive local timestamp is an autumn fold-back duplicate
    (maps to two distinct UTC instants)."""
    _reject_aware(local_naive)
    zone = get_zone(source_timezone)
    first = local_naive.replace(tzinfo=zone, fold=0).utcoffset()
    second = local_naive.replace(tzinfo=zone, fold=1).utcoffset()
    return first != second


def is_nonexistent_local(local_naive: datetime, source_timezone: str) -> bool:
    """True if the naive local timestamp falls in a spring-forward gap
    (no UTC instant maps back to it)."""
    _reject_aware(local_naive)
    zone = get_zone(source_timezone)
    round_trip = local_naive.replace(tzinfo=zone).astimezone(UTC).astimezone(zone)
    return round_trip.replace(tzinfo=None) != local_naive


def _reject_aware(value: datetime) -> None:
    if value.tzinfo is not None:
        raise TimezoneError("DST primitives inspect naive source-local timestamps only")


class DstAnomalyKind(StrEnum):
    """Kind of DST anomaly found in source-local timestamps."""

    FOLD_DUPLICATE = "fold_duplicate"
    SPRING_GAP = "spring_gap"


@dataclass(frozen=True)
class DstAnomaly:
    """A DST anomaly descriptor consumed by validation reporting (M-10)."""

    kind: DstAnomalyKind
    local_time: datetime
    source_timezone: str


def find_dst_anomalies(
    local_timestamps: list[datetime],
    source_timezone: str,
) -> list[DstAnomaly]:
    """Identify DST anomalies in naive source-local timestamps.

    Returns one descriptor per affected timestamp, in input order. The
    caller reports these (PROJECT.md §8: detected and reported, never
    silently dropped).
    """
    anomalies: list[DstAnomaly] = []
    for ts in local_timestamps:
        if is_nonexistent_local(ts, source_timezone):
            anomalies.append(DstAnomaly(DstAnomalyKind.SPRING_GAP, ts, source_timezone))
        elif is_ambiguous_local(ts, source_timezone):
            anomalies.append(DstAnomaly(DstAnomalyKind.FOLD_DUPLICATE, ts, source_timezone))
    return anomalies
