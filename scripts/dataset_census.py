"""Phase 0.5 dataset census — READ-ONLY, FACTS ONLY (PROJECT.md §7.5).

Produces the JSON evidence for docs/DATASET_DUE_DILIGENCE.md: per-file row
counts, timestamp behaviour (sampling intervals, irregularities, duplicates,
DST facts under an explicitly declared assumed timezone), per-column null
fractions and value ranges, constant and low-variance columns, event-file
row counts by category, and — only where the author has designated the
qualifying event codes — the count of confirmed gearbox failure events.

No cleaning, no judgment, no narrative, no inferred labels. Anything that
would require a definition the author has not supplied is emitted as
"UNKNOWN — requires confirmation". Input files are never modified.

Usage (run from the repository root):

    uv run --project backend python scripts/dataset_census.py \
        --scada <scada.csv> [<scada2.csv> ...] --timestamp-column "<raw name>" \
        [--turbine-column "<raw name>"] [--comment-prefix "#"] \
        [--assume-timezone Europe/London] \
        [--events <status.csv> ...] [--event-timestamp-column "<raw name>"] \
        [--event-category-columns "<col>" ...] [--event-code-column "<col>"] \
        [--gearbox-event-codes 1510 1800 ...] \
        --output census.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

UNKNOWN = "UNKNOWN — requires confirmation"
LOW_VARIANCE_STD = 1e-6
_OFFSET_RE = re.compile(r"(?:[+-]\d{2}:?\d{2}|Z)\s*$")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path: Path, comment_prefix: str | None) -> tuple[pd.DataFrame, str]:
    for encoding in ("utf-8", "latin-1"):
        try:
            frame = pd.read_csv(path, comment=comment_prefix, low_memory=False, encoding=encoding)
        except UnicodeDecodeError:
            continue
        return frame, encoding
    raise SystemExit(f"Cannot decode {path} as utf-8 or latin-1")


def _column_facts(frame: pd.DataFrame) -> dict[str, Any]:
    per_column: dict[str, Any] = {}
    constant: list[str] = []
    low_variance: list[str] = []
    n_rows = len(frame)
    for name in frame.columns:
        series = frame[name]
        n_unique = int(series.nunique(dropna=True))
        facts: dict[str, Any] = {
            "dtype": str(series.dtype),
            "null_fraction": round(float(series.isna().mean()) if n_rows else 0.0, 6),
            "n_unique": n_unique,
        }
        if pd.api.types.is_numeric_dtype(series):
            std = series.std() if n_unique > 0 else None
            facts["min"] = None if pd.isna(series.min()) else float(series.min())
            facts["max"] = None if pd.isna(series.max()) else float(series.max())
            facts["std"] = None if std is None or pd.isna(std) else float(std)
            if n_unique > 1 and facts["std"] is not None and facts["std"] < LOW_VARIANCE_STD:
                low_variance.append(str(name))
        if n_unique <= 1:
            constant.append(str(name))
        per_column[str(name)] = facts
    return {
        "per_column": per_column,
        "constant_columns": constant,
        "low_variance_columns": low_variance,
        "criteria": {
            "constant": "n_unique(dropna) <= 1 (includes all-null columns)",
            "low_variance": f"numeric std < {LOW_VARIANCE_STD} and not constant",
        },
    }


def _timestamp_facts(
    frame: pd.DataFrame, column: str, assume_timezone: str | None
) -> dict[str, Any]:
    if column not in frame.columns:
        return {"error": f"timestamp column {column!r} not present", "status": UNKNOWN}
    raw = frame[column].astype("string")
    parsed = pd.to_datetime(raw, errors="coerce")
    valid = parsed.dropna().sort_values()
    sample = raw.dropna().head(100)
    facts: dict[str, Any] = {
        "column": column,
        "unparseable_count": int(parsed.isna().sum() - raw.isna().sum()),
        "null_count": int(raw.isna().sum()),
        "min": None if valid.empty else valid.iloc[0].isoformat(),
        "max": None if valid.empty else valid.iloc[-1].isoformat(),
        "duplicate_timestamp_count": int(valid.duplicated().sum()),
        "utc_offset_markers_present_in_raw_strings": bool(
            sample.map(lambda s: bool(_OFFSET_RE.search(s))).any()
        ),
    }
    if len(valid) >= 2:
        deltas = valid.diff().dropna()
        counts = deltas.value_counts().head(5)
        facts["interval_value_counts_top5"] = {
            str(interval): int(count) for interval, count in counts.items()
        }
        modal = deltas.mode().iloc[0]
        gaps = deltas[deltas > modal]
        largest = gaps.sort_values(ascending=False).head(5)
        facts["modal_interval"] = str(modal)
        facts["gap_count_above_modal_interval"] = len(gaps)
        facts["largest_gaps"] = [
            {"end": valid.loc[idx].isoformat(), "duration": str(gap)}
            for idx, gap in largest.items()
        ]
    facts["dst"] = _dst_facts(valid, assume_timezone)
    return facts


def _dst_facts(valid: pd.Series, assume_timezone: str | None) -> dict[str, Any]:
    if assume_timezone is None:
        return {
            "status": UNKNOWN,
            "note": "no timezone declared; pass --assume-timezone to compute DST facts",
        }
    if valid.empty:
        return {"assumed_timezone": assume_timezone, "transitions_in_range": []}
    zone = ZoneInfo(assume_timezone)
    start, end = valid.iloc[0].date(), valid.iloc[-1].date()
    transitions: list[dict[str, Any]] = []
    day = start
    while day < end:
        noon = datetime(day.year, day.month, day.day, 12, tzinfo=zone)
        next_noon = noon + timedelta(days=1)
        off_a, off_b = noon.utcoffset(), next_noon.astimezone(zone).utcoffset()
        if off_a != off_b:
            transition_date = next_noon.date()
            that_day = valid[valid.dt.date == transition_date]
            transitions.append(
                {
                    "date": transition_date.isoformat(),
                    "offset_before": str(off_a),
                    "offset_after": str(off_b),
                    "direction": "forward"
                    if (off_b or timedelta()) > (off_a or timedelta())
                    else "backward",
                    "duplicate_timestamps_that_day": int(that_day.duplicated().sum()),
                    "rows_that_day": len(that_day),
                }
            )
        day = day + timedelta(days=1)
    return {"assumed_timezone": assume_timezone, "transitions_in_range": transitions}


def census_scada(
    paths: list[Path],
    timestamp_column: str,
    turbine_column: str | None,
    comment_prefix: str | None,
    assume_timezone: str | None,
) -> list[dict[str, Any]]:
    results = []
    for path in paths:
        frame, encoding = _read_csv(path, comment_prefix)
        entry: dict[str, Any] = {
            "file": path.name,
            "sha256": sha256_of(path),
            "encoding_used": encoding,
            "n_rows": len(frame),
            "n_columns": int(frame.shape[1]),
            "timestamps": _timestamp_facts(frame, timestamp_column, assume_timezone),
        }
        if turbine_column is not None and turbine_column in frame.columns:
            counts = frame[turbine_column].value_counts(dropna=False)
            entry["rows_per_turbine"] = {str(k): int(v) for k, v in counts.items()}
        elif turbine_column is not None:
            entry["rows_per_turbine"] = {"error": f"column {turbine_column!r} absent"}
        else:
            entry["rows_per_turbine"] = {
                "note": "no turbine column declared; file treated as one unit"
            }
        entry.update(_column_facts(frame))
        results.append(entry)
    return results


def census_events(
    paths: list[Path],
    comment_prefix: str | None,
    timestamp_column: str | None,
    category_columns: list[str],
    code_column: str | None,
) -> list[dict[str, Any]]:
    results = []
    for path in paths:
        frame, encoding = _read_csv(path, comment_prefix)
        entry: dict[str, Any] = {
            "file": path.name,
            "sha256": sha256_of(path),
            "encoding_used": encoding,
            "n_rows": len(frame),
            "columns": [str(c) for c in frame.columns],
        }
        if timestamp_column is not None and timestamp_column in frame.columns:
            parsed = pd.to_datetime(frame[timestamp_column], errors="coerce").dropna()
            entry["timestamp_range"] = {
                "column": timestamp_column,
                "min": None if parsed.empty else parsed.min().isoformat(),
                "max": None if parsed.empty else parsed.max().isoformat(),
            }
        chosen = category_columns or [
            str(c)
            for c in frame.columns
            if frame[c].dtype == object and frame[c].nunique(dropna=True) <= 60
        ]
        entry["row_counts_by_category"] = {
            column: {str(k): int(v) for k, v in frame[column].value_counts(dropna=False).items()}
            for column in chosen
            if column in frame.columns
        }
        if code_column is not None and code_column in frame.columns:
            counts = frame[code_column].value_counts(dropna=False).head(500)
            entry["event_code_counts"] = {str(k): int(v) for k, v in counts.items()}
        results.append(entry)
    return results


def gearbox_event_count(
    event_entries: list[dict[str, Any]],
    event_paths: list[Path],
    comment_prefix: str | None,
    code_column: str | None,
    designated_codes: list[str],
) -> dict[str, Any]:
    if not designated_codes or code_column is None:
        return {
            "count": UNKNOWN,
            "note": (
                "Counting confirmed gearbox failure events requires the author to "
                "designate qualifying event codes (--gearbox-event-codes with "
                "--event-code-column). No inference is performed."
            ),
        }
    codes = {str(c) for c in designated_codes}
    per_file: dict[str, int] = {}
    total = 0
    for path in event_paths:
        frame, _ = _read_csv(path, comment_prefix)
        if code_column not in frame.columns:
            per_file[path.name] = -1
            continue
        n = int(frame[code_column].astype("string").isin(codes).sum())
        per_file[path.name] = n
        total += n
    return {
        "author_designated_codes": sorted(codes),
        "occurrences_per_file": per_file,
        "total_occurrences": total,
        "note": (
            "Occurrences of author-designated codes; whether occurrences constitute "
            "independent events is a D-04 ground-truth decision, not a script output."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scada", nargs="*", default=[], help="SCADA CSV files")
    parser.add_argument("--timestamp-column", default=None)
    parser.add_argument("--turbine-column", default=None)
    parser.add_argument("--comment-prefix", default=None)
    parser.add_argument("--assume-timezone", default=None)
    parser.add_argument("--events", nargs="*", default=[], help="Event/status CSV files")
    parser.add_argument("--event-timestamp-column", default=None)
    parser.add_argument("--event-category-columns", nargs="*", default=[])
    parser.add_argument("--event-code-column", default=None)
    parser.add_argument("--gearbox-event-codes", nargs="*", default=[])
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    scada_paths = [Path(p) for p in args.scada]
    event_paths = [Path(p) for p in args.events]
    if scada_paths and args.timestamp_column is None:
        parser.error("--timestamp-column is required when --scada files are given")

    scada = census_scada(
        scada_paths,
        args.timestamp_column or "",
        args.turbine_column,
        args.comment_prefix,
        args.assume_timezone,
    )
    events = census_events(
        event_paths,
        args.comment_prefix,
        args.event_timestamp_column,
        args.event_category_columns,
        args.event_code_column,
    )
    report = {
        "banner": (
            "PHASE 0.5 DATASET CENSUS — FACTS ONLY. No cleaning, no judgment, "
            "no narrative, no inferred labels. Read-only over its inputs."
        ),
        "generated_at_utc": datetime.now(tz=UTC).isoformat(),
        "arguments": {k: v for k, v in vars(args).items()},
        "scada_files": scada,
        "event_files": events,
        "confirmed_gearbox_failure_events": gearbox_event_count(
            events,
            event_paths,
            args.comment_prefix,
            args.event_code_column,
            args.gearbox_event_codes,
        ),
    }
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Census written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
