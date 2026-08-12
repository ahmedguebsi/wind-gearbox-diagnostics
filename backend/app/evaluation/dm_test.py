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
