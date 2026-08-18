"""M-19a/M-19b/M-20 tests: residual engine, normalizers + Guard 4, EWMA.

Fixtures are SYNTHETIC TEST DATA — NOT VALID THESIS EVIDENCE — with no fault
labels (LOCKED-08). Detection tests verify mechanics (thresholds fire on
constructed exceedances), never detection performance claims.
"""

import dataclasses
import math

import numpy as np
import pandas as pd
import pytest

from app.core.config import NormalizationMethod, ThresholdStatsSource
from app.core.errors import ConfigError, ThresholdProvenanceError
from app.data.schema import (
    GEARBOX_BEARING_TEMPERATURE,
    GEARBOX_OIL_TEMPERATURE,
    default_schema,
)
from app.residuals.engine import (
    NORMALIZED_RESIDUAL_COLUMN,
    RAW_RESIDUAL_COLUMN,
    ResidualFrame,
    compute_residuals,
)
from app.residuals.ewma import (
    PRIMARY_EWMA_LABEL,
    ControlLimitFormulation,
    ControlLimitSpec,
    DetectionSeries,
    EwmaDetector,
    GapHandling,
    ewma_recursion,
)
from app.residuals.normalization import (
    MAD_SIGMA_CONSISTENCY,
    ConditionBinnedNormalizer,
    MadNormalizer,
    PartitionRef,
    PercentileNormalizer,
    SigmaNormalizer,
    make_normalizer,
    partition_for,
)

SCHEMA = default_schema()
OIL = GEARBOX_OIL_TEMPERATURE
BEARING = GEARBOX_BEARING_TEMPERATURE


def _residual_frame(
    raw_by_target: dict[str, list[float]],
    condition: list[float] | None = None,
    turbine: str = "T1",
) -> ResidualFrame:
    rows = []
    for target, values in raw_by_target.items():
        for i, value in enumerate(values):
            row = {
                "timestamp": pd.Timestamp("2020-01-01", tz="UTC") + pd.Timedelta(minutes=10 * i),
                "turbine_id": turbine,
                "target": target,
                "actual": value,
                "prediction": 0.0,
                RAW_RESIDUAL_COLUMN: value,
                NORMALIZED_RESIDUAL_COLUMN: np.nan,
            }
            if condition is not None:
                row["condition"] = condition[i]
            rows.append(row)
    return ResidualFrame(pd.DataFrame(rows))


def _normalized_frame(values_by_target: dict[str, np.ndarray]) -> ResidualFrame:
    rf = _residual_frame({t: list(v) for t, v in values_by_target.items()})
    stacked = np.concatenate(
        [np.asarray(values_by_target[t], dtype=float) for t in sorted(values_by_target)]
    )
    return rf.with_normalized(pd.Series(stacked))


class TestResidualEngine:
    def test_identity_arithmetic_and_alignment(self):
        frame = pd.DataFrame(
            {
                "timestamp": pd.date_range("2020-01-01", periods=3, freq="10min", tz="UTC"),
                "turbine_id": ["T1", "T1", "T1"],
                OIL: [50.0, 51.0, 52.0],
                BEARING: [60.0, 61.0, 62.0],
            }
        )
        predictions = pd.DataFrame(
            {OIL: [49.0, 51.5, 50.0], BEARING: [58.0, 61.0, 63.0]}, index=frame.index
        )
        rf = compute_residuals(frame, predictions, SCHEMA, (OIL, BEARING))
        data = rf.data
        oil_rows = data[data["target"] == OIL]
        assert list(oil_rows[RAW_RESIDUAL_COLUMN]) == [1.0, -0.5, 2.0]
        assert data[NORMALIZED_RESIDUAL_COLUMN].isna().all()
        assert (data["actual"] - data["prediction"]).equals(data[RAW_RESIDUAL_COLUMN])

    def test_misaligned_predictions_rejected(self):
        frame = pd.DataFrame(
            {
                "timestamp": pd.date_range("2020-01-01", periods=3, freq="10min", tz="UTC"),
                "turbine_id": ["T1"] * 3,
                OIL: [50.0, 51.0, 52.0],
                BEARING: [60.0, 61.0, 62.0],
            }
        )
        predictions = pd.DataFrame({OIL: [1.0], BEARING: [1.0]})
        with pytest.raises(ConfigError):
            compute_residuals(frame, predictions, SCHEMA, (OIL, BEARING))

    def test_raw_residuals_are_write_once(self):
        """M-19a acceptance 1: no downstream module can overwrite raw."""
        rf = _residual_frame({OIL: [1.0, 2.0, 3.0]})
        leaked = rf.data
        leaked[RAW_RESIDUAL_COLUMN] = 999.0
        assert list(rf.data[RAW_RESIDUAL_COLUMN]) == [1.0, 2.0, 3.0]
        with pytest.raises(dataclasses.FrozenInstanceError):
            rf._frame = leaked  # type: ignore[misc]

    def test_with_normalized_preserves_raw_and_fills_normalized(self):
        rf = _residual_frame({OIL: [1.0, 2.0, 3.0]})
        normalized = rf.with_normalized(pd.Series([0.1, 0.2, 0.3]))
        assert list(normalized.data[NORMALIZED_RESIDUAL_COLUMN]) == [0.1, 0.2, 0.3]
        assert list(normalized.data[RAW_RESIDUAL_COLUMN]) == [1.0, 2.0, 3.0]
        assert rf.data[NORMALIZED_RESIDUAL_COLUMN].isna().all()

    def test_length_mismatch_rejected(self):
        rf = _residual_frame({OIL: [1.0, 2.0]})
        with pytest.raises(ConfigError):
            rf.with_normalized(pd.Series([1.0]))


class TestGuard4:
    @pytest.mark.parametrize("source", [PartitionRef.TEST, PartitionRef.FAULT])
    def test_non_healthy_statistics_source_rejected(self, source):
        rf = _residual_frame({OIL: [1.0, 2.0, 3.0]})
        with pytest.raises(ThresholdProvenanceError, match="Guard 4"):
            MadNormalizer().fit(rf, source)

    def test_ewma_limits_also_guarded(self):
        rf = _normalized_frame({OIL: np.array([0.1, -0.2, 0.3])})
        detector = EwmaDetector(0.2, ControlLimitSpec())
        with pytest.raises(ThresholdProvenanceError, match="Guard 4"):
            detector.fit_control_limits(rf, PartitionRef.TEST)

    def test_both_adr001_branches_recorded_distinguishably(self):
        rf = _residual_frame({OIL: [1.0, 2.0, 3.0, 4.0]})
        for config_source, expected in [
            (ThresholdStatsSource.TRAINING, "healthy_training"),
            (ThresholdStatsSource.VALIDATION, "healthy_validation"),
        ]:
            normalizer = MadNormalizer()
            normalizer.fit(rf, partition_for(config_source))
            assert normalizer.fitted_stats()["source"] == expected

    def test_source_unavailable_when_unfitted(self):
        with pytest.raises(ConfigError):
            _ = MadNormalizer().source


class TestNormalizers:
    def test_sigma_reference(self):
        rf = _residual_frame({OIL: [1.0, 2.0, 3.0, 4.0, 5.0]})
        normalizer = SigmaNormalizer()
        normalizer.fit(rf, PartitionRef.HEALTHY_TRAINING)
        out = normalizer.transform(rf).data[NORMALIZED_RESIDUAL_COLUMN]
        assert out.iloc[-1] == pytest.approx(2.0 / math.sqrt(2.5))

    def test_mad_reference(self):
        rf = _residual_frame({OIL: [1.0, 2.0, 3.0, 4.0, 100.0]})
        normalizer = MadNormalizer()
        normalizer.fit(rf, PartitionRef.HEALTHY_TRAINING)
        out = normalizer.transform(rf).data[NORMALIZED_RESIDUAL_COLUMN]
        assert out.iloc[3] == pytest.approx(1.0 / MAD_SIGMA_CONSISTENCY)

    def test_percentile_reference(self):
        values = [float(v) for v in range(101)]
        rf = _residual_frame({OIL: values})
        normalizer = PercentileNormalizer()
        normalizer.fit(rf, PartitionRef.HEALTHY_TRAINING)
        out = normalizer.transform(rf).data[NORMALIZED_RESIDUAL_COLUMN]
        assert out.iloc[100] == pytest.approx((100.0 - 50.0) / (50.0 / 1.349))

    def test_condition_binned_bin_membership_and_reference(self):
        low_raw = [1.0, 1.2, 0.8, 1.5, 0.5, 1.1]
        high_raw = [8.0, 8.4, 7.6, 9.0, 7.0, 8.2]
        condition = [0.0] * 6 + [10.0] * 6
        rf = _residual_frame({OIL: low_raw + high_raw}, condition=condition)
        normalizer = ConditionBinnedNormalizer("condition", n_bins=2)
        normalizer.fit(rf, PartitionRef.HEALTHY_TRAINING)
        out = normalizer.transform(rf).data
        low_bin = out[out["condition"] == 0.0]
        median = float(np.median(low_raw))
        mad = float(np.median(np.abs(np.array(low_raw) - median)))
        expected = (low_raw[0] - median) / (MAD_SIGMA_CONSISTENCY * mad)
        assert low_bin[NORMALIZED_RESIDUAL_COLUMN].iloc[0] == pytest.approx(expected)
        stats = normalizer.fitted_stats()
        assert len(stats["per_target_bin"]) == 2
        assert stats["source"] == "healthy_training"

    def test_per_target_statistics_are_separate(self):
        rf = _residual_frame({OIL: [1.0, 2.0, 3.0], BEARING: [10.0, 20.0, 30.0]})
        normalizer = MadNormalizer()
        normalizer.fit(rf, PartitionRef.HEALTHY_TRAINING)
        stats = normalizer.fitted_stats()["per_target"]
        assert stats[OIL]["center"] == pytest.approx(2.0)
        assert stats[BEARING]["center"] == pytest.approx(20.0)

    def test_unfitted_transform_rejected(self):
        rf = _residual_frame({OIL: [1.0, 2.0]})
        with pytest.raises(ConfigError):
            SigmaNormalizer().transform(rf)

    def test_factory_resolves_all_four_families(self):
        for method in NormalizationMethod:
            kwargs = {"condition_column": "c"} if method.value == "condition_binned" else {}
            assert make_normalizer(method, **kwargs) is not None

    def test_factory_condition_binned_requires_column(self):
        with pytest.raises(ConfigError):
            make_normalizer(NormalizationMethod.CONDITION_BINNED)


class TestEwma:
    def test_recursion_against_hand_computed_reference(self):
        values = np.array([1.0, 0.0, 2.0])
        assert ewma_recursion(values, 0.5) == pytest.approx([0.5, 0.25, 1.125])

    def test_steady_state_limits_reference(self):
        rng = np.random.default_rng(1)
        healthy = _normalized_frame({OIL: rng.standard_normal(500)})
        detector = EwmaDetector(0.5, ControlLimitSpec(sigma_multiplier=3.0))
        detector.fit_control_limits(healthy, PartitionRef.HEALTHY_VALIDATION)
        series, _ = detector.detect(healthy)
        sigma = np.std(healthy.data[NORMALIZED_RESIDUAL_COLUMN].to_numpy(), ddof=1)
        expected = 3.0 * sigma * math.sqrt(0.5 / 1.5)
        assert series[0].upper.iloc[0] == pytest.approx(expected)
        assert series[0].lower.iloc[0] == pytest.approx(-expected)

    def test_time_varying_limits_reference(self):
        healthy = _normalized_frame({OIL: np.array([1.0, -1.0, 1.0, -1.0, 1.0, -1.0])})
        spec = ControlLimitSpec(
            sigma_multiplier=3.0, formulation=ControlLimitFormulation.TIME_VARYING
        )
        detector = EwmaDetector(0.5, spec)
        detector.fit_control_limits(healthy, PartitionRef.HEALTHY_VALIDATION)
        series, _ = detector.detect(healthy)
        sigma = np.std(healthy.data[NORMALIZED_RESIDUAL_COLUMN].to_numpy(), ddof=1)
        factor = 0.5 / 1.5
        expected_t1 = 3.0 * sigma * math.sqrt(factor * (1.0 - 0.25))
        expected_t2 = 3.0 * sigma * math.sqrt(factor * (1.0 - 0.0625))
        assert series[0].upper.iloc[0] == pytest.approx(expected_t1)
        assert series[0].upper.iloc[1] == pytest.approx(expected_t2)
        assert series[0].upper.iloc[1] > series[0].upper.iloc[0]

    def test_state_encoding_high_low_normal(self):
        rng = np.random.default_rng(2)
        healthy = _normalized_frame({OIL: rng.standard_normal(300)})
        detector = EwmaDetector(1.0, ControlLimitSpec(sigma_multiplier=3.0))
        detector.fit_control_limits(healthy, PartitionRef.HEALTHY_VALIDATION)
        monitored = _normalized_frame({OIL: np.array([0.0, 0.1, 8.0, -8.0, 0.0])})
        _, detections = detector.detect(monitored)
        assert list(detections[0].states) == [0, 0, 1, -1, 0]
        assert detections[0].method_label == PRIMARY_EWMA_LABEL

    def test_method_label_is_mandatory(self):
        with pytest.raises(ConfigError):
            DetectionSeries(
                turbine="T1",
                target=OIL,
                timestamps=pd.Series([pd.Timestamp("2020-01-01", tz="UTC")]),
                states=pd.Series([0]),
                method_label="  ",
            )

    def test_in_control_characterization_iid_close_to_theory(self):
        rng = np.random.default_rng(3)
        values = rng.standard_normal(4000)
        healthy = _normalized_frame({OIL: values})
        detector = EwmaDetector(0.2, ControlLimitSpec(sigma_multiplier=3.0))
        detector.fit_control_limits(healthy, PartitionRef.HEALTHY_VALIDATION)
        report = detector.characterize_in_control(healthy)
        assert report.n_points == 4000
        assert np.isfinite(report.empirical_rate)
        assert report.inflation_ratio < 5.0

    def test_autocorrelated_residuals_inflate_false_alarms(self):
        """The reason the empirical characterization exists (risk R4)."""
        rng = np.random.default_rng(4)
        n = 4000
        ar = np.empty(n)
        ar[0] = rng.standard_normal()
        for i in range(1, n):
            ar[i] = 0.9 * ar[i - 1] + rng.standard_normal()
        ar = ar / np.std(ar, ddof=1)
        healthy = _normalized_frame({OIL: ar})
        detector = EwmaDetector(0.2, ControlLimitSpec(sigma_multiplier=3.0))
        detector.fit_control_limits(healthy, PartitionRef.HEALTHY_VALIDATION)
        report = detector.characterize_in_control(healthy)
        assert report.empirical_rate > report.theoretical_rate
        assert report.materially_inflated
        entry = report.limitations_entry()
        assert entry is not None and "R4" in entry

    def test_detect_requires_normalized_residuals(self):
        rf = _residual_frame({OIL: [1.0, 2.0, 3.0]})
        detector = EwmaDetector(0.2, ControlLimitSpec())
        healthy = _normalized_frame({OIL: np.array([0.1, -0.1, 0.2])})
        detector.fit_control_limits(healthy, PartitionRef.HEALTHY_VALIDATION)
        with pytest.raises(ConfigError):
            detector.detect(rf)

    def test_unfitted_detector_rejected(self):
        rf = _normalized_frame({OIL: np.array([0.1, -0.1])})
        with pytest.raises(ConfigError):
            EwmaDetector(0.2, ControlLimitSpec()).detect(rf)

    def test_invalid_lambda_rejected(self):
        with pytest.raises(ConfigError):
            EwmaDetector(0.0, ControlLimitSpec())
        with pytest.raises(ConfigError):
            EwmaDetector(1.5, ControlLimitSpec())


def _gapped_normalized_frame(values: np.ndarray, gap_after: int) -> ResidualFrame:
    """Two contiguous segments separated by a one-day gap — the shape
    healthy-state exclusion produces when it removes an alarm window from the
    middle of a stream."""
    early = pd.date_range("2019-01-01", periods=gap_after, freq="10min", tz="UTC")
    late = pd.date_range("2019-01-02", periods=len(values) - gap_after, freq="10min", tz="UTC")
    stamps = early.append(late)
    frame = pd.DataFrame(
        {
            "timestamp": stamps,
            "turbine_id": "T1",
            "target": OIL,
            "actual": values,
            "prediction": 0.0,
            RAW_RESIDUAL_COLUMN: values,
            NORMALIZED_RESIDUAL_COLUMN: np.nan,
        }
    )
    return ResidualFrame(frame).with_normalized(pd.Series(values))


class TestGapHandling:
    """ADR-042: the EWMA recursion carried its memory across exclusion gaps as
    though the rows were adjacent, and ``np.nan_to_num`` charted an absent
    residual as exactly normal. Both branches now exist; CONTINUOUS stays the
    default so no stored result moves without an author ruling.
    """

    @staticmethod
    def _detector(gap_handling: GapHandling) -> EwmaDetector:
        rng = np.random.default_rng(0)
        healthy = _normalized_frame({OIL: rng.standard_normal(400)})
        detector = EwmaDetector(
            0.2, ControlLimitSpec(sigma_multiplier=3.0), gap_handling=gap_handling
        )
        detector.fit_control_limits(healthy, PartitionRef.HEALTHY_TRAINING)
        return detector

    @staticmethod
    def _excursion() -> ResidualFrame:
        # Sustained excursion in segment one, nothing in segment two.
        return _gapped_normalized_frame(
            np.concatenate([np.full(20, 5.0), np.zeros(20)]), gap_after=20
        )

    def test_continuous_carries_memory_across_the_gap(self):
        series, _ = self._detector(GapHandling.CONTINUOUS).detect(self._excursion())
        assert series[0].values.to_numpy()[20] > 1.0

    def test_reset_restarts_the_recursion_at_the_gap(self):
        series, _ = self._detector(GapHandling.RESET).detect(self._excursion())
        assert series[0].values.to_numpy()[20] == pytest.approx(0.0)

    def test_gap_census_is_reported_on_the_default_branch(self):
        """The size of the open question must be visible on a CONTINUOUS run,
        not only on one that already decided to act on it."""
        detector = self._detector(GapHandling.CONTINUOUS)
        detector.detect(self._excursion())
        census = detector.gap_census()
        assert census["gap_handling"] == "continuous"
        assert census["n_discontinuities"] == 1
        assert census["n_samples"] == 40
        assert census["n_segments"] == 2

    def test_contiguous_stream_makes_both_branches_identical(self):
        """The monitoring partition is unfiltered and contiguous, so the
        branches must agree there. That is why this never surfaced in the
        detection results — only in the healthy-block calibration."""
        values = np.concatenate([np.full(20, 5.0), np.zeros(20)])
        frame = _gapped_normalized_frame(values, gap_after=40)  # no gap
        continuous = self._detector(GapHandling.CONTINUOUS)
        reset = self._detector(GapHandling.RESET)
        a, _ = continuous.detect(frame)
        b, _ = reset.detect(frame)
        assert continuous.gap_census()["n_discontinuities"] == 0
        assert np.allclose(a[0].values.to_numpy(), b[0].values.to_numpy())

    def test_in_control_report_carries_the_gap_census(self):
        detector = self._detector(GapHandling.CONTINUOUS)
        report = detector.characterize_in_control(self._excursion())
        assert report.as_dict()["gap_census"]["n_discontinuities"] == 1
