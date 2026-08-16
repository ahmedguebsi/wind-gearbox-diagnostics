"""M-15…M-18 tests: NBM contract, registry, XGBoost, baseline, metrics.

Fixtures are SYNTHETIC TEST DATA — NOT VALID THESIS EVIDENCE — with no fault
labels (LOCKED-08); they exercise mechanics only.
"""

import ast
import io
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import app.models  # noqa: F401  (registration side effect)
from app.core.errors import ConfigError
from app.data.guards import FeatureConfig
from app.data.schema import (
    ACTIVE_POWER,
    AMBIENT_TEMPERATURE,
    GEARBOX_BEARING_TEMPERATURE,
    GEARBOX_OIL_TEMPERATURE,
    WIND_SPEED,
    default_schema,
)
from app.models import base as base_module
from app.models.base import FitReport, ModelKind, NormalBehaviourModel, fit_model
from app.models.baselines import LinearRegressionNBM
from app.models.metrics import (
    MetricSet,
    compute_metrics,
    compute_per_target,
    condition_diagnostics,
    condition_sliced,
)
from app.models.registry import register_model, registered, resolve
from app.models.xgboost_nbm import XGBoostNBM

SCHEMA = default_schema()
PREDICTORS = (WIND_SPEED, ACTIVE_POWER, AMBIENT_TEMPERATURE)
TARGETS = (GEARBOX_OIL_TEMPERATURE, GEARBOX_BEARING_TEMPERATURE)


def _frames(n: int = 300) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(0)
    wind = rng.uniform(3.0, 15.0, n)
    power = 50.0 + 140.0 * wind + rng.normal(0.0, 20.0, n)
    ambient = rng.uniform(-5.0, 25.0, n)
    oil = 30.0 + 0.02 * power + 0.4 * ambient + rng.normal(0.0, 0.5, n)
    bearing = 35.0 + 0.015 * power + 0.3 * ambient + rng.normal(0.0, 0.5, n)
    X = pd.DataFrame({WIND_SPEED: wind, ACTIVE_POWER: power, AMBIENT_TEMPERATURE: ambient})
    y = pd.DataFrame({GEARBOX_OIL_TEMPERATURE: oil, GEARBOX_BEARING_TEMPERATURE: bearing})
    return X, y


def _full_frame(n: int = 300) -> pd.DataFrame:
    X, y = _frames(n)
    return pd.concat([X, y], axis=1)


FAST_PARAMS = {"n_estimators": 20, "max_depth": 3}


class TestRegistry:
    def test_exactly_three_models_one_thesis_two_baseline(self):
        """M-17 acceptance 2, as amended by ADR-032: the model set is one
        THESIS and two BASELINE. A fourth model still requires an ADR — the
        count is asserted, not merely bounded, so scope creep cannot ship."""
        entries = registered()
        assert len(entries) == 3
        kinds = sorted(reg.kind for reg in entries.values())
        assert kinds == [ModelKind.BASELINE, ModelKind.BASELINE, ModelKind.THESIS]

    def test_ols_remains_a_zero_hyperparameter_reference(self):
        """ADR-032: OLS is kept precisely because nothing about it is tunable,
        so it contributes zero configurations to the multiple-comparison
        count. If that stops being true the ruling's justification fails."""
        import pandas as pd

        from app.models.baselines import LinearRegressionNBM

        X = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "b": [4.0, 3.0, 2.0, 1.0]})
        y = pd.DataFrame({"t1": [1.0, 2.0, 3.0, 4.0], "t2": [2.0, 4.0, 6.0, 8.0]})
        report = LinearRegressionNBM().fit(X, y, seed=42)
        assert report.hyperparameters == {}
        assert report.tuning_configurations_evaluated == 0

    def test_xgboost_is_the_only_thesis_model(self):
        """M-16 acceptance 1."""
        thesis = [reg for reg in registered().values() if reg.kind is ModelKind.THESIS]
        assert len(thesis) == 1
        assert thesis[0].cls is XGBoostNBM

    def test_resolution_and_unknown_name(self):
        assert resolve("xgboost_multi_target").cls is XGBoostNBM
        assert resolve("linear_regression").cls is LinearRegressionNBM
        with pytest.raises(ConfigError):
            resolve("random_forest")

    def test_duplicate_registration_rejected(self):
        with pytest.raises(ConfigError):
            register_model("linear_regression", LinearRegressionNBM, ModelKind.BASELINE)

    def test_registered_models_conform_to_protocol(self):
        for reg in registered().values():
            assert isinstance(reg.cls(), NormalBehaviourModel)


class TestFitChokepoint:
    def test_fit_model_validates_before_fitting(self, monkeypatch):
        """M-15 acceptance 1: validation precedes fit, always."""
        calls: list[str] = []
        original = base_module.validate_feature_configuration

        def spy(config, schema):
            calls.append("validate")
            original(config, schema)

        monkeypatch.setattr(base_module, "validate_feature_configuration", spy)

        class Recorder:
            model_kind = ModelKind.BASELINE

            def fit(self, X, y, *, seed):
                calls.append("fit")
                return FitReport(
                    model_type="recorder",
                    model_kind=ModelKind.BASELINE,
                    targets=tuple(map(str, y.columns)),
                    n_training_rows=len(X),
                    hyperparameters={},
                    tuning_configurations_evaluated=0,
                    seed=seed,
                )

        feature = FeatureConfig(predictors=PREDICTORS, targets=TARGETS)
        fit_model(Recorder(), _full_frame(50), feature, SCHEMA, seed=7)
        assert calls == ["validate", "fit"]

    def test_no_model_fit_calls_outside_models_package(self):
        """M-15 acceptance 1 (meta-test): every other layer goes through
        ``fit_model``. An NBM fit is recognizable statically: the protocol
        requires the keyword-only ``seed`` argument, and conventionally the
        receiver is named *model*. Residual-layer ``fit`` contracts
        (normalizers, EWMA limits) take a PartitionRef instead and are
        guarded by their own chokepoint (Guard 4) — they are not model
        training. The dynamic spy test above enforces the chokepoint at
        runtime regardless of naming."""
        app_root = Path(base_module.__file__).resolve().parents[1]
        offenders: list[str] = []
        for py_file in app_root.rglob("*.py"):
            if py_file.resolve().parent.name == "models":
                continue
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "fit"
                ):
                    continue
                has_seed_kwarg = any(kw.arg == "seed" for kw in node.keywords)
                receiver = node.func.value
                receiver_name = ""
                if isinstance(receiver, ast.Name):
                    receiver_name = receiver.id
                elif isinstance(receiver, ast.Attribute):
                    receiver_name = receiver.attr
                if has_seed_kwarg or "model" in receiver_name.lower():
                    offenders.append(f"{py_file.name}:{node.lineno}")
        assert offenders == [], f"model .fit() calls outside the chokepoint: {offenders}"


class TestXGBoostNBM:
    def test_multi_output_shape_contract(self):
        X, y = _frames()
        model = XGBoostNBM(FAST_PARAMS)
        report = model.fit(X, y, seed=42)
        predictions = model.predict(X)
        assert list(predictions.columns) == list(TARGETS)
        assert len(predictions) == len(X)
        assert report.model_kind is ModelKind.THESIS
        assert report.tuning_configurations_evaluated == 0

    def test_per_target_ablation_mode(self):
        X, y = _frames()
        model = XGBoostNBM(FAST_PARAMS, multi_output=False)
        model.fit(X, y, seed=42)
        predictions = model.predict(X)
        assert list(predictions.columns) == list(TARGETS)

    def test_seed_determinism_bit_identical(self):
        """M-16 acceptance 2."""
        X, y = _frames()
        first = XGBoostNBM(FAST_PARAMS)
        second = XGBoostNBM(FAST_PARAMS)
        first.fit(X, y, seed=42)
        second.fit(X, y, seed=42)
        a, b = first.predict(X), second.predict(X)
        assert np.array_equal(a.to_numpy(), b.to_numpy())
        buffer_a, buffer_b = io.BytesIO(), io.BytesIO()
        a.to_parquet(buffer_a)
        b.to_parquet(buffer_b)
        assert buffer_a.getvalue() == buffer_b.getvalue()

    def test_save_load_predict_equality(self, tmp_path):
        X, y = _frames()
        model = XGBoostNBM(FAST_PARAMS)
        model.fit(X, y, seed=42)
        model.save(tmp_path / "xgb")
        loaded = XGBoostNBM.load(tmp_path / "xgb")
        assert np.array_equal(model.predict(X).to_numpy(), loaded.predict(X).to_numpy())

    def test_tuning_on_validation_block_records_count(self):
        """M-16 acceptance 3 mechanics: the tuning API takes train and
        validation only, and the configuration count is recorded."""
        X, y = _frames(400)
        X_train, y_train = X.iloc[:280], y.iloc[:280]
        X_val, y_val = X.iloc[280:], y.iloc[280:]
        model = XGBoostNBM(FAST_PARAMS)
        grid = [{"n_estimators": 10}, {"n_estimators": 40}]
        report = model.tune(X_train, y_train, X_val, y_val, grid, seed=42)
        assert report.tuning_configurations_evaluated == 2
        assert model.hyperparameters["n_estimators"] in {10, 40}

    def test_empty_grid_rejected(self):
        X, y = _frames(50)
        with pytest.raises(ConfigError):
            XGBoostNBM(FAST_PARAMS).tune(X, y, X, y, [], seed=1)

    def test_baseline_normalized_selection_requires_baseline_rmse(self):
        """ADR-021: the selection rule cannot run without its denominator."""
        X, y = _frames(60)
        with pytest.raises(ConfigError):
            XGBoostNBM(FAST_PARAMS).tune(
                X,
                y,
                X,
                y,
                [{"max_depth": 2}],
                seed=1,
                selection="baseline_normalized_mean_rmse",
            )

    def test_adr021_trials_and_early_stopping_recorded(self):
        """ADR-021: per-candidate trial records (params, seed, score,
        best_iteration) land in the FitReport; the winner's scored trees
        are adopted directly."""
        X, y = _frames(400)
        X_train, y_train = X.iloc[:280], y.iloc[:280]
        X_val, y_val = X.iloc[280:], y.iloc[280:]
        model = XGBoostNBM({"n_estimators": 40})
        report = model.tune(
            X_train,
            y_train,
            X_val,
            y_val,
            [{"max_depth": 2}, {"max_depth": 3}],
            seed=42,
            selection="baseline_normalized_mean_rmse",
            baseline_validation_rmse={target: 1.0 for target in TARGETS},
            early_stopping_rounds=5,
        )
        assert report.tuning_configurations_evaluated == 2
        assert len(report.tuning_trials) == 2
        scores = []
        for trial in report.tuning_trials:
            assert trial["seed"] == 42
            assert trial["best_iteration"] is not None
            scores.append(trial["score"])
        # The adopted winner is the scored minimum.
        winning = min(report.tuning_trials, key=lambda trial: trial["score"])
        assert model.hyperparameters["max_depth"] == winning["hyperparameters"]["max_depth"]

    def test_unknown_selection_metric_rejected(self):
        X, y = _frames(60)
        with pytest.raises(ConfigError):
            XGBoostNBM(FAST_PARAMS).tune(X, y, X, y, [{"max_depth": 2}], seed=1, selection="mape")

    def test_predict_before_fit_rejected(self):
        X, _ = _frames(10)
        with pytest.raises(ConfigError):
            XGBoostNBM(FAST_PARAMS).predict(X)


class TestLinearBaseline:
    def test_contract_and_kind(self):
        X, y = _frames()
        model = LinearRegressionNBM()
        report = model.fit(X, y, seed=42)
        predictions = model.predict(X)
        assert list(predictions.columns) == list(TARGETS)
        assert report.model_kind is ModelKind.BASELINE
        assert report.hyperparameters == {}
        assert report.tuning_configurations_evaluated == 0

    def test_no_tuning_interface_exists(self):
        """M-17 acceptance 3: nothing to tune, nothing to record."""
        assert not hasattr(LinearRegressionNBM(), "tune")

    def test_deterministic_without_stochastic_component(self):
        X, y = _frames()
        a = LinearRegressionNBM()
        b = LinearRegressionNBM()
        a.fit(X, y, seed=1)
        b.fit(X, y, seed=999)
        assert np.array_equal(a.predict(X).to_numpy(), b.predict(X).to_numpy())

    def test_save_load_round_trip(self, tmp_path):
        X, y = _frames()
        model = LinearRegressionNBM()
        model.fit(X, y, seed=42)
        model.save(tmp_path / "lin")
        loaded = LinearRegressionNBM.load(tmp_path / "lin")
        assert np.array_equal(model.predict(X).to_numpy(), loaded.predict(X).to_numpy())


class TestMetrics:
    def test_hand_computed_reference(self):
        actual = pd.Series([1.0, 2.0, 3.0])
        predicted = pd.Series([2.0, 2.0, 2.0])
        metrics = compute_metrics(actual, predicted)
        assert metrics.rmse == pytest.approx(math.sqrt(2.0 / 3.0))
        assert metrics.mae == pytest.approx(2.0 / 3.0)
        assert metrics.r2 == pytest.approx(0.0)
        assert metrics.bias == pytest.approx(0.0)

    def test_metric_set_exposes_exactly_four_fields(self):
        """M-18: MetricSet is exactly {rmse, mae, r2, bias} — no MAPE."""
        from dataclasses import fields

        assert {f.name for f in fields(MetricSet)} == {"rmse", "mae", "r2", "bias"}

    def test_no_mape_anywhere_in_models_layer(self):
        """M-18 acceptance 1 (meta-test): no code identifier computes or
        exposes MAPE. Docstrings explaining its removal (§19) are prose,
        not computation, and are exempt."""
        models_dir = Path(compute_metrics.__code__.co_filename).parent
        for py_file in models_dir.rglob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            identifiers: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    identifiers.add(node.id.lower())
                elif isinstance(node, ast.Attribute):
                    identifiers.add(node.attr.lower())
                elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                    identifiers.add(node.name.lower())
                elif isinstance(node, ast.arg):
                    identifiers.add(node.arg.lower())
            offenders = {name for name in identifiers if "mape" in name}
            assert offenders == set(), f"MAPE identifier in {py_file.name}: {offenders}"

    def test_per_target_metrics(self):
        X, y = _frames()
        model = LinearRegressionNBM()
        model.fit(X, y, seed=42)
        per_target = compute_per_target(y, model.predict(X))
        assert set(per_target) == set(TARGETS)
        for metrics in per_target.values():
            assert metrics.r2 > 0.9

    def test_mismatched_columns_rejected(self):
        _, y = _frames(20)
        with pytest.raises(ConfigError):
            compute_per_target(y, y.rename(columns={GEARBOX_OIL_TEMPERATURE: "other"}))

    def test_condition_slicing_bin_arithmetic(self):
        actual = pd.Series([1.0, 2.0, 3.0, 4.0])
        predicted = pd.Series([1.5, 2.0, 3.5, 4.0])
        condition = pd.Series([0.0, 1.0, 10.0, 11.0])
        sliced = condition_sliced(actual, predicted, condition, bins=2)
        assert sliced["n"].sum() == 4
        assert len(sliced) == 2
        assert sliced.iloc[0]["bias"] == pytest.approx(0.25)

    def test_condition_diagnostics_covers_supplied_variables(self):
        """M-18 acceptance 2: power/wind/ambient slices (§20)."""
        X, y = _frames()
        model = LinearRegressionNBM()
        model.fit(X, y, seed=42)
        predictions = model.predict(X)
        diagnostics = condition_diagnostics(
            y[GEARBOX_OIL_TEMPERATURE], predictions[GEARBOX_OIL_TEMPERATURE], X, bins=5
        )
        assert set(diagnostics) == {WIND_SPEED, ACTIVE_POWER, AMBIENT_TEMPERATURE}
        for table in diagnostics.values():
            assert table["n"].sum() == len(X)
