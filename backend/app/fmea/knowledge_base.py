"""Structured FMEA knowledge base (M-25; PROJECT.md §26; LOCKED-03).

Rules live in YAML, never in scattered if/else. Loading schema-validates
every rule, stamps the ruleset version, and enforces two policies at the
door:

- Guard 7: an unvalidated rule carries the ``UNVALIDATED RULE`` banner into
  every match result; the ``validated`` flag flips only through a
  docs/DECISIONS.md ADR-005 sign-off citing the specific literature source,
  so a rule with ``validated: true`` and no source is rejected at load.
- ADR-008 mandatory caveat: every rule's rationale must carry the overlap
  caveat (Feng et al., 2013) — three of five gearbox failure modes share
  the oil-temperature signature, so differentiation rests on the
  coordinated pattern, never a single residual.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from app.core.errors import FmeaRuleError
from app.detection.coordinated import CoordinatedState

#: Guard 7 banner, propagated into every artifact touching an unvalidated
#: rule (PROJECT.md §26, §33).
UNVALIDATED_RULE_BANNER = (
    "UNVALIDATED RULE — PRELIMINARY — DEMONSTRATION ONLY — NOT SCIENTIFICALLY VALIDATED"
)

#: The ADR-008 mandatory overlap caveat, checked verbatim by citation key.
OVERLAP_CAVEAT_KEY = "Feng et al., 2013"

_SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class PatternState(StrEnum):
    """Required signal state in a rule pattern ({-1, 0, +1} vocabulary)."""

    HIGH = "high"
    LOW = "low"
    NORMAL = "normal"
    ANY = "any"


#: PatternState → the discrete states it accepts.
_ACCEPTED: dict[PatternState, tuple[int, ...]] = {
    PatternState.HIGH: (1,),
    PatternState.LOW: (-1,),
    PatternState.NORMAL: (0,),
    PatternState.ANY: (-1, 0, 1),
}


class _SignalRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: PatternState


class FmeaRule(BaseModel):
    """One residual-pattern → candidate-mechanism rule (PROJECT.md §26)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    mechanism: str
    residual_pattern: dict[str, _SignalRequirement]
    qualifiers: tuple[str, ...] = ()
    confidence: str = "preliminary"
    rationale: str
    source: str
    validated: bool = False

    @property
    def signals(self) -> tuple[str, ...]:
        return tuple(sorted(self.residual_pattern))

    def instantiable(self, available_signals: set[str]) -> bool:
        """Whether every pattern signal exists in the modelled channel set
        (ADR-008 dependency note: subsetting is a data matter, not a rule
        change)."""
        return set(self.residual_pattern) <= available_signals


@dataclass(frozen=True)
class RuleAssessment:
    """One rule assessed against one coordinated state.

    ``supporting`` are explicit requirements met; ``violated`` are explicit
    requirements contradicted by an observed state. ANY-requirements support
    presence only and can never be violated.
    """

    rule: FmeaRule
    supporting: tuple[str, ...]
    violated: tuple[str, ...]
    label: str

    @property
    def exact_match(self) -> bool:
        return not self.violated


class FmeaKnowledgeBase:
    """Versioned rule set with the coordinated-state match primitive."""

    def __init__(self, ruleset_version: str, rules: tuple[FmeaRule, ...]) -> None:
        self.ruleset_version = ruleset_version
        self.rules = rules

    @classmethod
    def load(cls, path: Path) -> FmeaKnowledgeBase:
        try:
            raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise FmeaRuleError("Ruleset file unreadable", path=str(path)) from exc
        except yaml.YAMLError as exc:
            raise FmeaRuleError("Ruleset is not valid YAML", path=str(path)) from exc
        if not isinstance(raw, dict):
            raise FmeaRuleError("Ruleset root must be a mapping", path=str(path))

        version = str(raw.get("ruleset_version", ""))
        if not _SEMVER_RE.match(version):
            raise FmeaRuleError("ruleset_version must be valid semver", version=version)
        entries = raw.get("rules")
        if not isinstance(entries, list) or not entries:
            raise FmeaRuleError("Ruleset declares no rules", path=str(path))

        rules: list[FmeaRule] = []
        for entry in entries:
            try:
                rule = FmeaRule.model_validate(entry)
            except ValidationError as exc:
                raise FmeaRuleError("Malformed rule", detail=str(exc)) from exc
            _enforce_policies(rule)
            rules.append(rule)
        ids = [rule.id for rule in rules]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise FmeaRuleError("Duplicate rule ids", duplicates=duplicates)
        return cls(ruleset_version=version, rules=tuple(rules))

    def assess(self, state: CoordinatedState) -> list[RuleAssessment]:
        """Assess every instantiable rule against one coordinated state.

        A rule is assessed only when every pattern signal is present (an
        explicit gap makes coordination undefined, never assumed normal).
        Returns assessments with at least one supporting signal; exact
        matches carry no violations.
        """
        available = {signal for signal, value in state.vector.items() if value is not None}
        assessments: list[RuleAssessment] = []
        for rule in self.rules:
            if not rule.instantiable(available):
                continue
            supporting: list[str] = []
            violated: list[str] = []
            for signal, requirement in rule.residual_pattern.items():
                observed = state.vector[signal]
                assert observed is not None  # instantiable() guarantees presence
                if observed in _ACCEPTED[requirement.state]:
                    if requirement.state is not PatternState.ANY:
                        supporting.append(signal)
                else:
                    violated.append(signal)
            if supporting:
                assessments.append(
                    RuleAssessment(
                        rule=rule,
                        supporting=tuple(sorted(supporting)),
                        violated=tuple(sorted(violated)),
                        label="" if rule.validated else UNVALIDATED_RULE_BANNER,
                    )
                )
        return assessments

    def not_instantiable(self, available_signals: set[str]) -> tuple[str, ...]:
        """Rule ids whose pattern signals are not all modelled (transparency)."""
        return tuple(rule.id for rule in self.rules if not rule.instantiable(available_signals))


def _enforce_policies(rule: FmeaRule) -> None:
    if rule.validated and not rule.source.strip():
        raise FmeaRuleError(
            "A validated rule must cite its literature source "
            "(sign-off policy, PROJECT.md §26 / ADR-005)",
            rule=rule.id,
        )
    if OVERLAP_CAVEAT_KEY not in rule.rationale:
        raise FmeaRuleError(
            "Rule rationale omits the mandatory overlap caveat "
            "(ADR-008: three of five gearbox failure modes share the "
            "oil-temperature signature)",
            rule=rule.id,
        )
    if not rule.residual_pattern:
        raise FmeaRuleError("Rule declares no residual pattern", rule=rule.id)


def default_ruleset_path() -> Path:
    """The packaged initial rule base (ADR-008)."""
    return Path(__file__).parent / "rulesets" / "initial_v1.yaml"
