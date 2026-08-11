"""M-08/M-09 tests: provenance, ingestion, UTC normalization, deduplication.

Fixtures are SYNTHETIC TEST DATA — NOT VALID THESIS EVIDENCE — with no fault
labels (LOCKED-08).
"""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app.core.errors import ProvenanceError, SchemaError
from app.data.ingestion import (
    CanonicalDataset,
    deduplicate,
    detect_encoding,
    ingest_files,
)
from app.data.mapping import load_mapping
from app.data.provenance import ProvenanceChain, ProvenanceRecord, sha256_of_file
from app.data.schema import default_schema

MAPPING_YAML = """
schema_version: 1.1.0
dataset:
  timestamp_column: RawTime
  source_timezone: UTC
  turbine_column: RawUnit
  skip_lines: 9
  header_comment_prefix: "#"
  missing_value_tokens: ["NaN"]
columns:
  RawWind:
    canonical: wind_speed
  RawPower:
    canonical: active_power
  RawAmbient:
    canonical: ambient_temperature
  RawOilTemp:
    canonical: gearbox_oil_temperature
  RawBearingTemp:
    canonical: gearbox_bearing_temperature
"""

BANNER = "\n".join(["# synthetic export banner"] * 9)


@pytest.fixture
def schema():
    return default_schema()


@pytest.fixture
def mapping(tmp_path, schema):
    path = tmp_path / "mapping.yaml"
    path.write_text(MAPPING_YAML, encoding="utf-8")
    return load_mapping(path, schema)


def _write_scada(path: Path, rows: list[str]) -> Path:
    header = "# RawTime,RawUnit,RawWind,RawPower,RawAmbient,RawOilTemp,RawBearingTemp"
    path.write_text("\n".join([BANNER, header, *rows]) + "\n", encoding="utf-8")
    return path


def _row(ts: str, turbine: str = "T1", oil: str = "50.0", power: str = "900") -> str:
    return f"{ts},{turbine},7.5,{power},9.0,{oil},61.0"


class TestProvenance:
    def test_record_captures_identity_and_verifies(self, tmp_path):
        path = _write_scada(tmp_path / "a.csv", [_row("2020-01-01 00:00:00")])
        record = ProvenanceRecord.capture(
            path,
            source_timezone="UTC",
            encoding="utf-8",
            schema_version="1.1.0",
            mapping_hash="abc",
        )
        assert record.sha256 == sha256_of_file(path)
        assert record.source_filename == "a.csv"
        assert record.size_bytes > 0
        record.verify()

    def test_tampered_source_fails_verification(self, tmp_path):
        path = _write_scada(tmp_path / "a.csv", [_row("2020-01-01 00:00:00")])
        record = ProvenanceRecord.capture(
            path,
            source_timezone="UTC",
            encoding="utf-8",
            schema_version="1.1.0",
            mapping_hash="abc",
        )
        path.write_text(
            path.read_text(encoding="utf-8") + _row("2020-01-01 00:10:00") + "\n", encoding="utf-8"
        )
        with pytest.raises(ProvenanceError):
            record.verify()

    def test_chain_extension_preserves_ancestry(self, tmp_path):
        path = _write_scada(tmp_path / "a.csv", [_row("2020-01-01 00:00:00")])
        record = ProvenanceRecord.capture(
            path,
            source_timezone="UTC",
            encoding="utf-8",
            schema_version="1.1.0",
            mapping_hash="abc",
        )
        chain = ProvenanceChain(sources=(record,))
        extended = chain.extended("cleaned", "hash1").extended("healthy", "hash2")
        assert extended.source_hashes == chain.source_hashes
        assert [s[0] for s in extended.stages] == ["cleaned", "healthy"]

    def test_dataset_cannot_exist_without_provenance(self):
        with pytest.raises(ProvenanceError):
            CanonicalDataset(
                frame=pd.DataFrame({"a": [1]}),
                schema_version="1.1.0",
                provenance=ProvenanceChain(sources=()),
                roles={},
            )


class TestEncoding:
    def test_utf8_detected_strictly(self, tmp_path):
        path = tmp_path / "utf8.csv"
        path.write_text("Gear oil temperature (°C)\n", encoding="utf-8")
        assert detect_encoding(path) == "utf-8"

    def test_non_utf8_falls_back_explicitly_not_silently(self, tmp_path):
        path = tmp_path / "cp1252.csv"
        path.write_bytes("Gear oil temperature (°C)\n".encode("cp1252"))
        encoding = detect_encoding(path)
        assert encoding != "utf-8"
        # The degree sign survives — no replacement characters.
        assert "°C" in path.read_text(encoding=encoding)


class TestIngestion:
    def test_utc_normalization_and_provenance(self, tmp_path, mapping, schema):
        path = _write_scada(
            tmp_path / "a.csv",
            [
                _row("2020-06-01 00:00:00"),
                _row("2020-06-01 00:10:00"),
            ],
        )
        dataset = ingest_files([path], mapping, schema)
        stamps = dataset.frame[schema.timestamp_name]
        assert str(stamps.dt.tz) == "UTC"
        assert len(dataset.provenance.sources) == 1
        assert dataset.provenance.sources[0].encoding == "utf-8"
        assert dataset.roles["gearbox_oil_temperature"].value == "target"

    def test_source_file_untouched(self, tmp_path, mapping, schema):
        path = _write_scada(tmp_path / "a.csv", [_row("2020-06-01 00:00:00")])
        before = sha256_of_file(path)
        ingest_files([path], mapping, schema)
        assert sha256_of_file(path) == before

    def test_literal_nan_token_is_missing(self, tmp_path, mapping, schema):
        path = _write_scada(tmp_path / "a.csv", [_row("2020-06-01 00:00:00", oil="NaN")])
        dataset = ingest_files([path], mapping, schema)
        assert dataset.frame["gearbox_oil_temperature"].isna().all()

    def test_non_utc_source_timezone_converted(self, tmp_path, schema):
        yaml_text = MAPPING_YAML.replace("source_timezone: UTC", "source_timezone: Europe/London")
        mapping_path = tmp_path / "m.yaml"
        mapping_path.write_text(yaml_text, encoding="utf-8")
        mapping = load_mapping(mapping_path, schema)
        path = _write_scada(tmp_path / "a.csv", [_row("2020-07-01 12:00:00")])
        dataset = ingest_files([path], mapping, schema)
        # British Summer Time: local 12:00 is 11:00 UTC.
        assert dataset.frame[schema.timestamp_name].iloc[0] == pd.Timestamp(
            "2020-07-01 11:00:00", tz="UTC"
        )

    def test_span_filter_excludes_outside_rows(self, tmp_path, mapping, schema):
        path = _write_scada(
            tmp_path / "a.csv",
            [
                _row("2016-01-10 00:00:00"),
                _row("2016-05-03 12:00:00"),
                _row("2021-06-30 23:50:00"),
                _row("2021-07-01 00:00:00"),
            ],
        )
        dataset = ingest_files(
            [path],
            mapping,
            schema,
            span_start=date(2016, 5, 3),
            span_end=date(2021, 6, 30),
        )
        stamps = dataset.frame[schema.timestamp_name]
        assert len(stamps) == 2
        assert stamps.min() == pd.Timestamp("2016-05-03 12:00:00", tz="UTC")
        assert stamps.max() == pd.Timestamp("2021-06-30 23:50:00", tz="UTC")

    def test_no_files_raises(self, mapping, schema):
        with pytest.raises(SchemaError):
            ingest_files([], mapping, schema)


class TestDeduplication:
    def test_overlapping_year_folders_deduplicate(self, tmp_path, mapping, schema):
        """The real overlap: the 2021 export begins inside 2020, so the same
        row appears in both files (LIM-006)."""
        shared = _row("2020-12-31 23:50:00")
        file_2020 = _write_scada(tmp_path / "y2020.csv", [_row("2020-12-31 23:40:00"), shared])
        file_2021 = _write_scada(tmp_path / "y2021.csv", [shared, _row("2021-01-01 00:00:00")])
        dataset = ingest_files([file_2020, file_2021], mapping, schema)
        report = dataset.deduplication
        assert report is not None
        assert report.rows_before == 4
        assert report.rows_after == 3
        assert report.duplicates_removed == 1
        assert report.removed_per_source == {"y2021.csv": 1}
        assert len(dataset.frame) == 3

    def test_conflicting_duplicate_raises_rather_than_choosing(self, tmp_path, mapping, schema):
        a = _write_scada(tmp_path / "a.csv", [_row("2020-12-31 23:50:00", oil="50.0")])
        b = _write_scada(tmp_path / "b.csv", [_row("2020-12-31 23:50:00", oil="55.0")])
        with pytest.raises(ProvenanceError, match="differ in content"):
            ingest_files([a, b], mapping, schema)

    def test_distinct_turbines_at_same_timestamp_are_kept(self, tmp_path, mapping, schema):
        path = _write_scada(
            tmp_path / "a.csv",
            [
                _row("2020-06-01 00:00:00", turbine="T1"),
                _row("2020-06-01 00:00:00", turbine="T2"),
            ],
        )
        dataset = ingest_files([path], mapping, schema)
        assert len(dataset.frame) == 2
        assert dataset.deduplication.duplicates_removed == 0

    def test_deduplicate_requires_known_key_columns(self):
        frame = pd.DataFrame({"a": [1, 2]})
        with pytest.raises(SchemaError):
            deduplicate(frame, ["missing_column"])


class TestStatusCodeKeyedDeduplication:
    """Status exports carry a code, so the key must include it — otherwise two
    genuinely different alarms at one timestamp would collide."""

    def test_code_column_included_in_key_when_schema_defines_status(self, tmp_path, schema):
        from app.data.schema import CanonicalSchema, CanonicalVariable, VariableRole

        extended = CanonicalSchema(
            schema_version="1.2.0",
            variables=(
                *schema.variables,
                CanonicalVariable(name="status_code", role=VariableRole.STATUS),
            ),
        )
        yaml_text = MAPPING_YAML.replace("schema_version: 1.1.0", "schema_version: 1.2.0").replace(
            "  RawWind:\n    canonical: wind_speed\n",
            "  RawWind:\n    canonical: wind_speed\n  RawCode:\n    canonical: status_code\n",
        )
        mapping_path = tmp_path / "m.yaml"
        mapping_path.write_text(yaml_text, encoding="utf-8")
        mapping = load_mapping(mapping_path, extended)

        header = "# RawTime,RawUnit,RawWind,RawPower,RawAmbient,RawOilTemp,RawBearingTemp,RawCode"
        rows = [
            "2020-12-31 23:50:00,T1,7.5,900,9.0,50.0,61.0,7057",
            "2020-12-31 23:50:00,T1,7.5,900,9.0,50.0,61.0,1860",
        ]
        path = tmp_path / "status.csv"
        path.write_text("\n".join([BANNER, header, *rows]) + "\n", encoding="utf-8")
        dataset = ingest_files([path], mapping, extended)
        # Same turbine and timestamp, different codes: both survive.
        assert len(dataset.frame) == 2
        assert dataset.deduplication.duplicates_removed == 0
        assert "status_code" in dataset.deduplication.key_columns
