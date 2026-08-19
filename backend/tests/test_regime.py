"""LIM-034 mitigation (a): operating-regime split of error and detection figures."""

import numpy as np
import pandas as pd
import pytest

from app.core.errors import ConfigError
from app.evaluation.regime import (
    MIN_SEPARATION_ROWS,
    REGIME_BOUNDARY_SOURCE,
    ExceedanceCensus,
    Regime,
    exceedance_census,
    label_regime,
    regime_slices,
    separation,
)


class TestLabelRegime:
    def test_split_is_at_the_floor_and_is_inclusive_above(self):
        power = pd.Series([49.9, 50.0, 50.1, 1000.0])
        labels = label_regime(power, 50.0)
        assert list(labels) == [
            Regime.OUT_OF_REGIME.value,
            Regime.IN_REGIME.value,
            Regime.IN_REGIME.value,
            Regime.IN_REGIME.value,
        ]

    def test_missing_power_is_out_of_regime(self):
        """The healthy-state builder excludes NaN power (``fillna(True)``), so a
        row whose regime cannot be established was never in the training
        population either. Calling it in-regime would widen the very support
        this split exists to delimit."""
        labels = label_regime(pd.Series([np.nan, 500.0]), 50.0)
        assert list(labels) == [Regime.OUT_OF_REGIME.value, Regime.IN_REGIME.value]

    def test_negative_power_is_out_of_regime(self):
        """Consuming turbines are the worst-behaved band in LIM-034."""
        assert label_regime(pd.Series([-30.0]), 50.0).iloc[0] == Regime.OUT_OF_REGIME.value

    @pytest.mark.parametrize("floor", [0.0, -1.0])
    def test_non_positive_floor_rejected(self, floor):
        with pytest.raises(ConfigError, match="floor must be positive"):
            label_regime(pd.Series([1.0]), floor)

    def test_index_is_preserved(self):
        power = pd.Series([10.0, 100.0], index=[7, 9])
        assert list(label_regime(power, 50.0).index) == [7, 9]

    def test_boundary_source_names_the_healthy_state_config(self):
        """A second, independently chosen threshold would measure something
        other than 'inside vs outside the training support'."""
        assert "minimum_active_power_kw" in REGIME_BOUNDARY_SOURCE


class TestRegimeSlices:
    @staticmethod
    def _case():
        actual = pd.Series([10.0, 10.0, 10.0, 10.0])
        predicted = pd.Series([10.0, 10.0, 40.0, 0.0])  # errors 0, 0, -30, +10
        regime = pd.Series([Regime.IN_REGIME.value] * 2 + [Regime.OUT_OF_REGIME.value] * 2)
        return actual, predicted, regime

    def test_shares_and_variance_shares_each_sum_to_one(self):
        slices = regime_slices(*self._case())
        assert sum(s.share for s in slices.values()) == pytest.approx(1.0)
        assert sum(s.variance_share for s in slices.values()) == pytest.approx(1.0)

    def test_variance_share_can_far_exceed_row_share(self):
        """The LIM-034 shape: a minority of rows carrying most of the error."""
        slices = regime_slices(*self._case())
        out = slices[Regime.OUT_OF_REGIME.value]
        assert out.share == pytest.approx(0.5)
        assert out.variance_share == pytest.approx(1.0)  # in-regime errors are exactly zero

    def test_beyond_10c_fraction_uses_strict_inequality(self):
        actual = pd.Series([0.0, 0.0])
        predicted = pd.Series([-10.0, -10.001])  # |error| = 10.0 then 10.001
        regime = pd.Series([Regime.IN_REGIME.value, Regime.IN_REGIME.value])
        slices = regime_slices(actual, predicted, regime)
        assert slices[Regime.IN_REGIME.value].beyond_10c_fraction == pytest.approx(0.5)

    def test_bias_follows_the_project_error_convention(self):
        """residual = actual - predicted, so under-prediction is POSITIVE bias."""
        actual = pd.Series([10.0, 10.0])
        predicted = pd.Series([8.0, 8.0])
        regime = pd.Series([Regime.IN_REGIME.value] * 2)
        slices = regime_slices(actual, predicted, regime)
        assert slices[Regime.IN_REGIME.value].metrics.bias == pytest.approx(2.0)

    def test_single_regime_input_yields_one_slice(self):
        actual, predicted, _ = self._case()
        regime = pd.Series([Regime.IN_REGIME.value] * 4)
        assert set(regime_slices(actual, predicted, regime)) == {Regime.IN_REGIME.value}

    def test_length_mismatch_rejected(self):
        with pytest.raises(ConfigError, match="equal length"):
            regime_slices(pd.Series([1.0, 2.0]), pd.Series([1.0]), pd.Series(["in_regime"]))

    def test_empty_input_rejected(self):
        empty = pd.Series([], dtype=float)
        with pytest.raises(ConfigError, match="empty series"):
            regime_slices(empty, empty, pd.Series([], dtype=object))

    def test_as_dict_carries_the_four_metrics_and_the_shares(self):
        payload = regime_slices(*self._case())[Regime.IN_REGIME.value].as_dict()
        assert {"rmse", "mae", "r2", "bias", "share", "variance_share", "n"} <= set(payload)


class TestSeparation:
    @staticmethod
    def _series(n_healthy: int, n_unhealthy: int, unhealthy_error: float):
        n = n_healthy + n_unhealthy
        actual = pd.Series(np.zeros(n))
        predicted = pd.Series(
            np.concatenate([np.zeros(n_healthy), np.full(n_unhealthy, -unhealthy_error)])
        )
        healthy = pd.Series([True] * n_healthy + [False] * n_unhealthy)
        return actual, predicted, healthy

    def test_delta_is_unhealthy_minus_healthy(self):
        result = separation(
            *self._series(MIN_SEPARATION_ROWS, MIN_SEPARATION_ROWS, 4.0), regime=Regime.IN_REGIME
        )
        assert result.rmse_healthy == pytest.approx(0.0)
        assert result.rmse_unhealthy == pytest.approx(4.0)
        assert result.delta == pytest.approx(4.0)

    def test_larger_delta_is_the_better_model(self):
        """Chesterman's dual criterion: small error healthy, LARGE error unhealthy."""
        weak = separation(
            *self._series(MIN_SEPARATION_ROWS, MIN_SEPARATION_ROWS, 1.0), regime=Regime.IN_REGIME
        )
        strong = separation(
            *self._series(MIN_SEPARATION_ROWS, MIN_SEPARATION_ROWS, 9.0), regime=Regime.IN_REGIME
        )
        assert strong.delta > weak.delta

    def test_small_side_is_flagged_not_silently_reported(self):
        result = separation(*self._series(10, 10, 4.0), regime=Regime.OUT_OF_REGIME)
        assert result.interpretable is False
        assert result.caveat is not None and "descriptively" in result.caveat

    def test_adequate_sample_carries_no_caveat(self):
        result = separation(
            *self._series(MIN_SEPARATION_ROWS, MIN_SEPARATION_ROWS, 4.0), regime=Regime.IN_REGIME
        )
        assert result.interpretable is True
        assert result.caveat is None

    @pytest.mark.parametrize("n_healthy,n_unhealthy", [(0, 5), (5, 0)])
    def test_one_sided_input_rejected(self, n_healthy, n_unhealthy):
        actual, predicted, healthy = self._series(max(n_healthy, 1), max(n_unhealthy, 1), 1.0)
        healthy = pd.Series([n_healthy > 0] * len(actual))
        with pytest.raises(ConfigError, match="both healthy and unhealthy"):
            separation(actual, predicted, healthy, regime=Regime.IN_REGIME)

    def test_length_mismatch_rejected(self):
        with pytest.raises(ConfigError, match="equal length"):
            separation(
                pd.Series([1.0, 2.0]),
                pd.Series([1.0]),
                pd.Series([True]),
                regime=Regime.IN_REGIME,
            )

    def test_as_dict_is_json_ready_and_names_its_regime(self):
        payload = separation(
            *self._series(MIN_SEPARATION_ROWS, MIN_SEPARATION_ROWS, 4.0), regime=Regime.IN_REGIME
        ).as_dict()
        assert payload["regime"] == "in_regime"
        assert payload["delta"] == pytest.approx(4.0)
        assert payload["caveat"] is None


class TestExceedanceCensus:
    def test_high_and_low_counted_separately(self):
        states = pd.Series([1, -1, -1, 0])
        regime = pd.Series([Regime.IN_REGIME.value] * 4)
        census = exceedance_census(states, regime)[Regime.IN_REGIME.value]
        assert (census.n_high, census.n_low, census.n_exceedances) == (1, 2, 3)
        assert census.exceedance_rate == pytest.approx(0.75)

    def test_direction_asymmetry_is_visible_per_regime(self):
        """The LIM-034 mechanism for LIM-026: the untrained regime emits
        predominantly NEGATIVE (cold-side) excursions."""
        states = pd.Series([1, 1, -1, -1, -1, -1])
        regime = pd.Series([Regime.IN_REGIME.value] * 2 + [Regime.OUT_OF_REGIME.value] * 4)
        census = exceedance_census(states, regime)
        assert census[Regime.IN_REGIME.value].n_low == 0
        assert census[Regime.OUT_OF_REGIME.value].n_low == 4
        assert census[Regime.OUT_OF_REGIME.value].n_high == 0

    def test_zero_states_produce_zero_rate(self):
        census = exceedance_census(pd.Series([0, 0]), pd.Series([Regime.IN_REGIME.value] * 2))
        assert census[Regime.IN_REGIME.value].exceedance_rate == 0.0

    def test_length_mismatch_rejected(self):
        with pytest.raises(ConfigError, match="equal length"):
            exceedance_census(pd.Series([1, 0]), pd.Series(["in_regime"]))

    def test_as_dict_is_json_ready(self):
        payload = ExceedanceCensus(
            regime=Regime.IN_REGIME,
            n_points=4,
            n_high=1,
            n_low=2,
            n_exceedances=3,
            exceedance_rate=0.75,
        ).as_dict()
        assert payload["regime"] == "in_regime"
        assert payload["n_exceedances"] == 3
