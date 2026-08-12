"""The single BASELINE comparator: multiple linear regression (M-17; ADR-002).

The model set is exactly two (ADR-002, closing decision queue D-02): the
multi-target XGBoost NBM (THESIS) and this multiple linear regression on the
same exogenous predictors. The baseline is a measuring stick, not a
competitor: it establishes how much thermal variance is linear in operating
conditions versus captured non-linearly, indicating how much residual spread
is irreducible physics rather than modelling error. It has no
hyperparameters and no architecture decisions, so nothing about the
comparison is tunable after the fact — and it contributes zero
configurations to the §18 multiple-comparison count (M-17 acceptance 3).

Bangalore & Tjernberg's (2015) NARX ANN was considered and NOT reimplemented:
its lagged-target inputs violate Guard 8 (see ADR-002).
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.linear_model import LinearRegression

from app.core.errors import ConfigError
from app.models.base import FitReport, ModelKind
from app.models.registry import register_model

MODEL_NAME = "linear_regression"

_META_FILENAME = "meta.json"
_MODEL_FILENAME = "model.joblib"


class LinearRegressionNBM:
    """Multiple linear regression on exogenous predictors (BASELINE, ADR-002).

    Deterministic by construction: ordinary least squares has no stochastic
    component, so repeated fits are bit-identical regardless of seed.
    """

    def __init__(self) -> None:
        self._model: LinearRegression | None = None
        self._targets: tuple[str, ...] = ()
        self._seed: int | None = None

    @property
    def model_kind(self) -> ModelKind:
        return ModelKind.BASELINE

    def fit(self, X: pd.DataFrame, y: pd.DataFrame, *, seed: int) -> FitReport:
        if y.empty or X.empty:
            raise ConfigError("Cannot fit on empty frames")
        self._targets = tuple(str(c) for c in y.columns)
        self._seed = seed
        self._model = LinearRegression()
        self._model.fit(X, y)
        return FitReport(
            model_type=MODEL_NAME,
            model_kind=self.model_kind,
            targets=self._targets,
            n_training_rows=len(X),
            hyperparameters={},
            tuning_configurations_evaluated=0,
            seed=seed,
        )

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        if self._model is None:
            raise ConfigError("Model is not fitted")
        values = self._model.predict(X)
        return pd.DataFrame(values, columns=list(self._targets), index=X.index)

    def save(self, path: Path) -> None:
        if self._model is None:
            raise ConfigError("Cannot save an unfitted model")
        path.mkdir(parents=True, exist_ok=True)
        meta = {"model_type": MODEL_NAME, "targets": list(self._targets), "seed": self._seed}
        (path / _META_FILENAME).write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")
        joblib.dump(self._model, path / _MODEL_FILENAME)

    @classmethod
    def load(cls, path: Path) -> LinearRegressionNBM:
        meta_path = path / _META_FILENAME
        if not meta_path.is_file():
            raise ConfigError("Saved model metadata not found", path=str(path))
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        instance = cls()
        instance._targets = tuple(meta["targets"])
        instance._seed = meta["seed"]
        instance._model = joblib.load(path / _MODEL_FILENAME)
        return instance


register_model(MODEL_NAME, LinearRegressionNBM, ModelKind.BASELINE)
