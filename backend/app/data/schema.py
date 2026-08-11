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
SCHEMA_VERSION = "1.0.0"

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

#: Thermal targets the thesis requires at minimum (PROJECT.md §8).
REQUIRED_TARGET_NAMES: tuple[str, ...] = (
    "gearbox_oil_temperature",
    "gearbox_bearing_temperature",
)


class CanonicalVariable(BaseModel):
    """One canonical variable: generic name, role, unit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    role: VariableRole
    unit: str | None = None
    description: str = ""


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
        CanonicalVariable(name="timestamp", role=VariableRole.TIMESTAMP, unit=None),
        CanonicalVariable(name="turbine_id", role=VariableRole.TURBINE_ID, unit=None),
        CanonicalVariable(name="wind_speed", role=VariableRole.PREDICTOR, unit="m/s"),
        CanonicalVariable(name="rotor_speed", role=VariableRole.PREDICTOR, unit="rpm"),
        CanonicalVariable(name="generator_speed", role=VariableRole.PREDICTOR, unit="rpm"),
        CanonicalVariable(name="active_power", role=VariableRole.PREDICTOR, unit="kW"),
        CanonicalVariable(name="pitch_angle", role=VariableRole.PREDICTOR, unit="deg"),
        CanonicalVariable(name="ambient_temperature", role=VariableRole.PREDICTOR, unit=celsius),
        CanonicalVariable(name="nacelle_temperature", role=VariableRole.PREDICTOR, unit=celsius),
        CanonicalVariable(name="gearbox_oil_temperature", role=VariableRole.TARGET, unit=celsius),
        CanonicalVariable(
            name="gearbox_bearing_temperature", role=VariableRole.TARGET, unit=celsius
        ),
    )
    return CanonicalSchema(schema_version=SCHEMA_VERSION, variables=variables)
