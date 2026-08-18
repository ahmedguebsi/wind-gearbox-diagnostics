"""Sensitivity analysis suite (M-27; PROJECT.md §27.3).

Provisional parameters are discovered automatically from their config
markers — a newly added provisional parameter without grid coverage fails
:func:`verify_grid_coverage` (and the checklist test) rather than slipping
through unswept (M-27 acceptance 2). Sweeps re-run a caller-supplied,
seeded, deterministic runner per value; conclusion-flipping parameters are
flagged and appended to LIMITATIONS.md (M-27 acceptance 3), converting the
provisional values of PROJECT.md §13/§23 into defended choices.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.config import AppConfig, iter_provisional_parameters
from app.core.errors import ConfigError
from app.core.limitations import append_limitation

#: Default sweep grids per provisional parameter. The fault-pre-exclusion
#: grid is the one PROJECT.md §27.3 names (15/30/60); the event-match grid
#: is ADR-017(d) (7/14/30); the step-change grids exist because the detector
#: drove the dominant healthy-state exclusion in EXP-20260812-001 (LIM-014),
#: and ADR-018 requires the enabled/disabled variant to be swept alongside
#: the parameters so the disabled-exclusion conclusion itself is tested;
#: the remaining grids bracket each provisional default and stay
#: configurable per run.
DEFAULT_GRIDS: dict[str, tuple[Any, ...]] = {
    "healthy_state.exclude_step_changes": (False, True),
    "healthy_state.fault_pre_exclusion_days": (15, 30, 60),
    "healthy_state.maintenance_post_exclusion_days": (1, 2, 4),
    "healthy_state.minimum_active_power_kw": (25.0, 50.0, 100.0),
    "healthy_state.step_change_exclusion_days": (0.5, 1.0, 2.0),
    #: PROJECT.md §27.3 lists the normalization method explicitly. condition_binned
    #: is excluded: the runner refuses it pending the D-12 heteroscedasticity
    #: decision, so sweeping it would fail every configuration rather than
    #: measure one.
    "residual.normalization": ("sigma", "mad", "percentile"),
    #: ADR-001 / PROJECT.md §22: both branches exist as configuration, and the
    #: closure evidence §22 names is a comparison of in-control false-alarm
    #: behaviour under each.
    "residual.threshold_stats_source": ("training", "validation"),
    "detection.ewma_lambda": (0.1, 0.2, 0.3),
    "detection.control_limit_sigma": (2.0, 3.0, 4.0),
    "detection.persistence_min_samples": (2, 3, 6),
    #: ADR-042: both branches exist as configuration so the closure evidence
    #: — what the in-control rate does when the recursion stops crossing
    #: exclusion gaps — can actually be produced.
    "detection.gap_handling": ("continuous", "reset"),
    "evaluation.event_match_window_days": (7, 14, 30),
    "validation.step_change_window_samples": (72, 144, 288),
    "validation.step_change_min_magnitude_c": (2.5, 5.0, 10.0),
}


def verify_grid_coverage(grids: Mapping[str, Sequence[Any]] | None = None) -> None:
    """Every provisional-marked parameter must have a sweep grid — and only
    provisional parameters may be swept (fixed values are not tunable)."""
    grids = grids if grids is not None else DEFAULT_GRIDS
    provisional = set(iter_provisional_parameters())
    missing = sorted(provisional - set(grids))
    extra = sorted(set(grids) - provisional)
    if missing:
        raise ConfigError(
            "Provisional parameter(s) lack sensitivity grid coverage (PROJECT.md §27.3)",
            missing=missing,
        )
    if extra:
        raise ConfigError("Sensitivity grid names non-provisional parameter(s)", extra=extra)


def override_parameter(config: AppConfig, dotted: str, value: Any) -> AppConfig:
    """A new AppConfig with one dotted parameter replaced (re-validated)."""
    payload = config.model_dump(mode="python")
    keys = dotted.split(".")
    cursor: dict[str, Any] = payload
    for key in keys[:-1]:
        if key not in cursor or not isinstance(cursor[key], dict):
            raise ConfigError("Unknown configuration section", parameter=dotted)
        cursor = cursor[key]
    if keys[-1] not in cursor:
        raise ConfigError("Unknown configuration parameter", parameter=dotted)
    cursor[keys[-1]] = value
    return AppConfig.model_validate(payload)


#: Sweep status labels. NOT_APPLICABLE is the one that had to be added: a
#: parameter with no lever on the run reports identical outcomes at every
#: value, which is indistinguishable from genuine insensitivity unless it is
#: said out loud (ADR-040).
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"
STATUS_FLIPS = "FLIPS"
STATUS_STABLE = "STABLE"


@dataclass(frozen=True)
class ParameterSweep:
    """One parameter's sweep: values, outcomes, and conclusion labels.

    ``inapplicable_reason`` is set when the parameter cannot affect this run
    at all. On the Kelmarsh configuration five of the thirteen provisional
    parameters are in that position: no caller supplies fault or maintenance
    exclusion windows, so ``fault_pre_exclusion_days`` and
    ``maintenance_post_exclusion_days`` have nothing to act on; and
    ``exclude_step_changes`` is False at the base configuration (ADR-018), so
    the three step-change parameters are inert around it. Sweeping them
    produced identical outcomes and the suite labelled them STABLE — reading
    as robustness evidence for parameters that were merely switched off.
    """

    parameter: str
    values: tuple[Any, ...]
    outcomes: tuple[dict[str, Any], ...]
    conclusions: tuple[str, ...]
    #: Why this parameter has no lever on the run, or None when it does.
    inapplicable_reason: str | None = None

    @property
    def applicable(self) -> bool:
        return self.inapplicable_reason is None

    @property
    def conclusion_flips(self) -> bool:
        """True only for a parameter that CAN move the outcome and does.

        An inapplicable parameter cannot flip a conclusion, and must not be
        able to raise a false alarm in the register either.
        """
        return self.applicable and len(set(self.conclusions)) > 1

    @property
    def status(self) -> str:
        if not self.applicable:
            return STATUS_NOT_APPLICABLE
        return STATUS_FLIPS if self.conclusion_flips else STATUS_STABLE

    def outcome_range(self, metric: str) -> float:
        numbers = [float(outcome[metric]) for outcome in self.outcomes]
        return max(numbers) - min(numbers)

    def as_dict(self) -> dict[str, Any]:
        return {
            "parameter": self.parameter,
            "values": list(self.values),
            "outcomes": list(self.outcomes),
            "conclusions": list(self.conclusions),
            "conclusion_flips": self.conclusion_flips,
            "status": self.status,
            "applicable": self.applicable,
            "inapplicable_reason": self.inapplicable_reason,
        }


@dataclass(frozen=True)
class SensitivityReport:
    """All sweeps + tornado summary + the conclusion-flip register hook."""

    sweeps: tuple[ParameterSweep, ...]

    def flipping_parameters(self) -> tuple[str, ...]:
        return tuple(s.parameter for s in self.sweeps if s.conclusion_flips)

    def inapplicable_parameters(self) -> tuple[str, ...]:
        """Parameters with no lever on this run — NOT evidence of stability."""
        return tuple(s.parameter for s in self.sweeps if not s.applicable)

    def tornado(self, metric: str) -> pd.DataFrame:
        """Tornado-style summary: outcome range per parameter, widest first
        — which parameters materially change conclusions (PROJECT.md §27.3).

        Carries the ``status`` column so a zero-range row cannot be read as
        robustness without seeing whether the parameter was applicable at all
        (ADR-040).
        """
        rows = [
            {
                "parameter": s.parameter,
                "range": s.outcome_range(metric),
                "status": s.status,
                "inapplicable_reason": s.inapplicable_reason,
            }
            for s in self.sweeps
        ]
        return pd.DataFrame(rows).sort_values("range", ascending=False).reset_index(drop=True)

    def append_flips(self, limitations_path: Path, *, source: str) -> list[str]:
        """M-27 acceptance 3: conclusion-flipping parameters auto-append
        LIMITATIONS.md entries. Returns the new LIM ids."""
        lim_ids: list[str] = []
        for sweep in self.sweeps:
            if not sweep.conclusion_flips:
                continue
            pairs = ", ".join(
                f"{value} -> {conclusion}"
                for value, conclusion in zip(sweep.values, sweep.conclusions, strict=True)
            )
            lim_ids.append(
                append_limitation(
                    limitations_path,
                    title=f"Conclusion flips across the {sweep.parameter} sweep",
                    description=(
                        f"Sensitivity sweep of provisional parameter "
                        f"{sweep.parameter} changes the stated conclusion: "
                        f"{pairs}. The parameter choice materially affects "
                        "the result and must be defended, not defaulted "
                        "(PROJECT.md 27.3)."
                    ),
                    affected_rqs="RQ2 (detection conclusions)",
                    mitigation_status="OPEN — defend the chosen value in Chapter 3/5",
                    source=source,
                )
            )
        return lim_ids

    def as_dict(self) -> dict[str, Any]:
        return {
            "sweeps": [s.as_dict() for s in self.sweeps],
            "flipping_parameters": list(self.flipping_parameters()),
            "inapplicable_parameters": list(self.inapplicable_parameters()),
            "note": (
                "A parameter listed under inapplicable_parameters has no lever "
                "on this run and its identical outcomes are NOT evidence that "
                "the conclusion is robust to it (ADR-040)."
            ),
        }


#: A predicate returning the reason a parameter cannot affect a run, or None
#: when it can. Evaluated against the CONFIGURATION BEING SWEPT, so a
#: parameter gated by another config field is judged per value.
ApplicabilityCheck = Callable[[AppConfig], str | None]


def run_sensitivity(
    base_config: AppConfig,
    runner: Callable[[AppConfig], dict[str, Any]],
    conclusion: Callable[[dict[str, Any]], str],
    grids: Mapping[str, Sequence[Any]] | None = None,
    applicability: Mapping[str, ApplicabilityCheck] | None = None,
) -> SensitivityReport:
    """Sweep every provisional parameter, one at a time, around the base.

    ``runner`` must be seeded and deterministic (it re-runs the pipeline per
    configuration); ``conclusion`` maps an outcome to the stated conclusion
    label whose stability is being tested (e.g. the ADR-016 criterion).

    ``applicability`` declares, per parameter, whether it can affect this run
    at all. A parameter inapplicable at EVERY swept value is labelled
    NOT_APPLICABLE and is excluded from the conclusion-flip register: its
    identical outcomes say nothing about robustness (ADR-040). Applicability
    is a property of the run's INPUTS as well as its config — no caller
    supplies fault or maintenance windows on the Kelmarsh holdings — so the
    checks are supplied by the caller that owns those inputs, not inferred
    here.
    """
    grids = grids if grids is not None else DEFAULT_GRIDS
    checks = dict(applicability or {})
    verify_grid_coverage(grids)
    sweeps: list[ParameterSweep] = []
    for parameter in sorted(grids):
        values = tuple(grids[parameter])
        if not values:
            raise ConfigError("Empty sensitivity grid", parameter=parameter)
        check = checks.get(parameter)
        outcomes: list[dict[str, Any]] = []
        labels: list[str] = []
        reasons: list[str | None] = []
        for value in values:
            config = override_parameter(base_config, parameter, value)
            reasons.append(check(config) if check is not None else None)
            outcome = runner(config)
            outcomes.append(outcome)
            labels.append(conclusion(outcome))
        # Inapplicable only when NO swept value gives the parameter a lever.
        # Sweeping `exclude_step_changes` False->True is exactly the case that
        # must stay applicable: one of its values turns the machinery on.
        inapplicable = reasons[0] if all(r is not None for r in reasons) else None
        sweeps.append(
            ParameterSweep(
                parameter=parameter,
                values=values,
                outcomes=tuple(outcomes),
                conclusions=tuple(labels),
                inapplicable_reason=inapplicable,
            )
        )
    return SensitivityReport(sweeps=tuple(sweeps))
