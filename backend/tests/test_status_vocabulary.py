"""Tests for scripts/status_vocabulary.py (complete multi-year inventory).

Fixtures are SYNTHETIC TEST DATA — NOT VALID THESIS EVIDENCE — with no fault
labels (LOCKED-08). The decisive property under test is that **selection
applies no code or keyword filter**: a code whose wording contains no
gearbox-related term must still appear in full.
"""

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "status_vocabulary.py"


def _comments(turbine: str, year: int) -> str:
    return "\n".join(
        [
            "# This file was exported by Greenbyte at 2022-01-27 23:29:26.",
            "#",
            f"# Turbine: {turbine}",
            "# Turbine type: Synthetic Model X",
            "# Time zone: UTC",
            f"# Time interval: {year}-01-01 00:00:00 - {year + 1}-01-01 00:00:00 (366 days)",
            "#",
            f"# {turbine} Sum production: 1000 kWh",
            "#",
        ]
    )


STATUS_HEADER = (
    "Timestamp start,Timestamp end,Duration,Status,Code,Message,Comment,"
    "Service contract category,IEC category"
)


def _write_year(root: Path, year: int, status_rows: list[str], scada_hours: int = 8) -> Path:
    folder = root / f"Kelmarsh_SCADA_{year}_000"
    folder.mkdir(parents=True)
    scada = [
        _comments("Synthetic 1", year),
        "# Date and time,Wind speed (m/s),Gear oil temperature (°C)",
    ]
    for i in range(scada_hours * 6):  # 10-minute cadence
        hh, mm = divmod(i * 10, 60)
        oil = "NaN" if i == 3 else f"{50 + i / 100}"  # one uncovered sample
        scada.append(f"{year}-01-01 {hh:02d}:{mm:02d}:00,7.5,{oil}")
    (folder / f"Turbine_Data_Synthetic_1_{year}.csv").write_text(
        "\n".join(scada) + "\n", encoding="utf-8"
    )
    (folder / f"Status_Synthetic_1_{year}.csv").write_text(
        "\n".join([_comments("Synthetic 1", year), STATUS_HEADER, *status_rows]) + "\n",
        encoding="utf-8",
    )
    return folder


@pytest.fixture
def folders(tmp_path: Path) -> list[Path]:
    data = tmp_path / "data"
    y1 = _write_year(
        data,
        2016,
        [
            # No gearbox-related word anywhere in this row.
            "2016-01-01 05:00:00,2016-01-01 12:00:00,07:00:00,Stop,4711,"
            "Anlage gestoppt,,Mechanical error (23),Forced outage",
            "2016-01-01 06:00:00,-,-,Informational,10,Wind < start wind,,,Full Performance",
        ],
    )
    y2 = _write_year(
        data,
        2017,
        [
            "2017-01-01 05:00:00,2017-01-01 05:30:00,00:30:00,Warning,1700,"
            "High temp. gear bearing 1,,Warnings (27),",
            "2017-01-01 07:00:00,2017-01-01 20:00:00,13:00:00,Warning,9999,"
            "Unmapped vendor state,,Warnings (27),Forced outage",
        ],
    )
    return [y1, y2]


def _run(folders: list[Path], stem: Path) -> tuple[dict, list[dict]]:
    args = []
    for folder in folders:
        args += ["--folder", str(folder)]
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args, "--output", str(stem)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(stem.with_suffix(".json").read_text(encoding="utf-8"))
    with stem.with_suffix(".csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return report, rows


class TestNoFiltering:
    def test_code_without_any_gearbox_term_is_fully_inventoried(self, folders, tmp_path):
        report, _ = _run(folders, tmp_path / "out")
        vocab = report["status_vocabulary"]
        codes = {c["code"]: c for c in vocab["codes_by_total_duration_desc"]}
        # 'Anlage gestoppt' contains no gearbox-related term at all.
        assert "4711" in codes
        entry = codes["4711"]
        assert entry["messages_verbatim"] == {"Anlage gestoppt": 1}
        assert entry["status_tiers"] == {"Stop": 1}
        assert entry["total_duration_hours"] == 7.0
        assert entry["years_present"] == ["Kelmarsh_SCADA_2016_000"]
        # And it is absent from the convenience index, while still inventoried.
        assert "4711" not in report["gearbox_term_index"]["codes_whose_message_contains_a_term"]
        assert report["gearbox_term_index"]["n_codes_total"] == vocab["n_distinct_codes"]
        assert "never a filter" in report["gearbox_term_index"]["note"]

    def test_every_code_present_and_sorted_by_duration(self, folders, tmp_path):
        report, _ = _run(folders, tmp_path / "out")
        vocab = report["status_vocabulary"]
        assert {c["code"] for c in vocab["codes_by_total_duration_desc"]} == {
            "4711",
            "10",
            "1700",
            "9999",
        }
        durations = [c["total_duration_hours"] for c in vocab["codes_by_total_duration_desc"]]
        assert durations == sorted(durations, reverse=True)


class TestRequestedSections:
    def test_taxonomies_reported_with_counts_and_durations(self, folders, tmp_path):
        vocab = _run(folders, tmp_path / "out")[0]["status_vocabulary"]
        iec = vocab["iec_category_taxonomy"]
        assert iec["Forced outage"]["count"] == 2
        assert iec["Forced outage"]["total_duration_hours"] == 20.0
        scc = vocab["service_contract_category_taxonomy"]
        assert scc["Warnings (27)"]["count"] == 2

    def test_long_stop_or_warning_events_with_full_row_context(self, folders, tmp_path):
        vocab = _run(folders, tmp_path / "out")[0]["status_vocabulary"]
        assert vocab["long_event_threshold_hours"] == 6.0
        events = vocab["long_stop_or_warning_events"]
        # 7h Stop and 13h Warning qualify; the 30-minute Warning does not.
        assert [e["row_verbatim"]["Code"] for e in events] == ["9999", "4711"]
        assert set(events[0]["row_verbatim"]) == {
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

    def test_year_presence_patterns_and_per_turbine_year(self, folders, tmp_path):
        vocab = _run(folders, tmp_path / "out")[0]["status_vocabulary"]
        patterns = vocab["code_year_presence_patterns"]
        assert "4711" in patterns["Kelmarsh_SCADA_2016_000"]
        assert "1700" in patterns["Kelmarsh_SCADA_2017_000"]
        rows = {(r["turbine"], r["year_folder"]): r for r in vocab["per_turbine_year"]}
        y2016 = rows[("Synthetic 1", "Kelmarsh_SCADA_2016_000")]
        assert y2016["counts_by_status"] == {"Stop": 1, "Informational": 1}
        assert y2016["duration_hours_by_status"]["Stop"] == 7.0

    def test_year_timestamp_spans_reported(self, folders, tmp_path):
        report = _run(folders, tmp_path / "out")[0]
        spans = report["status_vocabulary"]["status_row_timestamp_span_per_year_folder"]
        assert spans["Kelmarsh_SCADA_2016_000"]["first"] == "2016-01-01 05:00:00"
        scada = report["scada_coverage_per_year"]["Kelmarsh_SCADA_2016_000"]["Synthetic 1"]
        assert scada["first_timestamp"].startswith("2016-01-01T00:00")
        assert scada["thermal_candidate_columns"] == ["Gear oil temperature (°C)"]


class TestPrecedingCoverage:
    def test_preceding_run_stops_at_uncovered_sample(self, folders, tmp_path):
        report, rows = _run(folders, tmp_path / "out")
        by_code = {r["code"]: r for r in rows}
        # Sample index 3 (00:30) is NaN, so a 05:00 event has a run starting 00:40.
        assert float(by_code["4711"]["preceding_covered_scada_hours"]) == pytest.approx(
            4.333, abs=0.01
        )
        codes = {c["code"]: c for c in report["status_vocabulary"]["codes_by_total_duration_desc"]}
        stats = codes["4711"]["preceding_covered_scada_hours"]
        assert stats["n_occurrences_measured"] == 1
        assert stats["n_with_at_least_30_days"] == 0

    def test_csv_holds_every_status_row_untruncated(self, folders, tmp_path):
        report, rows = _run(folders, tmp_path / "out")
        assert len(rows) == report["status_vocabulary"]["total_status_rows"] == 4
        assert set(rows[0]) >= {
            "year_folder",
            "turbine",
            "code",
            "message",
            "status",
            "timestamp_start",
            "duration_hours",
            "preceding_covered_scada_hours",
        }


class TestReadOnly:
    def test_inputs_unchanged_and_verified(self, folders, tmp_path):
        report, _ = _run(folders, tmp_path / "out")
        assert report["read_only_verification"]["inputs_unchanged"] is True

    def test_output_inside_a_censused_folder_is_refused(self, folders):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--folder",
                str(folders[0]),
                "--output",
                str(folders[0] / "out"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert "must not be inside" in result.stderr
