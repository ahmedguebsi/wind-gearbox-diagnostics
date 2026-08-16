"""Tests for residual-level diagnostics (docs/METHODOLOGY_REVIEW.md §4).

Fixtures are SYNTHETIC TEST DATA — NOT VALID THESIS EVIDENCE — with no fault
labels (LOCKED-08). They verify mechanics and numerical correctness against
constructions whose answer is known in advance, never detection performance.
"""

import numpy as np
import pandas as pd
import pytest

from app.core.errors import ConfigError
from app.evaluation.residual_diagnostics import (
    MIN_PAIRED_OBSERVATIONS,
    cross_target_correlation,
    per_turbine_residual_stats,
)
from app.residuals.engine import (
    ACTUAL_COLUMN,
    NORMALIZED_RESIDUAL_COLUMN,
    PREDICTION_COLUMN,
    RAW_RESIDUAL_COLUMN,
    TARGET_COLUMN,
    TIMESTAMP_COLUMN,
    TURBINE_COLUMN,
    ResidualFrame,
)

OIL = "gearbox_oil_temperature"
BEARING = "gearbox_bearing_temperature"


def _frame(streams: dict[tuple[str, str], np.ndarray]) -> ResidualFrame:
    """Build a long-format ResidualFrame from {(turbine, target): residuals}."""
    parts = []
    for (turbine, target), values in streams.items():
        stamps = pd.date_range("2020-01-01", periods=len(values), freq="10min", tz="UTC")
        parts.append(
            pd.DataFrame(
                {
                    TIMESTAMP_COLUMN: stamps,
                    TURBINE_COLUMN: turbine,
                    TARGET_COLUMN: target,
                    ACTUAL_COLUMN: values,
                    PREDICTION_COLUMN: 0.0,
                    RAW_RESIDUAL_COLUMN: values,
                    NORMALIZED_RESIDUAL_COLUMN: np.nan,
                }
            )
        )
    return ResidualFrame(pd.concat(parts, ignore_index=True))


class TestCrossTargetCorrelation:
    def test_recovers_a_known_correlation(self):
        """Construct residuals with a known Pearson correlation and recover it."""
        rng = np.random.default_rng(0)
        n = 4000
        base = rng.standard_normal(n)
        independent = rng.standard_normal(n)
        rho = 0.8
        # y = rho*x + sqrt(1-rho^2)*z has population correlation rho with x.
        partner = rho * base + np.sqrt(1.0 - rho**2) * independent
        result = cross_target_correlation(
            _frame({("T1", OIL): base, ("T1", BEARING): partner}), partition="test"
        )
        pair = result.pairs[0]
        assert pair.n_paired == n
        assert pair.pearson == pytest.approx(rho, abs=0.03)

    def test_independent_residuals_correlate_near_zero(self):
        rng = np.random.default_rng(1)
        n = 4000
        result = cross_target_correlation(
            _frame(
                {
                    ("T1", OIL): rng.standard_normal(n),
                    ("T1", BEARING): rng.standard_normal(n),
                }
            ),
            partition="test",
        )
        assert result.pairs[0].pearson == pytest.approx(0.0, abs=0.05)

    def test_pearson_is_invariant_to_affine_normalization(self):
        """The documented claim: because M-19b normalizers are per-target
        affine maps, the raw-residual Pearson figure is also the normalized
        figure. A reviewer may check this."""
        rng = np.random.default_rng(2)
        n = 2000
        oil = rng.standard_normal(n)
        bearing = 0.6 * oil + 0.8 * rng.standard_normal(n)
        raw = cross_target_correlation(
            _frame({("T1", OIL): oil, ("T1", BEARING): bearing}), partition="p"
        )
        # Apply an arbitrary per-target affine map, as normalization does.
        scaled = cross_target_correlation(
            _frame({("T1", OIL): 3.0 * oil - 7.0, ("T1", BEARING): 0.25 * bearing + 100.0}),
            partition="p",
        )
        assert raw.pairs[0].pearson == pytest.approx(scaled.pairs[0].pearson, abs=1e-9)

    def test_per_turbine_estimates_are_reported_and_ranged(self):
        rng = np.random.default_rng(3)
        n = 1500
        t1 = rng.standard_normal(n)
        t2 = rng.standard_normal(n)
        streams = {
            ("T1", OIL): t1,
            ("T1", BEARING): 0.95 * t1 + 0.31 * rng.standard_normal(n),  # tightly coupled
            ("T2", OIL): t2,
            ("T2", BEARING): rng.standard_normal(n),  # independent
        }
        result = cross_target_correlation(_frame(streams), partition="test")
        per_turbine = result.pairs[0].per_turbine_pearson
        assert set(per_turbine) == {"T1", "T2"}
        assert per_turbine["T1"] > 0.85
        assert abs(per_turbine["T2"]) < 0.1
        assert result.pairs[0].per_turbine_range > 0.75

    def test_single_target_rejected(self):
        rng = np.random.default_rng(4)
        with pytest.raises(ConfigError, match="at least two targets"):
            cross_target_correlation(
                _frame({("T1", OIL): rng.standard_normal(100)}), partition="test"
            )

    def test_too_few_paired_observations_rejected(self):
        rng = np.random.default_rng(5)
        n = MIN_PAIRED_OBSERVATIONS - 1
        with pytest.raises(ConfigError, match="Too few aligned observations"):
            cross_target_correlation(
                _frame(
                    {
                        ("T1", OIL): rng.standard_normal(n),
                        ("T1", BEARING): rng.standard_normal(n),
                    }
                ),
                partition="test",
            )

    def test_duplicate_keys_raise_rather_than_averaging(self):
        """A duplicate (timestamp, turbine, target) is a data-integrity
        failure; averaging it would fabricate a residual."""
        rng = np.random.default_rng(6)
        frame = _frame(
            {
                ("T1", OIL): rng.standard_normal(50),
                ("T1", BEARING): rng.standard_normal(50),
            }
        ).data
        duplicated = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
        with pytest.raises(ConfigError, match="not unique"):
            cross_target_correlation(ResidualFrame(duplicated), partition="test")

    def test_serializes(self):
        rng = np.random.default_rng(7)
        n = 200
        result = cross_target_correlation(
            _frame(
                {
                    ("T1", OIL): rng.standard_normal(n),
                    ("T1", BEARING): rng.standard_normal(n),
                }
            ),
            partition="validation",
        )
        payload = result.as_dict()
        assert payload["partition"] == "validation"
        assert "pearson" in payload["pairs"][0]
        assert "invariant" in payload["note"]


class TestPerTurbineResidualStats:
    def test_recovers_known_offsets(self):
        """Two turbines with deliberately different residual centres."""
        rng = np.random.default_rng(10)
        n = 3000
        streams = {
            ("T1", OIL): rng.standard_normal(n) + 2.0,
            ("T2", OIL): rng.standard_normal(n) - 1.0,
        }
        result = per_turbine_residual_stats(_frame(streams), partition="training")
        centres = {s.turbine: s.median for s in result.per_stream}
        assert centres["T1"] == pytest.approx(2.0, abs=0.1)
        assert centres["T2"] == pytest.approx(-1.0, abs=0.1)

    def test_centre_spread_in_pooled_scales_flags_material_offset(self):
        """The decisive number: a 3-unit offset against a ~1-unit scale must
        report a spread of roughly 3 pooled scales, not a small number."""
        rng = np.random.default_rng(11)
        n = 3000
        streams = {
            ("T1", OIL): rng.standard_normal(n) + 1.5,
            ("T2", OIL): rng.standard_normal(n) - 1.5,
        }
        result = per_turbine_residual_stats(_frame(streams), partition="training")
        pooled = result.pooled[0]
        assert pooled.per_turbine_centre_spread == pytest.approx(3.0, abs=0.15)
        assert pooled.centre_spread_in_pooled_scales > 1.0

    def test_identical_turbines_report_near_zero_spread(self):
        rng = np.random.default_rng(12)
        n = 3000
        streams = {
            ("T1", OIL): rng.standard_normal(n),
            ("T2", OIL): rng.standard_normal(n),
        }
        result = per_turbine_residual_stats(_frame(streams), partition="training")
        assert result.pooled[0].centre_spread_in_pooled_scales < 0.15

    def test_covers_every_turbine_target_stream(self):
        rng = np.random.default_rng(13)
        n = 500
        streams = {
            ("T1", OIL): rng.standard_normal(n),
            ("T1", BEARING): rng.standard_normal(n),
            ("T2", OIL): rng.standard_normal(n),
            ("T2", BEARING): rng.standard_normal(n),
        }
        result = per_turbine_residual_stats(_frame(streams), partition="test")
        assert len(result.per_stream) == 4
        assert {p.target for p in result.pooled} == {OIL, BEARING}

    def test_serializes(self):
        rng = np.random.default_rng(14)
        result = per_turbine_residual_stats(
            _frame({("T1", OIL): rng.standard_normal(200)}), partition="training"
        )
        payload = result.as_dict()
        assert payload["partition"] == "training"
        assert "pooled" in payload and "per_stream" in payload
