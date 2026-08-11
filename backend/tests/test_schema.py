"""M-06 tests: versioned canonical schema."""

import ast
from pathlib import Path

import pytest

from app.core.errors import SchemaError
from app.data import schema as schema_module
from app.data.schema import (
    REQUIRED_TARGET_NAMES,
    SCHEMA_VERSION,
    CanonicalSchema,
    CanonicalVariable,
    VariableRole,
    default_schema,
)

# Pinned content hash of the default schema at SCHEMA_VERSION. If this test
# fails, the schema content changed: bump SCHEMA_VERSION and log the change
# in docs/DECISIONS.md ADR-004, then re-pin (M-06 acceptance 2).
PINNED_SCHEMA_HASH = "d32fe02ebc6cf0e8072445c84efd1767c8eb838a4e996d874bce578975c6ad72"


def _minimal_variables() -> tuple[CanonicalVariable, ...]:
    return (
        CanonicalVariable(name="timestamp", role=VariableRole.TIMESTAMP),
        CanonicalVariable(name="turbine_id", role=VariableRole.TURBINE_ID),
        CanonicalVariable(name="wind_speed", role=VariableRole.PREDICTOR, unit="m/s"),
        CanonicalVariable(name="gearbox_oil_temperature", role=VariableRole.TARGET, unit="C"),
        CanonicalVariable(name="gearbox_bearing_temperature", role=VariableRole.TARGET, unit="C"),
    )


class TestSchemaInvariants:
    def test_default_schema_valid_and_versioned(self):
        s = default_schema()
        assert s.schema_version == SCHEMA_VERSION
        assert set(REQUIRED_TARGET_NAMES) <= s.names()

    def test_semver_enforced(self):
        with pytest.raises(SchemaError):
            CanonicalSchema(schema_version="1.0", variables=_minimal_variables())

    def test_duplicate_names_rejected(self):
        variables = (
            *_minimal_variables(),
            CanonicalVariable(name="wind_speed", role=VariableRole.PREDICTOR),
        )
        with pytest.raises(SchemaError):
            CanonicalSchema(schema_version="1.0.0", variables=variables)

    def test_duplicate_structural_role_rejected(self):
        variables = (
            *_minimal_variables(),
            CanonicalVariable(name="timestamp_2", role=VariableRole.TIMESTAMP),
        )
        with pytest.raises(SchemaError):
            CanonicalSchema(schema_version="1.0.0", variables=variables)

    def test_missing_thermal_target_rejected(self):
        variables = tuple(
            v for v in _minimal_variables() if v.name != "gearbox_bearing_temperature"
        )
        with pytest.raises(SchemaError):
            CanonicalSchema(schema_version="1.0.0", variables=variables)

    def test_unknown_variable_lookup_raises(self):
        with pytest.raises(SchemaError):
            default_schema().variable("does_not_exist")

    def test_role_lookup(self):
        s = default_schema()
        assert s.timestamp_name == "timestamp"
        assert s.turbine_id_name == "turbine_id"
        target_names = {v.name for v in s.by_role(VariableRole.TARGET)}
        assert target_names == set(REQUIRED_TARGET_NAMES)


class TestVersionDiscipline:
    def test_content_hash_pinned_to_version(self):
        """M-06 acceptance 2: unversioned schema drift fails."""
        assert default_schema().content_hash() == PINNED_SCHEMA_HASH

    def test_extension_requires_version_bump(self):
        extra = (
            CanonicalVariable(
                name="generator_bearing_temperature", role=VariableRole.TARGET, unit="C"
            ),
        )
        with pytest.raises(SchemaError):
            default_schema().extended(SCHEMA_VERSION, extra)
        extended = default_schema().extended("1.1.0", extra)
        assert "generator_bearing_temperature" in extended.names()
        assert extended.content_hash() != default_schema().content_hash()


class TestNoCanonicalNameLiteralsElsewhere:
    def test_canonical_names_resolve_through_schema_module_only(self):
        """M-06 acceptance 1 (meta-test): no module in ``app`` outside
        data/schema.py embeds canonical variable names as string literals —
        they must resolve through the schema. Structural names ("timestamp",
        "turbine_id") are excluded: they are generic terms that legitimately
        appear in unrelated contexts (e.g. log-record keys)."""
        s = default_schema()
        canonical_names = s.names() - {s.timestamp_name, s.turbine_id_name}
        app_root = Path(schema_module.__file__).resolve().parents[1]
        schema_file = Path(schema_module.__file__).resolve()
        offenders: list[str] = []
        for py_file in app_root.rglob("*.py"):
            if py_file.resolve() == schema_file:
                continue
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and node.value in canonical_names
                ):
                    offenders.append(f"{py_file.name}:{node.lineno}:{node.value!r}")
        assert offenders == [], f"Canonical-name literals outside schema: {offenders}"
