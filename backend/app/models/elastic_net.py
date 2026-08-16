"""Second BASELINE: multi-task Elastic Net (M-17; ADR-032).

ADR-002 established the baseline as a measuring stick rather than a
competitor. OLS answers "how much thermal variance is linear in operating
conditions". It does not answer the follow-up an examiner will ask: is the
thesis model's advantage NON-LINEARITY, or merely REGULARISATION? A
regularised linear model separates those two explanations; OLS alone cannot.

Chesterman et al. (Wind Energy Science 8(6):893, 2023) compare Elastic Net,
LightGBM, SVR and MLP as SCADA normal-behaviour models on overlapping
thermal targets and recommend Elastic Net as the reference — simple,
transparent, robust, competitive with more complex models. This is that
reference.

Multi-task rather than per-target: ``MultiTaskElasticNet`` applies an L2,1
penalty across targets, so a predictor is retained or dropped for BOTH
thermal targets together. That matches the multi-target framing of the
thesis NBM, and keeps the baseline a single model rather than two.

STANDARDISATION LIVES INSIDE THE ESTIMATOR. Elastic Net regularisation is
scale-sensitive, so the predictors must be standardised — and a scaler
fitted across a split boundary is a textbook leakage vector. Wrapping the
scaler in a Pipeline means it is fitted only on the rows passed to ``fit``,
which the M-15 chokepoint guarantees are training rows. The leak is not
merely avoided, it is unrepresentable.

Unlike OLS this model HAS hyperparameters, so under ADR-032(a) it is tuned
through the same chokepoint, on the same ADR-030 inner holdout, with its
configuration count recorded in the multiple-comparison register.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import MultiTaskElasticNet
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.core.errors import ConfigError
from app.models.base import FitReport, ModelKind
from app.models.registry import register_model

MODEL_NAME = "elastic_net"

#: Defaults; both swept values are pre-registered in ADR-032's grid.
DEFAULT_HYPERPARAMETERS: dict[str, Any] = {
    "alpha": 0.1,
    "l1_ratio": 0.5,
    "max_iter": 5000,
}

_META_FILENAME = "meta.json"
_MODEL_FILENAME = "model.joblib"


class ElasticNetNBM:
    """Multi-task Elastic Net on exogenous predictors (BASELINE, ADR-032).

    Deterministic: coordinate descent on a fixed design has no stochastic
    component, so repeated fits are identical regardless of seed. The seed is
    accepted and recorded for interface symmetry with the thesis model.
    """

    def __init__(self, hyperparameters: dict[str, Any] | None = None) -> None:
        self.hyperparameters: dict[str, Any] = {
            **DEFAULT_HYPERPARAMETERS,
            **(hyperparameters or {}),
        }
        self._model: Pipeline | None = None
        self._targets: tuple[str, ...] = ()
        self._seed: int | None = None
        self._tuning_configurations_evaluated = 0
        self._tuning_trials: list[dict[str, Any]] = []

    @property
    def model_kind(self) -> ModelKind:
        return ModelKind.BASELINE

    def _make_pipeline(self) -> Pipeline:
        """Scaler + estimator as one unit, so the scaler cannot be fitted on
        anything the estimator was not fitted on."""
        return Pipeline(
            [
                ("scale", StandardScaler()),
                ("model", MultiTaskElasticNet(**self.hyperparameters)),
            ]
        )

    def _fit_internal(self, X: pd.DataFrame, y: pd.DataFrame) -> None:
        if y.empty or X.empty:
            raise ConfigError("Cannot fit on empty frames")
        self._targets = tuple(str(c) for c in y.columns)
        self._model = self._make_pipeline()
        self._model.fit(X, y)

    def _fit_report(self, n_training_rows: int, seed: int) -> FitReport:
        return FitReport(
            model_type=MODEL_NAME,
            model_kind=self.model_kind,
            targets=self._targets,
            n_training_rows=n_training_rows,
            hyperparameters=dict(self.hyperparameters),
            tuning_configurations_evaluated=self._tuning_configurations_evaluated,
            seed=seed,
            tuning_trials=tuple(self._tuning_trials),
        )

    def fit(self, X: pd.DataFrame, y: pd.DataFrame, *, seed: int) -> FitReport:
        self._fit_internal(X, y)
        self._seed = seed
        return self._fit_report(len(X), seed)

    def tune(
        self,
        X_train: pd.DataFrame,
        y_train: pd.DataFrame,
        X_validation: pd.DataFrame,
        y_validation: pd.DataFrame,
        candidates: Sequence[dict[str, Any]],
        *,
        seed: int,
        selection: str = "pooled_rmse",
        baseline_validation_rmse: Mapping[str, float] | None = None,
        early_stopping_rounds: int | None = None,
    ) -> FitReport:
        """Select regularisation on the scoring block, per ADR-032(a).

        Same contract as the thesis model's ``tune`` so both route through the
        M-15 chokepoint and see the same ADR-030 inner holdout.
        ``early_stopping_rounds`` is accepted and ignored: coordinate descent
        has no boosting rounds to stop.
        """
        if not candidates:
            raise ConfigError("Tuning grid is empty")
        best: tuple[float, dict[str, Any], Pipeline, tuple[str, ...]] | None = None
        trials: list[dict[str, Any]] = []
        for candidate in candidates:
            trial = ElasticNetNBM({**self.hyperparameters, **candidate})
            trial._fit_internal(X_train, y_train)
            score = _selection_score(
                y_validation, trial.predict(X_validation), selection, baseline_validation_rmse
            )
            trials.append(
                {
                    "hyperparameters": dict(candidate),
                    "seed": seed,
                    "score": round(score, 6),
                    "best_iteration": None,
                }
            )
            if best is None or score < best[0]:
                assert trial._model is not None
                best = (score, dict(candidate), trial._model, trial._targets)
        assert best is not None
        _, best_candidate, best_model, best_targets = best
        self.hyperparameters = {**self.hyperparameters, **best_candidate}
        self._model = best_model
        self._targets = best_targets
        self._seed = seed
        self._tuning_configurations_evaluated = len(candidates)
        self._tuning_trials = trials
        return self._fit_report(len(X_train), seed)

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        if self._model is None:
            raise ConfigError("Model is not fitted")
        values = np.asarray(self._model.predict(X))
        return pd.DataFrame(values, columns=list(self._targets), index=X.index)

    def save(self, path: Path) -> None:
        if self._model is None:
            raise ConfigError("Cannot save an unfitted model")
        path.mkdir(parents=True, exist_ok=True)
        meta = {
            "model_type": MODEL_NAME,
            "targets": list(self._targets),
            "hyperparameters": self.hyperparameters,
            "seed": self._seed,
            "tuning_configurations_evaluated": self._tuning_configurations_evaluated,
            "tuning_trials": self._tuning_trials,
        }
        (path / _META_FILENAME).write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")
        joblib.dump(self._model, path / _MODEL_FILENAME)

    @classmethod
    def load(cls, path: Path) -> ElasticNetNBM:
        meta_path = path / _META_FILENAME
        if not meta_path.is_file():
            raise ConfigError("Saved model metadata not found", path=str(path))
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        instance = cls(meta["hyperparameters"])
        instance._targets = tuple(meta["targets"])
        instance._seed = meta["seed"]
        instance._tuning_configurations_evaluated = meta["tuning_configurations_evaluated"]
        instance._tuning_trials = meta.get("tuning_trials", [])
        instance._model = joblib.load(path / _MODEL_FILENAME)
        return instance


def _selection_score(
    y_validation: pd.DataFrame,
    predictions: pd.DataFrame,
    selection: str,
    baseline_validation_rmse: Mapping[str, float] | None,
) -> float:
    """Score one candidate (lower is better).

    ``baseline_normalized_mean_rmse`` divides each target's RMSE by the OLS
    reference's, so this model and the thesis model are selected by mean
    improvement over the SAME fixed reference (ADR-032(b)).
    """
    errors = y_validation.to_numpy() - predictions.to_numpy()
    if selection == "pooled_rmse":
        return float(np.sqrt(np.mean(errors**2)))
    if selection == "baseline_normalized_mean_rmse":
        if baseline_validation_rmse is None:
            raise ConfigError(
                "baseline_normalized_mean_rmse requires the reference model's "
                "per-target validation RMSE (ADR-021/ADR-032)"
            )
        ratios: list[float] = []
        for index, target in enumerate(str(c) for c in y_validation.columns):
            rmse = float(np.sqrt(np.mean(errors[:, index] ** 2)))
            base = baseline_validation_rmse.get(target)
            if base is None or base <= 0:
                raise ConfigError(
                    "Missing or non-positive reference validation RMSE", target=target
                )
            ratios.append(rmse / base)
        return float(np.mean(ratios))
    raise ConfigError("Unknown tuning selection metric", selection=selection)


register_model(MODEL_NAME, ElasticNetNBM, ModelKind.BASELINE)
