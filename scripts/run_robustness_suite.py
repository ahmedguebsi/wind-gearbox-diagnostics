"""Three experiments the minimum matrix requires and that had never been run.

Each is registered in `docs/EXPERIMENT_PROTOCOL.md` §4 and each closes a
question an examiner will ask. Nothing here changes the headline pipeline; the
arms are declared comparisons reported alongside it.

**B3 — fleet-median-only detector, no NBM at all.** The protocol lists it as
required and notes "an examiner will ask". It is the first-order sanity check
on the whole instrument: if deviation from the contemporaneous fleet median
detects as well as the full XGBoost pipeline, the NBM is not earning its
place. Implemented as leave-one-out (a turbine never contributes to the
reference it is judged against), normalized and thresholded through the SAME
machinery as the NBM residual so the comparison is of the SIGNAL, not of two
different detectors.

**S-seeds — multi-seed variance.** `docs/METHODOLOGY_REVIEW.md` §4 lists a
three-seed check as an "Add" item: without it there is no answer to whether
the XGBoost margin over the baseline exceeds seed noise. One seed was ever
run.

**A-multi — per-target versus multi-output.** PROJECT.md §18 requires
one-model-per-target as an ablation ("the thesis headline model is the
multi-target configuration"). The code path exists and is tested; it had never
been run on real data. For a thesis whose headline contribution is
MULTI-TARGET modelling, this is the ablation that isolates the contribution.

Every arm is a full in-memory pipeline run via `run_pipeline`; nothing is
persisted per arm. Results land in one JSON beside the named experiment.

Usage (from backend/):
    uv run python ../scripts/run_robustness_suite.py --arms b3 seeds multi_output
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from app.core.config import AppConfig  # noqa: E402
from app.core.versioning import capture_version_stamp  # noqa: E402
from app.data.schema import default_schema  # noqa: E402
from app.detection.matched_fpr import (  # noqa: E402
    CoordinatedPipeline,
    ObservationBasis,
    SingleSignalPipeline,
    matched_multiplier,
    sweep,
)
from app.evaluation.events import EVENT_001  # noqa: E402
from app.experiments.runner import run_pipeline  # noqa: E402
from app.residuals.engine import (  # noqa: E402
    NORMALIZED_RESIDUAL_COLUMN,
    RAW_RESIDUAL_COLUMN,
    TARGET_COLUMN,
    TIMESTAMP_COLUMN,
    TURBINE_COLUMN,
    ResidualFrame,
)
from app.residuals.ewma import (  # noqa: E402
    ControlLimitFormulation,
    ControlLimitSpec,
    EwmaDetector,
    GapHandling,
)
from app.residuals.fleet import leave_one_out_median  # noqa: E402
from app.residuals.normalization import PartitionRef, make_normalizer  # noqa: E402
from run_kelmarsh_experiment import kelmarsh_config, kelmarsh_inputs  # noqa: E402

#: The rung ADR-025 anchors on, re-matched per arm on that arm's own healthy
#: validation block. A fixed multiplier would compare arms at different
#: effective sensitivities.
FPR_RUNG = 10.0
MULTIPLIER_GRID = (
    tuple(round(1.0 + 0.25 * i, 2) for i in range(21))
    + tuple(round(6.5 + 0.5 * i, 1) for i in range(12))
    + tuple(float(m) for m in range(13, 41))
)


def _detector(config: AppConfig) -> EwmaDetector:
    return EwmaDetector(
        config.detection.ewma_lambda,
        ControlLimitSpec(
            sigma_multiplier=config.detection.control_limit_sigma,
            formulation=ControlLimitFormulation(config.detection.control_limit_formulation),
        ),
        gap_handling=GapHandling(config.detection.gap_handling),
    )


def _slice_rmse(result: Any) -> dict[str, dict[str, float]]:
    """Per-model RMSE on the ADR-022 headline slice."""
    nbm = result.metrics["nbm"]
    return {
        model: {
            target: round(float(values["rmse"]), 6)
            for target, values in nbm[model]["monitoring_healthy"].items()
        }
        for model in sorted(nbm)
        if "monitoring_healthy" in nbm[model]
    }


def _operating_point(series: list[Any], name: str, coordinated: bool) -> dict[str, Any]:
    """False-alarm curve on healthy validation, matched at the ADR-025 rung."""
    pipeline: Any
    if coordinated:
        pipeline = CoordinatedPipeline(name, series, min_coordinated=None)
    else:
        pipeline = SingleSignalPipeline(name, series, target=series[0].target)
    curve = sweep(pipeline, list(MULTIPLIER_GRID), ObservationBasis.ROW_TIME)
    multiplier = matched_multiplier(curve, FPR_RUNG)
    return {
        "pipeline": name,
        "matched_multiplier": multiplier,
        "reachable": multiplier is not None,
        "curve_head": [p.as_dict() for p in curve.points[:3]],
        "curve_tail": [p.as_dict() for p in curve.points[-3:]],
    }


# --------------------------------------------------------------------------
# B3 — fleet-median-only detector (NO normal behaviour model)
# --------------------------------------------------------------------------


def _fleet_deviation_frame(
    frame: pd.DataFrame, schema: Any, targets: tuple[str, ...]
) -> ResidualFrame:
    """Leave-one-out fleet deviation of the RAW target, with no model.

    This is the B3 signal: ``actual - median(peer turbines' actual at the same
    timestamp)``. It is deliberately shaped as a ResidualFrame so it flows
    through the identical normalizer, EWMA detector and matched-FPR sweep the
    NBM residual uses — the arms then differ ONLY in how the expected value
    was formed, which is the question B3 asks.

    Rows whose timestamp offers fewer than two peer turbines are dropped, the
    same rule ADR-029 binds the fleet-relative arm to.
    """
    parts: list[pd.DataFrame] = []
    for target in targets:
        wide = frame.pivot_table(
            index=schema.timestamp_name,
            columns=schema.turbine_id_name,
            values=target,
            aggfunc="first",
        )
        reference = leave_one_out_median(wide.to_numpy(dtype=float), min_peers=2)
        deviation = wide.to_numpy(dtype=float) - reference
        long = pd.DataFrame(deviation, index=wide.index, columns=wide.columns)
        long = long.reset_index().melt(
            id_vars=schema.timestamp_name,
            var_name=TURBINE_COLUMN,
            value_name=RAW_RESIDUAL_COLUMN,
        )
        actual = wide.reset_index().melt(
            id_vars=schema.timestamp_name,
            var_name=TURBINE_COLUMN,
            value_name="actual",
        )
        merged = long.merge(actual, on=[schema.timestamp_name, TURBINE_COLUMN], how="left")
        merged = merged[merged[RAW_RESIDUAL_COLUMN].notna()]
        merged = merged.rename(columns={schema.timestamp_name: TIMESTAMP_COLUMN})
        merged[TARGET_COLUMN] = target
        merged["prediction"] = merged["actual"] - merged[RAW_RESIDUAL_COLUMN]
        merged[NORMALIZED_RESIDUAL_COLUMN] = np.nan
        parts.append(merged)
    combined = pd.concat(parts, ignore_index=True)
    combined = combined.sort_values([TURBINE_COLUMN, TARGET_COLUMN, TIMESTAMP_COLUMN])
    return ResidualFrame(combined.reset_index(drop=True))


def arm_b3(config: AppConfig, inputs: Any) -> dict[str, Any]:
    """B3: does deviation from the fleet median detect as well as the NBM?"""
    schema = inputs.schema
    targets = inputs.feature.targets
    result = run_pipeline(config, inputs)

    boundary = result.split.boundaries_utc[0]
    healthy = result.healthy.frame
    partitions = {
        "training": healthy[healthy[schema.timestamp_name] < boundary],
        "validation": healthy[healthy[schema.timestamp_name] >= boundary],
    }

    out: dict[str, Any] = {"arm": "B3_fleet_median_only", "operating_points": {}}
    fleet_frames = {
        name: _fleet_deviation_frame(frame, schema, targets) for name, frame in partitions.items()
    }

    # Same normalizer family, same source partition, same detector as the NBM.
    normalizer = make_normalizer(config.residual.normalization)
    normalizer.fit(fleet_frames["training"], PartitionRef.HEALTHY_TRAINING)
    normalized = {k: normalizer.transform(v) for k, v in fleet_frames.items()}

    detector = _detector(config)
    detector.fit_control_limits(normalized["training"], PartitionRef.HEALTHY_TRAINING)
    fleet_series, _ = detector.detect(normalized["validation"])
    in_control = detector.characterize_in_control(normalized["validation"])
    out["in_control"] = in_control.as_dict()
    out["operating_points"]["fleet_coordinated"] = _operating_point(
        fleet_series, "fleet_coordinated", coordinated=True
    )

    # The NBM arm, measured through the identical machinery.
    nbm_detector = _detector(config)
    nbm_detector.fit_control_limits(
        result.residuals[config.residual.threshold_stats_source.value],
        PartitionRef(f"healthy_{config.residual.threshold_stats_source.value}"),
    )
    nbm_series, _ = nbm_detector.detect(result.residuals["validation"])
    out["operating_points"]["nbm_coordinated"] = _operating_point(
        nbm_series, "nbm_coordinated", coordinated=True
    )
    out["nbm_in_control"] = nbm_detector.characterize_in_control(
        result.residuals["validation"]
    ).as_dict()

    # Signal quality: the spread each expectation leaves behind, per target.
    out["signal_spread_celsius"] = {
        "fleet_median_only": {
            str(t): round(
                float(
                    fleet_frames["validation"]
                    .data.query(f"{TARGET_COLUMN} == @t")[RAW_RESIDUAL_COLUMN]
                    .std()
                ),
                4,
            )
            for t in targets
        },
        "nbm_residual": {
            str(t): round(
                float(
                    result.residuals["validation"]
                    .data.query(f"{TARGET_COLUMN} == @t")[RAW_RESIDUAL_COLUMN]
                    .std()
                ),
                4,
            )
            for t in targets
        },
    }
    out["interpretation_note"] = (
        "A fleet-median-only detector needs NO model, NO training period and "
        "NO tuning. If it reaches comparable false-alarm behaviour, the NBM's "
        "contribution is not established by the detection results alone."
    )
    return out


# --------------------------------------------------------------------------
# Seed variance and the multi-output ablation
# --------------------------------------------------------------------------


def arm_seeds(config: AppConfig, inputs: Any, seeds: tuple[int, ...]) -> dict[str, Any]:
    """Does the XGBoost margin over the baseline exceed seed noise?"""
    runs: dict[str, Any] = {}
    for seed in seeds:
        seeded = AppConfig.model_validate(
            {
                **config.model_dump(mode="python"),
                "model": {**config.model_dump()["model"], "seed": seed},
            }
        )
        runs[str(seed)] = _slice_rmse(run_pipeline(seeded, inputs))
    thesis = {
        target: [runs[s]["thesis"][target] for s in runs]
        for target in runs[str(seeds[0])]["thesis"]
    }
    baseline = {
        target: [runs[s]["baseline"][target] for s in runs]
        for target in runs[str(seeds[0])]["baseline"]
    }
    return {
        "arm": "S_seed_variance",
        "seeds": list(seeds),
        "per_seed_slice_rmse": runs,
        "summary": {
            target: {
                "thesis_mean": round(float(np.mean(values)), 6),
                "thesis_spread": round(float(max(values) - min(values)), 6),
                "baseline_mean": round(float(np.mean(baseline[target])), 6),
                "margin_over_baseline": round(
                    float(np.mean(baseline[target]) - np.mean(values)), 6
                ),
                "margin_exceeds_seed_spread": bool(
                    (np.mean(baseline[target]) - np.mean(values)) > (max(values) - min(values))
                ),
            }
            for target, values in thesis.items()
        },
        "interpretation_note": (
            "margin_exceeds_seed_spread is the question: a model advantage "
            "smaller than the spread across seeds is not an advantage."
        ),
    }


def arm_multi_output(config: AppConfig, inputs: Any) -> dict[str, Any]:
    """PROJECT.md §18 mode B: one model per target, as the declared ablation."""
    arms: dict[str, Any] = {}
    for label, multi in (("multi_output_headline", True), ("per_target_ablation", False)):
        payload = config.model_dump(mode="python")
        payload["model"]["multi_output"] = multi
        arms[label] = _slice_rmse(run_pipeline(AppConfig.model_validate(payload), inputs))
    return {
        "arm": "A_multi_output_vs_per_target",
        "slice_rmse": arms,
        "delta_headline_minus_ablation": {
            target: round(
                arms["multi_output_headline"]["thesis"][target]
                - arms["per_target_ablation"]["thesis"][target],
                6,
            )
            for target in arms["multi_output_headline"]["thesis"]
        },
        "interpretation_note": (
            "Negative delta = the multi-output configuration is better and the "
            "thesis's multi-target framing is doing work. Positive delta = the "
            "headline configuration is WORSE than modelling each target "
            "separately, which must be reported."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--downloads", type=Path, default=REPO_ROOT / "dataset")
    parser.add_argument("--artifacts", type=Path, default=REPO_ROOT / "artifacts")
    parser.add_argument("--experiment", default=None)
    parser.add_argument(
        "--arms",
        nargs="+",
        default=["b3", "seeds", "multi_output"],
        choices=["b3", "seeds", "multi_output"],
    )
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 7, 2024])
    args = parser.parse_args()

    experiment = (
        args.experiment or sorted(p.name for p in args.artifacts.glob("EXP-*") if p.is_dir())[-1]
    )
    out_dir = args.artifacts / experiment / "evaluation"
    out_dir.mkdir(parents=True, exist_ok=True)

    config = kelmarsh_config()
    inputs, _ = kelmarsh_inputs(
        args.downloads,
        supplier_note="Robustness/baseline suite (in-memory arms; nothing persisted per arm)",
        limitations_path=None,
    )

    # MERGE, never clobber. Arms cost 15-30 minutes each, so they are run in
    # separate invocations; a second invocation that rewrote the file from
    # scratch would destroy the first's results silently. Arms named in THIS
    # invocation are recomputed and replace their previous entries; arms not
    # named are carried forward with the timestamp of the run that produced
    # them, so the file never mixes results without saying so.
    path = out_dir / "robustness_suite.json"
    previous: dict[str, Any] = {}
    if path.is_file():
        previous = json.loads(path.read_text(encoding="utf-8"))
        for arm in previous.get("arms", {}).values():
            arm.setdefault("created_at_utc", previous.get("created_at_utc"))

    results: dict[str, Any] = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "base_experiment": experiment,
        "event_under_study": EVENT_001.code,
        "environment": capture_version_stamp(
            schema_version=default_schema().schema_version
        ).model_dump(),
        "arms": {k: v for k, v in previous.get("arms", {}).items() if k not in args.arms},
    }
    runners = {
        "b3": lambda: arm_b3(config, inputs),
        "seeds": lambda: arm_seeds(config, inputs, tuple(args.seeds)),
        "multi_output": lambda: arm_multi_output(config, inputs),
    }
    for name in args.arms:
        started = time.time()
        print(f"[{datetime.now(UTC):%H:%M:%S}] running arm {name}...", flush=True)
        try:
            results["arms"][name] = runners[name]()
        except Exception as error:  # recorded, never silently dropped
            traceback.print_exc()
            results["arms"][name] = {"arm": name, "FAILED": f"{type(error).__name__}: {error}"}
        results["arms"][name]["runtime_seconds"] = round(time.time() - started, 1)
        results["arms"][name]["created_at_utc"] = datetime.now(UTC).isoformat()
        print(f"    done in {results['arms'][name]['runtime_seconds']}s", flush=True)

    path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(json.dumps(results["arms"], indent=2, default=str)[:6000])
    print(f"\nWritten to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
