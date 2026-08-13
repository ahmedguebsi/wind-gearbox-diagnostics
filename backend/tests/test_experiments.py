"""M-29/M-30/M-31 tests: tracking, artifact store, runner, reproduce.

Fixtures are SYNTHETIC TEST DATA — NOT VALID THESIS EVIDENCE — with no fault
labels (LOCKED-08); they exercise mechanics only.
"""

import json
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from app.core.config import AppConfig
from app.core.errors import CausalSeparationError, ConfigError, ProvenanceError, SplitPolicyError
from app.core.limitations import append_limitation, next_lim_id
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
from app.experiments.runner import (
    PipelineInputs,
    _record_inflation,
    run_experiment,
    run_pipeline,
)
from app.experiments.store import ARTIFACT_SUBDIRS, ArtifactStore
from app.experiments.tracker import ExperimentRecord
from app.residuals.ewma import InControlReport

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


def _config(**overrides) -> AppConfig:
    """Fast fixture config: small XGBoost, tuning off, so E2E stays quick.

    The ADR-021 tuning path has its own dedicated E2E test with a
    single-candidate grid.
    """
    payload = {
        "model": {
            "hyperparameters": {"n_estimators": 20, "max_depth": 3},
            "tuning": {"enabled": False},
        }
    }
    payload.update(overrides)
    return AppConfig.model_validate(payload)


def _write_fixture_csv(
    path: Path, rows: int = 240, low_power_tail: int = 0, noisy: bool = False
) -> Path:
    """Synthetic 10-minute SCADA export, one turbine, deterministic values.

    ``low_power_tail`` rows at the end carry 10 kW — below the healthy-state
    power floor — to exercise the unfiltered-monitoring semantics.
    ``noisy`` adds a deterministic non-linear perturbation so the linear
    baseline's RMSE is non-zero (the ADR-021 selection rule divides by it).
    """
    import pandas as pd

    stamps = pd.date_range("2020-01-01", periods=rows, freq="10min")
    lines = ["RawTime,RawUnit,RawWind,RawPower,RawAmbient,RawOilTemp,RawBearingTemp"]
    for i, stamp in enumerate(stamps):
        wind = 4.0 + (i % 40) * 0.2
        power = 10.0 if i >= rows - low_power_tail else 200.0 + (i % 40) * 40.0
        ambient = 5.0 + (i % 24) * 0.5
        wiggle = ((i * 37) % 17) * 0.08 if noisy else 0.0
        oil = 45.0 + (i % 40) * 0.3 + wiggle
        bearing = 55.0 + (i % 40) * 0.25 + wiggle
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
        experiment_id, _ = run_experiment(_config(), inputs, store)
        payload = json.loads(
            (store.experiment_dir(experiment_id) / "metadata.json").read_text(encoding="utf-8")
        )
        for field_name in payload:
            broken = {k: v for k, v in payload.items() if k != field_name}
            with pytest.raises(ValidationError):
                ExperimentRecord.model_validate(broken)

    def test_unknown_field_rejected(self, inputs, store):
        experiment_id, _ = run_experiment(_config(), inputs, store)
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
        experiment_id, result = run_experiment(_config(), inputs, store)
        record = store.load_record(experiment_id)
        assert record.experiment_id == experiment_id
        assert store.load_metrics(experiment_id) == json.loads(json.dumps(result.metrics))
        assert experiment_id in store.registered_ids()

    def test_database_loss_resilience(self, inputs, store):
        """M-29 acceptance 2: artifacts alone rebuild the pointer rows."""
        experiment_id, _ = run_experiment(_config(), inputs, store)
        store.db_path.unlink()
        rebuilt = ArtifactStore(store.root, db_path=store.db_path)
        assert rebuilt.registered_ids() == []
        assert rebuilt.reindex() == 1
        assert rebuilt.registered_ids() == [experiment_id]


class TestRunner:
    def test_artifacts_written(self, inputs, store):
        experiment_id, result = run_experiment(_config(), inputs, store)
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
            run_experiment(_config(), bad, store)
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
            run_pipeline(_config(), bad)

    def test_metrics_are_deterministic(self, inputs):
        first = run_pipeline(_config(), inputs)
        second = run_pipeline(_config(), inputs)
        assert first.metrics == second.metrics


class TestReproduce:
    def test_exact_match_on_untouched_experiment(self, inputs, store):
        experiment_id, _ = run_experiment(_config(), inputs, store)
        report = reproduce(experiment_id, store)
        assert report.status is ReproductionStatus.EXACT_MATCH
        assert report.diffs == []

    def test_mismatch_on_tampered_metrics(self, inputs, store):
        experiment_id, _ = run_experiment(_config(), inputs, store)
        metrics_path = store.experiment_dir(experiment_id) / "metrics.json"
        tampered = json.loads(metrics_path.read_text(encoding="utf-8"))
        tampered["ingestion"]["rows"] += 1
        metrics_path.write_text(json.dumps(tampered), encoding="utf-8")
        report = reproduce(experiment_id, store)
        assert report.status is ReproductionStatus.MISMATCH
        assert any("ingestion.rows" in diff for diff in report.diffs)

    def test_provenance_error_on_tampered_source(self, inputs, store):
        experiment_id, _ = run_experiment(_config(), inputs, store)
        source = inputs.source_paths[0]
        source.write_text(source.read_text(encoding="utf-8") + "tamper\n", encoding="utf-8")
        with pytest.raises(ProvenanceError):
            reproduce(experiment_id, store)

    def test_cli_exit_codes(self, inputs, store, capsys):
        experiment_id, _ = run_experiment(_config(), inputs, store)
        assert cli_main(["reproduce", experiment_id, "--root", str(store.root)]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["status"] == "EXACT MATCH"
        metrics_path = store.experiment_dir(experiment_id) / "metrics.json"
        tampered = json.loads(metrics_path.read_text(encoding="utf-8"))
        tampered["split"]["train"] += 1
        metrics_path.write_text(json.dumps(tampered), encoding="utf-8")
        assert cli_main(["reproduce", experiment_id, "--root", str(store.root)]) == 1


class TestModelStages:
    """M-30 full wiring: models, residuals, EWMA in the runner."""

    def test_model_and_detection_artifacts_written(self, inputs, store):
        experiment_id, _ = run_experiment(_config(), inputs, store)
        directory = store.experiment_dir(experiment_id)
        assert (directory / "model" / "thesis" / "meta.json").is_file()
        assert (directory / "model" / "baseline" / "meta.json").is_file()
        for key in ("thesis_training", "thesis_validation", "thesis_test", "baseline_test"):
            assert (directory / "predictions" / f"{key}.parquet").is_file()
        for partition in ("training", "validation", "test"):
            assert (directory / "residuals" / f"{partition}.parquet").is_file()
        assert (directory / "evaluation" / "in_control_report.json").is_file()
        assert (directory / "evaluation" / "normalizer_stats.json").is_file()
        metrics = store.load_metrics(experiment_id)
        for model_key in ("thesis", "baseline"):
            per_target = metrics["nbm"][model_key]["test"][GEARBOX_OIL_TEMPERATURE]
            assert set(per_target) == {"rmse", "mae", "r2", "bias"}
        assert metrics["detection"]["test_streams"] == 2

    def test_record_carries_model_metadata_and_guard4(self, inputs, store):
        experiment_id, _ = run_experiment(_config(), inputs, store)
        record = store.load_record(experiment_id)
        assert record.model.type == "xgboost_multi_target"
        assert record.model.model_kind == "thesis"
        assert record.model.tuning_configurations_evaluated == 0
        assert "G4" in record.guards.validated
        assert record.seeds["model"] == 42

    def test_tuned_run_records_grid_and_trials(self, tmp_path, mapping, store):
        """ADR-021 wiring: the config-declared grid tunes on the healthy
        validation block; the count and per-candidate trials land in
        metadata; the selection rule is baseline-normalized."""
        csv = _write_fixture_csv(tmp_path / "scada_noisy.csv", noisy=True)
        inputs = PipelineInputs(
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
        config = _config(
            model={
                "tuning": {
                    "max_depth_grid": [2, 3],
                    "learning_rate_grid": [0.1],
                    "subsample_grid": [1.0],
                    "n_estimators": 30,
                    "early_stopping_rounds": 5,
                }
            }
        )
        assert config.model.tuning.enabled  # default embodies the ruling
        experiment_id, _ = run_experiment(config, inputs, store)
        record = store.load_record(experiment_id)
        assert record.model.tuning_configurations_evaluated == 2
        assert len(record.model.tuning_trials) == 2
        for trial in record.model.tuning_trials:
            assert trial["seed"] == 42
            assert trial["score"] > 0
        assert record.model.hyperparameters["max_depth"] in {2, 3}
        assert record.model.hyperparameters["colsample_bytree"] == 0.8
        resolved = record.resolved_config
        assert resolved["model"]["tuning"]["selection"] == "baseline_normalized_mean_rmse"

    def test_tuning_without_baseline_rejected(self, inputs):
        """ADR-021: the selection rule needs the baseline's validation RMSE."""
        config = _config(model={"include_baseline": False, "tuning": {"n_estimators": 10}})
        with pytest.raises(ConfigError, match="include_baseline"):
            run_pipeline(config, inputs)

    def test_condition_binned_rejected_before_any_file_is_read(self, inputs):
        config = _config(residual={"normalization": "condition_binned"})
        bad = PipelineInputs(
            schema=inputs.schema,
            mapping=inputs.mapping,
            source_paths=(Path("does_not_exist.csv"),),
            feature=inputs.feature,
            split_spec=inputs.split_spec,
        )
        with pytest.raises(ConfigError, match="condition_binned"):
            run_pipeline(config, bad)

    def test_monitoring_period_is_unfiltered(self, tmp_path, mapping):
        """PROJECT.md §14 semantics: healthy-state construction applies to
        the train/validation periods only; anomalous or below-power-floor
        rows in the TEST period are the monitoring signal and stay in."""
        csv = _write_fixture_csv(tmp_path / "scada_tail.csv", low_power_tail=20)
        tail_inputs = PipelineInputs(
            schema=SCHEMA,
            mapping=mapping,
            source_paths=(csv,),
            feature=FeatureConfig(
                predictors=(WIND_SPEED, ACTIVE_POWER, AMBIENT_TEMPERATURE),
                targets=(GEARBOX_OIL_TEMPERATURE, GEARBOX_BEARING_TEMPERATURE),
            ),
            split_spec=SplitSpec(),
        )
        result = run_pipeline(_config(), tail_inputs)
        # 240 rows -> split 168/36/36; the 20 low-power rows all fall in test.
        assert result.metrics["split"]["test"] == 36
        assert result.metrics["split"]["test_is_unfiltered_monitoring"] is True
        assert result.healthy_report.total == 204  # train+validation only
        test_residuals = result.residuals["test"]
        assert len(test_residuals) == 36 * 2  # every monitoring row scored

    def test_reproduce_mismatch_on_tampered_prediction_file(self, inputs, store):
        """M-31 acceptance 1: predictions require EXACT match."""
        experiment_id, _ = run_experiment(_config(), inputs, store)
        path = store.experiment_dir(experiment_id) / "predictions" / "thesis_test.parquet"
        frame = pd.read_parquet(path)
        frame.iloc[0, 0] += 1.0
        frame.to_parquet(path)
        report = reproduce(experiment_id, store)
        assert report.status is ReproductionStatus.MISMATCH
        assert any("predictions.thesis_test" in diff for diff in report.diffs)


class TestLimitationsAppend:
    """M-20 acceptance 2: material in-control inflation reaches the register."""

    REGISTER = (
        "# LIMITATIONS.md — register\n\n"
        "## LIM-002 — existing entry\n\n"
        "Date discovered:    2026-08-11\n"
        "Description:        placeholder\n"
    )

    def _register_file(self, tmp_path):
        path = tmp_path / "LIMITATIONS.md"
        path.write_text(self.REGISTER, encoding="utf-8")
        return path

    def _report(self, ratio: float) -> InControlReport:
        return InControlReport(
            n_points=1000,
            n_exceedances=int(ratio * 0.0027 * 1000),
            empirical_rate=ratio * 0.0027,
            theoretical_rate=0.0027,
            inflation_ratio=ratio,
            material_inflation_threshold=2.0,
        )

    def test_next_lim_id_scans_existing_entries(self):
        assert next_lim_id(self.REGISTER) == "LIM-003"

    def test_append_follows_template(self, tmp_path):
        path = self._register_file(tmp_path)
        lim_id = append_limitation(
            path,
            title="test entry",
            description="something measured",
            affected_rqs="RQ2",
            mitigation_status="OPEN",
            source="test",
        )
        assert lim_id == "LIM-003"
        text = path.read_text(encoding="utf-8")
        assert "## LIM-003 — test entry" in text
        for field_label in (
            "Date discovered:",
            "Description:",
            "Affected RQ(s):",
            "Mitigation status:",
            "Source:",
        ):
            assert field_label in text

    def test_material_inflation_appends_entry(self, tmp_path):
        path = self._register_file(tmp_path)
        _record_inflation("EXP-20260812-001", self._report(ratio=10.0), path)
        text = path.read_text(encoding="utf-8")
        assert "EWMA in-control false-alarm inflation (EXP-20260812-001)" in text
        assert "R4" in text

    def test_non_material_inflation_does_not_append(self, tmp_path):
        path = self._register_file(tmp_path)
        _record_inflation("EXP-20260812-001", self._report(ratio=1.0), path)
        assert path.read_text(encoding="utf-8") == self.REGISTER

    def test_no_path_supplied_leaves_register_untouched(self):
        _record_inflation("EXP-20260812-001", self._report(ratio=10.0), None)
