"""M-14 tests: causal-separation guards (Guards 1, 2, 8)."""

from pathlib import Path

import pytest

from app.core.errors import CausalSeparationError, SchemaError
from app.data import guards as guards_module
from app.data.guards import (
    FeatureConfig,
    FeatureConfigurationValidator,
    FeatureSpec,
    TransformKind,
    validate_feature_configuration,
)
from app.data.schema import (
    ACTIVE_POWER,
    AMBIENT_TEMPERATURE,
    GEARBOX_BEARING_TEMPERATURE,
    GEARBOX_OIL_TEMPERATURE,
    ROTOR_SPEED,
    TURBINE_ID,
    WIND_SPEED,
    default_schema,
)

SCHEMA = default_schema()
TARGETS = (GEARBOX_OIL_TEMPERATURE, GEARBOX_BEARING_TEMPERATURE)


def _config(**overrides) -> FeatureConfig:
    base = {
        "predictors": (WIND_SPEED, ACTIVE_POWER, AMBIENT_TEMPERATURE),
        "targets": TARGETS,
        "engineered": (),
    }
    base.update(overrides)
    return FeatureConfig(**base)


class TestGuard1TargetAsPredictor:
    def test_declared_target_as_predictor_raises(self):
        config = _config(predictors=(WIND_SPEED, GEARBOX_OIL_TEMPERATURE))
        with pytest.raises(CausalSeparationError, match="Guard 1"):
            validate_feature_configuration(config, SCHEMA)

    def test_target_role_variable_as_predictor_raises_even_if_not_declared_target(self):
        config = _config(
            predictors=(WIND_SPEED, GEARBOX_BEARING_TEMPERATURE),
            targets=(GEARBOX_OIL_TEMPERATURE,),
        )
        with pytest.raises(CausalSeparationError, match="Guard 1"):
            validate_feature_configuration(config, SCHEMA)


class TestGuard2FutureInformation:
    def test_future_shifted_feature_raises(self):
        spec = FeatureSpec(
            name="power_future", source=ACTIVE_POWER, transform=TransformKind.LAG, periods=-1
        )
        with pytest.raises(CausalSeparationError, match="Guard 2"):
            validate_feature_configuration(_config(engineered=(spec,)), SCHEMA)

    def test_zero_step_raises(self):
        spec = FeatureSpec(
            name="power_now", source=ACTIVE_POWER, transform=TransformKind.DIFF, periods=0
        )
        with pytest.raises(CausalSeparationError, match="Guard 2"):
            validate_feature_configuration(_config(engineered=(spec,)), SCHEMA)

    def test_degenerate_rolling_window_raises(self):
        spec = FeatureSpec(
            name="rotor_roll", source=ROTOR_SPEED, transform=TransformKind.ROLLING_MEAN, window=1
        )
        with pytest.raises(CausalSeparationError, match="Guard 2"):
            validate_feature_configuration(_config(engineered=(spec,)), SCHEMA)


class TestGuard8TargetDerivedFeatures:
    """M-14 acceptance 2: negative tests enumerate every prohibited class.

    Parametrizing over the TransformKind enum itself guarantees a newly
    added transform kind cannot ship without a Guard 8 negative test.
    """

    @pytest.mark.parametrize("kind", list(TransformKind))
    @pytest.mark.parametrize("target", TARGETS)
    def test_every_transform_class_on_a_target_raises(self, kind, target):
        spec = FeatureSpec(name=f"bad_{kind.value}", source=target, transform=kind)
        with pytest.raises(CausalSeparationError, match="Guard 8"):
            validate_feature_configuration(_config(engineered=(spec,)), SCHEMA)

    @pytest.mark.parametrize("kind", list(TransformKind))
    def test_violation_message_names_the_feature_class(self, kind):
        spec = FeatureSpec(name="bad", source=GEARBOX_OIL_TEMPERATURE, transform=kind)
        with pytest.raises(CausalSeparationError) as excinfo:
            validate_feature_configuration(_config(engineered=(spec,)), SCHEMA)
        expected = guards_module._GUARD8_CLASS_MESSAGES[kind]
        assert expected in str(excinfo.value)

    def test_class_message_registry_covers_every_kind(self):
        assert set(guards_module._GUARD8_CLASS_MESSAGES) == set(TransformKind)


class TestFailClosedSourceDeclaration:
    def test_blank_source_raises(self):
        spec = FeatureSpec(name="mystery", source="  ", transform=TransformKind.LAG)
        with pytest.raises(CausalSeparationError, match="fail-closed"):
            validate_feature_configuration(_config(engineered=(spec,)), SCHEMA)

    def test_unknown_source_raises(self):
        spec = FeatureSpec(name="mystery", source="not_a_variable", transform=TransformKind.LAG)
        with pytest.raises(CausalSeparationError, match="fail-closed"):
            validate_feature_configuration(_config(engineered=(spec,)), SCHEMA)

    def test_non_exogenous_source_raises(self):
        spec = FeatureSpec(name="odd", source=TURBINE_ID, transform=TransformKind.LAG)
        with pytest.raises(CausalSeparationError, match="exogenous"):
            validate_feature_configuration(_config(engineered=(spec,)), SCHEMA)


class TestUpstreamEngineeringPermitted:
    def test_thermal_lag_aware_upstream_features_pass(self):
        engineered = (
            FeatureSpec(
                name="power_lag1", source=ACTIVE_POWER, transform=TransformKind.LAG, periods=1
            ),
            FeatureSpec(
                name="rotor_mean6",
                source=ROTOR_SPEED,
                transform=TransformKind.ROLLING_MEAN,
                window=6,
            ),
            FeatureSpec(
                name="ambient_lag3",
                source=AMBIENT_TEMPERATURE,
                transform=TransformKind.LAG,
                periods=3,
            ),
        )
        validate_feature_configuration(_config(engineered=engineered), SCHEMA)

    def test_validator_class_entry_point(self):
        FeatureConfigurationValidator().validate(_config(), SCHEMA)


class TestStructuralRejections:
    def test_non_exogenous_predictor_raises(self):
        config = _config(predictors=(WIND_SPEED, TURBINE_ID))
        with pytest.raises(CausalSeparationError, match="exogenous"):
            validate_feature_configuration(config, SCHEMA)

    def test_unknown_predictor_raises_schema_error(self):
        with pytest.raises(SchemaError):
            validate_feature_configuration(_config(predictors=("nonexistent",)), SCHEMA)

    def test_unknown_target_raises_schema_error(self):
        with pytest.raises(SchemaError):
            validate_feature_configuration(_config(targets=("nonexistent",)), SCHEMA)

    def test_predictor_role_declared_as_target_raises_schema_error(self):
        with pytest.raises(SchemaError):
            validate_feature_configuration(_config(targets=(WIND_SPEED,)), SCHEMA)

    def test_empty_targets_raises(self):
        with pytest.raises(SchemaError):
            validate_feature_configuration(_config(targets=()), SCHEMA)

    def test_empty_predictors_raises(self):
        with pytest.raises(SchemaError):
            validate_feature_configuration(_config(predictors=()), SCHEMA)

    def test_duplicate_predictors_raise(self):
        with pytest.raises(SchemaError):
            validate_feature_configuration(_config(predictors=(WIND_SPEED, WIND_SPEED)), SCHEMA)

    def test_engineered_name_shadowing_canonical_raises(self):
        spec = FeatureSpec(name=WIND_SPEED, source=ACTIVE_POWER, transform=TransformKind.LAG)
        with pytest.raises(SchemaError):
            validate_feature_configuration(_config(engineered=(spec,)), SCHEMA)

    def test_duplicate_engineered_names_raise(self):
        specs = (
            FeatureSpec(name="f1", source=ACTIVE_POWER, transform=TransformKind.LAG),
            FeatureSpec(name="f1", source=WIND_SPEED, transform=TransformKind.LAG),
        )
        with pytest.raises(SchemaError):
            validate_feature_configuration(_config(engineered=specs), SCHEMA)


class TestVocabularyDiscipline:
    def test_no_leakage_vocabulary_in_module(self):
        """LOCKED-09 / M-14 acceptance 3: user-facing strings use "causal
        separation"; the module contains no "leakage" vocabulary at all."""
        source = Path(guards_module.__file__).read_text(encoding="utf-8")
        assert "leakage" not in source.lower()
        assert "causal separation" in source.lower()
