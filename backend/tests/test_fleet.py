"""Fleet-relative residual tests (ADR-029 PROPOSED).

Fixtures are SYNTHETIC TEST DATA — NOT VALID THESIS EVIDENCE — with no fault
labels (LOCKED-08).

The two tests that carry the scientific claim are
``test_fleet_wide_excursion_is_removed`` and
``test_single_turbine_excursion_survives``: together they state exactly what
this transform is for and what it costs. The LIM-023 finding — a coordinated
excursion visible on all six turbines and both targets, concluded to be
environmental — is the first case; a genuine single-machine fault is the
second.
"""

import numpy as np
import pandas as pd
import pytest

from app.core.errors import ConfigError
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
from app.residuals.fleet import (
    _leave_one_out_median,
    fleet_relative_residuals,
)

OIL = "gearbox_oil_temperature"
BEARING = "gearbox_bearing_temperature"


def _frame(streams: dict[tuple[str, str], np.ndarray]) -> ResidualFrame:
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


def _residual_of(frame: ResidualFrame, turbine: str, target: str) -> np.ndarray:
    data = frame.data
    mask = (data[TURBINE_COLUMN] == turbine) & (data[TARGET_COLUMN] == target)
    return data[mask].sort_values(TIMESTAMP_COLUMN)[RAW_RESIDUAL_COLUMN].to_numpy(dtype=float)


class TestLeaveOneOutMedian:
    def test_excludes_the_column_it_is_applied_to(self):
        """The whole point: a turbine must never contribute to its own
        reference, or its excursion attenuates itself."""
        values = np.array([[100.0, 1.0, 2.0, 3.0]])
        out = _leave_one_out_median(values, min_peers=2)
        # Column 0's reference is median(1, 2, 3) = 2, not median of all four.
        assert out[0, 0] == pytest.approx(2.0)
        # Column 1's reference is median(100, 2, 3) = 3.
        assert out[0, 1] == pytest.approx(3.0)

    def test_nan_when_too_few_peers(self):
        values = np.array([[1.0, np.nan, np.nan]])
        out = _leave_one_out_median(values, min_peers=2)
        assert np.isnan(out[0, 0])

    def test_peers_below_threshold_are_not_used(self):
        values = np.array([[1.0, 5.0, np.nan]])
        strict = _leave_one_out_median(values, min_peers=2)
        lenient = _leave_one_out_median(values, min_peers=1)
        assert np.isnan(strict[0, 0])
        assert lenient[0, 0] == pytest.approx(5.0)


class TestFleetRelativeResiduals:
    @staticmethod
    def _fleet(n: int, seed: int, turbines: int = 6) -> dict[tuple[str, str], np.ndarray]:
        rng = np.random.default_rng(seed)
        return {(f"T{i + 1}", OIL): rng.standard_normal(n) * 0.2 for i in range(turbines)}

    def test_fleet_wide_excursion_is_removed(self):
        """The LIM-023 case. A common-mode excursion on every turbine is
        environmental, not evidence about any one machine, and must not
        survive the adjustment."""
        n = 200
        streams = self._fleet(n, seed=1)
        excursion = np.zeros(n)
        excursion[100:140] = 8.0  # every turbine rises together
        streams = {key: values + excursion for key, values in streams.items()}

        adjusted, _ = fleet_relative_residuals(_frame(streams))
        during = _residual_of(adjusted, "T1", OIL)[100:140]
        assert np.abs(during).max() < 1.0  # 8.0 common-mode signal is gone

    def test_single_turbine_excursion_survives(self):
        """The counterpart. A one-machine excursion is exactly what the
        system exists to detect and must pass through essentially intact."""
        n = 200
        streams = self._fleet(n, seed=2)
        excursion = np.zeros(n)
        excursion[100:140] = 8.0
        streams[("T1", OIL)] = streams[("T1", OIL)] + excursion  # T1 only

        adjusted, _ = fleet_relative_residuals(_frame(streams))
        during = _residual_of(adjusted, "T1", OIL)[100:140]
        assert during.min() > 7.0  # survives; peers unaffected

    def test_the_event_turbine_does_not_dilute_its_own_excursion(self):
        """Self-inclusion would pull the reference toward the excursion. With
        six turbines a naive median would lose a noticeable fraction of it;
        leave-one-out must lose essentially none."""
        n = 120
        streams = self._fleet(n, seed=3)
        streams[("T1", OIL)] = streams[("T1", OIL)] + 10.0

        adjusted, _ = fleet_relative_residuals(_frame(streams))
        recovered = float(np.median(_residual_of(adjusted, "T1", OIL)))
        assert recovered == pytest.approx(10.0, abs=0.3)

    def test_input_residuals_are_not_mutated(self):
        streams = self._fleet(100, seed=4)
        original = _frame(streams)
        before = _residual_of(original, "T1", OIL).copy()
        fleet_relative_residuals(original)
        np.testing.assert_allclose(_residual_of(original, "T1", OIL), before)

    def test_handles_multiple_targets_independently(self):
        n = 150
        rng = np.random.default_rng(5)
        streams: dict[tuple[str, str], np.ndarray] = {}
        for i in range(6):
            streams[(f"T{i + 1}", OIL)] = rng.standard_normal(n) * 0.2
            streams[(f"T{i + 1}", BEARING)] = rng.standard_normal(n) * 0.2
        streams[("T1", BEARING)] = streams[("T1", BEARING)] + 6.0  # bearing only

        adjusted, report = fleet_relative_residuals(_frame(streams))
        assert float(np.median(_residual_of(adjusted, "T1", BEARING))) > 5.0
        assert abs(float(np.median(_residual_of(adjusted, "T1", OIL)))) < 0.5
        assert set(report.per_target_median_abs_adjustment) == {OIL, BEARING}

    def test_reports_dropped_rows_rather_than_adjusting_silently(self):
        """Timestamps without enough peers are dropped and counted, not
        adjusted against a degenerate reference."""
        n = 50
        streams = {
            ("T1", OIL): np.ones(n),
            ("T2", OIL): np.ones(n),
            ("T3", OIL): np.ones(n),
        }
        frame = _frame(streams).data
        # Remove T2 and T3 at the first timestamp: T1 then has 0 peers.
        first = frame[TIMESTAMP_COLUMN].min()
        frame = frame[~((frame[TIMESTAMP_COLUMN] == first) & (frame[TURBINE_COLUMN] != "T1"))]

        adjusted, report = fleet_relative_residuals(ResidualFrame(frame), min_peers=2)
        assert report.rows_dropped_insufficient_peers == 1
        assert report.rows_after == len(adjusted)
        assert report.retention_pct < 100.0

    def test_too_few_turbines_rejected(self):
        streams = {("T1", OIL): np.ones(50), ("T2", OIL): np.ones(50)}
        with pytest.raises(ConfigError, match="Too few turbines"):
            fleet_relative_residuals(_frame(streams), min_peers=2)

    def test_invalid_min_peers_rejected(self):
        with pytest.raises(ConfigError, match="min_peers"):
            fleet_relative_residuals(_frame(self._fleet(50, seed=6)), min_peers=0)

    def test_report_serializes_with_the_validity_caveat(self):
        _, report = fleet_relative_residuals(_frame(self._fleet(100, seed=7)))
        payload = report.as_dict()
        assert payload["min_peers"] == 2
        assert "contemporaneous" in payload["note"]
        assert "invalid for farm-wide fault modes" in payload["note"]
