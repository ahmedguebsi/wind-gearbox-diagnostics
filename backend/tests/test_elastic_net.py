"""Second BASELINE tests (M-17; ADR-032).

Fixtures are SYNTHETIC TEST DATA — NOT VALID THESIS EVIDENCE — with no fault
labels (LOCKED-08).

Two tests carry the ruling's fairness conditions: standardisation must be
fitted inside the estimator (so a scaler cannot straddle a split boundary),
and the model must route through the same tuning contract as the thesis
model (so its configuration count enters the multiple-comparison record).
"""

import numpy as np
import pandas as pd
import pytest
from sklearn.pipeline import Pipeline

from app.core.errors import ConfigError
from app.models.base import ModelKind, fit_model, tune_model
from app.models.elastic_net import DEFAULT_HYPERPARAMETERS, ElasticNetNBM
from app.models.registry import create, resolve

TARGETS = ("gearbox_oil_temperature", "gearbox_bearing_temperature")
PREDICTORS = ("wind_speed", "active_power", "ambient_temperature")


def _data(n: int = 400, seed: int = 0, scale_skew: float = 1.0):
    """Predictors on deliberately different scales, which is what makes
    standardisation load-bearing for a regularised model."""
    rng = np.random.default_rng(seed)
    wind = rng.uniform(0, 25, n)
    power = rng.uniform(0, 2000, n) * scale_skew
    ambient = rng.uniform(-5, 35, n)
    X = pd.DataFrame({PREDICTORS[0]: wind, PREDICTORS[1]: power, PREDICTORS[2]: ambient})
    y = pd.DataFrame(
        {
            TARGETS[0]: 40 + 0.01 * power + 0.5 * ambient + rng.standard_normal(n),
            TARGETS[1]: 50 + 0.008 * power + 0.4 * ambient + rng.standard_normal(n),
        }
    )
    return X, y


class TestRegistrationAndContract:
    def test_registered_as_baseline(self):
        registration = resolve("elastic_net")
        assert registration.kind is ModelKind.BASELINE
        assert registration.cls is ElasticNetNBM

    def test_creatable_through_the_registry(self):
        model = create("elastic_net")
        assert isinstance(model, ElasticNetNBM)

    def test_fits_and_predicts_both_targets(self):
        X, y = _data()
        report = fit_model(
            ElasticNetNBM(), pd.concat([X, y], axis=1), _feature_config(), _schema(), seed=42
        )
        assert report.model_kind is ModelKind.BASELINE
        assert report.targets == TARGETS

    def test_unfitted_predict_rejected(self):
        with pytest.raises(ConfigError, match="not fitted"):
            ElasticNetNBM().predict(_data()[0])

    def test_empty_frames_rejected(self):
        with pytest.raises(ConfigError, match="empty"):
            ElasticNetNBM().fit(pd.DataFrame(), pd.DataFrame(), seed=42)

    def test_deterministic_across_repeated_fits(self):
        X, y = _data()
        first = ElasticNetNBM()
        second = ElasticNetNBM()
        first.fit(X, y, seed=42)
        second.fit(X, y, seed=7)  # different seed: coordinate descent is exact
        pd.testing.assert_frame_equal(first.predict(X), second.predict(X))


class TestStandardisationIsInternal:
    """ADR-032(c): the scaler must be fitted inside the estimator, on the rows
    passed to fit. A scaler fitted across a split boundary is a leakage
    vector; keeping it in the Pipeline makes that unrepresentable."""

    def test_the_fitted_object_is_a_pipeline_containing_a_scaler(self):
        X, y = _data()
        model = ElasticNetNBM()
        model.fit(X, y, seed=42)
        assert isinstance(model._model, Pipeline)
        assert "scale" in dict(model._model.named_steps)

    def test_scaler_statistics_come_only_from_the_fitting_rows(self):
        """Fit on one half, then predict on the other. The scaler's mean must
        equal the FIRST half's mean — if it had seen the prediction rows it
        would not."""
        X, y = _data(n=400, seed=1)
        first_half, second_half = X.iloc[:200], X.iloc[200:]
        model = ElasticNetNBM()
        model.fit(first_half, y.iloc[:200], seed=42)
        model.predict(second_half)
        scaler = model._model.named_steps["scale"]
        np.testing.assert_allclose(scaler.mean_, first_half.to_numpy().mean(axis=0), rtol=1e-9)

    def test_predictor_scale_does_not_change_the_fit(self):
        """The point of internal standardisation: multiplying a predictor by
        1000 must not change what the regularised model learns."""
        X, y = _data(n=400, seed=2)
        plain = ElasticNetNBM()
        plain.fit(X, y, seed=42)
        skewed = X.copy()
        skewed[PREDICTORS[1]] = skewed[PREDICTORS[1]] * 1000.0
        rescaled = ElasticNetNBM()
        rescaled.fit(skewed, y, seed=42)
        np.testing.assert_allclose(
            plain.predict(X).to_numpy(), rescaled.predict(skewed).to_numpy(), rtol=1e-6
        )


class TestTuningContract:
    """ADR-032(a)/(b): same chokepoint, same inner block, configuration count
    recorded, selection normalised by the OLS reference."""

    def test_tunes_through_the_shared_chokepoint(self):
        X, y = _data(n=400, seed=3)
        frame = pd.concat([X, y], axis=1)
        model = ElasticNetNBM()
        report = tune_model(
            model,
            frame.iloc[:300],
            frame.iloc[300:],
            _feature_config(),
            _schema(),
            candidates=[{"alpha": 0.01}, {"alpha": 1.0}],
            seed=42,
            selection="pooled_rmse",
            baseline_validation_rmse=None,
            early_stopping_rounds=None,
        )
        assert report.tuning_configurations_evaluated == 2
        assert len(report.tuning_trials) == 2
        assert model.hyperparameters["alpha"] in {0.01, 1.0}

    def test_selection_normalised_by_the_reference_model(self):
        X, y = _data(n=400, seed=4)
        model = ElasticNetNBM()
        report = model.tune(
            X.iloc[:300],
            y.iloc[:300],
            X.iloc[300:],
            y.iloc[300:],
            candidates=[{"alpha": 0.01}, {"alpha": 0.5}],
            seed=42,
            selection="baseline_normalized_mean_rmse",
            baseline_validation_rmse={TARGETS[0]: 1.0, TARGETS[1]: 1.0},
        )
        assert report.tuning_configurations_evaluated == 2

    def test_normalized_selection_without_a_reference_is_refused(self):
        X, y = _data(n=200, seed=5)
        with pytest.raises(ConfigError, match="per-target validation RMSE"):
            ElasticNetNBM().tune(
                X.iloc[:150],
                y.iloc[:150],
                X.iloc[150:],
                y.iloc[150:],
                candidates=[{"alpha": 0.1}],
                seed=42,
                selection="baseline_normalized_mean_rmse",
                baseline_validation_rmse=None,
            )

    def test_empty_grid_rejected(self):
        X, y = _data(n=200, seed=6)
        with pytest.raises(ConfigError, match="grid is empty"):
            ElasticNetNBM().tune(
                X.iloc[:150], y.iloc[:150], X.iloc[150:], y.iloc[150:], candidates=[], seed=42
            )

    def test_stronger_regularisation_shrinks_coefficients(self):
        """Sanity: the hyperparameter being tuned does what it should."""
        X, y = _data(n=400, seed=7)
        weak = ElasticNetNBM({"alpha": 0.001})
        strong = ElasticNetNBM({"alpha": 10.0})
        weak.fit(X, y, seed=42)
        strong.fit(X, y, seed=42)
        weak_norm = np.abs(weak._model.named_steps["model"].coef_).sum()
        strong_norm = np.abs(strong._model.named_steps["model"].coef_).sum()
        assert strong_norm < weak_norm


class TestPersistence:
    def test_save_load_round_trip_preserves_predictions_and_trials(self, tmp_path):
        X, y = _data(n=300, seed=8)
        model = ElasticNetNBM()
        model.tune(
            X.iloc[:200],
            y.iloc[:200],
            X.iloc[200:],
            y.iloc[200:],
            candidates=[{"alpha": 0.05}, {"alpha": 0.5}],
            seed=42,
            selection="pooled_rmse",
        )
        model.save(tmp_path / "elastic")
        restored = ElasticNetNBM.load(tmp_path / "elastic")
        pd.testing.assert_frame_equal(model.predict(X), restored.predict(X))
        assert restored._tuning_configurations_evaluated == 2
        assert len(restored._tuning_trials) == 2

    def test_saving_unfitted_rejected(self, tmp_path):
        with pytest.raises(ConfigError, match="unfitted"):
            ElasticNetNBM().save(tmp_path / "nope")

    def test_load_without_metadata_rejected(self, tmp_path):
        (tmp_path / "empty").mkdir()
        with pytest.raises(ConfigError, match="metadata not found"):
            ElasticNetNBM.load(tmp_path / "empty")

    def test_defaults_are_the_adr032_values(self):
        assert DEFAULT_HYPERPARAMETERS["l1_ratio"] == 0.5
        assert DEFAULT_HYPERPARAMETERS["alpha"] == 0.1


# --- helpers -----------------------------------------------------------------


def _schema():
    from app.data.schema import (
        ACTIVE_POWER,
        AMBIENT_TEMPERATURE,
        GEARBOX_BEARING_TEMPERATURE,
        GEARBOX_OIL_TEMPERATURE,
        WIND_SPEED,
        CanonicalSchema,
        CanonicalVariable,
        VariableRole,
    )

    return CanonicalSchema(
        schema_version="1.3.0",
        variables=(
            CanonicalVariable(name="timestamp", role=VariableRole.TIMESTAMP),
            CanonicalVariable(name="turbine_id", role=VariableRole.TURBINE_ID),
            CanonicalVariable(name=WIND_SPEED, role=VariableRole.PREDICTOR),
            CanonicalVariable(name=ACTIVE_POWER, role=VariableRole.PREDICTOR),
            CanonicalVariable(name=AMBIENT_TEMPERATURE, role=VariableRole.PREDICTOR),
            CanonicalVariable(name=GEARBOX_OIL_TEMPERATURE, role=VariableRole.TARGET),
            CanonicalVariable(name=GEARBOX_BEARING_TEMPERATURE, role=VariableRole.TARGET),
        ),
    )


def _feature_config():
    from app.data.guards import FeatureConfig
    from app.data.schema import (
        ACTIVE_POWER,
        AMBIENT_TEMPERATURE,
        GEARBOX_BEARING_TEMPERATURE,
        GEARBOX_OIL_TEMPERATURE,
        WIND_SPEED,
    )

    return FeatureConfig(
        predictors=(WIND_SPEED, ACTIVE_POWER, AMBIENT_TEMPERATURE),
        targets=(GEARBOX_OIL_TEMPERATURE, GEARBOX_BEARING_TEMPERATURE),
    )
