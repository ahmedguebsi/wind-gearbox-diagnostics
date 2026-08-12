"""FMEA interpretation engine (M-26; LOCKED-03; PROJECT.md §26).

Maps coordinated residual patterns + persistence to :class:`DiagnosticEvent`
objects carrying ranked :class:`CandidateMechanism` hypotheses. Hypothesis
language only: "confirmed" is unrepresentable — the confidence enum has no
such member, and the operator rendering never emits the word.

An anomalous state that matches no rule yields an explicit
no-candidate-mechanism event, never silence. Every event serializes its
matched rule ids and the ruleset version for traceability (M-26 acceptance
2), and :meth:`DiagnosticEvent.render` produces the operator view — the
format the thesis Chapter 5 worked example uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import pandas as pd

from app.detection.coordinated import CoordinatedState
from app.fmea.knowledge_base import FmeaKnowledgeBase, RuleAssessment

#: State value → operator vocabulary.
_STATE_WORDS = {1: "HIGH", 0: "normal", -1: "LOW"}

NO_CANDIDATE_NOTE = (
    "No candidate mechanism: the anomalous pattern matched no FMEA rule. "
    "This is reported explicitly — an unexplained anomaly is a finding, not "
    "an absence."
)


class ConfidenceCategory(StrEnum):
    """Hypothesis grades. There is deliberately NO confirmed/definite member
    (ARCHITECTURE.md §5.5): candidate mechanisms are hypotheses."""

    PLAUSIBLE_PRELIMINARY = "plausible_preliminary"
    WEAK = "weak"


@dataclass(frozen=True)
class CandidateMechanism:
    """One ranked hypothesis with its evidence (PROJECT.md §26)."""

    mechanism: str
    rule_id: str
    confidence_category: ConfidenceCategory
    supporting_evidence: tuple[str, ...]
    contradictory_evidence: tuple[str, ...]
    rationale: str
    validated: bool
    label: str  # Guard 7 banner when unvalidated, "" otherwise

    def as_dict(self) -> dict[str, Any]:
        return {
            "mechanism": self.mechanism,
            "rule_id": self.rule_id,
            "confidence_category": self.confidence_category.value,
            "supporting_evidence": list(self.supporting_evidence),
            "contradictory_evidence": list(self.contradictory_evidence),
            "rationale": self.rationale,
            "validated": self.validated,
            "label": self.label,
        }


@dataclass(frozen=True)
class DiagnosticEvent:
    """One anomalous coordinated state, interpreted."""

    timestamp_utc: pd.Timestamp
    turbine: str
    pattern: dict[str, int | None]
    continuous: dict[str, float | None]
    severity: float
    persistence: int
    candidates: tuple[CandidateMechanism, ...]
    matched_rule_ids: tuple[str, ...]
    not_instantiable_rule_ids: tuple[str, ...]
    ruleset_version: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp_utc": self.timestamp_utc.isoformat(),
            "turbine": self.turbine,
            "pattern": dict(self.pattern),
            "continuous": dict(self.continuous),
            "severity": self.severity,
            "persistence": self.persistence,
            "candidates": [c.as_dict() for c in self.candidates],
            "matched_rule_ids": list(self.matched_rule_ids),
            "not_instantiable_rule_ids": list(self.not_instantiable_rule_ids),
            "ruleset_version": self.ruleset_version,
        }

    def render(self) -> str:
        """The operator view: pattern, ranked hypotheses with Guard 7
        banners, evidence for and against, confidence, rationale."""
        lines = [
            f"DIAGNOSTIC EVENT — {self.turbine} — {self.timestamp_utc:%Y-%m-%d %H:%M} UTC",
            (
                f"Severity: max |EWMA| = {self.severity:.2f} sigma"
                f"  |  Persistence: {self.persistence} consecutive 10-min samples"
            ),
            "Pattern: " + "; ".join(self._pattern_words()),
        ]
        if not self.candidates:
            lines.append(NO_CANDIDATE_NOTE)
        else:
            lines.append("Candidate mechanisms (hypotheses, ranked):")
            for rank, candidate in enumerate(self.candidates, start=1):
                lines.append(
                    f"  {rank}. {candidate.mechanism}  [rule {candidate.rule_id}]"
                    f"  —  {candidate.confidence_category.value}"
                )
                if candidate.label:
                    lines.append(f"     ** {candidate.label} **")
                lines.append(
                    "     Supporting: " + ("; ".join(candidate.supporting_evidence) or "none")
                )
                lines.append(
                    "     Contradictory: " + ("; ".join(candidate.contradictory_evidence) or "none")
                )
                lines.append(f"     Rationale: {candidate.rationale.strip()}")
        lines.append(f"Ruleset: {self.ruleset_version}")
        if self.not_instantiable_rule_ids:
            lines.append(
                "Not assessable with modelled channels: "
                + ", ".join(self.not_instantiable_rule_ids)
            )
        return "\n".join(lines)

    def _pattern_words(self) -> list[str]:
        words = []
        for signal in sorted(self.pattern):
            value = self.pattern[signal]
            if value is None:
                words.append(f"{signal} (no observation)")
                continue
            ewma = self.continuous.get(signal)
            ewma_text = "" if ewma is None else f" (EWMA {ewma:+.2f})"
            words.append(f"{signal} {_STATE_WORDS[value]}{ewma_text}")
        return words


class FmeaInterpreter:
    """Coordinated states → diagnostic events, through the rule base ONLY
    (LOCKED-03: no statistical attribution substitutes or supplements)."""

    def __init__(self, knowledge_base: FmeaKnowledgeBase) -> None:
        self.knowledge_base = knowledge_base

    def interpret(self, states: list[CoordinatedState]) -> list[DiagnosticEvent]:
        """One DiagnosticEvent per anomalous coordinated state.

        Persistence counts consecutive anomalous states per turbine up to
        and including the current one. Candidate ranking is deterministic:
        exact pattern matches first, then more supporting signals, then
        rule id.
        """
        events: list[DiagnosticEvent] = []
        run_lengths: dict[str, int] = {}
        for state in states:
            anomalous = any(v not in (0, None) for v in state.vector.values())
            run_lengths[state.turbine] = run_lengths.get(state.turbine, 0) + 1 if anomalous else 0
            if not anomalous:
                continue
            events.append(self._interpret_state(state, run_lengths[state.turbine]))
        return events

    def _interpret_state(self, state: CoordinatedState, persistence: int) -> DiagnosticEvent:
        assessments = self.knowledge_base.assess(state)
        ranked = sorted(
            assessments,
            key=lambda a: (len(a.violated), -len(a.supporting), a.rule.id),
        )
        candidates = tuple(self._candidate(state, a) for a in ranked)
        available = {signal for signal, value in state.vector.items() if value is not None}
        severity = max((abs(v) for v in state.continuous.values() if v is not None), default=0.0)
        return DiagnosticEvent(
            timestamp_utc=state.timestamp_utc,
            turbine=state.turbine,
            pattern=dict(state.vector),
            continuous=dict(state.continuous),
            severity=severity,
            persistence=persistence,
            candidates=candidates,
            matched_rule_ids=tuple(a.rule.id for a in ranked),
            not_instantiable_rule_ids=self.knowledge_base.not_instantiable(available),
            ruleset_version=self.knowledge_base.ruleset_version,
        )

    @staticmethod
    def _candidate(state: CoordinatedState, assessment: RuleAssessment) -> CandidateMechanism:
        def _describe(signal: str, met: bool) -> str:
            required = assessment.rule.residual_pattern[signal].state.value
            observed = state.vector[signal]
            word = _STATE_WORDS[observed] if observed is not None else "no observation"
            ewma = state.continuous.get(signal)
            ewma_text = "" if ewma is None else f", EWMA {ewma:+.2f}"
            relation = "matches" if met else "contradicts"
            return f"{signal} is {word}{ewma_text} — {relation} required '{required}'"

        supporting = tuple(_describe(s, True) for s in assessment.supporting)
        contradictory = tuple(_describe(s, False) for s in assessment.violated)
        confidence = (
            ConfidenceCategory.PLAUSIBLE_PRELIMINARY
            if assessment.exact_match
            else ConfidenceCategory.WEAK
        )
        return CandidateMechanism(
            mechanism=assessment.rule.mechanism,
            rule_id=assessment.rule.id,
            confidence_category=confidence,
            supporting_evidence=supporting,
            contradictory_evidence=contradictory,
            rationale=assessment.rule.rationale,
            validated=assessment.rule.validated,
            label=assessment.label,
        )
