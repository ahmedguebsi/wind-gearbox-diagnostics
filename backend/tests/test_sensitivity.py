"""M-27 tests: sensitivity suite over provisional-marked parameters."""

import pytest

from app.core.config import AppConfig, iter_provisional_parameters
from app.core.errors import ConfigError
from app.evaluation.sensitivity import (
    DEFAULT_GRIDS,
    STATUS_FLIPS,
    STATUS_NOT_APPLICABLE,
    STATUS_STABLE,
    override_parameter,
    run_sensitivity,
    verify_grid_coverage,
)


class TestGridCoverage:
    def test_default_grids_cover_every_provisional_parameter(self):
        """M-27 acceptance 2 (checklist test): a newly added provisional
        parameter without grid coverage fails here."""
        assert set(DEFAULT_GRIDS) == set(iter_provisional_parameters())
        verify_grid_coverage()

    def test_adr017_window_grid(self):
        assert DEFAULT_GRIDS["evaluation.event_match_window_days"] == (7, 14, 30)

    def test_spec_named_fault_pre_exclusion_grid(self):
        """PROJECT.md §27.3 names 15/30/60 explicitly."""
        assert DEFAULT_GRIDS["healthy_state.fault_pre_exclusion_days"] == (15, 30, 60)

    def test_missing_grid_fails(self):
        grids = {k: v for k, v in DEFAULT_GRIDS.items() if k != "detection.ewma_lambda"}
        with pytest.raises(ConfigError, match="lack"):
            verify_grid_coverage(grids)

    def test_non_provisional_parameter_in_grid_fails(self):
        grids = dict(DEFAULT_GRIDS)
        grids["model.seed"] = (1, 2)
        with pytest.raises(ConfigError, match="non-provisional"):
            verify_grid_coverage(grids)


class TestOverride:
    def test_override_returns_new_validated_config(self):
        base = AppConfig()
        changed = override_parameter(base, "detection.ewma_lambda", 0.3)
        assert changed.detection.ewma_lambda == 0.3
        assert base.detection.ewma_lambda == 0.2

    def test_unknown_parameter_rejected(self):
        with pytest.raises(ConfigError):
            override_parameter(AppConfig(), "detection.nonexistent", 1)
        with pytest.raises(ConfigError):
            override_parameter(AppConfig(), "nonexistent.section", 1)

    def test_invalid_value_rejected_by_validation(self):
        with pytest.raises(Exception):  # noqa: B017 — pydantic wraps into ConfigError-free error
            override_parameter(AppConfig(), "detection.ewma_lambda", 5.0)


class TestSweep:
    @staticmethod
    def _runner(config: AppConfig) -> dict:
        window = config.evaluation.event_match_window_days
        return {
            "detected": 1 if window >= 14 else 0,
            "lead_minutes": float(window) * 10.0,
        }

    @staticmethod
    def _conclusion(outcome: dict) -> str:
        return "matched" if outcome["detected"] else "missed"

    def test_sweep_covers_all_parameters_and_detects_flip(self):
        report = run_sensitivity(AppConfig(), self._runner, self._conclusion)
        assert {s.parameter for s in report.sweeps} == set(DEFAULT_GRIDS)
        assert report.flipping_parameters() == ("evaluation.event_match_window_days",)

    def test_tornado_orders_by_outcome_range(self):
        report = run_sensitivity(AppConfig(), self._runner, self._conclusion)
        tornado = report.tornado("lead_minutes")
        assert list(tornado.columns) == [
            "parameter",
            "range",
            "status",
            "inapplicable_reason",
        ]
        assert tornado.iloc[0]["parameter"] == "evaluation.event_match_window_days"
        assert tornado.iloc[0]["range"] == pytest.approx(230.0)
        assert tornado["range"].is_monotonic_decreasing

    def test_sweeps_are_deterministic(self):
        first = run_sensitivity(AppConfig(), self._runner, self._conclusion)
        second = run_sensitivity(AppConfig(), self._runner, self._conclusion)
        assert first.as_dict() == second.as_dict()

    def test_inapplicable_parameter_is_not_reported_as_stable(self):
        """ADR-040. Five of the thirteen Kelmarsh provisional parameters have
        no lever on the run (no fault or maintenance windows exist; step-change
        exclusion is off), so they produced identical outcomes and the suite
        labelled them STABLE — reading as robustness evidence for parameters
        that were merely switched off."""
        reason = "no fault windows are supplied for this dataset"
        report = run_sensitivity(
            AppConfig(),
            self._runner,
            self._conclusion,
            applicability={"healthy_state.fault_pre_exclusion_days": lambda _: reason},
        )
        sweep = next(
            s for s in report.sweeps if s.parameter == "healthy_state.fault_pre_exclusion_days"
        )
        assert sweep.status == STATUS_NOT_APPLICABLE
        assert sweep.applicable is False
        assert sweep.inapplicable_reason == reason
        assert report.inapplicable_parameters() == ("healthy_state.fault_pre_exclusion_days",)
        # An applicable parameter is untouched by the mechanism.
        other = next(
            s for s in report.sweeps if s.parameter == "evaluation.event_match_window_days"
        )
        assert other.status == STATUS_FLIPS

    def test_inapplicable_parameter_cannot_raise_a_false_flip(self):
        """A parameter with no lever must not be able to enter the
        conclusion-flip register, even if the runner is noisy."""
        flipping = {"healthy_state.minimum_active_power_kw": lambda _: "switched off"}
        report = run_sensitivity(
            AppConfig(),
            lambda c: {"detected": int(c.healthy_state.minimum_active_power_kw > 40), "x": 0.0},
            self._conclusion,
            applicability=flipping,
        )
        sweep = next(
            s for s in report.sweeps if s.parameter == "healthy_state.minimum_active_power_kw"
        )
        assert set(sweep.conclusions) == {"missed", "matched"}  # outcomes DID differ
        assert sweep.conclusion_flips is False  # but it has no lever, so no flip
        assert "healthy_state.minimum_active_power_kw" not in report.flipping_parameters()

    def test_parameter_applicable_at_any_swept_value_stays_applicable(self):
        """`exclude_step_changes` sweeps False->True: one value turns the
        machinery on, so the sweep as a whole is applicable."""
        report = run_sensitivity(
            AppConfig(),
            self._runner,
            self._conclusion,
            applicability={
                "healthy_state.exclude_step_changes": (
                    lambda c: None if c.healthy_state.exclude_step_changes else "off"
                )
            },
        )
        sweep = next(
            s for s in report.sweeps if s.parameter == "healthy_state.exclude_step_changes"
        )
        assert sweep.applicable is True
        assert sweep.status == STATUS_STABLE

    def test_flips_append_limitations_entries(self, tmp_path):
        """M-27 acceptance 3."""
        register = tmp_path / "LIMITATIONS.md"
        register.write_text("# register\n\n## LIM-004 — earlier\n", encoding="utf-8")
        report = run_sensitivity(AppConfig(), self._runner, self._conclusion)
        lim_ids = report.append_flips(register, source="test sweep")
        assert lim_ids == ["LIM-005"]
        text = register.read_text(encoding="utf-8")
        assert "Conclusion flips across the evaluation.event_match_window_days sweep" in text
        assert "7 -> missed" in text and "14 -> matched" in text
