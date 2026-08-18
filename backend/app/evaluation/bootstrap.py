"""Moving-block bootstrap confidence intervals (M-28; PROJECT.md §19).

All headline accuracy metrics carry CIs from a moving-block bootstrap on
chronologically ordered residuals. The naive i.i.d. bootstrap is prohibited
for time-series residuals — a block length below 2 IS the i.i.d. bootstrap
and is rejected at construction (config rejection, M-28 test obligation).

Block length comes from the residual autocorrelation via a documented
heuristic (:func:`block_length_from_autocorrelation`) and is recorded in
every ConfidenceInterval, together with the seed and replicate count, so
the choice is reproducible and reportable.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.core.errors import ConfigError


@dataclass(frozen=True)
class ConfidenceInterval:
    """Percentile CI with its full provenance (recorded per PROJECT.md §19)."""

    point: float
    lower: float
    upper: float
    confidence: float
    block_length: int
    n_boot: int
    seed: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "point": self.point,
            "lower": self.lower,
            "upper": self.upper,
            "confidence": self.confidence,
            "block_length": self.block_length,
            "n_boot": self.n_boot,
            "seed": self.seed,
        }


def sample_autocorrelation(series: np.ndarray, lag: int) -> float:
    """Biased sample ACF at one lag (the standard 1/n normalization)."""
    n = len(series)
    if lag >= n:
        raise ConfigError("Lag exceeds series length", lag=lag, n=n)
    centered = series - series.mean()
    denominator = float(np.sum(centered**2))
    if denominator == 0.0:
        return 0.0
    return float(np.sum(centered[lag:] * centered[:-lag]) / denominator)


def block_length_from_autocorrelation(series: np.ndarray) -> int:
    """Documented heuristic: twice the first lag at which the sample ACF
    falls inside the 95% white-noise band (1.96/sqrt(n)), bounded to
    [2, n // 4]. Recorded in every CI so the choice is auditable."""
    n = len(series)
    if n < 8:
        raise ConfigError("Series too short for a block-length estimate", n=n)
    band = 1.96 / math.sqrt(n)
    cutoff = 1
    for lag in range(1, n // 4 + 1):
        if abs(sample_autocorrelation(series, lag)) < band:
            cutoff = lag
            break
    else:
        cutoff = n // 4
    return int(min(max(2 * cutoff, 2), n // 4)) if n >= 16 else 2


class BlockedBootstrap:
    """Moving-block bootstrap (ARCHITECTURE.md §5.6)."""

    def __init__(self, block_length: int, n_boot: int, seed: int) -> None:
        if block_length < 2:
            raise ConfigError(
                "block_length < 2 is the i.i.d. bootstrap, which is "
                "prohibited for time-series residuals (PROJECT.md §19)",
                block_length=block_length,
            )
        if n_boot < 100:
            raise ConfigError("Too few bootstrap replicates", n_boot=n_boot)
        self.block_length = block_length
        self.n_boot = n_boot
        self.seed = seed

    def ci(
        self,
        series: np.ndarray,
        statistic: Callable[[np.ndarray], float],
        confidence: float = 0.95,
    ) -> ConfidenceInterval:
        """Percentile interval for ``statistic`` over moving-block resamples."""
        n = len(series)
        if n <= self.block_length:
            raise ConfigError(
                "Series shorter than a single block", n=n, block_length=self.block_length
            )
        if not 0.0 < confidence < 1.0:
            raise ConfigError("Confidence must be in (0, 1)", confidence=confidence)
        rng = np.random.default_rng(self.seed)
        n_blocks = math.ceil(n / self.block_length)
        max_start = n - self.block_length + 1
        offsets = np.arange(self.block_length)
        replicates = np.empty(self.n_boot, dtype=float)
        for i in range(self.n_boot):
            starts = rng.integers(0, max_start, size=n_blocks)
            indices = (starts[:, None] + offsets).ravel()[:n]
            replicates[i] = statistic(series[indices])
        alpha = (1.0 - confidence) / 2.0
        lower, upper = np.quantile(replicates, [alpha, 1.0 - alpha])
        return ConfidenceInterval(
            point=float(statistic(series)),
            lower=float(lower),
            upper=float(upper),
            confidence=confidence,
            block_length=self.block_length,
            n_boot=self.n_boot,
            seed=self.seed,
        )


#: Below this many blocks per resample the percentile interval is driven by a
#: handful of segments and is reported as unreliable rather than silently
#: quoted. Same standard ADR-034 binding condition (b) sets for control-limit
#: calibration; applied here for the same reason.
MIN_RELIABLE_BLOCKS = 30


@dataclass(frozen=True)
class PanelConfidenceInterval:
    """A CI over a panel of per-turbine series, with per-unit provenance.

    WHY THIS EXISTS (docs/METHODOLOGY_REVIEW.md P-3, completing it). The RQ1
    metrics are computed on a frame sorted by timestamp that INTERLEAVES six
    turbines, so consecutive rows are different machines at the same instant.
    Running a moving-block bootstrap over that series does two wrong things at
    once: a "block" spans six machines rather than a stretch of one machine's
    history, and the block length chosen from the interleaved autocorrelation
    inflates roughly sixfold. On EXP-20260817-001 the unfiltered-test baseline
    drew block length 132,858 from n = 740,463 — about SIX blocks per
    replicate. A percentile interval from six blocks is not an interval.

    P-3 specified per-turbine treatment for the bootstrap AND the DM test;
    only the DM test was rewired (commit ceb954d). This closes the other half.

    The resampling is a panel block bootstrap: each turbine's own series is
    resampled in blocks whose length comes from THAT turbine's autocorrelation,
    the resampled turbines are concatenated, and the statistic is evaluated on
    the reassembled panel. The reported quantity is therefore unchanged — it is
    still the fleet-level metric — while the dependence structure the resample
    preserves is now the real one.
    """

    point: float
    lower: float
    upper: float
    confidence: float
    n_boot: int
    seed: int
    #: unit -> {block_length, n, n_blocks}
    per_unit: dict[str, dict[str, int]]

    @property
    def min_blocks(self) -> int:
        return min((u["n_blocks"] for u in self.per_unit.values()), default=0)

    @property
    def reliable(self) -> bool:
        """False when any unit contributes too few blocks to resample from."""
        return self.min_blocks >= MIN_RELIABLE_BLOCKS

    def as_dict(self) -> dict[str, Any]:
        return {
            "point": self.point,
            "lower": self.lower,
            "upper": self.upper,
            "confidence": self.confidence,
            "n_boot": self.n_boot,
            "seed": self.seed,
            "per_unit": {k: dict(v) for k, v in self.per_unit.items()},
            "min_blocks": self.min_blocks,
            "reliable": self.reliable,
            "caveat": (
                None
                if self.reliable
                else (
                    f"Fewest blocks in any unit is {self.min_blocks} (< "
                    f"{MIN_RELIABLE_BLOCKS}); the percentile interval rests on "
                    "too few independent segments to be quoted as a confidence "
                    "interval. Report descriptively (PROJECT.md §19)."
                )
            ),
        }


class PanelBlockedBootstrap:
    """Moving-block bootstrap over a panel of independent per-unit series.

    Each unit keeps its own block length, so a machine with slower thermal
    dynamics is resampled in longer blocks than one with faster dynamics
    rather than both inheriting a length computed from their interleaving.
    """

    def __init__(self, n_boot: int, seed: int) -> None:
        if n_boot < 100:
            raise ConfigError("Too few bootstrap replicates", n_boot=n_boot)
        self.n_boot = n_boot
        self.seed = seed

    def ci(
        self,
        series_by_unit: dict[str, np.ndarray],
        statistic: Callable[[np.ndarray], float],
        confidence: float = 0.95,
    ) -> PanelConfidenceInterval:
        """Percentile interval for ``statistic`` over the reassembled panel.

        ``series_by_unit`` maps a unit label (turbine) to that unit's series in
        chronological order. Units are resampled independently and concatenated
        in sorted label order, so the result is deterministic given the seed.
        """
        if not series_by_unit:
            raise ConfigError("Panel bootstrap requires at least one unit")
        units = sorted(series_by_unit)
        plans: dict[str, tuple[np.ndarray, int, int]] = {}
        for unit in units:
            values = np.asarray(series_by_unit[unit], dtype=float)
            n = len(values)
            if n < 8:
                raise ConfigError("Unit series too short to bootstrap", unit=unit, n=n)
            block = block_length_from_autocorrelation(values)
            if n <= block:
                raise ConfigError(
                    "Unit series shorter than a single block", unit=unit, n=n, block_length=block
                )
            plans[unit] = (values, block, math.ceil(n / block))
        if not 0.0 < confidence < 1.0:
            raise ConfigError("Confidence must be in (0, 1)", confidence=confidence)

        rng = np.random.default_rng(self.seed)
        replicates = np.empty(self.n_boot, dtype=float)
        for i in range(self.n_boot):
            parts: list[np.ndarray] = []
            for unit in units:
                values, block, n_blocks = plans[unit]
                starts = rng.integers(0, len(values) - block + 1, size=n_blocks)
                indices = (starts[:, None] + np.arange(block)).ravel()[: len(values)]
                parts.append(values[indices])
            replicates[i] = statistic(np.concatenate(parts))

        observed = np.concatenate([plans[unit][0] for unit in units])
        alpha = (1.0 - confidence) / 2.0
        lower, upper = np.quantile(replicates, [alpha, 1.0 - alpha])
        return PanelConfidenceInterval(
            point=float(statistic(observed)),
            lower=float(lower),
            upper=float(upper),
            confidence=confidence,
            n_boot=self.n_boot,
            seed=self.seed,
            per_unit={
                unit: {
                    "block_length": plans[unit][1],
                    "n": len(plans[unit][0]),
                    "n_blocks": plans[unit][2],
                }
                for unit in units
            },
        )
