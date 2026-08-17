"""Exploratory data analysis over the Kelmarsh holdings — READ-ONLY, FACTS ONLY.

Describes the data as it arrives, BEFORE the modelling pipeline touches it,
and quantifies what each pipeline stage would remove. No cleaning is applied
to the source, no judgment is emitted, no anomaly is designated: those are
pipeline and author decisions (M-07/M-11/M-12), not EDA outputs.

Inputs are SHA-256 hashed before and after the run and the equality recorded,
so read-only behaviour is evidenced rather than asserted — the same
discipline as scripts/dataset_census.py, whose helpers this reuses.

Nine stages, each answering a question the project has open:

  A  inventory + provenance      what exactly was read
  B  per-channel statistics      null fraction, range, dispersion, constancy
  C  temporal coverage           span, sampling regularity, gap structure
  D  missingness structure       joint patterns, not just marginal rates
  E  operating regime            power curve, capacity factor, idle fraction
  F  target relationships        target-target correlation OVERALL and BY
                                 POWER BIN — the raw-signal precursor to the
                                 residual-level question that decides whether
                                 coordinated detection adds evidence (RQ2)
  G  fleet coherence             cross-turbine correlation per channel; the
                                 quantity ADR-029 subtracts and the one
                                 LIM-023 turned on
  H  attrition preview           rows each cleaning/healthy-state rule would
                                 remove, before any model is fitted
  I  autocorrelation structure   decorrelation lag of each thermal channel
                                 and of a load/ambient-detrended proxy —
                                 the PHASE 10 requirement that sets
                                 defensible bootstrap block lengths and
                                 HAC lag windows downstream

Usage (from backend/):
    uv run python ../scripts/run_eda.py --downloads <folder> --output ../artifacts/eda
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from app.data.mapping import load_mapping  # noqa: E402
from app.data.schema import (  # noqa: E402
    ACTIVE_POWER,
    VariableRole,
    default_schema,
)
from dataset_census import _read_source, header_provenance, sha256_of  # noqa: E402

#: Fixed physical power bins (kW), reported with counts so bin population is
#: visible. Matches the bins used for the ADR-012 target designation, so the
#: two analyses are directly comparable.
POWER_BIN_EDGES = [-np.inf, 0, 50, 250, 500, 1000, 1500, np.inf]

#: Provisional healthy-state values whose attrition is previewed (PROJECT.md
#: §13). Reported as counts only — applying them is M-12's job.
POWER_FLOOR_KW = 50.0

MAX_GAP_EXAMPLES = 20


def describe(series: pd.Series) -> dict[str, Any]:
    """Distribution summary. Percentiles rather than mean/std alone, because
    SCADA channels are routinely bimodal (idle versus generating)."""
    clean = series.dropna()
    if clean.empty:
        return {"n": len(series), "n_non_null": 0, "null_fraction": 1.0}
    return {
        "n": len(series),
        "n_non_null": len(clean),
        "null_fraction": round(float(series.isna().mean()), 6),
        "mean": round(float(clean.mean()), 4),
        "std": round(float(clean.std()), 4),
        "min": round(float(clean.min()), 4),
        "p01": round(float(clean.quantile(0.01)), 4),
        "p05": round(float(clean.quantile(0.05)), 4),
        "p25": round(float(clean.quantile(0.25)), 4),
        "median": round(float(clean.median()), 4),
        "p75": round(float(clean.quantile(0.75)), 4),
        "p95": round(float(clean.quantile(0.95)), 4),
        "p99": round(float(clean.quantile(0.99)), 4),
        "max": round(float(clean.max()), 4),
        "n_distinct": int(clean.nunique()),
        "is_constant": bool(clean.nunique() == 1),
    }


def load_turbine(path: Path, wanted: dict[str, str]) -> tuple[pd.DataFrame, str]:
    """Read one export file and rename mapped raw columns to canonical names."""
    provenance = header_provenance(path)
    columns = provenance["columns"]
    timestamp_raw = columns[0]
    present = [c for c in wanted if c in columns]
    raw_names = [provenance["columns_raw"][columns.index(c)] for c in [timestamp_raw, *present]]
    frame = _read_source(path, provenance, usecols=raw_names, low_memory=False)
    frame = frame.rename(columns=dict(zip(raw_names, [timestamp_raw, *present], strict=True)))
    frame = frame.rename(columns={timestamp_raw: "timestamp", **{c: wanted[c] for c in present}})
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    return frame, str(provenance["declared"].get("turbine", path.stem))


# --------------------------------------------------------------------------
# Stage C — temporal coverage
# --------------------------------------------------------------------------


def temporal_coverage(frame: pd.DataFrame) -> dict[str, Any]:
    stamps = frame["timestamp"].dropna().sort_values()
    if len(stamps) < 2:
        return {"n_rows": len(frame), "note": "fewer than two parseable timestamps"}
    deltas = stamps.diff().dropna()
    modal = deltas.mode().iloc[0]
    gaps = deltas[deltas > modal]
    return {
        "n_rows": len(frame),
        "first_timestamp": str(stamps.iloc[0]),
        "last_timestamp": str(stamps.iloc[-1]),
        "span_days": round(float((stamps.iloc[-1] - stamps.iloc[0]).total_seconds() / 86400), 3),
        "modal_interval": str(modal),
        "n_intervals_at_modal": int((deltas == modal).sum()),
        "n_duplicate_timestamps": int(stamps.duplicated().sum()),
        "n_gaps_above_modal": len(gaps),
        "total_gap_hours": round(float((gaps - modal).sum().total_seconds() / 3600), 3),
        "largest_gaps": [
            {"after": str(stamps.iloc[i]), "gap": str(deltas.iloc[i - 1])}
            for i in gaps.nlargest(MAX_GAP_EXAMPLES).index[:MAX_GAP_EXAMPLES]
            if i > 0
        ][:MAX_GAP_EXAMPLES],
        # Row-time vs calendar span: the distinction ADR-028 turns on.
        "observed_row_time_days": round(float(len(stamps) * modal.total_seconds() / 86400), 3),
    }


# --------------------------------------------------------------------------
# Stage D — missingness structure
# --------------------------------------------------------------------------


def missingness(frame: pd.DataFrame, channels: list[str]) -> dict[str, Any]:
    """Joint missingness, not just per-channel rates.

    Marginal null fractions hide whether channels fail together. A row missing
    ANY predictor is dropped by the pipeline, so the joint pattern is what
    determines attrition.
    """
    present = [c for c in channels if c in frame.columns]
    null_mask = frame[present].isna()
    patterns = (
        null_mask.apply(lambda row: "|".join(c for c in present if row[c]), axis=1)
        .replace("", "(complete)")
        .value_counts()
        .head(15)
    )
    return {
        "per_channel_null_fraction": {c: round(float(null_mask[c].mean()), 6) for c in present},
        "rows_complete": int((~null_mask.any(axis=1)).sum()),
        "rows_missing_any": int(null_mask.any(axis=1).sum()),
        "rows_missing_all": int(null_mask.all(axis=1).sum()),
        "top_missingness_patterns": {str(k): int(v) for k, v in patterns.items()},
    }


# --------------------------------------------------------------------------
# Stage E — operating regime
# --------------------------------------------------------------------------


def operating_regime(frame: pd.DataFrame, rated_kw: float) -> dict[str, Any]:
    if ACTIVE_POWER not in frame.columns:
        return {"note": "active power not mapped"}
    power = frame[ACTIVE_POWER].dropna()
    if power.empty:
        return {"note": "active power entirely null"}
    bins = pd.cut(power, POWER_BIN_EDGES)
    return {
        "rated_power_kw_assumed": rated_kw,
        "capacity_factor": round(float(power.mean() / rated_kw), 6),
        "fraction_below_power_floor": round(float((power < POWER_FLOOR_KW).mean()), 6),
        "fraction_negative_power": round(float((power < 0).mean()), 6),
        "power_bin_counts": {str(k): int(v) for k, v in bins.value_counts().sort_index().items()},
    }


# --------------------------------------------------------------------------
# Stage F — target relationships
# --------------------------------------------------------------------------


def target_relationships(
    frame: pd.DataFrame, targets: list[str], predictors: list[str]
) -> dict[str, Any]:
    """Target-target and target-predictor structure, overall and by power bin.

    The target-target correlation here is on RAW TEMPERATURES and is dominated
    by common load and ambient drive. It is the precursor to, and NOT a
    substitute for, the residual-level correlation the pipeline now emits
    (app/evaluation/residual_diagnostics.py) — that is the quantity which
    decides whether coordinated detection adds independent evidence.
    """
    present_targets = [t for t in targets if t in frame.columns]
    if len(present_targets) < 2:
        return {"note": "fewer than two targets mapped"}
    a, b = present_targets[0], present_targets[1]
    out: dict[str, Any] = {
        "targets": present_targets,
        "overall_pearson": round(float(frame[a].corr(frame[b])), 6),
        "overall_spearman": round(float(frame[a].corr(frame[b], method="spearman")), 6),
        "target_vs_predictor_pearson": {
            t: {
                p: round(float(frame[t].corr(frame[p])), 6)
                for p in predictors
                if p in frame.columns
            }
            for t in present_targets
        },
    }
    if ACTIVE_POWER in frame.columns:
        by_bin: dict[str, Any] = {}
        for interval, group in frame.groupby(
            pd.cut(frame[ACTIVE_POWER], POWER_BIN_EDGES), observed=True
        ):
            paired = group[[a, b]].dropna()
            if len(paired) < 30:
                continue
            by_bin[str(interval)] = {
                "n": len(paired),
                "pearson": round(float(paired[a].corr(paired[b])), 6),
                f"{a}_mean": round(float(paired[a].mean()), 4),
                f"{b}_mean": round(float(paired[b].mean()), 4),
            }
        out["by_power_bin"] = by_bin
    return out


# --------------------------------------------------------------------------
# Stage G — fleet coherence
# --------------------------------------------------------------------------


def fleet_coherence(per_turbine: dict[str, pd.DataFrame], channels: list[str]) -> dict[str, Any]:
    """Cross-turbine correlation per channel, on the common timestamp grid.

    High coherence means a channel is driven by farm-wide conditions rather
    than machine state. This is the structure ADR-029 subtracts as a
    leave-one-out fleet median, and the structure LIM-023 found had produced
    the EVENT-001 excursion on all six machines at once.
    """
    out: dict[str, Any] = {}
    for channel in channels:
        wide = pd.DataFrame(
            {
                turbine: frame.set_index("timestamp")[channel]
                for turbine, frame in per_turbine.items()
                if channel in frame.columns
            }
        ).dropna()
        if wide.shape[0] < 100 or wide.shape[1] < 2:
            continue
        matrix = wide.corr()
        off_diagonal = matrix.to_numpy()[~np.eye(matrix.shape[0], dtype=bool)]
        out[channel] = {
            "n_aligned_rows": int(wide.shape[0]),
            "n_turbines": int(wide.shape[1]),
            "mean_pairwise_pearson": round(float(off_diagonal.mean()), 6),
            "min_pairwise_pearson": round(float(off_diagonal.min()), 6),
            "max_pairwise_pearson": round(float(off_diagonal.max()), 6),
            "matrix": {
                str(i): {str(j): round(float(matrix.loc[i, j]), 4) for j in matrix.columns}
                for i in matrix.index
            },
        }
    return out


# --------------------------------------------------------------------------
# Stage I — autocorrelation structure
# --------------------------------------------------------------------------


def _acf(values: np.ndarray, lag: int) -> float:
    """Biased sample autocorrelation at one lag (standard 1/n normalisation)."""
    centred = values - values.mean()
    denominator = float(np.sum(centred**2))
    if denominator == 0.0:
        return 0.0
    return float(np.sum(centred[lag:] * centred[:-lag]) / denominator)


def autocorrelation_structure(
    frame: pd.DataFrame, channels: list[str], max_lag: int = 2016
) -> dict[str, Any]:
    """Decorrelation lag per channel, raw and load/ambient-detrended.

    PROJECT.md §35 PHASE 10 requires EDA of residual autocorrelation. At EDA
    time no model exists, so this reports two things: the raw channel's
    autocorrelation, and that of a DETRENDED PROXY formed by removing an
    ordinary least-squares fit on active power and ambient temperature — the
    two dominant drivers. The proxy is a stand-in for the NBM residual, not
    the residual itself, and is labelled as such.

    The number that matters downstream is the decorrelation lag: the first lag
    at which the sample autocorrelation falls inside the 95% white-noise band.
    It is the empirical basis for the moving-block bootstrap's block length and
    for the Diebold-Mariano HAC window, both of which are otherwise chosen from
    sample SIZE rather than from dependence.

    Computed on the LONGEST CONTIGUOUS RUN at the modal sampling interval, so
    lags correspond to real elapsed time rather than to row adjacency across
    gaps. The run length used is reported.
    """
    stamps = frame["timestamp"]
    ordered = frame.loc[stamps.notna()].sort_values("timestamp").reset_index(drop=True)
    if len(ordered) < 100:
        return {"note": "too few rows for an autocorrelation estimate"}
    deltas = ordered["timestamp"].diff()
    modal = deltas.mode().iloc[0]
    # Longest run of consecutive rows separated by exactly the modal interval.
    breaks = np.flatnonzero((deltas != modal).to_numpy()[1:]) + 1
    bounds = np.concatenate([[0], breaks, [len(ordered)]])
    lengths = np.diff(bounds)
    best = int(np.argmax(lengths))
    segment = ordered.iloc[bounds[best] : bounds[best + 1]]

    interval_minutes = modal.total_seconds() / 60.0
    out: dict[str, Any] = {
        "modal_interval": str(modal),
        "longest_contiguous_run_rows": len(segment),
        "longest_contiguous_run_hours": round(len(segment) * interval_minutes / 60.0, 2),
        "note": (
            "Detrended proxy = channel minus an OLS fit on active power and "
            "ambient temperature. A stand-in for the NBM residual, NOT the "
            "residual itself."
        ),
        "channels": {},
    }

    drivers = [c for c in (ACTIVE_POWER, "ambient_temperature") if c in segment.columns]
    for channel in channels:
        if channel not in segment.columns:
            continue
        usable = segment[[channel, *drivers]].dropna()
        if len(usable) < 200:
            continue
        raw = usable[channel].to_numpy(dtype=float)
        series: dict[str, np.ndarray] = {"raw": raw}
        if drivers:
            design = np.column_stack(
                [np.ones(len(usable))] + [usable[d].to_numpy(dtype=float) for d in drivers]
            )
            coefficients, *_ = np.linalg.lstsq(design, raw, rcond=None)
            series["detrended_proxy"] = raw - design @ coefficients

        entry: dict[str, Any] = {"n": len(usable)}
        for label, values in series.items():
            band = 1.96 / np.sqrt(len(values))
            limit = int(min(max_lag, len(values) // 4))
            decorrelation_lag = None
            curve: dict[str, float] = {}
            for lag in range(1, limit + 1):
                value = _acf(values, lag)
                if lag in (1, 6, 36, 144, 432, 1008, 2016):
                    curve[str(lag)] = round(value, 6)
                if decorrelation_lag is None and abs(value) < band:
                    decorrelation_lag = lag
            entry[label] = {
                "acf_at_selected_lags": curve,
                "white_noise_band": round(float(band), 6),
                "decorrelation_lag_samples": decorrelation_lag,
                "decorrelation_lag_hours": (
                    round(decorrelation_lag * interval_minutes / 60.0, 3)
                    if decorrelation_lag is not None
                    else None
                ),
                "exceeded_search_limit": decorrelation_lag is None,
            }
        out["channels"][channel] = entry
    return out


# --------------------------------------------------------------------------
# Stage H — attrition preview
# --------------------------------------------------------------------------


def attrition_preview(
    frame: pd.DataFrame, predictors: list[str], targets: list[str], schema: Any
) -> dict[str, Any]:
    """Rows each pipeline rule WOULD remove. Counts only; nothing is applied.

    Ordered as the cleaning registry applies them, so the numbers compose the
    way the audit trail will.
    """
    total = len(frame)
    steps: list[dict[str, Any]] = []
    surviving = frame

    unparseable = surviving["timestamp"].isna()
    steps.append({"rule": "drop_unparseable_timestamps", "would_remove": int(unparseable.sum())})
    surviving = surviving[~unparseable]

    present_targets = [t for t in targets if t in surviving.columns]
    missing_target = surviving[present_targets].isna().any(axis=1)
    steps.append({"rule": "drop_missing_any_target", "would_remove": int(missing_target.sum())})
    surviving = surviving[~missing_target]

    impossible = pd.Series(False, index=surviving.index)
    per_channel: dict[str, int] = {}
    for name in predictors:
        variable = schema.variable(name)
        if variable.plausible_range is None or name not in surviving.columns:
            continue
        low, high = variable.plausible_range
        outside = (surviving[name] < low) | (surviving[name] > high)
        per_channel[name] = int(outside.sum())
        impossible |= outside
    steps.append(
        {
            "rule": "nullify_impossible_predictor_values",
            "would_nullify_rows": int(impossible.sum()),
            "by_channel": per_channel,
        }
    )

    present_predictors = [p for p in predictors if p in surviving.columns]
    missing_predictor = surviving[present_predictors].isna().any(axis=1) | impossible
    steps.append(
        {"rule": "drop_missing_any_predictor", "would_remove": int(missing_predictor.sum())}
    )
    surviving = surviving[~missing_predictor]

    below_floor = (
        (surviving[ACTIVE_POWER] < POWER_FLOOR_KW).fillna(True)
        if ACTIVE_POWER in surviving.columns
        else pd.Series(False, index=surviving.index)
    )
    steps.append(
        {
            "rule": f"healthy_state_power_floor_{POWER_FLOOR_KW:g}kW",
            "would_remove": int(below_floor.sum()),
            "note": "healthy-state criterion; applies to train/validation only",
        }
    )

    modelling_rows = int((~below_floor).sum())
    return {
        "rows_before": total,
        "steps": steps,
        "rows_after_cleaning": len(surviving),
        "rows_after_power_floor": modelling_rows,
        "overall_retention_pct": round(100.0 * modelling_rows / total, 4) if total else 0.0,
    }


# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--downloads", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rated-kw", type=float, default=2050.0)
    args = parser.parse_args()

    schema = default_schema()
    mapping = load_mapping(REPO_ROOT / "configs" / "kelmarsh_scada.yaml", schema)
    wanted = {raw: spec.canonical for raw, spec in mapping.columns.items()}
    predictors = sorted(
        c for c in wanted.values() if schema.variable(c).role is VariableRole.PREDICTOR
    )
    targets = sorted(c for c in wanted.values() if schema.variable(c).role is VariableRole.TARGET)

    folders = sorted(p for p in args.downloads.glob("Kelmarsh_SCADA_*") if p.is_dir())
    paths = [f for folder in folders for f in sorted(folder.glob("Turbine_Data_*.csv"))]
    if not paths:
        raise SystemExit(f"No Turbine_Data_*.csv found under {args.downloads}")

    print(f"Hashing {len(paths)} source files before the run...")
    hashes_before = {str(p): sha256_of(p) for p in paths}

    per_file: dict[str, Any] = {}
    per_turbine_frames: dict[str, list[pd.DataFrame]] = {}
    for path in paths:
        frame, turbine = load_turbine(path, wanted)
        print(f"  {path.name}  ->  {turbine}  ({len(frame):,} rows)")
        # Keyed by path relative to the data root, not by bare filename: the
        # year folder is part of a file's identity, and a reader should not
        # have to parse it back out of a date range in the name.
        per_file[str(path.relative_to(args.downloads)).replace("\\", "/")] = {
            "turbine": turbine,
            "year_folder": path.parent.name,
            "temporal_coverage": temporal_coverage(frame),
            "per_channel": {c: describe(frame[c]) for c in frame.columns if c != "timestamp"},
            "missingness": missingness(frame, predictors + targets),
        }
        per_turbine_frames.setdefault(turbine, []).append(frame)

    combined = {
        turbine: pd.concat(frames, ignore_index=True).sort_values("timestamp")
        for turbine, frames in per_turbine_frames.items()
    }

    print("Computing per-turbine regime, target structure and attrition...")
    per_turbine: dict[str, Any] = {}
    for turbine, frame in combined.items():
        per_turbine[turbine] = {
            "temporal_coverage": temporal_coverage(frame),
            "operating_regime": operating_regime(frame, args.rated_kw),
            "target_relationships": target_relationships(frame, targets, predictors),
            "attrition_preview": attrition_preview(frame, predictors, targets, schema),
            "autocorrelation_structure": autocorrelation_structure(frame, targets),
        }

    print("Computing fleet coherence...")
    coherence = fleet_coherence(combined, predictors + targets)

    print("Re-hashing sources to evidence read-only behaviour...")
    hashes_after = {str(p): sha256_of(p) for p in paths}

    payload = {
        "banner": (
            "READ-ONLY EDA. Facts only: no cleaning applied to source, no "
            "judgment, no anomaly designation, no inferred labels. Cleaning "
            "and healthy-state figures are PREVIEWS of what the pipeline "
            "would remove, not applied transformations."
        ),
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "mapping_hash": mapping.mapping_hash,
        "schema_version": schema.schema_version,
        "canonical_predictors": predictors,
        "canonical_targets": targets,
        "read_only_verification": {
            "inputs_unchanged": hashes_before == hashes_after,
            "n_files": len(paths),
            "sha256_before": hashes_before,
        },
        "per_file": per_file,
        "per_turbine": per_turbine,
        "fleet_coherence": coherence,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out_path = args.output.with_suffix(".json")
    out_path.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    print(f"\nEDA written to {out_path}")
    print(f"Inputs unchanged: {hashes_before == hashes_after}")
    if hashes_before != hashes_after:
        raise SystemExit("SOURCE FILES CHANGED DURING THE RUN — investigate before using output")
    return 0


if __name__ == "__main__":
    sys.exit(main())
