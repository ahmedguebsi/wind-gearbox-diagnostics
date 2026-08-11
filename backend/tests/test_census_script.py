"""Tests for scripts/dataset_census.py (Phase 0.5 evidence generator).

Fixtures are SYNTHETIC TEST DATA — NOT VALID THESIS EVIDENCE — and contain
no fault labels (LOCKED-08). They reproduce the Greenbyte export shape: nine
``#`` comment lines, the column header on row 10, and — for turbine data —
that header row itself carrying a ``# `` prefix, which a naive
``comment='#'`` read would silently consume.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dataset_census.py"

COMMENTS = [
    "# This file was exported by Greenbyte at 2022-01-27 23:29:26.",
    "#",
    "# Turbine: Synthetic 1",
    "# Turbine type: Synthetic Model X",
    "# Time zone: UTC",
    "# Time interval: 2020-01-01 00:00:00 - 2020-01-02 00:00:00 (1 days)",
    "#",
    "# Synthetic 1 Sum production: 12345 kWh",
    "#",
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    tmp_path = tmp_path / "export"  # keep census output outside the censused folder
    tmp_path.mkdir()
    scada = ["\n".join(COMMENTS)]
    # Header row prefixed with "# ", as Turbine_Data files are.
    scada.append("# Date and time,Synth wind speed (m/s),SynthConst,Gear oil temperature (°C)")
    minutes = [i * 10 for i in range(12) if i != 5]  # one skipped slot -> gap
    for m in minutes:
        hh, mm = divmod(m, 60)
        scada.append(f"2020-01-01 {hh:02d}:{mm:02d}:00,{5 + m / 100},7.0,{50 + m / 50}")
    scada.append("2020-01-01 00:10:00,5.1,7.0,50.2")  # duplicate timestamp
    scada.append("2020-01-01 02:00:00,NaN,7.0,NaN")  # literal NaN missing marker
    (tmp_path / "Turbine_Data_Synthetic_1_2020.csv").write_text(
        "\n".join(scada) + "\n", encoding="utf-8"
    )

    status = ["\n".join(COMMENTS)]
    status.append(
        "Timestamp start,Timestamp end,Duration,Status,Code,Message,Comment,"
        "Service contract category,IEC category"
    )
    status.append(
        "2020-01-01 08:42:37,2020-01-01 08:43:25,00:00:48,Informational,10,"
        "Wind < start wind,,External stop (5),Out of Environmental Specification"
    )
    status.append(
        "2020-01-01 09:00:00,-,-,Informational,100070,Brake program 50,,,Full Performance"
    )
    status.append(
        "2020-01-02 05:14:40,2020-01-02 05:52:51,00:38:11,Warning,1700,"
        "High temp. gear bearing 1,,Warnings (27),"
    )
    status.append(
        "2020-01-03 05:00:00,2020-01-03 06:00:00,01:00:00,Stop,5760,"
        "Hydraulic oil flushing operation,,Operating states (28),Technical Standby"
    )
    (tmp_path / "Status_Synthetic_1_2020.csv").write_text(
        "\n".join(status) + "\n", encoding="utf-8"
    )

    (tmp_path / "REPORT.md").write_text("derived artefact\n", encoding="utf-8")
    (tmp_path / "script.py").write_text("# derived artefact\n", encoding="utf-8")
    (tmp_path / "SOMETHING_ELSE.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    return tmp_path


def _run(folder: Path, out: Path) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--folder", str(folder), "--output", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(out.read_text(encoding="utf-8"))


class TestClassificationAndProvenance:
    def test_inventory_classifies_and_hashes_every_file(self, folder, tmp_path):
        report = _run(folder, tmp_path / "out.json")
        by_name = {e["name"]: e for e in report["inventory"]}
        assert by_name["Turbine_Data_Synthetic_1_2020.csv"]["classification"] == "SOURCE_SCADA"
        assert by_name["Status_Synthetic_1_2020.csv"]["classification"] == "SOURCE_STATUS"
        assert by_name["REPORT.md"]["classification"] == "EXCLUDED_DERIVED"
        assert by_name["script.py"]["classification"] == "EXCLUDED_DERIVED"
        assert (
            by_name["SOMETHING_ELSE.csv"]["classification"]
            == "UNCLASSIFIED_REQUIRES_AUTHOR_DECISION"
        )
        # Excluded and unclassified files are inventoried with hashes but not read.
        assert by_name["REPORT.md"]["content_read_by_census"] is False
        assert by_name["SOMETHING_ELSE.csv"]["content_read_by_census"] is False
        assert all(len(e["sha256"]) == 64 and e["size_bytes"] > 0 for e in report["inventory"])
        assert report["unclassified_requiring_author_decision"] == ["SOMETHING_ELSE.csv"]

    def test_read_only_verified_by_rehash(self, folder, tmp_path):
        before = {p.name: _sha(p) for p in folder.iterdir() if p.is_file()}
        report = _run(folder, tmp_path / "out.json")
        assert report["read_only_verification"]["inputs_unchanged"] is True
        assert {p.name: _sha(p) for p in folder.iterdir() if p.is_file()} == before

    def test_output_inside_censused_folder_is_refused(self, folder):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--folder",
                str(folder),
                "--output",
                str(folder / "census.json"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert "must not be inside" in result.stderr
        assert not (folder / "census.json").exists()

    def test_header_provenance_declared_not_assumed(self, folder, tmp_path):
        report = _run(folder, tmp_path / "out.json")
        prov = report["header_provenance"]["Turbine_Data_Synthetic_1_2020.csv"]
        assert prov["declared"]["turbine"] == "Synthetic 1"
        assert prov["declared"]["turbine_type"] == "Synthetic Model X"
        assert prov["declared"]["time_zone"] == "UTC"
        assert "2020-01-01" in prov["declared"]["time_interval"]
        assert prov["header_row_number_1_indexed"] == 10
        assert prov["header_row_is_comment_prefixed"] is True
        # The "# " prefix is stripped, so the header is not swallowed.
        assert prov["columns"][0] == "Date and time"
        status_prov = report["header_provenance"]["Status_Synthetic_1_2020.csv"]
        assert status_prov["header_row_is_comment_prefixed"] is False
        assert status_prov["declared"]["sum_production"].endswith("12345 kWh")
        assert report["timezone"]["distinct_declared_values"] == ["UTC"]


class TestStatusInventory:
    def test_codes_statuses_and_completeness(self, folder, tmp_path):
        si = _run(folder, tmp_path / "out.json")["status_inventory"]
        assert si["total_rows"] == 4
        assert si["status_values"] == {"Informational": 2, "Warning": 1, "Stop": 1}
        codes = {c["code"]: c for c in si["codes_by_total_duration_desc"]}
        assert codes["1700"]["messages_verbatim"] == {"High temp. gear bearing 1": 1}
        assert codes["1700"]["turbines_affected"] == ["Synthetic 1"]
        assert codes["1700"]["first_occurrence"] == "2020-01-02 05:14:40"
        assert codes["100070"]["rows_without_duration"] == 1
        # Sorted by total duration descending.
        durations = [c["total_duration_seconds"] for c in si["codes_by_total_duration_desc"]]
        assert durations == sorted(durations, reverse=True)
        assert si["completeness"]["timestamp_end"]["populated"] == 3
        assert si["completeness"]["timestamp_end"]["blank_dash"] == 1

    def test_absent_free_text_column_reported_not_substituted(self, folder, tmp_path):
        si = _run(folder, tmp_path / "out.json")["status_inventory"]
        assert si["free_text_fields"]["Comment"]["present_in_files"] is True
        assert si["free_text_fields"]["Comment"]["n_distinct_non_empty"] == 0
        service = si["free_text_fields"]["Service comment"]
        assert service["present_in_files"] is False
        assert "does not exist" in service["note"]
        assert "Service contract category" in si["other_categorical_fields"]


class TestKeywordCandidates:
    def test_matches_are_candidates_with_full_row_context(self, folder, tmp_path):
        kc = _run(folder, tmp_path / "out.json")["keyword_candidates"]
        assert "CANDIDATES FOR AUTHOR REVIEW" in kc["note"]
        assert kc["truncated"] is False
        assert kc["n_matching_rows"] == 2  # gear bearing warning + oil flushing
        by_code = {m["row_verbatim"]["Code"]: m for m in kc["matches"]}
        gear = by_code["1700"]
        assert sorted(gear["matched_keywords"]) == ["bearing", "gear"]
        assert set(gear["row_verbatim"]) == {
            "Timestamp start",
            "Timestamp end",
            "Duration",
            "Status",
            "Code",
            "Message",
            "Comment",
            "Service contract category",
            "IEC category",
        }
        assert gear["row_verbatim"]["Status"] == "Warning"


class TestScadaCensus:
    def test_timestamps_columns_and_channel_candidates(self, folder, tmp_path):
        census = _run(folder, tmp_path / "out.json")["scada_census"][0]
        assert census["turbine_declared"] == "Synthetic 1"
        assert census["n_rows"] == 13
        ts = census["timestamps"]
        assert ts["modal_interval"] == "0 days 00:10:00"
        assert ts["duplicate_timestamp_count"] == 1
        assert ts["gap_count_above_modal_interval"] == 1
        assert census["dst"]["status"].startswith("not applicable")
        assert census["dst"]["declared_time_zone"] == "UTC"
        cols = census["per_column"]
        assert "SynthConst" in census["constant_columns"]
        # Literal "NaN" is honoured as missing.
        assert cols["Synth wind speed (m/s)"]["null_fraction"] > 0
        assert cols["Gear oil temperature (°C)"]["kind"] == "numeric"
        candidates = census["channel_candidates"]
        assert "Gear oil temperature (°C)" in candidates["thermal_target_candidates"]
        assert "Synth wind speed (m/s)" in candidates["upstream_predictor_candidates"]
        assert "mapping decision (M-07)" in candidates["note"]

    def test_coverage_note_flags_seasonal_boundary(self, folder, tmp_path):
        note = _run(folder, tmp_path / "out.json")["coverage_note"]
        assert note["months"] == 12
        assert "§14" in note["note"] and "Zenodo" in note["note"]
