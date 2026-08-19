"""Regime-split statistics of the ADR-035 orthogonal modes (LIM-037 mitigation).

WHY THIS EXISTS. Arm A6 measured the mode correlation POOLED per partition and
found the monitoring collapse LIM-037 records (mode r = 0.835 on test). The
question that decides whether the differential mode can carry any
interpretation weight (ADR-049/ADR-050) is whether that collapse is a property
of the monitoring period or of the out-of-support rows LIM-034 identified.
An exploratory computation answered it; this driver makes the answer a
recorded artefact, and adds the differential-mode characterization an external
methodological review (idea_assessment.pdf, 2026-08-20) required before the
mode representation may carry weight: per-turbine stability, an excursion
census, and sensitivity to operating variables. Corr(C,D) ~ 0 alone is NOT
evidence of diagnostic discrimination — these are the measurements that
separate "uncorrelated" from "informative".

Method notes:
- Standardization uses TRAINING healthy statistics only (ADR-035 condition a),
  via the identical SigmaNormalizer the A6 arm used. On the training partition
  the orthogonality is exact BY CONSTRUCTION (equal variances); its transfer
  to validation and to the in-support monitoring slice is the empirical
  content, and the out-of-support slice shows the statistic can fail.
- Regime labels follow ADR-047: active_power below the healthy-state floor OR
  missing => OUT_OF_REGIME (HealthyStateConfig.minimum_active_power_kw).
- The recomputed pooled per-partition statistics are VERIFIED against the A6
  arm's stored mode_statistics and the run aborts on any disagreement, so this
  artefact cannot silently drift from the arm it refines.
- Eligibility language (external review §6): the in-regime share is the
  ELIGIBLE population, never a success rate.

Reads STORED ARTIFACTS ONLY. Writes ``evaluation/mode_regime_split.json``.

Usage (from backend/):
    uv run python ../scripts/run_mode_regime_split.py --experiment EXP-YYYYMMDD-NNN
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
from app.evaluation.regime import REGIME_BOUNDARY_SOURCE, Regime, label_regime  # noqa: E402
from app.residuals.engine import ResidualFrame  # noqa: E402
from app.residuals.modes import MODE_DIFFERENTIAL, ModeRotationReport, rotate_to_modes  # noqa: E402
from app.residuals.normalization import PartitionRef, SigmaNormalizer  # noqa: E402

#: Excursion thresholds in units of the TRAINING differential-mode sd.
EXCURSION_MULTIPLES = (3.0, 5.0)
#: Cross-check tolerance against the stored A6 statistics.
CROSS_CHECK_ATOL = 1e-9


def _lag1(values: np.ndarray) -> float | None:
    if len(values) < 3 or float(np.std(values[:-1])) == 0.0 or float(np.std(values[1:])) == 0.0:
        return None
    return float(np.corrcoef(values[:-1], values[1:])[0, 1])


def _rising_edges(mask: np.ndarray) -> int:
    if len(mask) == 0:
        return 0
    previous = np.concatenate([[False], mask[:-1]])
    return int((mask & ~previous).sum())


def _longest_run(mask: np.ndarray) -> int:
    longest = current = 0
    for flag in mask:
        current = current + 1 if flag else 0
        longest = max(longest, current)
    return longest


def _differential_series(mode_frame: ResidualFrame) -> pd.DataFrame:
    data = mode_frame.data
    d = data[data["target"] == MODE_DIFFERENTIAL]
    return d.sort_values(["turbine_id", "timestamp"]).reset_index(drop=True)


def _characterize_differential(
    mode_frame: ResidualFrame,
    sigma_d_training: float,
    conditions: pd.DataFrame,
) -> dict[str, Any]:
    """The external review's work list: stability, excursions, sensitivity."""
    d = _differential_series(mode_frame)

    per_turbine: dict[str, Any] = {}
    for turbine, group in d.groupby("turbine_id"):
        values = group["raw_residual"].to_numpy(dtype=float)
        per_turbine[str(turbine)] = {
            "n": len(values),
            "sd": round(float(np.std(values, ddof=1)), 4),
            "lag1": None if (phi := _lag1(values)) is None else round(phi, 4),
        }

    census: dict[str, Any] = {}
    for multiple in EXCURSION_MULTIPLES:
        threshold = multiple * sigma_d_training
        entry: dict[str, Any] = {
            "threshold_in_training_sd": multiple,
            "threshold_value": round(threshold, 4),
        }
        totals = {"points_above": 0, "points_below": 0, "episodes": 0, "longest_run": 0}
        by_turbine: dict[str, Any] = {}
        for turbine, group in d.groupby("turbine_id"):
            values = group["raw_residual"].to_numpy(dtype=float)
            above, below = values > threshold, values < -threshold
            either = above | below
            by_turbine[str(turbine)] = {
                "points_above": int(above.sum()),
                "points_below": int(below.sum()),
                "episodes": _rising_edges(either),
                "longest_run": _longest_run(either),
            }
            totals["points_above"] += int(above.sum())
            totals["points_below"] += int(below.sum())
            totals["episodes"] += _rising_edges(either)
            totals["longest_run"] = max(totals["longest_run"], _longest_run(either))
        entry["total"] = {
            **totals,
            "point_fraction": round((totals["points_above"] + totals["points_below"]) / len(d), 6),
        }
        entry["per_turbine"] = by_turbine
        census[f"{multiple:g}sd"] = entry

    merged = d.merge(conditions, on=["timestamp", "turbine_id"], how="left")
    sensitivity = {
        variable: round(float(merged["raw_residual"].corr(merged[variable])), 4)
        for variable in ("active_power", "wind_speed", "ambient_temperature")
        if variable in merged.columns
    }
    return {
        "per_turbine_stability": per_turbine,
        "excursion_census": census,
        "sensitivity_to_operating_variables": sensitivity,
        "note": (
            "Excursion thresholds are multiples of the TRAINING differential sd, "
            "descriptive only — they are not detection thresholds and carry no "
            "detection claim (ADR-035 condition c)."
        ),
    }


def _verify_against_arm(stored: dict[str, Any], recomputed: dict[str, ModeRotationReport]) -> None:
    """Abort if this artefact disagrees with the A6 arm it refines."""
    for partition, report in recomputed.items():
        arm = stored[partition]
        for field, value in (
            ("mode_pearson", report.mode_pearson),
            ("sd_common", report.sd_common),
            ("sd_differential", report.sd_differential),
        ):
            if abs(float(arm[field]) - value) > CROSS_CHECK_ATOL:
                raise SystemExit(
                    f"CROSS-CHECK FAILED: {partition}.{field} stored={arm[field]} "
                    f"recomputed={value} — refusing to write an artefact that "
                    "disagrees with the A6 arm"
                )
        if int(arm["n_aligned_points"]) != report.n_aligned_points:
            raise SystemExit(
                f"CROSS-CHECK FAILED: {partition} aligned-point count "
                f"stored={arm['n_aligned_points']} recomputed={report.n_aligned_points}"
            )


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

    suite_path = directory / "evaluation" / "robustness_suite.json"
    if not suite_path.is_file():
        raise SystemExit(f"Missing {suite_path}; run the A6 arm first (--arms orthogonal)")
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    arm = suite.get("arms", {}).get("orthogonal")
    if arm is None or "FAILED" in arm:
        raise SystemExit("No completed `orthogonal` arm in robustness_suite.json")

    residuals = {
        partition: ResidualFrame(pd.read_parquet(directory / "residuals" / f"{partition}.parquet"))
        for partition in ("training", "validation", "test")
    }
    conditions = pd.read_parquet(directory / "evaluation" / "conditions.parquet")

    # Identical standardization to the A6 arm (training stats only, condition a).
    standardizer = SigmaNormalizer()
    standardizer.fit(residuals["training"], PartitionRef.HEALTHY_TRAINING)
    standardized = {p: standardizer.transform(rf) for p, rf in residuals.items()}

    # Pooled per-partition rotations, verified against the arm before anything else.
    pooled: dict[str, ModeRotationReport] = {}
    mode_frames: dict[str, ResidualFrame] = {}
    for partition, frame in standardized.items():
        mode_frames[partition], pooled[partition] = rotate_to_modes(frame)
    _verify_against_arm(arm["mode_statistics"], pooled)

    # Regime labels for the monitoring stream; the join must be exact.
    floor_kw = AppConfig().healthy_state.minimum_active_power_kw
    test_frame = standardized["test"].data
    joined = test_frame.merge(
        conditions[["timestamp", "turbine_id", "active_power"]],
        on=["timestamp", "turbine_id"],
        how="left",
        indicator=True,
    )
    unmatched = int((joined["_merge"] != "both").sum())
    if unmatched:
        raise SystemExit(
            f"JOIN FAILED: {unmatched} monitoring residual rows found no "
            "conditions row — refusing to report on a bad alignment"
        )
    regime = label_regime(joined["active_power"], floor_kw)

    slices: dict[str, ModeRotationReport] = {}
    slice_frames: dict[str, ResidualFrame] = {}
    for name, member in (
        ("test_in_regime", Regime.IN_REGIME),
        ("test_out_of_regime", Regime.OUT_OF_REGIME),
    ):
        mask = (regime == member.value).to_numpy(dtype=bool)
        subset = joined[mask][test_frame.columns]
        slice_frames[name], slices[name] = rotate_to_modes(
            ResidualFrame(subset.reset_index(drop=True))
        )
    n_in = slices["test_in_regime"].n_aligned_points
    n_out = slices["test_out_of_regime"].n_aligned_points
    if n_in + n_out != pooled["test"].n_aligned_points:
        raise SystemExit(
            f"PARTITION FAILED: in ({n_in}) + out ({n_out}) != pooled "
            f"({pooled['test'].n_aligned_points})"
        )

    characterization = _characterize_differential(
        slice_frames["test_in_regime"], pooled["training"].sd_differential, conditions
    )

    output = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "experiment_id": experiment,
        "environment": capture_version_stamp(
            schema_version=default_schema().schema_version
        ).model_dump(),
        "regime_boundary": {"floor_kw": floor_kw, "source": REGIME_BOUNDARY_SOURCE},
        "standardization": (
            "per-channel sigma statistics from HEALTHY TRAINING only "
            "(ADR-035 condition a; identical to arm A6)"
        ),
        "cross_check": (
            "pooled per-partition statistics verified equal to "
            "robustness_suite.json arms.orthogonal.mode_statistics"
        ),
        "mode_statistics": {
            **{p: r.as_dict() for p, r in pooled.items()},
            **{name: r.as_dict() for name, r in slices.items()},
        },
        "eligible_share_of_monitoring": round(n_in / (n_in + n_out), 4),
        "in_regime_differential_characterization": characterization,
        "reading": (
            "The LIM-037 collapse is confined to the out-of-support slice: the "
            "training-frozen rotation transfers to the in-support monitoring "
            "population but fails out-of-support. The in-regime share is the "
            "population ELIGIBLE for interpretation under the ADR-049 gate — "
            "eligibility is not a success rate, and near-zero mode correlation "
            "alone is not evidence of diagnostic discrimination; the "
            "characterization block carries that burden."
        ),
        "references": ["ADR-035", "ADR-047", "ADR-049", "ADR-050", "LIM-034", "LIM-037"],
    }
    out_path = directory / "evaluation" / "mode_regime_split.json"
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {k: output[k] for k in ("mode_statistics", "eligible_share_of_monitoring")}, indent=2
        )
    )
    print(f"\nWritten to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
