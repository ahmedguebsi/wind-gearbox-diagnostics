"""NBM contract and the single fit entry point (M-15; ARCHITECTURE.md §5.1).

``fit_model`` is THE only way the application fits a model: it invokes the
causal-separation chokepoint (M-14, Guards 1/2/8) before any ``fit()``. A
meta-test asserts no other module outside ``app/models`` calls ``.fit(``
directly, so fitting is impossible without validation (M-15 acceptance 1).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import pandas as pd

from app.core.errors import ConfigError
from app.data.guards import FeatureConfig, validate_feature_configuration
from app.data.schema import CanonicalSchema


class ModelKind(StrEnum):
    """Machine-readable thesis/baseline distinction (ARCHITECTURE.md §5.1).

    Only THESIS-kind results feed headline claims; comparison tables label
    BASELINE results automatically (M-28).
    """

    THESIS = "thesis"
    BASELINE = "baseline"


@dataclass(frozen=True)
class FitReport:
    """What one fit did — persisted into experiment metadata (M-29)."""

    model_type: str
    model_kind: ModelKind
    targets: tuple[str, ...]
    n_training_rows: int
    hyperparameters: dict[str, Any]
    #: Silent multiple-comparison guard (PROJECT.md §18): how many
    #: configurations a tuning search evaluated (0 = no search).
    tuning_configurations_evaluated: int
    seed: int
    #: ADR-021: one record per tuning candidate (hyperparameters, seed,
    #: score, best_iteration) so the comparisons made are on the record.
    tuning_trials: tuple[dict[str, Any], ...] = ()


@runtime_checkable
class NormalBehaviourModel(Protocol):
    """Multi-target NBM contract. Thesis implementation: XGBoostNBM (LOCKED-01)."""

    def fit(self, X: pd.DataFrame, y: pd.DataFrame, *, seed: int) -> FitReport: ...

    def predict(self, X: pd.DataFrame) -> pd.DataFrame: ...

    def save(self, path: Path) -> None: ...

    @classmethod
    def load(cls, path: Path) -> NormalBehaviourModel: ...

    @property
    def model_kind(self) -> ModelKind: ...


def fit_model(
    model: NormalBehaviourModel,
    frame: pd.DataFrame,
    feature: FeatureConfig,
    schema: CanonicalSchema,
    *,
    seed: int,
) -> FitReport:
    """The single fit chokepoint: causal-separation validation, then fit.

    Predictor/target matrices are assembled here from the validated feature
    configuration, so a model never sees columns the guards did not approve.
    (Engineered upstream features are validated already; their computation
    joins this entry point with the pipeline integration of M-30.)
    """
    validate_feature_configuration(feature, schema)
    X = frame[list(feature.predictors)]
    y = frame[list(feature.targets)]
    return model.fit(X, y, seed=seed)


def tune_model(
    model: NormalBehaviourModel,
    train_frame: pd.DataFrame,
    validation_frame: pd.DataFrame,
    feature: FeatureConfig,
    schema: CanonicalSchema,
    *,
    candidates: Sequence[dict[str, Any]],
    seed: int,
    selection: str,
    baseline_validation_rmse: Mapping[str, float] | None,
    early_stopping_rounds: int | None,
) -> FitReport:
    """The single tuning chokepoint (ADR-021; PROJECT.md §18).

    Causal-separation validation runs first, and the matrices assembled
    here are train and validation ONLY — structurally, no test data can
    reach a tuning search.
    """
    validate_feature_configuration(feature, schema)
    tune = getattr(model, "tune", None)
    if tune is None:
        raise ConfigError("Model does not support tuning", model=type(model).__name__)
    X_train = train_frame[list(feature.predictors)]
    y_train = train_frame[list(feature.targets)]
    X_validation = validation_frame[list(feature.predictors)]
    y_validation = validation_frame[list(feature.targets)]
    report = tune(
        X_train,
        y_train,
        X_validation,
        y_validation,
        candidates,
        seed=seed,
        selection=selection,
        baseline_validation_rmse=baseline_validation_rmse,
        early_stopping_rounds=early_stopping_rounds,
    )
    assert isinstance(report, FitReport)
    return report
