"""Matched-FPR sweep over stored EXP residuals (M-23; ADR-016 as operationalised).

Design approved by the author 2026-08-13 (recorded in ADR-016's
Operationalisation block BEFORE this script first ran):

- Operating-point parameter: control-limit multiplier, 2.0-6.0 step 0.25
  then 6.5-12.0 step 0.5; adaptive extension in +1.0 steps to 20.0 if the
  strictest point still exceeds the smallest FPR target (extension
  reported, targets never clamped).
- Lambda swept as curve families at the pre-registered M-27 grid
  (0.1 / 0.2 / 0.3); persistence stays fixed at 3 samples (ADR-017(b)) and
  defines the isolated/sustained episode boundary.
- FA rate: alarm EPISODES (rising edges) per turbine-year, measured on the
  healthy VALIDATION block (selection basis). Out-of-period check on the
  ADR-022/024 healthy monitoring slice is REPORTED, never selection-driving.
- Pipelines: single_bearing / single_oil (context), single_union (either
  signal exceeds - the operational meaning of independent monitoring;
  ADR-016 baseline), coordinated (both targets, same direction).
- Matching at {200, 100, 50, 20, 10, 5, 2, 1, 0.5} FA/turbine-year; the
  sub-1/yr rungs are reported with single-event resolution stated.
- ADR-016 verdict per matched point per lambda: (a) coordinated isolated
  excursions < single_union's AND (b) coordinated sustained episodes
  within +/-20% of single_union's. (a) without (b) = "fewer isolated
  excursions at reduced sustained sensitivity"; not (a) = not met. Pairs
  whose ACHIEVED rates differ by more than 5% (relative to the larger)
  are labelled NOT INTERPRETABLE.
- Fairness symmetry check on real data: two identical coordinated
  pipelines must produce identical curves and matched multipliers.

Reads the stored experiment's residual parquets; rebuilds the RQ1 slice
membership with the pipeline's own ingestion/cleaning/split/builder code
and verifies the row count against the stored metrics before use. Writes
ONE additive analysis file: evaluation/matched_fpr_sweep.json.

v2 extensions (author-ordered 2026-08-13, AFTER the pre-registered sweep
ran and its verdict was accepted as the RQ2 answer; the pre-registered
sections are unchanged):
- SLICE CALIBRATION (SECONDARY): operating curves and matched points
  measured on the healthy monitoring slice. Uses monitoring-period
  healthy data — a WEAKER independence claim, stated plainly; the slice
  excludes the full ADR-013 event span, so no event-tuning is possible.
  Its grid extends adaptively to 40 sigma (reported) because the LIM-021
  transfer gap pushes slice rates far above validation rates.
- EXPLORATORY boundary sensitivity: ADR-016 verdicts recomputed at
  isolated/sustained boundaries {2, 3, 5, 10} samples. POST-HOC — it
  does not replace the pre-registered answer; the boundary-3 verdict is
  listed first in every table.

Usage (from backend/):
    uv run python ../scripts/run_matched_fpr_sweep.py --experiment EXP-20260813-002
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from app.core.config import (  # noqa: E402
    AppConfig,
    HealthyStateConfig,
    ThresholdStatsSource,
)
from app.core.versioning import capture_version_stamp  # noqa: E402
from app.data.cleaning import clean  # noqa: E402
from app.data.healthy_state import HealthyStateBuilder  # noqa: E402
from app.data.ingestion import ingest_files  # noqa: E402
from app.data.mapping import load_mapping  # noqa: E402
from app.data.schema import default_schema  # noqa: E402
from app.data.splitting import (  # noqa: E402
    ExperimentFlags,
    SplitSpec,
    SplitStrategy,
    split_chronologically,
)
from app.detection.matched_fpr import (  # noqa: E402
    CoordinatedPipeline,
    DetectionPipeline,
    OperatingCurve,
    OperatingPoint,
    SingleSignalPipeline,
    compare_at,
    matched_multiplier,
    sweep,
    turbine_years,
)
from app.residuals.engine import ResidualFrame  # noqa: E402
from app.residuals.ewma import ControlLimitFormulation, ControlLimitSpec, EwmaDetector  # noqa: E402
from app.residuals.normalization import partition_for  # noqa: E402
from run_kelmarsh_experiment import (  # noqa: E402
    MANUAL_EXCLUSION_WINDOWS,
    SPAN,
    TRAIN_END,
    VALIDATION_END,
    alarm_windows,
    turbine_data_paths,
)

LAMBDAS = (0.1, 0.2, 0.3)
FPR_TARGETS = (200.0, 100.0, 50.0, 20.0, 10.0, 5.0, 2.0, 1.0, 0.5)
BASE_GRID = tuple(round(2.0 + 0.25 * i, 2) for i in range(17)) + tuple(
    round(6.5 + 0.5 * i, 1) for i in range(12)
)
EXTENSION_GRID = tuple(float(m) for m in range(13, 21))
PERSISTENCE = 3  # ADR-017(b): the isolated/sustained boundary
#: ADR-031: the pre-registered boundary FIRST, then the literature-anchored
#: values. Nogueira et al. (Sensors 25(14):4499, 2025) require 20 consecutive
#: samples (~3.3 h); Gueck et al. (CARE, arXiv:2404.10320) require 72 (~12 h)
#: before declaring a false-alarm event. At 10-minute sampling our 3 samples
#: is 30 minutes - an order of magnitude below published practice, and it
#: defines the boundary that decides the ADR-016 verdict.
BOUNDARY_GRID = (PERSISTENCE, 2, 5, 10, 12, 20)
INTERPRETABILITY_TOLERANCE = 0.05
SAMPLE_MINUTES = 10.0
MINUTES_PER_YEAR = 365.25 * 24 * 60


def episode_lengths(flags: pd.Series) -> list[int]:
    values = flags.to_numpy(dtype=bool)
    if len(values) == 0:
        return []
    padded = np.concatenate([[False], values, [False]])
    starts = np.flatnonzero(~padded[:-1] & padded[1:])
    ends = np.flatnonzero(padded[:-1] & ~padded[1:])
    return [int(e - s) for s, e in zip(starts, ends, strict=True)]


def pipeline_lengths(pipeline: DetectionPipeline, multiplier: float) -> tuple[list[int], float]:
    flag_map = pipeline.alarm_flags(multiplier)
    # ADR-028: row-time, the same basis slice_rate uses. Before this change the
    # validation curves used calendar span while the slice check used row-time,
    # so the two arms of the headline comparison were not commensurable.
    years = turbine_years(flag_map)
    lengths: list[int] = []
    for flags in flag_map.values():
        lengths.extend(episode_lengths(flags))
    return lengths, years


def episode_stats(pipeline: DetectionPipeline, multiplier: float) -> dict[str, object]:
    lengths, years = pipeline_lengths(pipeline, multiplier)
    isolated = sum(1 for n in lengths if n < PERSISTENCE)
    sustained = sum(1 for n in lengths if n >= PERSISTENCE)
    return {
        "multiplier": multiplier,
        "achieved_fa_per_turbine_year": len(lengths) / years,
        "n_episodes": len(lengths),
        "isolated_excursions": isolated,
        "sustained_episodes": sustained,
        "median_duration_samples": float(np.median(lengths)) if lengths else None,
        "p90_duration_samples": float(np.percentile(lengths, 90)) if lengths else None,
        "turbine_years": years,
    }


def verdict_from_counts(
    iso_u: int, sus_u: int, iso_c: int, sus_c: int, a_u: float, a_c: float, boundary: int
) -> dict[str, object]:
    a_met = iso_c < iso_u
    # ADR-016(b): equivalence means within +/-20% of the baseline count; a
    # zero-baseline point is equivalent only at zero.
    b_met = sus_c == 0 if sus_u == 0 else abs(sus_c - sus_u) <= 0.2 * sus_u
    if a_met and b_met:
        verdict = "met"
    elif a_met:
        verdict = "fewer isolated excursions at reduced sustained sensitivity"
    else:
        verdict = "not met"
    larger = max(a_u, a_c)
    rel_diff = abs(a_u - a_c) / larger if larger > 0 else 0.0
    interpretable = rel_diff <= INTERPRETABILITY_TOLERANCE
    return {
        "boundary_samples": boundary,
        "criterion_a_fewer_isolated": a_met,
        "criterion_b_sustained_within_20pct": b_met,
        "verdict": verdict,
        "achieved_rate_relative_difference": rel_diff,
        "interpretable": interpretable,
        "reported_verdict": (
            verdict if interpretable else "not interpretable at unequal achieved rates"
        ),
    }


def adr016_verdict(union: dict[str, object], coordinated: dict[str, object]) -> dict[str, object]:
    result = verdict_from_counts(
        int(union["isolated_excursions"]),  # type: ignore[arg-type]
        int(union["sustained_episodes"]),  # type: ignore[arg-type]
        int(coordinated["isolated_excursions"]),  # type: ignore[arg-type]
        int(coordinated["sustained_episodes"]),  # type: ignore[arg-type]
        float(union["achieved_fa_per_turbine_year"]),  # type: ignore[arg-type]
        float(coordinated["achieved_fa_per_turbine_year"]),  # type: ignore[arg-type]
        PERSISTENCE,
    )
    result.pop("boundary_samples")
    return result


def slice_rate(
    pipeline: DetectionPipeline,
    multiplier: float,
    slice_keys: dict[str, pd.DatetimeIndex],
) -> dict[str, object]:
    """FA rate on the healthy monitoring slice (row-time basis; an episode
    re-entering after an excluded gap counts once per re-entry)."""
    flag_map = pipeline.alarm_flags(multiplier)
    n_events = 0
    n_rows = 0
    n_alarmed = 0
    for turbine, flags in flag_map.items():
        keys = slice_keys.get(turbine)
        if keys is None:
            continue
        restricted = flags[flags.index.isin(keys)]
        n_rows += len(restricted)
        n_alarmed += int(restricted.sum())
        n_events += len(episode_lengths(restricted))
    years = n_rows * SAMPLE_MINUTES / MINUTES_PER_YEAR
    return {
        "fa_per_turbine_year": (n_events / years) if years > 0 else None,
        "n_episodes": n_events,
        "n_rows": n_rows,
        "n_alarmed": n_alarmed,
        "turbine_years_row_time": years,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    # Defaults corrected 2026-08-18 (ADR-044 housekeeping): --experiment named
    # a run whose artifacts have since been deleted, and --downloads pointed at
    # a different machine's Downloads directory, so this script could not run
    # anywhere but its author's workstation.
    parser.add_argument("--experiment", default=None)
    parser.add_argument("--artifacts", type=Path, default=REPO_ROOT / "artifacts")
    parser.add_argument("--downloads", type=Path, default=REPO_ROOT / "dataset")
    args = parser.parse_args()
    experiment = (
        args.experiment or sorted(p.name for p in args.artifacts.glob("EXP-*") if p.is_dir())[-1]
    )
    directory = args.artifacts / experiment
    if not directory.is_dir():
        raise SystemExit(f"Experiment directory not found: {directory}")

    schema = default_schema()
    residual_frames = {
        partition: ResidualFrame(pd.read_parquet(directory / "residuals" / f"{partition}.parquet"))
        for partition in ("training", "validation", "test")
    }
    targets = residual_frames["validation"].targets
    stored_metrics = json.loads((directory / "metrics.json").read_text(encoding="utf-8"))

    # ---- rebuild the RQ1 slice membership with the pipeline's own code ----
    print("Rebuilding slice membership (ingest -> clean -> split -> builder)...")
    mapping = load_mapping(REPO_ROOT / "configs" / "kelmarsh_scada.yaml", schema)
    windows, _stats = alarm_windows(args.downloads)
    dataset = ingest_files(
        turbine_data_paths(args.downloads),
        mapping,
        schema,
        span_start=SPAN[0],
        span_end=SPAN[1],
        supplier_note="matched-FPR sweep slice reconstruction (read-only analysis)",
    )
    cleaned, _audit = clean(
        dataset,
        schema,
        [
            "drop_unparseable_timestamps",
            "drop_missing_any_target",
            "nullify_impossible_predictor_values",
            "drop_missing_any_predictor",
        ],
    )
    split = split_chronologically(
        cleaned,
        schema,
        SplitSpec(
            strategy=SplitStrategy.EXPLICIT_DATES,
            train_end=TRAIN_END,
            validation_end=VALIDATION_END,
        ),
        ExperimentFlags(thesis_official=True),
    )
    config = AppConfig(
        healthy_state=HealthyStateConfig(manual_exclusion_windows=MANUAL_EXCLUSION_WINDOWS)
    )
    test_frame = cleaned.frame.loc[split.test]
    builder = HealthyStateBuilder(config.healthy_state, schema)
    healthy_slice, _report = builder.build(
        cleaned.with_frame(test_frame.reset_index(drop=True), stage="matched_fpr_slice"),
        alarm_windows=list(windows),
        step_changes=[],  # exclude_step_changes is False (ADR-018); list unused
    )
    stored_rows = stored_metrics["rq1"]["monitoring_healthy_rows"]
    if len(healthy_slice.frame) != stored_rows:
        raise SystemExit(
            f"Slice reconstruction mismatch: rebuilt {len(healthy_slice.frame)} rows, "
            f"stored run recorded {stored_rows}. Aborting rather than reporting on a "
            "membership that differs from the headline run's."
        )
    timestamp_name, turbine_name = schema.timestamp_name, schema.turbine_id_name
    slice_keys: dict[str, pd.DatetimeIndex] = {}
    for turbine, group in healthy_slice.frame.groupby(turbine_name, observed=True):
        slice_keys[str(turbine)] = pd.DatetimeIndex(group[timestamp_name])

    # ---- sweep per lambda ---------------------------------------------------
    source = partition_for(ThresholdStatsSource.TRAINING)
    results: dict[str, object] = {}
    for lam in LAMBDAS:
        print(f"lambda={lam}: fitting EWMA and sweeping...")
        detector = EwmaDetector(
            lam,
            ControlLimitSpec(
                sigma_multiplier=3.0, formulation=ControlLimitFormulation.STEADY_STATE
            ),
        )
        detector.fit_control_limits(residual_frames["training"], source)
        validation_series, _ = detector.detect(residual_frames["validation"])
        test_series, _ = detector.detect(residual_frames["test"])

        def build_pipelines(series: list) -> dict[str, DetectionPipeline]:
            return {
                f"single_{target.split('_')[1]}": SingleSignalPipeline(
                    f"single_{target.split('_')[1]}", series, target
                )
                for target in targets
            } | {
                "single_union": CoordinatedPipeline("single_union", series, min_coordinated=1),
                "coordinated": CoordinatedPipeline("coordinated", series, min_coordinated=None),
            }

        pipelines = build_pipelines(validation_series)
        grid = list(BASE_GRID)
        curves = {name: sweep(p, grid) for name, p in pipelines.items()}
        strictest = min(
            curves[name].points[-1].false_alarms_per_turbine_year
            for name in ("single_union", "coordinated")
        )
        extended = False
        if strictest > min(FPR_TARGETS):
            grid = list(BASE_GRID) + list(EXTENSION_GRID)
            curves = {name: sweep(p, grid) for name, p in pipelines.items()}
            extended = True

        comparison = compare_at(curves, FPR_TARGETS)

        test_pipelines = build_pipelines(test_series)
        matched_detail = []
        for fpr_target in FPR_TARGETS:
            m_union = matched_multiplier(curves["single_union"], fpr_target)
            m_coord = matched_multiplier(curves["coordinated"], fpr_target)
            row: dict[str, object] = {"fpr_target": fpr_target}
            if m_union is None or m_coord is None:
                row["reachable"] = False
                row["unreachable_pipelines"] = [
                    name
                    for name, m in (("single_union", m_union), ("coordinated", m_coord))
                    if m is None
                ]
                matched_detail.append(row)
                continue
            union_stats = episode_stats(pipelines["single_union"], m_union)
            coord_stats = episode_stats(pipelines["coordinated"], m_coord)
            years = float(union_stats["turbine_years"])  # type: ignore[arg-type]
            # POST-HOC EXPLORATORY boundary sensitivity (author-permitted
            # 2026-08-13). Does not replace the pre-registered answer; the
            # boundary-3 verdict is listed first.
            union_lengths, _ = pipeline_lengths(pipelines["single_union"], m_union)
            coord_lengths, _ = pipeline_lengths(pipelines["coordinated"], m_coord)
            a_u = float(union_stats["achieved_fa_per_turbine_year"])  # type: ignore[arg-type]
            a_c = float(coord_stats["achieved_fa_per_turbine_year"])  # type: ignore[arg-type]
            exploratory = [
                verdict_from_counts(
                    sum(1 for n in union_lengths if n < b),
                    sum(1 for n in union_lengths if n >= b),
                    sum(1 for n in coord_lengths if n < b),
                    sum(1 for n in coord_lengths if n >= b),
                    a_u,
                    a_c,
                    b,
                )
                | {"pre_registered": b == PERSISTENCE}
                for b in BOUNDARY_GRID
            ]
            row.update(
                {
                    "reachable": True,
                    "single_union": union_stats,
                    "coordinated": coord_stats,
                    "adr016": adr016_verdict(union_stats, coord_stats),
                    "single_event_resolution_fa_per_ty": 1.0 / years,
                    "coarse_rung": bool(fpr_target * years < 10),
                    "slice_check": {
                        "single_union": slice_rate(
                            test_pipelines["single_union"], m_union, slice_keys
                        ),
                        "coordinated": slice_rate(
                            test_pipelines["coordinated"], m_coord, slice_keys
                        ),
                    },
                    "exploratory_boundary_sensitivity": {
                        "label": (
                            "POST-HOC EXPLORATORY (author-permitted 2026-08-13; "
                            "extended to 12 and 20 samples under ADR-031): does "
                            "not replace the pre-registered answer; the "
                            "pre-registered boundary (3 samples) is listed first. "
                            "20 samples is the Nogueira et al. (2025) persistence "
                            "rule; 12 approximates the CARE 72-sample false-alarm "
                            "criticality threshold scaled to this sweep's episode "
                            "definition. Our 3 samples is 30 minutes, an order of "
                            "magnitude below published practice"
                        ),
                        "verdicts": exploratory,
                    },
                }
            )
            matched_detail.append(row)

        # ---- SECONDARY: slice-calibrated points (weaker independence) -----
        # Uses monitoring-period healthy data; the slice excludes the full
        # ADR-013 event span, so no event-tuning is possible. Grid extends
        # adaptively to 40 sigma because of the LIM-021 transfer gap.
        slice_grid = list(grid)
        while slice_grid[-1] < 40.0:
            strictest_slice = min(
                float(
                    slice_rate(test_pipelines[name], slice_grid[-1], slice_keys)[
                        "fa_per_turbine_year"
                    ]  # type: ignore[arg-type]
                )
                for name in ("single_union", "coordinated")
            )
            if strictest_slice <= min(FPR_TARGETS):
                break
            slice_grid.append(slice_grid[-1] + 2.0)
        slice_curves: dict[str, OperatingCurve] = {}
        for name in ("single_union", "coordinated"):
            points = []
            for m in slice_grid:
                stats = slice_rate(test_pipelines[name], m, slice_keys)
                points.append(
                    OperatingPoint(
                        multiplier=float(m),
                        false_alarms_per_turbine_year=float(stats["fa_per_turbine_year"]),  # type: ignore[arg-type]
                        alarm_fraction=(
                            int(stats["n_alarmed"]) / int(stats["n_rows"])  # type: ignore[call-overload]
                            if stats["n_rows"]
                            else 0.0
                        ),
                        n_alarm_events=int(stats["n_episodes"]),  # type: ignore[call-overload]
                        n_points=int(stats["n_rows"]),  # type: ignore[call-overload]
                    )
                )
            slice_curves[name] = OperatingCurve(pipeline=f"{name}_slice", points=tuple(points))
        slice_matched = []
        for fpr_target in FPR_TARGETS:
            entry: dict[str, object] = {"fpr_target": fpr_target}
            for name in ("single_union", "coordinated"):
                m = matched_multiplier(slice_curves[name], fpr_target)
                if m is None:
                    entry[name] = {"reachable": False}
                    continue
                achieved = slice_rate(test_pipelines[name], m, slice_keys)
                validation_at_m = episode_stats(pipelines[name], m)
                entry[name] = {
                    "reachable": True,
                    "multiplier": m,
                    "achieved_slice_fa_per_turbine_year": achieved["fa_per_turbine_year"],
                    "validation_fa_per_turbine_year_at_multiplier": (
                        validation_at_m["achieved_fa_per_turbine_year"]
                    ),
                }
            slice_matched.append(entry)

        # fairness symmetry on real data: identical pipelines, zero difference
        mirror = CoordinatedPipeline("coordinated_mirror", validation_series, min_coordinated=None)
        mirror_curve = sweep(mirror, grid)
        symmetry_curves_equal = mirror_curve.points == curves["coordinated"].points
        symmetry_matches_equal = all(
            matched_multiplier(mirror_curve, t) == matched_multiplier(curves["coordinated"], t)
            for t in FPR_TARGETS
        )
        results[str(lam)] = {
            "grid": grid,
            "grid_extended_beyond_12": extended,
            "curves": {name: curve.as_dict() for name, curve in curves.items()},
            "comparison": comparison.as_dict(),
            "matched_detail": matched_detail,
            "slice_calibration": {
                "label": (
                    "SECONDARY (author ruling 2026-08-13): calibrated on the "
                    "healthy monitoring slice — monitoring-period healthy data, "
                    "a WEAKER independence claim than validation selection; the "
                    "slice excludes the full ADR-013 event span, so no "
                    "event-tuning is possible"
                ),
                "grid_max_multiplier": slice_grid[-1],
                "curves": {n: c.as_dict() for n, c in slice_curves.items()},
                "matched": slice_matched,
            },
            "symmetry_check": {
                "curves_identical": bool(symmetry_curves_equal),
                "matched_multipliers_identical": bool(symmetry_matches_equal),
                "passed": bool(symmetry_curves_equal and symmetry_matches_equal),
            },
        }

    payload = {
        "experiment_id": experiment,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "design": {
            "approved_by": "author, 2026-08-13 (ADR-016 Operationalisation block)",
            "fa_definition": "alarm episodes (rising edges) per turbine-year",
            "selection_basis": "healthy validation block",
            "out_of_period_check": (
                "ADR-022/024 healthy monitoring slice, row-time basis, reported only"
            ),
            "persistence_boundary_samples": PERSISTENCE,
            "fpr_targets": list(FPR_TARGETS),
            "lambdas": list(LAMBDAS),
            "interpretability_tolerance": INTERPRETABILITY_TOLERANCE,
        },
        "slice_rows_verified": stored_rows,
        "environment": capture_version_stamp(schema_version=schema.schema_version).model_dump(),
        "lambdas": results,
    }
    out_path = directory / "evaluation" / "matched_fpr_sweep.json"
    out_path.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    print(f"Sweep written to {out_path}")

    # condensed console summary
    for lam, block in results.items():
        print(f"\n=== lambda {lam} (symmetry passed: {block['symmetry_check']['passed']}) ===")  # type: ignore[index]
        for row in block["matched_detail"]:  # type: ignore[index]
            if not row.get("reachable"):
                unreachable = row.get("unreachable_pipelines")
                print(f"  target {row['fpr_target']:>6}/ty: UNREACHABLE {unreachable}")
                continue
            verdict = row["adr016"]["reported_verdict"]
            u, c = row["single_union"], row["coordinated"]
            print(
                f"  target {row['fpr_target']:>6}/ty: union m={u['multiplier']:.2f} "
                f"ach={u['achieved_fa_per_turbine_year']:.2f} iso={u['isolated_excursions']} "
                f"sus={u['sustained_episodes']} | coord m={c['multiplier']:.2f} "
                f"ach={c['achieved_fa_per_turbine_year']:.2f} iso={c['isolated_excursions']} "
                f"sus={c['sustained_episodes']} | {verdict}"
            )
        print("  -- SECONDARY slice-calibrated (weaker independence claim) --")
        calibration = block["slice_calibration"]  # type: ignore[index]
        print(f"  slice grid max multiplier: {calibration['grid_max_multiplier']}")
        for entry in calibration["matched"]:
            parts = [f"  slice t={entry['fpr_target']:>6}/ty:"]
            for name in ("single_union", "coordinated"):
                info = entry[name]
                if not info.get("reachable"):
                    parts.append(f"{name} UNREACHABLE")
                    continue
                parts.append(
                    f"{name} m={info['multiplier']:.2f} "
                    f"slice_ach={info['achieved_slice_fa_per_turbine_year']:.2f} "
                    f"(val {info['validation_fa_per_turbine_year_at_multiplier']:.2f})"
                )
            print(" | ".join(parts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
