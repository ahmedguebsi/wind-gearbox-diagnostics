"""THE thesis model: multi-target XGBoost NBM (M-16; LOCKED-01).

Headline configuration is native multi-output (one model, one tree set for
all targets); one-model-per-target is supported as the ablation mode
(PROJECT.md §18). Fits are seeded and single-threaded so repeated fits with
identical config+seed are bit-identical (M-16 acceptance 2).

Hyperparameter tuning happens on the healthy VALIDATION block only, and the
number of configurations evaluated is recorded (silent multiple-comparison
guard, PROJECT.md §18): the tuning API structurally takes train and
validation frames — there is no argument through which test data could
enter (M-16 acceptance 3).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from app.core.errors import ConfigError
from app.models.base import FitReport, ModelKind
from app.models.registry import register_model

MODEL_NAME = "xgboost_multi_target"

#: Defaults; every headline value is tunable on the validation block.
DEFAULT_HYPERPARAMETERS: dict[str, Any] = {
    "n_estimators": 300,
    "learning_rate": 0.05,
    "max_depth": 6,
    "subsample": 1.0,
    "colsample_bytree": 1.0,
}

_META_FILENAME = "meta.json"


class XGBoostNBM:
    """Multi-target XGBoost Normal Behaviour Model (LOCKED-01)."""

    def __init__(
        self,
        hyperparameters: dict[str, Any] | None = None,
        *,
        multi_output: bool = True,
    ) -> None:
        self.hyperparameters: dict[str, Any] = {
            **DEFAULT_HYPERPARAMETERS,
            **(hyperparameters or {}),
        }
        #: True = native multi-output (headline); False = per-target ablation.
        self.multi_output = multi_output
        self._models: dict[str, XGBRegressor] = {}
        self._targets: tuple[str, ...] = ()
        self._seed: int | None = None
        self._tuning_configurations_evaluated = 0
        self._tuning_trials: list[dict[str, Any]] = []

    @property
    def model_kind(self) -> ModelKind:
        return ModelKind.THESIS

    def _make_regressor(
        self, seed: int, *, multi: bool, early_stopping_rounds: int | None = None
    ) -> XGBRegressor:
        return XGBRegressor(
            **self.hyperparameters,
            random_state=seed,
            n_jobs=1,
            tree_method="hist",
            multi_strategy="multi_output_tree" if multi else "one_output_per_tree",
            early_stopping_rounds=early_stopping_rounds,
        )

    def _fit_internal(
        self,
        X: pd.DataFrame,
        y: pd.DataFrame,
        *,
        seed: int,
        eval_X: pd.DataFrame | None = None,
        eval_y: pd.DataFrame | None = None,
        early_stopping_rounds: int | None = None,
    ) -> None:
        if y.empty or X.empty:
            raise ConfigError("Cannot fit on empty frames")
        stopping = early_stopping_rounds if eval_X is not None else None
        self._targets = tuple(str(c) for c in y.columns)
        self._seed = seed
        self._models = {}
        if self.multi_output:
            model = self._make_regressor(seed, multi=True, early_stopping_rounds=stopping)
            if eval_X is not None and stopping is not None:
                model.fit(X, y, eval_set=[(eval_X, eval_y)], verbose=False)
            else:
                model.fit(X, y)
            self._models["__multi__"] = model
        else:
            for target in self._targets:
                model = self._make_regressor(seed, multi=False, early_stopping_rounds=stopping)
                if eval_X is not None and eval_y is not None and stopping is not None:
                    model.fit(X, y[target], eval_set=[(eval_X, eval_y[target])], verbose=False)
                else:
                    model.fit(X, y[target])
                self._models[target] = model

    def _best_iteration(self) -> int | None:
        model = self._models.get("__multi__")
        if model is None:
            return None
        best = getattr(model, "best_iteration", None)
        return int(best) if best is not None else None

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
        self._fit_internal(X, y, seed=seed)
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
        """Select hyperparameters on the validation block, per ADR-021.

        Only the validation block scores candidates (PROJECT.md §18); the
        evaluated-configuration count and per-candidate trial records land
        in the FitReport. The scored winner's fitted trees are adopted
        directly — the model selected IS the model used.
        """
        if not candidates:
            raise ConfigError("Tuning grid is empty")
        best: tuple[float, dict[str, Any], XGBoostNBM] | None = None
        trials: list[dict[str, Any]] = []
        for candidate in candidates:
            trial = XGBoostNBM(
                {**self.hyperparameters, **candidate}, multi_output=self.multi_output
            )
            trial._fit_internal(
                X_train,
                y_train,
                seed=seed,
                eval_X=X_validation,
                eval_y=y_validation,
                early_stopping_rounds=early_stopping_rounds,
            )
            predictions = trial.predict(X_validation)
            score = _selection_score(y_validation, predictions, selection, baseline_validation_rmse)
            trials.append(
                {
                    "hyperparameters": dict(candidate),
                    "seed": seed,
                    "score": round(score, 6),
                    "best_iteration": trial._best_iteration(),
                }
            )
            if best is None or score < best[0]:
                best = (score, dict(candidate), trial)
        assert best is not None
        _, best_candidate, best_model = best
        self.hyperparameters = {**self.hyperparameters, **best_candidate}
        self._models = best_model._models
        self._targets = best_model._targets
        self._seed = seed
        self._tuning_configurations_evaluated = len(candidates)
        self._tuning_trials = trials
        return self._fit_report(len(X_train), seed)

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        if not self._models:
            raise ConfigError("Model is not fitted")
        if self.multi_output:
            values = self._models["__multi__"].predict(X)
            return pd.DataFrame(np.asarray(values), columns=list(self._targets), index=X.index)
        columns = {target: np.asarray(self._models[target].predict(X)) for target in self._targets}
        return pd.DataFrame(columns, index=X.index)

    def save(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        meta = {
            "model_type": MODEL_NAME,
            "multi_output": self.multi_output,
            "targets": list(self._targets),
            "hyperparameters": self.hyperparameters,
            "seed": self._seed,
            "tuning_configurations_evaluated": self._tuning_configurations_evaluated,
            "tuning_trials": self._tuning_trials,
        }
        (path / _META_FILENAME).write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")
        for key, model in self._models.items():
            model.save_model(path / f"{key}.ubj")

    @classmethod
    def load(cls, path: Path) -> XGBoostNBM:
        meta_path = path / _META_FILENAME
        if not meta_path.is_file():
            raise ConfigError("Saved model metadata not found", path=str(path))
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        instance = cls(meta["hyperparameters"], multi_output=meta["multi_output"])
        instance._targets = tuple(meta["targets"])
        instance._seed = meta["seed"]
        instance._tuning_configurations_evaluated = meta["tuning_configurations_evaluated"]
        # .get: models saved before ADR-021 carry no trial records.
        instance._tuning_trials = meta.get("tuning_trials", [])
        keys = ["__multi__"] if meta["multi_output"] else list(instance._targets)
        for key in keys:
            model = instance._make_regressor(meta["seed"] or 0, multi=meta["multi_output"])
            model.load_model(path / f"{key}.ubj")
            instance._models[key] = model
        return instance


def _selection_score(
    y_validation: pd.DataFrame,
    predictions: pd.DataFrame,
    selection: str,
    baseline_validation_rmse: Mapping[str, float] | None,
) -> float:
    """Score one tuning candidate on the validation block (lower is better).

    ``baseline_normalized_mean_rmse`` (ADR-021): mean over targets of
    (candidate RMSE / baseline RMSE), so each target contributes equally
    regardless of its error scale. ``pooled_rmse`` stacks all targets'
    errors and is retained as the non-default alternative.
    """
    errors = y_validation.to_numpy() - predictions.to_numpy()
    if selection == "pooled_rmse":
        return float(np.sqrt(np.mean(errors**2)))
    if selection == "baseline_normalized_mean_rmse":
        if baseline_validation_rmse is None:
            raise ConfigError(
                "baseline_normalized_mean_rmse requires the baseline's "
                "per-target validation RMSE (ADR-021)"
            )
        ratios: list[float] = []
        for index, target in enumerate(str(c) for c in y_validation.columns):
            rmse = float(np.sqrt(np.mean(errors[:, index] ** 2)))
            base = baseline_validation_rmse.get(target)
            if base is None or base <= 0:
                raise ConfigError("Missing or non-positive baseline validation RMSE", target=target)
            ratios.append(rmse / base)
        return float(np.mean(ratios))
    raise ConfigError("Unknown tuning selection metric", selection=selection)


register_model(MODEL_NAME, XGBoostNBM, ModelKind.THESIS)
