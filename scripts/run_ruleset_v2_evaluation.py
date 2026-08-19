"""The ADR-050 frozen evaluation of ruleset v2 over the monitoring stream.

STATUS: EXPLORATORY — post-hoc methodological refinement (ADR-050). The
pre-registered v1 outcome is reported FIRST, always: at the measured channel
correlation (r = 0.93-0.95) the v1 instantaneous match returned the same
undifferentiated candidate set on essentially every positive excursion
(LIM-030), and on EVENT-001 it reported "no candidate mechanism". Nothing
here amends that result; this evaluation asks whether the mode-coordinate
re-expression of the SAME signatures produces differentiated, physically
readable episode interpretations, under the ADR-049 eligibility gate.

Frozen spec provenance: the transformation, thresholds, persistence, timing
and eligibility were recorded in ADR-050 (commit c2c79d1, 2026-08-20) BEFORE
this driver existed; the implementation (app/fmea/modes_v2.py) was committed
before this evaluation ran. Chronology is provable from git history.

The chain is arm A6's, verbatim: per-channel sigma standardization fitted on
healthy TRAINING -> ADR-035 rotation -> the config normalizer family fitted
on training modes -> the config EWMA detector fitted on training modes ->
states on the monitoring stream. No parameter is introduced beyond ADR-050's
frozen values; every effective value is echoed into the output.

Reads STORED ARTIFACTS ONLY (plus packaged config defaults). Writes
``evaluation/ruleset_v2_evaluation.json`` and the untruncated episode table
``evaluation/ruleset_v2_episodes.csv``.

Usage (from backend/):
    uv run python ../scripts/run_ruleset_v2_evaluation.py --experiment EXP-YYYYMMDD-NNN
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import AppConfig  # noqa: E402
from app.core.versioning import capture_version_stamp  # noqa: E402
from app.data.schema import default_schema  # noqa: E402
from app.evaluation.events import EVENT_001  # noqa: E402
from app.evaluation.regime import REGIME_BOUNDARY_SOURCE, Regime, label_regime  # noqa: E402
from app.fmea.knowledge_base import FmeaKnowledgeBase, default_ruleset_path  # noqa: E402
from app.fmea.modes_v2 import (  # noqa: E402
    MODES_V2_VERSION,
    EpisodeInterpretation,
    ModeStateSeries,
    interpret_modes,
)
from app.residuals.engine import ResidualFrame  # noqa: E402
from app.residuals.ewma import (  # noqa: E402
    ControlLimitFormulation,
    ControlLimitSpec,
    EwmaDetector,
    GapHandling,
)
from app.residuals.modes import MODE_COMMON, MODE_DIFFERENTIAL, rotate_to_modes  # noqa: E402
from app.residuals.normalization import PartitionRef, SigmaNormalizer, make_normalizer  # noqa: E402

V1_RECAP = (
    "PRE-REGISTERED v1 OUTCOME, REPORTED FIRST (ADR-050 chronology "
    "condition): at cross-target residual correlation r = 0.932-0.952 the v1 "
    "instantaneous coordinated-state match cannot discriminate mechanisms — "
    "FMEA-001/002/004 fire together on essentially every positive excursion "
    "and FMEA-003's region is near-empty (LIM-030). On EVENT-001 the v1 "
    "interpreter reported 'no candidate mechanism' (LIM-036). This "
    "exploratory v2 evaluation amends the REPRESENTATION, never that result."
)


def _episode_row(interp: EpisodeInterpretation) -> dict[str, Any]:
    e = interp.episode
    return {
        "turbine": e.turbine,
        "start_utc": e.start_utc.isoformat(),
        "end_utc": e.end_utc.isoformat(),
        "n_samples": e.n_samples,
        "output_type": interp.output_type.value,
        "top_rule": interp.candidates[0].rule_id if interp.candidates else "",
        "top_mechanism": interp.candidates[0].mechanism if interp.candidates else "",
        "n_candidates": len(interp.candidates),
        "max_abs_c_ewma": round(e.max_abs_c, 4),
        "max_abs_d_ewma": round(e.max_abs_d, 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, default=REPO_ROOT / "artifacts")
    parser.add_argument("--experiment", default=None)
    args = parser.parse_args()

    experiment = args.experiment
    if experiment is None:
        candidates = sorted(p.name for p in args.artifacts.glob("EXP-*") if p.is_dir())
        if not candidates:
            raise SystemExit(f"No experiment directories under {args.artifacts}")
        experiment = candidates[-1]
    directory = args.artifacts / experiment

    config = AppConfig()
    kb = FmeaKnowledgeBase.load(default_ruleset_path())

    residuals = {
        partition: ResidualFrame(pd.read_parquet(directory / "residuals" / f"{partition}.parquet"))
        for partition in ("training", "test")
    }
    conditions = pd.read_parquet(directory / "evaluation" / "conditions.parquet")

    # --- The arm-A6 chain, verbatim -----------------------------------------
    standardizer = SigmaNormalizer()
    standardizer.fit(residuals["training"], PartitionRef.HEALTHY_TRAINING)
    modes = {}
    for partition in ("training", "test"):
        modes[partition], _ = rotate_to_modes(standardizer.transform(residuals[partition]))

    normalizer = make_normalizer(config.residual.normalization)
    normalizer.fit(modes["training"], PartitionRef.HEALTHY_TRAINING)
    normalized = {p: normalizer.transform(f) for p, f in modes.items()}

    detector = EwmaDetector(
        config.detection.ewma_lambda,
        ControlLimitSpec(
            sigma_multiplier=config.detection.control_limit_sigma,
            formulation=ControlLimitFormulation(config.detection.control_limit_formulation),
        ),
        gap_handling=GapHandling(config.detection.gap_handling),
    )
    detector.fit_control_limits(normalized["training"], PartitionRef.HEALTHY_TRAINING)
    ewma_series, detections = detector.detect(normalized["test"])

    # --- ADR-049 eligibility from the conditions frame ----------------------
    floor_kw = config.healthy_state.minimum_active_power_kw
    power = conditions.set_index(["turbine_id", "timestamp"])["active_power"]

    by_turbine: dict[str, dict[str, Any]] = {}
    for detection, series in zip(detections, ewma_series, strict=True):
        entry = by_turbine.setdefault(detection.turbine, {})
        entry[detection.target] = (detection, series)

    series_list: list[ModeStateSeries] = []
    for turbine in sorted(by_turbine):
        streams = by_turbine[turbine]
        if set(streams) != {MODE_COMMON, MODE_DIFFERENTIAL}:
            raise SystemExit(f"Turbine {turbine} lacks a mode stream: {sorted(streams)}")
        c_det, c_ewma = streams[MODE_COMMON]
        d_det, d_ewma = streams[MODE_DIFFERENTIAL]
        if not c_det.timestamps.reset_index(drop=True).equals(
            d_det.timestamps.reset_index(drop=True)
        ):
            raise SystemExit(f"ALIGNMENT FAILED: mode streams disagree on {turbine} timestamps")
        keys = pd.MultiIndex.from_arrays(
            [np.repeat(turbine, len(c_det.timestamps)), c_det.timestamps]
        )
        active_power = power.reindex(keys)
        if active_power.isna().all():
            raise SystemExit(f"JOIN FAILED: no conditions rows matched for {turbine}")
        regime = label_regime(active_power.reset_index(drop=True), floor_kw)
        series_list.append(
            ModeStateSeries(
                turbine=turbine,
                timestamps=c_det.timestamps.reset_index(drop=True),
                c_states=c_det.states.to_numpy(dtype=int),
                d_states=d_det.states.to_numpy(dtype=int),
                c_values=c_ewma.values.to_numpy(dtype=float),
                d_values=d_ewma.values.to_numpy(dtype=float),
                eligible=(regime == Regime.IN_REGIME.value).to_numpy(dtype=bool),
            )
        )

    # --- Interpret ----------------------------------------------------------
    min_samples = config.detection.persistence_min_samples
    report = interpret_modes(series_list, kb, min_samples)

    # --- Aggregates ----------------------------------------------------------
    rows = [_episode_row(i) for i in report.interpretations]
    frame = pd.DataFrame(rows)
    aggregates: dict[str, Any] = {}
    if len(frame):
        aggregates["episodes_by_type_and_turbine"] = {
            t: g.groupby("turbine").size().to_dict() for t, g in frame.groupby("output_type")
        }
        aggregates["episodes_by_top_rule"] = frame.groupby("top_rule").size().to_dict()
        aggregates["episode_length_samples"] = {
            t: {
                "median": float(g["n_samples"].median()),
                "p90": float(g["n_samples"].quantile(0.9)),
                "max": int(g["n_samples"].max()),
            }
            for t, g in frame.groupby("output_type")
        }
        eligible_total = report.coverage["n_eligible"]
        aggregates["episode_sample_share_of_eligible"] = round(
            float(frame["n_samples"].sum()) / eligible_total, 6
        )

    # --- EVENT-001 block (real-data abstention case, ADR-050 condition e) ---
    window_mask = (
        (frame["turbine"] == EVENT_001.turbine)
        & (pd.to_datetime(frame["start_utc"]) <= EVENT_001.end_utc)
        & (pd.to_datetime(frame["end_utc"]) >= EVENT_001.start_utc)
        if len(frame)
        else pd.Series(dtype=bool)
    )
    in_window = frame[window_mask] if len(frame) else frame
    positive_in_window = (
        in_window[in_window["output_type"] != "C_no_candidate"] if len(in_window) else in_window
    )
    event_block = {
        "event": f"{EVENT_001.code} {EVENT_001.turbine}",
        "window_utc": [EVENT_001.start_utc.isoformat(), EVENT_001.end_utc.isoformat()],
        "episodes_overlapping_window": len(in_window),
        "episodes_by_type": in_window.groupby("output_type").size().to_dict()
        if len(in_window)
        else {},
        "positive_candidate_episodes": len(positive_in_window),
        "reading": (
            "The system abstained from unsupported positive attribution."
            if len(positive_in_window) == 0
            else (
                "Episodes with positive candidates overlap the EVENT-001 window; "
                "they are reported as-is. EVENT-001's documented primary "
                "indicators lie outside the modelled signal set (LIM-036), so "
                "overlap is not confirmation."
            )
        ),
    }

    # --- Write ----------------------------------------------------------------
    csv_path = directory / "evaluation" / "ruleset_v2_episodes.csv"
    frame.to_csv(csv_path, index=False)
    top = sorted(report.interpretations, key=lambda i: -i.episode.n_samples)[:25]
    output = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "experiment_id": experiment,
        "status": "EXPLORATORY — post-hoc methodological refinement (ADR-050)",
        "v1_outcome_reported_first": V1_RECAP,
        "environment": capture_version_stamp(
            schema_version=default_schema().schema_version
        ).model_dump(),
        "frozen_spec": {
            "modes_version": MODES_V2_VERSION,
            "knowledge_base": kb.ruleset_version,
            "standardization": "per-channel sigma, healthy TRAINING only (ADR-035 a/d)",
            "mode_normalizer": config.residual.normalization.value,
            "ewma_lambda": config.detection.ewma_lambda,
            "control_limit_sigma": config.detection.control_limit_sigma,
            "control_limit_formulation": config.detection.control_limit_formulation,
            "gap_handling": config.detection.gap_handling,
            "persistence_min_samples": min_samples,
            "eligibility": {
                "floor_kw": floor_kw,
                "source": REGIME_BOUNDARY_SOURCE,
                "rule": "ADR-049: withheld samples cannot start, extend or bridge episodes",
            },
        },
        "summary": report.as_dict(),
        "aggregates": aggregates,
        "event_001": event_block,
        "largest_episodes": [i.as_dict() for i in top],
        "episode_table": csv_path.name,
        "standing_limits": (
            "Detection value of the modes remains UNTESTED (ADR-035 condition "
            "c); n(maintenance-confirmed faults) = 0, so no output here is a "
            "validated diagnosis; eligibility is not a success rate (ADR-049)."
        ),
    }
    out_path = directory / "evaluation" / "ruleset_v2_evaluation.json"
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps({k: output[k] for k in ("summary", "aggregates", "event_001")}, indent=2))
    print(f"\nWritten to {out_path} and {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
