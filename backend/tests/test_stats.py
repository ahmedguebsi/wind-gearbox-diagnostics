"""M-28 tests: blocked bootstrap, Diebold-Mariano, comparison tables.

Synthetic series are SYNTHETIC TEST DATA — NOT VALID THESIS EVIDENCE; they
verify statistical mechanics against references, never scientific claims.
"""

import inspect

import numpy as np
import pandas as pd
import pytest

from app.core.errors import ConfigError
from app.detection.matched_fpr import (
    ComparisonReport,
    MatchedPoint,
    OperatingCurve,
    OperatingPoint,
)
from app.evaluation.bootstrap import (
    BlockedBootstrap,
    ConfidenceInterval,
    block_length_from_autocorrelation,
)
from app.evaluation.comparison import (
    MetricWithCI,
    ModelAccuracyRow,
    build_accuracy_table,
    provisional_footnote,
    rq2_table,
    verify_comparable,
)
from app.evaluation.dm_test import MIN_RELIABLE_N, diebold_mariano


def _ar1(n: int, phi: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    series = np.empty(n)
    series[0] = rng.standard_normal()
    for i in range(1, n):
        series[i] = phi * series[i - 1] + rng.standard_normal()
    return series


class TestBlockedBootstrap:
    def test_iid_bootstrap_is_not_selectable(self):
        """M-28 test obligation: block_length < 2 IS the i.i.d. bootstrap."""
        with pytest.raises(ConfigError, match=r"i\.i\.d\."):
            BlockedBootstrap(block_length=1, n_boot=500, seed=1)

    def test_too_few_replicates_rejected(self):
        with pytest.raises(ConfigError):
            BlockedBootstrap(block_length=5, n_boot=10, seed=1)

    def test_ci_brackets_point_and_is_seed_reproducible(self):
        series = _ar1(300, 0.5, seed=2)
        bootstrap = BlockedBootstrap(block_length=10, n_boot=400, seed=7)
        first = bootstrap.ci(series, np.mean)
        second = BlockedBootstrap(block_length=10, n_boot=400, seed=7).ci(series, np.mean)
        assert first == second
        assert first.lower <= first.point <= first.upper
        assert first.block_length == 10 and first.seed == 7

    def test_series_shorter_than_block_rejected(self):
        with pytest.raises(ConfigError):
            BlockedBootstrap(block_length=50, n_boot=200, seed=1).ci(np.zeros(20), np.mean)

    def test_block_length_heuristic_grows_with_autocorrelation(self):
        rng = np.random.default_rng(3)
        white = rng.standard_normal(1000)
        correlated = _ar1(1000, 0.9, seed=3)
        assert block_length_from_autocorrelation(correlated) > (
            block_length_from_autocorrelation(white)
        )

    def test_coverage_on_synthetic_ar1(self):
        """M-28 test obligation: empirical coverage near nominal on AR(1)."""
        nominal = 0.90
        hits = 0
        n_sims = 60
        for sim in range(n_sims):
            series = _ar1(200, 0.5, seed=100 + sim)
            ci = BlockedBootstrap(block_length=10, n_boot=200, seed=sim).ci(
                series, np.mean, confidence=nominal
            )
            if ci.lower <= 0.0 <= ci.upper:  # true AR(1) mean is 0
                hits += 1
        coverage = hits / n_sims
        assert 0.75 <= coverage <= 1.0


class TestDieboldMariano:
    def test_matches_reference_hac_implementation(self):
        """M-28 test obligation: DM vs a reference implementation."""
        import statsmodels.api as sm

        rng = np.random.default_rng(4)
        loss_a = rng.standard_normal(120) ** 2
        loss_b = (rng.standard_normal(120) * 1.1) ** 2
        result = diebold_mariano(loss_a, loss_b, hac_lags=4)
        d = loss_a - loss_b
        fit = sm.OLS(d, np.ones(len(d))).fit(
            cov_type="HAC", cov_kwds={"maxlags": 4, "use_correction": False}
        )
        assert result.statistic == pytest.approx(float(fit.tvalues[0]), rel=1e-8)

    def test_identical_losses_are_a_null_result(self):
        losses = np.abs(_ar1(50, 0.3, seed=5))
        result = diebold_mariano(losses, losses.copy())
        assert result.statistic == 0.0
        assert result.p_value == 1.0

    def test_short_series_flagged_with_caveat(self):
        rng = np.random.default_rng(6)
        result = diebold_mariano(rng.standard_normal(10), rng.standard_normal(10))
        assert result.n < MIN_RELIABLE_N
        assert result.reliable is False
        assert result.caveat is not None and "LIMITATIONS" in result.caveat

    def test_mismatched_lengths_rejected(self):
        with pytest.raises(ConfigError):
            diebold_mariano(np.zeros(10), np.zeros(11))

    def test_default_hac_lags_recorded(self):
        rng = np.random.default_rng(7)
        result = diebold_mariano(rng.standard_normal(130), rng.standard_normal(130))
        assert result.hac_lags == 5  # floor(130 ** (1/3)) = floor(5.066)


def _record(experiment_id: str, sha: str, provisional=("detection.ewma_lambda",)):
    return {
        "experiment_id": experiment_id,
        "schema_version": "1.2.0",
        "dataset": {"provenance": {"sources": [{"sha256": sha}]}},
        "resolved_config": {"provisional_parameters": list(provisional)},
    }


def _ci(value: float) -> ConfidenceInterval:
    return ConfidenceInterval(
        point=value,
        lower=value - 0.1,
        upper=value + 0.1,
        confidence=0.95,
        block_length=10,
        n_boot=500,
        seed=1,
    )


def _metric(value: float) -> MetricWithCI:
    return MetricWithCI(value=value, ci=_ci(value))


class TestComparisonTables:
    def test_provenance_mismatch_refused(self):
        """ARCHITECTURE §8.4: no accidental apples-to-oranges tables."""
        with pytest.raises(ConfigError, match="not comparable"):
            verify_comparable([_record("EXP-A", "aaa"), _record("EXP-B", "bbb")])

    def test_schema_version_mismatch_refused(self):
        record_b = _record("EXP-B", "aaa")
        record_b["schema_version"] = "1.1.0"
        with pytest.raises(ConfigError, match="not comparable"):
            verify_comparable([_record("EXP-A", "aaa"), record_b])

    def test_explicit_override_is_allowed_and_logged(self, caplog):
        records = [_record("EXP-A", "aaa"), _record("EXP-B", "bbb")]
        with caplog.at_level("WARNING"):
            verify_comparable(records, override_justification="ablation across datasets")
        assert any("ablation across datasets" in message for message in caplog.messages)

    def test_accuracy_table_labels_and_footnotes(self):
        records = [_record("EXP-A", "aaa")]
        row = ModelAccuracyRow(
            experiment_id="EXP-A",
            model_type="linear_regression",
            model_kind="baseline",
            target="gearbox_oil_temperature",
            partition="test",
            rmse=_metric(1.2),
            mae=_metric(0.9),
            r2=_metric(0.85),
            bias=_metric(0.01),
            dm_vs_thesis=None,
        )
        table = build_accuracy_table(records, [row])
        assert table.iloc[0]["kind"] == "BASELINE"
        assert "[1.100, 1.300]" in table.iloc[0]["rmse"]
        assert "detection.ewma_lambda" in table.iloc[0]["footnote"]

    def test_headline_metrics_require_cis_structurally(self):
        """M-28 acceptance 1: a bare float cannot enter the row type."""
        signature = inspect.signature(ModelAccuracyRow)
        assert signature.parameters["rmse"].annotation == "MetricWithCI"

    def test_rq2_table_accepts_only_matched_fpr_reports(self):
        """M-28 acceptance 2: RQ2 routes through M-23; raw counts are not a
        representable input."""
        signature = inspect.signature(rq2_table)
        assert signature.parameters["report"].annotation == "ComparisonReport"

        curve = OperatingCurve(
            pipeline="single", points=(OperatingPoint(3.0, 12.0, 0.01, 12, 1000),)
        )
        report = ComparisonReport(
            fpr_targets=(12.0,),
            matched=(
                MatchedPoint(pipeline="single", fpr_target=12.0, multiplier=3.0, reachable=True),
            ),
            curves={"single": curve},
        )
        table = rq2_table(report)
        assert list(table.columns) == [
            "pipeline",
            "fpr_target_per_turbine_year",
            "matched_multiplier",
            "reachable",
        ]
        assert table.iloc[0]["reachable"] == np.True_ or table.iloc[0]["reachable"] is True

    def test_footnote_empty_when_nothing_provisional(self):
        record = _record("EXP-A", "aaa", provisional=())
        assert provisional_footnote(record) == ""


class TestRq2TableRoundTrip:
    def test_table_is_dataframe_with_one_row_per_matched_point(self):
        curve = OperatingCurve(
            pipeline="coordinated",
            points=(
                OperatingPoint(2.0, 20.0, 0.02, 20, 1000),
                OperatingPoint(3.0, 8.0, 0.008, 8, 1000),
            ),
        )
        report = ComparisonReport(
            fpr_targets=(10.0, 15.0),
            matched=(
                MatchedPoint("coordinated", 10.0, 2.83, True),
                MatchedPoint("coordinated", 15.0, 2.42, True),
            ),
            curves={"coordinated": curve},
        )
        table = rq2_table(report)
        assert isinstance(table, pd.DataFrame)
        assert len(table) == 2
