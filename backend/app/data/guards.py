"""Causal-separation chokepoint: Guards 1, 2, 8 (M-14; PROJECT.md §9, §33).

Fault-masking rationale (PROJECT.md §9, LOCKED-05/06): the NBM must use only
variables causally upstream of the thermal targets. An autoregressive NBM
that tracks its own target follows slow fault-driven drift and suppresses
exactly the residual signal the thesis is designed to detect. Thermal-lag
awareness is therefore expressed exclusively through lagged/rolled UPSTREAM
variables — never through lags, rolling statistics, differences, or any
other transform of a thermal target.

This module is THE single chokepoint: the model layer's fit entry point
(M-15) invokes :class:`FeatureConfigurationValidator` before any ``fit()``,
so no registered model can train on a violating feature configuration.

Vocabulary (LOCKED-09): causal predictor-target separation is a robustness
and design principle. All messages here use "causal separation".
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.core.errors import CausalSeparationError, SchemaError
from app.data.schema import CanonicalSchema, VariableRole


class TransformKind(StrEnum):
    """Engineered-feature transform families.

    Every kind applied to a thermal target is a distinct Guard 8 violation
    class (PROJECT.md §9). The test suite parametrizes its negative tests
    over this enum, so a newly added kind cannot ship without one (M-14
    acceptance 2).
    """

    LAG = "lag"
    ROLLING_MEAN = "rolling_mean"
    ROLLING_STD = "rolling_std"
    DIFF = "diff"
    ELEMENTWISE = "elementwise"


#: Guard 8 violation phrasing per transform class — class-specific messages
#: so a failure names exactly which prohibited feature class was attempted.
_GUARD8_CLASS_MESSAGES: dict[TransformKind, str] = {
    TransformKind.LAG: "a lagged thermal target",
    TransformKind.ROLLING_MEAN: "a rolling statistic of a thermal target",
    TransformKind.ROLLING_STD: "a rolling statistic of a thermal target",
    TransformKind.DIFF: "a difference of a thermal target",
    TransformKind.ELEMENTWISE: "a transform of a thermal target",
}

#: Transforms parameterized by backward steps.
_STEPPED = (TransformKind.LAG, TransformKind.DIFF)
#: Transforms parameterized by a trailing window.
_WINDOWED = (TransformKind.ROLLING_MEAN, TransformKind.ROLLING_STD)


class FeatureSpec(BaseModel):
    """One engineered feature with its declared source variable.

    The ``source`` declaration is mandatory and fail-closed (M-14 acceptance
    1): a feature whose provenance cannot be established against the
    canonical schema is rejected — exogeneity must be provable, never
    assumed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    source: str
    transform: TransformKind
    #: Backward steps for LAG/DIFF. Must be >= 1: negative steps would read
    #: future values (Guard 2), and step 0 is not a transform.
    periods: int = 1
    #: Trailing window length for rolling transforms (>= 2). Windows are
    #: always trailing; a centered or leading window would read the future.
    window: int = 2


class FeatureConfig(BaseModel):
    """The predictor/target/engineered-feature declaration validated before
    any fit (ARCHITECTURE.md §4)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    predictors: tuple[str, ...]
    targets: tuple[str, ...]
    engineered: tuple[FeatureSpec, ...] = ()


class FeatureConfigurationValidator:
    """Guards 1, 2, 8 (PROJECT.md §33; ARCHITECTURE.md §5.2, §9).

    Raises :class:`CausalSeparationError` on: target-as-predictor (Guard 1),
    future-reading feature parameters (Guard 2), any target-derived feature
    (Guard 8), any non-exogenous predictor or feature source (LOCKED-05),
    and any feature whose source cannot be established (fail-closed).
    Structural mistakes (unknown names, duplicates) raise
    :class:`SchemaError`.
    """

    def validate(self, config: FeatureConfig, schema: CanonicalSchema) -> None:
        self._validate_targets(config, schema)
        self._validate_predictors(config, schema)
        self._validate_engineered(config, schema)

    @staticmethod
    def _validate_targets(config: FeatureConfig, schema: CanonicalSchema) -> None:
        if not config.targets:
            raise SchemaError("Feature configuration declares no targets")
        duplicates = _duplicates(config.targets)
        if duplicates:
            raise SchemaError("Duplicate targets declared", duplicates=duplicates)
        for name in config.targets:
            if name not in schema.names():
                raise SchemaError("Unknown target variable", variable=name)
            if schema.variable(name).role is not VariableRole.TARGET:
                raise SchemaError("Declared target is not a TARGET-role variable", variable=name)

    @staticmethod
    def _validate_predictors(config: FeatureConfig, schema: CanonicalSchema) -> None:
        if not config.predictors and not config.engineered:
            raise SchemaError("Feature configuration declares no predictors")
        duplicates = _duplicates(config.predictors)
        if duplicates:
            raise SchemaError("Duplicate predictors declared", duplicates=duplicates)
        for name in config.predictors:
            if name not in schema.names():
                raise SchemaError("Unknown predictor variable", variable=name)
            role = schema.variable(name).role
            if role is VariableRole.TARGET or name in config.targets:
                raise CausalSeparationError(
                    "Guard 1: a target cannot also be a predictor — causal "
                    "separation requires exogenous inputs only (LOCKED-05)",
                    variable=name,
                )
            if role is not VariableRole.PREDICTOR:
                raise CausalSeparationError(
                    "Causal separation: predictors must be exogenous "
                    "upstream variables (LOCKED-05); this variable's role "
                    "does not establish that",
                    variable=name,
                    role=role.value,
                )

    def _validate_engineered(self, config: FeatureConfig, schema: CanonicalSchema) -> None:
        seen: set[str] = set()
        for spec in config.engineered:
            if not spec.name.strip():
                raise SchemaError("Engineered feature has a blank name")
            if spec.name in seen:
                raise SchemaError("Duplicate engineered feature name", feature=spec.name)
            if spec.name in schema.names():
                raise SchemaError(
                    "Engineered feature name shadows a canonical variable",
                    feature=spec.name,
                )
            seen.add(spec.name)
            self._validate_spec(spec, config, schema)

    @staticmethod
    def _validate_spec(spec: FeatureSpec, config: FeatureConfig, schema: CanonicalSchema) -> None:
        source = spec.source.strip()
        if not source or source not in schema.names():
            raise CausalSeparationError(
                "Causal separation is fail-closed: an engineered feature "
                "must declare a source variable resolvable in the canonical "
                "schema — exogeneity cannot be established otherwise",
                feature=spec.name,
                source=spec.source,
            )
        role = schema.variable(source).role
        if role is VariableRole.TARGET or source in config.targets:
            raise CausalSeparationError(
                f"Guard 8: {_GUARD8_CLASS_MESSAGES[spec.transform]} may never "
                "enter model inputs — an NBM tracking its own target would "
                "suppress the fault-driven residual signal (PROJECT.md §9)",
                feature=spec.name,
                source=source,
                transform=spec.transform.value,
            )
        if role is not VariableRole.PREDICTOR:
            raise CausalSeparationError(
                "Causal separation: engineered features may derive from "
                "exogenous upstream variables only (LOCKED-05)",
                feature=spec.name,
                source=source,
                role=role.value,
            )
        if spec.transform in _STEPPED and spec.periods < 1:
            raise CausalSeparationError(
                "Guard 2: lag/difference steps must look strictly backward; "
                "a non-positive step would admit future information at "
                "inference time",
                feature=spec.name,
                periods=spec.periods,
            )
        if spec.transform in _WINDOWED and spec.window < 2:
            raise CausalSeparationError(
                "Guard 2: rolling windows must be trailing with length >= 2; "
                "anything else is degenerate or would read the future",
                feature=spec.name,
                window=spec.window,
            )


def validate_feature_configuration(config: FeatureConfig, schema: CanonicalSchema) -> None:
    """PROJECT.md §9 entry point: raises on any causal-separation violation."""
    FeatureConfigurationValidator().validate(config, schema)


def _duplicates(names: tuple[str, ...]) -> list[str]:
    return sorted({n for n in names if names.count(n) > 1})
