"""READ-ONLY measurement behind ADR-034 and ADR-035.

(1) Does residual autocorrelation quantitatively explain the 60x EWMA
    false-alarm inflation?
(2) How much independent signal survives a common/differential rotation of
    the two collinear channels?

Nothing is written; the experiment directory is opened read-only.
"""

from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
import pandas as pd

LAMBDA = 0.2
K = 3.0
STEP = pd.Timedelta(minutes=10)
PATH = "artifacts/EXP-20260817-001/residuals/validation.parquet"  # override via argv[1]


def contiguous_lag1(frame: pd.DataFrame, col: str) -> tuple[float, int]:
    """Lag-1 autocorrelation using only genuinely adjacent 10-minute pairs.

    The healthy series is gap-filled by exclusion, so a naive shift() would
    pair rows that are hours apart and understate the dependence.
    """
    frame = frame.sort_values("timestamp")
    values = frame[col].to_numpy()
    times = frame["timestamp"].to_numpy()
    adjacent = (times[1:] - times[:-1]) == STEP.to_timedelta64()
    a, b = values[:-1][adjacent], values[1:][adjacent]
    ok = ~(np.isnan(a) | np.isnan(b))
    if ok.sum() < 100:
        return float("nan"), int(ok.sum())
    return float(np.corrcoef(a[ok], b[ok])[0, 1]), int(ok.sum())


def ewma(values: np.ndarray, lam: float = LAMBDA) -> np.ndarray:
    out = np.empty_like(values, dtype=float)
    z = 0.0
    for i, x in enumerate(values):
        z = lam * x + (1 - lam) * z
        out[i] = z
    return out


def main() -> None:
    df = pd.read_parquet(sys.argv[1] if len(sys.argv) > 1 else PATH)
    a = 1 - LAMBDA
    iid_sd = np.sqrt(LAMBDA / (2 - LAMBDA))

    print("=" * 74)
    print("PART 1 - does residual autocorrelation explain the inflation?")
    print("=" * 74)
    print(f"EWMA lambda={LAMBDA}, limits at +/-{K} sigma_z")
    print(f"i.i.d. steady-state sd factor sqrt(l/(2-l)) = {iid_sd:.5f}\n")
    print(
        f"{'turbine':13}{'target':10}{'phi(lag1)':>11}{'pred infl':>11}"
        f"{'meas infl':>11}{'exceed%':>10}"
    )

    rows = []
    for (turbine, target), grp in df.groupby(["turbine_id", "target"]):
        phi, _n = contiguous_lag1(grp, "normalized_residual")
        # Var(EWMA) of an AR(1) input, relative to the i.i.d. formula.
        predicted = np.sqrt((1 + a * phi) / (1 - a * phi))
        grp = grp.sort_values("timestamp")
        z = ewma(grp["normalized_residual"].fillna(0.0).to_numpy())
        sd_resid = float(np.nanstd(grp["normalized_residual"].to_numpy()))
        measured = float(np.std(z)) / (iid_sd * sd_resid)
        limit = K * iid_sd * sd_resid
        exceed = 100.0 * float(np.mean(np.abs(z) > limit))
        rows.append((phi, predicted, measured, exceed))
        short = str(target).replace("gearbox_", "").replace("_temperature", "")
        print(
            f"{turbine:13}{short:10}{phi:>11.4f}{predicted:>11.2f}{measured:>11.2f}{exceed:>10.2f}"
        )

    phis, preds, meas, exc = map(np.array, zip(*rows, strict=True))
    print(
        f"\n{'MEAN':23}{phis.mean():>11.4f}{preds.mean():>11.2f}"
        f"{meas.mean():>11.2f}{exc.mean():>10.2f}"
    )

    from scipy.stats import norm  # type: ignore[import-untyped]

    implied = float(2 * (1 - norm.cdf(K / meas.mean())))
    print(f"\nExceedance predicted from the measured inflation : {100 * implied:.2f}%")
    recorded = json.loads(
        pathlib.Path(PATH).parents[1].joinpath("metrics.json").read_text(encoding="utf-8")
    )["detection"]["in_control"]["empirical_rate"]
    print(f"Exceedance recorded by the pipeline              : {100 * recorded:.2f}%")
    print(f"Nominal rate the limits were set for             : {100 * 2 * (1 - norm.cdf(K)):.2f}%")

    print("\n" + "=" * 74)
    print("PART 2 - what survives a common/differential rotation?")
    print("=" * 74)
    wide = df.pivot_table(
        index=["turbine_id", "timestamp"],
        columns="target",
        values="normalized_residual",
    ).dropna()
    oil = wide["gearbox_oil_temperature"].to_numpy()
    bear = wide["gearbox_bearing_temperature"].to_numpy()
    r = float(np.corrcoef(oil, bear)[0, 1])

    # Rotate to principal axes. Standardize first so the rotation reflects
    # correlation rather than the two channels' differing spreads; then PC1
    # and PC2 are orthogonal by construction, which a raw
    # bearing-minus-beta*oil contrast is NOT (it is orthogonal to oil, not
    # to the common mode).
    oil_s = (oil - oil.mean()) / oil.std()
    bear_s = (bear - bear.mean()) / bear.std()
    common = (oil_s + bear_s) / np.sqrt(2.0)  # PC1
    diff = (bear_s - oil_s) / np.sqrt(2.0)  # PC2

    print(f"correlation(oil, bearing)          : {r:.4f}")
    print(
        f"corr(common, differential)         : {np.corrcoef(common, diff)[0, 1]:+.2e}"
        "   <- now genuinely orthogonal"
    )
    print(
        f"sd(common mode)                    : {np.std(common):.4f}"
        f"   (theory sqrt(1+r) = {np.sqrt(1 + r):.4f})"
    )
    print(
        f"sd(differential mode)              : {np.std(diff):.4f}"
        f"   (theory sqrt(1-r) = {np.sqrt(1 - r):.4f})"
    )
    print(
        f"variance share  common / diff      : "
        f"{100 * np.var(common) / (np.var(common) + np.var(diff)):.1f}% / "
        f"{100 * np.var(diff) / (np.var(common) + np.var(diff)):.1f}%"
    )

    tmp = wide.reset_index()[["turbine_id", "timestamp"]].copy()
    tmp["differential"] = diff
    tmp["common"] = common
    ph_d = np.mean([contiguous_lag1(g, "differential")[0] for _, g in tmp.groupby("turbine_id")])
    ph_c = np.mean([contiguous_lag1(g, "common")[0] for _, g in tmp.groupby("turbine_id")])
    print(f"\nmean lag-1 phi, common mode        : {ph_c:.4f}")
    print(f"mean lag-1 phi, differential mode  : {ph_d:.4f}")
    print(f"implied EWMA inflation, common     : {np.sqrt((1 + a * ph_c) / (1 - a * ph_c)):.2f}x")
    print(f"implied EWMA inflation, differential: {np.sqrt((1 + a * ph_d) / (1 - a * ph_d)):.2f}x")


if __name__ == "__main__":
    main()
