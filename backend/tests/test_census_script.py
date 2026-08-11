"""Tests for scripts/dataset_census.py (Phase 0.5 evidence generator).

Fixtures are SYNTHETIC TEST DATA — NOT VALID THESIS EVIDENCE — and contain
no fault labels (LOCKED-08): event codes here exercise counting mechanics
only.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dataset_census.py"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def scada_csv(tmp_path: Path) -> Path:
    # 10-minute series with one duplicated timestamp and one skipped interval.
    rows = ["SynthTime,SynthWind,SynthConst,SynthOil"]
    minutes = [i * 10 for i in range(18) if i != 7]  # skip one -> gap
    for m in minutes:
        hh, mm = divmod(m, 60)
        rows.append(f"2016-06-01 {hh:02d}:{mm:02d},{5 + m / 100},5.0,{50 + m / 50}")
    rows.append("2016-06-01 00:10,5.1,5.0,50.2")  # duplicate timestamp
    path = tmp_path / "SYNTHETIC_scada.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def events_csv(tmp_path: Path) -> Path:
    rows = [
        "Code,Category",
        "1510,Stop",
        "1510,Stop",
        "20,Stop",
        "0,Informational",
        "0,Informational",
    ]
    path = tmp_path / "SYNTHETIC_events.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _run(args: list[str]) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


class TestCensusScript:
    def test_facts_reported_and_inputs_untouched(self, tmp_path, scada_csv, events_csv):
        before = (_sha(scada_csv), _sha(events_csv))
        out = tmp_path / "census.json"
        _run(
            [
                "--scada",
                str(scada_csv),
                "--timestamp-column",
                "SynthTime",
                "--assume-timezone",
                "Europe/London",
                "--events",
                str(events_csv),
                "--event-code-column",
                "Code",
                "--event-category-columns",
                "Category",
                "--output",
                str(out),
            ]
        )
        assert (_sha(scada_csv), _sha(events_csv)) == before  # read-only
        report = json.loads(out.read_text(encoding="utf-8"))
        assert "FACTS ONLY" in report["banner"]

        scada = report["scada_files"][0]
        assert scada["n_rows"] == 18
        ts = scada["timestamps"]
        assert ts["duplicate_timestamp_count"] == 1
        assert ts["gap_count_above_modal_interval"] == 1
        assert ts["modal_interval"] == "0 days 00:10:00"
        assert ts["utc_offset_markers_present_in_raw_strings"] is False
        assert ts["dst"]["assumed_timezone"] == "Europe/London"
        assert ts["dst"]["transitions_in_range"] == []  # June: none
        assert "SynthConst" in scada["constant_columns"]
        assert scada["per_column"]["SynthWind"]["null_fraction"] == 0.0

        events = report["event_files"][0]
        assert events["n_rows"] == 5
        assert events["row_counts_by_category"]["Category"]["Stop"] == 3
        assert events["event_code_counts"]["1510"] == 2

    def test_gearbox_count_unknown_without_designated_codes(self, tmp_path, events_csv):
        out = tmp_path / "census.json"
        _run(["--events", str(events_csv), "--event-code-column", "Code", "--output", str(out)])
        report = json.loads(out.read_text(encoding="utf-8"))
        assert "UNKNOWN" in report["confirmed_gearbox_failure_events"]["count"]

    def test_gearbox_count_with_author_designated_codes(self, tmp_path, events_csv):
        out = tmp_path / "census.json"
        _run(
            [
                "--events",
                str(events_csv),
                "--event-code-column",
                "Code",
                "--gearbox-event-codes",
                "1510",
                "--output",
                str(out),
            ]
        )
        report = json.loads(out.read_text(encoding="utf-8"))
        gearbox = report["confirmed_gearbox_failure_events"]
        assert gearbox["total_occurrences"] == 2
        assert gearbox["author_designated_codes"] == ["1510"]
        assert "D-04" in gearbox["note"]  # counting ≠ event definition
