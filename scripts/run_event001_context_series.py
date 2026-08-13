"""Descriptive context series for the EVENT-001 Chapter 5 discussion (LIM-010).

Author-ordered 2026-08-13. DESCRIPTIVE ONLY: series and descriptive
statistics — no judgment, no anomaly designation. Purpose: make the icing
episode (2019-02-03), the ADR-025 PRIMARY detection (2019-02-11 17:10),
and the code-1860 onset (2019-02-24 16:46) visible in one series, for
Kelmarsh 1 and — the fleet-coherence principle applied to residuals — for
the other five turbines over the same period.

Outputs (additive):
    plots/event001_context_k1.png            Kelmarsh 1, both targets
    plots/event001_context_fleet_<target>.png six turbines per target
    evaluation/event001_context_stats.json   per-turbine/-target/-window stats

Usage (from backend/):
    uv run python ../scripts/run_event001_context_series.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import ThresholdStatsSource  # noqa: E402
from app.core.versioning import capture_version_stamp  # noqa: E402
from app.data.schema import default_schema  # noqa: E402
from app.residuals.engine import (  # noqa: E402
    NORMALIZED_RESIDUAL_COLUMN,
    TARGET_COLUMN,
    TIMESTAMP_COLUMN,
    TURBINE_COLUMN,
    ResidualFrame,
)
from app.residuals.ewma import ControlLimitFormulation, ControlLimitSpec, EwmaDetector  # noqa: E402
from app.residuals.normalization import partition_for  # noqa: E402

LAMBDA = 0.2  # ADR-025 selected lambda
PRIMARY_COORD_MULTIPLIER = 10.0528726307873  # reference limits only (ADR-025)
PERIOD = (pd.Timestamp("2019-01-15", tz="UTC"), pd.Timestamp("2019-03-10", tz="UTC"))
ICING = (
    pd.Timestamp("2019-02-03 04:00:30", tz="UTC"),
    pd.Timestamp("2019-02-03 13:42:30", tz="UTC"),
)
DETECTION = pd.Timestamp("2019-02-11 17:10:00", tz="UTC")  # ADR-025 PRIMARY coordinated
ONSET = pd.Timestamp("2019-02-24 16:46:28", tz="UTC")
EVENT_TURBINE = "Kelmarsh 1"

#: Sub-windows for descriptive statistics (labels are period names only).
WINDOWS = (
    ("pre_icing", PERIOD[0], ICING[0]),
    ("icing_to_detection", ICING[0], DETECTION),
    ("detection_to_onset", DETECTION, ONSET),
    ("post_onset", ONSET, PERIOD[1]),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", default="EXP-20260813-002")
    parser.add_argument("--artifacts", type=Path, default=REPO_ROOT / "artifacts")
    args = parser.parse_args()
    directory = args.artifacts / args.experiment

    schema = default_schema()
    residual_frames = {
        partition: ResidualFrame(pd.read_parquet(directory / "residuals" / f"{partition}.parquet"))
        for partition in ("training", "test")
    }
    detector = EwmaDetector(
        LAMBDA,
        ControlLimitSpec(sigma_multiplier=3.0, formulation=ControlLimitFormulation.STEADY_STATE),
    )
    detector.fit_control_limits(
        residual_frames["training"], partition_for(ThresholdStatsSource.TRAINING)
    )
    test_series, _ = detector.detect(residual_frames["test"])
    raw = residual_frames["test"].data

    targets = sorted({s.target for s in test_series})
    turbines = sorted({s.turbine for s in test_series})
    scale = PRIMARY_COORD_MULTIPLIER / 3.0

    def window_slice(series_index: pd.Series, values: pd.Series) -> tuple[pd.Series, pd.Series]:
        mask = (series_index >= PERIOD[0]) & (series_index <= PERIOD[1])
        return series_index[mask.to_numpy()], values[mask.to_numpy()]

    def draw_panel(ax: plt.Axes, turbine: str, target: str) -> None:
        stream = next(s for s in test_series if s.turbine == turbine and s.target == target)
        stamps, ewma = window_slice(stream.timestamps, stream.values)
        _, upper = window_slice(stream.timestamps, stream.upper)
        _, lower = window_slice(stream.timestamps, stream.lower)
        rows = raw[(raw[TURBINE_COLUMN] == turbine) & (raw[TARGET_COLUMN] == target)]
        rows = rows[(rows[TIMESTAMP_COLUMN] >= PERIOD[0]) & (rows[TIMESTAMP_COLUMN] <= PERIOD[1])]
        ax.plot(
            rows[TIMESTAMP_COLUMN],
            rows[NORMALIZED_RESIDUAL_COLUMN],
            lw=0.4,
            alpha=0.45,
            label="normalized residual",
        )
        ax.plot(stamps, ewma, lw=1.4, label=f"EWMA (lambda={LAMBDA})")
        ax.plot(stamps, upper * scale, ls="--", lw=0.8, label="PRIMARY reference limits")
        ax.plot(stamps, lower * scale, ls="--", lw=0.8)
        ax.axvspan(ICING[0], ICING[1], alpha=0.25, color="tab:cyan", label="icing episode")
        ax.axvline(DETECTION, ls=":", lw=1.2, color="tab:orange", label="PRIMARY detection")
        ax.axvline(ONSET, ls="-", lw=1.2, color="tab:red", label="code-1860 onset")
        ax.set_ylabel(f"{turbine}\n{target.split('_')[1]}", fontsize=8)
        ax.tick_params(labelsize=7)

    plots_dir = directory / "plots"
    plots_dir.mkdir(exist_ok=True)

    # Kelmarsh 1: both targets in one figure.
    fig, axes = plt.subplots(2, 1, figsize=(13, 6), sharex=True)
    for ax, target in zip(axes, targets, strict=True):
        draw_panel(ax, EVENT_TURBINE, target)
    axes[0].legend(fontsize=7, ncol=3, loc="upper left")
    fig.suptitle(
        "EVENT-001 context, Kelmarsh 1 (descriptive; reference limits are the "
        "ADR-025 PRIMARY coordinated multiplier)",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(plots_dir / "event001_context_k1.png", dpi=150)
    plt.close(fig)

    # Fleet figures: one per target, six turbine panels.
    for target in targets:
        fig, axes = plt.subplots(len(turbines), 1, figsize=(13, 14), sharex=True)
        for ax, turbine in zip(axes, turbines, strict=True):
            draw_panel(ax, turbine, target)
        axes[0].legend(fontsize=7, ncol=3, loc="upper left")
        fig.suptitle(
            f"EVENT-001 context, fleet, {target} (descriptive; markers are "
            "Kelmarsh 1 event times, drawn on every panel for time reference)",
            fontsize=10,
        )
        fig.tight_layout()
        fig.savefig(plots_dir / f"event001_context_fleet_{target.split('_')[1]}.png", dpi=150)
        plt.close(fig)

    # Descriptive statistics per turbine / target / sub-window.
    stats: dict[str, dict[str, dict[str, dict[str, float | int | None]]]] = {}
    for turbine in turbines:
        stats[turbine] = {}
        for target in targets:
            stream = next(s for s in test_series if s.turbine == turbine and s.target == target)
            frame = pd.DataFrame(
                {"ts": stream.timestamps.to_numpy(), "ewma": stream.values.to_numpy()}
            )
            rows = raw[(raw[TURBINE_COLUMN] == turbine) & (raw[TARGET_COLUMN] == target)]
            stats[turbine][target] = {}
            for label, start, end in WINDOWS:
                seg = frame[(frame["ts"] >= start) & (frame["ts"] < end)]["ewma"]
                res = rows[(rows[TIMESTAMP_COLUMN] >= start) & (rows[TIMESTAMP_COLUMN] < end)][
                    NORMALIZED_RESIDUAL_COLUMN
                ]
                stats[turbine][target][label] = {
                    "n": len(seg),
                    "ewma_mean": round(float(seg.mean()), 4) if len(seg) else None,
                    "ewma_max": round(float(seg.max()), 4) if len(seg) else None,
                    "ewma_min": round(float(seg.min()), 4) if len(seg) else None,
                    "abs_residual_max": (
                        round(float(res.abs().max()), 4) if res.notna().any() else None
                    ),
                }

    payload = {
        "experiment_id": args.experiment,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "basis": (
            "Descriptive context for the LIM-010 Chapter 5 discussion — series "
            "and descriptive statistics only; no judgment, no anomaly "
            "designation. Windows are period labels, not classifications."
        ),
        "period_utc": [str(PERIOD[0]), str(PERIOD[1])],
        "markers": {
            "icing_episode_utc": [str(ICING[0]), str(ICING[1])],
            "primary_detection_utc": str(DETECTION),
            "code_1860_onset_utc": str(ONSET),
        },
        "windows": {label: [str(a), str(b)] for label, a, b in WINDOWS},
        "stats": stats,
        "environment": capture_version_stamp(schema_version=schema.schema_version).model_dump(),
    }
    out_path = directory / "evaluation" / "event001_context_stats.json"
    out_path.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")

    # Console: EWMA means per window, all turbines, both targets.
    for target in targets:
        print(f"\n=== {target} — EWMA mean per window ===")
        header = "turbine".ljust(12) + "".join(label.rjust(22) for label, _, _ in WINDOWS)
        print(header)
        for turbine in turbines:
            cells = "".join(
                str(stats[turbine][target][label]["ewma_mean"]).rjust(22) for label, _, _ in WINDOWS
            )
            print(turbine.ljust(12) + cells)
    print(f"\nStats written to {out_path}")
    print(f"Plots written to {plots_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
