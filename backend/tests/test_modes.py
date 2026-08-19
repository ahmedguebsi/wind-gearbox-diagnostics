"""ADR-035 orthogonal-mode rotation tests (app/residuals/modes.py; arm A6).

Fixtures are SYNTHETIC TEST DATA — NOT VALID THESIS EVIDENCE — with no fault
labels (LOCKED-08). Tests verify the rotation's algebraic identities and its
refusal behaviour, never detection performance claims.
"""

import math

import numpy as np
import pandas as pd
import pytest

from app.core.errors import ConfigError
from app.data.schema import GEARBOX_BEARING_TEMPERATURE, GEARBOX_OIL_TEMPERATURE
from app.residuals.engine import (
    NORMALIZED_RESIDUAL_COLUMN,
    RAW_RESIDUAL_COLUMN,
    TARGET_COLUMN,
    TIMESTAMP_COLUMN,
    TURBINE_COLUMN,
    ResidualFrame,
)
from app.residuals.ewma import ControlLimitSpec, EwmaDetector
from app.residuals.modes import (
    MODE_COMMON,
    MODE_DIFFERENTIAL,
    rotate_to_modes,
)
from app.residuals.normalization import MadNormalizer, PartitionRef

BEARING = GEARBOX_BEARING_TEMPERATURE
OIL = GEARBOX_OIL_TEMPERATURE


def _frame(
    normalized_by_target: dict[str, list[float]],
    turbine: str = "T1",
    start: str = "2020-01-01",
) -> pd.DataFrame:
    rows = []
    for target, values in normalized_by_target.items():
        for i, value in enumerate(values):
            rows.append(
                {
                    TIMESTAMP_COLUMN: pd.Timestamp(start, tz="UTC") + pd.Timedelta(minutes=10 * i),
                    TURBINE_COLUMN: turbine,
                    TARGET_COLUMN: target,
                    "actual": value,
                    "prediction": 0.0,
                    RAW_RESIDUAL_COLUMN: value,
                    NORMALIZED_RESIDUAL_COLUMN: value,
                }
            )
    return pd.DataFrame(rows)


def _standardized_pair(r: float, n: int = 400, seed: int = 7) -> tuple[np.ndarray, np.ndarray]:
    """Two exactly unit-variance (ddof=1), zero-mean series with correlation ~r."""
    rng = np.random.default_rng(seed)
    z = rng.standard_normal(n)
    w = rng.standard_normal(n)
    b = z
    o = r * z + math.sqrt(1.0 - r * r) * w
    b = (b - b.mean()) / b.std(ddof=1)
    o = (o - o.mean()) / o.std(ddof=1)
    return b, o


def test_rotation_values_and_sign_convention():
    frame = ResidualFrame(_frame({BEARING: [1.0, 3.0], OIL: [0.5, -1.0]}))
    modes, report = rotate_to_modes(frame)
    data = modes.data
    common = data[data[TARGET_COLUMN] == MODE_COMMON].sort_values(TIMESTAMP_COLUMN)
    diff = data[data[TARGET_COLUMN] == MODE_DIFFERENTIAL].sort_values(TIMESTAMP_COLUMN)
    sqrt2 = math.sqrt(2.0)
    assert np.allclose(common[RAW_RESIDUAL_COLUMN], [1.5 / sqrt2, 2.0 / sqrt2])
    # bearing sorts first, so a positive differential = bearing hotter than oil.
    assert np.allclose(diff[RAW_RESIDUAL_COLUMN], [0.5 / sqrt2, 4.0 / sqrt2])
    assert report.first_target == BEARING
    assert report.second_target == OIL
    # The mode enters the downstream machinery as a RAW pseudo-signal.
    assert modes.data[NORMALIZED_RESIDUAL_COLUMN].isna().all()


def test_exact_orthogonality_on_standardized_channels():
    b, o = _standardized_pair(r=0.95)
    frame = ResidualFrame(_frame({BEARING: list(b), OIL: list(o)}))
    _, report = rotate_to_modes(frame)
    r_sample = float(np.corrcoef(b, o)[0, 1])
    # ADR-035 identities: exact where the channels have exactly unit variance.
    assert abs(report.mode_pearson) < 1e-12
    assert math.isclose(report.sd_common, math.sqrt(1.0 + r_sample), rel_tol=1e-12)
    assert math.isclose(report.sd_differential, math.sqrt(1.0 - r_sample), rel_tol=1e-12)
    assert math.isclose(
        report.variance_share_common + report.variance_share_differential, 1.0, rel_tol=1e-12
    )
    assert math.isclose(report.channel_pearson, r_sample, rel_tol=1e-12)


def test_misaligned_points_are_dropped_and_counted():
    frame_df = _frame({BEARING: [1.0, 2.0, 3.0], OIL: [0.5, 1.5, 2.5]})
    # Remove one oil row: that timestamp no longer carries both channels.
    dropped_ts = frame_df[TIMESTAMP_COLUMN].iloc[1]
    mask = ~((frame_df[TARGET_COLUMN] == OIL) & (frame_df[TIMESTAMP_COLUMN] == dropped_ts))
    modes, report = rotate_to_modes(ResidualFrame(frame_df[mask].reset_index(drop=True)))
    assert report.n_aligned_points == 2
    assert report.n_dropped_points == 1
    assert len(modes.data) == 4  # 2 aligned points x 2 modes
    assert dropped_ts not in set(modes.data[TIMESTAMP_COLUMN])


def test_multi_turbine_alignment_and_lag1_pooling():
    b1, o1 = _standardized_pair(r=0.9, n=50, seed=1)
    b2, o2 = _standardized_pair(r=0.9, n=50, seed=2)
    combined = pd.concat(
        [
            _frame({BEARING: list(b1), OIL: list(o1)}, turbine="T1"),
            _frame({BEARING: list(b2), OIL: list(o2)}, turbine="T2"),
        ],
        ignore_index=True,
    )
    modes, report = rotate_to_modes(ResidualFrame(combined))
    assert report.n_aligned_points == 100
    assert set(modes.data[TURBINE_COLUMN]) == {"T1", "T2"}
    assert report.lag1_common is not None
    assert -1.0 <= report.lag1_common <= 1.0


def test_refuses_wrong_target_count():
    single = ResidualFrame(_frame({BEARING: [1.0, 2.0]}))
    with pytest.raises(ConfigError, match="exactly two channels"):
        rotate_to_modes(single)


def test_refuses_unnormalized_frame():
    frame_df = _frame({BEARING: [1.0, 2.0], OIL: [0.5, 1.5]})
    frame_df[NORMALIZED_RESIDUAL_COLUMN] = np.nan
    with pytest.raises(ConfigError, match="binding condition d"):
        rotate_to_modes(ResidualFrame(frame_df))


def test_refuses_duplicate_rows():
    frame_df = _frame({BEARING: [1.0, 2.0], OIL: [0.5, 1.5]})
    duplicated = pd.concat([frame_df, frame_df.iloc[[0]]], ignore_index=True)
    with pytest.raises(ConfigError, match="refuses to aggregate"):
        rotate_to_modes(ResidualFrame(duplicated))


def test_refuses_too_few_aligned_points():
    frame_df = _frame({BEARING: [1.0], OIL: [0.5]})
    with pytest.raises(ConfigError, match="Too few aligned"):
        rotate_to_modes(ResidualFrame(frame_df))


def test_modes_flow_through_identical_normalizer_and_detector():
    """The A6 chain: rotation -> config normalizer family -> EWMA detector."""
    b, o = _standardized_pair(r=0.95, n=300, seed=11)
    modes, _ = rotate_to_modes(ResidualFrame(_frame({BEARING: list(b), OIL: list(o)})))
    normalizer = MadNormalizer()
    normalizer.fit(modes, PartitionRef.HEALTHY_TRAINING)
    normalized = normalizer.transform(modes)
    detector = EwmaDetector(0.2, ControlLimitSpec(sigma_multiplier=3.0))
    detector.fit_control_limits(normalized, PartitionRef.HEALTHY_TRAINING)
    ewma_series, detections = detector.detect(normalized)
    assert sorted(s.target for s in ewma_series) == [MODE_COMMON, MODE_DIFFERENTIAL]
    assert all((d.states.isin([-1, 0, 1])).all() for d in detections)
