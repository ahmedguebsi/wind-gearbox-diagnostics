"""Complete multi-year status vocabulary inventory — READ-ONLY, FACTS ONLY.

Inventories the ENTIRE status vocabulary across every supplied year folder.
There is no code filter and no keyword filter anywhere in the selection path:
every distinct code that appears anywhere is reported. A keyword index over
the finished inventory is provided as a clearly-labelled convenience section
— it indexes the full list, it never restricts it.

Also computes, for every status occurrence, how much continuous preceding
SCADA data exists on the affected turbine with the thermal-candidate channels
non-null. Continuity is evaluated across year boundaries (files are
concatenated per turbine), so a run may exceed one year.

No designations, no rankings, no inferred labels. Anything requiring an
author definition is emitted as "UNKNOWN — requires confirmation".

Outputs:
  <output>.json  the inventory (deliverable)
  <output>.csv   per-occurrence detail for EVERY status row, no truncation

Usage:

    uv run --project backend python scripts/status_vocabulary.py \
        --folder <2016 folder> --folder <2017 folder> ... \
        --output <path outside those folders>/status_vocabulary
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset_census import (
    UNKNOWN,
    _parse_duration,
    _read_source,
    classify,
    header_provenance,
    is_environment_noise,
    sha256_of,
    summarise_skipped,
)

LONG_EVENT_HOURS = 6.0

#: Convenience index only — applied to the finished inventory, never to
#: selection. Any vocabulary guess would risk hiding events logged in
#: wording that contains no gearbox term, so nothing is filtered by it.
GEARBOX_INDEX_TERMS = (
    "gear",
    "gearbox",
    "oil",
    "bearing",
    "lubric",
    "hss",
    "high speed shaft",
    "planet",
    "particle",
    "filter",
    "temp",
)


def _is_thermal_candidate(column: str) -> bool:
    """Base (non-aggregate) gear-thermal channel by name.

    Name-based grouping only: designating which column IS a canonical
    thermal target is a mapping decision (M-07), never a census output.
    """
    low = column.lower()
    if not ("gear" in low and "temp" in low):
        return False
    return not any(agg in low for agg in (", max", ", min", ", std", "standard deviation"))


# --------------------------------------------------------------------------
# SCADA coverage (timestamp + thermal-candidate columns only, for speed)
# --------------------------------------------------------------------------


class TurbineCoverage:
    """Covered-sample timeline for one turbine across all supplied years."""

    def __init__(self) -> None:
        self._covered: list[pd.Series] = []
        self.columns_used: dict[str, list[str]] = {}
        self.per_year: dict[str, dict[str, Any]] = {}
        self.timestamps: np.ndarray = np.array([], dtype="datetime64[ns]")
        self.run_start: np.ndarray = np.array([], dtype="datetime64[ns]")

    def add_year(self, year: str, covered: pd.Series, columns: list[str], facts: dict) -> None:
        self._covered.append(covered)
        self.columns_used[year] = columns
        self.per_year[year] = facts

    def finalise(self) -> None:
        if not self._covered:
            return
        allts = pd.concat(self._covered).sort_values().drop_duplicates()
        self.timestamps = allts.to_numpy()
        if len(self.timestamps) == 0:
            return
        deltas = np.diff(self.timestamps)
        modal = pd.Series(deltas).mode()
        step = modal.iloc[0] if len(modal) else np.timedelta64(10, "m")
        breaks = np.concatenate([[True], deltas > step])
        run_ids = np.cumsum(breaks) - 1
        starts = self.timestamps[breaks]
        self.run_start = starts[run_ids]

    def preceding_hours(self, when: pd.Timestamp) -> float | None:
        """Continuous covered history immediately before ``when`` (hours)."""
        if len(self.timestamps) == 0 or pd.isna(when):
            return None
        idx = int(np.searchsorted(self.timestamps, np.datetime64(when), side="right")) - 1
        if idx < 0:
            return 0.0
        span = self.timestamps[idx] - self.run_start[idx]
        return round(float(span / np.timedelta64(1, "h")), 3)


def build_coverage(
    scada_files: list[tuple[str, Path]],
) -> tuple[dict[str, TurbineCoverage], dict[str, Any]]:
    coverage: dict[str, TurbineCoverage] = defaultdict(TurbineCoverage)
    year_facts: dict[str, Any] = defaultdict(dict)
    for year, path in scada_files:
        prov = header_provenance(path)
        turbine = prov["declared"].get("turbine") or UNKNOWN
        columns = prov["columns"]
        timestamp_col = columns[0]
        thermal = [c for c in columns if _is_thermal_candidate(c)]
        # usecols must match the header as written in the file, which for
        # Turbine_Data carries a "# " prefix on the first column.
        raw_selection = [prov["columns_raw"][columns.index(c)] for c in [timestamp_col, *thermal]]
        frame = _read_source(path, prov, usecols=raw_selection, low_memory=False)
        frame = frame.rename(
            columns=dict(zip(raw_selection, [timestamp_col, *thermal], strict=True))
        )
        ts = pd.to_datetime(frame[timestamp_col], errors="coerce")
        valid = ts.notna()
        if thermal:
            valid &= frame[thermal].notna().all(axis=1)
        covered = ts[valid]
        facts = {
            "file": path.name,
            "n_rows": len(frame),
            "first_timestamp": None if ts.dropna().empty else ts.min().isoformat(),
            "last_timestamp": None if ts.dropna().empty else ts.max().isoformat(),
            "thermal_candidate_columns": thermal,
            "n_covered_samples": int(valid.sum()),
            "covered_fraction": round(float(valid.mean()), 6) if len(frame) else 0.0,
            "per_column_null_fraction": {
                c: round(float(frame[c].isna().mean()), 6) for c in thermal
            },
            "declared_time_zone": prov["declared"].get("time_zone") or UNKNOWN,
            "declared_time_interval": prov["declared"].get("time_interval") or UNKNOWN,
        }
        coverage[turbine].add_year(year, covered, thermal, facts)
        year_facts[year][turbine] = facts
    for cov in coverage.values():
        cov.finalise()
    return dict(coverage), dict(year_facts)


# --------------------------------------------------------------------------
# Status vocabulary
# --------------------------------------------------------------------------


def _new_code_record() -> dict[str, Any]:
    return {
        "messages_verbatim": Counter(),
        "status_tiers": Counter(),
        "iec_categories": Counter(),
        "service_contract_categories": Counter(),
        "occurrences": 0,
        "turbines": set(),
        "years": set(),
        "total_duration_seconds": 0.0,
        "longest_single_seconds": 0.0,
        "longest_single_row": None,
        "rows_with_duration": 0,
        "rows_without_duration": 0,
        "first_occurrence": None,
        "last_occurrence": None,
        "preceding_hours": [],
    }


def inventory_status(
    status_files: list[tuple[str, Path]],
    coverage: dict[str, TurbineCoverage],
) -> dict[str, Any]:
    codes: dict[str, dict[str, Any]] = defaultdict(_new_code_record)
    iec_counts: Counter[str] = Counter()
    iec_seconds: dict[str, float] = defaultdict(float)
    scc_counts: Counter[str] = Counter()
    scc_seconds: dict[str, float] = defaultdict(float)
    header_variants: Counter[str] = Counter()
    turbine_year: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"counts": Counter(), "seconds": defaultdict(float), "rows": 0}
    )
    long_events: list[dict[str, Any]] = []
    per_occurrence: list[dict[str, Any]] = []
    year_span: dict[str, dict[str, str | None]] = defaultdict(lambda: {"first": None, "last": None})
    files_meta: list[dict[str, Any]] = []

    for year, path in status_files:
        prov = header_provenance(path)
        turbine = prov["declared"].get("turbine") or UNKNOWN
        frame = _read_source(path, prov, dtype=str, keep_default_na=False)
        columns = [str(c) for c in frame.columns]
        header_variants[" | ".join(columns)] += 1
        files_meta.append(
            {
                "year_folder": year,
                "file": path.name,
                "turbine_declared": turbine,
                "n_rows": len(frame),
                "columns": columns,
                "declared_time_interval": prov["declared"].get("time_interval") or UNKNOWN,
                "declared_time_zone": prov["declared"].get("time_zone") or UNKNOWN,
                "declared_sum_production": prov["declared"].get("sum_production") or UNKNOWN,
            }
        )
        cov = coverage.get(turbine)

        for row in frame.itertuples(index=False):
            record = {k: str(v) for k, v in zip(columns, row, strict=False)}
            code = record.get("Code", "").strip()
            start_raw = record.get("Timestamp start", "")
            start = pd.to_datetime(start_raw, errors="coerce")
            duration = _parse_duration(record.get("Duration", ""))
            seconds = duration.total_seconds() if duration is not None else 0.0
            status_tier = record.get("Status", "")
            iec = record.get("IEC category", "")
            scc = record.get("Service contract category", record.get("Service comment", ""))
            preceding = cov.preceding_hours(start) if cov is not None else None

            rec = codes[code]
            rec["messages_verbatim"][record.get("Message", "")] += 1
            rec["status_tiers"][status_tier] += 1
            rec["iec_categories"][iec] += 1
            rec["service_contract_categories"][scc] += 1
            rec["occurrences"] += 1
            rec["turbines"].add(turbine)
            rec["years"].add(year)
            if duration is not None:
                rec["total_duration_seconds"] += seconds
                rec["rows_with_duration"] += 1
                if seconds > rec["longest_single_seconds"]:
                    rec["longest_single_seconds"] = seconds
                    rec["longest_single_row"] = {
                        "year_folder": year,
                        "turbine_declared": turbine,
                        "row_verbatim": record,
                    }
            else:
                rec["rows_without_duration"] += 1
            if start_raw not in {"", "-"}:
                if rec["first_occurrence"] is None or start_raw < rec["first_occurrence"]:
                    rec["first_occurrence"] = start_raw
                if rec["last_occurrence"] is None or start_raw > rec["last_occurrence"]:
                    rec["last_occurrence"] = start_raw
                span = year_span[year]
                if span["first"] is None or start_raw < span["first"]:
                    span["first"] = start_raw
                if span["last"] is None or start_raw > span["last"]:
                    span["last"] = start_raw
            if preceding is not None:
                rec["preceding_hours"].append(preceding)

            iec_counts[iec] += 1
            iec_seconds[iec] += seconds
            scc_counts[scc] += 1
            scc_seconds[scc] += seconds

            ty = turbine_year[(turbine, year)]
            ty["counts"][status_tier] += 1
            ty["seconds"][status_tier] += seconds
            ty["rows"] += 1

            if status_tier in {"Stop", "Warning"} and seconds > LONG_EVENT_HOURS * 3600:
                long_events.append(
                    {
                        "year_folder": year,
                        "turbine_declared": turbine,
                        "duration_hours": round(seconds / 3600, 3),
                        "preceding_covered_scada_hours": preceding,
                        "row_verbatim": record,
                    }
                )

            per_occurrence.append(
                {
                    "year_folder": year,
                    "turbine": turbine,
                    "code": code,
                    "message": record.get("Message", ""),
                    "status": status_tier,
                    "iec_category": iec,
                    "service_contract_category": scc,
                    "timestamp_start": start_raw,
                    "timestamp_end": record.get("Timestamp end", ""),
                    "duration_raw": record.get("Duration", ""),
                    "duration_hours": round(seconds / 3600, 4) if duration is not None else "",
                    "preceding_covered_scada_hours": "" if preceding is None else preceding,
                }
            )

    code_list = []
    for code, rec in codes.items():
        preceding = rec["preceding_hours"]
        code_list.append(
            {
                "code": code,
                "messages_verbatim": dict(rec["messages_verbatim"]),
                "status_tiers": dict(rec["status_tiers"]),
                "iec_categories": dict(rec["iec_categories"]),
                "service_contract_categories": dict(rec["service_contract_categories"]),
                "occurrences": rec["occurrences"],
                "turbines_affected": sorted(rec["turbines"]),
                "n_turbines_affected": len(rec["turbines"]),
                "years_present": sorted(rec["years"]),
                "total_duration_hours": round(rec["total_duration_seconds"] / 3600, 3),
                "longest_single_occurrence_hours": round(rec["longest_single_seconds"] / 3600, 3),
                "longest_single_occurrence": rec["longest_single_row"],
                "rows_with_duration": rec["rows_with_duration"],
                "rows_without_duration": rec["rows_without_duration"],
                "first_occurrence": rec["first_occurrence"],
                "last_occurrence": rec["last_occurrence"],
                "preceding_covered_scada_hours": {
                    "n_occurrences_measured": len(preceding),
                    "min": min(preceding) if preceding else None,
                    "median": round(float(np.median(preceding)), 3) if preceding else None,
                    "max": max(preceding) if preceding else None,
                    "n_with_at_least_30_days": sum(1 for h in preceding if h >= 720),
                    "n_with_zero": sum(1 for h in preceding if h == 0.0),
                    "note": (
                        "Continuous preceding samples on the affected turbine with all "
                        "thermal-candidate channels non-null; continuity spans year "
                        "boundaries. Per-occurrence values are in the companion CSV."
                    ),
                },
            }
        )
    code_list.sort(key=lambda d: d["total_duration_hours"], reverse=True)

    year_signature: dict[str, list[str]] = defaultdict(list)
    for entry in code_list:
        year_signature["|".join(entry["years_present"])].append(entry["code"])

    return {
        "files": files_meta,
        "header_variants": dict(header_variants),
        "total_status_rows": sum(f["n_rows"] for f in files_meta),
        "codes_by_total_duration_desc": code_list,
        "n_distinct_codes": len(code_list),
        "iec_category_taxonomy": {
            value: {
                "count": count,
                "total_duration_hours": round(iec_seconds[value] / 3600, 3),
            }
            for value, count in iec_counts.most_common()
        },
        "service_contract_category_taxonomy": {
            value: {
                "count": count,
                "total_duration_hours": round(scc_seconds[value] / 3600, 3),
            }
            for value, count in scc_counts.most_common()
        },
        "long_stop_or_warning_events": sorted(
            long_events, key=lambda d: d["duration_hours"], reverse=True
        ),
        "long_event_threshold_hours": LONG_EVENT_HOURS,
        "n_long_stop_or_warning_events": len(long_events),
        "per_turbine_year": [
            {
                "turbine": turbine,
                "year_folder": year,
                "total_rows": data["rows"],
                "counts_by_status": dict(data["counts"]),
                "duration_hours_by_status": {
                    k: round(v / 3600, 3) for k, v in data["seconds"].items()
                },
            }
            for (turbine, year), data in sorted(turbine_year.items())
        ],
        "code_year_presence_patterns": {
            signature: sorted(codes_in) for signature, codes_in in sorted(year_signature.items())
        },
        "status_row_timestamp_span_per_year_folder": dict(year_span),
    }, per_occurrence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", action="append", required=True, dest="folders")
    parser.add_argument("--output", required=True, help="Output path stem (no extension)")
    args = parser.parse_args(argv)

    folders = [Path(f) for f in args.folders]
    for folder in folders:
        if not folder.is_dir():
            parser.error(f"{folder} is not a directory")
    out_stem = Path(args.output).resolve()
    for folder in folders:
        if folder.resolve() in out_stem.parents:
            parser.error("--output must not be inside any --folder")

    inventory_rows: list[dict[str, Any]] = []
    status_files: list[tuple[str, Path]] = []
    scada_files: list[tuple[str, Path]] = []
    skipped: dict[str, Any] = {}
    for folder in folders:
        year = folder.name
        skipped_here = summarise_skipped(folder)
        if skipped_here["directories"]:
            skipped[year] = skipped_here
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or is_environment_noise(path, folder):
                continue
            classification = classify(path)
            inventory_rows.append(
                {
                    "year_folder": year,
                    "name": str(path.relative_to(folder)),
                    "classification": classification,
                    "sha256": sha256_of(path),
                    "size_bytes": path.stat().st_size,
                }
            )
            if classification == "SOURCE_STATUS":
                status_files.append((year, path))
            elif classification == "SOURCE_SCADA":
                scada_files.append((year, path))

    print(f"Building SCADA coverage from {len(scada_files)} files...", flush=True)
    coverage, scada_year_facts = build_coverage(scada_files)
    print(f"Inventorying {len(status_files)} status files...", flush=True)
    inventory, per_occurrence = inventory_status(status_files, coverage)

    gearbox_index = [
        entry["code"]
        for entry in inventory["codes_by_total_duration_desc"]
        if any(
            term in text.lower()
            for term in GEARBOX_INDEX_TERMS
            for text in entry["messages_verbatim"]
        )
    ]

    report = {
        "banner": (
            "COMPLETE STATUS VOCABULARY INVENTORY — FACTS ONLY. No code filter and "
            "no keyword filter is applied to selection: every distinct code that "
            "appears anywhere is reported. No designations, no rankings, no inferred "
            "labels. Read-only over its inputs."
        ),
        "generated_at_utc": datetime.now(tz=UTC).isoformat(),
        "folders": [str(f) for f in folders],
        "inventory": inventory_rows,
        "unclassified_requiring_author_decision": [
            f"{r['year_folder']}/{r['name']}"
            for r in inventory_rows
            if r["classification"] == "UNCLASSIFIED_REQUIRES_AUTHOR_DECISION"
        ],
        "environment_directories_skipped": skipped,
        "scada_coverage_per_year": scada_year_facts,
        "scada_coverage_method": {
            "definition": (
                "A sample counts as covered when its timestamp parses and every "
                "thermal-candidate channel in that file is non-null."
            ),
            "thermal_candidate_rule": (
                "column name contains both 'gear' and 'temp' and is not a Max/Min/"
                "StdDev aggregate — a name-based grouping, NOT a designation"
            ),
            "continuity": "runs are continuous across year-folder boundaries per turbine",
        },
        "status_vocabulary": inventory,
        "gearbox_term_index": {
            "note": (
                "CONVENIENCE INDEX ONLY — an index into the full inventory above, "
                "never a filter on it. Selection applied no keyword matching, because "
                "a gearbox failure may be logged in wording containing no gearbox "
                "term. Codes not listed here are NOT excluded from anything."
            ),
            "terms": list(GEARBOX_INDEX_TERMS),
            "codes_whose_message_contains_a_term": gearbox_index,
            "n_codes_indexed": len(gearbox_index),
            "n_codes_total": inventory["n_distinct_codes"],
        },
        "per_occurrence_csv": f"{out_stem.name}.csv",
    }

    after = {
        (r["year_folder"], r["name"]): sha256_of(
            next(f for f in folders if f.name == r["year_folder"]) / r["name"]
        )
        for r in inventory_rows
    }
    report["read_only_verification"] = {
        "inputs_unchanged": all(
            r["sha256"] == after[(r["year_folder"], r["name"])] for r in inventory_rows
        ),
        "method": "SHA-256 of every inventoried file compared before and after the run",
    }

    out_stem.parent.mkdir(parents=True, exist_ok=True)
    out_stem.with_suffix(".json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    with out_stem.with_suffix(".csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(per_occurrence[0]))
        writer.writeheader()
        writer.writerows(per_occurrence)
    print(f"Wrote {out_stem.with_suffix('.json')}")
    print(f"Wrote {out_stem.with_suffix('.csv')} ({len(per_occurrence)} rows, no truncation)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
