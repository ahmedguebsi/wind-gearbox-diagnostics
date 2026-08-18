"""M-10…M-13 tests: validation, cleaning, healthy state, chronological splits.

Fixtures are SYNTHETIC TEST DATA — NOT VALID THESIS EVIDENCE — with no fault
labels (LOCKED-08). Where a fixture names a "fault window" it is a mechanics
fixture for exclusion arithmetic, never a claimed failure.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.core.config import HealthyStateConfig, ManualExclusionWindow
from app.core.errors import ConfigError, SplitPolicyError
from app.data.cleaning import OPERATION_REGISTRY, clean
from app.data.healthy_state import (
    ExclusionWindow,
    HealthyStateBuilder,
    deduplicate_exclusion_windows,
)
from app.data.ingestion import CanonicalDataset
from app.data.provenance import ProvenanceChain, ProvenanceRecord
from app.data.schema import default_schema
from app.data.splitting import (
    ExperimentFlags,
    Split,
    SplitPolicyGuard,
    SplitSpec,
    SplitStrategy,
    rolling_origin_folds,
    seasonal_coverage,
    split_chronologically,
)
from app.data.validation import Level, StepChangeRule, validate


def _record() -> ProvenanceRecord:
    return ProvenanceRecord(
        sha256="0" * 64,
        source_path="synthetic",
        source_filename="synthetic.csv",
        size_bytes=1,
        ingested_at_utc=pd.Timestamp("2026-08-11", tz="UTC").to_pydatetime(),
        source_timezone="UTC",
        encoding="utf-8",
        schema_version="1.0.0",
        mapping_hash="hash",
    )


def make_dataset(frame: pd.DataFrame) -> CanonicalDataset:
    schema = default_schema()
    roles = {c: schema.variable(c).role for c in frame.columns if c in schema.names()}
    return CanonicalDataset(
        frame=frame,
        schema_version="1.0.0",
        provenance=ProvenanceChain(sources=(_record(),)),
        roles=roles,
    )


def synthetic_frame(
    days: int = 400, start: str = "2019-01-01", turbine: str = "T1", freq: str = "10min"
) -> pd.DataFrame:
    periods = days * 144
    stamps = pd.date_range(start, periods=periods, freq=freq, tz="UTC")
    rng = np.random.default_rng(42)
    day_of_year = stamps.dayofyear.to_numpy()
    ambient = 10 + 8 * np.sin(2 * np.pi * day_of_year / 365) + rng.normal(0, 1, periods)
    power = np.clip(rng.normal(900, 400, periods), -10, 2050)
    return pd.DataFrame(
        {
            "timestamp": stamps,
            "turbine_id": turbine,
            "wind_speed": np.clip(rng.normal(7, 2, periods), 0, 25),
            "active_power": power,
            "ambient_temperature": ambient,
            "gearbox_oil_temperature": 45 + 0.005 * power + 0.2 * ambient,
            "gearbox_bearing_temperature": 50 + 0.006 * power + 0.2 * ambient,
        }
    )


class TestValidation:
    def test_read_only(self):
        frame = synthetic_frame(days=3)
        dataset = make_dataset(frame)
        before = dataset.content_hash
        validate(dataset, default_schema())
        assert dataset.content_hash == before

    def test_gap_and_duplicate_findings(self):
        frame = synthetic_frame(days=2)
        frame = pd.concat([frame.iloc[:100], frame.iloc[120:]], ignore_index=True)
        frame = pd.concat([frame, frame.iloc[[5]]], ignore_index=True)
        report = validate(make_dataset(frame), default_schema())
        rule_ids = {f.rule_id for f in report.findings}
        assert "TIMESTAMP.GAP" in rule_ids
        assert "TIMESTAMP.DUPLICATE" in rule_ids

    def test_impossible_values_are_errors(self):
        frame = synthetic_frame(days=2)
        frame.loc[0, "wind_speed"] = 500.0
        report = validate(make_dataset(frame), default_schema())
        assert any(
            f.rule_id == "RANGE.IMPOSSIBLE" and f.level is Level.ERROR for f in report.findings
        )

    def test_step_change_detected_and_not_corrected(self):
        frame = synthetic_frame(days=10)
        shift_at = len(frame) // 2
        frame.loc[shift_at:, "gearbox_oil_temperature"] += 15.0
        dataset = make_dataset(frame)
        before = dataset.frame["gearbox_oil_temperature"].copy()
        report = validate(dataset, default_schema())
        assert report.step_changes, "expected a detected level shift"
        step = report.step_changes[0]
        assert step.column == "gearbox_oil_temperature"
        assert step.magnitude > 10
        # Detection must not alter the data.
        pd.testing.assert_series_equal(dataset.frame["gearbox_oil_temperature"], before)

    def test_smooth_seasonal_series_yields_no_step(self):
        frame = synthetic_frame(days=60)
        rule = StepChangeRule()
        rule.check(make_dataset(frame), default_schema())
        assert rule.detected == []

    def test_report_serialises(self):
        report = validate(make_dataset(synthetic_frame(days=2)), default_schema())
        payload = report.as_dict()
        assert payload["n_rows"] > 0
        assert isinstance(payload["findings"], list)


class TestCleaning:
    def test_audit_arithmetic_holds(self):
        frame = synthetic_frame(days=3)
        frame.loc[0:5, "gearbox_oil_temperature"] = np.nan
        frame.loc[10:12, "wind_speed"] = np.nan
        cleaned, audit = clean(
            make_dataset(frame),
            default_schema(),
            ["drop_missing_any_target", "drop_missing_any_predictor"],
        )
        assert audit.arithmetic_holds()
        assert audit.operations[0].rows_removed == 6
        assert len(cleaned.frame) == audit.operations[-1].rows_after

    def test_disabled_rule_leaves_data_untouched(self):
        frame = synthetic_frame(days=2)
        cleaned, audit = clean(make_dataset(frame), default_schema(), [])
        assert len(cleaned.frame) == len(frame)
        assert audit.operations == []

    def test_unknown_operation_rejected(self):
        with pytest.raises(ConfigError):
            clean(make_dataset(synthetic_frame(days=1)), default_schema(), ["delete_everything"])

    def test_cleaned_dataset_keeps_provenance_chain(self):
        dataset = make_dataset(synthetic_frame(days=2))
        cleaned, _ = clean(dataset, default_schema(), ["drop_unparseable_timestamps"])
        assert cleaned.provenance.source_hashes == dataset.provenance.source_hashes
        assert cleaned.provenance.stages[-1][0] == "cleaned"

    def test_every_registered_operation_produces_an_audit_entry(self):
        """Meta-test: no cleaning path removes rows without recording it."""
        dataset = make_dataset(synthetic_frame(days=2))
        for name in OPERATION_REGISTRY:
            # ADR-020: the nullify operation refuses to run without its
            # companion drop rule, so it is exercised as the pair.
            operations = (
                [name, "drop_missing_any_predictor"]
                if name == "nullify_impossible_predictor_values"
                else [name]
            )
            _, audit = clean(dataset, default_schema(), operations)
            assert len(audit.operations) == len(operations)
            assert audit.operations[0].rule == name
            assert audit.operations[0].reason

    def test_impossible_predictor_values_nullified_then_dropped(self):
        """ADR-020: impossible predictor values cannot serve as model
        inputs; the row is removed with the count visible in the audit."""
        frame = synthetic_frame(days=2)
        frame["generator_speed"] = 1500.0
        frame.loc[3, "generator_speed"] = -576.6  # stuck-signal artefact
        frame.loc[7, "generator_speed"] = 9999.0
        cleaned, audit = clean(
            make_dataset(frame),
            default_schema(),
            ["nullify_impossible_predictor_values", "drop_missing_any_predictor"],
        )
        assert len(cleaned.frame) == len(frame) - 2
        nullify = audit.operations[0]
        assert nullify.rows_removed == 0  # it nullifies; the drop rule removes
        assert nullify.detail["rows_affected"] == 2
        assert nullify.detail["by_column"] == {"generator_speed": 2}
        assert audit.operations[1].rows_removed == 2
        assert audit.arithmetic_holds()

    def test_standstill_jitter_within_widened_bounds_is_kept(self):
        """ADR-020 schema 1.3.0: -1 to -5 RPM at standstill is routine
        sensor jitter, not physically impossible."""
        frame = synthetic_frame(days=2)
        frame["generator_speed"] = 1500.0
        frame.loc[3, "generator_speed"] = -1.4
        cleaned, audit = clean(
            make_dataset(frame),
            default_schema(),
            ["nullify_impossible_predictor_values", "drop_missing_any_predictor"],
        )
        assert len(cleaned.frame) == len(frame)
        assert audit.operations[0].detail == {}

    def test_nullify_without_drop_rule_rejected(self):
        """ADR-020: the policy must not silently half-apply."""
        with pytest.raises(ConfigError):
            clean(
                make_dataset(synthetic_frame(days=1)),
                default_schema(),
                ["nullify_impossible_predictor_values"],
            )


class TestHealthyState:
    def test_accounting_is_exact_and_disjoint(self):
        frame = synthetic_frame(days=30)
        config = HealthyStateConfig()
        builder = HealthyStateBuilder(config, default_schema())
        start = frame["timestamp"].iloc[500]
        windows = [ExclusionWindow("T1", start, start + timedelta(hours=6), "known_fault_period")]
        healthy, report = builder.build(make_dataset(frame), fault_windows=windows)
        assert report.accounting_holds()
        assert report.total == len(frame)
        assert report.accepted == len(healthy.frame)
        assert sum(report.exclusion_counts.values()) == report.excluded

    def test_overlapping_reasons_attributed_once_by_priority(self):
        frame = synthetic_frame(days=10)
        start = frame["timestamp"].iloc[100]
        end = start + timedelta(hours=2)
        builder = HealthyStateBuilder(
            HealthyStateConfig(fault_pre_exclusion_days=0), default_schema()
        )
        overlapping = [ExclusionWindow("T1", start, end, "known_fault_period")]
        alarms = [ExclusionWindow("T1", start, end, "alarm_period")]
        _, report = builder.build(
            make_dataset(frame), fault_windows=overlapping, alarm_windows=alarms
        )
        assert report.accounting_holds()
        # Fault wins; the same rows are not counted twice.
        assert "known_fault_period" in report.exclusion_counts
        assert report.exclusion_counts.get("alarm_period", 0) == 0

    def test_power_floor_excludes_and_is_provisional(self):
        frame = synthetic_frame(days=5)
        frame["active_power"] = 10.0
        builder = HealthyStateBuilder(HealthyStateConfig(), default_schema())
        _, report = builder.build(make_dataset(frame))
        assert report.exclusion_counts["below_minimum_active_power"] == len(frame)
        assert report.accepted == 0

    def test_pre_fault_window_applied(self):
        frame = synthetic_frame(days=40)
        fault_start = frame["timestamp"].iloc[-100]
        builder = HealthyStateBuilder(
            HealthyStateConfig(fault_pre_exclusion_days=30, minimum_active_power_kw=-1e9),
            default_schema(),
        )
        _, report = builder.build(
            make_dataset(frame),
            fault_windows=[
                ExclusionWindow(
                    "T1", fault_start, frame["timestamp"].iloc[-1], "known_fault_period"
                )
            ],
        )
        assert report.exclusion_counts["pre_fault_window"] > 0

    def test_guard5_warns_when_fault_window_matches_nothing(self):
        """The dangerous case: a turbine-identifier mismatch means the
        exclusion silently does nothing and the failure period stays in
        training."""
        frame = synthetic_frame(days=5, turbine="Kelmarsh 1")
        builder = HealthyStateBuilder(
            HealthyStateConfig(minimum_active_power_kw=-1e9), default_schema()
        )
        mismatched = ExclusionWindow(
            "KELMARSH_01",  # same turbine, different identifier spelling
            frame["timestamp"].iloc[10],
            frame["timestamp"].iloc[20],
            "known_fault_period",
        )
        _, report = builder.build(make_dataset(frame), fault_windows=[mismatched])
        assert any(f.rule_id == "GUARD5.WINDOW_MATCHED_NOTHING" for f in report.findings)

    def test_guard5_covers_author_designated_event_spans(self):
        """ADR-041: Guard 5 was structurally dead on the real dataset.

        It inspected ``known_fault_period`` only, and no caller constructs one
        — this dataset has no maintenance-confirmed failures (LIM-002), so the
        designated failure episode is carried as an ADR-024
        ``author_designated_event_span`` manual window. Every real run
        therefore reported ``findings: []``, which read as "no known failure
        reached the healthy set" when nothing had been checked.
        """
        frame = synthetic_frame(days=5, turbine="Kelmarsh 1")
        span = ManualExclusionWindow(
            label="EVENT-001-episode-span",
            turbine="KELMARSH_01",  # identifier mismatch: exclusion does nothing
            start_utc=frame["timestamp"].iloc[10].to_pydatetime(),
            end_utc=frame["timestamp"].iloc[20].to_pydatetime(),
            citation="ADR-013 via ADR-024",
            reason="author_designated_event_span",
        )
        builder = HealthyStateBuilder(
            HealthyStateConfig(minimum_active_power_kw=-1e9, manual_exclusion_windows=(span,)),
            default_schema(),
        )
        _, report = builder.build(make_dataset(frame))
        assert any(f.rule_id == "GUARD5.WINDOW_MATCHED_NOTHING" for f in report.findings)

    def test_guard5_does_not_warn_for_a_window_outside_this_period(self):
        """ADR-041 scoping. The EVENT-001 span lies wholly inside the
        monitoring period, so it correctly matches nothing during the
        pre-monitoring healthy build. Warning there would fire on every run
        and train the reader to ignore the guard."""
        frame = synthetic_frame(days=5, turbine="Kelmarsh 1")
        far_future = ManualExclusionWindow(
            label="EVENT-001-episode-span",
            turbine="Kelmarsh 1",
            start_utc=(frame["timestamp"].iloc[-1] + timedelta(days=30)).to_pydatetime(),
            end_utc=(frame["timestamp"].iloc[-1] + timedelta(days=60)).to_pydatetime(),
            citation="ADR-013 via ADR-024",
            reason="author_designated_event_span",
        )
        builder = HealthyStateBuilder(
            HealthyStateConfig(
                minimum_active_power_kw=-1e9, manual_exclusion_windows=(far_future,)
            ),
            default_schema(),
        )
        _, report = builder.build(make_dataset(frame))
        assert report.findings == []

    def test_guard5_flags_a_designated_event_span_left_in_the_healthy_set(self):
        """The substantive check: a designated failure episode overlapping the
        accepted population is reported, not silently trained on."""
        frame = synthetic_frame(days=5, turbine="Kelmarsh 1")
        builder = HealthyStateBuilder(
            HealthyStateConfig(minimum_active_power_kw=-1e9, fault_pre_exclusion_days=0),
            default_schema(),
        )
        overlapping = ExclusionWindow(
            "Kelmarsh 1",
            frame["timestamp"].iloc[10],
            frame["timestamp"].iloc[20],
            "author_designated_event_span",
        )
        _, report = builder.build(make_dataset(frame), fault_windows=[overlapping])
        # The span IS excluded, so no failure survives into the healthy
        # population and Guard 5 stays silent — the correct outcome, now
        # actually verified rather than vacuously true.
        assert not any(f.rule_id == "GUARD5.FAILURE_IN_HEALTHY" for f in report.findings)
        assert report.exclusion_counts["author_designated_event_span"] == 11

    def test_guard5_silent_when_window_applies_correctly(self):
        frame = synthetic_frame(days=5, turbine="Kelmarsh 1")
        builder = HealthyStateBuilder(
            HealthyStateConfig(minimum_active_power_kw=-1e9, fault_pre_exclusion_days=0),
            default_schema(),
        )
        window = ExclusionWindow(
            "Kelmarsh 1",
            frame["timestamp"].iloc[10],
            frame["timestamp"].iloc[20],
            "known_fault_period",
        )
        _, report = builder.build(make_dataset(frame), fault_windows=[window])
        assert report.findings == []
        assert report.exclusion_counts["known_fault_period"] == 11

    def test_step_change_windows_excluded_only_when_enabled(self):
        """ADR-018: the enabled variant still excludes (the sensitivity
        suite sweeps it), but it must be an explicit opt-in."""
        from app.data.validation import StepChange

        frame = synthetic_frame(days=10)
        builder = HealthyStateBuilder(
            HealthyStateConfig(minimum_active_power_kw=-1e9, exclude_step_changes=True),
            default_schema(),
        )
        step = StepChange(
            column="gearbox_oil_temperature",
            turbine="T1",
            timestamp_utc=frame["timestamp"].iloc[720],
            magnitude=15.0,
            before_median=50.0,
            after_median=65.0,
        )
        _, report = builder.build(make_dataset(frame), step_changes=[step])
        assert report.exclusion_counts["sensor_failure_or_step_change"] > 0

    def test_step_changes_report_without_excluding_by_default(self):
        """ADR-018: detected step changes are findings, not exclusions."""
        from app.data.validation import StepChange

        frame = synthetic_frame(days=10)
        builder = HealthyStateBuilder(
            HealthyStateConfig(minimum_active_power_kw=-1e9), default_schema()
        )
        step = StepChange(
            column="gearbox_oil_temperature",
            turbine="T1",
            timestamp_utc=frame["timestamp"].iloc[720],
            magnitude=15.0,
            before_median=50.0,
            after_median=65.0,
        )
        _, report = builder.build(make_dataset(frame), step_changes=[step])
        assert "sensor_failure_or_step_change" not in report.exclusion_counts
        assert report.accepted == len(frame)

    def test_manual_exclusion_window_applies_with_attribution(self):
        """ADR-018: author-designated artefact windows exclude by name."""
        from app.core.config import ManualExclusionWindow

        frame = synthetic_frame(days=10, turbine="Kelmarsh 6")
        start = frame["timestamp"].iloc[100]
        end = frame["timestamp"].iloc[150]
        config = HealthyStateConfig(
            minimum_active_power_kw=-1e9,
            manual_exclusion_windows=(
                ManualExclusionWindow(
                    label="K6-artefact-test",
                    turbine="Kelmarsh 6",
                    start_utc=start.to_pydatetime(),
                    end_utc=end.to_pydatetime(),
                    citation="ADR-018 (test fixture)",
                ),
            ),
        )
        builder = HealthyStateBuilder(config, default_schema())
        _, report = builder.build(make_dataset(frame))
        assert report.exclusion_counts["author_designated_artefact"] == 51
        assert report.accounting_holds()


class TestSplitting:
    def test_guard3_rejects_random_on_thesis_runs(self):
        spec = SplitSpec(strategy=SplitStrategy.RANDOM)
        with pytest.raises(SplitPolicyError):
            SplitPolicyGuard().validate(spec, ExperimentFlags(thesis_official=True))

    def test_guard3_unbypassable_across_configs(self):
        """Property-style: no fraction combination lets a random split through."""
        for train in (0.5, 0.6, 0.7):
            spec = SplitSpec(
                strategy=SplitStrategy.RANDOM,
                train_fraction=train,
                validation_fraction=(1 - train) / 2,
                test_fraction=(1 - train) / 2,
            )
            with pytest.raises(SplitPolicyError):
                split_chronologically(
                    make_dataset(synthetic_frame(days=30)),
                    default_schema(),
                    spec,
                    ExperimentFlags(thesis_official=True),
                )

    def test_boundaries_are_disjoint_and_ordered(self):
        dataset = make_dataset(synthetic_frame(days=400))
        split = split_chronologically(dataset, default_schema(), SplitSpec())
        assert split.disjoint()
        stamps = dataset.frame["timestamp"]
        assert stamps[split.train].max() < stamps[split.validation].min()
        assert stamps[split.validation].max() < stamps[split.test].min()

    def test_fractions_must_sum_to_one(self):
        with pytest.raises(SplitPolicyError):
            SplitSpec(train_fraction=0.7, validation_fraction=0.2, test_fraction=0.2)

    def test_explicit_dates_reject_overlap(self):
        with pytest.raises(SplitPolicyError):
            SplitSpec(
                strategy=SplitStrategy.EXPLICIT_DATES,
                train_end=date(2020, 6, 1),
                validation_end=date(2020, 1, 1),
            )

    def test_explicit_date_split_places_window_in_test(self):
        """ADR-010 shape: an explicit split can place a named window in TEST
        with training data preceding it."""
        dataset = make_dataset(synthetic_frame(days=400, start="2019-01-01"))
        spec = SplitSpec(
            strategy=SplitStrategy.EXPLICIT_DATES,
            train_end=date(2019, 9, 1),
            validation_end=date(2019, 11, 1),
        )
        split = split_chronologically(dataset, default_schema(), spec)
        stamps = dataset.frame["timestamp"]
        assert stamps[split.train].max() < pd.Timestamp("2019-09-01", tz="UTC")
        assert stamps[split.test].min() >= pd.Timestamp("2019-11-01", tz="UTC")
        assert len(split.train) > 0 and len(split.test) > 0

    def test_seasonal_warning_below_twelve_months(self):
        dataset = make_dataset(synthetic_frame(days=240))  # 8 months
        split = split_chronologically(dataset, default_schema(), SplitSpec())
        assert split.seasonal_coverage.train_months < 12
        assert any("seasonal covariate shift" in w for w in split.seasonal_coverage.warnings)

    def test_no_seasonal_warning_with_full_year_training(self):
        dataset = make_dataset(synthetic_frame(days=600, start="2018-01-01"))
        split = split_chronologically(dataset, default_schema(), SplitSpec())
        assert split.seasonal_coverage.train_months >= 12
        assert split.seasonal_coverage.months_in_test_absent_from_train == []

    def test_ambient_range_comparison_reported(self):
        dataset = make_dataset(synthetic_frame(days=400))
        split = split_chronologically(dataset, default_schema(), SplitSpec())
        coverage = split.seasonal_coverage
        assert coverage.ambient_range_train is not None
        assert coverage.ambient_range_test is not None
        assert coverage.as_dict()["ambient_range_train"][0] <= coverage.ambient_range_train[1]

    def test_rolling_origin_folds_are_ordered_and_counted(self):
        dataset = make_dataset(synthetic_frame(days=100))
        folds = rolling_origin_folds(dataset, default_schema(), SplitSpec(n_folds=4))
        assert len(folds) == 4
        stamps = dataset.frame["timestamp"]
        for train_index, test_index in folds:
            assert stamps[train_index].max() <= stamps[test_index].min()
        # Training blocks grow monotonically.
        assert [len(t) for t, _ in folds] == sorted(len(t) for t, _ in folds)

    def test_empty_dataset_rejected(self):
        empty = synthetic_frame(days=1).iloc[0:0]
        with pytest.raises(SplitPolicyError):
            split_chronologically(make_dataset(empty), default_schema(), SplitSpec())

    def test_seasonal_coverage_flags_months_absent_from_training(self):
        frame = synthetic_frame(days=200, start="2019-01-01")
        n = len(frame)
        report = seasonal_coverage(
            frame, default_schema(), frame.index[: n // 2], frame.index[n // 2 :]
        )
        assert report.months_in_test_absent_from_train
        assert any("absent from training" in w for w in report.warnings)
        assert isinstance(
            Split(
                train=frame.index[:1],
                validation=frame.index[1:2],
                test=frame.index[2:3],
                spec=SplitSpec(),
                seasonal_coverage=report,
                boundaries_utc=(None, None),
            ).disjoint(),
            bool,
        )


class TestExclusionWindowDeduplication:
    """ADR-033(b): status folders overlap, so the same record can yield the
    same window twice. The healthy population must be unchanged — window
    application is idempotent over the row mask — while the count stops
    double-counting."""

    @staticmethod
    def _window(turbine="T1", hours=(0, 6), reason="alarm_period"):
        start = pd.Timestamp("2020-01-05", tz="UTC") + timedelta(hours=hours[0])
        end = pd.Timestamp("2020-01-05", tz="UTC") + timedelta(hours=hours[1])
        return ExclusionWindow(turbine, start, end, reason)

    def test_identical_windows_collapse(self):
        windows = [self._window(), self._window(), self._window()]
        unique, removed = deduplicate_exclusion_windows(windows)
        assert len(unique) == 1
        assert removed == 2

    def test_windows_differing_in_any_field_are_kept(self):
        windows = [
            self._window(),
            self._window(turbine="T2"),
            self._window(hours=(0, 7)),
            self._window(reason="maintenance_period"),
        ]
        unique, removed = deduplicate_exclusion_windows(windows)
        assert len(unique) == 4
        assert removed == 0

    def test_first_occurrence_order_is_preserved(self):
        a, b = self._window(turbine="T1"), self._window(turbine="T2")
        unique, _ = deduplicate_exclusion_windows([a, b, a, b])
        assert [w.turbine for w in unique] == ["T1", "T2"]

    def test_healthy_population_is_unchanged_by_duplicates(self):
        """The load-bearing property: deduplicating must not move a single
        row, because applying a window twice excludes the same rows once."""
        frame = synthetic_frame(days=10)
        builder = HealthyStateBuilder(
            HealthyStateConfig(minimum_active_power_kw=-1e9), default_schema()
        )
        start = frame["timestamp"].iloc[50]
        window = ExclusionWindow("T1", start, start + timedelta(hours=3), "alarm_period")

        with_dupes, report_dupes = builder.build(
            make_dataset(frame), alarm_windows=[window, window, window]
        )
        deduped, _ = deduplicate_exclusion_windows([window, window, window])
        without, report_without = builder.build(make_dataset(frame), alarm_windows=list(deduped))

        assert report_dupes.accepted == report_without.accepted
        assert report_dupes.exclusion_counts == report_without.exclusion_counts
        pd.testing.assert_frame_equal(with_dupes.frame, without.frame)

    def test_empty_input(self):
        unique, removed = deduplicate_exclusion_windows([])
        assert unique == () and removed == 0
