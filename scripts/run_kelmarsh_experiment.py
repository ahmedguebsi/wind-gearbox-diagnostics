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
    uv run python ../scripts/run_kelmarsh_experiment.py --approved-by "AG 2026-08-17"
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import AppConfig, HealthyStateConfig, ManualExclusionWindow  # noqa: E402
from app.data.guards import FeatureConfig  # noqa: E402
from app.data.healthy_state import (  # noqa: E402
    ExclusionWindow,
    deduplicate_exclusion_windows,
)
from app.data.mapping import load_mapping  # noqa: E402
from app.data.schema import (  # noqa: E402
    SCHEMA_VERSION,
    CanonicalSchema,
    VariableRole,
    default_schema,
)
from app.data.splitting import ExperimentFlags, SplitSpec, SplitStrategy  # noqa: E402
from app.detection.coordinated import CoordinatedAnalyzer  # noqa: E402
from app.evaluation.bootstrap import PanelBlockedBootstrap  # noqa: E402
from app.evaluation.dm_test import (  # noqa: E402
    diebold_mariano,
    diebold_mariano_by_turbine,
)
from app.evaluation.event_eval import evaluate_events  # noqa: E402
from app.evaluation.events import EVENT_001, StatusValue, parse_status_csv  # noqa: E402
from app.experiments.runner import (  # noqa: E402
    THESIS_KEY,
    PipelineInputs,
    PipelineResult,
    assert_reproducible_code_state,
    run_experiment,
)
from app.experiments.store import ArtifactStore  # noqa: E402
from app.fmea.interpreter import FmeaInterpreter  # noqa: E402
from app.fmea.knowledge_base import FmeaKnowledgeBase, default_ruleset_path  # noqa: E402
from app.models.metrics import residual  # noqa: E402
from app.residuals.ewma import ControlLimitFormulation, ControlLimitSpec, EwmaDetector  # noqa: E402
from app.residuals.normalization import partition_for  # noqa: E402

SPAN = (date(2016, 5, 3), date(2021, 6, 30))  # ADR-009
TRAIN_END = date(2018, 7, 1)  # RATIFIED (ADR-023, closes D-07)
VALIDATION_END = date(2019, 2, 1)  # 9.7 d before the ADR-017 window opens (ADR-023)
STATUS_SKIP_LINES = 9

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
    # ADR-033(b): folder boundaries overlap, so the same Stop/Warning record
    # can be read twice and yield the same window twice. Idempotent over the
    # row mask, so the healthy population is unchanged - but the count and the
    # stored metadata were double-counting.
    windows_tuple, duplicate_windows = deduplicate_exclusion_windows(windows)
    windows = list(windows_tuple)
    stats: dict[str, object] = {
        "duplicate_windows_removed": duplicate_windows,
        "status_rows_seen": n_rows,
        "stop_warning_without_end": skipped_no_end,
        "rows_rejected_by_constructor": len(rejected),
        "rejected_examples": rejected[:5],
    }
    return windows, stats


def metric_cis(
    residuals_by_turbine: dict[str, np.ndarray],
    actual: np.ndarray,
    *,
    n_boot: int,
    seed: int,
) -> dict[str, Any]:
    """PANEL blocked-bootstrap CIs for RMSE/MAE/bias, plus R² via the
    fixed-denominator approximation (variance of actuals held at its sample
    value — a documented approximation, labelled in the output).

    ADR-038 / METHODOLOGY_REVIEW P-3: each turbine is resampled in blocks whose
    length comes from ITS OWN autocorrelation, then the panel is reassembled
    and the fleet statistic evaluated. Previously the bootstrap ran on the
    pooled interleaved series, where a block spanned six machines and the
    block length inflated roughly sixfold — the unfiltered-test baseline drew
    six blocks per replicate. Per-unit block counts are reported so that
    failure mode is visible rather than latent.
    """
    bootstrap = PanelBlockedBootstrap(n_boot, seed)
    var_actual = float(np.var(actual))
    statistics: dict[str, Callable[[np.ndarray], float]] = {
        "rmse": lambda r: float(np.sqrt(np.mean(r**2))),
        "mae": lambda r: float(np.mean(np.abs(r))),
        "bias": lambda r: float(np.mean(r)),
        "r2_fixed_denominator": lambda r: float(1.0 - np.mean(r**2) / var_actual),
    }
    out: dict[str, Any] = {}
    for name, stat in statistics.items():
        ci = bootstrap.ci(residuals_by_turbine, stat)
        payload = ci.as_dict()
        out[name] = {
            "point": payload["point"],
            "lower": payload["lower"],
            "upper": payload["upper"],
            "reliable": payload["reliable"],
            "caveat": payload["caveat"],
        }
        out.setdefault("bootstrap", payload["per_unit"])
        out.setdefault("min_blocks", {"value": payload["min_blocks"]})
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


def three_period_rq1(
    result: PipelineResult,
    schema: CanonicalSchema,
    targets: tuple[str, ...],
    config: AppConfig | None = None,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, pd.DataFrame],
]:
    """The ADR-022 three-period RQ1 table (CIs + DM per target).

    Shared with the ADR-027 nacelle ablation so both arms are computed by
    the identical machinery. Returns (rq1, dm, period_frames).

    ``config`` supplies the bootstrap seed and replicate count, which ADR-044
    lifted out of module constants and into the resolved configuration so they
    reach experiment metadata like every other stochastic component (§15).
    """
    evaluation = (config or kelmarsh_config()).evaluation
    n_boot, seed = evaluation.bootstrap_replicates, evaluation.bootstrap_seed
    split = result.split
    cleaned = result.cleaned.frame
    boundary = split.boundaries_utc[0]
    healthy_frame = result.healthy.frame
    period_frames = {
        "validation": healthy_frame[healthy_frame[schema.timestamp_name] >= boundary],
        "monitoring_healthy": cleaned.loc[result.predictions["thesis_monitoring_healthy"].index],
        "test": cleaned.loc[split.test],
    }
    turbine_column = schema.turbine_id_name
    rq1: dict[str, dict[str, Any]] = {}
    dm: dict[str, dict[str, Any]] = {}
    for period, frame in period_frames.items():
        frame = frame.sort_values(schema.timestamp_name)
        # ADR-032 requires three-model comparison tables. Iterating the fitted
        # model set rather than a hard-coded pair is what makes that true: the
        # Elastic Net reference previously appeared in metrics.json as bare
        # point estimates and never reached the CI/DM table at all, so the
        # non-linearity-versus-regularisation question it was admitted to
        # answer could not be answered with an interval.
        model_keys = [k for k in result.models if f"{k}_{period}" in result.predictions]
        predicted_by_model = {
            model_key: result.predictions[f"{model_key}_{period}"].loc[frame.index]
            for model_key in model_keys
        }
        turbines_all = frame[turbine_column].astype(str).to_numpy()
        for target in targets:
            actual = frame[target].to_numpy(dtype=float)
            # ONE mask across ALL models. Masking per model and then
            # truncating to the shorter series would pair mismatched
            # observations whenever the models' missing patterns differ.
            keep = ~np.isnan(actual)
            for predictions in predicted_by_model.values():
                keep &= ~np.isnan(predictions[target].to_numpy(dtype=float))

            turbines = turbines_all[keep]
            losses: dict[str, np.ndarray] = {}
            for model_key, predictions in predicted_by_model.items():
                errors = residual(actual[keep], predictions[target].to_numpy(dtype=float)[keep])
                rq1.setdefault(period, {}).setdefault(model_key, {})[target] = metric_cis(
                    {t: errors[turbines == t] for t in sorted(set(turbines))},
                    actual[keep],
                    n_boot=n_boot,
                    seed=seed,
                )
                losses[model_key] = errors**2

            # ADR/P-3: the pooled series interleaves six turbines at every
            # 10-minute stamp, so a single test treats contemporaneous
            # cross-turbine observations as sequential ones and the default
            # lag rule covers a fraction of the real dependence. Both are
            # reported: the pooled figure is what was previously published,
            # so the change is quantified rather than silently substituted.
            #
            # One comparison per BASELINE, per PROJECT.md §19 ("XGBoost vs.
            # EACH baseline, per target"). Only the OLS pairing was computed
            # before, so the Elastic Net reference had no significance test.
            for other in sorted(k for k in losses if k != THESIS_KEY):
                dm.setdefault(period, {}).setdefault(target, {})[f"thesis_vs_{other}"] = {
                    "pooled_interleaved": diebold_mariano(
                        losses[THESIS_KEY], losses[other]
                    ).as_dict(),
                    "per_turbine": diebold_mariano_by_turbine(
                        losses[THESIS_KEY], losses[other], turbines
                    ).as_dict(),
                    "note": (
                        "per_turbine is the defensible figure; pooled_interleaved "
                        "is retained only so the correction can be measured. A "
                        "negative statistic favours the thesis model."
                    ),
                }
    return rq1, dm, period_frames


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--approved-by", required=False, default=None)
    # Repo-relative: the holdings are gitignored (4.5 GB) but obtainable from
    # the DOI, so a checkout plus the Zenodo download reproduces the run
    # without editing the script. Overridable for a copy held elsewhere.
    parser.add_argument("--downloads", type=Path, default=REPO_ROOT / "dataset")
    parser.add_argument("--artifacts", type=Path, default=REPO_ROOT / "artifacts")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Run despite an uncommitted working tree (exploratory runs only).",
    )
    args = parser.parse_args()
    if not args.approved_by:
        raise SystemExit(
            "REFUSING TO RUN: the predictor set, split dates, and alarm-window "
            "policy require author approval (pass --approved-by 'name date')."
        )

    schema = default_schema()
    # ADR-044: refuse before the ~16-minute pipeline, not after it. The
    # previous headline run (EXP-20260817-001) was executed from a dirty tree,
    # so the commit recorded in its metadata does not name the code that
    # produced it.
    assert_reproducible_code_state(schema.schema_version, allow_dirty=args.allow_dirty)
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
    rq1, dm, period_frames = three_period_rq1(result, schema, targets, config)

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
    event_end = EVENT_001.end_utc
    if event_end is None:  # registered with a concrete end; fail loudly if that changes
        raise SystemExit("EVENT-001 has no recorded end; cannot bound the diagnostic window")
    in_window = [s for s in states if window_start <= s.timestamp_utc <= event_end]
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
