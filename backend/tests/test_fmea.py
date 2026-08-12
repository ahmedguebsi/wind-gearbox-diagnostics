"""M-25/M-26 tests: FMEA knowledge base, Guard 7, interpretation engine.

Coordinated-state fixtures are SYNTHETIC TEST DATA — NOT VALID THESIS
EVIDENCE — they exercise rule-match mechanics only (LOCKED-08). The real
EVENT-001 rendering for Chapter 5 comes from the pipeline on Kelmarsh data.
"""

import pandas as pd
import pytest
import yaml

from app.core.errors import FmeaRuleError
from app.detection.coordinated import CoordinatedState
from app.fmea.interpreter import (
    NO_CANDIDATE_NOTE,
    ConfidenceCategory,
    FmeaInterpreter,
)
from app.fmea.knowledge_base import (
    OVERLAP_CAVEAT_KEY,
    UNVALIDATED_RULE_BANNER,
    FmeaKnowledgeBase,
    default_ruleset_path,
)

OIL = "gearbox_oil_temperature"
BEARING = "gearbox_bearing_temperature"


def _state(
    vector: dict[str, int | None],
    continuous: dict[str, float | None] | None = None,
    turbine: str = "Kelmarsh 1",
    stamp: str = "2019-02-17 14:20:00",
) -> CoordinatedState:
    if continuous is None:
        continuous = {k: None if v is None else float(v) * 3.0 for k, v in vector.items()}
    return CoordinatedState(
        timestamp_utc=pd.Timestamp(stamp, tz="UTC"),
        turbine=turbine,
        vector=vector,
        continuous=continuous,
    )


@pytest.fixture(scope="module")
def kb() -> FmeaKnowledgeBase:
    return FmeaKnowledgeBase.load(default_ruleset_path())


class TestRulesetLoading:
    def test_initial_ruleset_is_the_adr008_five(self, kb):
        assert kb.ruleset_version == "1.0.0"
        assert [r.id for r in kb.rules] == [f"FMEA-{i:03d}" for i in range(1, 6)]
        assert all(r.validated is False for r in kb.rules)
        assert all(OVERLAP_CAVEAT_KEY in r.rationale for r in kb.rules)
        assert all(r.source.strip() for r in kb.rules)

    def test_malformed_yaml_rejected(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text("rules: [unclosed", encoding="utf-8")
        with pytest.raises(FmeaRuleError):
            FmeaKnowledgeBase.load(path)

    def _write_ruleset(self, tmp_path, mutate):
        payload = yaml.safe_load(default_ruleset_path().read_text(encoding="utf-8"))
        mutate(payload)
        path = tmp_path / "ruleset.yaml"
        path.write_text(yaml.safe_dump(payload), encoding="utf-8")
        return path

    def test_validated_true_without_source_rejected(self, tmp_path):
        """Sign-off enforcement at load (M-25 acceptance 1)."""

        def mutate(payload):
            payload["rules"][0]["validated"] = True
            payload["rules"][0]["source"] = "  "

        with pytest.raises(FmeaRuleError, match="sign-off"):
            FmeaKnowledgeBase.load(self._write_ruleset(tmp_path, mutate))

    def test_missing_overlap_caveat_rejected(self, tmp_path):
        def mutate(payload):
            payload["rules"][0]["rationale"] = "no caveat here"

        with pytest.raises(FmeaRuleError, match="caveat"):
            FmeaKnowledgeBase.load(self._write_ruleset(tmp_path, mutate))

    def test_duplicate_rule_ids_rejected(self, tmp_path):
        def mutate(payload):
            payload["rules"][1]["id"] = payload["rules"][0]["id"]

        with pytest.raises(FmeaRuleError, match="Duplicate"):
            FmeaKnowledgeBase.load(self._write_ruleset(tmp_path, mutate))

    def test_unknown_pattern_state_rejected(self, tmp_path):
        def mutate(payload):
            payload["rules"][0]["residual_pattern"][OIL] = {"state": "very_high"}

        with pytest.raises(FmeaRuleError, match="Malformed"):
            FmeaKnowledgeBase.load(self._write_ruleset(tmp_path, mutate))

    def test_bad_semver_rejected(self, tmp_path):
        def mutate(payload):
            payload["ruleset_version"] = "1.0"

        with pytest.raises(FmeaRuleError, match="semver"):
            FmeaKnowledgeBase.load(self._write_ruleset(tmp_path, mutate))


class TestMatching:
    def test_high_high_matches_and_ranks(self, kb):
        assessments = kb.assess(_state({OIL: 1, BEARING: 1}))
        by_id = {a.rule.id: a for a in assessments}
        assert set(by_id) == {"FMEA-001", "FMEA-002", "FMEA-003", "FMEA-004"}
        assert by_id["FMEA-004"].exact_match
        assert by_id["FMEA-004"].supporting == (BEARING, OIL)
        assert by_id["FMEA-003"].violated == (BEARING,)

    def test_unvalidated_label_propagates(self, kb):
        assessments = kb.assess(_state({OIL: 1, BEARING: 1}))
        assert all(a.label == UNVALIDATED_RULE_BANNER for a in assessments)

    def test_low_low_matches_nothing(self, kb):
        assert kb.assess(_state({OIL: -1, BEARING: -1})) == []

    def test_explicit_gap_makes_rules_uninstantiable(self, kb):
        assessments = kb.assess(_state({OIL: 1, BEARING: None}))
        assert assessments == []
        assert set(kb.not_instantiable({OIL})) == {f"FMEA-{i:03d}" for i in range(1, 6)}

    def test_generator_rule_not_instantiable_with_current_targets(self, kb):
        assert kb.not_instantiable({OIL, BEARING}) == ("FMEA-005",)


class TestInterpreter:
    def test_ranking_is_deterministic(self, kb):
        events = FmeaInterpreter(kb).interpret([_state({OIL: 1, BEARING: 1})])
        (event,) = events
        assert event.matched_rule_ids == ("FMEA-004", "FMEA-001", "FMEA-002", "FMEA-003")
        assert event.candidates[0].confidence_category is (ConfidenceCategory.PLAUSIBLE_PRELIMINARY)
        assert event.candidates[-1].confidence_category is ConfidenceCategory.WEAK
        assert event.candidates[-1].contradictory_evidence

    def test_confidence_enum_has_no_confirmed_member(self):
        """ARCHITECTURE §5.5: "confirmed" is unrepresentable."""
        assert all("confirm" not in member.value.lower() for member in ConfidenceCategory)

    def test_normal_states_produce_no_events(self, kb):
        assert FmeaInterpreter(kb).interpret([_state({OIL: 0, BEARING: 0})]) == []

    def test_persistence_counts_consecutive_anomalous_states(self, kb):
        states = [
            _state({OIL: 0, BEARING: 0}, stamp="2019-02-17 14:00:00"),
            _state({OIL: 1, BEARING: 1}, stamp="2019-02-17 14:10:00"),
            _state({OIL: 1, BEARING: 1}, stamp="2019-02-17 14:20:00"),
            _state({OIL: 0, BEARING: 0}, stamp="2019-02-17 14:30:00"),
            _state({OIL: 1, BEARING: 0}, stamp="2019-02-17 14:40:00"),
        ]
        events = FmeaInterpreter(kb).interpret(states)
        assert [e.persistence for e in events] == [1, 2, 1]

    def test_no_candidate_is_explicit_never_silence(self, kb):
        events = FmeaInterpreter(kb).interpret([_state({OIL: -1, BEARING: -1})])
        (event,) = events
        assert event.candidates == ()
        assert NO_CANDIDATE_NOTE in event.render()

    def test_traceability_serialized(self, kb):
        (event,) = FmeaInterpreter(kb).interpret([_state({OIL: 1, BEARING: 1})])
        payload = event.as_dict()
        assert payload["ruleset_version"] == "1.0.0"
        assert payload["matched_rule_ids"][0] == "FMEA-004"
        assert payload["not_instantiable_rule_ids"] == ["FMEA-005"]
        assert payload["candidates"][0]["label"] == UNVALIDATED_RULE_BANNER


class TestOperatorRendering:
    """The Chapter 5 worked-example format (M-26; SYNTHETIC fixture values)."""

    def test_render_carries_everything_an_operator_needs(self, kb):
        state = _state(
            {OIL: 1, BEARING: 1},
            continuous={OIL: 3.42, BEARING: 2.87},
            stamp="2019-02-17 14:20:00",
        )
        states = [state] * 36  # sustained excursion → persistence 36
        rendered = FmeaInterpreter(kb).interpret(states)[-1].render()
        assert "DIAGNOSTIC EVENT — Kelmarsh 1 — 2019-02-17 14:20 UTC" in rendered
        assert "Persistence: 36 consecutive 10-min samples" in rendered
        assert f"{OIL} HIGH (EWMA +3.42)" in rendered
        assert "1. lubrication_system_degradation  [rule FMEA-004]" in rendered
        assert UNVALIDATED_RULE_BANNER in rendered
        assert "Supporting:" in rendered and "Contradictory:" in rendered
        assert OVERLAP_CAVEAT_KEY in rendered
        assert "Ruleset: 1.0.0" in rendered
        assert "Not assessable with modelled channels: FMEA-005" in rendered

    def test_render_never_says_confirmed(self, kb):
        (event,) = FmeaInterpreter(kb).interpret([_state({OIL: 1, BEARING: 1})])
        assert "confirmed" not in event.render().lower()
