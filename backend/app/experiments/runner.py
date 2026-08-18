"""Pipeline orchestration (M-30; PROJECT.md §36, ARCHITECTURE.md §7).

Executes the pipeline from one resolved configuration: guard validation →
ingest → validate → clean → healthy-state → chronological split (+seasonal
coverage) → NBM fit (thesis + baseline) → predictions → residuals →
normalization (Guard 4) → EWMA + control limits (PRIMARY, LOCKED-02) →
in-control characterization, and persists every artifact through the store
(M-29). This is the only module that imports every scientific layer.

Fail-early ordering (M-30 acceptance 2): the causal-separation chokepoint
(Guards 1/2/8) and the split-policy guard (Guard 3) run BEFORE any data is
read, and nothing is persisted unless the whole pipeline succeeds — a guard
failure therefore aborts with no partial artifacts. Guard 4 fires inside the
normalization stage before any threshold statistic is fitted.

LIMITATIONS.md auto-append (M-20 acceptance 2): a materially inflated
empirical in-control false-alarm rate appends its entry during the
PERSISTENCE phase only (run_experiment), never inside run_pipeline — so
reproduction re-runs cannot grow the register.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.core.config import (
    AppConfig,
    NormalizationMethod,
    TuningSelection,
    config_hash,
    resolved_dict,
)
from app.core.errors import ConfigError
from app.core.limitations import append_limitation
from app.core.logging import buffered_logs, experiment_logging, get_logger
from app.core.time import utc_now
from app.core.versioning import capture_version_stamp
from app.data.cleaning import CleaningAudit, clean, impossible_predictor_rows
from app.data.guards import FeatureConfig, validate_feature_configuration
from app.data.healthy_state import ExclusionWindow, HealthyStateBuilder, HealthyStateReport
from app.data.ingestion import CanonicalDataset, ingest_files
from app.data.mapping import ColumnMapping
from app.data.schema import (
    ACTIVE_POWER,
    AMBIENT_TEMPERATURE,
    WIND_SPEED,
    CanonicalSchema,
)
from app.data.splitting import (
    ExperimentFlags,
    Split,
    SplitPolicyGuard,
    SplitSpec,
    inner_chronological_holdout,
    split_chronologically,
)
from app.data.validation import DatasetReport, default_rules, validate
from app.evaluation.residual_diagnostics import (
    cross_target_correlation,
    per_turbine_residual_stats,
)
from app.experiments.store import ArtifactStore
from app.experiments.tracker import (
    DatasetMetadata,
    ExclusionsMetadata,
    ExclusionWindowRecord,
    ExperimentFlagsRecord,
    ExperimentRecord,
    GuardAttestations,
    ModelMetadata,
    MultipleComparisonRegister,
    SplitMetadata,
)
from app.models.base import (
    FitReport,
    NormalBehaviourModel,
    adopt_tuned_iteration_count,
    fit_model,
    tune_model,
)
from app.models.metrics import compute_per_target, condition_diagnostics
from app.models.registry import create as create_model
from app.residuals.engine import ResidualFrame, compute_residuals
from app.residuals.ewma import (
    ControlLimitFormulation,
    ControlLimitSpec,
    EwmaDetector,
    GapHandling,
    InControlReport,
)
from app.residuals.fleet import fleet_relative_residuals
from app.residuals.normalization import make_normalizer, partition_for

_logger = get_logger("experiments.runner")

#: Guards exercised by the full pipeline. G5 lives inside healthy-state
#: (WARNING findings); G6/G7 attach with exports and FMEA.
PIPELINE_GUARDS: tuple[str, ...] = ("G1", "G2", "G3", "G4", "G8")

THESIS_KEY = "thesis"
BASELINE_KEY = "baseline"
BASELINE_MODEL_NAME = "linear_regression"


@dataclass(frozen=True)
class PipelineInputs:
    """Everything a run needs beyond the resolved AppConfig."""

    schema: CanonicalSchema
    mapping: ColumnMapping
    source_paths: tuple[Path, ...]
    feature: FeatureConfig
    split_spec: SplitSpec
    flags: ExperimentFlags = field(default_factory=ExperimentFlags)
    cleaning_operations: tuple[str, ...] = ()
    fault_windows: tuple[ExclusionWindow, ...] = ()
    alarm_windows: tuple[ExclusionWindow, ...] = ()
    maintenance_windows: tuple[ExclusionWindow, ...] = ()
    modelling_span: tuple[date | None, date | None] = (None, None)
    seeds: dict[str, int] | None = None
    supplier_note: str = ""
    #: When set, material in-control inflation appends its entry here during
    #: persistence (M-20 acceptance 2). None = entry text lands in artifacts
    #: only.
    limitations_path: Path | None = None


@dataclass(frozen=True)
class PipelineResult:
    """In-memory outputs of one pipeline run (persisted via the store)."""

    cleaned: CanonicalDataset
    healthy: CanonicalDataset
    dataset_report: DatasetReport
    cleaning_audit: CleaningAudit
    healthy_report: HealthyStateReport
    split: Split
    models: dict[str, NormalBehaviourModel]
    fit_reports: dict[str, FitReport]
    predictions: dict[str, pd.DataFrame]
    residuals: dict[str, ResidualFrame]
    normalizer_stats: dict[str, Any]
    in_control: InControlReport | None
    metrics: dict[str, Any]
    #: Descriptive residual diagnostics per partition (read-only).
    residual_diagnostics: dict[str, Any] = field(default_factory=dict)
    #: PROJECT.md §20 condition-sliced error tables (read-only).
    condition_diagnostics: dict[str, Any] = field(default_factory=dict)


def _cleaning_metrics(
    audit: CleaningAudit,
    cleaned: CanonicalDataset,
    dataset: CanonicalDataset,
    inputs: PipelineInputs,
    split: Split,
) -> dict[str, Any]:
    """Cleaning metrics. When the ADR-020 policy is active, the rows dropped
    for impossible predictor values are counted per split partition, so the
    number is stated rather than inferred from audit arithmetic."""
    metrics: dict[str, Any] = {
        "rows_removed": audit.total_removed,
        "rows_after": len(cleaned.frame),
    }
    if "nullify_impossible_predictor_values" not in inputs.cleaning_operations:
        return metrics
    mask = impossible_predictor_rows(dataset.frame, inputs.schema)
    stamps = dataset.frame.loc[mask, inputs.schema.timestamp_name].dropna()
    train_boundary, test_boundary = split.boundaries_utc
    counts = {"train": 0, "validation": 0, "test": 0}
    if train_boundary is not None and test_boundary is not None:
        counts["train"] = int((stamps < train_boundary).sum())
        counts["validation"] = int(((stamps >= train_boundary) & (stamps < test_boundary)).sum())
        counts["test"] = int((stamps >= test_boundary).sum())
    metrics["impossible_predictor_rows_dropped_total"] = int(mask.sum())
    metrics["impossible_predictor_rows_dropped_by_partition"] = counts
    return metrics


def assert_reproducible_code_state(schema_version: str, *, allow_dirty: bool = False) -> None:
    """ADR-044: a citable run needs a recoverable code state.

    ``metadata.json`` records the git commit so a result can be regenerated
    from the code that produced it. When the working tree is dirty that
    promise is void — the commit names code that is not what ran, and the
    difference is unrecorded. EXP-20260817-001, the RQ1 headline, carries
    ``git_dirty: true``.

    Called by the run DRIVERS rather than by the pipeline, because that is
    where the intent to produce a citable result is declared (the Kelmarsh
    script already refuses to start without ``--approved-by``). Putting it in
    the library would also block the in-memory sweeps and the test suite,
    neither of which produces a thesis artifact.
    """
    if allow_dirty:
        return
    stamp = capture_version_stamp(schema_version=schema_version)
    if stamp.git_dirty:
        raise SystemExit(
            "REFUSING TO RUN: the working tree is dirty, so this run could not "
            "be reproduced from the commit its metadata would record "
            f"({stamp.git_commit[:10]}; PROJECT.md §15). Commit or stash the "
            "changes, or pass --allow-dirty for an explicitly exploratory run."
        )


def run_pipeline(config: AppConfig, inputs: PipelineInputs) -> PipelineResult:
    """Run the full pipeline in memory. Raises on any guard violation."""
    # Guards fire before any file is opened (fail-early, M-30 acceptance 2).
    validate_feature_configuration(inputs.feature, inputs.schema)
    SplitPolicyGuard().validate(inputs.split_spec, inputs.flags)
    if config.residual.normalization is NormalizationMethod.CONDITION_BINNED:
        raise ConfigError(
            "condition_binned normalization is not wired into the runner yet: "
            "the condition column choice is a D-12 heteroscedasticity decision, "
            "not a default (PROJECT.md §22)"
        )

    span_start, span_end = inputs.modelling_span
    dataset = ingest_files(
        list(inputs.source_paths),
        inputs.mapping,
        inputs.schema,
        span_start=span_start,
        span_end=span_end,
        supplier_note=inputs.supplier_note,
    )
    dataset_report = validate(dataset, inputs.schema, default_rules(config.validation))
    cleaned, audit = clean(dataset, inputs.schema, list(inputs.cleaning_operations))

    # PROJECT.md §14: healthy training period → healthy validation period →
    # test/monitoring period. The chronological split is computed on the
    # CLEANED data; healthy-state construction applies to the train and
    # validation periods only, and the TEST partition is the UNFILTERED
    # monitoring period — anomalous rows there are the signal being
    # monitored, never excluded.
    split = split_chronologically(cleaned, inputs.schema, inputs.split_spec, inputs.flags)
    train_boundary, _ = split.boundaries_utc
    if train_boundary is None:
        raise ConfigError("Split produced no training/validation boundary")

    timestamp = inputs.schema.timestamp_name
    pre_monitoring = cleaned.frame.loc[split.train.union(split.validation)]
    builder = HealthyStateBuilder(config.healthy_state, inputs.schema)
    healthy, healthy_report = builder.build(
        cleaned.with_frame(pre_monitoring.reset_index(drop=True), stage="pre_monitoring"),
        fault_windows=list(inputs.fault_windows),
        alarm_windows=list(inputs.alarm_windows),
        maintenance_windows=list(inputs.maintenance_windows),
        step_changes=dataset_report.step_changes,
    )
    healthy_frame = healthy.frame
    partitions = {
        "training": healthy_frame[healthy_frame[timestamp] < train_boundary],
        "validation": healthy_frame[healthy_frame[timestamp] >= train_boundary],
        "test": cleaned.frame.loc[split.test],
    }
    for name, frame in partitions.items():
        if frame.empty:
            raise ConfigError("Split partition is empty; cannot fit or monitor", partition=name)

    models, fit_reports, predictions = _fit_and_predict(config, inputs, partitions)
    residual_frames, normalizer_stats, in_control, detection_metrics = _residual_stages(
        config, inputs, partitions, predictions
    )
    residual_diagnostics = _residual_diagnostics(residual_frames)

    # ADR-022: the RQ1 headline is the healthy-filtered monitoring slice —
    # a METRICS path only. Detection, residuals, EWMA, and all RQ2/RQ3
    # evaluation above consumed the FULL unfiltered test partition
    # (PROJECT.md §14); the slice is computed after them and feeds nothing
    # back. Slice predictions are row-subsets of the already-computed test
    # predictions, so the models are never re-run.
    monitoring_healthy_frame, slice_report = _monitoring_healthy_slice(
        config, inputs, cleaned, split, dataset_report
    )
    for key in models:
        predictions[f"{key}_monitoring_healthy"] = predictions[f"{key}_test"].loc[
            monitoring_healthy_frame.index
        ]
    metrics_partitions = {**partitions, "monitoring_healthy": monitoring_healthy_frame}

    metrics: dict[str, Any] = {
        "ingestion": {
            "rows": len(dataset.frame),
            "duplicates_removed": (
                dataset.deduplication.duplicates_removed if dataset.deduplication else 0
            ),
        },
        "validation": {
            "errors": len(dataset_report.errors),
            "warnings": len(dataset_report.warnings),
            "step_changes": len(dataset_report.step_changes),
        },
        "cleaning": _cleaning_metrics(audit, cleaned, dataset, inputs, split),
        "healthy_state": {
            "accepted": healthy_report.accepted,
            "excluded": healthy_report.excluded,
            "retention_pct": healthy_report.retention_pct,
        },
        "split": {
            "train": len(split.train),
            "validation": len(split.validation),
            "test": len(split.test),
            "healthy_training": len(partitions["training"]),
            "healthy_validation": len(partitions["validation"]),
            "test_is_unfiltered_monitoring": True,
            "seasonal_warnings": len(split.seasonal_coverage.warnings),
        },
        "nbm": _nbm_metrics(inputs, metrics_partitions, predictions, list(models)),
        "rq1": {
            "headline_period": "monitoring_healthy",
            "period_labels": {
                "validation": "selection-biased after tuning (ADR-021)",
                "monitoring_healthy": "RQ1 HEADLINE (ADR-022)",
                "test": (
                    "conflates model error with anomalous operation and "
                    "LIM-013 confounds; not an RQ1 measure"
                ),
            },
            "monitoring_rows": len(partitions["test"]),
            "monitoring_healthy_rows": len(monitoring_healthy_frame),
            "monitoring_healthy_retention_pct": round(
                100.0 * len(monitoring_healthy_frame) / len(partitions["test"]), 4
            ),
            "monitoring_healthy_exclusions": slice_report.exclusion_counts,
        },
        "detection": detection_metrics,
        "residual_diagnostics": _residual_diagnostics_summary(residual_diagnostics),
    }
    condition_tables = _condition_diagnostics(inputs, metrics_partitions, predictions, list(models))
    return PipelineResult(
        cleaned=cleaned,
        healthy=healthy,
        dataset_report=dataset_report,
        cleaning_audit=audit,
        healthy_report=healthy_report,
        split=split,
        models=models,
        fit_reports=fit_reports,
        predictions=predictions,
        residuals=residual_frames,
        normalizer_stats=normalizer_stats,
        in_control=in_control,
        metrics=metrics,
        residual_diagnostics=residual_diagnostics,
        condition_diagnostics=condition_tables,
    )


def _per_target_rmse(
    frame: pd.DataFrame, predicted: pd.DataFrame, targets: tuple[str, ...]
) -> dict[str, float]:
    return {
        target: float(
            np.sqrt(np.mean((frame[target].to_numpy() - predicted[target].to_numpy()) ** 2))
        )
        for target in targets
    }


def _fit_and_predict(
    config: AppConfig, inputs: PipelineInputs, partitions: dict[str, pd.DataFrame]
) -> tuple[dict[str, NormalBehaviourModel], dict[str, FitReport], dict[str, pd.DataFrame]]:
    """Fit thesis (+ baseline) through the M-15/ADR-021 chokepoints;
    predict val/test.

    Training-partition predictions are also produced because the ADR-001
    ``threshold_stats_source: training`` branch fits its statistics there.
    The baseline fits first: the ADR-021 selection rule normalises each
    target's candidate RMSE by the baseline's validation RMSE.
    """
    seed = config.model.seed
    tuning = config.model.tuning
    predictors = list(inputs.feature.predictors)
    models: dict[str, NormalBehaviourModel] = {}
    fit_reports: dict[str, FitReport] = {}
    predictions: dict[str, pd.DataFrame] = {}

    if config.model.include_baseline:
        # ADR-032: OLS keeps the historical ``baseline`` key — it is the fixed
        # zero-hyperparameter reference whose validation RMSE normalises every
        # tuned model's selection score. Further baselines are keyed by model
        # name. Baseline residuals are never thresholded (RQ1 context only).
        for baseline_name in config.model.baselines:
            key = BASELINE_KEY if baseline_name == BASELINE_MODEL_NAME else baseline_name
            baseline = create_model(baseline_name)
            models[key] = baseline
            fit_reports[key] = fit_model(
                baseline, partitions["training"], inputs.feature, inputs.schema, seed=seed
            )
            for partition, frame in partitions.items():
                if partition == "training":
                    continue
                predictions[f"{key}_{partition}"] = baseline.predict(frame[predictors])
        if BASELINE_KEY not in models:
            raise ConfigError(
                "The OLS reference must be among model.baselines: it is the "
                "zero-hyperparameter denominator every tuned model's selection "
                "score divides by (ADR-021/ADR-032)",
                baselines=list(config.model.baselines),
            )

    thesis_hyperparameters = dict(config.model.hyperparameters)
    if tuning.enabled:
        # ADR-021 fixed values govern the search; candidates sweep the rest.
        thesis_hyperparameters["n_estimators"] = tuning.n_estimators
        thesis_hyperparameters["colsample_bytree"] = tuning.colsample_bytree
    thesis = create_model(
        config.model.name,
        hyperparameters=thesis_hyperparameters,
        multi_output=config.model.multi_output,
    )
    models[THESIS_KEY] = thesis
    if tuning.enabled:
        # ADR-030: selection happens on an inner holdout carved from the END of
        # TRAIN, never on the healthy VALIDATION block. VALIDATION supplies the
        # M-20 in-control characterisation and, under one ADR-001 branch, the
        # threshold statistics; scoring candidates there would calibrate
        # detection thresholds on data the model was selected to fit well, and
        # bias the measured in-control false-alarm rate downward.
        timestamp = inputs.schema.timestamp_name
        inner_fit_index, inner_score_index = inner_chronological_holdout(
            partitions["training"], timestamp, tuning.inner_holdout_fraction
        )
        inner_fit = partitions["training"].loc[inner_fit_index]
        inner_score = partitions["training"].loc[inner_score_index]

        baseline_rmse: dict[str, float] | None = None
        if tuning.selection is TuningSelection.BASELINE_NORMALIZED_MEAN_RMSE:
            if not config.model.include_baseline:
                raise ConfigError(
                    "baseline_normalized_mean_rmse selection requires include_baseline (ADR-021)"
                )
            # The selection denominator must come from the same block the
            # candidates are scored on, or the ratio compares two periods.
            baseline_rmse = _per_target_rmse(
                inner_score,
                models[BASELINE_KEY].predict(inner_score[predictors]),
                inputs.feature.targets,
            )
        tuning_report = tune_model(
            thesis,
            inner_fit,
            inner_score,
            inputs.feature,
            inputs.schema,
            candidates=tuning.candidates(),
            seed=seed,
            selection=tuning.selection.value,
            baseline_validation_rmse=baseline_rmse,
            early_stopping_rounds=tuning.early_stopping_rounds,
        )
        # The winner was fitted on the inner block only. Refit it on the FULL
        # training partition at the selected hyperparameters, holding the tree
        # count early stopping chose, so the thesis model and the baseline see
        # exactly the same training rows and the comparison stays fair. The
        # tuning trial records survive the refit.
        adopt_tuned_iteration_count(thesis)
        fit_reports[THESIS_KEY] = fit_model(
            thesis, partitions["training"], inputs.feature, inputs.schema, seed=seed
        )

        # ADR-032(a): the regularised baseline is tuned on the SAME inner
        # block, against the SAME OLS denominator, and refitted on full TRAIN.
        # An untuned regularised model would be a strawman in the opposite
        # direction to an unregularised one.
        elastic = models.get("elastic_net")
        elastic_tuning = config.model.elastic_net_tuning
        if elastic is not None and elastic_tuning.enabled:
            elastic_tuning_report = tune_model(
                elastic,
                inner_fit,
                inner_score,
                inputs.feature,
                inputs.schema,
                candidates=elastic_tuning.candidates(),
                seed=seed,
                selection=tuning.selection.value,
                baseline_validation_rmse=baseline_rmse,
                early_stopping_rounds=None,
            )
            # The tuning record survives the refit because it is model state,
            # not report state (verified: ElasticNetNBM._fit_report reads
            # self._tuning_*). Binding the search report to a name anyway, and
            # asserting the refit preserved it, keeps that guarantee explicit
            # rather than incidental — the double assignment previously here
            # read as a lost write.
            fit_reports["elastic_net"] = fit_model(
                elastic, partitions["training"], inputs.feature, inputs.schema, seed=seed
            )
            assert (
                fit_reports["elastic_net"].tuning_configurations_evaluated
                == elastic_tuning_report.tuning_configurations_evaluated
            )
            for partition, frame in partitions.items():
                if partition == "training":
                    continue
                predictions[f"elastic_net_{partition}"] = elastic.predict(frame[predictors])
        assert fit_reports[THESIS_KEY].tuning_configurations_evaluated == len(
            tuning_report.tuning_trials
        )
    else:
        fit_reports[THESIS_KEY] = fit_model(
            thesis, partitions["training"], inputs.feature, inputs.schema, seed=seed
        )
    for partition, frame in partitions.items():
        predictions[f"{THESIS_KEY}_{partition}"] = thesis.predict(frame[predictors])
    return models, fit_reports, predictions


def _residual_stages(
    config: AppConfig,
    inputs: PipelineInputs,
    partitions: dict[str, pd.DataFrame],
    predictions: dict[str, pd.DataFrame],
) -> tuple[dict[str, ResidualFrame], dict[str, Any], InControlReport, dict[str, Any]]:
    """Residuals → normalization (Guard 4) → EWMA (PRIMARY) → in-control."""
    targets = inputs.feature.targets
    raw = {
        partition: compute_residuals(
            frame, predictions[f"{THESIS_KEY}_{partition}"], inputs.schema, targets
        )
        for partition, frame in partitions.items()
    }

    fleet_reports: dict[str, Any] = {}
    if config.residual.fleet_relative:
        # ADR-029 ABLATION ARM. Applied to raw residuals in every partition
        # before any statistic is fitted, so the normalizer and control limits
        # describe the same quantity the detector will read.
        for partition in list(raw):
            raw[partition], fleet_report = fleet_relative_residuals(raw[partition])
            fleet_reports[partition] = fleet_report.as_dict()

    source = partition_for(config.residual.threshold_stats_source)
    source_partition = config.residual.threshold_stats_source.value
    normalizer = make_normalizer(config.residual.normalization)
    normalizer.fit(raw[source_partition], source)

    normalized = {partition: normalizer.transform(rf) for partition, rf in raw.items()}

    detector = EwmaDetector(
        config.detection.ewma_lambda,
        ControlLimitSpec(
            sigma_multiplier=config.detection.control_limit_sigma,
            formulation=ControlLimitFormulation(config.detection.control_limit_formulation),
        ),
        gap_handling=GapHandling(config.detection.gap_handling),
    )
    detector.fit_control_limits(normalized[source_partition], source)
    in_control = detector.characterize_in_control(normalized["validation"])
    _, test_detections = detector.detect(normalized["test"])

    detection_metrics: dict[str, Any] = {
        "fleet_relative": config.residual.fleet_relative,
        "fleet_adjustment": fleet_reports,
        "in_control": in_control.as_dict(),
        "test_streams": len(test_detections),
        "test_points": sum(len(d.states) for d in test_detections),
        "test_exceedance_points": sum(int((d.states != 0).sum()) for d in test_detections),
    }
    return normalized, dict(normalizer.fitted_stats()), in_control, detection_metrics


#: PROJECT.md §20 condition variables. The ambient slice doubles as the
#: seasonal-shift diagnostic and is the mitigation LIM-013 names.
CONDITION_VARIABLES: tuple[str, ...] = (ACTIVE_POWER, WIND_SPEED, AMBIENT_TEMPERATURE)


def _condition_diagnostics(
    inputs: PipelineInputs,
    partitions: dict[str, pd.DataFrame],
    predictions: dict[str, pd.DataFrame],
    model_keys: Sequence[str],
) -> dict[str, Any]:
    """PROJECT.md §20 condition-sliced error diagnostics.

    Mandated by the specification, implemented in M-18, and — until now —
    never invoked outside the test suite: ``condition_diagnostics`` had no
    production caller, so no experiment ever produced them. They matter for
    three specific reasons, not as decoration:

    1. They are the heteroscedasticity evidence the §22 normalization design
       is supposed to rest on, and the evidence decision D-12 (condition-binned
       normalization) is blocked on.
    2. The ambient slice is the named mitigation for LIM-013 — whether the
       model's error grows where it extrapolates beyond its training range.
    3. §20 states the purpose plainly: "We need to know whether model error
       changes by operating condition."

    Computed on the out-of-sample partitions only, per model and target.
    """
    targets = list(inputs.feature.targets)
    output: dict[str, Any] = {}
    for partition, frame in partitions.items():
        if partition == "training":
            continue
        conditions = [c for c in CONDITION_VARIABLES if c in frame.columns]
        if not conditions:
            continue
        for model_key in model_keys:
            key = f"{model_key}_{partition}"
            if key not in predictions:
                continue
            for target in targets:
                tables = condition_diagnostics(
                    frame[target], predictions[key][target], frame[conditions]
                )
                output.setdefault(partition, {}).setdefault(model_key, {})[target] = {
                    condition: table.to_dict(orient="records")
                    for condition, table in tables.items()
                }
    return output


def _residual_diagnostics(residuals: dict[str, ResidualFrame]) -> dict[str, Any]:
    """Descriptive residual diagnostics per partition (M-28 companion).

    Read-only: nothing here feeds a model, a threshold, or a reported metric.
    Two assumptions the pipeline otherwise leaves unmeasured — that the two
    thermal targets carry non-redundant residual evidence (the coordinated-
    detection premise), and that pooling residual statistics across turbines
    is defensible (M-19b fits per target, pooled across machines).

    A diagnostic must not be able to abort a run, so a partition that cannot
    support an estimate records the refusal reason instead of raising.
    """
    output: dict[str, Any] = {}
    for partition, frame in residuals.items():
        entry: dict[str, Any] = {}
        try:
            entry["cross_target_correlation"] = cross_target_correlation(
                frame, partition=partition
            ).as_dict()
        except ConfigError as exc:
            entry["cross_target_correlation"] = {"not_computed": exc.message}
        try:
            entry["per_turbine_residual_stats"] = per_turbine_residual_stats(
                frame, partition=partition
            ).as_dict()
        except ConfigError as exc:
            entry["per_turbine_residual_stats"] = {"not_computed": exc.message}
        output[partition] = entry
    return output


def _residual_diagnostics_summary(diagnostics: dict[str, Any]) -> dict[str, Any]:
    """The two decisive numbers per partition, for metrics.json.

    Full detail lands in evaluation/residual_diagnostics.json; these are the
    figures that decide whether coordination adds evidence and whether pooled
    normalization is defensible, so they belong where the diff will see them.
    """
    summary: dict[str, Any] = {}
    for partition, entry in diagnostics.items():
        correlation = entry.get("cross_target_correlation", {})
        pooling = entry.get("per_turbine_residual_stats", {})
        pairs = correlation.get("pairs", [])
        pooled = pooling.get("pooled", [])
        summary[partition] = {
            "max_abs_cross_target_pearson": (
                round(max(abs(float(p["pearson"])) for p in pairs), 6) if pairs else None
            ),
            "max_centre_spread_in_pooled_scales": (
                round(max(float(p["centre_spread_in_pooled_scales"]) for p in pooled), 6)
                if pooled
                else None
            ),
        }
    return summary


def _monitoring_healthy_slice(
    config: AppConfig,
    inputs: PipelineInputs,
    cleaned: CanonicalDataset,
    split: Split,
    dataset_report: DatasetReport,
) -> tuple[pd.DataFrame, HealthyStateReport]:
    """The ADR-022 RQ1 headline slice: the same healthy-state criteria as
    train/validation, applied to the monitoring period. The returned frame
    keeps the test partition's row index, so slice predictions subset the
    already-computed test predictions exactly."""
    test_frame = cleaned.frame.loc[split.test]
    builder = HealthyStateBuilder(config.healthy_state, inputs.schema)
    healthy, report = builder.build(
        cleaned.with_frame(test_frame.reset_index(drop=True), stage="monitoring_healthy_slice"),
        fault_windows=list(inputs.fault_windows),
        alarm_windows=list(inputs.alarm_windows),
        maintenance_windows=list(inputs.maintenance_windows),
        step_changes=dataset_report.step_changes,
    )
    if healthy.frame.empty:
        raise ConfigError(
            "Monitoring period contains no healthy rows; the ADR-022 RQ1 "
            "headline cannot be computed"
        )
    # The builder resets indices; recover the original test rows by
    # (timestamp, turbine) key so the slice aligns with test predictions.
    keys = [inputs.schema.timestamp_name, inputs.schema.turbine_id_name]
    keys = [k for k in keys if k in test_frame.columns]
    test_keys = pd.MultiIndex.from_frame(test_frame[keys])
    slice_keys = pd.MultiIndex.from_frame(healthy.frame[keys])
    mask = test_keys.isin(slice_keys)
    return test_frame.loc[mask], report


def _nbm_metrics(
    inputs: PipelineInputs,
    partitions: dict[str, pd.DataFrame],
    predictions: dict[str, pd.DataFrame],
    model_keys: Sequence[str],
) -> dict[str, Any]:
    """RMSE/MAE/R²/bias per model, partition, and target (M-18; no MAPE).

    Model and partition are iterated EXPLICITLY rather than recovered by
    splitting the prediction key. Parsing on the first underscore silently
    mis-keys any model whose name contains one — ``elastic_net_test`` would
    resolve to model ``elastic``, partition ``net_test`` — and the error would
    surface as a plausible-looking metrics table rather than a failure.
    """
    targets = list(inputs.feature.targets)
    table: dict[str, Any] = {}
    for model_key in model_keys:
        for partition in partitions:
            if partition == "training":
                continue  # headline accuracy is out-of-sample only
            key = f"{model_key}_{partition}"
            if key not in predictions:
                continue
            per_target = compute_per_target(partitions[partition][targets], predictions[key])
            table.setdefault(model_key, {})[partition] = {
                target: metric_set.as_dict() for target, metric_set in per_target.items()
            }
    return table


def run_experiment(
    config: AppConfig, inputs: PipelineInputs, store: ArtifactStore
) -> tuple[str, PipelineResult]:
    """Run the pipeline, then persist the complete artifact set (M-29/M-30).

    The pipeline runs entirely in memory first; only a successful run touches
    the artifact root, so failures leave no partial experiment behind. Logs
    from that phase are buffered and replayed into the experiment's run.log
    once the directory exists (ADR-043) — previously they were lost, and the
    stored log held only the persistence phase.
    """
    with buffered_logs() as buffered:
        result = run_pipeline(config, inputs)

    experiment_id = store.new_experiment_id()
    directory = store.create_layout(experiment_id)
    with experiment_logging(experiment_id, directory, replay=buffered):
        _logger.info("Persisting experiment %s", experiment_id)
        record = _build_record(experiment_id, config, inputs, result)
        store.persist(record, config, result.metrics)
        store.write_report(experiment_id, "dataset_report", result.dataset_report.as_dict())
        store.write_report(experiment_id, "cleaning_audit", result.cleaning_audit.as_dict())
        store.write_report(experiment_id, "healthy_state_report", result.healthy_report.as_dict())
        store.write_report(experiment_id, "split", _split_dict(result.split))
        store.write_report(experiment_id, "normalizer_stats", result.normalizer_stats)
        store.write_report(experiment_id, "residual_diagnostics", result.residual_diagnostics)
        store.write_report(experiment_id, "condition_diagnostics", result.condition_diagnostics)
        for key, model in result.models.items():
            model.save(directory / "model" / key)
        for key, frame in result.predictions.items():
            frame.to_parquet(directory / "predictions" / f"{key}.parquet")
        for partition, residual_frame in result.residuals.items():
            residual_frame.data.to_parquet(directory / "residuals" / f"{partition}.parquet")
        _persist_conditions(directory, inputs, result)
        if result.in_control is not None:
            store.write_report(experiment_id, "in_control_report", result.in_control.as_dict())
            _record_inflation(experiment_id, result.in_control, inputs.limitations_path)
    return experiment_id, result


def _persist_conditions(directory: Path, inputs: PipelineInputs, result: PipelineResult) -> None:
    """The §20 condition variables for the monitoring partition, keyed like the
    residual frame.

    The residual frame deliberately carries no predictor columns (M-19a keeps
    it minimal and raw-write-once). Persisting the three §20 conditions beside
    it is what lets the diagnostic figures be regenerated from artifacts alone
    — in seconds, rather than by re-running the pipeline — while guaranteeing
    a figure and the metric beside it describe the same rows.
    """
    frame = result.cleaned.frame.loc[result.split.test]
    keys = [inputs.schema.timestamp_name, inputs.schema.turbine_id_name]
    columns = keys + [c for c in CONDITION_VARIABLES if c in frame.columns]
    conditions = frame[columns].rename(
        columns={
            inputs.schema.timestamp_name: "timestamp",
            inputs.schema.turbine_id_name: "turbine_id",
        }
    )
    # NOT under predictions/: `reproduce` requires exact frame equality over
    # every stored prediction, and a non-prediction file there is diffed as a
    # missing prediction.
    conditions.to_parquet(directory / "evaluation" / "conditions.parquet", index=False)


def _record_inflation(
    experiment_id: str, report: InControlReport, limitations_path: Path | None
) -> None:
    """M-20 acceptance 2: material inflation reaches the living register."""
    entry_text = report.limitations_entry()
    if entry_text is None:
        return
    if limitations_path is None:
        _logger.warning(
            "In-control false-alarm inflation is material but no LIMITATIONS.md "
            "path was supplied; entry retained in artifacts only: %s",
            entry_text,
        )
        return
    lim_id = append_limitation(
        limitations_path,
        title=f"EWMA in-control false-alarm inflation ({experiment_id})",
        description=entry_text,
        affected_rqs="RQ2 (detection thresholds; risk R4)",
        mitigation_status="OPEN — widen limits or justify empirically (PROJECT.md §23)",
        source=f"M-20 empirical in-control characterization, experiment {experiment_id}",
    )
    _logger.warning("Appended %s to %s", lim_id, limitations_path)


def _build_record(
    experiment_id: str, config: AppConfig, inputs: PipelineInputs, result: PipelineResult
) -> ExperimentRecord:
    stamps = result.cleaned.frame[inputs.schema.timestamp_name].dropna()
    start = None if stamps.empty else stamps.min().to_pydatetime()
    end = None if stamps.empty else stamps.max().to_pydatetime()
    thesis_report = result.fit_reports[THESIS_KEY]
    return ExperimentRecord(
        experiment_id=experiment_id,
        created_at_utc=utc_now(),
        schema_version=inputs.schema.schema_version,
        config_hash=config_hash(config),
        resolved_config=resolved_dict(config),
        mapping=inputs.mapping.model_dump(mode="json"),
        feature=inputs.feature,
        cleaning_operations=inputs.cleaning_operations,
        exclusions=ExclusionsMetadata(
            fault=_window_records(inputs.fault_windows),
            alarm=_window_records(inputs.alarm_windows),
            maintenance=_window_records(inputs.maintenance_windows),
        ),
        dataset=DatasetMetadata(
            provenance=result.healthy.provenance,
            turbines=tuple(result.healthy_report.turbines),
            date_range_utc=(start, end),
            modelling_span=inputs.modelling_span,
            deduplication=(
                result.cleaned.deduplication.as_dict() if result.cleaned.deduplication else None
            ),
        ),
        split=SplitMetadata(
            spec=_spec_dict(inputs.split_spec),
            seasonal_coverage=result.split.seasonal_coverage.as_dict(),
            sizes={
                "train": len(result.split.train),
                "validation": len(result.split.validation),
                "test": len(result.split.test),
            },
        ),
        model=ModelMetadata(
            type=thesis_report.model_type,
            model_kind=thesis_report.model_kind.value,
            hyperparameters=dict(thesis_report.hyperparameters),
            tuning_configurations_evaluated=thesis_report.tuning_configurations_evaluated,
            tuning_trials=thesis_report.tuning_trials,
        ),
        multiple_comparison_register=_multiple_comparison_register(result.fit_reports),
        # PROJECT.md §15: a seed per stochastic component, not one global seed.
        # ``model`` covers the XGBoost fit and its row subsampling; ``bootstrap``
        # covers the moving-block resampling that produces every reported CI.
        seeds={
            "model": config.model.seed,
            "bootstrap": config.evaluation.bootstrap_seed,
            **dict(inputs.seeds or {}),
        },
        environment=capture_version_stamp(schema_version=inputs.schema.schema_version),
        guards=GuardAttestations(
            validated=PIPELINE_GUARDS,
            threshold_stats_source=config.residual.threshold_stats_source.value,
        ),
        flags=ExperimentFlagsRecord(thesis_official=inputs.flags.thesis_official),
    )


def _multiple_comparison_register(
    fit_reports: dict[str, FitReport],
) -> MultipleComparisonRegister:
    """Total configurations scored across every tuned model (PROJECT.md §18).

    ADR-039: the register previously carried only the thesis model's count, so
    a run that scored 12 XGBoost candidates and 9 Elastic Net candidates
    recorded 12. The guard exists to make the search surface visible, and a
    count that omits a whole model's search does not do that.
    """
    per_model = {
        key: report.tuning_configurations_evaluated for key, report in sorted(fit_reports.items())
    }
    return MultipleComparisonRegister(
        per_model=per_model,
        total_configurations_evaluated=sum(per_model.values()),
        untuned_models=tuple(key for key, count in per_model.items() if count == 0),
    )


def _window_records(
    windows: tuple[ExclusionWindow, ...],
) -> tuple[ExclusionWindowRecord, ...]:
    return tuple(
        ExclusionWindowRecord(
            turbine=w.turbine,
            start_utc=w.start_utc.to_pydatetime(),
            end_utc=w.end_utc.to_pydatetime(),
            reason=w.reason,
        )
        for w in windows
    )


def _spec_dict(spec: SplitSpec) -> dict[str, Any]:
    return {
        "strategy": spec.strategy.value,
        "train_fraction": spec.train_fraction,
        "validation_fraction": spec.validation_fraction,
        "test_fraction": spec.test_fraction,
        "train_end": None if spec.train_end is None else spec.train_end.isoformat(),
        "validation_end": (
            None if spec.validation_end is None else spec.validation_end.isoformat()
        ),
        "n_folds": spec.n_folds,
    }


def _split_dict(split: Split) -> dict[str, Any]:
    return {
        "spec": _spec_dict(split.spec),
        "sizes": {
            "train": len(split.train),
            "validation": len(split.validation),
            "test": len(split.test),
        },
        "boundaries_utc": [None if b is None else b.isoformat() for b in split.boundaries_utc],
        "seasonal_coverage": split.seasonal_coverage.as_dict(),
    }
