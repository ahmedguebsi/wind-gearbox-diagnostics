"""M-29/M-30/M-31 tests: tracking, artifact store, runner, reproduce.

Fixtures are SYNTHETIC TEST DATA — NOT VALID THESIS EVIDENCE — with no fault
labels (LOCKED-08); they exercise mechanics only.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import AppConfig
from app.core.errors import CausalSeparationError, ProvenanceError, SplitPolicyError
from app.data.guards import FeatureConfig
from app.data.mapping import load_mapping
from app.data.schema import (
    ACTIVE_POWER,
    AMBIENT_TEMPERATURE,
    GEARBOX_BEARING_TEMPERATURE,
    GEARBOX_OIL_TEMPERATURE,
    WIND_SPEED,
    default_schema,
)
from app.data.splitting import ExperimentFlags, SplitSpec, SplitStrategy
from app.experiments.__main__ import main as cli_main
from app.experiments.reproduce import ReproductionStatus, reproduce
from app.experiments.runner import PipelineInputs, run_experiment, run_pipeline
from app.experiments.store import ARTIFACT_SUBDIRS, ArtifactStore
from app.experiments.tracker import ExperimentRecord

MAPPING_YAML = """
schema_version: 1.2.0
dataset:
  timestamp_column: RawTime
  source_timezone: UTC
  turbine_column: RawUnit
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

SCHEMA = default_schema()


def _write_fixture_csv(path: Path, rows: int = 240) -> Path:
    """Synthetic 10-minute SCADA export, one turbine, deterministic values."""
    import pandas as pd

    stamps = pd.date_range("2020-01-01", periods=rows, freq="10min")
    lines = ["RawTime,RawUnit,RawWind,RawPower,RawAmbient,RawOilTemp,RawBearingTemp"]
    for i, stamp in enumerate(stamps):
        wind = 4.0 + (i % 40) * 0.2
        power = 200.0 + (i % 40) * 40.0
        ambient = 5.0 + (i % 24) * 0.5
        oil = 45.0 + (i % 40) * 0.3
        bearing = 55.0 + (i % 40) * 0.25
        lines.append(f"{stamp:%Y-%m-%d %H:%M:%S},T1,{wind},{power},{ambient},{oil},{bearing}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def mapping(tmp_path):
    path = tmp_path / "mapping.yaml"
    path.write_text(MAPPING_YAML, encoding="utf-8")
    return load_mapping(path, SCHEMA)


@pytest.fixture
def inputs(tmp_path, mapping):
    csv = _write_fixture_csv(tmp_path / "scada.csv")
    return PipelineInputs(
        schema=SCHEMA,
        mapping=mapping,
        source_paths=(csv,),
        feature=FeatureConfig(
            predictors=(WIND_SPEED, ACTIVE_POWER, AMBIENT_TEMPERATURE),
            targets=(GEARBOX_OIL_TEMPERATURE, GEARBOX_BEARING_TEMPERATURE),
        ),
        split_spec=SplitSpec(),
        cleaning_operations=("drop_missing_any_target",),
    )


@pytest.fixture
def store(tmp_path):
    return ArtifactStore(tmp_path / "artifacts")


class TestExperimentRecordContract:
    def test_missing_any_field_cannot_be_validated(self, inputs, store):
        """M-29 acceptance 1: every PROJECT.md §15 field is required."""
        experiment_id, _ = run_experiment(AppConfig(), inputs, store)
        payload = json.loads(
            (store.experiment_dir(experiment_id) / "metadata.json").read_text(encoding="utf-8")
        )
        for field_name in payload:
            broken = {k: v for k, v in payload.items() if k != field_name}
            with pytest.raises(ValidationError):
                ExperimentRecord.model_validate(broken)

    def test_unknown_field_rejected(self, inputs, store):
        experiment_id, _ = run_experiment(AppConfig(), inputs, store)
        payload = json.loads(
            (store.experiment_dir(experiment_id) / "metadata.json").read_text(encoding="utf-8")
        )
        payload["surprise"] = 1
        with pytest.raises(ValidationError):
            ExperimentRecord.model_validate(payload)


class TestArtifactStore:
    def test_ids_are_monotonic_per_day(self, store):
        first = store.new_experiment_id()
        store.create_layout(first)
        second = store.new_experiment_id()
        store.create_layout(second)
        assert first.endswith("-001")
        assert second.endswith("-002")
        assert first[:12] == second[:12]

    def test_layout_conformance(self, store):
        directory = store.create_layout(store.new_experiment_id())
        for sub in ARTIFACT_SUBDIRS:
            assert (directory / sub).is_dir()

    def test_persist_and_load_round_trip(self, inputs, store):
        experiment_id, result = run_experiment(AppConfig(), inputs, store)
        record = store.load_record(experiment_id)
        assert record.experiment_id == experiment_id
        assert store.load_metrics(experiment_id) == json.loads(json.dumps(result.metrics))
        assert experiment_id in store.registered_ids()

    def test_database_loss_resilience(self, inputs, store):
        """M-29 acceptance 2: artifacts alone rebuild the pointer rows."""
        experiment_id, _ = run_experiment(AppConfig(), inputs, store)
        store.db_path.unlink()
        rebuilt = ArtifactStore(store.root, db_path=store.db_path)
        assert rebuilt.registered_ids() == []
        assert rebuilt.reindex() == 1
        assert rebuilt.registered_ids() == [experiment_id]


class TestRunner:
    def test_artifacts_written(self, inputs, store):
        experiment_id, result = run_experiment(AppConfig(), inputs, store)
        directory = store.experiment_dir(experiment_id)
        for name in ("config.yaml", "metadata.json", "metrics.json"):
            assert (directory / name).is_file()
        for report in (
            "dataset_report",
            "cleaning_audit",
            "healthy_state_report",
            "split",
        ):
            assert (directory / "evaluation" / f"{report}.json").is_file()
        assert result.split.disjoint()
        assert result.healthy_report.accounting_holds()

    def test_guard_failure_leaves_no_partial_artifacts(self, inputs, store):
        """M-30 acceptance 2: fail-early, nothing persisted."""
        bad = PipelineInputs(
            schema=inputs.schema,
            mapping=inputs.mapping,
            source_paths=inputs.source_paths,
            feature=FeatureConfig(
                predictors=(WIND_SPEED, GEARBOX_OIL_TEMPERATURE),
                targets=(GEARBOX_OIL_TEMPERATURE, GEARBOX_BEARING_TEMPERATURE),
            ),
            split_spec=inputs.split_spec,
        )
        with pytest.raises(CausalSeparationError):
            run_experiment(AppConfig(), bad, store)
        assert store.list_experiments() == []

    def test_split_policy_guard_fires_before_any_file_is_read(self, inputs, store):
        """Guard 3 rejects a random thesis split without touching data: the
        source path here does not exist, so reaching ingestion would raise a
        different error."""
        bad = PipelineInputs(
            schema=inputs.schema,
            mapping=inputs.mapping,
            source_paths=(Path("does_not_exist.csv"),),
            feature=inputs.feature,
            split_spec=SplitSpec(strategy=SplitStrategy.RANDOM),
            flags=ExperimentFlags(thesis_official=True),
        )
        with pytest.raises(SplitPolicyError):
            run_pipeline(AppConfig(), bad)

    def test_metrics_are_deterministic(self, inputs):
        first = run_pipeline(AppConfig(), inputs)
        second = run_pipeline(AppConfig(), inputs)
        assert first.metrics == second.metrics


class TestReproduce:
    def test_exact_match_on_untouched_experiment(self, inputs, store):
        experiment_id, _ = run_experiment(AppConfig(), inputs, store)
        report = reproduce(experiment_id, store)
        assert report.status is ReproductionStatus.EXACT_MATCH
        assert report.diffs == []

    def test_mismatch_on_tampered_metrics(self, inputs, store):
        experiment_id, _ = run_experiment(AppConfig(), inputs, store)
        metrics_path = store.experiment_dir(experiment_id) / "metrics.json"
        tampered = json.loads(metrics_path.read_text(encoding="utf-8"))
        tampered["ingestion"]["rows"] += 1
        metrics_path.write_text(json.dumps(tampered), encoding="utf-8")
        report = reproduce(experiment_id, store)
        assert report.status is ReproductionStatus.MISMATCH
        assert any("ingestion.rows" in diff for diff in report.diffs)

    def test_provenance_error_on_tampered_source(self, inputs, store):
        experiment_id, _ = run_experiment(AppConfig(), inputs, store)
        source = inputs.source_paths[0]
        source.write_text(source.read_text(encoding="utf-8") + "tamper\n", encoding="utf-8")
        with pytest.raises(ProvenanceError):
            reproduce(experiment_id, store)

    def test_cli_exit_codes(self, inputs, store, capsys):
        experiment_id, _ = run_experiment(AppConfig(), inputs, store)
        assert cli_main(["reproduce", experiment_id, "--root", str(store.root)]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["status"] == "EXACT MATCH"
        metrics_path = store.experiment_dir(experiment_id) / "metrics.json"
        tampered = json.loads(metrics_path.read_text(encoding="utf-8"))
        tampered["split"]["train"] += 1
        metrics_path.write_text(json.dumps(tampered), encoding="utf-8")
        assert cli_main(["reproduce", experiment_id, "--root", str(store.root)]) == 1
