"""First real Kelmarsh pipeline run (PROJECT.md §36; ADR-009/010/012/014/016/017).

REQUIRES EXPLICIT AUTHOR APPROVAL: the script refuses to run without
``--approved-by`` (the predictor set in configs/kelmarsh_scada.yaml, the
provisional split dates below, and the alarm-window policy all await author
sign-off; the approval string is recorded in the experiment's provenance).

Run configuration (documented, provisional where noted):
- Span 2016-05-03 to 2021-06-30, all six turbines (ADR-009).
- Explicit chronological split — TRAIN to 2018-07-01, VALIDATION to
  2019-02-01, TEST/monitoring from there (places EVENT-001 in TEST per
  ADR-010, with the monitoring period opening before the ADR-017 14-day
  match window). RATIFIED by ADR-023 (closes D-07); 70/15/15 fractions
  are recorded there as infeasible for this dataset.
- Alarm windows for healthy-state exclusion: status rows with Status in
  {Stop, Warning} AND a populated Timestamp end, across the ADR-009
  modelling span (ADR-022: monitoring-period windows feed the RQ1 healthy
  slice only; the detection stream stays unfiltered per PROJECT.md §14).
  Rows without an end cannot define a window and are counted and
  reported, never guessed.
- Cleaning: drop_unparseable_timestamps, drop_missing_any_target,
  nullify_impossible_predictor_values (ADR-020), drop_missing_any_predictor
  (rows that cannot be scored or produce residuals; every removal audited).

Usage (from backend/):
    uv run python ../scripts/run_kelmarsh_experiment.py --approved-by "MK 2026-08-12"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import AppConfig, HealthyStateConfig, ManualExclusionWindow  # noqa: E402
from app.data.guards import FeatureConfig  # noqa: E402
from app.data.healthy_state import ExclusionWindow  # noqa: E402
from app.data.mapping import load_mapping  # noqa: E402
from app.data.schema import SCHEMA_VERSION, VariableRole, default_schema  # noqa: E402
from app.data.splitting import ExperimentFlags, SplitSpec, SplitStrategy  # noqa: E402
from app.detection.coordinated import CoordinatedAnalyzer  # noqa: E402
from app.evaluation.bootstrap import (  # noqa: E402
    BlockedBootstrap,
    block_length_from_autocorrelation,
)
from app.evaluation.dm_test import diebold_mariano  # noqa: E402
from app.evaluation.event_eval import evaluate_events  # noqa: E402
from app.evaluation.events import EVENT_001, StatusValue, parse_status_csv  # noqa: E402
from app.experiments.runner import PipelineInputs, run_experiment  # noqa: E402
from app.experiments.store import ArtifactStore  # noqa: E402
from app.fmea.interpreter import FmeaInterpreter  # noqa: E402
from app.fmea.knowledge_base import FmeaKnowledgeBase, default_ruleset_path  # noqa: E402
from app.residuals.ewma import ControlLimitFormulation, ControlLimitSpec, EwmaDetector  # noqa: E402
from app.residuals.normalization import partition_for  # noqa: E402

SPAN = (date(2016, 5, 3), date(2021, 6, 30))  # ADR-009
TRAIN_END = date(2018, 7, 1)  # RATIFIED (ADR-023, closes D-07)
VALIDATION_END = date(2019, 2, 1)  # 9.7 d before the ADR-017 window opens (ADR-023)
STATUS_SKIP_LINES = 9
BOOTSTRAP_REPLICATES = 1000
BOOTSTRAP_SEED = 42

# Author-designated exclusion windows.
# ADR-018: the two Kelmarsh 6 episodes whose level shifts persist WITHOUT a
# coincident power change — the only recalibration-like candidates in the
# 3,187-detection population. Bounds follow the +/-1-day convention around
# the detection timestamps (the February pair is one episode covering both
# channels).
# ADR-024: the full ADR-013 EVENT-001 episode span — clearance gaps between
# occurrences are relief of the filter restriction, not healthy operation,
# so no row of the span counts as healthy for RQ1. Slice-only by
# construction: the detection stream never passes through the
# healthy-state builder.
MANUAL_EXCLUSION_WINDOWS = (
    ManualExclusionWindow(
        label="EVENT-001-episode-span",
        turbine="Kelmarsh 1",
        start_utc=pd.Timestamp("2019-02-24T16:46:28Z").to_pydatetime(),
        end_utc=pd.Timestamp("2019-05-30T07:34:04Z").to_pydatetime(),
        reason="author_designated_event_span",
        citation=(
            "ADR-013 via ADR-024: ONE continuous degradation episode; rows "
            "within the span cannot be counted as healthy regardless of "
            "momentary alarm state (author ruling 2026-08-13)"
        ),
    ),
    ManualExclusionWindow(
        label="K6-artefact-2021-02-05",
        turbine="Kelmarsh 6",
        start_utc=pd.Timestamp("2021-02-04T17:50:00Z").to_pydatetime(),
        end_utc=pd.Timestamp("2021-02-06T19:00:00Z").to_pydatetime(),
        citation=(
            "ADR-018: bearing -45.1 C (17:50) and oil -34.8 C (19:00) within "
            "~1 h at |dP| ~70 kW; ~90% of the shift retained at 30 days"
        ),
    ),
    ManualExclusionWindow(
        label="K6-artefact-2021-03-05",
        turbine="Kelmarsh 6",
        start_utc=pd.Timestamp("2021-03-04T06:20:00Z").to_pydatetime(),
        end_utc=pd.Timestamp("2021-03-06T06:20:00Z").to_pydatetime(),
        citation="ADR-018: bearing +36.4 C at dP = 0; shift retained at 30 days",
    ),
)


def turbine_data_paths(downloads: Path) -> list[Path]:
    folders = sorted(p for p in downloads.glob("Kelmarsh_SCADA_*") if p.is_dir())
    paths = [f for folder in folders for f in sorted(folder.glob("Turbine_Data_*.csv"))]
    if len(paths) != 36:
        raise SystemExit(f"Expected 36 turbine-data files, found {len(paths)}")
    return paths


def alarm_windows(
    downloads: Path,
) -> tuple[list[ExclusionWindow], dict[str, object]]:
    """Stop/Warning windows with populated ends, within the train/val span.

    Rows the event constructor refuses (e.g. end-before-start pairs — real
    rows in the 2016 export) are collected and reported as dataset findings
    (LIM-011), never guessed at.
    """
    folders = sorted(p for p in downloads.glob("Kelmarsh_SCADA_*") if p.is_dir())
    span_start = pd.Timestamp(SPAN[0], tz="UTC")
    # ADR-022: windows span the FULL modelling period, not just train/val —
    # monitoring-period windows feed the RQ1 healthy slice (metrics only);
    # the detection stream stays unfiltered per PROJECT.md §14.
    span_end = pd.Timestamp(SPAN[1], tz="UTC") + pd.Timedelta(days=1)
    windows: list[ExclusionWindow] = []
    rejected: list[dict[str, str]] = []
    skipped_no_end = 0
    n_rows = 0
    for folder in folders:
        for path in sorted(folder.glob("Status_Kelmarsh_*.csv")):
            turbine = "Kelmarsh " + path.name.split("Status_Kelmarsh_")[1][0]
            events, _record = parse_status_csv(
                path,
                turbine=turbine,
                skip_lines=STATUS_SKIP_LINES,
                schema_version=SCHEMA_VERSION,
                rejected=rejected,
            )
            for event in events:
                n_rows += 1
                if event.status not in (StatusValue.STOP, StatusValue.WARNING):
                    continue
                if event.start_utc >= span_end or event.start_utc < span_start:
                    continue
                if event.end_utc is None:
                    skipped_no_end += 1
                    continue
                windows.append(
                    ExclusionWindow(
                        turbine=event.turbine,
                        start_utc=event.start_utc,
                        end_utc=min(event.end_utc, span_end),
                        reason="alarm_period",
                    )
                )
    stats: dict[str, object] = {
        "status_rows_seen": n_rows,
        "stop_warning_without_end": skipped_no_end,
        "rows_rejected_by_constructor": len(rejected),
        "rejected_examples": rejected[:5],
    }
    return windows, stats


def metric_cis(residuals: np.ndarray, actual: np.ndarray) -> dict[str, dict[str, float]]:
    """Blocked-bootstrap CIs for RMSE/MAE/bias; R² via the fixed-denominator
    approximation (variance of actuals held at its sample value — documented
    approximation, labelled in the output)."""
    block = block_length_from_autocorrelation(residuals)
    bootstrap = BlockedBootstrap(block, BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED)
    var_actual = float(np.var(actual))
    statistics = {
        "rmse": lambda r: float(np.sqrt(np.mean(r**2))),
        "mae": lambda r: float(np.mean(np.abs(r))),
        "bias": lambda r: float(np.mean(r)),
        "r2_fixed_denominator": lambda r: float(1.0 - np.mean(r**2) / var_actual),
    }
    out: dict[str, dict[str, float]] = {"block_length": {"value": float(block)}}
    for name, stat in statistics.items():
        ci = bootstrap.ci(residuals, stat)
        out[name] = {"point": ci.point, "lower": ci.lower, "upper": ci.upper}
    return out


def kelmarsh_config() -> AppConfig:
    """The standing Kelmarsh run configuration (ADR-018/020/021/022/023)."""
    return AppConfig(
        healthy_state=HealthyStateConfig(manual_exclusion_windows=MANUAL_EXCLUSION_WINDOWS)
    )


def kelmarsh_inputs(
    downloads: Path,
    supplier_note: str,
    limitations_path: Path | None,
    predictors_override: tuple[str, ...] | None = None,
) -> tuple[PipelineInputs, dict[str, object]]:
    """The standing Kelmarsh pipeline inputs; shared with the M-27
    sensitivity suite and the ADR-027 ablation (which overrides the
    predictor set)."""
    schema = default_schema()
    mapping = load_mapping(REPO_ROOT / "configs" / "kelmarsh_scada.yaml", schema)
    predictors = tuple(
        sorted(
            spec.canonical
            for spec in mapping.columns.values()
            if schema.variable(spec.canonical).role is VariableRole.PREDICTOR
        )
    )
    targets = tuple(
        sorted(
            spec.canonical
            for spec in mapping.columns.values()
            if schema.variable(spec.canonical).role is VariableRole.TARGET
        )
    )
    windows, window_stats = alarm_windows(downloads)
    inputs = PipelineInputs(
        schema=schema,
        mapping=mapping,
        source_paths=tuple(turbine_data_paths(downloads)),
        feature=FeatureConfig(
            predictors=predictors_override if predictors_override is not None else predictors,
            targets=targets,
        ),
        split_spec=SplitSpec(
            strategy=SplitStrategy.EXPLICIT_DATES,
            train_end=TRAIN_END,
            validation_end=VALIDATION_END,
        ),
        flags=ExperimentFlags(thesis_official=True),
        cleaning_operations=(
            "drop_unparseable_timestamps",
            "drop_missing_any_target",
            # ADR-020: impossible predictor values become missing, then the
            # drop rule removes the row — in every partition, monitoring
            # included.
            "nullify_impossible_predictor_values",
            "drop_missing_any_predictor",
        ),
        alarm_windows=tuple(windows),
        modelling_span=SPAN,
        seeds={},
        supplier_note=supplier_note,
        limitations_path=limitations_path,
    )
    return inputs, window_stats


def three_period_rq1(result, schema, targets):
    """The ADR-022 three-period RQ1 table (CIs + DM per target).

    Shared with the ADR-027 nacelle ablation so both arms are computed by
    the identical machinery. Returns (rq1, dm, period_frames).
    """
    split = result.split
    cleaned = result.cleaned.frame
    boundary = split.boundaries_utc[0]
    healthy_frame = result.healthy.frame
    period_frames = {
        "validation": healthy_frame[healthy_frame[schema.timestamp_name] >= boundary],
        "monitoring_healthy": cleaned.loc[result.predictions["thesis_monitoring_healthy"].index],
        "test": cleaned.loc[split.test],
    }
    rq1: dict[str, dict] = {}
    dm: dict[str, dict] = {}
    for period, frame in period_frames.items():
        frame = frame.sort_values(schema.timestamp_name)
        losses: dict[str, np.ndarray] = {}
        for model_key in ("thesis", "baseline"):
            predictions = result.predictions[f"{model_key}_{period}"].loc[frame.index]
            for target in targets:
                actual = frame[target].to_numpy(dtype=float)
                predicted = predictions[target].to_numpy(dtype=float)
                keep = ~np.isnan(actual) & ~np.isnan(predicted)
                residual = actual[keep] - predicted[keep]
                rq1.setdefault(period, {}).setdefault(model_key, {})[target] = metric_cis(
                    residual, actual[keep]
                )
                losses[f"{model_key}_{target}"] = residual**2
        for target in targets:
            loss_thesis = losses[f"thesis_{target}"]
            loss_baseline = losses[f"baseline_{target}"]
            n = min(len(loss_thesis), len(loss_baseline))
            dm.setdefault(period, {})[target] = diebold_mariano(
                loss_thesis[:n], loss_baseline[:n]
            ).as_dict()
    return rq1, dm, period_frames


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--approved-by", required=False, default=None)
    parser.add_argument(
        "--downloads", type=Path, default=Path(r"C:\Users\mokhles.khedhri.993\Downloads")
    )
    parser.add_argument("--artifacts", type=Path, default=REPO_ROOT / "artifacts")
    args = parser.parse_args()
    if not args.approved_by:
        raise SystemExit(
            "REFUSING TO RUN: the predictor set, split dates, and alarm-window "
            "policy require author approval (pass --approved-by 'name date')."
        )

    schema = default_schema()
    print("Collecting status windows (Stop/Warning with populated ends)...")
    config = kelmarsh_config()
    inputs, window_stats = kelmarsh_inputs(
        args.downloads,
        supplier_note=(
            f"Kelmarsh Zenodo 10.5281/zenodo.5841833 (CC-BY-4.0); headline run under "
            f"ADR-018/020/021/022/023; approved by {args.approved_by}; split dates "
            f"ratified (ADR-023)"
        ),
        limitations_path=REPO_ROOT / "docs" / "LIMITATIONS.md",
    )
    windows = list(inputs.alarm_windows)
    targets = inputs.feature.targets
    print(f"  {len(windows)} alarm windows; {window_stats}")

    print("Running the pipeline (this is the long step)...")
    store = ArtifactStore(args.artifacts)
    experiment_id, result = run_experiment(config, inputs, store)
    directory = store.experiment_dir(experiment_id)
    print(f"Experiment {experiment_id} persisted at {directory}")

    # ---- RQ1: ADR-022 three-period table with CIs + DM per target ---------
    # Headline: monitoring_healthy. Validation is selection-biased after
    # ADR-021 tuning; unfiltered test is not an RQ1 measure. All three are
    # reported with labels (metrics.rq1 carries the designations).
    print("Computing blocked-bootstrap CIs and DM tests (three periods)...")
    rq1, dm, period_frames = three_period_rq1(result, schema, targets)

    # ---- EWMA detection on the monitoring period → coordinated → FMEA -----
    print("Detecting on the monitoring period and interpreting EVENT-001...")
    source = partition_for(config.residual.threshold_stats_source)
    detector = EwmaDetector(
        config.detection.ewma_lambda,
        ControlLimitSpec(
            sigma_multiplier=config.detection.control_limit_sigma,
            formulation=ControlLimitFormulation(config.detection.control_limit_formulation),
        ),
    )
    detector.fit_control_limits(
        result.residuals[config.residual.threshold_stats_source.value], source
    )
    series, detections = detector.detect(result.residuals["test"])

    event_result = evaluate_events(
        [EVENT_001],
        detections,
        window_days=config.evaluation.event_match_window_days,
        min_samples=config.detection.persistence_min_samples,
    )

    window_start = EVENT_001.start_utc - pd.Timedelta(
        days=config.evaluation.event_match_window_days
    )
    k1_detections = [d for d in detections if d.turbine == EVENT_001.turbine]
    k1_series = [s for s in series if s.turbine == EVENT_001.turbine]
    states = CoordinatedAnalyzer().combine(k1_detections, k1_series)
    in_window = [s for s in states if window_start <= s.timestamp_utc <= EVENT_001.end_utc]
    interpreter = FmeaInterpreter(FmeaKnowledgeBase.load(default_ruleset_path()))
    diagnostics = interpreter.interpret(in_window)
    rendering = None
    match = event_result.matches[0]
    if diagnostics:
        anchor = match.detection_time_utc
        chosen = next(
            (d for d in diagnostics if anchor is not None and d.timestamp_utc >= anchor),
            diagnostics[0],
        )
        rendering = chosen.render()

    # ---- ADR-022/ADR-023 check: EVENT-001 window vs the RQ1 slice ----------
    # The event window must be excluded from the healthy slice (alarm
    # periods) while remaining fully present in the detection stream.
    slice_frame = period_frames["monitoring_healthy"]
    turbine_column = schema.turbine_id_name
    timestamp_column = schema.timestamp_name

    def _rows_in_event_window(frame: pd.DataFrame) -> int:
        mask = (
            (frame[turbine_column].astype(str) == EVENT_001.turbine)
            & (frame[timestamp_column] >= EVENT_001.start_utc)
            & (frame[timestamp_column] <= EVENT_001.end_utc)
        )
        return int(mask.sum())

    event001_slice_check = {
        "event_window_utc": [str(EVENT_001.start_utc), str(EVENT_001.end_utc)],
        "slice_rows_in_event_window": _rows_in_event_window(slice_frame),
        "detection_rows_in_event_window": _rows_in_event_window(period_frames["test"]),
    }

    # ---- persist + print ---------------------------------------------------
    summary = {
        "experiment_id": experiment_id,
        "approved_by": args.approved_by,
        "alarm_window_stats": window_stats,
        "n_alarm_windows": len(windows),
        "rq1_headline_period": result.metrics["rq1"]["headline_period"],
        "rq1_period_labels": result.metrics["rq1"]["period_labels"],
        "rq1_metrics_with_cis": rq1,
        "dm_thesis_vs_baseline_squared_error": dm,
        "rq1_slice": {
            "monitoring_rows": result.metrics["rq1"]["monitoring_rows"],
            "monitoring_healthy_rows": result.metrics["rq1"]["monitoring_healthy_rows"],
            "retention_pct": result.metrics["rq1"]["monitoring_healthy_retention_pct"],
            "exclusions": result.metrics["rq1"]["monitoring_healthy_exclusions"],
        },
        "event001_slice_check": event001_slice_check,
        "tuning": {
            "configurations_evaluated": (
                result.fit_reports["thesis"].tuning_configurations_evaluated
            ),
            "selected_hyperparameters": dict(result.fit_reports["thesis"].hyperparameters),
            "trials": list(result.fit_reports["thesis"].tuning_trials),
        },
        "event_001": event_result.as_dict(),
        "seasonal_coverage": result.split.seasonal_coverage.as_dict(),
        "healthy_state": result.healthy_report.as_dict(),
        "cleaning": result.metrics["cleaning"],
        "in_control": result.in_control.as_dict() if result.in_control else None,
        "n_diagnostics_in_event_window": len(diagnostics),
    }
    (directory / "evaluation" / "first_run_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    if rendering is not None:
        (directory / "evaluation" / "event001_diagnostic.txt").write_text(
            rendering, encoding="utf-8"
        )

    print(json.dumps(summary, indent=2, default=str))
    if rendering:
        print("\n=== EVENT-001 diagnostic (operator view) ===")
        print(rendering)
    return 0


if __name__ == "__main__":
    sys.exit(main())
