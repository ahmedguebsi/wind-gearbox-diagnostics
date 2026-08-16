"""Diebold-Mariano test with HAC variance (M-28; PROJECT.md §19).

Model-vs-model accuracy comparisons use the DM test on the loss-differential
series with autocorrelation-robust (Newey-West/Bartlett) variance. Where
series are short, the result is flagged unreliable with a caveat — the
caller reports descriptively and logs the caveat to LIMITATIONS.md rather
than forcing a test (PROJECT.md §19).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.core.errors import ConfigError
from app.evaluation.bootstrap import sample_autocorrelation

#: Below this many loss differentials the asymptotic normal approximation is
#: strained; results are flagged and reported descriptively.
MIN_RELIABLE_N = 30


@dataclass(frozen=True)
class DmResult:
    statistic: float
    p_value: float
    n: int
    hac_lags: int
    reliable: bool
    caveat: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "statistic": self.statistic,
            "p_value": self.p_value,
            "n": self.n,
            "hac_lags": self.hac_lags,
            "reliable": self.reliable,
            "caveat": self.caveat,
        }


def _gaussian_two_sided_p(statistic: float) -> float:
    return float(2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(statistic) / math.sqrt(2.0)))))


def suggest_hac_lags(loss_differential: np.ndarray) -> int:
    """HAC lag count from the loss differential's own autocorrelation.

    The ``floor(n^(1/3))`` rule of thumb is a function of sample SIZE, not of
    dependence: on ~5e5 ten-minute residuals it yields ~81 lags, and if the
    series interleaves six turbines that is ~13 samples per machine, roughly
    two hours of real time. Thermal residuals autocorrelate over far longer,
    so the long-run variance is understated and |DM| inflated.

    This selects the first lag at which the sample autocorrelation falls
    inside the 95% white-noise band, then doubles it (the same documented
    heuristic the moving-block bootstrap uses for block length), bounded to
    [1, n // 4]. Report the value used — it is part of the result.
    """
    n = len(loss_differential)
    if n < 8:
        raise ConfigError("Series too short for a HAC lag estimate", n=n)
    band = 1.96 / math.sqrt(n)
    cutoff = n // 4
    for lag in range(1, n // 4 + 1):
        if abs(sample_autocorrelation(loss_differential, lag)) < band:
            cutoff = lag
            break
    return int(min(max(2 * cutoff, 1), n // 4))


@dataclass(frozen=True)
class PerTurbineDm:
    """DM computed separately per turbine, with a direction-agreement summary.

    Pooling six machines into one loss series and running a single test treats
    contemporaneous cross-turbine observations as sequential ones, so neither
    the HAC correction nor the blocked bootstrap sees the structure it assumes.
    Running the test per turbine keeps each series a genuine time series.

    No combined p-value is reported. Combining dependent per-turbine tests
    would need an assumption about their joint distribution that this data
    cannot support; the honest summary is how many machines agree in direction
    and what the worst case is.
    """

    per_turbine: dict[str, DmResult]
    favours_a: int
    favours_b: int
    n_turbines: int

    @property
    def direction_is_unanimous(self) -> bool:
        return self.favours_a == self.n_turbines or self.favours_b == self.n_turbines

    @property
    def weakest_p_value(self) -> float:
        return max(r.p_value for r in self.per_turbine.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "per_turbine": {k: v.as_dict() for k, v in self.per_turbine.items()},
            "n_turbines": self.n_turbines,
            "favours_a": self.favours_a,
            "favours_b": self.favours_b,
            "direction_is_unanimous": self.direction_is_unanimous,
            "weakest_p_value": self.weakest_p_value,
            "note": (
                "No combined p-value: per-turbine tests are dependent and "
                "combining them would require an unsupported assumption about "
                "their joint distribution."
            ),
        }


def diebold_mariano_by_turbine(
    loss_a: np.ndarray,
    loss_b: np.ndarray,
    turbines: np.ndarray,
    hac_lags: int | None = None,
) -> PerTurbineDm:
    """Run the DM test separately per turbine on aligned loss series.

    ``hac_lags=None`` selects the lag count per turbine from that turbine's
    own loss differential via :func:`suggest_hac_lags`.
    """
    if not (len(loss_a) == len(loss_b) == len(turbines)):
        raise ConfigError(
            "Loss and turbine arrays must align",
            a=len(loss_a),
            b=len(loss_b),
            turbines=len(turbines),
        )
    results: dict[str, DmResult] = {}
    for turbine in sorted({str(t) for t in turbines}):
        mask = turbines.astype(str) == turbine
        a, b = np.asarray(loss_a)[mask], np.asarray(loss_b)[mask]
        if len(a) < 4:
            continue
        lags = hac_lags if hac_lags is not None else suggest_hac_lags(a - b)
        results[turbine] = diebold_mariano(a, b, lags)
    if not results:
        raise ConfigError("No turbine had enough observations for a DM test")
    return PerTurbineDm(
        per_turbine=results,
        favours_a=sum(1 for r in results.values() if r.statistic < 0),
        favours_b=sum(1 for r in results.values() if r.statistic > 0),
        n_turbines=len(results),
    )


def diebold_mariano(
    loss_a: np.ndarray, loss_b: np.ndarray, hac_lags: int | None = None
) -> DmResult:
    """DM statistic on d = loss_a - loss_b with Bartlett-kernel HAC variance.

    ``hac_lags`` defaults to floor(n^(1/3)) (the common rule of thumb),
    recorded in the result. Identical loss series give statistic 0, p 1.
    """
    if len(loss_a) != len(loss_b):
        raise ConfigError("Loss series lengths differ", a=len(loss_a), b=len(loss_b))
    n = len(loss_a)
    if n < 4:
        raise ConfigError("Too few observations for a DM test", n=n)
    d = np.asarray(loss_a, dtype=float) - np.asarray(loss_b, dtype=float)
    lags = int(hac_lags) if hac_lags is not None else math.floor(n ** (1.0 / 3.0))
    if lags < 0 or lags >= n:
        raise ConfigError("Invalid HAC lag count", hac_lags=lags, n=n)

    d_bar = float(d.mean())
    centered = d - d_bar
    gamma0 = float(np.sum(centered**2) / n)
    long_run = gamma0
    for lag in range(1, lags + 1):
        weight = 1.0 - lag / (lags + 1.0)
        gamma = float(np.sum(centered[lag:] * centered[:-lag]) / n)
        long_run += 2.0 * weight * gamma
    if long_run <= 0.0:
        # Degenerate (e.g. identical losses): no variance, no difference.
        statistic = 0.0
        p_value = 1.0
    else:
        statistic = d_bar / math.sqrt(long_run / n)
        p_value = _gaussian_two_sided_p(statistic)

    reliable = n >= MIN_RELIABLE_N
    caveat = (
        None
        if reliable
        else (
            f"Loss-differential series has n={n} < {MIN_RELIABLE_N}; the "
            "asymptotic DM approximation is strained — report descriptively "
            "and log to LIMITATIONS.md (PROJECT.md §19)."
        )
    )
    return DmResult(
        statistic=statistic,
        p_value=p_value,
        n=n,
        hac_lags=lags,
        reliable=reliable,
        caveat=caveat,
    )
