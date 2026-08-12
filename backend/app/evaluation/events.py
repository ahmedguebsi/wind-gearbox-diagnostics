"""Canonical operational events and two-tier ground truth (M-24; PROJECT.md §27.1).

The two ground-truth tiers are STRUCTURALLY distinct types (M-24 acceptance
1): :class:`AlarmLevelEvent` (status-log-derived) and
:class:`MechanismLevelEvent` (maintenance-confirmed) share a base but are
different classes, so an evaluation call typed to one tier cannot silently
receive the other.

For the Kelmarsh dataset, ALARM-LEVEL is the only reachable tier (ADR-013):
the exports carry no maintenance free text (LIM-002), and a
MechanismLevelEvent cannot be constructed without a non-empty confirmation
source — the constructor is the guard.

Observed status vocabulary (census, 2016-2021; never assumed beyond it):
the ``Status`` field takes exactly four values — Informational, Stop,
Warning, Communication. There is no Error and no Fault tier.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import pandas as pd

from app.core.errors import ConfigError, TimezoneError
from app.data.ingestion import detect_encoding
from app.data.provenance import ProvenanceRecord

#: Literal used by the Greenbyte export for "no end timestamp / no duration".
BLANK_DASH = "-"


class EventType(StrEnum):
    """Canonical event kinds (PROJECT.md §27.1)."""

    ALARM = "alarm"
    STATUS = "status"
    MAINTENANCE = "maintenance"
    KNOWN_FAILURE = "known_failure"
    REPLACEMENT = "replacement"
    INSPECTION = "inspection"


class StatusValue(StrEnum):
    """The complete observed status vocabulary (census; M-24 note)."""

    INFORMATIONAL = "Informational"
    STOP = "Stop"
    WARNING = "Warning"
    COMMUNICATION = "Communication"


def _require_utc(value: pd.Timestamp, field_name: str) -> None:
    if value.tzinfo is None:
        raise TimezoneError("Event timestamps must be UTC-aware", field=field_name)
    if str(value.tz) != "UTC":
        raise TimezoneError(
            "Event timestamps must be UTC (conversion happens at ingestion)",
            field=field_name,
            timezone=str(value.tz),
        )


@dataclass(frozen=True)
class OperationalEvent:
    """Common event structure. Instantiate a TIER subclass, never this base."""

    turbine: str
    start_utc: pd.Timestamp
    end_utc: pd.Timestamp | None
    event_type: EventType
    code: str | None
    description: str

    def __post_init__(self) -> None:
        _require_utc(self.start_utc, "start_utc")
        if self.end_utc is not None:
            _require_utc(self.end_utc, "end_utc")
            if self.end_utc < self.start_utc:
                raise ConfigError(
                    "Event ends before it starts",
                    start=str(self.start_utc),
                    end=str(self.end_utc),
                )

    @property
    def duration_hours(self) -> float | None:
        if self.end_utc is None:
            return None
        return float((self.end_utc - self.start_utc) / pd.Timedelta(hours=1))


@dataclass(frozen=True)
class AlarmLevelEvent(OperationalEvent):
    """Tier 1 — anomaly-detection ground truth, status-log-derived.

    The only tier constructible from the Kelmarsh exports (ADR-013).
    """

    status: StatusValue | None = None


@dataclass(frozen=True)
class MechanismLevelEvent(OperationalEvent):
    """Tier 2 — mechanism-level ground truth, maintenance-confirmed.

    Requires a non-empty ``confirmation_source`` naming the maintenance or
    inspection evidence. The Kelmarsh exports contain none (LIM-002), so no
    instance of this tier exists for this dataset — the constructor makes
    silently promoting an alarm to a mechanism impossible.
    """

    confirmation_source: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.confirmation_source.strip():
            raise ConfigError(
                "Mechanism-level ground truth requires maintenance confirmation "
                "evidence (ADR-013: none exists in this dataset — LIM-002)",
                event_code=self.code,
            )


#: Verbatim Greenbyte status-export columns (census header inventory).
STATUS_EXPORT_COLUMNS: tuple[str, ...] = (
    "Timestamp start",
    "Timestamp end",
    "Status",
    "Code",
    "Message",
)


def parse_status_frame(
    frame: pd.DataFrame,
    *,
    turbine: str,
    rejected: list[dict[str, str]] | None = None,
) -> list[AlarmLevelEvent]:
    """Greenbyte status rows → alarm-level events (UTC; census-declared).

    ``Timestamp end`` holding the literal ``-`` becomes ``None`` — most
    status rows carry no measurable duration (LIM-003), and that absence is
    preserved, never imputed. A ``Status`` value outside the observed
    four-value vocabulary is an error: the census does not assume beyond it.

    ``rejected``: when a list is supplied, rows the event constructor
    refuses (e.g. end-before-start timestamp pairs — real rows exist in the
    2016 export) are collected verbatim with the refusal reason instead of
    aborting the parse; the caller reports them as dataset findings
    (LIM-011). When None (the default), the first invalid row raises.
    """
    missing = [c for c in STATUS_EXPORT_COLUMNS if c not in frame.columns]
    if missing:
        raise ConfigError("Status frame lacks expected columns", missing=missing)
    events: list[AlarmLevelEvent] = []
    for _, row in frame.iterrows():
        raw_status = str(row["Status"]).strip()
        try:
            status = StatusValue(raw_status)
        except ValueError as exc:
            raise ConfigError(
                "Status value outside the observed vocabulary "
                "(census: Informational/Stop/Warning/Communication)",
                value=raw_status,
            ) from exc
        raw_end = str(row["Timestamp end"]).strip()
        end = None if raw_end in (BLANK_DASH, "", "nan", "NaT") else pd.Timestamp(raw_end, tz="UTC")
        try:
            events.append(
                AlarmLevelEvent(
                    turbine=turbine,
                    start_utc=pd.Timestamp(str(row["Timestamp start"]).strip(), tz="UTC"),
                    end_utc=end,
                    event_type=EventType.ALARM,
                    code=str(row["Code"]).strip(),
                    description=str(row["Message"]).strip(),
                    status=status,
                )
            )
        except ConfigError as exc:
            if rejected is None:
                raise
            rejected.append(
                {
                    "turbine": turbine,
                    "start": str(row["Timestamp start"]).strip(),
                    "end": raw_end,
                    "code": str(row["Code"]).strip(),
                    "status": raw_status,
                    "reason": str(exc),
                }
            )
    return events


def parse_status_csv(
    path: Path,
    *,
    turbine: str,
    skip_lines: int = 0,
    schema_version: str = "",
    rejected: list[dict[str, str]] | None = None,
) -> tuple[list[AlarmLevelEvent], ProvenanceRecord]:
    """Load a status CSV with provenance capture (M-24 test obligation).

    Timestamps in these exports are UTC by the files' own declaration
    (census ``timezone`` section: single distinct declared value).
    """
    encoding = detect_encoding(path)
    frame = pd.read_csv(path, encoding=encoding, skiprows=skip_lines, dtype=str)
    record = ProvenanceRecord.capture(
        path,
        source_timezone="UTC",
        encoding=encoding,
        schema_version=schema_version,
        mapping_hash="status-export-parser-v1",
    )
    return parse_status_frame(frame, turbine=turbine, rejected=rejected), record


def _utc(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


#: EVENT-001 — the single labelled gearbox event (ADR-013; decision queue
#: D-04). Timestamps are the verbatim occurrence rows recorded in
#: docs/evidence/EVIDENCE_D04_AND_TARGETS.json. ONE event, not three: the
#: occurrences are separated by 4.9 and 7.45 days across a 95-day span with
#: the alarm active ~82 days — a single continuous degradation episode with
#: brief clearances. Alarm-level tier ONLY: code 1860 is a
#: filter-restriction Warning, not maintenance-verified damage.
EVENT_001_OCCURRENCES: tuple[AlarmLevelEvent, ...] = (
    AlarmLevelEvent(
        turbine="Kelmarsh 1",
        start_utc=_utc("2019-02-24 16:46:28"),
        end_utc=_utc("2019-04-04 12:35:45"),
        event_type=EventType.ALARM,
        code="1860",
        description="Oil filter gear choked",
        status=StatusValue.WARNING,
    ),
    AlarmLevelEvent(
        turbine="Kelmarsh 1",
        start_utc=_utc("2019-04-09 10:09:03"),
        end_utc=_utc("2019-05-21 10:06:24"),
        event_type=EventType.ALARM,
        code="1860",
        description="Oil filter gear choked",
        status=StatusValue.WARNING,
    ),
    AlarmLevelEvent(
        turbine="Kelmarsh 1",
        start_utc=_utc("2019-05-28 20:55:45"),
        end_utc=_utc("2019-05-30 07:34:04"),
        event_type=EventType.ALARM,
        code="1860",
        description="Oil filter gear choked",
        status=StatusValue.WARNING,
    ),
)

EVENT_001: AlarmLevelEvent = AlarmLevelEvent(
    turbine="Kelmarsh 1",
    start_utc=EVENT_001_OCCURRENCES[0].start_utc,
    end_utc=EVENT_001_OCCURRENCES[-1].end_utc,
    event_type=EventType.ALARM,
    code="1860",
    description=(
        "Oil filter gear choked — ONE event per ADR-013 (three occurrences, "
        "single continuous degradation episode with brief clearances). "
        "Case-study analysis focuses on the onset of occurrence 1; "
        "occurrences 2-3 are continuation (ADR-014, LIM-008)."
    ),
    status=StatusValue.WARNING,
)
