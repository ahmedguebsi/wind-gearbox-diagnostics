"""Single-signal detection on EWMA series — the primary path (M-21).

The EWMA detector (M-20, LOCKED-02) already emits per-signal decisions at
its fitted control limits; this module adds the ability to re-decide the
same EWMA stream at a DIFFERENT control-limit multiplier without refitting —
the primitive the matched-FPR threshold sweep (M-23) is built on. Limits
scale linearly with the multiplier, so the stored limit profile is rescaled
exactly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.core.errors import ConfigError
from app.residuals.ewma import PRIMARY_EWMA_LABEL, DetectionSeries, EwmaSeries


def states_at_multiplier(series: EwmaSeries, multiplier: float) -> DetectionSeries:
    """Re-decide one EWMA stream at an alternative sigma multiplier.

    The stored limit profile corresponds to ``series.spec.sigma_multiplier``;
    limits are proportional to the multiplier, so rescaling reproduces the
    limit profile any other multiplier would have produced.
    """
    if multiplier <= 0.0:
        raise ConfigError("Control-limit multiplier must be positive", multiplier=multiplier)
    scale = multiplier / series.spec.sigma_multiplier
    upper = series.upper.to_numpy(dtype=float) * scale
    lower = series.lower.to_numpy(dtype=float) * scale
    values = series.values.to_numpy(dtype=float)
    states = np.zeros(len(values), dtype=int)
    states[values > upper] = 1
    states[values < lower] = -1
    return DetectionSeries(
        turbine=series.turbine,
        target=series.target,
        timestamps=series.timestamps,
        states=pd.Series(states),
        method_label=PRIMARY_EWMA_LABEL,
    )


class SingleSignalDetector:
    """Primary per-signal decision on an EWMA stream (ARCHITECTURE.md §6.3).

    ``multiplier=None`` decides at the stream's own fitted limits.
    """

    def __init__(self, multiplier: float | None = None) -> None:
        self.multiplier = multiplier

    def detect(self, series: EwmaSeries) -> DetectionSeries:
        multiplier = (
            self.multiplier if self.multiplier is not None else (series.spec.sigma_multiplier)
        )
        return states_at_multiplier(series, multiplier)
