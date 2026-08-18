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
    labelling (ARCHITECTURE.md §5.1); pipeline-only runs record ``none``.

    ``tuning_configurations_evaluated`` is the THESIS model's search. The
    experiment-wide multiple-comparison total lives in
    :attr:`ExperimentRecord.multiple_comparison_register`, because a run may
    tune more than one model and PROJECT.md §18's guard is about the total
    number of configurations scored, not one model's share of it.
    """

    type: str
    model_kind: str
    hyperparameters: dict[str, Any]
    tuning_configurations_evaluated: int
    #: ADR-021 per-candidate records; default keeps pre-ADR-021 metadata
    #: loadable.
    tuning_trials: tuple[dict[str, Any], ...] = ()


class MultipleComparisonRegister(StrictRecord):
    """Every configuration this experiment scored, across every tuned model.

    PROJECT.md §18 requires the number of evaluated configurations to be
    recorded as the silent-multiple-comparison guard (risk R9). Before
    ADR-039 the record carried only the thesis model's count, so an
    experiment that scored 12 XGBoost candidates AND 9 Elastic Net candidates
    reported 12 — the guard understated the search surface by the exact
    amount ADR-032(a) had promised to add to it.
    """

    #: model key -> configurations scored for that model.
    per_model: dict[str, int]
    #: Sum across models: the number §18's guard is about.
    total_configurations_evaluated: int
    #: Models fitted with no search at all (zero configurations), listed so
    #: "untuned" is visible rather than inferred from a missing key. OLS is
    #: permanently here by design — it has no hyperparameters (ADR-002).
    untuned_models: tuple[str, ...] = ()
    #: True on records written BEFORE ADR-039, upgraded on load by
    #: ``store._upgrade_legacy_payload``. Their per-model breakdown carries the
    #: thesis model's count only, because that is all that was recorded — the
    #: total may therefore UNDERSTATE the search actually performed. Marked
    #: rather than silently backfilled, so a legacy figure is never mistaken
    #: for a complete one.
    recorded_before_adr_039: bool = False


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
    #: PROJECT.md §18 multiple-comparison guard across every tuned model.
    multiple_comparison_register: MultipleComparisonRegister
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
