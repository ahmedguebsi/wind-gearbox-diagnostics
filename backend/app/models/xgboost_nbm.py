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
from collections.abc import Sequence
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

    @property
    def model_kind(self) -> ModelKind:
        return ModelKind.THESIS

    def _make_regressor(self, seed: int, *, multi: bool) -> XGBRegressor:
        return XGBRegressor(
            **self.hyperparameters,
            random_state=seed,
            n_jobs=1,
            tree_method="hist",
            multi_strategy="multi_output_tree" if multi else "one_output_per_tree",
        )

    def fit(self, X: pd.DataFrame, y: pd.DataFrame, *, seed: int) -> FitReport:
        if y.empty or X.empty:
            raise ConfigError("Cannot fit on empty frames")
        self._targets = tuple(str(c) for c in y.columns)
        self._seed = seed
        self._models = {}
        if self.multi_output:
            model = self._make_regressor(seed, multi=True)
            model.fit(X, y)
            self._models["__multi__"] = model
        else:
            for target in self._targets:
                model = self._make_regressor(seed, multi=False)
                model.fit(X, y[target])
                self._models[target] = model
        return FitReport(
            model_type=MODEL_NAME,
            model_kind=self.model_kind,
            targets=self._targets,
            n_training_rows=len(X),
            hyperparameters=dict(self.hyperparameters),
            tuning_configurations_evaluated=self._tuning_configurations_evaluated,
            seed=seed,
        )

    def tune(
        self,
        X_train: pd.DataFrame,
        y_train: pd.DataFrame,
        X_validation: pd.DataFrame,
        y_validation: pd.DataFrame,
        grid: Sequence[dict[str, Any]],
        *,
        seed: int,
    ) -> FitReport:
        """Select hyperparameters by validation RMSE, then refit with them.

        Only the validation block scores candidates (PROJECT.md §18); the
        evaluated-configuration count lands in the FitReport.
        """
        if not grid:
            raise ConfigError("Tuning grid is empty")
        best_rmse = float("inf")
        best_params: dict[str, Any] = {}
        for candidate in grid:
            trial = XGBoostNBM(
                {**self.hyperparameters, **candidate}, multi_output=self.multi_output
            )
            trial.fit(X_train, y_train, seed=seed)
            predictions = trial.predict(X_validation)
            rmse = float(np.sqrt(np.mean((y_validation.to_numpy() - predictions.to_numpy()) ** 2)))
            if rmse < best_rmse:
                best_rmse = rmse
                best_params = candidate
        self.hyperparameters = {**self.hyperparameters, **best_params}
        self._tuning_configurations_evaluated = len(grid)
        return self.fit(X_train, y_train, seed=seed)

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
        keys = ["__multi__"] if meta["multi_output"] else list(instance._targets)
        for key in keys:
            model = instance._make_regressor(meta["seed"] or 0, multi=meta["multi_output"])
            model.load_model(path / f"{key}.ubj")
            instance._models[key] = model
        return instance


register_model(MODEL_NAME, XGBoostNBM, ModelKind.THESIS)
