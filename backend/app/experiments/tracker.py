"""Experiment metadata capture (M-29; PROJECT.md §15; ARCHITECTURE.md §8.2).

Every field of the §15 contract is a required field of
:class:`ExperimentRecord` — a record missing any of them cannot be
constructed, so it cannot be persisted (M-29 acceptance 1).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from app.core.errors import ConfigError
from app.core.versioning import VersionStamp
from app.data.guards import FeatureConfig
from app.data.provenance import ProvenanceChain

EXPERIMENT_ID_RE = re.compile(r"^EXP-\d{8}-\d{3}$")


class StrictRecord(BaseModel):
    """Base for metadata records: unknown keys rejected, immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DatasetMetadata(StrictRecord):
    """Dataset identity: provenance chain, population, span (PROJECT.md §15)."""

    provenance: ProvenanceChain
    turbines: tuple[str, ...]
    date_range_utc: tuple[datetime | None, datetime | None]
    modelling_span: tuple[date | None, date | None]
    deduplication: dict[str, Any] | None


class SplitMetadata(StrictRecord):
    """Split spec + the mandatory seasonal coverage report (PROJECT.md §14)."""

    spec: dict[str, Any]
    seasonal_coverage: dict[str, Any]
    sizes: dict[str, int]


class ExclusionWindowRecord(StrictRecord):
    """One healthy-state exclusion window as stored metadata."""

    turbine: str
    start_utc: datetime
    end_utc: datetime
    reason: str


class ExclusionsMetadata(StrictRecord):
    """The exclusion windows a run was given (healthy-state configuration)."""

    fault: tuple[ExclusionWindowRecord, ...]
    alarm: tuple[ExclusionWindowRecord, ...]
    maintenance: tuple[ExclusionWindowRecord, ...]


class ModelMetadata(StrictRecord):
    """Model identity. ``model_kind`` is machine-readable THESIS/BASELINE
    labelling (ARCHITECTURE.md §5.1); pipeline-only runs record ``none``."""

    type: str
    model_kind: str
    hyperparameters: dict[str, Any]
    tuning_configurations_evaluated: int
    #: ADR-021 per-candidate records; default keeps pre-ADR-021 metadata
    #: loadable.
    tuning_trials: tuple[dict[str, Any], ...] = ()


class GuardAttestations(StrictRecord):
    """Which guards were exercised, and the threshold-statistics source
    (the ADR-001 enum, recorded per run)."""

    validated: tuple[str, ...]
    threshold_stats_source: str


class ExperimentFlagsRecord(StrictRecord):
    """Experiment flags; ``thesis_official`` activates Guard 3 strictness."""

    thesis_official: bool


class ExperimentRecord(StrictRecord):
    """The complete metadata.json contract (ARCHITECTURE.md §8.2)."""

    experiment_id: str
    created_at_utc: datetime
    schema_version: str
    config_hash: str
    resolved_config: dict[str, Any]
    mapping: dict[str, Any]
    feature: FeatureConfig
    cleaning_operations: tuple[str, ...]
    exclusions: ExclusionsMetadata
    dataset: DatasetMetadata
    split: SplitMetadata
    model: ModelMetadata
    seeds: dict[str, int]
    environment: VersionStamp
    guards: GuardAttestations
    flags: ExperimentFlagsRecord

    @model_validator(mode="after")
    def _validate(self) -> ExperimentRecord:
        if not EXPERIMENT_ID_RE.match(self.experiment_id):
            raise ConfigError(
                "Experiment ID must match EXP-YYYYMMDD-NNN", experiment_id=self.experiment_id
            )
        return self
