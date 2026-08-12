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

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.config import AppConfig, NormalizationMethod, config_hash, resolved_dict
from app.core.errors import ConfigError
from app.core.limitations import append_limitation
from app.core.logging import experiment_logging, get_logger
from app.core.time import utc_now
from app.core.versioning import capture_version_stamp
from app.data.cleaning import CleaningAudit, clean
from app.data.guards import FeatureConfig, validate_feature_configuration
from app.data.healthy_state import ExclusionWindow, HealthyStateBuilder, HealthyStateReport
from app.data.ingestion import CanonicalDataset, ingest_files
from app.data.mapping import ColumnMapping
from app.data.schema import CanonicalSchema
from app.data.splitting import (
    ExperimentFlags,
    Split,
    SplitPolicyGuard,
    SplitSpec,
    split_chronologically,
)
from app.data.validation import DatasetReport, validate
from app.experiments.store import ArtifactStore
from app.experiments.tracker import (
    DatasetMetadata,
    ExclusionsMetadata,
    ExclusionWindowRecord,
    ExperimentFlagsRecord,
    ExperimentRecord,
    GuardAttestations,
    ModelMetadata,
    SplitMetadata,
)
from app.models.base import FitReport, NormalBehaviourModel, fit_model
from app.models.metrics import compute_per_target
from app.models.registry import create as create_model
from app.residuals.engine import ResidualFrame, compute_residuals
from app.residuals.ewma import (
    ControlLimitFormulation,
    ControlLimitSpec,
    EwmaDetector,
    InControlReport,
)
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
    dataset_report = validate(dataset, inputs.schema)
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
        "cleaning": {"rows_removed": audit.total_removed, "rows_after": len(cleaned.frame)},
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
        "nbm": _nbm_metrics(inputs, partitions, predictions),
        "detection": detection_metrics,
    }
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
    )


def _fit_and_predict(
    config: AppConfig, inputs: PipelineInputs, partitions: dict[str, pd.DataFrame]
) -> tuple[dict[str, NormalBehaviourModel], dict[str, FitReport], dict[str, pd.DataFrame]]:
    """Fit thesis (+ baseline) through the M-15 chokepoint; predict val/test.

    Training-partition predictions are also produced because the ADR-001
    ``threshold_stats_source: training`` branch fits its statistics there.
    """
    seed = config.model.seed
    models = {
        THESIS_KEY: create_model(
            config.model.name,
            hyperparameters=dict(config.model.hyperparameters),
            multi_output=config.model.multi_output,
        )
    }
    if config.model.include_baseline:
        models[BASELINE_KEY] = create_model(BASELINE_MODEL_NAME)

    fit_reports: dict[str, FitReport] = {}
    predictions: dict[str, pd.DataFrame] = {}
    for key, model in models.items():
        fit_reports[key] = fit_model(
            model, partitions["training"], inputs.feature, inputs.schema, seed=seed
        )
        for partition, frame in partitions.items():
            if key == BASELINE_KEY and partition == "training":
                continue  # baseline residuals are never thresholded (RQ1 context only)
            predictions[f"{key}_{partition}"] = model.predict(
                frame[list(inputs.feature.predictors)]
            )
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
    )
    detector.fit_control_limits(normalized[source_partition], source)
    in_control = detector.characterize_in_control(normalized["validation"])
    _, test_detections = detector.detect(normalized["test"])

    detection_metrics: dict[str, Any] = {
        "in_control": in_control.as_dict(),
        "test_streams": len(test_detections),
        "test_points": sum(len(d.states) for d in test_detections),
        "test_exceedance_points": sum(int((d.states != 0).sum()) for d in test_detections),
    }
    return normalized, dict(normalizer.fitted_stats()), in_control, detection_metrics


def _nbm_metrics(
    inputs: PipelineInputs,
    partitions: dict[str, pd.DataFrame],
    predictions: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    """RMSE/MAE/R²/bias per model, partition, and target (M-18; no MAPE)."""
    targets = list(inputs.feature.targets)
    table: dict[str, Any] = {}
    for key, predicted in predictions.items():
        model_key, _, partition = key.partition("_")
        if partition == "training":
            continue  # headline accuracy is out-of-sample only
        actual = partitions[partition][targets]
        per_target = compute_per_target(actual, predicted)
        table.setdefault(model_key, {})[partition] = {
            target: metric_set.as_dict() for target, metric_set in per_target.items()
        }
    return table


def run_experiment(
    config: AppConfig, inputs: PipelineInputs, store: ArtifactStore
) -> tuple[str, PipelineResult]:
    """Run the pipeline, then persist the complete artifact set (M-29/M-30).

    The pipeline runs entirely in memory first; only a successful run touches
    the artifact root, so failures leave no partial experiment behind.
    """
    result = run_pipeline(config, inputs)

    experiment_id = store.new_experiment_id()
    directory = store.create_layout(experiment_id)
    with experiment_logging(experiment_id, directory):
        _logger.info("Persisting experiment %s", experiment_id)
        record = _build_record(experiment_id, config, inputs, result)
        store.persist(record, config, result.metrics)
        store.write_report(experiment_id, "dataset_report", result.dataset_report.as_dict())
        store.write_report(experiment_id, "cleaning_audit", result.cleaning_audit.as_dict())
        store.write_report(experiment_id, "healthy_state_report", result.healthy_report.as_dict())
        store.write_report(experiment_id, "split", _split_dict(result.split))
        store.write_report(experiment_id, "normalizer_stats", result.normalizer_stats)
        for key, model in result.models.items():
            model.save(directory / "model" / key)
        for key, frame in result.predictions.items():
            frame.to_parquet(directory / "predictions" / f"{key}.parquet")
        for partition, residual_frame in result.residuals.items():
            residual_frame.data.to_parquet(directory / "residuals" / f"{partition}.parquet")
        if result.in_control is not None:
            store.write_report(experiment_id, "in_control_report", result.in_control.as_dict())
            _record_inflation(experiment_id, result.in_control, inputs.limitations_path)
    return experiment_id, result


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
        ),
        seeds={"model": config.model.seed, **dict(inputs.seeds or {})},
        environment=capture_version_stamp(schema_version=inputs.schema.schema_version),
        guards=GuardAttestations(
            validated=PIPELINE_GUARDS,
            threshold_stats_source=config.residual.threshold_stats_source.value,
        ),
        flags=ExperimentFlagsRecord(thesis_official=inputs.flags.thesis_official),
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
