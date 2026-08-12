"""M-21/M-22/M-23 tests: single-signal, comparators, coordinated, matched-FPR.

Fixtures are SYNTHETIC TEST DATA — NOT VALID THESIS EVIDENCE — with no fault
labels (LOCKED-08). Detection tests verify mechanics (thresholds fire on
constructed exceedances), never detection performance claims.
"""

import numpy as np
import pandas as pd
import pytest

from app.core.errors import ConfigError
from app.detection.comparators import (
    COMPARATOR_CONSECUTIVE_LABEL,
    COMPARATOR_ROLLING_COUNT_LABEL,
    COMPARATOR_ROLLING_MEAN_LABEL,
    ConsecutiveExceedanceDetector,
    RollingCountDetector,
    RollingMeanDetector,
)
from app.detection.coordinated import CoordinatedAnalyzer
from app.detection.matched_fpr import (
    ComparisonReport,
    CoordinatedPipeline,
    OperatingCurve,
    OperatingPoint,
    SingleSignalPipeline,
    compare_at,
    matched_multiplier,
    sweep,
)
from app.detection.single import SingleSignalDetector, states_at_multiplier
from app.residuals.engine import (
    NORMALIZED_RESIDUAL_COLUMN,
    RAW_RESIDUAL_COLUMN,
    ResidualFrame,
)
from app.residuals.ewma import (
    PRIMARY_EWMA_LABEL,
    ControlLimitSpec,
    DetectionSeries,
    EwmaSeries,
)

OIL = "oil"
BEARING = "bearing"


def _timestamps(n: int, start: str = "2020-01-01") -> pd.Series:
    return pd.Series(pd.date_range(start, periods=n, freq="10min", tz="UTC"))


def _ewma_series(
    turbine: str,
    target: str,
    values,
    limit: float = 1.0,
    multiplier: float = 3.0,
    start: str = "2020-01-01",
) -> EwmaSeries:
    n = len(values)
    return EwmaSeries(
        turbine=turbine,
        target=target,
        timestamps=_timestamps(n, start),
        values=pd.Series(np.asarray(values, dtype=float)),
        upper=pd.Series(np.full(n, limit)),
        lower=pd.Series(np.full(n, -limit)),
        lam=0.2,
        spec=ControlLimitSpec(sigma_multiplier=multiplier),
    )


def _detection(turbine: str, target: str, states, start: str = "2020-01-01") -> DetectionSeries:
    n = len(states)
    return DetectionSeries(
        turbine=turbine,
        target=target,
        timestamps=_timestamps(n, start),
        states=pd.Series(np.asarray(states, dtype=int)),
        method_label=PRIMARY_EWMA_LABEL,
    )


def _residual_frame(values, turbine: str = "T1", target: str = OIL) -> ResidualFrame:
    n = len(values)
    frame = pd.DataFrame(
        {
            "timestamp": _timestamps(n),
            "turbine_id": turbine,
            "target": target,
            "actual": np.asarray(values, dtype=float),
            "prediction": 0.0,
            RAW_RESIDUAL_COLUMN: np.asarray(values, dtype=float),
            NORMALIZED_RESIDUAL_COLUMN: np.asarray(values, dtype=float),
        }
    )
    return ResidualFrame(frame)


class TestSingleSignal:
    def test_states_at_own_limits(self):
        series = _ewma_series("T1", OIL, [0.0, 2.0, -2.0, 0.5])
        detection = SingleSignalDetector().detect(series)
        assert list(detection.states) == [0, 1, -1, 0]
        assert detection.method_label == PRIMARY_EWMA_LABEL

    def test_limits_rescale_with_multiplier(self):
        series = _ewma_series("T1", OIL, [1.5], limit=1.0, multiplier=3.0)
        assert list(states_at_multiplier(series, 3.0).states) == [1]
        assert list(states_at_multiplier(series, 6.0).states) == [0]

    def test_invalid_multiplier_rejected(self):
        series = _ewma_series("T1", OIL, [0.0, 0.0])
        with pytest.raises(ConfigError):
            states_at_multiplier(series, 0.0)


class TestComparators:
    def test_consecutive_exceedance_counting(self):
        rf = _residual_frame([2.0, 2.0, 0.0, 2.0, 2.0, 2.0, -2.0, -2.0])
        detector = ConsecutiveExceedanceDetector(threshold=1.0, n_consecutive=2)
        (detection,) = detector.detect(rf)
        assert list(detection.states) == [0, 1, 0, 0, 1, 1, 0, -1]
        assert detection.method_label == COMPARATOR_CONSECUTIVE_LABEL

    def test_rolling_count_window_boundaries(self):
        rf = _residual_frame([2.0, 0.0, 2.0, 0.0, 2.0, -2.0, -2.0, 0.0])
        detector = RollingCountDetector(threshold=1.0, window=3, min_count=2)
        (detection,) = detector.detect(rf)
        assert list(detection.states) == [0, 0, 1, 0, 1, 0, -1, -1]
        assert detection.method_label == COMPARATOR_ROLLING_COUNT_LABEL

    def test_rolling_mean_warm_up_and_direction(self):
        rf = _residual_frame([0.0, 3.0, 3.0, -3.0, -3.0])
        detector = RollingMeanDetector(threshold=1.0, window=2)
        (detection,) = detector.detect(rf)
        assert list(detection.states) == [0, 1, 1, 0, -1]
        assert detection.method_label == COMPARATOR_ROLLING_MEAN_LABEL

    def test_labels_are_distinct_and_non_primary(self):
        labels = {
            COMPARATOR_CONSECUTIVE_LABEL,
            COMPARATOR_ROLLING_COUNT_LABEL,
            COMPARATOR_ROLLING_MEAN_LABEL,
        }
        assert len(labels) == 3
        assert all(label.startswith("COMPARATOR_") for label in labels)
        assert PRIMARY_EWMA_LABEL not in labels

    def test_unnormalized_frame_rejected(self):
        frame = _residual_frame([1.0, 2.0]).data
        frame[NORMALIZED_RESIDUAL_COLUMN] = np.nan
        with pytest.raises(ConfigError):
            ConsecutiveExceedanceDetector().detect(ResidualFrame(frame))

    def test_invalid_parameters_rejected(self):
        with pytest.raises(ConfigError):
            ConsecutiveExceedanceDetector(threshold=-1.0)
        with pytest.raises(ConfigError):
            RollingCountDetector(window=2, min_count=3)
        with pytest.raises(ConfigError):
            RollingMeanDetector(window=0)


class TestCoordinated:
    def test_vector_assembly_preserves_both_representations(self):
        detections = [
            _detection("T1", OIL, [0, 1, 1]),
            _detection("T1", BEARING, [0, 0, 1]),
        ]
        ewma = [
            _ewma_series("T1", OIL, [0.1, 3.1, 3.2]),
            _ewma_series("T1", BEARING, [0.2, 0.3, 2.7]),
        ]
        states = CoordinatedAnalyzer().combine(detections, ewma)
        assert len(states) == 3
        last = states[-1]
        assert last.vector == {BEARING: 1, OIL: 1}
        assert last.continuous == {BEARING: 2.7, OIL: 3.2}
        payload = last.as_dict()
        assert "vector" in payload and "continuous" in payload

    def test_time_and_turbine_ordering_stable(self):
        detections = [
            _detection("T2", OIL, [0, 0]),
            _detection("T1", OIL, [1, 0]),
        ]
        ewma = [
            _ewma_series("T2", OIL, [0.0, 0.0]),
            _ewma_series("T1", OIL, [3.0, 0.0]),
        ]
        states = CoordinatedAnalyzer().combine(detections, ewma)
        assert [s.turbine for s in states] == ["T1", "T1", "T2", "T2"]
        assert states[0].timestamp_utc < states[1].timestamp_utc

    def test_missing_target_is_explicit_gap_never_silent_zero(self):
        detections = [
            _detection("T1", OIL, [0, 1, 0]),
            _detection("T1", BEARING, [1, 1], start="2020-01-01 00:10:00"),
        ]
        ewma = [
            _ewma_series("T1", OIL, [0.0, 3.0, 0.0]),
            _ewma_series("T1", BEARING, [2.9, 2.8], start="2020-01-01 00:10:00"),
        ]
        states = CoordinatedAnalyzer().combine(detections, ewma)
        first = states[0]
        assert first.vector[BEARING] is None
        assert first.continuous[BEARING] is None
        assert first.vector[OIL] == 0

    def test_misaligned_streams_rejected(self):
        detections = [_detection("T1", OIL, [0, 1])]
        ewma = [_ewma_series("T1", OIL, [0.0, 3.0, 0.0])]
        with pytest.raises(ConfigError):
            CoordinatedAnalyzer().combine(detections, ewma)

    def test_missing_ewma_stream_rejected(self):
        with pytest.raises(ConfigError):
            CoordinatedAnalyzer().combine([_detection("T1", OIL, [0])], [])


class TestMatchedFpr:
    def _noise_series(self, target: str, seed: int, n: int = 2000) -> EwmaSeries:
        rng = np.random.default_rng(seed)
        return _ewma_series("T1", target, rng.standard_normal(n) * 0.5, limit=1.0)

    def test_sweep_monotonic_alarm_fraction_and_tail_event_rate(self):
        """Alarm-point fraction is structurally monotone at every multiplier;
        the event rate is monotone in the operating tail (low alarm
        fractions). At very loose limits alarm runs merge, so the event rate
        is deliberately NOT asserted monotone there — the module documents
        and handles that."""
        pipeline = SingleSignalPipeline("single", [self._noise_series(OIL, 1)], OIL)
        wide = sweep(pipeline, [0.5, 1.0, 1.5, 2.0, 3.0, 4.0])
        fractions = [p.alarm_fraction for p in wide.points]
        assert fractions == sorted(fractions, reverse=True)
        tail = sweep(pipeline, [1.5, 2.0, 3.0, 4.0])
        rates = [p.false_alarms_per_turbine_year for p in tail.points]
        assert rates == sorted(rates, reverse=True)

    def test_fairness_two_identical_pipelines_report_no_difference(self):
        """PROJECT.md §25 symmetry sanity check (M-23 test list)."""
        series = [self._noise_series(OIL, 2)]
        grid = [0.5, 1.0, 2.0, 3.0]
        curve_a = sweep(SingleSignalPipeline("a", series, OIL), grid)
        curve_b = sweep(SingleSignalPipeline("b", series, OIL), grid)
        assert curve_a.points == curve_b.points
        report = compare_at({"a": curve_a, "b": curve_b}, fpr_targets=[10.0, 50.0])
        by_target: dict[float, set[float | None]] = {}
        for matched in report.matched:
            by_target.setdefault(matched.fpr_target, set()).add(matched.multiplier)
        for multipliers in by_target.values():
            assert len(multipliers) == 1

    def test_coordinated_alarms_no_more_than_single_at_same_multiplier(self):
        oil = self._noise_series(OIL, 3)
        bearing = self._noise_series(BEARING, 4)
        grid = [0.5, 1.0, 2.0]
        single_curve = sweep(SingleSignalPipeline("single", [oil], OIL), grid)
        coordinated_curve = sweep(CoordinatedPipeline("coord", [oil, bearing]), grid)
        for single_point, coordinated_point in zip(
            single_curve.points, coordinated_curve.points, strict=True
        ):
            assert (
                coordinated_point.false_alarms_per_turbine_year
                <= single_point.false_alarms_per_turbine_year
            )

    def test_coordinated_fires_on_same_direction_only(self):
        oil = _ewma_series("T1", OIL, [2.0, 2.0, 0.0], limit=1.0)
        bearing = _ewma_series("T1", BEARING, [2.0, -2.0, 0.0], limit=1.0)
        pipeline = CoordinatedPipeline("coord", [oil, bearing])
        flags = pipeline.alarm_flags(3.0)["T1"]
        assert list(flags) == [True, False, False]

    def test_matched_multiplier_interpolation(self):
        curve = OperatingCurve(
            pipeline="p",
            points=(
                OperatingPoint(1.0, 10.0, 0.1, 10, 100),
                OperatingPoint(2.0, 6.0, 0.06, 6, 100),
                OperatingPoint(3.0, 2.0, 0.02, 2, 100),
            ),
        )
        assert matched_multiplier(curve, 6.0) == pytest.approx(2.0)
        assert matched_multiplier(curve, 4.0) == pytest.approx(2.5)
        assert matched_multiplier(curve, 12.0) is None
        assert matched_multiplier(curve, 1.0) is None

    def test_unreachable_target_marked_not_silently_clamped(self):
        curve = OperatingCurve(
            pipeline="p",
            points=(OperatingPoint(1.0, 5.0, 0.05, 5, 100),),
        )
        report = compare_at({"p": curve}, fpr_targets=[100.0])
        assert report.matched[0].reachable is False
        assert report.matched[0].multiplier is None

    def test_full_curves_always_embedded_in_report(self):
        """M-23 acceptance 2: never just the matched points."""
        series = [self._noise_series(OIL, 5)]
        curve = sweep(SingleSignalPipeline("single", series, OIL), [1.0, 2.0])
        report = compare_at({"single": curve}, fpr_targets=[1.0])
        assert isinstance(report, ComparisonReport)
        assert report.curves["single"] == curve
        assert "curves" in report.as_dict()

    def test_curve_serialization_round_trip(self):
        series = [self._noise_series(OIL, 6)]
        curve = sweep(SingleSignalPipeline("single", series, OIL), [1.0, 2.0, 3.0])
        assert OperatingCurve.from_dict(curve.as_dict()) == curve

    def test_pipeline_construction_validation(self):
        oil = self._noise_series(OIL, 7)
        with pytest.raises(ConfigError):
            SingleSignalPipeline("s", [oil], BEARING)
        with pytest.raises(ConfigError):
            CoordinatedPipeline("c", [])
        with pytest.raises(ConfigError):
            CoordinatedPipeline("c", [oil], min_coordinated=2)

    def test_empty_grid_rejected(self):
        pipeline = SingleSignalPipeline("s", [self._noise_series(OIL, 8)], OIL)
        with pytest.raises(ConfigError):
            sweep(pipeline, [])
