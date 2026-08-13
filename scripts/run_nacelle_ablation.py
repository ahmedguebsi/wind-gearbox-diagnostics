"""ADR-027 nacelle-temperature ablation (specified before execution).

Varied: the predictor set — with and without ``nacelle_temperature``
(refit, full pipeline, ADR-021 tuning inside). Compared: the ADR-022 RQ1
three-period table, both targets, with blocked-bootstrap CIs and
Diebold-Mariano per §19. Conclusion label: whether the RQ1 slice ordering
(XGBoost vs baseline) holds in both configurations.

The WITH arm is the standing headline experiment (bit-identical
configuration), so its stored results are reused, not re-run. The WITHOUT
arm runs as a stored experiment of its own (full provenance, reproducible)
with ``limitations_path=None`` — its in-control inflation is the known
LIM-017/019 phenomenon and an ablation arm must not append duplicate
register entries. A separate labelled ABLATION per ADR-027: explicitly
NOT part of the M-27 provisional-parameter suite.

Usage (from backend/):
    uv run python ../scripts/run_nacelle_ablation.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from app.core.versioning import capture_version_stamp  # noqa: E402
from app.data.schema import NACELLE_TEMPERATURE, default_schema  # noqa: E402
from app.experiments.runner import run_experiment  # noqa: E402
from app.experiments.store import ArtifactStore  # noqa: E402
from run_kelmarsh_experiment import (  # noqa: E402
    kelmarsh_config,
    kelmarsh_inputs,
    three_period_rq1,
)


def slice_ordering(nbm: dict, targets: tuple[str, ...]) -> dict[str, str]:
    return {
        target: (
            "xgb"
            if nbm["thesis"]["monitoring_healthy"][target]["rmse"]
            < nbm["baseline"]["monitoring_healthy"][target]["rmse"]
            else "baseline"
        )
        for target in targets
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--downloads", type=Path, default=Path(r"C:\Users\mokhles.khedhri.993\Downloads")
    )
    parser.add_argument("--artifacts", type=Path, default=REPO_ROOT / "artifacts")
    parser.add_argument("--with-arm", default="EXP-20260813-002")
    args = parser.parse_args()

    schema = default_schema()
    with_dir = args.artifacts / args.with_arm
    with_summary = json.loads(
        (with_dir / "evaluation" / "first_run_summary.json").read_text(encoding="utf-8")
    )
    with_metrics = json.loads((with_dir / "metrics.json").read_text(encoding="utf-8"))

    config = kelmarsh_config()
    inputs, _stats = kelmarsh_inputs(
        args.downloads,
        supplier_note=(
            "ADR-027 nacelle-temperature ablation, WITHOUT arm (predictor set "
            f"minus {NACELLE_TEMPERATURE}); WITH arm is {args.with_arm}; "
            "author-specified 2026-08-13"
        ),
        limitations_path=None,
    )
    predictors_without = tuple(p for p in inputs.feature.predictors if p != NACELLE_TEMPERATURE)
    if len(predictors_without) == len(inputs.feature.predictors):
        raise SystemExit(f"{NACELLE_TEMPERATURE} is not in the standing predictor set")
    inputs, _stats = kelmarsh_inputs(
        args.downloads,
        supplier_note=inputs.supplier_note,
        limitations_path=None,
        predictors_override=predictors_without,
    )
    targets = inputs.feature.targets

    print(f"Running WITHOUT arm ({len(predictors_without)} predictors)...")
    store = ArtifactStore(args.artifacts)
    experiment_id, result = run_experiment(config, inputs, store)
    directory = store.experiment_dir(experiment_id)
    print(f"WITHOUT arm persisted as {experiment_id}")

    print("Computing three-period CIs and DM for the WITHOUT arm...")
    rq1_without, dm_without, _frames = three_period_rq1(result, schema, targets)

    ordering_with = slice_ordering(with_metrics["nbm"], targets)
    ordering_without = slice_ordering(result.metrics["nbm"], targets)
    holds = ordering_with == ordering_without and all(v == "xgb" for v in ordering_with.values())

    payload = {
        "adr": "ADR-027",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "with_arm_experiment": args.with_arm,
        "without_arm_experiment": experiment_id,
        "predictors_without": list(predictors_without),
        "conclusion": {
            "label": ("slice_ordering_holds_in_both" if holds else "slice_ordering_does_not_hold"),
            "slice_ordering_with": ordering_with,
            "slice_ordering_without": ordering_without,
        },
        "rq1_three_period_with_cis": {
            "with": with_summary["rq1_metrics_with_cis"],
            "without": rq1_without,
        },
        "dm_thesis_vs_baseline": {
            "with": with_summary["dm_thesis_vs_baseline_squared_error"],
            "without": dm_without,
        },
        "rq1_slice_counts": {
            "with": with_metrics["rq1"],
            "without": result.metrics["rq1"],
        },
        "environment": capture_version_stamp(schema_version=schema.schema_version).model_dump(),
    }
    out_path = directory / "evaluation" / "nacelle_ablation.json"
    out_path.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")

    print(f"\nConclusion: {payload['conclusion']['label']}")
    print(f"  with:    {ordering_with}")
    print(f"  without: {ordering_without}")
    for period in ("monitoring_healthy", "validation", "test"):
        for target in targets:
            w = with_summary["rq1_metrics_with_cis"][period]["thesis"][target]["rmse"]
            wo = rq1_without[period]["thesis"][target]["rmse"]
            print(
                f"  {period:20} {target.split('_')[1]:8} XGB RMSE "
                f"with {w['point']:.4f} [{w['lower']:.3f},{w['upper']:.3f}] | "
                f"without {wo['point']:.4f} [{wo['lower']:.3f},{wo['upper']:.3f}]"
            )
    print(f"\nWritten to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
