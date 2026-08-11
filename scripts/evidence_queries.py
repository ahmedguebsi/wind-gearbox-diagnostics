"""Author-requested evidence queries — READ-ONLY, FACTS ONLY.

Produces two evidence sets requested before D-04 and the thermal-target
designation are closed:

D-04 evidence
  * the exact start/end timestamps of every code-1860 occurrence and the
    gaps between them
  * every other status row logged on the affected turbine in the surrounding
    window, full row context, unfiltered
  * descriptive statistics for the gear-oil and bearing temperature channels
    in the 60 days preceding each occurrence

Target-designation evidence
  * correlation of gear oil temperature with each candidate bearing channel,
    overall and within power bins
  * gear oil inlet temperature distribution and its relationship to load

Descriptive statistics only. No anomaly judgment, no designation, no ranking,
no inferred labels. Code 1860 is a filter-restriction alarm and is treated
here as a candidate occurrence, never as verified gearbox damage.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset_census import (
    _read_source,
    classify,
    header_provenance,
    is_environment_noise,
)

TARGET_CODE = "1860"
SURROUNDING_DAYS = 120
PRECEDING_DAYS = 60

OIL_CHANNELS = ("Gear oil temperature (°C)", "Gear oil inlet temperature (°C)")
BEARING_CANDIDATES = (
    "Front bearing temperature (°C)",
    "Rear bearing temperature (°C)",
    "Generator bearing front temperature (°C)",
    "Generator bearing rear temperature (°C)",
    "Rotor bearing temp (°C)",
)
POWER_COLUMN = "Power (kW)"
#: Fixed physical power bins (kW). Reported with counts so the reader can see
#: how populated each bin is.
POWER_BIN_EDGES = [-float("inf"), 0, 50, 250, 500, 1000, 1500, float("inf")]


def describe(series: pd.Series) -> dict[str, Any]:
    clean = series.dropna()
    if clean.empty:
        return {"n": len(series), "n_non_null": 0}
    return {
        "n": len(series),
        "n_non_null": len(clean),
        "null_fraction": round(float(series.isna().mean()), 6),
        "mean": round(float(clean.mean()), 4),
        "std": round(float(clean.std()), 4),
        "min": round(float(clean.min()), 4),
        "p05": round(float(clean.quantile(0.05)), 4),
        "p25": round(float(clean.quantile(0.25)), 4),
        "median": round(float(clean.median()), 4),
        "p75": round(float(clean.quantile(0.75)), 4),
        "p95": round(float(clean.quantile(0.95)), 4),
        "max": round(float(clean.max()), 4),
    }


def discover(folders: list[Path]) -> tuple[list[Path], list[Path]]:
    scada, status = [], []
    for folder in folders:
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or is_environment_noise(path, folder):
                continue
            kind = classify(path)
            if kind == "SOURCE_SCADA":
                scada.append(path)
            elif kind == "SOURCE_STATUS":
                status.append(path)
    return scada, status


def load_scada(path: Path, columns_wanted: list[str]) -> tuple[pd.DataFrame, str]:
    prov = header_provenance(path)
    cols = prov["columns"]
    ts_col = cols[0]
    present = [c for c in columns_wanted if c in cols]
    raw = [prov["columns_raw"][cols.index(c)] for c in [ts_col, *present]]
    frame = _read_source(path, prov, usecols=raw, low_memory=False)
    frame = frame.rename(columns=dict(zip(raw, [ts_col, *present], strict=True)))
    frame[ts_col] = pd.to_datetime(frame[ts_col], errors="coerce")
    frame = frame.rename(columns={ts_col: "timestamp"})
    return frame, prov["declared"].get("turbine", "")


def d04_evidence(scada: list[Path], status: list[Path]) -> dict[str, Any]:
    occurrences: list[dict[str, Any]] = []
    rows_by_turbine: dict[str, list[dict[str, str]]] = {}
    for path in status:
        prov = header_provenance(path)
        turbine = prov["declared"].get("turbine", "")
        frame = _read_source(path, prov, dtype=str, keep_default_na=False)
        cols = [str(c) for c in frame.columns]
        records = [dict(zip(cols, r, strict=False)) for r in frame.itertuples(index=False)]
        rows_by_turbine.setdefault(turbine, []).extend(
            {k: str(v) for k, v in rec.items()} for rec in records
        )
        for rec in records:
            if str(rec.get("Code", "")).strip() == TARGET_CODE:
                occurrences.append(
                    {
                        "file": path.name,
                        "turbine": turbine,
                        "row_verbatim": {k: str(v) for k, v in rec.items()},
                    }
                )

    occurrences.sort(key=lambda o: o["row_verbatim"].get("Timestamp start", ""))
    for i, occ in enumerate(occurrences):
        row = occ["row_verbatim"]
        start = pd.to_datetime(row.get("Timestamp start"), errors="coerce")
        end = pd.to_datetime(row.get("Timestamp end"), errors="coerce")
        occ["start"] = None if pd.isna(start) else start.isoformat()
        occ["end"] = None if pd.isna(end) else end.isoformat()
        occ["duration_hours"] = (
            None
            if pd.isna(start) or pd.isna(end)
            else round((end - start).total_seconds() / 3600, 3)
        )
        if i > 0:
            prev_end = pd.to_datetime(occurrences[i - 1]["end"], errors="coerce")
            occ["gap_from_previous_end_hours"] = (
                None
                if pd.isna(prev_end) or pd.isna(start)
                else round((start - prev_end).total_seconds() / 3600, 3)
            )
            occ["gap_from_previous_end_days"] = (
                None
                if occ["gap_from_previous_end_hours"] is None
                else round(occ["gap_from_previous_end_hours"] / 24, 3)
            )
        else:
            occ["gap_from_previous_end_hours"] = None
            occ["gap_from_previous_end_days"] = None

    turbines = {o["turbine"] for o in occurrences}
    starts = [pd.to_datetime(o["start"]) for o in occurrences if o["start"]]
    window = None
    surrounding: list[dict[str, Any]] = []
    if starts:
        lo = min(starts) - pd.Timedelta(days=SURROUNDING_DAYS)
        hi = max(starts) + pd.Timedelta(days=SURROUNDING_DAYS)
        window = {
            "from": lo.isoformat(),
            "to": hi.isoformat(),
            "days_either_side": SURROUNDING_DAYS,
        }
        for turbine in turbines:
            for rec in rows_by_turbine.get(turbine, []):
                ts = pd.to_datetime(rec.get("Timestamp start"), errors="coerce")
                if not pd.isna(ts) and lo <= ts <= hi:
                    surrounding.append({"turbine": turbine, "row_verbatim": rec})
        surrounding.sort(key=lambda r: r["row_verbatim"].get("Timestamp start", ""))

    wanted = [*OIL_CHANNELS, *BEARING_CANDIDATES, POWER_COLUMN]
    frames: dict[str, list[pd.DataFrame]] = {}
    for path in scada:
        frame, turbine = load_scada(path, wanted)
        if turbine in turbines:
            frames.setdefault(turbine, []).append(frame)

    preceding: list[dict[str, Any]] = []
    for occ in occurrences:
        turbine = occ["turbine"]
        start = pd.to_datetime(occ["start"], errors="coerce")
        if turbine not in frames or pd.isna(start):
            preceding.append({"occurrence_start": occ["start"], "note": "no SCADA loaded"})
            continue
        data = pd.concat(frames[turbine]).sort_values("timestamp")
        lo = start - pd.Timedelta(days=PRECEDING_DAYS)
        window_data = data[(data["timestamp"] >= lo) & (data["timestamp"] < start)]
        stats = {
            column: describe(window_data[column])
            for column in wanted
            if column in window_data.columns
        }
        preceding.append(
            {
                "turbine": turbine,
                "occurrence_start": occ["start"],
                "window": {"from": lo.isoformat(), "to": start.isoformat(), "days": PRECEDING_DAYS},
                "n_samples_in_window": len(window_data),
                "channel_statistics": stats,
            }
        )

    return {
        "code": TARGET_CODE,
        "framing": (
            "Code 1860 is a filter-restriction alarm, not maintenance-verified "
            "failure. Reported as candidate occurrences for author review; no "
            "designation, no judgment about what they represent."
        ),
        "occurrences": occurrences,
        "n_occurrences": len(occurrences),
        "surrounding_window": window,
        "surrounding_status_rows_unfiltered": surrounding,
        "n_surrounding_rows": len(surrounding),
        "preceding_channel_statistics": preceding,
    }


def target_evidence(scada: list[Path]) -> dict[str, Any]:
    wanted = [*OIL_CHANNELS, *BEARING_CANDIDATES, POWER_COLUMN]
    per_turbine: dict[str, list[pd.DataFrame]] = {}
    for path in scada:
        frame, turbine = load_scada(path, wanted)
        per_turbine.setdefault(turbine, []).append(frame)

    oil = OIL_CHANNELS[0]
    inlet = OIL_CHANNELS[1]
    results: dict[str, Any] = {"per_turbine": {}, "channels_missing": {}}
    pooled: list[pd.DataFrame] = []

    for turbine, parts in sorted(per_turbine.items()):
        data = pd.concat(parts).sort_values("timestamp")
        pooled.append(data)
        missing = [c for c in wanted if c not in data.columns]
        if missing:
            results["channels_missing"][turbine] = missing
        entry: dict[str, Any] = {"n_rows": len(data)}
        if oil in data.columns:
            entry["overall_correlation_with_gear_oil_temperature"] = {
                column: (
                    None
                    if column not in data.columns
                    else round(float(data[oil].corr(data[column])), 4)
                )
                for column in [*BEARING_CANDIDATES, inlet]
            }
        results["per_turbine"][turbine] = entry

    allrows = pd.concat(pooled).sort_values("timestamp")
    results["pooled"] = {"n_rows": len(allrows)}
    if oil in allrows.columns:
        results["pooled"]["overall_correlation_with_gear_oil_temperature"] = {
            column: (
                None
                if column not in allrows.columns
                else round(float(allrows[oil].corr(allrows[column])), 4)
            )
            for column in [*BEARING_CANDIDATES, inlet]
        }
        if POWER_COLUMN in allrows.columns:
            bins = pd.cut(allrows[POWER_COLUMN], POWER_BIN_EDGES)
            binned: dict[str, Any] = {}
            for interval, group in allrows.groupby(bins, observed=True):
                binned[str(interval)] = {
                    "n_rows": len(group),
                    "correlation_with_gear_oil_temperature": {
                        column: (
                            None
                            if column not in group.columns or group[column].notna().sum() < 3
                            else round(float(group[oil].corr(group[column])), 4)
                        )
                        for column in [*BEARING_CANDIDATES, inlet]
                    },
                    "gear_oil_inlet_temperature": describe(group[inlet])
                    if inlet in group.columns
                    else None,
                    "gear_oil_temperature": describe(group[oil]),
                }
            results["pooled"]["by_power_bin"] = binned
            results["pooled"]["power_bin_edges_kw"] = [str(e) for e in POWER_BIN_EDGES]

    if inlet in allrows.columns:
        clean = allrows[inlet].dropna()
        rounded = clean.round(0)
        modal = rounded.mode()
        modal_value = float(modal.iloc[0]) if len(modal) else None
        results["gear_oil_inlet_temperature_profile"] = {
            "distribution": describe(allrows[inlet]),
            "correlation_with_power": (
                None
                if POWER_COLUMN not in allrows.columns
                else round(float(allrows[inlet].corr(allrows[POWER_COLUMN])), 4)
            ),
            "correlation_with_gear_oil_temperature": round(
                float(allrows[inlet].corr(allrows[oil])), 4
            ),
            "modal_value_1c_resolution": modal_value,
            "fraction_within_1c_of_modal": (
                None
                if modal_value is None
                else round(float((clean.sub(modal_value).abs() <= 1.0).mean()), 6)
            ),
            "fraction_within_2c_of_modal": (
                None
                if modal_value is None
                else round(float((clean.sub(modal_value).abs() <= 2.0).mean()), 6)
            ),
            "note": (
                "Descriptive only. Whether this constitutes setpoint-like "
                "behaviour is the author's reading, not a census output."
            ),
        }
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", action="append", required=True, dest="folders")
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--span-start", default=None, help="ISO date; rows before this are excluded"
    )
    args = parser.parse_args(argv)

    folders = [Path(f) for f in args.folders]
    scada, status = discover(folders)
    print(f"Discovered {len(scada)} SCADA and {len(status)} status files", flush=True)

    print("Building D-04 evidence...", flush=True)
    d04 = d04_evidence(scada, status)
    print("Building target-designation evidence...", flush=True)
    targets = target_evidence(scada)

    report = {
        "banner": (
            "EVIDENCE QUERIES — FACTS ONLY. Descriptive statistics, no anomaly "
            "judgment, no designation, no ranking, no inferred labels."
        ),
        "generated_at_utc": datetime.now(tz=UTC).isoformat(),
        "folders": [str(f) for f in folders],
        "d04_evidence": d04,
        "target_designation_evidence": targets,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
