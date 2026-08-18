"""M-27 sensitivity suite over the ten provisional parameters (PROJECT.md §27.3).

Design approved by the author 2026-08-13:
1. DEDUPE: identical resolved configs run once (config-hash cache), so the
   ten redundant base-value runs cost nothing (~21 unique full pipeline
   runs instead of 30).
2. EVENT-001 conclusion label RE-MATCHES 10 FA/turbine-year per
   configuration on that configuration's healthy validation block — a
   fixed multiplier would compare configurations at different effective
   sensitivities.
3. Conclusion labels, reported component-wise (a flip in ANY component
   flips the conclusion and auto-appends to LIMITATIONS.md per M-27):
   - rq1: slice ordering (XGBoost vs baseline RMSE) per target on the
     ADR-022 healthy monitoring slice;
   - event: EVENT-001 matched / unmatched / 10-per-ty-unreachable at the
     re-matched coordinated point (ADR-017 mechanics with the
     configuration's own window and persistence values);
   - incontrol: the M-20 material-inflation flag;
   - fleet: whether Kelmarsh 1 is the LARGEST responder (EWMA maximum,
     either target) in the fixed icing->detection window
     2019-02-03 04:00:30 -> 2019-02-11 17:10 (LIM-023 stability — the
     author must know if any configuration makes K1 the largest).
4. The ADR-027 nacelle ablation is a separate labelled run, NOT part of
   this suite (predictor-set ablations do not pass the grid-coverage
   guard, by design).

Each configuration is a full in-memory pipeline run (ingest -> clean ->
split -> healthy state -> ADR-021 tuning -> residuals -> EWMA ->
in-control -> ADR-022 slice) via run_pipeline; nothing is persisted per
configuration. Conclusion-flips append to docs/LIMITATIONS.md (M-27
acceptance 3); full outcomes land in evaluation/sensitivity_suite.json.
A configuration that raises is recorded as RUN_FAILED and the suite
continues.

Usage (from backend/):
    uv run python ../scripts/run_sensitivity_suite.py
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from app.core.config import AppConfig, config_hash  # noqa: E402
from app.core.versioning import capture_version_stamp  # noqa: E402
from app.data.schema import default_schema  # noqa: E402
from app.detection.matched_fpr import CoordinatedPipeline, matched_multiplier, sweep  # noqa: E402
from app.evaluation.events import EVENT_001  # noqa: E402
from app.evaluation.sensitivity import ApplicabilityCheck, run_sensitivity  # noqa: E402
from app.experiments.runner import PipelineInputs, run_pipeline  # noqa: E402
from app.residuals.ewma import ControlLimitFormulation, ControlLimitSpec, EwmaDetector  # noqa: E402
from app.residuals.normalization import partition_for  # noqa: E402
from run_kelmarsh_experiment import kelmarsh_config, kelmarsh_inputs  # noqa: E402

FPR_RUNG = 10.0  # ADR-025 rung, re-matched per configuration (approval item 2)
MULTIPLIER_GRID = (
    tuple(round(2.0 + 0.25 * i, 2) for i in range(17))
    + tuple(round(6.5 + 0.5 * i, 1) for i in range(12))
    + tuple(float(m) for m in range(13, 21))
)
ICING_WINDOW = (
    pd.Timestamp("2019-02-03 04:00:30", tz="UTC"),
    pd.Timestamp("2019-02-11 17:10:00", tz="UTC"),
)
EVENT_TURBINE = "Kelmarsh 1"


def _latest_experiment(artifacts: Path) -> str:
    """Newest EXP-* directory present, so the suite cannot default to a run
    that has since been deleted (the previous default named EXP-20260813-002,
    whose artifacts no longer exist)."""
    candidates = sorted(p.name for p in artifacts.glob("EXP-*") if p.is_dir())
    if not candidates:
        raise SystemExit(f"No experiment directories found under {artifacts}")
    return candidates[-1]


def persistent_starts(flags: pd.Series, min_samples: int) -> list[pd.Timestamp]:
    values = flags.to_numpy(dtype=bool)
    starts: list[pd.Timestamp] = []
    run = 0
    for i, alarmed in enumerate(values):
        if alarmed:
            run += 1
            if run == min_samples:
                starts.append(flags.index[i - min_samples + 1])
        else:
            run = 0
    return starts


def outcome_for(config: AppConfig, inputs: PipelineInputs) -> dict[str, object]:
    result = run_pipeline(config, inputs)
    nbm = result.metrics["nbm"]
    targets = sorted(nbm["thesis"]["monitoring_healthy"])
    rq1 = {
        target: (
            "xgb"
            if nbm["thesis"]["monitoring_healthy"][target]["rmse"]
            < nbm["baseline"]["monitoring_healthy"][target]["rmse"]
            else "baseline"
        )
        for target in targets
    }

    detector = EwmaDetector(
        config.detection.ewma_lambda,
        ControlLimitSpec(
            sigma_multiplier=3.0,
            formulation=ControlLimitFormulation(config.detection.control_limit_formulation),
        ),
    )
    source = config.residual.threshold_stats_source
    detector.fit_control_limits(result.residuals[source.value], partition_for(source))
    validation_series, _ = detector.detect(result.residuals["validation"])
    test_series, _ = detector.detect(result.residuals["test"])

    coordinated_val = CoordinatedPipeline("coordinated", validation_series, min_coordinated=None)
    curve = sweep(coordinated_val, list(MULTIPLIER_GRID))
    multiplier = matched_multiplier(curve, FPR_RUNG)
    if multiplier is None:
        event_label = "10ty_unreachable"
        lead_minutes: float | None = None
    else:
        coordinated_test = CoordinatedPipeline("coordinated", test_series, min_coordinated=None)
        flags = coordinated_test.alarm_flags(multiplier)[EVENT_TURBINE]
        window_start = EVENT_001.start_utc - pd.Timedelta(
            days=config.evaluation.event_match_window_days
        )
        starts = [
            t
            for t in persistent_starts(flags, config.detection.persistence_min_samples)
            if window_start <= t <= EVENT_001.start_utc
        ]
        if starts:
            event_label = "matched"
            lead_minutes = float((EVENT_001.start_utc - starts[0]).total_seconds() / 60.0)
        else:
            event_label = "unmatched"
            lead_minutes = None

    fleet_max: dict[str, dict[str, float]] = {}
    for stream in test_series:
        mask = (stream.timestamps >= ICING_WINDOW[0]) & (stream.timestamps <= ICING_WINDOW[1])
        segment = stream.values[mask.to_numpy()]
        if len(segment):
            fleet_max.setdefault(stream.target, {})[stream.turbine] = float(segment.max())
    largest = {target: max(values, key=values.get) for target, values in fleet_max.items()}
    k1_largest = any(turbine == EVENT_TURBINE for turbine in largest.values())

    in_control = result.in_control
    label = (
        "|".join(f"rq1_{t.split('_')[1]}={rq1[t]}" for t in targets)
        + f"|event={event_label}"
        + f"|incontrol={'inflated' if in_control.materially_inflated else 'ok'}"
        + f"|fleet={'k1_largest' if k1_largest else 'k1_not_largest'}"
    )
    return {
        "label": label,
        "rq1_slice_ordering": rq1,
        "event": {
            "label": event_label,
            "rematched_multiplier": multiplier,
            "lead_minutes": lead_minutes,
            "window_days": config.evaluation.event_match_window_days,
            "persistence_min_samples": config.detection.persistence_min_samples,
        },
        "in_control_rate": float(in_control.empirical_rate),
        "in_control_inflated": bool(in_control.materially_inflated),
        "fleet_largest_responder": largest,
        "fleet_icing_window_ewma_max": fleet_max,
        "slice_rmse_bearing": float(
            nbm["thesis"]["monitoring_healthy"]["gearbox_bearing_temperature"]["rmse"]
        ),
        "slice_rmse_oil": float(
            nbm["thesis"]["monitoring_healthy"]["gearbox_oil_temperature"]["rmse"]
        ),
    }


def applicability_checks(inputs: PipelineInputs) -> dict[str, ApplicabilityCheck]:
    """Which provisional parameters actually have a lever on THIS run (ADR-040).

    Applicability depends on the run's inputs, not only its configuration, so
    it is decided here where the inputs are known rather than inside the
    generic suite.

    On the Kelmarsh holdings five of the thirteen provisional parameters have
    no lever: the dataset carries no maintenance-confirmed failures (LIM-002),
    so no caller constructs fault or maintenance exclusion windows; and
    ADR-018 disabled step-change exclusion, so its three parameters are inert
    except in the arm that switches it back on. Before this, all five reported
    identical outcomes and were labelled STABLE.
    """
    no_fault_windows = not inputs.fault_windows
    no_maintenance_windows = not inputs.maintenance_windows

    def gated_on_fault_windows(_: AppConfig) -> str | None:
        return (
            "No fault exclusion windows are supplied for this dataset: it "
            "carries no maintenance-confirmed failures (LIM-002/ADR-013), so "
            "the pre-fault window has nothing to act on."
            if no_fault_windows
            else None
        )

    def gated_on_maintenance_windows(_: AppConfig) -> str | None:
        return (
            "No maintenance exclusion windows are supplied for this dataset "
            "(LIM-002: the exports carry no maintenance records), so the "
            "post-maintenance window has nothing to act on."
            if no_maintenance_windows
            else None
        )

    def gated_on_step_change_exclusion(config: AppConfig) -> str | None:
        return (
            "healthy_state.exclude_step_changes is False (ADR-018), so the "
            "step-change detector reports without excluding and this "
            "parameter cannot change the healthy population."
            if not config.healthy_state.exclude_step_changes
            else None
        )

    return {
        "healthy_state.fault_pre_exclusion_days": gated_on_fault_windows,
        "healthy_state.maintenance_post_exclusion_days": gated_on_maintenance_windows,
        "healthy_state.step_change_exclusion_days": gated_on_step_change_exclusion,
        "validation.step_change_window_samples": gated_on_step_change_exclusion,
        "validation.step_change_min_magnitude_c": gated_on_step_change_exclusion,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    # Repo-relative, matching run_kelmarsh_experiment.py. The previous default
    # pointed at a different machine's Downloads directory, so the script could
    # not run anywhere but its author's workstation.
    parser.add_argument("--downloads", type=Path, default=REPO_ROOT / "dataset")
    parser.add_argument("--artifacts", type=Path, default=REPO_ROOT / "artifacts")
    parser.add_argument(
        "--experiment",
        default=None,
        help="Experiment directory to write into; defaults to the latest present.",
    )
    args = parser.parse_args()
    experiment = args.experiment or _latest_experiment(args.artifacts)
    out_dir = args.artifacts / experiment / "evaluation"
    if not out_dir.is_dir():
        raise SystemExit(f"Experiment evaluation directory not found: {out_dir}")

    base_config = kelmarsh_config()
    inputs, _stats = kelmarsh_inputs(
        args.downloads,
        supplier_note=(
            "M-27 sensitivity suite over the EXP-20260813-002 base configuration "
            "(in-memory runs; nothing persisted per configuration)"
        ),
        limitations_path=None,  # only conclusion-FLIPS append (M-27), via append_flips
    )

    cache: dict[str, dict[str, object]] = {}
    calls: list[dict[str, object]] = []

    def cached_runner(config: AppConfig) -> dict[str, object]:
        key = config_hash(config)
        if key not in cache:
            print(f"[{datetime.now(UTC).isoformat(timespec='seconds')}] run {key[:10]}...")
            try:
                cache[key] = outcome_for(config, inputs)
            except Exception as error:
                traceback.print_exc()
                cache[key] = {
                    "label": f"RUN_FAILED:{type(error).__name__}",
                    "error": str(error),
                    "in_control_rate": float("nan"),
                    "slice_rmse_bearing": float("nan"),
                    "slice_rmse_oil": float("nan"),
                }
        calls.append({"config_hash": key})
        return cache[key]

    report = run_sensitivity(
        base_config,
        cached_runner,
        lambda outcome: str(outcome["label"]),
        applicability=applicability_checks(inputs),
    )

    lim_ids = report.append_flips(
        REPO_ROOT / "docs" / "LIMITATIONS.md",
        source=f"M-27 sensitivity suite, {experiment} base configuration",
    )

    schema = default_schema()
    payload = {
        "experiment_id": experiment,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "design": {
            "approved_by": "author, 2026-08-13 (dedupe; per-config re-match at 10 FA/ty; "
            "four conclusion labels component-wise; nacelle ablation separate per ADR-027)",
            "fpr_rung_rematched_per_config": FPR_RUNG,
            "icing_window_utc": [str(ICING_WINDOW[0]), str(ICING_WINDOW[1])],
            "multiplier_grid_max": MULTIPLIER_GRID[-1],
        },
        "unique_runs": len(cache),
        "runner_calls": len(calls),
        "report": report.as_dict(),
        "outcomes_by_config_hash": cache,
        "conclusion_flip_lim_ids": lim_ids,
        "environment": capture_version_stamp(schema_version=schema.schema_version).model_dump(),
    }
    out_path = out_dir / "sensitivity_suite.json"
    out_path.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")

    print(f"\nUnique runs: {len(cache)} of {len(calls)} runner calls")
    for sweep_result in report.sweeps:
        print(f"\n{sweep_result.parameter} [{sweep_result.status}]")
        if sweep_result.inapplicable_reason:
            print(f"  (no lever on this run) {sweep_result.inapplicable_reason}")
        for value, conclusion in zip(sweep_result.values, sweep_result.conclusions, strict=True):
            print(f"  {value}: {conclusion}")
    if report.inapplicable_parameters():
        print(
            "\nNOT APPLICABLE (identical outcomes are not robustness evidence): "
            f"{list(report.inapplicable_parameters())}"
        )
    if lim_ids:
        print(f"\nConclusion-flip register entries appended: {lim_ids}")
    print(f"\nWritten to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
