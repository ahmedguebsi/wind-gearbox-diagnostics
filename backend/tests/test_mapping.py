"""M-07 tests: raw→canonical mapping with mandatory source_timezone.

Fixture column names are deliberately fictional (SYNTHETIC TEST DATA — NOT
VALID THESIS EVIDENCE); no real dataset's column names appear in code.
"""

from pathlib import Path

import pandas as pd
import pytest

from app.core.errors import SchemaError, TimezoneError
from app.data.mapping import load_mapping
from app.data.schema import SCHEMA_VERSION, default_schema

VALID_YAML = f"""
schema_version: {SCHEMA_VERSION}
dataset:
  timestamp_column: RawTime
  source_timezone: Europe/London
  turbine_id_constant: "T01"
columns:
  RawWind:
    canonical: wind_speed
  RawPower:
    canonical: active_power
  RawOilTemp:
    canonical: gearbox_oil_temperature
  RawBearingTemp:
    canonical: gearbox_bearing_temperature
"""


@pytest.fixture
def schema():
    return default_schema()


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "mapping.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def _raw_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "RawTime": ["2016-06-01 10:00", "2016-06-01 10:10"],
            "RawWind": [6.1, 6.4],
            "RawPower": [850.0, 900.0],
            "RawOilTemp": [55.2, 55.4],
            "RawBearingTemp": [61.0, 61.3],
            "UnmappedExtra": [1, 2],
        }
    )


class TestLoadValidation:
    def test_valid_mapping_loads(self, tmp_path, schema):
        mapping = load_mapping(_write(tmp_path, VALID_YAML), schema)
        assert mapping.dataset.source_timezone == "Europe/London"
        assert not mapping.is_outdated()

    def test_missing_source_timezone_raises_timezone_error(self, tmp_path, schema):
        content = VALID_YAML.replace("  source_timezone: Europe/London\n", "")
        with pytest.raises(TimezoneError):
            load_mapping(_write(tmp_path, content), schema)

    def test_empty_source_timezone_raises_timezone_error(self, tmp_path, schema):
        content = VALID_YAML.replace("Europe/London", "''")
        with pytest.raises(TimezoneError):
            load_mapping(_write(tmp_path, content), schema)

    def test_unresolvable_timezone_raises_timezone_error(self, tmp_path, schema):
        content = VALID_YAML.replace("Europe/London", "Mars/Olympus")
        with pytest.raises(TimezoneError):
            load_mapping(_write(tmp_path, content), schema)

    def test_unknown_canonical_rejected(self, tmp_path, schema):
        content = VALID_YAML.replace("canonical: wind_speed", "canonical: warp_speed")
        with pytest.raises(SchemaError):
            load_mapping(_write(tmp_path, content), schema)

    def test_duplicate_canonical_assignment_rejected(self, tmp_path, schema):
        content = VALID_YAML.replace("canonical: active_power", "canonical: wind_speed")
        with pytest.raises(SchemaError):
            load_mapping(_write(tmp_path, content), schema)

    def test_structural_variable_in_columns_rejected(self, tmp_path, schema):
        content = VALID_YAML.replace("canonical: wind_speed", "canonical: turbine_id")
        with pytest.raises(SchemaError):
            load_mapping(_write(tmp_path, content), schema)

    def test_no_target_mapped_rejected(self, tmp_path, schema):
        content = VALID_YAML.replace(
            "  RawOilTemp:\n    canonical: gearbox_oil_temperature\n", ""
        ).replace("  RawBearingTemp:\n    canonical: gearbox_bearing_temperature\n", "")
        with pytest.raises(SchemaError):
            load_mapping(_write(tmp_path, content), schema)

    def test_both_turbine_declarations_rejected(self, tmp_path, schema):
        content = VALID_YAML.replace(
            'turbine_id_constant: "T01"', 'turbine_id_constant: "T01"\n  turbine_column: RawUnit'
        )
        with pytest.raises(SchemaError):
            load_mapping(_write(tmp_path, content), schema)

    def test_neither_turbine_declaration_rejected(self, tmp_path, schema):
        content = VALID_YAML.replace('  turbine_id_constant: "T01"\n', "")
        with pytest.raises(SchemaError):
            load_mapping(_write(tmp_path, content), schema)

    def test_missing_file_raises_schema_error(self, tmp_path, schema):
        with pytest.raises(SchemaError):
            load_mapping(tmp_path / "absent.yaml", schema)

    def test_outdated_schema_version_flagged(self, tmp_path, schema):
        content = VALID_YAML.replace(f"schema_version: {SCHEMA_VERSION}", "schema_version: 0.9.0")
        mapping = load_mapping(_write(tmp_path, content), schema)
        assert mapping.is_outdated()


class TestToCanonical:
    def test_round_trip_renames_and_constant_turbine(self, tmp_path, schema):
        mapping = load_mapping(_write(tmp_path, VALID_YAML), schema)
        raw = _raw_frame()
        out = mapping.to_canonical(raw, schema)
        assert set(out.columns) == {
            schema.timestamp_name,
            schema.turbine_id_name,
            "wind_speed",
            "active_power",
            "gearbox_oil_temperature",
            "gearbox_bearing_temperature",
        }
        assert (out[schema.turbine_id_name] == "T01").all()
        assert out["wind_speed"].tolist() == [6.1, 6.4]
        assert "UnmappedExtra" not in out.columns

    def test_source_frame_untouched(self, tmp_path, schema):
        mapping = load_mapping(_write(tmp_path, VALID_YAML), schema)
        raw = _raw_frame()
        before = raw.copy(deep=True)
        mapping.to_canonical(raw, schema)
        pd.testing.assert_frame_equal(raw, before)

    def test_turbine_column_variant(self, tmp_path, schema):
        content = VALID_YAML.replace('turbine_id_constant: "T01"', "turbine_column: RawUnit")
        mapping = load_mapping(_write(tmp_path, content), schema)
        raw = _raw_frame()
        raw["RawUnit"] = ["T01", "T02"]
        out = mapping.to_canonical(raw, schema)
        assert out[schema.turbine_id_name].tolist() == ["T01", "T02"]

    def test_missing_raw_columns_listed(self, tmp_path, schema):
        mapping = load_mapping(_write(tmp_path, VALID_YAML), schema)
        raw = _raw_frame().drop(columns=["RawWind", "RawOilTemp"])
        with pytest.raises(SchemaError) as excinfo:
            mapping.to_canonical(raw, schema)
        assert excinfo.value.context["missing"] == ["RawOilTemp", "RawWind"]


class TestMappingHash:
    def test_hash_deterministic_and_content_sensitive(self, tmp_path, schema):
        a = load_mapping(_write(tmp_path, VALID_YAML), schema)
        b = load_mapping(_write(tmp_path, VALID_YAML), schema)
        assert a.mapping_hash == b.mapping_hash
        changed = VALID_YAML.replace('"T01"', '"T02"')
        c = load_mapping(_write(tmp_path, changed), schema)
        assert c.mapping_hash != a.mapping_hash
