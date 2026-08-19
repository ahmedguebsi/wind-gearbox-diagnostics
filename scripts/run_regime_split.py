"""Report every error and detection figure SPLIT by operating regime.

LIM-034 mitigation (a), and the prerequisite for the Chesterman dual-criterion
reporting in the same output. Reads STORED ARTIFACTS ONLY — no refit, no
re-ingestion, no dataset access — so it can be re-run in seconds against any
completed experiment and cannot silently disagree with the run it describes.

What it produces (``evaluation/regime_split.json``):

1. ACCURACY BY REGIME. RMSE/MAE/R2/bias per model per target, split at the
   healthy-state active-power floor, with each regime's share of rows AND of
   total squared residual — the pair that makes LIM-034's "17.9% of rows,
   50.4% of variance" a statement about leverage.

2. SEPARATION (delta-PE). Chesterman et al. (2023) evaluate a normal
   behaviour model on two things at once: small error on healthy data and
   LARGE error on unhealthy data. Reported WITHIN regime, because across the
   whole stream the quantity is dominated by extrapolation rather than by
   degradation response.

3. EXCEEDANCE CENSUS BY REGIME AND DIRECTION. Turns LIM-034's proposed
   mechanism for the LIM-026 cold-side match into a measurement.

4. A STRUCTURAL NOTE on what this split does NOT explain — see the
   ``in_control_scope`` block, which is the honest half of the result.

Usage (from backend/):
    uv run python ../scripts/run_regime_split.py --experiment EXP-20260818-001
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.core.config import ThresholdStatsSource  # noqa: E402
from app.core.versioning import capture_version_stamp  # noqa: E402
from app.evaluation.regime import (  # noqa: E402
    REGIME_BOUNDARY_SOURCE,
    Regime,
    exceedance_census,
    label_regime,
    regime_slices,
    separation,
)
from app.residuals.engine import ResidualFrame  # noqa: E402
from app.residuals.ewma import (  # noqa: E402
    ControlLimitFormulation,
    ControlLimitSpec,
    EwmaDetector,
    GapHandling,
)
from app.residuals.normalization import partition_for  # noqa: E402

TARGET_COLUMN = "target"
KEY_COLUMNS = ["timestamp", "turbine_id"]


def _load_conditions(directory: Path, models: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Conditions keyed by the cleaned-frame row index, VERIFIED not assumed.

    ``conditions.parquet`` is written with ``index=False`` from the same
    ``cleaned.frame.loc[split.test]`` selection the prediction frames come
    from, so the two are positionally aligned. Positional alignment is an
    assumption, and an assumption that silently mis-joins would corrupt every
    number below — so it is checked against an independent path (the key-joined
    residual frame) by the caller before use.
    """
    conditions = pd.read_parquet(directory / "evaluation" / "conditions.parquet")
    reference_key, reference = next(iter(models.items()))
    if len(conditions) != len(reference):
        raise SystemExit(
            f"conditions.parquet has {len(conditions)} rows but the test prediction "
            f"frame has {len(reference)}; refusing to align two frames of different length."
        )
    for key, frame in models.items():
        if not frame.index.equals(reference.index):
            raise SystemExit(
                f"Test prediction frames disagree on row identity ({key} vs {reference_key}); "
                "the models were not scored on the same rows. Aborting."
            )
    conditions = conditions.copy()
    conditions.index = reference.index
    return conditions


def _verify_alignment(
    conditions: pd.DataFrame, residuals: pd.DataFrame, predictions: dict[str, pd.DataFrame]
) -> dict[str, Any]:
    """Prove the positional alignment via a key-based join before relying on it.

    ``residuals/test.parquet`` carries ONE model's predictions — the residual
    stream is built from the thesis model (M-19a). Rather than hard-code which,
    every stored model is tried and exactly one must reproduce the residual
    frame's ``prediction`` column row for row. That identifies the
    residual-bearing model AND proves the alignment in a single check; a run
    where none matches, or several do, is a run this script must not report on.
    """
    keyed = conditions.reset_index(names="row_index")[["row_index", *KEY_COLUMNS]]
    merged = residuals.merge(keyed, on=KEY_COLUMNS, how="left", validate="many_to_one")
    unmatched = int(merged["row_index"].isna().sum())
    if unmatched:
        raise SystemExit(
            f"{unmatched} residual rows did not key-join to conditions.parquet; aborting "
            "rather than reporting on a partial join."
        )
    per_model: dict[str, float] = {}
    for key, frame in predictions.items():
        worst = 0.0
        for target, group in merged.groupby(TARGET_COLUMN, observed=True):
            stored = frame.loc[group["row_index"].to_numpy(dtype=int), str(target)]
            delta = stored.to_numpy(dtype=float) - group["prediction"].to_numpy(dtype=float)
            worst = max(worst, float(abs(delta).max()))
        per_model[key] = worst
    matching = sorted(key for key, diff in per_model.items() if diff <= 1e-4)
    if len(matching) != 1:
        raise SystemExit(
            "Alignment check failed: expected exactly one stored model to reproduce "
            f"residuals/test.parquet, found {matching or 'none'}. Per-model max |diff|: "
            f"{ {k: f'{v:.3e}' for k, v in per_model.items()} }. Aborting."
        )
    return {
        "method": (
            "conditions.parquet aligned positionally to predictions/*_test.parquet, then "
            "PROVEN by key-joining residuals/test.parquet on (timestamp, turbine_id) and "
            "identifying which stored model reproduces its prediction column row for row"
        ),
        "residual_bearing_model": matching[0],
        "per_model_max_abs_difference": per_model,
        "residual_rows_joined": len(merged),
        "unmatched_rows": unmatched,
        "max_abs_prediction_difference": per_model[matching[0]],
        "verified": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", default=None)
    parser.add_argument("--artifacts", type=Path, default=REPO_ROOT / "artifacts")
    args = parser.parse_args()
    experiment = (
        args.experiment or sorted(p.name for p in args.artifacts.glob("EXP-*") if p.is_dir())[-1]
    )
    directory = args.artifacts / experiment
    if not directory.is_dir():
        raise SystemExit(f"Experiment directory not found: {directory}")

    config = yaml.safe_load((directory / "config.yaml").read_text(encoding="utf-8"))
    floor_kw = float(config["healthy_state"]["minimum_active_power_kw"])
    stored_metrics = json.loads((directory / "metrics.json").read_text(encoding="utf-8"))

    model_keys = sorted(stored_metrics["nbm"])
    test_predictions = {
        key: pd.read_parquet(directory / "predictions" / f"{key}_test.parquet")
        for key in model_keys
    }
    healthy_predictions = {
        key: pd.read_parquet(directory / "predictions" / f"{key}_monitoring_healthy.parquet")
        for key in model_keys
    }
    residuals = pd.read_parquet(directory / "residuals" / "test.parquet")
    conditions = _load_conditions(directory, test_predictions)

    print("Verifying conditions/prediction alignment against the key-joined residuals...")
    alignment = _verify_alignment(conditions, residuals, test_predictions)
    print(
        f"  alignment verified; residuals/test.parquet belongs to "
        f"'{alignment['residual_bearing_model']}' "
        f"(max |diff| = {alignment['max_abs_prediction_difference']:.3e})"
    )

    regime = label_regime(conditions["active_power"], floor_kw)
    healthy_index = next(iter(healthy_predictions.values())).index
    is_healthy = pd.Series(conditions.index.isin(healthy_index), index=conditions.index)

    stored_healthy_rows = int(stored_metrics["rq1"]["monitoring_healthy_rows"])
    if int(is_healthy.sum()) != stored_healthy_rows:
        raise SystemExit(
            f"Healthy-slice membership rebuilt from artifacts has {int(is_healthy.sum())} rows "
            f"but the run recorded {stored_healthy_rows}. Aborting."
        )

    # ---- actuals, keyed like the prediction frames -------------------------
    targets = sorted(residuals[TARGET_COLUMN].unique())
    keyed = conditions.reset_index(names="row_index")[["row_index", *KEY_COLUMNS]]
    merged = residuals.merge(keyed, on=KEY_COLUMNS, how="left", validate="many_to_one")
    actuals = (
        merged.pivot(index="row_index", columns=TARGET_COLUMN, values="actual")
        .reindex(conditions.index)
        .astype(float)
    )

    # ---- 1. accuracy by regime, and 2. separation --------------------------
    accuracy: dict[str, Any] = {}
    separations: dict[str, Any] = {}
    for key in model_keys:
        predicted = test_predictions[key]
        accuracy[key] = {}
        separations[key] = {}
        for target in targets:
            slices = regime_slices(actuals[target], predicted[target].astype(float), regime)
            accuracy[key][target] = {name: s.as_dict() for name, s in slices.items()}
            per_regime: dict[str, Any] = {}
            for member in (Regime.IN_REGIME, Regime.OUT_OF_REGIME):
                mask = (regime == member.value).to_numpy(dtype=bool)
                if not mask.any():
                    continue
                try:
                    result = separation(
                        actuals[target][mask],
                        predicted[target].astype(float)[mask],
                        is_healthy[mask],
                        regime=member,
                    )
                except Exception as exc:  # a regime with no healthy or no unhealthy rows
                    per_regime[member.value] = {"computable": False, "reason": str(exc)}
                    continue
                per_regime[member.value] = {"computable": True, **result.as_dict()}
            # the contaminated figure, reported so the correction is visible
            pooled = separation(
                actuals[target],
                predicted[target].astype(float),
                is_healthy,
                regime=Regime.IN_REGIME,
            )
            per_regime["pooled_uncorrected"] = {
                "computable": True,
                **pooled.as_dict(),
                "warning": (
                    "NOT a defensible delta-PE. Computed over the whole monitoring stream, "
                    "whose unhealthy complement is dominated by rows below the training "
                    "floor (LIM-034). Retained ONLY so the size of the correction is "
                    "visible; cite the in_regime entry."
                ),
            }
            separations[key][target] = per_regime

    # ---- 3. exceedance census by regime and direction ----------------------
    print("Recomputing EWMA states on the stored residuals for the direction census...")
    detection_config = config["detection"]
    detector = EwmaDetector(
        float(detection_config["ewma_lambda"]),
        ControlLimitSpec(
            sigma_multiplier=float(detection_config["control_limit_sigma"]),
            formulation=ControlLimitFormulation(detection_config["control_limit_formulation"]),
        ),
        gap_handling=GapHandling(detection_config["gap_handling"]),
    )
    training = ResidualFrame(pd.read_parquet(directory / "residuals" / "training.parquet"))
    detector.fit_control_limits(training, partition_for(ThresholdStatsSource.TRAINING))
    _ewma, detections = detector.detect(ResidualFrame(residuals))

    state_frames = [
        pd.DataFrame(
            {
                "timestamp": series.timestamps.to_numpy(),
                "turbine_id": series.turbine,
                TARGET_COLUMN: series.target,
                "state": series.states.to_numpy(),
            }
        )
        for series in detections
    ]
    states = pd.concat(state_frames, ignore_index=True).merge(
        keyed, on=KEY_COLUMNS, how="left", validate="many_to_one"
    )
    states["regime"] = states["row_index"].map(regime)

    census: dict[str, Any] = {}
    for target in targets:
        subset = states[states[TARGET_COLUMN] == target]
        by_regime = exceedance_census(subset["state"], subset["regime"])
        census[target] = {name: c.as_dict() for name, c in by_regime.items()}
    overall = exceedance_census(states["state"], states["regime"])

    # ---- 4. what this split does NOT explain -------------------------------
    in_control = stored_metrics["detection"]["in_control"]
    healthy_validation_rows = int(stored_metrics["split"]["healthy_validation"])
    in_control_scope = {
        "measured_on": "healthy VALIDATION block",
        "n_points": in_control["n_points"],
        "rows_x_targets": f"{healthy_validation_rows} x {len(targets)}",
        "inflation_ratio": in_control["inflation_ratio"],
        "already_in_regime_by_construction": True,
        "finding": (
            "The in-control block is built with the full healthy-state criteria, INCLUDING "
            "the active-power floor, so every row in it is in-regime already. The "
            f"{in_control['inflation_ratio']:.2f}x in-control false-alarm inflation therefore "
            "CANNOT be a regime-mismatch effect and this split does not reduce it. ADR-034 "
            "(serial correlation in the residual stream) remains the sole explanation on "
            "record. LIM-034's mechanism explains the TEST-stream alarm volume and its "
            "direction asymmetry, not the in-control rate."
        ),
    }

    payload = {
        "experiment_id": experiment,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "purpose": "LIM-034 mitigation (a): report every figure split by operating regime",
        "regime_boundary": {
            "floor_kw": floor_kw,
            "source": REGIME_BOUNDARY_SOURCE,
            "note": (
                "The regime boundary IS the healthy-state floor that built the training "
                "population. It is not an independently chosen threshold."
            ),
        },
        "alignment_check": alignment,
        "row_census": {
            "test_rows": len(conditions),
            "healthy_slice_rows": int(is_healthy.sum()),
            "unhealthy_complement_rows": int((~is_healthy).sum()),
            "in_regime_rows": int((regime == Regime.IN_REGIME.value).sum()),
            "out_of_regime_rows": int((regime == Regime.OUT_OF_REGIME.value).sum()),
            "unhealthy_complement_out_of_regime_share": float(
                (regime[~is_healthy] == Regime.OUT_OF_REGIME.value).mean()
            ),
        },
        "accuracy_by_regime": accuracy,
        "separation_delta_pe": {
            "definition": "delta = RMSE(unhealthy) - RMSE(healthy); larger is better",
            "source": (
                "Chesterman, Verstraeten, Daems, Nowe, Helsen (2023), Wind Energy Science "
                "8(6):893 — a normal behaviour model needs small error on healthy data AND "
                "large error on unhealthy data; accuracy alone scores only the first"
            ),
            "by_model": separations,
        },
        "exceedance_census": {"overall": {k: v.as_dict() for k, v in overall.items()}, **census},
        "in_control_scope": in_control_scope,
        "environment": capture_version_stamp(
            schema_version=str(stored_metrics.get("schema_version", "")) or "1.3.0"
        ).model_dump(),
    }

    out_path = directory / "evaluation" / "regime_split.json"
    out_path.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    print(f"\nRegime split written to {out_path}")

    # ---- console summary ---------------------------------------------------
    census_row = payload["row_census"]
    print(
        f"\nRows: {census_row['test_rows']} test = "
        f"{census_row['in_regime_rows']} in-regime + "
        f"{census_row['out_of_regime_rows']} out-of-regime"
    )
    print(
        "  the 'unhealthy' complement is "
        f"{census_row['unhealthy_complement_out_of_regime_share']:.1%} out-of-regime "
        "— which is why the pooled delta-PE is not citable"
    )
    for key in model_keys:
        print(f"\n=== {key} ===")
        for target in targets:
            for name, entry in accuracy[key][target].items():
                print(
                    f"  {target:<30} {name:<14} n={entry['n']:>7} "
                    f"({entry['share']:>5.1%})  rmse={entry['rmse']:>7.4f}  "
                    f"bias={entry['bias']:>8.4f}  var_share={entry['variance_share']:>5.1%}"
                )
            sep = separations[key][target]
            for name in ("in_regime", "out_of_regime", "pooled_uncorrected"):
                entry = sep.get(name)
                if entry and entry.get("computable"):
                    flag = "  <-- CITE" if name == "in_regime" else ""
                    print(
                        f"    delta-PE {name:<20} healthy={entry['rmse_healthy']:.4f} "
                        f"unhealthy={entry['rmse_unhealthy']:.4f} "
                        f"delta={entry['delta']:+.4f}{flag}"
                    )
    print("\n=== exceedance census (points) ===")
    for name, entry in payload["exceedance_census"]["overall"].items():
        print(
            f"  {name:<14} n={entry['n_points']:>8}  high={entry['n_high']:>7} "
            f"low={entry['n_low']:>7}  rate={entry['exceedance_rate']:.4f}"
        )
    print(f"\n{in_control_scope['finding']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
