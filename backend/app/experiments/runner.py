"""Pipeline orchestration (M-30 skeleton; PROJECT.md §36, ARCHITECTURE.md §7).

Executes the data pipeline from one resolved configuration: guard validation
→ ingest → validate → clean → healthy-state → chronological split (+seasonal
coverage), and persists every artifact through the store (M-29). The model /
residual / detection stages attach here as M-15…M-20 come online — this is
the only module that will import every scientific layer.

Fail-early ordering (M-30 acceptance 2): the causal-separation chokepoint
(Guards 1/2/8) and the split-policy guard (Guard 3) run BEFORE any data is
read, and nothing is persisted unless the whole pipeline succeeds — a guard
failure therefore aborts with no partial artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from app.core.config import AppConfig, config_hash, resolved_dict
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

_logger = get_logger("experiments.runner")

#: Guards exercised by the data-stage pipeline. G4 joins with M-19b, when
#: normalization statistics exist to guard.
DATA_STAGE_GUARDS: tuple[str, ...] = ("G1", "G2", "G3", "G8")


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


@dataclass(frozen=True)
class PipelineResult:
    """In-memory outputs of one pipeline run (persisted via the store)."""

    cleaned: CanonicalDataset
    healthy: CanonicalDataset
    dataset_report: DatasetReport
    cleaning_audit: CleaningAudit
    healthy_report: HealthyStateReport
    split: Split
    metrics: dict[str, Any]


def run_pipeline(config: AppConfig, inputs: PipelineInputs) -> PipelineResult:
    """Run the data pipeline in memory. Raises on any guard violation."""
    # Guards fire before any file is opened (fail-early, M-30 acceptance 2).
    validate_feature_configuration(inputs.feature, inputs.schema)
    SplitPolicyGuard().validate(inputs.split_spec, inputs.flags)

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
    builder = HealthyStateBuilder(config.healthy_state, inputs.schema)
    healthy, healthy_report = builder.build(
        cleaned,
        fault_windows=list(inputs.fault_windows),
        alarm_windows=list(inputs.alarm_windows),
        maintenance_windows=list(inputs.maintenance_windows),
        step_changes=dataset_report.step_changes,
    )
    split = split_chronologically(healthy, inputs.schema, inputs.split_spec, inputs.flags)

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
            "seasonal_warnings": len(split.seasonal_coverage.warnings),
        },
    }
    return PipelineResult(
        cleaned=cleaned,
        healthy=healthy,
        dataset_report=dataset_report,
        cleaning_audit=audit,
        healthy_report=healthy_report,
        split=split,
        metrics=metrics,
    )


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
    return experiment_id, result


def _build_record(
    experiment_id: str, config: AppConfig, inputs: PipelineInputs, result: PipelineResult
) -> ExperimentRecord:
    start, end = result.healthy_report.date_range_utc
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
            date_range_utc=(
                None if start is None else start.to_pydatetime(),
                None if end is None else end.to_pydatetime(),
            ),
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
            type="none",
            model_kind="none",
            hyperparameters={},
            tuning_configurations_evaluated=0,
        ),
        seeds=dict(inputs.seeds or {}),
        environment=capture_version_stamp(schema_version=inputs.schema.schema_version),
        guards=GuardAttestations(
            validated=DATA_STAGE_GUARDS,
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
