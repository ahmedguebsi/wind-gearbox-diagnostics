"""Ruleset v2 tests (app/fmea/modes_v2.py; ADR-050 frozen decision tree).

Fixtures are SYNTHETIC TEST DATA — NOT VALID THESIS EVIDENCE — with no fault
labels (LOCKED-08). Tests verify the frozen spec's mechanics: persistence,
the ADR-049 gate, episode construction, and the classification tree. They
never make diagnostic-performance claims.
"""

import numpy as np
import pandas as pd
import pytest

from app.core.errors import ConfigError
from app.fmea.knowledge_base import (
    UNVALIDATED_RULE_BANNER,
    FmeaKnowledgeBase,
    default_ruleset_path,
)
from app.fmea.modes_v2 import (
    MODES_V2_VERSION,
    ModeStateSeries,
    OutputType,
    classify_episode,
    find_episodes,
    interpret_modes,
    persistent_runs,
)

KB = FmeaKnowledgeBase.load(default_ruleset_path())
MIN = 3


def _series(
    c: list[int],
    d: list[int],
    eligible: list[bool] | None = None,
    turbine: str = "T1",
) -> ModeStateSeries:
    n = len(c)
    assert len(d) == n
    return ModeStateSeries(
        turbine=turbine,
        timestamps=pd.Series(pd.date_range("2020-06-01", periods=n, freq="10min", tz="UTC")),
        c_states=np.array(c, dtype=int),
        d_states=np.array(d, dtype=int),
        c_values=np.array(c, dtype=float) * 2.0,
        d_values=np.array(d, dtype=float) * 0.5,
        eligible=np.array(eligible if eligible is not None else [True] * n, dtype=bool),
    )


def _one_episode(c: list[int], d: list[int], eligible: list[bool] | None = None):
    episodes = find_episodes(_series(c, d, eligible), MIN)
    assert len(episodes) == 1
    return episodes[0]


# ---------------------------------------------------------------- persistence


def test_runs_require_min_consecutive_samples():
    states = np.array([1, 1, 0, 1, 1, 1, -1, -1, -1, -1], dtype=int)
    eligible = np.ones(len(states), dtype=bool)
    runs = persistent_runs(states, eligible, MIN, "C")
    assert [(r.sign, r.start_index, r.end_index) for r in runs] == [(1, 3, 5), (-1, 6, 9)]


def test_ineligible_samples_break_runs():
    states = np.array([1, 1, 1, 1, 1, 1], dtype=int)
    eligible = np.array([True, True, True, False, True, True])
    runs = persistent_runs(states, eligible, MIN, "D")
    # The gate splits one six-sample run into 3 + 2; only the first survives.
    assert [(r.start_index, r.end_index) for r in runs] == [(0, 2)]


def test_persistence_floor_is_validated():
    with pytest.raises(ConfigError, match="min_samples"):
        persistent_runs(np.array([1], dtype=int), np.array([True]), 0, "C")


# ------------------------------------------------------------------ episodes


def test_overlapping_runs_merge_into_one_episode():
    c = [0, 1, 1, 1, 1, 0, 0]
    d = [0, 0, 0, 1, 1, 1, 0]
    episode = _one_episode(c, d)
    assert (episode.start_index, episode.end_index) == (1, 5)
    assert {(r.mode, r.sign) for r in episode.runs} == {("C", 1), ("D", 1)}
    assert episode.max_abs_c == 2.0 and episode.max_abs_d == 0.5


def test_disjoint_runs_are_separate_episodes():
    c = [1, 1, 1, 0, 0, 0, 0, 0, 0]
    d = [0, 0, 0, 0, 0, 0, -1, -1, -1]
    episodes = find_episodes(_series(c, d), MIN)
    assert [(e.start_index, e.end_index) for e in episodes] == [(0, 2), (6, 8)]


def test_misaligned_series_refused():
    with pytest.raises(ConfigError, match="not aligned"):
        ModeStateSeries(
            turbine="T1",
            timestamps=pd.Series(pd.date_range("2020-06-01", periods=3, freq="10min", tz="UTC")),
            c_states=np.zeros(2, dtype=int),
            d_states=np.zeros(3, dtype=int),
            c_values=np.zeros(3),
            d_values=np.zeros(3),
            eligible=np.ones(3, dtype=bool),
        )


# ------------------------------------------------------- classification tree


def test_bearing_led_without_common_is_type_a_fmea002():
    interp = classify_episode(_one_episode([0] * 6, [0, 1, 1, 1, 1, 0]), KB)
    assert interp.output_type is OutputType.A_POSITIVE_CANDIDATE
    assert [c.rule_id for c in interp.candidates] == ["FMEA-002"]
    assert interp.candidates[0].label == UNVALIDATED_RULE_BANNER  # Guard 7 propagates
    assert "ADR-050 caution" in interp.note


def test_bearing_leads_common_is_type_a_with_lead_evidence():
    d = [1, 1, 1, 1, 1, 1, 1, 0]
    c = [0, 0, 1, 1, 1, 1, 1, 0]
    interp = classify_episode(_one_episode(c, d), KB)
    assert interp.output_type is OutputType.A_POSITIVE_CANDIDATE
    assert "precedes first persistent C+ by 2 samples" in interp.candidates[0].ordering_evidence


def test_common_led_bearing_divergence_is_type_b():
    c = [1, 1, 1, 1, 1, 1, 1, 0]
    d = [0, 0, 0, 1, 1, 1, 1, 0]
    interp = classify_episode(_one_episode(c, d), KB)
    assert interp.output_type is OutputType.B_AMBIGUOUS_CANDIDATES
    assert [c.rule_id for c in interp.candidates] == ["FMEA-004", "FMEA-002"]


def test_oil_led_with_bearing_following_ranks_fmea001_first():
    d = [-1, -1, -1, -1, -1, -1, 0]
    c = [0, 0, 0, 1, 1, 1, 0]
    interp = classify_episode(_one_episode(c, d), KB)
    assert interp.output_type is OutputType.B_AMBIGUOUS_CANDIDATES
    assert [c.rule_id for c in interp.candidates] == ["FMEA-001", "FMEA-003"]
    assert "lag qualifier met" in interp.candidates[0].ordering_evidence


def test_weak_oil_only_ranks_fmea003_first():
    interp = classify_episode(_one_episode([0] * 5, [-1, -1, -1, -1, 0]), KB)
    assert [c.rule_id for c in interp.candidates] == ["FMEA-003", "FMEA-001"]
    assert "weak oil-only" in interp.candidates[0].ordering_evidence


def test_common_only_is_type_b_fmea004_first():
    interp = classify_episode(_one_episode([1, 1, 1, 1, 0], [0] * 5), KB)
    assert interp.output_type is OutputType.B_AMBIGUOUS_CANDIDATES
    assert [c.rule_id for c in interp.candidates] == ["FMEA-004", "FMEA-001"]


def test_differential_sign_reversal_is_r5():
    d = [1, 1, 1, -1, -1, -1]
    interp = classify_episode(_one_episode([0] * 6, d), KB)
    assert interp.output_type is OutputType.C_NO_CANDIDATE
    assert "reverses sign" in interp.note


def test_cold_side_common_is_r5():
    interp = classify_episode(_one_episode([-1, -1, -1, -1], [0] * 4), KB)
    assert interp.output_type is OutputType.C_NO_CANDIDATE
    assert "cold-side" in interp.note


def test_relative_warm_inside_cold_episode_is_r5_both_signs():
    cold = [-1, -1, -1, -1, -1, -1]
    for d_sign, phrase in ((1, "oil-cold pattern"), (-1, "bearing-cold pattern")):
        interp = classify_episode(_one_episode(cold, [0, d_sign, d_sign, d_sign, 0, 0]), KB)
        assert interp.output_type is OutputType.C_NO_CANDIDATE
        assert phrase in interp.note


# ------------------------------------------------------------- gate and report


def test_gate_withholds_episodes_and_counts_r_ood():
    c = [1, 1, 1, 1, 1, 1]
    series = _series(c, [0] * 6, eligible=[False] * 6)
    report = interpret_modes([series], KB, MIN)
    assert len(report.interpretations) == 0  # withheld samples never form episodes
    coverage = report.coverage["per_turbine"]["T1"]
    assert coverage["n_withheld"] == 6
    assert coverage["n_withheld_active"] == 6
    assert "R_OOD" in report.coverage["note"]


def test_report_counts_and_versions():
    series = [
        _series([0] * 6, [0, 1, 1, 1, 1, 0], turbine="T1"),
        _series([-1, -1, -1, -1], [0] * 4, turbine="T2"),
    ]
    report = interpret_modes(series, KB, MIN)
    summary = report.as_dict()
    assert summary["modes_version"] == MODES_V2_VERSION
    assert summary["knowledge_base_version"] == KB.ruleset_version
    assert summary["n_episodes"] == 2
    assert summary["episodes_by_type"][OutputType.A_POSITIVE_CANDIDATE.value] == 1
    assert summary["episodes_by_type"][OutputType.C_NO_CANDIDATE.value] == 1
    assert summary["coverage"]["n_samples"] == 10


def test_missing_rule_id_is_a_hard_stop():
    thin = FmeaKnowledgeBase(ruleset_version="9.9.9", rules=())
    with pytest.raises(ConfigError, match="lacks a rule"):
        classify_episode(_one_episode([0] * 5, [0, 1, 1, 1, 0]), thin)


def test_episode_serialization_is_complete():
    interp = classify_episode(_one_episode([0] * 5, [0, 1, 1, 1, 0]), KB)
    payload = interp.as_dict()
    assert payload["output_type"] == "A_positive_candidate"
    assert payload["candidates"][0]["rule_id"] == "FMEA-002"
    assert payload["runs"] == [{"mode": "D", "sign": 1, "length": 3, "start_index": 1}]
