"""Typed configuration loading, resolution, and hashing (M-03; PROJECT.md §10 arch).

Principles (ARCHITECTURE.md §10):

- One resolved config per experiment: YAML is validated into Pydantic models,
  every default is materialized, and the resolved form is standalone —
  re-loading it reproduces an identical object and hash.
- The resolved-config SHA-256 hash identifies the experiment configuration.
- Provisional values (PROJECT.md §13, §23) are marked in the *schema* via
  field metadata; the resolved output carries a ``provisional_parameters``
  list so the sensitivity analyzer (M-27) can discover them automatically.
- Open ADRs surface as config enums (``threshold_stats_source``) so both
  branches exist in code while the thesis decision is recorded in
  docs/DECISIONS.md, never silently in code.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.errors import ConfigError

PROVISIONAL_MARKER = "provisional"


def provisional_field(default: Any, description: str, **field_kwargs: Any) -> Any:
    """A config field whose value is provisional pending sensitivity analysis
    (PROJECT.md §27.3). The marker is discoverable via
    :func:`iter_provisional_parameters`."""
    return Field(
        default=default,
        description=description,
        json_schema_extra={PROVISIONAL_MARKER: True},
        **field_kwargs,
    )


class StrictModel(BaseModel):
    """Base for all config models: unknown keys rejected, immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ThresholdStatsSource(StrEnum):
    """Healthy partition from which normalization/threshold statistics derive.

    OPEN ADR (PROJECT.md §22, risk R6): training block (v1.0 default) vs.
    validation block (reviewer-recommended). Both branches exist as
    configuration; the thesis choice is closed in docs/DECISIONS.md (ADR-001).
    """

    TRAINING = "training"
    VALIDATION = "validation"


class NormalizationMethod(StrEnum):
    """Residual normalization families (PROJECT.md §22)."""

    SIGMA = "sigma"
    MAD = "mad"
    PERCENTILE = "percentile"
    CONDITION_BINNED = "condition_binned"


class LoggingConfig(StrictModel):
    """Structured logging options (M-04)."""

    level: str = "INFO"
    json_console: bool = False


class HealthyStateConfig(StrictModel):
    """Healthy-state exclusion parameters (PROJECT.md §13).

    Provisional values become defended choices only through the sensitivity
    analysis phase (§27.3) and Chapter 3 justification.
    """

    exclude_alarm_periods: bool = True
    fault_pre_exclusion_days: int = provisional_field(
        30, "Days excluded before a known fault", ge=0
    )
    maintenance_post_exclusion_days: int = provisional_field(
        2, "Days excluded after maintenance", ge=0
    )
    minimum_active_power_kw: float = provisional_field(
        50.0, "Operating-state floor on active power (kW)"
    )


class ModelConfig(StrictModel):
    """NBM configuration (PROJECT.md §18).

    The thesis model is fixed (LOCKED-01): ``name`` resolves through the
    model registry, which contains exactly the ADR-002 two-model set. The
    baseline has nothing to configure — ``include_baseline`` only controls
    whether it is fitted alongside the thesis model for RQ1 context.
    """

    name: str = "xgboost_multi_target"
    hyperparameters: dict[str, Any] = Field(default_factory=dict)
    multi_output: bool = True
    include_baseline: bool = True
    #: Seed for every stochastic model component; recorded per PROJECT.md §15.
    seed: int = 42


class ResidualConfig(StrictModel):
    """Residual normalization configuration (PROJECT.md §22)."""

    normalization: NormalizationMethod = NormalizationMethod.MAD
    threshold_stats_source: ThresholdStatsSource = ThresholdStatsSource.TRAINING


class DetectionConfig(StrictModel):
    """Detection configuration (PROJECT.md §23).

    EWMA is the PRIMARY persistence/anomaly treatment (LOCKED-02): it is the
    only value ``method`` currently admits. Comparator methods (consecutive
    exceedance, rolling rules) will be added as explicitly-labelled opt-ins
    with M-21 — they can never become the default.
    """

    method: Literal["ewma"] = "ewma"
    ewma_lambda: float = provisional_field(0.2, "EWMA smoothing constant λ", gt=0.0, le=1.0)
    control_limit_sigma: float = provisional_field(3.0, "Control-limit multiplier", gt=0.0)
    #: D-10 keeps the formulation open; both branches exist as configuration.
    control_limit_formulation: Literal["steady_state", "time_varying"] = "steady_state"
    #: ADR-017(b): a detection qualifies only when sustained; isolated
    #: single-sample crossings never count.
    persistence_min_samples: int = provisional_field(
        3, "Consecutive exceedance samples for a persistent detection", ge=2
    )


class EvaluationConfig(StrictModel):
    """Event-evaluation configuration (PROJECT.md §27; ADR-017)."""

    #: ADR-017(a): a detection matches an event when its first persistent
    #: exceedance falls within [event_start - window, event_start].
    event_match_window_days: int = provisional_field(
        14, "Pre-event matching window in days (ADR-017; sweep 7/14/30)", ge=1
    )
    #: The pre-committed Phase 0.5 decision rule threshold (PROJECT.md §7.5).
    #: NOT provisional: the rule is fixed; the census count selects the branch.
    min_events_for_inferential: int = 2


class AppConfig(StrictModel):
    """Root configuration. Sections mirror pipeline stages and grow as the
    corresponding modules are implemented (ARCHITECTURE.md §10)."""

    logging: LoggingConfig = LoggingConfig()
    healthy_state: HealthyStateConfig = HealthyStateConfig()
    model: ModelConfig = ModelConfig()
    residual: ResidualConfig = ResidualConfig()
    detection: DetectionConfig = DetectionConfig()
    evaluation: EvaluationConfig = EvaluationConfig()


# Key carried in resolved output only; regenerated on every resolution.
_RESOLVED_ANNOTATION_KEY = "provisional_parameters"


def load_config(path: Path | None = None) -> AppConfig:
    """Load and validate configuration from YAML; no file → all defaults.

    A previously resolved config file (containing the
    ``provisional_parameters`` annotation) loads back to an identical object.
    """
    raw: dict[str, Any] = {}
    if path is not None:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError("Configuration file unreadable", path=str(path)) from exc
        loaded = yaml.safe_load(text)
        if loaded is None:
            loaded = {}
        if not isinstance(loaded, dict):
            raise ConfigError("Configuration root must be a mapping", path=str(path))
        raw = loaded
    raw.pop(_RESOLVED_ANNOTATION_KEY, None)
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError("Invalid configuration", detail=str(exc)) from exc


def iter_provisional_parameters(
    model: type[BaseModel] = AppConfig, _prefix: str = ""
) -> Iterator[str]:
    """Yield dotted paths of every provisional-marked parameter in the schema."""
    for name, field in model.model_fields.items():
        extra = field.json_schema_extra
        if isinstance(extra, dict) and extra.get(PROVISIONAL_MARKER):
            yield f"{_prefix}{name}"
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            yield from iter_provisional_parameters(annotation, f"{_prefix}{name}.")


def resolved_dict(config: AppConfig) -> dict[str, Any]:
    """Fully materialized configuration: every default present, plus the
    ``provisional_parameters`` discovery list."""
    data: dict[str, Any] = config.model_dump(mode="json")
    data[_RESOLVED_ANNOTATION_KEY] = sorted(iter_provisional_parameters())
    return data


def config_hash(config: AppConfig) -> str:
    """SHA-256 of the canonical (sorted, compact) JSON serialization of the
    resolved configuration. Stable across YAML key order and formatting."""
    canonical = json.dumps(resolved_dict(config), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def to_resolved_yaml(config: AppConfig) -> str:
    """Canonical YAML serialization of the resolved configuration."""
    return yaml.safe_dump(resolved_dict(config), sort_keys=True)


def write_resolved(config: AppConfig, path: Path) -> None:
    """Write the standalone resolved ``config.yaml`` for an artifact directory."""
    path.write_text(to_resolved_yaml(config), encoding="utf-8")
