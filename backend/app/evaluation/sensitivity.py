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
#: drove the dominant healthy-state exclusion in EXP-20260812-001 (LIM-014);
#: the remaining grids bracket each provisional default and stay
#: configurable per run.
DEFAULT_GRIDS: dict[str, tuple[Any, ...]] = {
    "healthy_state.fault_pre_exclusion_days": (15, 30, 60),
    "healthy_state.maintenance_post_exclusion_days": (1, 2, 4),
    "healthy_state.minimum_active_power_kw": (25.0, 50.0, 100.0),
    "healthy_state.step_change_exclusion_days": (0.5, 1.0, 2.0),
    "detection.ewma_lambda": (0.1, 0.2, 0.3),
    "detection.control_limit_sigma": (2.0, 3.0, 4.0),
    "detection.persistence_min_samples": (2, 3, 6),
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


@dataclass(frozen=True)
class ParameterSweep:
    """One parameter's sweep: values, outcomes, and conclusion labels."""

    parameter: str
    values: tuple[Any, ...]
    outcomes: tuple[dict[str, Any], ...]
    conclusions: tuple[str, ...]

    @property
    def conclusion_flips(self) -> bool:
        return len(set(self.conclusions)) > 1

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
        }


@dataclass(frozen=True)
class SensitivityReport:
    """All sweeps + tornado summary + the conclusion-flip register hook."""

    sweeps: tuple[ParameterSweep, ...]

    def flipping_parameters(self) -> tuple[str, ...]:
        return tuple(s.parameter for s in self.sweeps if s.conclusion_flips)

    def tornado(self, metric: str) -> pd.DataFrame:
        """Tornado-style summary: outcome range per parameter, widest first
        — which parameters materially change conclusions (PROJECT.md §27.3)."""
        rows = [{"parameter": s.parameter, "range": s.outcome_range(metric)} for s in self.sweeps]
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
        }


def run_sensitivity(
    base_config: AppConfig,
    runner: Callable[[AppConfig], dict[str, Any]],
    conclusion: Callable[[dict[str, Any]], str],
    grids: Mapping[str, Sequence[Any]] | None = None,
) -> SensitivityReport:
    """Sweep every provisional parameter, one at a time, around the base.

    ``runner`` must be seeded and deterministic (it re-runs the pipeline per
    configuration); ``conclusion`` maps an outcome to the stated conclusion
    label whose stability is being tested (e.g. the ADR-016 criterion).
    """
    grids = grids if grids is not None else DEFAULT_GRIDS
    verify_grid_coverage(grids)
    sweeps: list[ParameterSweep] = []
    for parameter in sorted(grids):
        values = tuple(grids[parameter])
        if not values:
            raise ConfigError("Empty sensitivity grid", parameter=parameter)
        outcomes: list[dict[str, Any]] = []
        labels: list[str] = []
        for value in values:
            outcome = runner(override_parameter(base_config, parameter, value))
            outcomes.append(outcome)
            labels.append(conclusion(outcome))
        sweeps.append(
            ParameterSweep(
                parameter=parameter,
                values=values,
                outcomes=tuple(outcomes),
                conclusions=tuple(labels),
            )
        )
    return SensitivityReport(sweeps=tuple(sweeps))
