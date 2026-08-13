"""Kelmarsh mapping config + M-07/M-09 filename-identity and encoding modes.

configs/kelmarsh_scada.yaml is real thesis configuration (PROPOSED, pending
author approval); the ingestion fixtures here are SYNTHETIC TEST DATA — NOT
VALID THESIS EVIDENCE.
"""

from pathlib import Path

import pytest

from app.core.errors import SchemaError
from app.data.guards import FeatureConfig, validate_feature_configuration
from app.data.ingestion import ingest_files
from app.data.mapping import load_mapping
from app.data.schema import (
    GEARBOX_BEARING_TEMPERATURE,
    GEARBOX_OIL_TEMPERATURE,
    VariableRole,
    default_schema,
)

SCHEMA = default_schema()
REPO_ROOT = Path(__file__).resolve().parents[2]
KELMARSH_MAPPING = REPO_ROOT / "configs" / "kelmarsh_scada.yaml"


class TestKelmarshMappingConfig:
    def test_loads_with_mandatory_declarations(self):
        mapping = load_mapping(KELMARSH_MAPPING, SCHEMA)
        assert mapping.schema_version == "1.3.0"
        assert mapping.dataset.source_timezone == "UTC"
        assert mapping.dataset.encoding == "utf-8"
        assert mapping.dataset.skip_lines == 9
        assert mapping.dataset.header_comment_prefix == "#"
        assert mapping.dataset.missing_value_tokens == ("NaN",)

    def test_targets_are_the_adr012_designation(self):
        mapping = load_mapping(KELMARSH_MAPPING, SCHEMA)
        assert mapping.columns["Gear oil temperature (°C)"].canonical == (GEARBOX_OIL_TEMPERATURE)
        assert mapping.columns["Rear bearing temperature (°C)"].canonical == (
            GEARBOX_BEARING_TEMPERATURE
        )
        assert not any("inlet" in raw.lower() for raw in mapping.columns)

    def test_no_derived_statistics_and_no_other_thermal_channels(self):
        mapping = load_mapping(KELMARSH_MAPPING, SCHEMA)
        for raw_name in mapping.columns:
            assert not any(
                marker in raw_name
                for marker in (", Max", ", Min", ", Standard deviation", ", StdDev", ", Std")
            ), raw_name
            if mapping.columns[raw_name].canonical not in (
                GEARBOX_OIL_TEMPERATURE,
                GEARBOX_BEARING_TEMPERATURE,
            ):
                assert "bearing" not in raw_name.lower(), raw_name
                assert "oil" not in raw_name.lower(), raw_name

    def test_guard8_accepts_the_proposed_feature_configuration(self):
        """The author's Guard-8 backstop: the mapping's predictor/target
        split must survive the causal-separation chokepoint."""
        mapping = load_mapping(KELMARSH_MAPPING, SCHEMA)
        predictors = tuple(
            sorted(
                spec.canonical
                for spec in mapping.columns.values()
                if SCHEMA.variable(spec.canonical).role is VariableRole.PREDICTOR
            )
        )
        targets = tuple(
            sorted(
                spec.canonical
                for spec in mapping.columns.values()
                if SCHEMA.variable(spec.canonical).role is VariableRole.TARGET
            )
        )
        assert len(predictors) == 7
        assert set(targets) == {GEARBOX_OIL_TEMPERATURE, GEARBOX_BEARING_TEMPERATURE}
        validate_feature_configuration(
            FeatureConfig(predictors=predictors, targets=targets), SCHEMA
        )

    def test_filename_identity_extraction(self):
        mapping = load_mapping(KELMARSH_MAPPING, SCHEMA)
        pattern = mapping.dataset.turbine_id_from_filename
        assert pattern is not None
        assert (
            pattern.extract("Turbine_Data_Kelmarsh_1_2020-01-01_-_2021-01-01_228.csv")
            == "Kelmarsh 1"
        )
        assert (
            pattern.extract("Turbine_Data_Kelmarsh_6_2016-01-03_-_2017-01-01_233.csv")
            == "Kelmarsh 6"
        )
        with pytest.raises(SchemaError):
            pattern.extract("Status_Kelmarsh_1_2020-01-01_-_2021-01-01_228.csv")


GREENBYTE_BANNER = "\n".join(["# synthetic Greenbyte-style banner"] * 9)

FILENAME_MODE_YAML = """
schema_version: 1.2.0
dataset:
  timestamp_column: Date and time
  source_timezone: UTC
  encoding: utf-8
  turbine_id_from_filename:
    pattern: 'Turbine_Data_Kelmarsh_(\\d)_'
    template: 'Kelmarsh \\1'
  skip_lines: 9
  header_comment_prefix: "#"
columns:
  Wind speed (m/s):
    canonical: wind_speed
  Temp (°C):
    canonical: gearbox_oil_temperature
  Bearing (°C):
    canonical: gearbox_bearing_temperature
"""


def _write_turbine_csv(path: Path, rows: list[str]) -> Path:
    header = "# Date and time,Wind speed (m/s),Temp (°C),Bearing (°C)"
    path.write_text("\n".join([GREENBYTE_BANNER, header, *rows]) + "\n", encoding="utf-8")
    return path


class TestFilenameModeIngestion:
    @pytest.fixture
    def mapping(self, tmp_path):
        path = tmp_path / "mapping.yaml"
        path.write_text(FILENAME_MODE_YAML, encoding="utf-8")
        return load_mapping(path, SCHEMA)

    def test_per_file_turbine_identity(self, tmp_path, mapping):
        first = _write_turbine_csv(
            tmp_path / "Turbine_Data_Kelmarsh_1_x.csv",
            ["2020-01-01 00:00:00,7.5,50.0,61.0"],
        )
        second = _write_turbine_csv(
            tmp_path / "Turbine_Data_Kelmarsh_2_x.csv",
            ["2020-01-01 00:00:00,6.0,49.0,60.0"],
        )
        dataset = ingest_files([first, second], mapping, SCHEMA)
        turbines = sorted(dataset.frame[SCHEMA.turbine_id_name].unique())
        assert turbines == ["Kelmarsh 1", "Kelmarsh 2"]

    def test_declared_encoding_is_recorded_and_strict(self, tmp_path, mapping):
        path = _write_turbine_csv(
            tmp_path / "Turbine_Data_Kelmarsh_1_x.csv",
            ["2020-01-01 00:00:00,7.5,50.0,61.0"],
        )
        dataset = ingest_files([path], mapping, SCHEMA)
        assert dataset.provenance.sources[0].encoding == "utf-8"

    def test_wrong_declared_encoding_fails_loudly(self, tmp_path):
        yaml_text = FILENAME_MODE_YAML.replace("encoding: utf-8", "encoding: utf-32")
        mapping_path = tmp_path / "mapping.yaml"
        mapping_path.write_text(yaml_text, encoding="utf-8")
        mapping = load_mapping(mapping_path, SCHEMA)
        path = _write_turbine_csv(
            tmp_path / "Turbine_Data_Kelmarsh_1_x.csv",
            ["2020-01-01 00:00:00,7.5,50.0,61.0"],
        )
        with pytest.raises(Exception):  # noqa: B017 — decode failure surfaces, never replaces
            ingest_files([path], mapping, SCHEMA)

    def test_exactly_one_identity_mode_enforced(self, tmp_path):
        conflicting = FILENAME_MODE_YAML.replace(
            "  turbine_id_from_filename:",
            "  turbine_id_constant: T9\n  turbine_id_from_filename:",
        )
        path = tmp_path / "mapping.yaml"
        path.write_text(conflicting, encoding="utf-8")
        with pytest.raises(SchemaError, match="exactly one"):
            load_mapping(path, SCHEMA)

    def test_pattern_without_capture_group_rejected(self, tmp_path):
        bad = FILENAME_MODE_YAML.replace(r"Turbine_Data_Kelmarsh_(\d)_", "Turbine_Data_")
        path = tmp_path / "mapping.yaml"
        path.write_text(bad, encoding="utf-8")
        with pytest.raises(SchemaError, match="capture group"):
            load_mapping(path, SCHEMA)

    def test_invalid_regex_rejected(self, tmp_path):
        bad = FILENAME_MODE_YAML.replace(r"Turbine_Data_Kelmarsh_(\d)_", "([unclosed")
        path = tmp_path / "mapping.yaml"
        path.write_text(bad, encoding="utf-8")
        with pytest.raises(SchemaError, match="regex"):
            load_mapping(path, SCHEMA)
