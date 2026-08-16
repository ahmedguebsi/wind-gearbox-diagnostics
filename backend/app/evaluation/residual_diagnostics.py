"""Residual-level diagnostics (M-28 companion; docs/METHODOLOGY_REVIEW.md §4).

Two measurements the pipeline did not previously produce. Both are read-only
descriptions of residuals that already exist: neither changes a fitted model,
a threshold, or any reported metric. They exist because two load-bearing
assumptions were unmeasured.

1. CROSS-TARGET RESIDUAL CORRELATION (:func:`cross_target_correlation`).
   The coordinated-detection premise (PROJECT.md §24) is that two thermally
   coupled targets carry evidence that is not redundant. The deciding
   quantity is the correlation between the two RESIDUAL series, which is not
   the correlation between the raw temperatures — the latter is dominated by
   common load and ambient drive and was the basis of the ADR-012 target
   designation. If the residual streams are near-duplicates, requiring
   coincidence buys specificity against per-channel noise but adds little
   independent physical evidence.

   Reported on raw residuals. Because every normalizer family in M-19b
   applies a per-target affine map, Pearson correlation is invariant to
   normalization and the raw figure is also the normalized figure; Spearman
   is reported alongside because affine invariance does not imply the
   relationship is linear.

2. PER-TURBINE RESIDUAL LOCATION AND SCALE (:func:`per_turbine_residual_stats`).
   Normalization statistics (M-19b) and EWMA control limits (M-20) are fitted
   per target and POOLED across turbines. A systematic per-turbine offset
   therefore enters that machine's normalized residual as a constant bias and
   permanently consumes part of its alarm budget. LIM-021 names per-turbine
   drift as one of four candidate explanations it cannot separate; this
   function measures the quantity that decides whether pooling is defensible.
   The dispersion summary answers that question directly: it is the spread of
   per-turbine centres expressed in units of the pooled scale.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd

from app.core.errors import ConfigError
from app.residuals.engine import (
    RAW_RESIDUAL_COLUMN,
    TARGET_COLUMN,
    TIMESTAMP_COLUMN,
    TURBINE_COLUMN,
    ResidualFrame,
)
from app.residuals.normalization import MAD_SIGMA_CONSISTENCY

#: Below this many aligned observations a correlation is not reported.
MIN_PAIRED_OBSERVATIONS = 30


@dataclass(frozen=True)
class TargetPairCorrelation:
    """Correlation between two targets' residuals, pooled and per turbine."""

    target_a: str
    target_b: str
    n_paired: int
    pearson: float
    spearman: float
    per_turbine_pearson: dict[str, float]

    @property
    def per_turbine_range(self) -> float:
        """Spread of the per-turbine estimates; wide spread means the pooled
        figure is not representative of any single machine."""
        values = list(self.per_turbine_pearson.values())
        return float(max(values) - min(values)) if values else float("nan")

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_a": self.target_a,
            "target_b": self.target_b,
            "n_paired": self.n_paired,
            "pearson": self.pearson,
            "spearman": self.spearman,
            "per_turbine_pearson": dict(self.per_turbine_pearson),
            "per_turbine_range": self.per_turbine_range,
        }


@dataclass(frozen=True)
class CrossTargetCorrelation:
    """All target pairs' residual correlations for one partition."""

    partition: str
    pairs: tuple[TargetPairCorrelation, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "partition": self.partition,
            "note": (
                "Pearson is computed on raw residuals and is invariant to the "
                "per-target affine normalization of M-19b, so it is also the "
                "normalized-residual figure."
            ),
            "pairs": [pair.as_dict() for pair in self.pairs],
        }


def _wide_residuals(residuals: ResidualFrame) -> pd.DataFrame:
    """Long ResidualFrame -> one column per target, indexed by (timestamp, turbine).

    Uses ``pivot`` rather than ``pivot_table``: a duplicate
    (timestamp, turbine, target) key is a dataset-integrity failure and must
    raise rather than be silently averaged.
    """
    frame = residuals.data
    try:
        wide = frame.pivot(
            index=[TIMESTAMP_COLUMN, TURBINE_COLUMN],
            columns=TARGET_COLUMN,
            values=RAW_RESIDUAL_COLUMN,
        )
    except ValueError as exc:  # duplicate keys
        raise ConfigError(
            "Residual rows are not unique on (timestamp, turbine, target); "
            "averaging them would fabricate a residual",
            detail=str(exc),
        ) from exc
    return wide


def cross_target_correlation(residuals: ResidualFrame, *, partition: str) -> CrossTargetCorrelation:
    """Residual correlation for every target pair, pooled and per turbine."""
    targets = residuals.targets
    if len(targets) < 2:
        raise ConfigError(
            "Cross-target correlation needs at least two targets", targets=list(targets)
        )
    wide = _wide_residuals(residuals)
    pairs: list[TargetPairCorrelation] = []
    for target_a, target_b in combinations(targets, 2):
        paired = wide[[target_a, target_b]].dropna()
        if len(paired) < MIN_PAIRED_OBSERVATIONS:
            raise ConfigError(
                "Too few aligned observations for a correlation estimate",
                target_a=target_a,
                target_b=target_b,
                n_paired=len(paired),
            )
        per_turbine: dict[str, float] = {}
        for turbine, group in paired.groupby(level=TURBINE_COLUMN, observed=True):
            if len(group) < MIN_PAIRED_OBSERVATIONS:
                continue
            value = group[target_a].corr(group[target_b])
            per_turbine[str(turbine)] = round(float(value), 6)
        pairs.append(
            TargetPairCorrelation(
                target_a=target_a,
                target_b=target_b,
                n_paired=len(paired),
                pearson=round(float(paired[target_a].corr(paired[target_b])), 6),
                spearman=round(
                    float(paired[target_a].corr(paired[target_b], method="spearman")), 6
                ),
                per_turbine_pearson=per_turbine,
            )
        )
    return CrossTargetCorrelation(partition=partition, pairs=tuple(pairs))


@dataclass(frozen=True)
class TurbineTargetStats:
    """Location and scale of one (turbine, target) residual stream."""

    turbine: str
    target: str
    n: int
    median: float
    mad_scale: float
    mean: float
    std: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "turbine": self.turbine,
            "target": self.target,
            "n": self.n,
            "median": self.median,
            "mad_scale": self.mad_scale,
            "mean": self.mean,
            "std": self.std,
        }


@dataclass(frozen=True)
class PooledTargetStats:
    """Pooled statistics for one target, plus the dispersion of the
    per-turbine centres that the pooled figure replaces."""

    target: str
    pooled_median: float
    pooled_mad_scale: float
    per_turbine_centre_spread: float
    #: The spread of per-turbine centres in units of the pooled scale. This is
    #: the number that decides whether pooling is defensible: it is, in effect,
    #: the systematic offset pooling imposes on the worst-placed machine.
    centre_spread_in_pooled_scales: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "pooled_median": self.pooled_median,
            "pooled_mad_scale": self.pooled_mad_scale,
            "per_turbine_centre_spread": self.per_turbine_centre_spread,
            "centre_spread_in_pooled_scales": self.centre_spread_in_pooled_scales,
        }


@dataclass(frozen=True)
class PerTurbineResidualStats:
    """Per-(turbine, target) statistics with the pooled comparison."""

    partition: str
    per_stream: tuple[TurbineTargetStats, ...]
    pooled: tuple[PooledTargetStats, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "partition": self.partition,
            "note": (
                "M-19b fits normalization statistics per target, pooled across "
                "turbines. centre_spread_in_pooled_scales states how large the "
                "between-turbine offset is relative to the single scale applied "
                "to all of them."
            ),
            "per_stream": [s.as_dict() for s in self.per_stream],
            "pooled": [p.as_dict() for p in self.pooled],
        }


def _median_and_mad(values: np.ndarray) -> tuple[float, float]:
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    return median, MAD_SIGMA_CONSISTENCY * mad


def per_turbine_residual_stats(
    residuals: ResidualFrame, *, partition: str
) -> PerTurbineResidualStats:
    """Residual location and scale per (turbine, target), against the pooled fit."""
    frame = residuals.data
    streams: list[TurbineTargetStats] = []
    centres_by_target: dict[str, list[float]] = {}

    for (turbine, target), group in frame.groupby([TURBINE_COLUMN, TARGET_COLUMN], observed=True):
        values = group[RAW_RESIDUAL_COLUMN].to_numpy(dtype=float)
        values = values[~np.isnan(values)]
        if len(values) < 2:
            continue
        median, mad_scale = _median_and_mad(values)
        streams.append(
            TurbineTargetStats(
                turbine=str(turbine),
                target=str(target),
                n=len(values),
                median=round(median, 6),
                mad_scale=round(mad_scale, 6),
                mean=round(float(np.mean(values)), 6),
                std=round(float(np.std(values, ddof=1)), 6),
            )
        )
        centres_by_target.setdefault(str(target), []).append(median)

    if not streams:
        raise ConfigError("No residual stream had enough observations", partition=partition)

    pooled: list[PooledTargetStats] = []
    for target, group in frame.groupby(TARGET_COLUMN, observed=True):
        values = group[RAW_RESIDUAL_COLUMN].to_numpy(dtype=float)
        values = values[~np.isnan(values)]
        if len(values) < 2:
            continue
        pooled_median, pooled_scale = _median_and_mad(values)
        centres = centres_by_target.get(str(target), [])
        spread = float(max(centres) - min(centres)) if len(centres) > 1 else 0.0
        pooled.append(
            PooledTargetStats(
                target=str(target),
                pooled_median=round(pooled_median, 6),
                pooled_mad_scale=round(pooled_scale, 6),
                per_turbine_centre_spread=round(spread, 6),
                centre_spread_in_pooled_scales=(
                    round(spread / pooled_scale, 6) if pooled_scale > 0.0 else float("nan")
                ),
            )
        )

    return PerTurbineResidualStats(
        partition=partition,
        per_stream=tuple(streams),
        pooled=tuple(pooled),
    )
