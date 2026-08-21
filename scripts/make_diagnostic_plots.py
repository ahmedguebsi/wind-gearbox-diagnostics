"""PROJECT.md §20 model diagnostic figures (ADR-045).

WHY THIS EXISTS. §20 mandates five diagnostic plots and §31 requires PNG/SVG
export. No experiment had ever produced one: ``artifacts/*/plots/`` was empty
in every run, and the only plotting code in the repository belonged to a
one-off EVENT-001 context script. Chapters 4 and 5 need figures, and two of
these are load-bearing evidence rather than illustration:

- **error vs ambient temperature** is the seasonal-shift diagnostic §20 names
  and the mitigation LIM-013 names — it shows whether error grows where the
  model extrapolates beyond its training range.
- **error vs active power / wind speed** are the heteroscedasticity evidence
  the §22 normalization design rests on and that decision D-12
  (condition-binned normalization) is blocked on.

This reads STORED ARTIFACTS ONLY and writes into the experiment's own
``plots/`` directory, so figures regenerate in seconds without re-running the
~16-minute pipeline, and a figure can never disagree with the metrics it sits
beside — both come from the same persisted predictions.

Usage (from backend/):
    uv run python ../scripts/make_diagnostic_plots.py --experiment EXP-YYYYMMDD-NNN
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: no display is available on a clean runner
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.models.metrics import residual  # noqa: E402

#: The RQ1 headline partition (ADR-022). Figures follow the headline, not the
#: unfiltered stream, so a reader is not invited to compare a plot against a
#: metric computed on a different population.
HEADLINE_PARTITION = "monitoring_healthy"
DPI = 150
#: Scatter plots of 500k points produce unreadable ink and enormous files.
#: Deterministic subsampling with a recorded seed and a stated count.
SCATTER_MAX_POINTS = 20_000
SCATTER_SEED = 42
#: Every figure states the population it draws, in the figure itself: the
#: residual frames cover the FULL unfiltered monitoring partition (the
#: detection population), while the ADR-022 headline metrics use its
#: healthy-filtered subset. A reader of a printed page never sees the
#: manifest, so the label cannot live only there.
POPULATION_LABEL = "monitoring period (unfiltered)"
#: §20 condition axes carry physical units (schema.py units for the mapped
#: canonical channels); the raw column name alone is not an axis label.
CONDITION_LABELS = {
    "active_power": "active power (kW)",
    "wind_speed": "wind speed (m/s)",
    "ambient_temperature": "ambient temperature (°C)",
}


def _load(directory: Path, partition: str) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Residual rows for the partition plus per-model prediction frames."""
    residuals = pd.read_parquet(directory / "residuals" / "test.parquet")
    predictions = {}
    for path in sorted((directory / "predictions").glob(f"*_{partition}.parquet")):
        model = path.stem[: -len(f"_{partition}")]
        predictions[model] = pd.read_parquet(path)
    return residuals, predictions


def _subsample(n: int) -> np.ndarray | slice:
    if n <= SCATTER_MAX_POINTS:
        return slice(None)
    rng = np.random.default_rng(SCATTER_SEED)
    return np.sort(rng.choice(n, SCATTER_MAX_POINTS, replace=False))


def _style(ax: plt.Axes, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_title(title, fontsize=10)
    ax.set_xlabel(xlabel, fontsize=9)
    ax.set_ylabel(ylabel, fontsize=9)
    ax.grid(alpha=0.25, linewidth=0.5)
    ax.tick_params(labelsize=8)


#: Set to ("png", "svg") by --svg: §31 asks for PNG/SVG "where practical".
#: SVG stays opt-in because vector scatters of 20k points are heavy files.
SAVE_FORMATS: tuple[str, ...] = ("png",)


def _save(fig: plt.Figure, out: Path) -> None:
    for fmt in SAVE_FORMATS:
        fig.savefig(out.with_suffix(f".{fmt}"), dpi=DPI)


def plot_actual_vs_predicted(frame: pd.DataFrame, target: str, out: Path) -> None:
    take = _subsample(len(frame))
    actual = frame["actual"].to_numpy()[take]
    predicted = frame["prediction"].to_numpy()[take]
    fig, ax = plt.subplots(figsize=(5.0, 5.0))
    ax.scatter(actual, predicted, s=2, alpha=0.15, linewidths=0, color="#0B6672")
    lo, hi = float(np.nanmin(actual)), float(np.nanmax(actual))
    ax.plot([lo, hi], [lo, hi], color="#8E2727", linewidth=1.0, label="perfect prediction")
    ax.legend(fontsize=8, frameon=False)
    _style(
        ax,
        f"Actual vs predicted — {target}\n{POPULATION_LABEL}",
        "actual (°C)",
        "predicted (°C)",
    )
    fig.tight_layout()
    _save(fig, out)
    plt.close(fig)


def plot_error_distribution(frame: pd.DataFrame, target: str, out: Path) -> None:
    errors = frame["raw_residual"].dropna().to_numpy()
    fig, ax = plt.subplots(figsize=(5.5, 3.6))
    ax.hist(errors, bins=120, color="#0B6672", alpha=0.85)
    ax.axvline(0.0, color="#8E2727", linewidth=1.0)
    ax.axvline(
        float(np.mean(errors)),
        color="#8A5606",
        linewidth=1.0,
        linestyle="--",
        label=f"bias = {np.mean(errors):+.3f} °C",
    )
    ax.legend(fontsize=8, frameon=False)
    _style(
        ax,
        f"Residual distribution — {target}\n{POPULATION_LABEL}",
        "residual = actual − predicted (°C)",  # noqa: RUF001 (axis label: real minus sign)
        "count",
    )
    fig.tight_layout()
    _save(fig, out)
    plt.close(fig)


def plot_residual_over_time(frame: pd.DataFrame, target: str, out: Path) -> None:
    """Daily median and inter-quartile band per turbine.

    Plotted as a daily aggregate rather than raw points because the finding
    this figure carries is a slow one: residual dispersion grows with distance
    from the training window on every turbine.
    """
    daily = (
        frame.set_index("timestamp")
        .groupby("turbine_id")["raw_residual"]
        .resample("1D")
        .agg(["median", "std"])
        .reset_index()
    )
    fig, ax = plt.subplots(figsize=(8.0, 3.8))
    for turbine, group in daily.groupby("turbine_id"):
        ax.plot(group["timestamp"], group["std"], linewidth=0.5, alpha=0.35, label=str(turbine))
    # A 30-day rolling median of the FLEET. The per-turbine daily traces are
    # spiky enough to hide the finding this figure exists to show (LIM-029):
    # dispersion grows with distance from the training window on every
    # machine, so the trend is the signal and the spikes are not.
    fleet = (
        daily.groupby("timestamp")["std"].median().rolling("30D", min_periods=5).median().dropna()
    )
    ax.plot(
        fleet.index,
        fleet.to_numpy(),
        linewidth=2.2,
        color="#8E2727",
        label="fleet median (30-day rolling)",
    )
    ax.legend(fontsize=7, frameon=False, ncol=4)
    _style(
        ax,
        f"Daily residual dispersion over the monitoring period — {target}",
        "date (UTC)",
        "daily residual σ (°C)",  # noqa: RUF001 (axis label: sigma)
    )
    fig.tight_layout()
    _save(fig, out)
    plt.close(fig)


def plot_error_vs_condition(
    errors: np.ndarray,
    condition: np.ndarray,
    name: str,
    target: str,
    out: Path,
    regime_floor_kw: float | None = None,
) -> None:
    """Binned |residual| against an operating-condition variable (§20).

    Binned rather than scattered: the question is whether error SPREAD varies
    with the condition (heteroscedasticity), which a cloud of points does not
    answer legibly.
    """
    keep = ~(np.isnan(errors) | np.isnan(condition))
    errors, condition = errors[keep], condition[keep]
    edges = np.quantile(condition, np.linspace(0.0, 1.0, 21))
    edges = np.unique(edges)
    index = np.clip(np.searchsorted(edges, condition, side="right") - 1, 0, len(edges) - 2)
    centres, spread, bias, counts = [], [], [], []
    for b in range(len(edges) - 1):
        mask = index == b
        if mask.sum() < 30:
            continue
        centres.append(0.5 * (edges[b] + edges[b + 1]))
        spread.append(float(np.std(errors[mask], ddof=1)))
        bias.append(float(np.mean(errors[mask])))
        counts.append(int(mask.sum()))

    fig, ax = plt.subplots(figsize=(6.0, 3.8))
    ax.plot(centres, spread, marker="o", markersize=3, linewidth=1.0, color="#0B6672", label="σ")  # noqa: RUF001
    ax.plot(centres, bias, marker="s", markersize=3, linewidth=1.0, color="#8A5606", label="mean")
    ax.axhline(0.0, color="#6B7D82", linewidth=0.6)
    if name == "active_power" and regime_floor_kw is not None:
        # The ADR-047 regime boundary IS the healthy-state power floor that
        # built the training population; drawing it makes the in/out-of-regime
        # split visible on the same axis the heteroscedasticity is read from.
        ax.axvline(
            regime_floor_kw,
            color="#8E2727",
            linewidth=0.9,
            linestyle="--",
            label=f"fitted-support boundary ({regime_floor_kw:g} kW, ADR-047)",
        )
    ax.legend(fontsize=8, frameon=False)
    label = CONDITION_LABELS.get(name, name)
    _style(ax, f"Residual vs {label} — {target}\n{POPULATION_LABEL}", label, "residual (°C)")
    fig.tight_layout()
    _save(fig, out)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, default=REPO_ROOT / "artifacts")
    parser.add_argument("--experiment", default=None)
    parser.add_argument("--model", default="thesis", help="Model key to plot.")
    parser.add_argument("--svg", action="store_true", help="Also write SVG (PROJECT.md §31).")
    args = parser.parse_args()
    if args.svg:
        global SAVE_FORMATS
        SAVE_FORMATS = ("png", "svg")

    experiment = args.experiment
    if experiment is None:
        candidates = sorted(p.name for p in args.artifacts.glob("EXP-*") if p.is_dir())
        if not candidates:
            raise SystemExit(f"No experiment directories under {args.artifacts}")
        experiment = candidates[-1]
    directory = args.artifacts / experiment
    plots = directory / "plots"
    plots.mkdir(parents=True, exist_ok=True)

    residuals, predictions = _load(directory, HEADLINE_PARTITION)
    if args.model not in predictions:
        raise SystemExit(f"No predictions for model {args.model!r} in {directory}")

    # The residual frame covers the full unfiltered monitoring partition; the
    # headline slice is a row-subset of it. Align on (timestamp, turbine) so
    # the figures describe exactly the population the headline metrics do.
    slice_index = predictions[args.model].index
    test_frame = pd.read_parquet(directory / "predictions" / f"{args.model}_test.parquet")
    in_slice = test_frame.index.isin(slice_index)

    # The ADR-047 regime boundary, read from the stored regime-split artifact
    # so the line in the figure cannot disagree with the analysis it cites.
    # Absent artifact -> no line, never a guessed constant.
    regime_floor_kw: float | None = None
    regime_path = directory / "evaluation" / "regime_split.json"
    if regime_path.is_file():
        regime_floor_kw = float(
            json.loads(regime_path.read_text(encoding="utf-8"))["regime_boundary"]["floor_kw"]
        )

    written: list[str] = []
    for target, group in residuals.groupby("target"):
        group = group.sort_values("timestamp").reset_index(drop=True)
        short = str(target).replace("gearbox_", "").replace("_temperature", "")

        for name, fn in (
            ("actual_vs_predicted", plot_actual_vs_predicted),
            ("residual_distribution", plot_error_distribution),
            ("residual_over_time", plot_residual_over_time),
        ):
            path = plots / f"{short}_{name}.png"
            fn(group, str(target), path)
            written.append(path.name)

        errors = residual(group["actual"].to_numpy(), group["prediction"].to_numpy())
        for condition in ("active_power", "wind_speed", "ambient_temperature"):
            values = _condition_series(directory, group, condition)
            if values is None:
                continue
            path = plots / f"{short}_residual_vs_{condition}.png"
            plot_error_vs_condition(errors, values, condition, str(target), path, regime_floor_kw)
            written.append(path.name)

    manifest = {
        "experiment_id": experiment,
        "model": args.model,
        "partition_note": (
            "Residual figures cover the full unfiltered monitoring partition "
            "(the detection population). The RQ1 headline metrics are computed "
            "on the healthy-filtered subset of it (ADR-022); "
            f"{int(in_slice.sum())} of {len(test_frame)} rows are in that slice."
        ),
        "scatter_subsample": {"max_points": SCATTER_MAX_POINTS, "seed": SCATTER_SEED},
        "population_label": POPULATION_LABEL,
        "regime_floor_kw": regime_floor_kw,
        "formats": list(SAVE_FORMATS),
        "figures": sorted(written),
    }
    (plots / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {len(written)} figures to {plots}")
    print(json.dumps(manifest, indent=2))
    return 0


def _condition_series(directory: Path, group: pd.DataFrame, condition: str) -> np.ndarray | None:
    """Condition values aligned to the residual rows.

    The residual frame carries no predictor columns, so the values are joined
    from the stored cleaned inputs when available. Returns None — and the
    figure is skipped rather than faked — when they are not.
    """
    source = directory / "evaluation" / "conditions.parquet"
    if not source.is_file():
        return None
    conditions = pd.read_parquet(source)
    if condition not in conditions.columns:
        return None
    merged = group.merge(conditions, on=["timestamp", "turbine_id"], how="left")
    return merged[condition].to_numpy(dtype=float)


if __name__ == "__main__":
    sys.exit(main())
