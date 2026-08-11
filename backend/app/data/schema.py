"""Versioned canonical SCADA schema (M-06; PROJECT.md §8).

Canonical variable names are generic. No real dataset's column names appear
here or anywhere downstream of here — dataset-specific names enter the
system exclusively through mapping configs (M-07, `app/data/mapping.py`).

Schema changes require a semver bump recorded in docs/DECISIONS.md (ADR-004);
a pinned-hash test fails on unversioned drift.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator

from app.core.errors import SchemaError

#: Current canonical schema version (semver). Bump via ADR-004 only.
#: 1.1.0 — added `plausible_range` to CanonicalVariable so physical bounds
#: are declared with the variable rather than duplicated in validation.
SCHEMA_VERSION = "1.1.0"

_SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class VariableRole(StrEnum):
    """Variable roles (PROJECT.md §8)."""

    TIMESTAMP = "timestamp"
    TURBINE_ID = "turbine_id"
    PREDICTOR = "predictor"
    TARGET = "target"
    STATUS = "status"
    ALARM = "alarm"
    MAINTENANCE = "maintenance"
    EXCLUDED = "excluded"


#: Structural roles that must appear exactly once per schema.
UNIQUE_ROLES: tuple[VariableRole, ...] = (VariableRole.TIMESTAMP, VariableRole.TURBINE_ID)

#: Canonical names referenced by pipeline logic. Other modules import these
#: constants rather than embedding the strings, so every canonical name
#: resolves through this module (M-06 acceptance 1).
TIMESTAMP = "timestamp"
TURBINE_ID = "turbine_id"
WIND_SPEED = "wind_speed"
ROTOR_SPEED = "rotor_speed"
GENERATOR_SPEED = "generator_speed"
ACTIVE_POWER = "active_power"
PITCH_ANGLE = "pitch_angle"
AMBIENT_TEMPERATURE = "ambient_temperature"
NACELLE_TEMPERATURE = "nacelle_temperature"
GEARBOX_OIL_TEMPERATURE = "gearbox_oil_temperature"
GEARBOX_BEARING_TEMPERATURE = "gearbox_bearing_temperature"

#: Thermal targets the thesis requires at minimum (PROJECT.md §8).
REQUIRED_TARGET_NAMES: tuple[str, ...] = (
    GEARBOX_OIL_TEMPERATURE,
    GEARBOX_BEARING_TEMPERATURE,
)


class CanonicalVariable(BaseModel):
    """One canonical variable: generic name, role, unit, physical bounds."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    role: VariableRole
    unit: str | None = None
    description: str = ""
    #: Physically impossible bounds (not operating limits). Validation
    #: reports values outside them; it never clips or corrects.
    plausible_range: tuple[float, float] | None = None


class CanonicalSchema(BaseModel):
    """The versioned canonical variable set.

    Invariants enforced at construction: valid semver, unique names, exactly
    one timestamp and one turbine_id variable, and both required thermal
    targets present with role TARGET.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    variables: tuple[CanonicalVariable, ...]

    @model_validator(mode="after")
    def _validate(self) -> CanonicalSchema:
        if not _SEMVER_RE.match(self.schema_version):
            raise SchemaError(
                "schema_version must be valid semver", schema_version=self.schema_version
            )
        names = [v.name for v in self.variables]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise SchemaError("Duplicate canonical variable names", duplicates=duplicates)
        for role in UNIQUE_ROLES:
            count = sum(1 for v in self.variables if v.role is role)
            if count != 1:
                raise SchemaError(
                    "Structural role must appear exactly once", role=role.value, count=count
                )
        for required in REQUIRED_TARGET_NAMES:
            match = next((v for v in self.variables if v.name == required), None)
            if match is None or match.role is not VariableRole.TARGET:
                raise SchemaError(
                    "Required thermal target missing or mis-roled (PROJECT.md §8)",
                    variable=required,
                )
        return self

    def names(self) -> frozenset[str]:
        return frozenset(v.name for v in self.variables)

    def variable(self, name: str) -> CanonicalVariable:
        for v in self.variables:
            if v.name == name:
                return v
        raise SchemaError("Unknown canonical variable", variable=name)

    def by_role(self, role: VariableRole) -> tuple[CanonicalVariable, ...]:
        return tuple(v for v in self.variables if v.role is role)

    @property
    def timestamp_name(self) -> str:
        return self.by_role(VariableRole.TIMESTAMP)[0].name

    @property
    def turbine_id_name(self) -> str:
        return self.by_role(VariableRole.TURBINE_ID)[0].name

    def content_hash(self) -> str:
        """SHA-256 over the canonical serialization; pinned by a drift test
        so schema changes without a version bump fail CI (M-06 acceptance 2)."""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def extended(
        self, new_version: str, extra_variables: tuple[CanonicalVariable, ...]
    ) -> CanonicalSchema:
        """A new schema with additional variables — requires a version bump
        (ADR-004 log entry) because content changes."""
        if new_version == self.schema_version:
            raise SchemaError(
                "Schema content change requires a version bump (ADR-004)",
                schema_version=new_version,
            )
        return CanonicalSchema(
            schema_version=new_version, variables=(*self.variables, *extra_variables)
        )


def default_schema() -> CanonicalSchema:
    """The canonical schema at SCHEMA_VERSION: structural variables, the
    thesis-identified upstream predictors, and the required thermal targets
    (PROJECT.md §8). Additional dataset-specific variables are added via
    :meth:`CanonicalSchema.extended` under a bumped version."""
    celsius = "C"
    variables = (
        CanonicalVariable(name=TIMESTAMP, role=VariableRole.TIMESTAMP, unit=None),
        CanonicalVariable(name=TURBINE_ID, role=VariableRole.TURBINE_ID, unit=None),
        CanonicalVariable(
            name=WIND_SPEED,
            role=VariableRole.PREDICTOR,
            unit="m/s",
            plausible_range=(0.0, 120.0),
        ),
        CanonicalVariable(
            name=ROTOR_SPEED,
            role=VariableRole.PREDICTOR,
            unit="rpm",
            plausible_range=(-1.0, 100.0),
        ),
        CanonicalVariable(
            name=GENERATOR_SPEED,
            role=VariableRole.PREDICTOR,
            unit="rpm",
            plausible_range=(-1.0, 5000.0),
        ),
        CanonicalVariable(name=ACTIVE_POWER, role=VariableRole.PREDICTOR, unit="kW"),
        CanonicalVariable(
            name=PITCH_ANGLE,
            role=VariableRole.PREDICTOR,
            unit="deg",
            plausible_range=(-360.0, 360.0),
        ),
        CanonicalVariable(
            name=AMBIENT_TEMPERATURE,
            role=VariableRole.PREDICTOR,
            unit=celsius,
            plausible_range=(-90.0, 70.0),
        ),
        CanonicalVariable(
            name=NACELLE_TEMPERATURE,
            role=VariableRole.PREDICTOR,
            unit=celsius,
            plausible_range=(-90.0, 120.0),
        ),
        CanonicalVariable(
            name=GEARBOX_OIL_TEMPERATURE,
            role=VariableRole.TARGET,
            unit=celsius,
            plausible_range=(-90.0, 200.0),
        ),
        CanonicalVariable(
            name=GEARBOX_BEARING_TEMPERATURE,
            role=VariableRole.TARGET,
            unit=celsius,
            plausible_range=(-90.0, 250.0),
        ),
    )
    return CanonicalSchema(schema_version=SCHEMA_VERSION, variables=variables)
