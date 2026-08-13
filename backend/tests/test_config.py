"""M-03 tests: typed configuration, resolution, hashing, provisional markers."""

from pathlib import Path

import pytest

from app.core.config import (
    AppConfig,
    NormalizationMethod,
    ThresholdStatsSource,
    config_hash,
    iter_provisional_parameters,
    load_config,
    resolved_dict,
    write_resolved,
)
from app.core.errors import ConfigError

EXPECTED_PROVISIONAL = sorted(
    [
        "detection.control_limit_sigma",
        "detection.ewma_lambda",
        "detection.persistence_min_samples",
        "evaluation.event_match_window_days",
        "healthy_state.exclude_step_changes",
        "healthy_state.fault_pre_exclusion_days",
        "healthy_state.maintenance_post_exclusion_days",
        "healthy_state.minimum_active_power_kw",
        "healthy_state.step_change_exclusion_days",
        "validation.step_change_min_magnitude_c",
        "validation.step_change_window_samples",
    ]
)


class TestDefaultsMaterialization:
    def test_no_file_yields_full_defaults(self):
        config = load_config()
        resolved = resolved_dict(config)
        assert resolved["detection"]["method"] == "ewma"  # LOCKED-02 primary
        assert resolved["detection"]["ewma_lambda"] == 0.2
        assert resolved["detection"]["control_limit_sigma"] == 3.0
        assert resolved["healthy_state"]["fault_pre_exclusion_days"] == 30
        assert resolved["healthy_state"]["maintenance_post_exclusion_days"] == 2
        assert resolved["healthy_state"]["minimum_active_power_kw"] == 50.0
        assert resolved["residual"]["normalization"] == "mad"
        assert resolved["residual"]["threshold_stats_source"] == "training"
        assert resolved["logging"]["level"] == "INFO"

    def test_step_change_exclusion_disabled_by_default(self):
        """ADR-018: the detector reports; exclusion is an explicit opt-in."""
        config = load_config()
        assert config.healthy_state.exclude_step_changes is False
        assert config.healthy_state.manual_exclusion_windows == ()

    def test_manual_exclusion_window_must_be_ordered(self):
        from app.core.config import ManualExclusionWindow

        with pytest.raises(ValueError, match="ends before it starts"):
            ManualExclusionWindow(
                label="bad",
                turbine="T1",
                start_utc="2021-02-06T19:00:00Z",  # type: ignore[arg-type]
                end_utc="2021-02-04T17:50:00Z",  # type: ignore[arg-type]
                citation="test",
            )

    def test_manual_exclusion_windows_load_from_yaml(self, tmp_path: Path):
        path = tmp_path / "manual.yaml"
        path.write_text(
            "healthy_state:\n"
            "  manual_exclusion_windows:\n"
            "    - label: K6-artefact-2021-02-05\n"
            "      turbine: Kelmarsh 6\n"
            "      start_utc: 2021-02-04T17:50:00Z\n"
            "      end_utc: 2021-02-06T19:00:00Z\n"
            "      citation: ADR-018\n",
            encoding="utf-8",
        )
        config = load_config(path)
        (window,) = config.healthy_state.manual_exclusion_windows
        assert window.turbine == "Kelmarsh 6"
        assert window.citation == "ADR-018"
        # The resolved form must round-trip (M-03 acceptance 1).
        resolved = tmp_path / "resolved.yaml"
        write_resolved(config, resolved)
        assert load_config(resolved) == config

    def test_partial_file_fills_remaining_defaults(self, tmp_path: Path):
        path = tmp_path / "partial.yaml"
        path.write_text("detection:\n  ewma_lambda: 0.1\n", encoding="utf-8")
        config = load_config(path)
        assert config.detection.ewma_lambda == 0.1
        assert config.detection.control_limit_sigma == 3.0  # default materialized
        assert config.healthy_state.fault_pre_exclusion_days == 30


class TestProvisionalMarkers:
    def test_every_spec_named_provisional_parameter_is_marked(self):
        """PROJECT.md §13 and §23 provisional values all carry the marker."""
        assert sorted(iter_provisional_parameters()) == EXPECTED_PROVISIONAL

    def test_markers_preserved_through_resolution(self):
        resolved = resolved_dict(load_config())
        assert resolved["provisional_parameters"] == EXPECTED_PROVISIONAL


class TestValidation:
    def test_unknown_key_rejected(self, tmp_path: Path):
        path = tmp_path / "bad.yaml"
        path.write_text("detection:\n  shap_enabled: true\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(path)

    def test_out_of_range_lambda_rejected(self, tmp_path: Path):
        path = tmp_path / "bad.yaml"
        path.write_text("detection:\n  ewma_lambda: 1.5\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(path)

    def test_non_mapping_root_rejected(self, tmp_path: Path):
        path = tmp_path / "bad.yaml"
        path.write_text("- just\n- a\n- list\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(path)

    def test_missing_file_rejected(self, tmp_path: Path):
        with pytest.raises(ConfigError):
            load_config(tmp_path / "does-not-exist.yaml")

    def test_detection_method_admits_only_ewma(self, tmp_path: Path):
        """LOCKED-02: comparators cannot be configured as the method today."""
        path = tmp_path / "bad.yaml"
        path.write_text("detection:\n  method: consecutive_exceedance\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(path)


class TestTuningConfig:
    def test_adr021_grid_defaults(self):
        tuning = load_config().model.tuning
        assert tuning.enabled
        assert len(tuning.candidates()) == 12  # 3 depths x 2 rates x 2 subsamples
        assert tuning.selection.value == "baseline_normalized_mean_rmse"
        assert tuning.n_estimators == 600
        assert tuning.early_stopping_rounds == 50
        assert tuning.colsample_bytree == 0.8
        # The grid is config, so every resolved config carries it (ADR-021).
        resolved = resolved_dict(load_config())
        assert resolved["model"]["tuning"]["max_depth_grid"] == [4, 6, 8]

    def test_empty_grid_axis_rejected(self, tmp_path: Path):
        path = tmp_path / "bad.yaml"
        path.write_text("model:\n  tuning:\n    max_depth_grid: []\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(path)

    def test_tuning_parameters_are_not_provisional(self):
        """ADR-021 is a closed ruling, not a provisional value: the tuning
        grid must not enter the M-27 sensitivity universe."""
        assert not any("tuning" in name for name in iter_provisional_parameters())


class TestAdrEnums:
    def test_threshold_stats_source_accepts_exactly_training_and_validation(self):
        assert {member.value for member in ThresholdStatsSource} == {"training", "validation"}

    def test_validation_branch_loadable(self, tmp_path: Path):
        path = tmp_path / "adr.yaml"
        path.write_text("residual:\n  threshold_stats_source: validation\n", encoding="utf-8")
        config = load_config(path)
        assert config.residual.threshold_stats_source is ThresholdStatsSource.VALIDATION

    def test_invalid_source_rejected(self, tmp_path: Path):
        path = tmp_path / "adr.yaml"
        path.write_text("residual:\n  threshold_stats_source: test\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(path)

    def test_all_four_normalization_families_selectable(self, tmp_path: Path):
        """PROJECT.md §22 families are all reachable by config."""
        for method in NormalizationMethod:
            path = tmp_path / f"{method.value}.yaml"
            path.write_text(f"residual:\n  normalization: {method.value}\n", encoding="utf-8")
            assert load_config(path).residual.normalization is method


class TestHashing:
    def test_hash_stable_across_key_order(self, tmp_path: Path):
        a = tmp_path / "a.yaml"
        b = tmp_path / "b.yaml"
        a.write_text(
            "detection:\n  ewma_lambda: 0.1\n  control_limit_sigma: 2.5\n"
            "logging:\n  level: DEBUG\n",
            encoding="utf-8",
        )
        b.write_text(
            "logging:\n  level: DEBUG\n"
            "detection:\n  control_limit_sigma: 2.5\n  ewma_lambda: 0.1\n",
            encoding="utf-8",
        )
        assert config_hash(load_config(a)) == config_hash(load_config(b))

    def test_hash_changes_with_content(self, tmp_path: Path):
        path = tmp_path / "c.yaml"
        path.write_text("detection:\n  ewma_lambda: 0.3\n", encoding="utf-8")
        assert config_hash(load_config(path)) != config_hash(load_config())


class TestResolvedRoundTrip:
    def test_resolved_config_is_standalone(self, tmp_path: Path):
        """M-03 acceptance 1: re-loading a resolved config reproduces an
        identical object and hash."""
        original = load_config()
        resolved_path = tmp_path / "config.yaml"
        write_resolved(original, resolved_path)
        reloaded = load_config(resolved_path)
        assert reloaded == original
        assert config_hash(reloaded) == config_hash(original)

    def test_frozen_config_cannot_be_mutated(self):
        config = load_config()
        with pytest.raises(Exception, match="frozen"):
            config.detection.ewma_lambda = 0.5  # type: ignore[misc]

    def test_defaults_type(self):
        assert isinstance(load_config(), AppConfig)
