"""``reproduce EXP-ID`` (M-31; PROJECT.md §15; ARCHITECTURE.md §8.3).

Sequence: environment check vs stored versions (warn), dataset hash
verification (fail on mismatch), re-run from the stored config and inputs,
diff regenerated metrics against the stored ``metrics.json``, and report
EXACT MATCH / TOLERANCE MATCH / MISMATCH with per-key diff detail.

We must be able to reproduce a thesis result months later; CI runs this on a
fixture experiment on every push and requires EXACT MATCH.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.config import AppConfig
from app.core.errors import ConfigError
from app.core.versioning import capture_library_versions
from app.data.healthy_state import ExclusionWindow
from app.data.mapping import ColumnMapping
from app.data.schema import default_schema
from app.data.splitting import ExperimentFlags, SplitSpec, SplitStrategy
from app.experiments.runner import PipelineInputs, run_pipeline
from app.experiments.store import ArtifactStore
from app.experiments.tracker import ExclusionWindowRecord, ExperimentRecord

#: Relative tolerance for float comparison in TOLERANCE mode.
DEFAULT_FLOAT_TOLERANCE = 1e-9


class ReproductionStatus(StrEnum):
    EXACT_MATCH = "EXACT MATCH"
    TOLERANCE_MATCH = "TOLERANCE MATCH"
    MISMATCH = "MISMATCH"


@dataclass(frozen=True)
class ReproductionReport:
    experiment_id: str
    status: ReproductionStatus
    environment_warnings: list[str] = field(default_factory=list)
    diffs: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "status": self.status.value,
            "environment_warnings": self.environment_warnings,
            "diffs": self.diffs,
        }


def reproduce(
    experiment_id: str,
    store: ArtifactStore,
    *,
    float_tolerance: float = DEFAULT_FLOAT_TOLERANCE,
) -> ReproductionReport:
    """Re-run an experiment from its stored artifacts and diff the results.

    Raises :class:`~app.core.errors.ProvenanceError` when any source file no
    longer matches its recorded SHA-256 — a changed dataset is a hard stop,
    never a warning (ARCHITECTURE.md §8.3).
    """
    record = store.load_record(experiment_id)
    stored_metrics = store.load_metrics(experiment_id)

    warnings = _environment_warnings(record)
    record.dataset.provenance.verify_sources()

    config = _config_from_record(record)
    inputs = _inputs_from_record(record)
    result = run_pipeline(config, inputs)

    diffs: list[str] = []
    tolerance_used = _diff_values("metrics", stored_metrics, result.metrics, float_tolerance, diffs)
    if diffs:
        status = ReproductionStatus.MISMATCH
    elif tolerance_used:
        status = ReproductionStatus.TOLERANCE_MATCH
    else:
        status = ReproductionStatus.EXACT_MATCH
    return ReproductionReport(
        experiment_id=experiment_id,
        status=status,
        environment_warnings=warnings,
        diffs=diffs,
    )


def _environment_warnings(record: ExperimentRecord) -> list[str]:
    """Version mismatches warn — they explain a mismatch, they do not fail it."""
    warnings: list[str] = []
    current = capture_library_versions()
    for library, stored_version in record.environment.library_versions.items():
        installed = current.get(library)
        if installed != stored_version:
            warnings.append(f"{library}: stored {stored_version}, installed {installed}")
    current_schema = default_schema().schema_version
    if record.schema_version != current_schema:
        warnings.append(f"schema_version: stored {record.schema_version}, current {current_schema}")
    return warnings


def _config_from_record(record: ExperimentRecord) -> AppConfig:
    raw = {k: v for k, v in record.resolved_config.items() if k != "provisional_parameters"}
    return AppConfig.model_validate(raw)


def _inputs_from_record(record: ExperimentRecord) -> PipelineInputs:
    schema = default_schema()
    mapping = ColumnMapping.model_validate(record.mapping)
    return PipelineInputs(
        schema=schema,
        mapping=mapping,
        source_paths=tuple(Path(r.source_path) for r in record.dataset.provenance.sources),
        feature=record.feature,
        split_spec=_spec_from_dict(record.split.spec),
        flags=ExperimentFlags(thesis_official=record.flags.thesis_official),
        cleaning_operations=record.cleaning_operations,
        fault_windows=_windows(record.exclusions.fault),
        alarm_windows=_windows(record.exclusions.alarm),
        maintenance_windows=_windows(record.exclusions.maintenance),
        modelling_span=record.dataset.modelling_span,
        seeds=dict(record.seeds),
    )


def _spec_from_dict(payload: dict[str, Any]) -> SplitSpec:
    try:
        return SplitSpec(
            strategy=SplitStrategy(payload["strategy"]),
            train_fraction=payload["train_fraction"],
            validation_fraction=payload["validation_fraction"],
            test_fraction=payload["test_fraction"],
            train_end=(
                None if payload["train_end"] is None else date.fromisoformat(payload["train_end"])
            ),
            validation_end=(
                None
                if payload["validation_end"] is None
                else date.fromisoformat(payload["validation_end"])
            ),
            n_folds=payload["n_folds"],
        )
    except KeyError as exc:
        raise ConfigError("Stored split spec is incomplete", missing=str(exc)) from exc


def _windows(records: tuple[ExclusionWindowRecord, ...]) -> tuple[ExclusionWindow, ...]:
    return tuple(
        ExclusionWindow(
            turbine=r.turbine,
            start_utc=pd.Timestamp(r.start_utc),
            end_utc=pd.Timestamp(r.end_utc),
            reason=r.reason,
        )
        for r in records
    )


def _diff_values(
    path: str, stored: Any, regenerated: Any, tolerance: float, diffs: list[str]
) -> bool:
    """Recursive diff. Returns True when a float matched only within tolerance."""
    tolerance_used = False
    if isinstance(stored, dict) and isinstance(regenerated, dict):
        for key in sorted(set(stored) | set(regenerated)):
            if key not in stored:
                diffs.append(f"{path}.{key}: absent in stored metrics")
            elif key not in regenerated:
                diffs.append(f"{path}.{key}: absent in regenerated metrics")
            else:
                tolerance_used |= _diff_values(
                    f"{path}.{key}", stored[key], regenerated[key], tolerance, diffs
                )
        return tolerance_used
    if isinstance(stored, list) and isinstance(regenerated, list):
        if len(stored) != len(regenerated):
            diffs.append(f"{path}: length {len(stored)} != {len(regenerated)}")
            return tolerance_used
        for i, (a, b) in enumerate(zip(stored, regenerated, strict=True)):
            tolerance_used |= _diff_values(f"{path}[{i}]", a, b, tolerance, diffs)
        return tolerance_used
    if (
        isinstance(stored, float)
        and isinstance(regenerated, int | float)
        and not isinstance(regenerated, bool)
    ):
        if stored == regenerated:
            return False
        scale = max(abs(stored), abs(float(regenerated)), 1.0)
        if abs(stored - float(regenerated)) <= tolerance * scale:
            return True
        diffs.append(f"{path}: stored {stored!r} != regenerated {regenerated!r}")
        return False
    if stored != regenerated:
        diffs.append(f"{path}: stored {stored!r} != regenerated {regenerated!r}")
    return tolerance_used
