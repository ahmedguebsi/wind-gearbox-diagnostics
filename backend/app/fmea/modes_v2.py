"""Ruleset v2: mode-coordinate FMEA interpretation (ADR-050; EXPLORATORY).

POST-HOC METHODOLOGICAL REFINEMENT, stated openly: this layer was introduced
after ADR-035/arm A6 measured the raw channels at r = 0.93-0.95 and LIM-030
recorded that the v1 instantaneous state match cannot discriminate mechanisms
there. Its results are exploratory and are always reported AFTER the
pre-registered v1 outcome (ADR-050 chronology conditions).

What it does — and does not — change. The FMEA taxonomy is v1's, loaded from
the same YAML knowledge base; no new mechanisms exist here. The change is the
state representation and the match unit: per-channel standardized residuals
are rotated into a common mode C = (z_bearing + z_oil)/sqrt(2) and a
differential mode D = (z_bearing - z_oil)/sqrt(2) (``app.residuals.modes``),
and the v1 signatures — including the temporal qualifiers v1 carried as text
— are matched MECHANICALLY over EPISODES of persistent mode exceedance:

- D+ persistent (bearing hot relative to its own oil bath) is the bearing-led
  signature of FMEA-002; "bearing leads" becomes "first persistent D+ run
  precedes any persistent C+ run" (ADR-050 frozen spec, condition c).
- D- persistent (oil-led) is the shared signature of FMEA-001 and FMEA-003 —
  the ADR-008 overlap caveat made mechanical: both are always reported
  together, ranked by whether the bearing followed (a later common elevation
  supports FMEA-001's lag qualifier; its absence favours FMEA-003's weak
  oil-only form).
- C+ persistent without any persistent D is FMEA-004's "broad simultaneous"
  signature; FMEA-001 is retained as a second candidate because a lag shorter
  than the 10-minute sampling cannot be excluded.
- Patterns matching no signature (cold-side episodes, differential sign
  reversals) yield the R5 abstention: "no gearbox-consistent thermal
  candidate" — an explicit output, never silence (M-26 acceptance 2).

The ADR-049 eligibility gate applies at THIS layer, not at detection:
ineligible samples (operating condition outside the NBM's fitted support)
cannot start, extend, or bridge a persistent run or an episode, and a
would-be-active ineligible sample is counted as WITHHELD (R_OOD) — a
different abstention in kind from R5. Detection artefacts upstream are
untouched (ADR-049 scope: RQ3 only).

Binding caution (ADR-050): a positive differential is not per se a bearing
fault — sensor bias, thermal-lag differences, target-specific model error and
operating transitions all produce it. Every bearing-led interpretation
carries this caution in its note.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np
import pandas as pd

from app.core.errors import ConfigError
from app.fmea.knowledge_base import (
    UNVALIDATED_RULE_BANNER,
    FmeaKnowledgeBase,
    FmeaRule,
)

#: Version of THIS interpretation layer; the mechanism taxonomy stays the
#: loaded knowledge base's ``ruleset_version``.
MODES_V2_VERSION = "2.0.0"

#: ADR-049 / review §10 fixed wordings.
R5_NOTE = (
    "No gearbox-consistent thermal candidate (R5): the mode pattern matches no FMEA signature."
)
R_OOD_NOTE = (
    "Interpretation withheld: operating condition outside the NBM's fitted support (R_OOD)."
)
BEARING_LED_CAUTION = (
    "ADR-050 caution: a positive differential is not per se a bearing fault — "
    "sensor bias, thermal-lag differences, target-specific model error and "
    "operating transitions also produce it."
)


class OutputType(StrEnum):
    """The ADR-050 output vocabulary (review §20). R_OOD is coverage, not an
    episode type: withheld samples never form episodes."""

    A_POSITIVE_CANDIDATE = "A_positive_candidate"
    B_AMBIGUOUS_CANDIDATES = "B_ambiguous_candidates"
    C_NO_CANDIDATE = "C_no_candidate"


@dataclass(frozen=True)
class ModeStateSeries:
    """Aligned per-turbine mode streams: discrete states, EWMA values, gate."""

    turbine: str
    timestamps: pd.Series
    c_states: np.ndarray
    d_states: np.ndarray
    c_values: np.ndarray
    d_values: np.ndarray
    eligible: np.ndarray

    def __post_init__(self) -> None:
        n = len(self.timestamps)
        arrays = (self.c_states, self.d_states, self.c_values, self.d_values, self.eligible)
        if any(len(a) != n for a in arrays):
            raise ConfigError("ModeStateSeries arrays are not aligned", turbine=self.turbine)


@dataclass(frozen=True)
class PersistentRun:
    """A maximal same-sign run of >= min_samples eligible exceedances."""

    mode: str  # "C" | "D"
    sign: int  # +1 | -1
    start_index: int
    end_index: int  # inclusive

    @property
    def length(self) -> int:
        return self.end_index - self.start_index + 1


@dataclass(frozen=True)
class ModeEpisode:
    """A maximal contiguous stretch of persistent-run activity (either mode)."""

    turbine: str
    start_index: int
    end_index: int  # inclusive
    start_utc: pd.Timestamp
    end_utc: pd.Timestamp
    n_samples: int
    runs: tuple[PersistentRun, ...]
    max_abs_c: float
    max_abs_d: float

    def first_run_start(self, mode: str, sign: int) -> int | None:
        starts = [r.start_index for r in self.runs if r.mode == mode and r.sign == sign]
        return min(starts) if starts else None

    def has(self, mode: str, sign: int) -> bool:
        return self.first_run_start(mode, sign) is not None


@dataclass(frozen=True)
class ModeCandidate:
    """One ranked hypothesis, carrying the v1 rule's identity and Guard 7."""

    rank: int
    rule_id: str
    mechanism: str
    ordering_evidence: str
    rationale: str
    validated: bool
    label: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "rule_id": self.rule_id,
            "mechanism": self.mechanism,
            "ordering_evidence": self.ordering_evidence,
            "validated": self.validated,
            "label": self.label,
        }


@dataclass(frozen=True)
class EpisodeInterpretation:
    episode: ModeEpisode
    output_type: OutputType
    candidates: tuple[ModeCandidate, ...]
    note: str

    def as_dict(self) -> dict[str, Any]:
        e = self.episode
        return {
            "turbine": e.turbine,
            "start_utc": e.start_utc.isoformat(),
            "end_utc": e.end_utc.isoformat(),
            "n_samples": e.n_samples,
            "max_abs_c_ewma": round(e.max_abs_c, 4),
            "max_abs_d_ewma": round(e.max_abs_d, 4),
            "runs": [
                {"mode": r.mode, "sign": r.sign, "length": r.length, "start_index": r.start_index}
                for r in e.runs
            ],
            "output_type": self.output_type.value,
            "candidates": [c.as_dict() for c in self.candidates],
            "note": self.note,
        }


@dataclass(frozen=True)
class ModesInterpretationReport:
    """Every interpreted episode plus the R_OOD coverage census."""

    interpretations: tuple[EpisodeInterpretation, ...]
    coverage: dict[str, Any]
    knowledge_base_version: str
    modes_version: str
    persistence_min_samples: int

    def as_dict(self) -> dict[str, Any]:
        counts: dict[str, int] = {t.value: 0 for t in OutputType}
        for interpretation in self.interpretations:
            counts[interpretation.output_type.value] += 1
        return {
            "modes_version": self.modes_version,
            "knowledge_base_version": self.knowledge_base_version,
            "persistence_min_samples": self.persistence_min_samples,
            "n_episodes": len(self.interpretations),
            "episodes_by_type": counts,
            "coverage": dict(self.coverage),
        }


def persistent_runs(
    states: np.ndarray, eligible: np.ndarray, min_samples: int, mode: str
) -> list[PersistentRun]:
    """Maximal same-sign runs of length >= min_samples, eligible samples only.

    An ineligible sample breaks a run (ADR-049: withheld samples cannot
    start, extend, or bridge persistence), exactly as a normal-state sample
    does.
    """
    if min_samples < 1:
        raise ConfigError("persistence_min_samples must be >= 1", min_samples=min_samples)
    runs: list[PersistentRun] = []
    current_sign = 0
    start = 0
    for i in range(len(states) + 1):
        sign = int(states[i]) if i < len(states) and bool(eligible[i]) else 0
        if sign == current_sign:
            continue
        if current_sign != 0 and i - start >= min_samples:
            runs.append(
                PersistentRun(mode=mode, sign=current_sign, start_index=start, end_index=i - 1)
            )
        current_sign = sign
        start = i
    return runs


def find_episodes(series: ModeStateSeries, min_samples: int) -> list[ModeEpisode]:
    """Maximal contiguous stretches covered by persistent runs in either mode."""
    runs = persistent_runs(series.c_states, series.eligible, min_samples, "C") + persistent_runs(
        series.d_states, series.eligible, min_samples, "D"
    )
    if not runs:
        return []
    active = np.zeros(len(series.timestamps), dtype=bool)
    for run in runs:
        active[run.start_index : run.end_index + 1] = True

    episodes: list[ModeEpisode] = []
    i = 0
    n = len(active)
    while i < n:
        if not active[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and active[j + 1]:
            j += 1
        members = tuple(
            sorted(
                (r for r in runs if r.start_index <= j and r.end_index >= i),
                key=lambda r: (r.start_index, r.mode),
            )
        )
        episodes.append(
            ModeEpisode(
                turbine=series.turbine,
                start_index=i,
                end_index=j,
                start_utc=pd.Timestamp(series.timestamps.iloc[i]),
                end_utc=pd.Timestamp(series.timestamps.iloc[j]),
                n_samples=j - i + 1,
                runs=members,
                max_abs_c=float(np.max(np.abs(series.c_values[i : j + 1]))),
                max_abs_d=float(np.max(np.abs(series.d_values[i : j + 1]))),
            )
        )
        i = j + 1
    return episodes


def _rule(kb: FmeaKnowledgeBase, rule_id: str) -> FmeaRule:
    for rule in kb.rules:
        if rule.id == rule_id:
            return rule
    raise ConfigError("Knowledge base lacks a rule ruleset v2 requires", rule_id=rule_id)


def _candidate(kb: FmeaKnowledgeBase, rule_id: str, rank: int, evidence: str) -> ModeCandidate:
    rule = _rule(kb, rule_id)
    return ModeCandidate(
        rank=rank,
        rule_id=rule.id,
        mechanism=rule.mechanism,
        ordering_evidence=evidence,
        rationale=rule.rationale,
        validated=rule.validated,
        label="" if rule.validated else UNVALIDATED_RULE_BANNER,
    )


def classify_episode(episode: ModeEpisode, kb: FmeaKnowledgeBase) -> EpisodeInterpretation:
    """The ADR-050 frozen decision tree over one episode's persistent runs.

    Deterministic, no tunables beyond persistence: signatures are decided by
    which persistent runs exist and by first-run ordering ("X leads Y" means
    X's first persistent run starts at least one sample before Y's).
    """
    d_pos, d_neg = episode.has("D", 1), episode.has("D", -1)
    c_pos, c_neg = episode.has("C", 1), episode.has("C", -1)

    def _r5(reason: str) -> EpisodeInterpretation:
        return EpisodeInterpretation(
            episode=episode,
            output_type=OutputType.C_NO_CANDIDATE,
            candidates=(),
            note=f"{R5_NOTE} {reason}",
        )

    # 1. A differential sign reversal inside one episode fits no v1 signature.
    if d_pos and d_neg:
        return _r5("The differential mode reverses sign within the episode.")

    # 2. Bearing-led branch: persistent D+ (bearing hot relative to its oil).
    if d_pos:
        if c_neg and not c_pos:
            # Overall cold with the bearing merely warm RELATIVE to it means
            # the oil channel is the one that is low — an oil-cold pattern no
            # gearbox-heating rule describes.
            return _r5("D+ inside a common-mode COLD episode is an oil-cold pattern.")
        first_d = episode.first_run_start("D", 1)
        first_c = episode.first_run_start("C", 1)
        assert first_d is not None
        if first_c is None or first_d < first_c:
            evidence = (
                "persistent D+ with no common elevation (early bearing-led form)"
                if first_c is None
                else (
                    "first persistent D+ precedes first persistent C+ by "
                    f"{first_c - first_d} samples"
                )
            )
            return EpisodeInterpretation(
                episode=episode,
                output_type=OutputType.A_POSITIVE_CANDIDATE,
                candidates=(_candidate(kb, "FMEA-002", 1, evidence),),
                note="Bearing-led thermal pattern; FMEA-002-consistent. " + BEARING_LED_CAUTION,
            )
        return EpisodeInterpretation(
            episode=episode,
            output_type=OutputType.B_AMBIGUOUS_CANDIDATES,
            candidates=(
                _candidate(kb, "FMEA-004", 1, "persistent C+ precedes the differential run"),
                _candidate(kb, "FMEA-002", 2, "persistent D+ present but common-led"),
            ),
            note=(
                "Common-mode onset with later bearing divergence; the thermal "
                "evidence cannot rank these further. " + BEARING_LED_CAUTION
            ),
        )

    # 3. Oil-led branch: persistent D- (oil hot relative to the bearing).
    if d_neg:
        if c_neg and not c_pos:
            # Overall cold with the oil merely warm RELATIVE to it means the
            # bearing channel is the one that is low — a bearing-cold pattern
            # no gearbox-heating rule describes (EVENT-001's matched
            # excursion direction lands here under v2 vocabulary).
            return _r5("D- inside a common-mode COLD episode is a bearing-cold pattern.")
        followed = "a later common elevation shows the bearing following (lag qualifier met)"
        oil_only = "no common elevation follows (weak oil-only form)"
        ranked = ("FMEA-001", "FMEA-003") if c_pos else ("FMEA-003", "FMEA-001")
        return EpisodeInterpretation(
            episode=episode,
            output_type=OutputType.B_AMBIGUOUS_CANDIDATES,
            candidates=(
                _candidate(kb, ranked[0], 1, followed if c_pos else oil_only),
                _candidate(kb, ranked[1], 2, "shared oil-led signature (ADR-008 overlap caveat)"),
            ),
            note=(
                "Oil-led thermal pattern consistent with FMEA-001/FMEA-003; the "
                "available thermal evidence cannot discriminate further."
            ),
        )

    # 4. Common mode only. C+ is FMEA-004's broad-simultaneous signature;
    #    FMEA-001 is retained because an oil lead shorter than one 10-minute
    #    sample cannot be excluded. C- only is a cold-side episode.
    if c_pos:
        return EpisodeInterpretation(
            episode=episode,
            output_type=OutputType.B_AMBIGUOUS_CANDIDATES,
            candidates=(
                _candidate(kb, "FMEA-004", 1, "persistent C+ with no persistent differential"),
                _candidate(kb, "FMEA-001", 2, "lag below sampling resolution cannot be excluded"),
            ),
            note=(
                "Common-mode thermal elevation; simultaneity matches FMEA-004 and "
                "the evidence cannot uniquely separate cooling, lubrication and "
                "load effects."
            ),
        )
    return _r5("Only cold-side persistent runs are present.")


def interpret_modes(
    series_seq: list[ModeStateSeries],
    kb: FmeaKnowledgeBase,
    min_samples: int,
) -> ModesInterpretationReport:
    """Interpret every turbine's mode streams under the ADR-049 gate."""
    interpretations: list[EpisodeInterpretation] = []
    per_turbine: dict[str, Any] = {}
    totals = {"n_samples": 0, "n_eligible": 0, "n_withheld": 0, "n_withheld_active": 0}
    for series in series_seq:
        for episode in find_episodes(series, min_samples):
            interpretations.append(classify_episode(episode, kb))
        withheld = ~series.eligible.astype(bool)
        active_raw = (series.c_states != 0) | (series.d_states != 0)
        entry = {
            "n_samples": len(series.timestamps),
            "n_eligible": int(series.eligible.sum()),
            "n_withheld": int(withheld.sum()),
            "n_withheld_active": int((withheld & active_raw).sum()),
        }
        per_turbine[series.turbine] = entry
        for key in totals:
            totals[key] += entry[key]
    coverage = {
        **totals,
        "per_turbine": per_turbine,
        "note": (
            R_OOD_NOTE + " Withheld-active samples are exceedances the gate "
            "declined to interpret; they are R_OOD coverage, not episodes, "
            "and eligibility is never a success rate (ADR-049)."
        ),
    }
    return ModesInterpretationReport(
        interpretations=tuple(interpretations),
        coverage=coverage,
        knowledge_base_version=kb.ruleset_version,
        modes_version=MODES_V2_VERSION,
        persistence_min_samples=min_samples,
    )
