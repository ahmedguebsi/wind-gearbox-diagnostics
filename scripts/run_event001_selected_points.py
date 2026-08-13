"""EVENT-001 at the ADR-025 selected operating points (ADR-016 SECONDARY criterion).

DESCRIPTIVE ONLY — `inferential_allowed` is false (ADR-014): the output is
two timestamps and their difference for one episode, never a capability
claim. Derivation follows ADR-017: a detection is the START of a persistent
exceedance (>= persistence_min_samples consecutive alarmed samples) falling
within [event_start - 14 days, event_start]; leads are quantised to the
10-minute grid.

Points derive from the stored matched-FPR sweep (single source of truth for
the interpolated multipliers), per ADR-025:
- PRIMARY (lambda 0.2, matched at 10 FA/turbine-year on validation):
  coordinated and single_union, each at its own matched multiplier.
- SECONDARY (lambda 0.2, slice-calibrated at 10 FA/turbine-year):
  coordinated at its slice-matched multiplier; single_union is UNREACHABLE
  at that rate (a result, ADR-025), so the union contrast is reported AT
  THE SAME MULTIPLIER, explicitly labelled not-rate-matched.

Writes evaluation/event001_at_selected_points.json (additive).

Usage (from backend/):
    uv run python ../scripts/run_event001_selected_points.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import ThresholdStatsSource  # noqa: E402
from app.core.versioning import capture_version_stamp  # noqa: E402
from app.data.schema import default_schema  # noqa: E402
from app.detection.matched_fpr import CoordinatedPipeline, DetectionPipeline  # noqa: E402
from app.evaluation.events import EVENT_001  # noqa: E402
from app.residuals.engine import ResidualFrame  # noqa: E402
from app.residuals.ewma import ControlLimitFormulation, ControlLimitSpec, EwmaDetector  # noqa: E402
from app.residuals.normalization import partition_for  # noqa: E402

LAMBDA = 0.2  # ADR-025: both selected points sit at the pre-registered default
FPR_RUNG = 10.0  # ADR-025: 10 FA/turbine-year, validation- and slice-matched
WINDOW_DAYS = 14  # ADR-017(a)
PERSISTENCE = 3  # ADR-017(b)


def persistent_starts(flags: pd.Series) -> list[pd.Timestamp]:
    """Start timestamps of runs of >= PERSISTENCE consecutive alarmed samples."""
    values = flags.to_numpy(dtype=bool)
    starts: list[pd.Timestamp] = []
    run = 0
    for i, alarmed in enumerate(values):
        if alarmed:
            run += 1
            if run == PERSISTENCE:
                starts.append(flags.index[i - PERSISTENCE + 1])
        else:
            run = 0
    return starts


def derive(pipeline: DetectionPipeline, multiplier: float) -> dict[str, object]:
    """ADR-017 derivation for EVENT-001's turbine at one multiplier."""
    flags = pipeline.alarm_flags(multiplier)[EVENT_001.turbine]
    window_start = EVENT_001.start_utc - pd.Timedelta(days=WINDOW_DAYS)
    starts = persistent_starts(flags)
    in_window = [t for t in starts if window_start <= t <= EVENT_001.start_utc]
    detection_time = in_window[0] if in_window else None
    lead_minutes = (
        float((EVENT_001.start_utc - detection_time).total_seconds() / 60.0)
        if detection_time is not None
        else None
    )
    active_at_window_open = bool(
        flags.loc[flags.index >= window_start].iloc[:PERSISTENCE].all()
    ) and bool(len(flags.loc[flags.index >= window_start]) >= PERSISTENCE)
    return {
        "multiplier": multiplier,
        "event_start_utc": str(EVENT_001.start_utc),
        "window_start_utc": str(window_start),
        "detection_time_utc": str(detection_time) if detection_time is not None else None,
        "matched": detection_time is not None,
        "lead_time_minutes": lead_minutes,
        "lead_time_days": round(lead_minutes / 1440.0, 2) if lead_minutes is not None else None,
        "lead_time_quantisation_minutes": 10,
        "n_persistent_starts_in_window": len(in_window),
        "already_alarming_at_window_open": active_at_window_open,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", default="EXP-20260813-002")
    parser.add_argument("--artifacts", type=Path, default=REPO_ROOT / "artifacts")
    args = parser.parse_args()
    directory = args.artifacts / args.experiment
    sweep_path = directory / "evaluation" / "matched_fpr_sweep.json"
    sweep = json.loads(sweep_path.read_text(encoding="utf-8"))
    block = sweep["lambdas"][str(LAMBDA)]
    primary_row = next(
        r for r in block["matched_detail"] if r["fpr_target"] == FPR_RUNG and r.get("reachable")
    )
    slice_row = next(
        e for e in block["slice_calibration"]["matched"] if e["fpr_target"] == FPR_RUNG
    )
    m_primary_union = float(primary_row["single_union"]["multiplier"])
    m_primary_coord = float(primary_row["coordinated"]["multiplier"])
    assert not slice_row["single_union"].get("reachable"), (
        "ADR-025 recorded single_union as unreachable at the SECONDARY rung; "
        "the stored sweep disagrees — investigate before deriving."
    )
    m_secondary_coord = float(slice_row["coordinated"]["multiplier"])

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
    union = CoordinatedPipeline("single_union", test_series, min_coordinated=1)
    coordinated = CoordinatedPipeline("coordinated", test_series, min_coordinated=None)

    payload = {
        "experiment_id": args.experiment,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "inferential_allowed": False,
        "basis": (
            "ADR-016 SECONDARY criterion: two timestamps and their difference "
            "for one episode — a factual observation, not a capability claim. "
            "ADR-017 matching (14-day window, persistence >= 3, 10-minute "
            "quantisation). Points per ADR-025."
        ),
        "event": {
            "code": EVENT_001.code if hasattr(EVENT_001, "code") else "1860",
            "turbine": EVENT_001.turbine,
            "start_utc": str(EVENT_001.start_utc),
        },
        "primary": {
            "label": "PRIMARY (ADR-025): lambda 0.2, matched at 10 FA/ty on validation",
            "coordinated": derive(coordinated, m_primary_coord),
            "single_union_contrast": derive(union, m_primary_union),
        },
        "secondary": {
            "label": (
                "SECONDARY (ADR-025): lambda 0.2, slice-calibrated at 10 FA/ty — "
                "weaker independence claim (monitoring-period healthy data)"
            ),
            "coordinated": derive(coordinated, m_secondary_coord),
            "single_union_contrast_same_multiplier": derive(union, m_secondary_coord)
            | {
                "label": (
                    "NOT RATE-MATCHED: single_union is unreachable at 10 FA/ty on "
                    "the slice (ADR-025 result); reported at the same multiplier "
                    "for contrast only"
                )
            },
        },
        "environment": capture_version_stamp(schema_version=schema.schema_version).model_dump(),
    }
    out_path = directory / "evaluation" / "event001_at_selected_points.json"
    out_path.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    print(json.dumps(payload, indent=1, default=str))
    print(f"\nWritten to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
