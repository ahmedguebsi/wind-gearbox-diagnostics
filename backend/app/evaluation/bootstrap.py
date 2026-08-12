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
