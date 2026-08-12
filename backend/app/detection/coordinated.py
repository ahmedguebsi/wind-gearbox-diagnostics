"""Coordinated multi-target residual states (M-22; PROJECT.md §24).

Central thesis contribution: thermal residuals are never evaluated only
independently. Per-target detections combine into a coordinated state
vector ({-1, 0, +1} per target) while the continuous EWMA values are
preserved alongside — any serialization carries BOTH representations
(M-22 acceptance 1). A target with no observation at a timestamp is an
explicit gap (None), never a silent 0.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.core.errors import ConfigError
from app.residuals.ewma import DetectionSeries, EwmaSeries


@dataclass(frozen=True)
class CoordinatedState:
    """One timestamp's multi-target state for one turbine."""

    timestamp_utc: pd.Timestamp
    turbine: str
    #: target -> -1 | 0 | +1, or None where the target has no observation.
    vector: dict[str, int | None]
    #: target -> continuous EWMA value, or None where absent.
    continuous: dict[str, float | None]

    def as_dict(self) -> dict[str, Any]:
        """Discrete and continuous are serialized together, always."""
        return {
            "timestamp_utc": self.timestamp_utc.isoformat(),
            "turbine": self.turbine,
            "vector": dict(self.vector),
            "continuous": dict(self.continuous),
        }


class CoordinatedAnalyzer:
    """Combine per-target detection and EWMA streams into state vectors."""

    def combine(
        self, detections: list[DetectionSeries], ewma: list[EwmaSeries]
    ) -> list[CoordinatedState]:
        """Time-ordered coordinated states per turbine (stable target order).

        Detection and EWMA streams are matched on (turbine, target) and must
        align point-for-point. Timestamps are unioned across a turbine's
        targets; a target missing at a timestamp yields explicit ``None``
        entries in both representations.
        """
        ewma_by_stream = {(s.turbine, s.target): s for s in ewma}
        targets = sorted({d.target for d in detections})
        frames: dict[str, list[pd.DataFrame]] = {}
        for detection in detections:
            key = (detection.turbine, detection.target)
            series = ewma_by_stream.get(key)
            if series is None:
                raise ConfigError(
                    "Detection stream has no matching EWMA stream",
                    turbine=detection.turbine,
                    target=detection.target,
                )
            if len(series.values) != len(detection.states):
                raise ConfigError(
                    "Detection and EWMA streams are misaligned",
                    turbine=detection.turbine,
                    target=detection.target,
                )
            frame = pd.DataFrame(
                {
                    f"state_{detection.target}": detection.states.to_numpy(),
                    f"value_{detection.target}": series.values.to_numpy(),
                },
                index=pd.Index(detection.timestamps, name="timestamp"),
            )
            frames.setdefault(detection.turbine, []).append(frame)

        states: list[CoordinatedState] = []
        for turbine in sorted(frames):
            joined = pd.concat(frames[turbine], axis=1, join="outer").sort_index()
            for timestamp, row in joined.iterrows():
                vector: dict[str, int | None] = {}
                continuous: dict[str, float | None] = {}
                for target in targets:
                    state: Any = row.get(f"state_{target}")
                    value: Any = row.get(f"value_{target}")
                    if state is None or pd.isna(state):
                        vector[target] = None
                        continuous[target] = None
                    else:
                        vector[target] = int(state)
                        continuous[target] = float(value)
                stamp: Any = timestamp
                states.append(
                    CoordinatedState(
                        timestamp_utc=pd.Timestamp(stamp),
                        turbine=turbine,
                        vector=vector,
                        continuous=continuous,
                    )
                )
        return states
