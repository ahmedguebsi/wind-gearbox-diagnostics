"""Phase 0.5 dataset census — READ-ONLY, FACTS ONLY (PROJECT.md §7.5).

Discovers and classifies the files in an export folder, then censuses the
source CSVs. Produces the JSON evidence for docs/DATASET_DUE_DILIGENCE.md.

No cleaning, no judgment, no narrative, no inferred labels. Anything that
would require a definition the author has not supplied is emitted as
"UNKNOWN — requires confirmation". Keyword hits are emitted as CANDIDATES
FOR AUTHOR REVIEW, never as designations. Inputs are hashed before and after
the run and the equality is recorded, so read-only behaviour is evidenced.

Greenbyte export shape (verified against the file headers, not assumed):
nine ``#`` comment lines precede the column header on row 10. In
Turbine_Data files that header row is itself prefixed with ``# ``, so a
naive ``comment='#'`` read would silently consume the header — this module
skips exactly nine lines and parses row 10 explicitly. Missing/erroneous
values are the literal string ``NaN``.

Usage (from the repository root):

    uv run --project backend python scripts/dataset_census.py \
        --folder <export folder> --output census.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

UNKNOWN = "UNKNOWN — requires confirmation"
LOW_VARIANCE_STD = 1e-6
HEADER_COMMENT_LINES = 9
CHUNK_ROWS = 10_000
MAX_DISTINCT_TRACKED = 200

#: Author-specified keyword flags. Matches are candidates for review only.
KEYWORDS = (
    "gearbox",
    "gear",
    "oil",
    "bearing",
    "lubrication",
    "replacement",
    "repair",
    "service",
)

#: Free-text status fields to keyword-search and inventory verbatim, where present.
FREE_TEXT_FIELDS = ("Message", "Comment", "Service comment")

#: Column-name keywords used to group candidate channels. Grouping is a
#: reading aid; designating which column IS a canonical variable is a
#: mapping decision (M-07), never a census output.
THERMAL_TARGET_KEYWORDS = ("gear oil", "gearbox oil", "gear bearing", "gearbox bearing")
PREDICTOR_KEYWORDS = (
    "wind speed",
    "rotor speed",
    "generator rpm",
    "gearbox speed",
    "power",
    "pitch",
    "blade angle",
    "ambient",
    "nacelle temperature",
)


# --------------------------------------------------------------------------
# Inventory and provenance
# --------------------------------------------------------------------------


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


#: Files the author has classified as their own derived artefacts
#: (2026-08-11). Inventoried and hashed for provenance; never read.
AUTHOR_DERIVED_FILES = {
    "data_dictionary_2020.csv",
    "data_dictionary_turbine_5.csv",
    "untitled-1.txt",
}


def classify(path: Path) -> str:
    """Classify a file by name/extension. Never infers from content."""
    name, suffix = path.name.lower(), path.suffix.lower()
    if suffix == ".csv" and name.startswith("turbine_data_"):
        return "SOURCE_SCADA"
    if suffix == ".csv" and name.startswith("status_"):
        return "SOURCE_STATUS"
    if name in AUTHOR_DERIVED_FILES:
        return "EXCLUDED_AUTHOR_DERIVED"
    if suffix in {".xlsx", ".xls", ".md", ".py"}:
        return "EXCLUDED_DERIVED"
    return "UNCLASSIFIED_REQUIRES_AUTHOR_DECISION"


#: Directory names that are tooling/environment noise rather than dataset
#: content. Their contents are counted and reported, never itemised.
SKIPPED_DIR_NAMES = {"__pycache__", "site-packages", "node_modules"}


def is_environment_noise(path: Path, folder: Path) -> bool:
    """True for files under a dot-directory or a known tooling directory."""
    return any(
        part.startswith(".") or part in SKIPPED_DIR_NAMES
        for part in path.relative_to(folder).parts[:-1]
    )


def summarise_skipped(folder: Path) -> dict[str, Any]:
    """Aggregate (never itemise) files skipped as environment noise."""
    roots: dict[str, dict[str, int]] = {}
    for path in folder.rglob("*"):
        if path.is_file() and is_environment_noise(path, folder):
            root = path.relative_to(folder).parts[0]
            entry = roots.setdefault(root, {"n_files": 0, "size_bytes": 0})
            entry["n_files"] += 1
            entry["size_bytes"] += path.stat().st_size
    return {
        "note": (
            "Tooling/environment directories present in the folder. Counted for "
            "completeness; not dataset content, not hashed, not read."
        ),
        "directories": roots,
    }


def inventory(folder: Path) -> list[dict[str, Any]]:
    entries = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or is_environment_noise(path, folder):
            continue
        classification = classify(path)
        entries.append(
            {
                "name": str(path.relative_to(folder)),
                "classification": classification,
                "sha256": sha256_of(path),
                "size_bytes": path.stat().st_size,
                "modified_utc": datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat(),
                "content_read_by_census": classification.startswith("SOURCE_"),
            }
        )
    return entries


_HEADER_PATTERNS = {
    "exported_by": re.compile(r"^#\s*(This file was exported.*)$"),
    "turbine": re.compile(r"^#\s*Turbine:\s*(.*)$"),
    "turbine_type": re.compile(r"^#\s*Turbine type:\s*(.*)$"),
    "time_zone": re.compile(r"^#\s*Time zone:\s*(.*)$"),
    "time_interval": re.compile(r"^#\s*Time interval:\s*(.*)$"),
    "sum_production": re.compile(r"^#\s*(.*Sum production:.*)$"),
    "missing_value_note": re.compile(r"^#\s*(Data that is missing.*)$"),
}


#: Encodings tried in order. UTF-8 is attempted STRICTLY first: silent
#: character replacement would corrupt degree signs and vendor text without
#: any trace, so a file that is not valid UTF-8 falls back explicitly and the
#: encoding actually used is recorded in the output.
ENCODING_CANDIDATES = ("utf-8", "cp1252", "latin-1")


def detect_encoding(path: Path) -> str:
    """First candidate encoding that decodes the whole file strictly."""
    raw = path.read_bytes()
    for encoding in ENCODING_CANDIDATES:
        try:
            raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        return encoding
    raise SystemExit(f"Cannot decode {path} with any of {ENCODING_CANDIDATES}")


def header_provenance(path: Path) -> dict[str, Any]:
    """Parse the nine leading ``#`` lines and the row-10 column header.

    Every field is reported as *declared by the file*; nothing is assumed.
    """
    encoding = detect_encoding(path)
    with path.open("r", encoding=encoding) as fh:
        lines = [fh.readline().rstrip("\n") for _ in range(HEADER_COMMENT_LINES + 1)]
    comment_lines = lines[:HEADER_COMMENT_LINES]
    header_line = lines[HEADER_COMMENT_LINES]
    declared: dict[str, Any] = {key: None for key in _HEADER_PATTERNS}
    for line in comment_lines:
        for key, pattern in _HEADER_PATTERNS.items():
            match = pattern.match(line)
            if match and declared[key] is None:
                declared[key] = match.group(1).strip()
    header_prefixed = header_line.startswith("#")
    raw_columns = [
        str(c)
        for c in pd.read_csv(
            path,
            skiprows=HEADER_COMMENT_LINES,
            nrows=0,
            header=0,
            encoding=encoding,
        ).columns
    ]
    columns = list(raw_columns)
    if header_prefixed and columns:
        columns[0] = re.sub(r"^#\s*", "", columns[0])
    return {
        "comment_lines_verbatim": comment_lines,
        "declared": declared,
        "header_row_number_1_indexed": HEADER_COMMENT_LINES + 1,
        "header_row_is_comment_prefixed": header_prefixed,
        "columns": columns,
        # As written in the file — what `usecols` must match.
        "columns_raw": raw_columns,
        "n_columns": len(columns),
        "encoding_detected": encoding,
    }


def _strip_header_prefix(frame: pd.DataFrame) -> pd.DataFrame:
    """Drop the leading ``# `` from the first column name (Turbine_Data files
    carry their header row as a comment line)."""
    first = list(frame.columns)[:1]
    return frame.rename(columns={c: re.sub(r"^#\s*", "", str(c)) for c in first})


def _read_source(path: Path, prov: dict[str, Any], **kwargs: Any) -> Any:
    """Read a source CSV honouring the nine-comment-line header offset.

    With ``chunksize`` this returns a reader; the caller strips the header
    prefix per chunk via :func:`_strip_header_prefix`.
    """
    result = pd.read_csv(
        path,
        skiprows=HEADER_COMMENT_LINES,
        header=0,
        encoding=prov.get("encoding_detected", "utf-8"),
        **kwargs,
    )
    if "chunksize" in kwargs:
        return result
    if prov["header_row_is_comment_prefixed"]:
        result = _strip_header_prefix(result)
    return result


# --------------------------------------------------------------------------
# Status / event inventory (priority output)
# --------------------------------------------------------------------------


def _parse_duration(value: str) -> pd.Timedelta | None:
    if value in {"", "-"}:
        return None
    try:
        parsed = pd.to_timedelta(value)
    except (ValueError, TypeError):
        return None
    return None if pd.isna(parsed) else parsed


def status_inventory(
    paths: list[Path], provenance: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Full status/event inventory. Returns (inventory, keyword_candidates, notes)."""
    notes: list[str] = []
    code_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "messages_verbatim": Counter(),
            "occurrences": 0,
            "turbines": set(),
            "total_duration_seconds": 0.0,
            "rows_with_duration": 0,
            "rows_without_duration": 0,
            "first_occurrence": None,
            "last_occurrence": None,
        }
    )
    status_values: Counter[str] = Counter()
    iec_counts: Counter[str] = Counter()
    iec_duration: dict[str, float] = defaultdict(float)
    free_text: dict[str, Counter[str]] = {f: Counter() for f in FREE_TEXT_FIELDS}
    other_categorical: dict[str, Counter[str]] = defaultdict(Counter)
    completeness = {
        "timestamp_end": Counter(),
        "duration": Counter(),
    }
    candidates: list[dict[str, Any]] = []
    header_variants: Counter[str] = Counter()
    total_rows = 0
    per_file: list[dict[str, Any]] = []

    for path in paths:
        prov = provenance[path.name]
        turbine = prov["declared"].get("turbine") or UNKNOWN
        # dtype=str + keep_default_na=False preserves "-" and "" exactly as written.
        frame = _read_source(path, prov, dtype=str, keep_default_na=False)
        columns = [str(c) for c in frame.columns]
        header_variants[" | ".join(columns)] += 1
        total_rows += len(frame)
        per_file.append(
            {
                "file": path.name,
                "turbine_declared": turbine,
                "n_rows": len(frame),
                "columns": columns,
            }
        )

        for field in ("Timestamp end", "Duration"):
            key = field.lower().replace(" ", "_")
            if field in frame.columns:
                series = frame[field]
                completeness[key]["populated"] += int((~series.isin(["-", ""])).sum())
                completeness[key]["blank_dash"] += int((series == "-").sum())
                completeness[key]["blank_empty"] += int((series == "").sum())
            else:
                notes.append(f"{path.name}: column {field!r} absent")

        for row in frame.itertuples(index=False):
            record = dict(zip(columns, row, strict=False))
            code = str(record.get("Code", "")).strip()
            message = str(record.get("Message", ""))
            start = str(record.get("Timestamp start", ""))
            duration = _parse_duration(str(record.get("Duration", "")))

            stats = code_stats[code]
            stats["messages_verbatim"][message] += 1
            stats["occurrences"] += 1
            stats["turbines"].add(turbine)
            if duration is not None:
                stats["total_duration_seconds"] += duration.total_seconds()
                stats["rows_with_duration"] += 1
            else:
                stats["rows_without_duration"] += 1
            if start not in {"", "-"}:
                if stats["first_occurrence"] is None or start < stats["first_occurrence"]:
                    stats["first_occurrence"] = start
                if stats["last_occurrence"] is None or start > stats["last_occurrence"]:
                    stats["last_occurrence"] = start

            status_values[str(record.get("Status", ""))] += 1
            iec = str(record.get("IEC category", ""))
            iec_counts[iec] += 1
            if duration is not None:
                iec_duration[iec] += duration.total_seconds()

            for field in FREE_TEXT_FIELDS:
                if field in record:
                    value = str(record[field]).strip()
                    if value not in {"", "-"}:
                        free_text[field][value] += 1
            for field in ("Service contract category",):
                if field in record:
                    other_categorical[field][str(record[field])] += 1

            searched = [f for f in FREE_TEXT_FIELDS if f in record]
            hits = sorted(
                {
                    keyword
                    for field in searched
                    for keyword in KEYWORDS
                    if keyword in str(record[field]).lower()
                }
            )
            if hits:
                candidates.append(
                    {
                        "file": path.name,
                        "turbine_declared": turbine,
                        "matched_keywords": hits,
                        "matched_fields": [
                            f for f in searched if any(k in str(record[f]).lower() for k in hits)
                        ],
                        "row_verbatim": {k: str(v) for k, v in record.items()},
                    }
                )

    codes_sorted = sorted(
        (
            {
                "code": code,
                "messages_verbatim": dict(stats["messages_verbatim"]),
                "occurrences": stats["occurrences"],
                "turbines_affected": sorted(stats["turbines"]),
                "n_turbines_affected": len(stats["turbines"]),
                "total_duration_seconds": round(stats["total_duration_seconds"], 3),
                "total_duration_hours": round(stats["total_duration_seconds"] / 3600, 3),
                "rows_with_duration": stats["rows_with_duration"],
                "rows_without_duration": stats["rows_without_duration"],
                "first_occurrence": stats["first_occurrence"],
                "last_occurrence": stats["last_occurrence"],
            }
            for code, stats in code_stats.items()
        ),
        key=lambda d: d["total_duration_seconds"],
        reverse=True,
    )

    free_text_out: dict[str, Any] = {}
    for field in FREE_TEXT_FIELDS:
        present = any(field in f["columns"] for f in per_file)
        free_text_out[field] = {
            "present_in_files": present,
            "distinct_non_empty_verbatim": dict(free_text[field].most_common()),
            "n_distinct_non_empty": len(free_text[field]),
            "total_non_empty_rows": sum(free_text[field].values()),
        }
        if not present:
            free_text_out[field]["note"] = (
                f"Column {field!r} does not exist in these status exports — reported "
                "as absent, not substituted."
            )

    inventory_out = {
        "files": per_file,
        "total_rows": total_rows,
        "header_variants": dict(header_variants),
        "codes_by_total_duration_desc": codes_sorted,
        "n_distinct_codes": len(codes_sorted),
        "status_values": dict(status_values.most_common()),
        "iec_categories": {
            value: {
                "count": count,
                "total_duration_hours": round(iec_duration.get(value, 0.0) / 3600, 3),
            }
            for value, count in iec_counts.most_common()
        },
        "free_text_fields": free_text_out,
        "other_categorical_fields": {
            field: dict(counter.most_common()) for field, counter in other_categorical.items()
        },
        "completeness": {field: dict(counter) for field, counter in completeness.items()},
    }
    return inventory_out, candidates, notes


# --------------------------------------------------------------------------
# SCADA census (streamed)
# --------------------------------------------------------------------------


class _ColumnAccumulator:
    """Streaming per-column facts (Welford chunk-merge for mean/std)."""

    def __init__(self) -> None:
        self.n_total = 0
        self.n_null = 0
        self.numeric = False
        self.count = 0
        self.mean = 0.0
        self.m2 = 0.0
        self.min: float | None = None
        self.max: float | None = None
        self.distinct: set[str] = set()
        self.distinct_overflow = False
        self.first_valid: str | None = None
        self.last_valid: str | None = None

    def update(self, series: pd.Series, timestamps: pd.Series) -> None:
        self.n_total += len(series)
        null_mask = series.isna()
        self.n_null += int(null_mask.sum())
        valid_times = timestamps[~null_mask.to_numpy()]
        if len(valid_times):
            first, last = str(valid_times.iloc[0]), str(valid_times.iloc[-1])
            self.first_valid = first if self.first_valid is None else min(self.first_valid, first)
            self.last_valid = last if self.last_valid is None else max(self.last_valid, last)
        clean = series.dropna()
        if pd.api.types.is_numeric_dtype(series):
            self.numeric = True
            if clean.empty:
                return
            n_b = len(clean)
            mean_b = float(clean.mean())
            m2_b = float(((clean - mean_b) ** 2).sum())
            if self.count == 0:
                self.count, self.mean, self.m2 = n_b, mean_b, m2_b
            else:
                delta = mean_b - self.mean
                total = self.count + n_b
                self.m2 += m2_b + delta * delta * self.count * n_b / total
                self.mean += delta * n_b / total
                self.count = total
            lo, hi = float(clean.min()), float(clean.max())
            self.min = lo if self.min is None else min(self.min, lo)
            self.max = hi if self.max is None else max(self.max, hi)
        elif not self.distinct_overflow:
            for value in clean.astype(str).unique():
                self.distinct.add(value)
                if len(self.distinct) > MAX_DISTINCT_TRACKED:
                    self.distinct_overflow = True
                    break

    def facts(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "null_fraction": round(self.n_null / self.n_total, 6) if self.n_total else 0.0,
            "n_non_null": self.n_total - self.n_null,
            "first_non_null_timestamp": self.first_valid,
            "last_non_null_timestamp": self.last_valid,
        }
        if self.numeric:
            std = (self.m2 / (self.count - 1)) ** 0.5 if self.count > 1 else None
            out.update(
                {
                    "kind": "numeric",
                    "min": self.min,
                    "max": self.max,
                    "mean": round(self.mean, 6) if self.count else None,
                    "std": round(std, 9) if std is not None else None,
                }
            )
            out["constant"] = bool(self.count and self.min == self.max)
            out["low_variance"] = bool(
                not out["constant"] and std is not None and std < LOW_VARIANCE_STD
            )
        else:
            out.update(
                {
                    "kind": "non_numeric",
                    "n_distinct_tracked": len(self.distinct),
                    "distinct_truncated": self.distinct_overflow,
                    "constant": bool(not self.distinct_overflow and len(self.distinct) <= 1),
                    "low_variance": False,
                }
            )
        return out


def _channel_candidates(columns: list[str], keywords: tuple[str, ...]) -> list[str]:
    return [c for c in columns if any(k in c.lower() for k in keywords)]


def scada_census(
    paths: list[Path], provenance: dict[str, dict[str, Any]], timestamp_column: str
) -> list[dict[str, Any]]:
    results = []
    for path in paths:
        prov = provenance[path.name]
        accumulators: dict[str, _ColumnAccumulator] = defaultdict(_ColumnAccumulator)
        timestamps: list[pd.Series] = []
        n_rows = 0
        reader = _read_source(path, prov, chunksize=CHUNK_ROWS, low_memory=False)
        for raw_chunk in reader:
            chunk = (
                _strip_header_prefix(raw_chunk)
                if prov["header_row_is_comment_prefixed"]
                else raw_chunk
            )
            n_rows += len(chunk)
            ts = pd.to_datetime(chunk[timestamp_column], errors="coerce")
            timestamps.append(ts)
            for column in chunk.columns:
                accumulators[str(column)].update(chunk[column], ts)
        all_ts = pd.concat(timestamps).sort_values() if timestamps else pd.Series(dtype=object)
        valid = all_ts.dropna()

        ts_facts: dict[str, Any] = {
            "column": timestamp_column,
            "unparseable_count": int(all_ts.isna().sum()),
            "min": None if valid.empty else valid.iloc[0].isoformat(),
            "max": None if valid.empty else valid.iloc[-1].isoformat(),
            "duplicate_timestamp_count": int(valid.duplicated().sum()),
        }
        if len(valid) >= 2:
            deltas = valid.diff().dropna()
            modal = deltas.mode().iloc[0]
            irregular = deltas[deltas != modal]
            ts_facts["modal_interval"] = str(modal)
            ts_facts["interval_value_counts_top10"] = {
                str(k): int(v) for k, v in deltas.value_counts().head(10).items()
            }
            ts_facts["irregular_interval_count"] = len(irregular)
            gaps = deltas[deltas > modal]
            ts_facts["gap_count_above_modal_interval"] = len(gaps)
            ts_facts["largest_gaps"] = [
                {"ends_at": valid.loc[idx].isoformat(), "duration": str(gap)}
                for idx, gap in gaps.sort_values(ascending=False).head(10).items()
            ]

        columns = [str(c) for c in accumulators]
        per_column = {name: acc.facts() for name, acc in accumulators.items()}
        results.append(
            {
                "file": path.name,
                "turbine_declared": prov["declared"].get("turbine") or UNKNOWN,
                "turbine_type_declared": prov["declared"].get("turbine_type") or UNKNOWN,
                "time_zone_declared": prov["declared"].get("time_zone") or UNKNOWN,
                "time_interval_declared": prov["declared"].get("time_interval") or UNKNOWN,
                "n_rows": n_rows,
                "n_columns": len(columns),
                "timestamps": ts_facts,
                "dst": {
                    "status": "not applicable — file header declares UTC",
                    "declared_time_zone": prov["declared"].get("time_zone") or UNKNOWN,
                    "source": "file header comment line (declared, not assumed)",
                },
                "per_column": per_column,
                "constant_columns": sorted(c for c, f in per_column.items() if f.get("constant")),
                "low_variance_columns": sorted(
                    c for c, f in per_column.items() if f.get("low_variance")
                ),
                "channel_candidates": {
                    "note": (
                        "Name-keyword groupings to aid review. Designating which column "
                        "IS a canonical variable is a mapping decision (M-07), not a "
                        "census output."
                    ),
                    "thermal_target_candidates": {
                        c: per_column[c]
                        for c in _channel_candidates(columns, THERMAL_TARGET_KEYWORDS)
                    },
                    "upstream_predictor_candidates": {
                        c: per_column[c] for c in _channel_candidates(columns, PREDICTOR_KEYWORDS)
                    },
                },
            }
        )
    return results


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--scada-timestamp-column",
        default="Date and time",
        help="Column header (row 10) holding the SCADA timestamp",
    )
    parser.add_argument("--skip-scada", action="store_true", help="Status inventory only")
    args = parser.parse_args(argv)

    folder = Path(args.folder)
    if not folder.is_dir():
        parser.error(f"{folder} is not a directory")
    output_path = Path(args.output).resolve()
    if folder.resolve() in output_path.parents:
        parser.error(
            "--output must not be inside --folder: writing the census into the "
            "censused folder would modify it and make the inventory self-referential"
        )

    files = inventory(folder)
    by_class: dict[str, list[Path]] = defaultdict(list)
    for entry in files:
        by_class[entry["classification"]].append(folder / entry["name"])

    source_paths = by_class["SOURCE_SCADA"] + by_class["SOURCE_STATUS"]
    provenance = {p.name: header_provenance(p) for p in source_paths}

    status_out, candidates, notes = status_inventory(by_class["SOURCE_STATUS"], provenance)
    scada_out = (
        []
        if args.skip_scada
        else scada_census(by_class["SOURCE_SCADA"], provenance, args.scada_timestamp_column)
    )

    declared_zones = {name: prov["declared"].get("time_zone") for name, prov in provenance.items()}
    report: dict[str, Any] = {
        "banner": (
            "PHASE 0.5 DATASET CENSUS — FACTS ONLY. No cleaning, no judgment, no "
            "narrative, no inferred labels. Read-only over its inputs. Keyword hits "
            "are CANDIDATES FOR AUTHOR REVIEW, not designations."
        ),
        "generated_at_utc": datetime.now(tz=UTC).isoformat(),
        "folder": str(folder),
        "inventory": files,
        "unclassified_requiring_author_decision": [
            e["name"]
            for e in files
            if e["classification"] == "UNCLASSIFIED_REQUIRES_AUTHOR_DECISION"
        ],
        "timezone": {
            "declared_per_file": declared_zones,
            "distinct_declared_values": sorted({z for z in declared_zones.values() if z}),
            "source": "Greenbyte header comment line 5 of each file (declared, not assumed)",
        },
        "header_provenance": provenance,
        "status_inventory": status_out,
        "keyword_candidates": {
            "note": (
                "CANDIDATES FOR AUTHOR REVIEW — not designations. No inference, "
                "ranking, or interpretation is applied."
            ),
            "keywords": list(KEYWORDS),
            "fields_searched": list(FREE_TEXT_FIELDS),
            "n_matching_rows": len(candidates),
            "matches": candidates,
            "truncated": False,
        },
        "scada_census": scada_out,
        "coverage_note": {
            "years_held": ["2020"],
            "months": 12,
            "note": (
                "Twelve months only — on the seasonal-coverage warning boundary in "
                "PROJECT.md §14 (WARNING is emitted when the training window spans "
                "< 12 months; a 12-month total means the training split will be "
                "shorter than 12 months). Years 2016-2022 are available from the same "
                "Zenodo record. Acquiring further years is an author decision, "
                "pending before splitting."
            ),
        },
        "census_notes": notes,
    }

    after = {e["name"]: sha256_of(folder / e["name"]) for e in files}
    report["read_only_verification"] = {
        "inputs_unchanged": all(e["sha256"] == after[e["name"]] for e in files),
        "method": "SHA-256 of every inventoried file compared before and after the run",
    }

    output_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"Census written to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
