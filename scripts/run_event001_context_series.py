"""Descriptive context series for the EVENT-001 Chapter 5 discussion (LIM-010).

Author-ordered 2026-08-13. DESCRIPTIVE ONLY: series and descriptive
statistics — no judgment, no anomaly designation. Purpose: make the icing
episode (2019-02-03), the matched coordinated detection, and the code-1860
onset (2019-02-24 16:46) visible in one series, for Kelmarsh 1 and — the
fleet-coherence principle applied to residuals — for the other five turbines
over the same period.

OPERATING POINT. The reference limits and the detection marker are READ FROM
THE EXPERIMENT'S STORED ARTIFACTS, never hardcoded: the re-matched
coordinated multiplier at the 10 FA/turbine-year rung comes from
``robustness_suite.json`` (ADR-028 row-time basis), and the detection time is
the code-1860 onset minus the persistence-qualifying matched lead recorded by
the M-27 suite (``sensitivity_suite.json``, nominal configuration). LIM-039
binds the citation: the nominal 3.0-sigma single-sample excursion is NOT a
qualifying detection and its lead is never drawn or quoted here.

Outputs (additive):
    plots/event001_context_k1.png            Kelmarsh 1, both targets
    plots/event001_context_fleet_<target>.png six turbines per target
    evaluation/event001_context_stats.json   per-turbine/-target/-window stats

Usage (from backend/):
    uv run python ../scripts/run_event001_context_series.py --experiment EXP-YYYYMMDD-NNN
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
PERIOD = (pd.Timestamp("2019-01-15", tz="UTC"), pd.Timestamp("2019-03-10", tz="UTC"))
ICING = (
    pd.Timestamp("2019-02-03 04:00:30", tz="UTC"),
    pd.Timestamp("2019-02-03 13:42:30", tz="UTC"),
)
ONSET = pd.Timestamp("2019-02-24 16:46:28", tz="UTC")  # code 1860, ADR-013
EVENT_TURBINE = "Kelmarsh 1"
#: The M-27 nominal value of detection.control_limit_sigma — used only to
#: locate the nominal configuration inside the stored sensitivity sweep.
NOMINAL_SIGMA = 3.0


def _matched_operating_point(directory: Path) -> tuple[float, float]:
    """(re-matched coordinated multiplier, qualifying lead in minutes).

    Both from stored artifacts. A missing artifact is a hard stop — this
    script must never fall back to an operating point from another
    experiment's sweep (that hardcoded constant is how the original outputs
    came to describe a deleted experiment).
    """
    suite_path = directory / "evaluation" / "robustness_suite.json"
    sens_path = directory / "evaluation" / "sensitivity_suite.json"
    if not suite_path.is_file() or not sens_path.is_file():
        raise SystemExit(
            f"Missing {suite_path.name} or {sens_path.name} under {directory / 'evaluation'}; "
            "run run_robustness_suite.py --arms orthogonal and run_sensitivity_suite.py first"
        )
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    multiplier = suite["arms"]["orthogonal"]["operating_points"]["raw_coordinated_2of2"][
        "matched_multiplier"
    ]
    sensitivity = json.loads(sens_path.read_text(encoding="utf-8"))
    sweep = next(
        s
        for s in sensitivity["report"]["sweeps"]
        if s["parameter"] == "detection.control_limit_sigma"
    )
    outcome = sweep["outcomes"][sweep["values"].index(NOMINAL_SIGMA)]
    if outcome["event"]["label"] != "matched":
        raise SystemExit("Nominal sensitivity outcome has no matched EVENT-001 detection")
    return float(multiplier), float(outcome["event"]["lead_minutes"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", default=None)
    parser.add_argument("--artifacts", type=Path, default=REPO_ROOT / "artifacts")
    args = parser.parse_args()
    experiment = args.experiment
    if experiment is None:
        candidates = sorted(p.name for p in args.artifacts.glob("EXP-*") if p.is_dir())
        if not candidates:
            raise SystemExit(f"No experiment directories under {args.artifacts}")
        experiment = candidates[-1]
    args.experiment = experiment
    directory = args.artifacts / experiment

    matched_multiplier, lead_minutes = _matched_operating_point(directory)
    detection = ONSET - pd.Timedelta(minutes=lead_minutes)
    #: Sub-windows for descriptive statistics (labels are period names only).
    windows = (
        ("pre_icing", PERIOD[0], ICING[0]),
        ("icing_to_detection", ICING[0], detection),
        ("detection_to_onset", detection, ONSET),
        ("post_onset", ONSET, PERIOD[1]),
    )

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
    scale = matched_multiplier / 3.0

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
        ax.plot(
            stamps,
            upper * scale,
            ls="--",
            lw=0.8,
            label=f"matched coordinated limits (x{matched_multiplier:.2f})",
        )
        ax.plot(stamps, lower * scale, ls="--", lw=0.8)
        ax.axvspan(ICING[0], ICING[1], alpha=0.25, color="tab:cyan", label="icing episode")
        ax.axvline(
            detection,
            ls=":",
            lw=1.2,
            color="tab:orange",
            label="matched detection (persistence-qualifying)",
        )
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
        "EVENT-001 context, Kelmarsh 1 — descriptive only (ADR-014: single event, no "
        "inferential claim).\nReference limits: the re-matched 10 FA/turbine-year coordinated "
        f"multiplier ({matched_multiplier:.2f}); detection marker: its persistence-qualifying "
        f"matched detection, lead {lead_minutes:,.0f} min (LIM-026 and LIM-039 apply).",
        fontsize=8,
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
            for label, start, end in windows:
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
            "matched_detection_utc": str(detection),
            "matched_multiplier": matched_multiplier,
            "matched_lead_minutes": lead_minutes,
            "code_1860_onset_utc": str(ONSET),
        },
        "windows": {label: [str(a), str(b)] for label, a, b in windows},
        "stats": stats,
        "environment": capture_version_stamp(schema_version=schema.schema_version).model_dump(),
    }
    out_path = directory / "evaluation" / "event001_context_stats.json"
    out_path.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")

    # Console: EWMA means per window, all turbines, both targets.
    for target in targets:
        print(f"\n=== {target} — EWMA mean per window ===")
        header = "turbine".ljust(12) + "".join(label.rjust(22) for label, _, _ in windows)
        print(header)
        for turbine in turbines:
            cells = "".join(
                str(stats[turbine][target][label]["ewma_mean"]).rjust(22) for label, _, _ in windows
            )
            print(turbine.ljust(12) + cells)
    print(f"\nStats written to {out_path}")
    print(f"Plots written to {plots_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
