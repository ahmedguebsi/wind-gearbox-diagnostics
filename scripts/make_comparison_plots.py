"""Comparison figures: model accuracy CIs, RQ2 operating curves, channel geometry.

WHY THIS EXISTS. Three quantities central to Chapters 4-5 existed only as JSON:

- **model_rmse_comparison** — the RQ1 model comparison (XGBoost vs OLS vs
  Elastic Net) with its blocked-bootstrap confidence intervals
  (`first_run_summary.json`). The common presentation of such comparisons is a
  bare bar chart with a truncated axis; this figure draws point estimates with
  their CI whiskers instead, on the ADR-022 headline slice, so the reader sees
  whether intervals overlap rather than how tall a bar looks.
- **rq2_operating_curves** — the matched-FPR operating curves for the raw
  channels and the ADR-035 orthogonal modes (arm A6,
  `robustness_suite.json`). This is the project's honest analogue of a ROC
  comparison: with one contested labelled event there is no true-positive
  axis, so the curves show false-alarm rate against the control-limit
  multiplier at the declared ADR-028 row-time basis, with the ADR-025
  10 FA/turbine-year rung marked.
- **residual_channel_scatter** — the joint distribution of the two normalized
  residual channels per partition: the "thin cigar on the diagonal" ADR-035
  measured (r = 0.93-0.95), and the monitoring-partition inflation behind
  LIM-034/LIM-037, visible as the monitoring panel's blown-up cloud.

Two more render when their artifacts exist:

- **rmse_by_regime** — ADR-047's reporting rule as a figure: RMSE per model
  split at the fitted-support boundary (`regime_split.json`).
- **feature_importance** — native XGBoost gain/cover of the stored thesis
  booster, the only importance view PROJECT.md §30 permits (NO SHAP,
  LOCKED-07).

Reads STORED ARTIFACTS ONLY and writes into the experiment's own ``plots/``
directory (its manifest goes to ``comparison_manifest.json`` so the §20
diagnostic manifest is never clobbered). Figures regenerate in seconds and
cannot disagree with the numbers beside them — same persisted inputs.

Usage (from backend/):
    uv run python ../scripts/make_comparison_plots.py --experiment EXP-YYYYMMDD-NNN
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless: no display is available on a clean runner
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]

DPI = 150
SCATTER_MAX_POINTS = 20_000
SCATTER_SEED = 42
#: The RQ1 headline period (ADR-022) — figures follow the headline.
HEADLINE_PERIOD = "monitoring_healthy"
#: The ADR-025 rung the arms are matched at.
FPR_RUNG = 10.0

MODEL_LABELS = {
    "baseline": "OLS baseline",
    "elastic_net": "Elastic Net baseline",
    "thesis": "XGBoost (thesis)",
}
MODEL_COLORS = {"baseline": "#8A5606", "elastic_net": "#6B7D82", "thesis": "#0B6672"}

PIPELINE_COLORS = {
    "coordinated_2of2": "#0B6672",
    "coordinated_1of2": "#8E2727",
    "single_a": "#8A5606",
    "single_b": "#6B7D82",
}

#: Display names for the stored partition files. The parquet partition is
#: called "test" on disk, but the project's reporting vocabulary (ADR-022
#: three-period labels, README, LIMITATIONS) calls that stream the MONITORING
#: period; a printed figure must use the reporting name, with the file name
#: kept in parentheses so the artifact remains findable.
PARTITION_DISPLAY = {
    "training": "training",
    "validation": "validation",
    "test": "monitoring (stored as test)",
}


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


# --------------------------------------------------------------------------
# Figure 1 — RQ1 model comparison with blocked-bootstrap CIs
# --------------------------------------------------------------------------


def plot_model_comparison(summary: dict[str, Any], out: Path) -> None:
    metrics = summary["rq1_metrics_with_cis"][HEADLINE_PERIOD]
    period_label = summary["rq1_period_labels"][HEADLINE_PERIOD]
    targets = sorted(next(iter(metrics.values())).keys())
    models = [m for m in ("baseline", "elastic_net", "thesis") if m in metrics]

    fig, axes = plt.subplots(1, len(targets), figsize=(4.2 * len(targets), 3.8), sharey=False)
    for ax, target in zip(np.atleast_1d(axes), targets, strict=True):
        for i, model in enumerate(models):
            cell = metrics[model][target]["rmse"]
            point, lower, upper = cell["point"], cell["lower"], cell["upper"]
            color = MODEL_COLORS[model]
            ax.errorbar(
                i,
                point,
                yerr=[[point - lower], [upper - point]],
                fmt="o",
                markersize=5,
                capsize=4,
                linewidth=1.2,
                color=color,
            )
            note = "" if cell["reliable"] else " (CI unreliable)"
            ax.annotate(
                f"{point:.3f}{note}",
                (i, upper),
                textcoords="offset points",
                xytext=(0, 5),
                ha="center",
                fontsize=7,
            )
        ax.set_xticks(range(len(models)))
        ax.set_xticklabels([MODEL_LABELS[m] for m in models], fontsize=8, rotation=12)
        ax.set_xlim(-0.5, len(models) - 0.5)
        ax.margins(y=0.18)  # headroom so the CI annotations stay inside the axes
        short = target.replace("gearbox_", "").replace("_temperature", "")
        _style(ax, f"RMSE with 95% CI — {short}", "", "RMSE (°C)")
    fig.suptitle(f"Model comparison on the RQ1 headline slice — {period_label}", fontsize=9)
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.95))
    _save(fig, out)
    plt.close(fig)


# --------------------------------------------------------------------------
# Figure 2 — matched-FPR operating curves, raw channels vs orthogonal modes
# --------------------------------------------------------------------------


def _draw_curves(ax: plt.Axes, points: dict[str, Any], title: str) -> None:
    for name, op in points.items():
        base = name.split("_", 1)[1]  # strip the raw_/modes_ prefix
        if base.startswith("single"):
            key = (
                "single_a" if base.endswith(("bearing_temperature", "mode_common")) else "single_b"
            )
        else:
            key = base
        curve = pd.DataFrame(op["curve"])
        shown = curve[curve["false_alarms_per_turbine_year"] > 0.0]
        label = base.replace("_", " ").replace("gearbox ", "").replace(" temperature", "")
        matched = op["matched_multiplier"]
        if matched is not None:
            label += f" (matched {matched:.2f})"
            ax.plot(matched, FPR_RUNG, marker="v", markersize=6, color=PIPELINE_COLORS[key])
        ax.plot(
            shown["multiplier"],
            shown["false_alarms_per_turbine_year"],
            linewidth=1.2,
            color=PIPELINE_COLORS[key],
            label=label,
        )
    ax.axhline(FPR_RUNG, color="#8E2727", linewidth=0.8, linestyle="--")
    ax.set_yscale("log")
    ax.legend(fontsize=7, frameon=False, loc="upper right")
    _style(ax, title, "control-limit multiplier", "false alarms / turbine-year (log)")


def plot_operating_curves(suite: dict[str, Any], out: Path) -> None:
    arm = suite["arms"]["orthogonal"]
    points = arm["operating_points"]
    raw = {k: v for k, v in points.items() if k.startswith("raw_")}
    modes = {k: v for k, v in points.items() if k.startswith("modes_")}

    fig, (ax_raw, ax_modes) = plt.subplots(1, 2, figsize=(10.5, 4.6), sharey=True)
    _draw_curves(ax_raw, raw, "Raw channels (pre-registered verdict, reported first)")
    _draw_curves(ax_modes, modes, "Orthogonal modes (ADR-035 arm A6)")
    ax_modes.set_ylabel("")
    fig.suptitle(
        "False-alarm operating curves on healthy validation — ADR-028 row-time basis;\n"
        f"dashed line = {FPR_RUNG:g} FA/turbine-year (ADR-025). No detection axis exists: the "
        "single labelled event cannot\nsupply one (ADR-035 condition c). Zero-rate points are "
        "omitted by the log scale.",
        fontsize=8,
    )
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.88))
    _save(fig, out)
    plt.close(fig)


# --------------------------------------------------------------------------
# Figure 3 — the joint residual-channel geometry per partition
# --------------------------------------------------------------------------


def plot_channel_scatter(
    directory: Path, mode_stats: dict[str, Any] | None, out: Path
) -> dict[str, Any]:
    partitions = ("training", "validation", "test")
    panels: list[tuple[str, pd.DataFrame, float]] = []
    for partition in partitions:
        frame = pd.read_parquet(directory / "residuals" / f"{partition}.parquet")
        wide = frame.pivot(
            index=["turbine_id", "timestamp"], columns="target", values="normalized_residual"
        ).dropna()
        first, second = sorted(wide.columns)
        r = float(wide[first].corr(wide[second]))
        panels.append((partition, wide, r))

    lim = float(max(np.nanquantile(np.abs(w[[c for c in w.columns]]), 0.999) for _, w, _ in panels))
    rng = np.random.default_rng(SCATTER_SEED)
    fig, axes = plt.subplots(1, 3, figsize=(12.0, 4.8), sharex=True, sharey=True)
    stats: dict[str, Any] = {}
    for ax, (partition, wide, r) in zip(axes, panels, strict=True):
        first, second = sorted(wide.columns)
        take: Any = slice(None)
        if len(wide) > SCATTER_MAX_POINTS:
            take = np.sort(rng.choice(len(wide), SCATTER_MAX_POINTS, replace=False))
        ax.scatter(
            wide[first].to_numpy()[take],
            wide[second].to_numpy()[take],
            s=2,
            alpha=0.12,
            linewidths=0,
            color="#0B6672",
        )
        ax.plot([-lim, lim], [-lim, lim], color="#8E2727", linewidth=0.8)
        ax.set_xlim(-lim, lim)
        ax.set_ylim(-lim, lim)
        ax.set_aspect("equal")
        annotation = f"channel r = {r:.3f}"
        if mode_stats is not None and partition in mode_stats:
            annotation += f"\nmode r = {mode_stats[partition]['mode_pearson']:.3f}"
        ax.annotate(
            annotation,
            (0.03, 0.94),
            xycoords="axes fraction",
            fontsize=8,
            va="top",
            bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.75, "linewidth": 0},
        )
        _style(
            ax,
            f"{PARTITION_DISPLAY[partition]} (n = {len(wide):,})",
            "bearing residual (normalized)",
            "oil residual (normalized)" if partition == "training" else "",
        )
        stats[partition] = {"channel_pearson": r, "n_aligned": len(wide)}
    fig.suptitle(
        'Joint residual-channel geometry — the ADR-035 "thin cigar on the diagonal".\n'
        "The monitoring panel's inflation is LIM-034; the mode-correlation collapse there "
        "is LIM-037.",
        fontsize=9,
    )
    # Equal-aspect panels defeat tight_layout's bottom-margin estimate, so the
    # margins are explicit: without this the x-axis labels render off-canvas.
    fig.subplots_adjust(left=0.07, right=0.98, bottom=0.14, top=0.80, wspace=0.15)
    _save(fig, out)
    plt.close(fig)
    return stats


# --------------------------------------------------------------------------
# Figure 4 — RMSE split by operating regime (ADR-047)
# --------------------------------------------------------------------------


def plot_regime_split(split: dict[str, Any], out: Path) -> None:
    """ADR-047's reporting rule rendered as a figure.

    "NO figure aggregated over the whole stream is a statement about the
    model" — this one shows why: per model and target, the RMSE inside the
    fitted operating regime sits an order of magnitude below the RMSE outside
    it, so the log axis is not presentation taste but the finding itself.
    Reads the stored ``regime_split.json`` (run_regime_split.py), never
    recomputes.
    """
    accuracy = split["accuracy_by_regime"]
    floor = split["regime_boundary"]["floor_kw"]
    models = [m for m in ("baseline", "elastic_net", "thesis") if m in accuracy]
    targets = sorted(next(iter(accuracy.values())).keys())

    fig, axes = plt.subplots(1, len(targets), figsize=(4.2 * len(targets), 3.8), sharey=True)
    for ax, target in zip(np.atleast_1d(axes), targets, strict=True):
        for i, model in enumerate(models):
            cells = accuracy[model][target]
            for regime, marker, fill in (("in_regime", "o", True), ("out_of_regime", "^", False)):
                cell = cells[regime]
                ax.plot(
                    i,
                    cell["rmse"],
                    marker=marker,
                    markersize=6,
                    linestyle="none",
                    color=MODEL_COLORS[model],
                    markerfacecolor=MODEL_COLORS[model] if fill else "none",
                )
                ax.annotate(
                    f"{cell['rmse']:.2f}",
                    (i, cell["rmse"]),
                    textcoords="offset points",
                    xytext=(8, -3),
                    fontsize=7,
                )
        ax.set_yscale("log")
        ax.set_xticks(range(len(models)))
        ax.set_xticklabels([MODEL_LABELS[m] for m in models], fontsize=8, rotation=12)
        ax.set_xlim(-0.5, len(models) - 0.5)
        short = target.replace("gearbox_", "").replace("_temperature", "")
        _style(ax, f"RMSE by operating regime — {short}", "", "RMSE (°C, log)")
    # Legend proxies: filled = in-regime, open = out-of-regime (colors vary by model).
    handles = [
        plt.Line2D([], [], marker="o", ls="none", color="#3A3A3A", label="in regime"),
        plt.Line2D(
            [], [], marker="^", ls="none", color="#3A3A3A", markerfacecolor="none",
            label="out of regime",
        ),
    ]
    np.atleast_1d(axes)[-1].legend(handles=handles, fontsize=8, frameon=False, loc="center right")
    thesis = accuracy["thesis"][targets[0]]
    fig.suptitle(
        "Monitoring-period error split at the fitted-support boundary "
        f"({floor:g} kW — ADR-047; the boundary IS the training power floor).\n"
        f"In-regime rows: {thesis['in_regime']['share']:.1%} of the stream carrying "
        f"{thesis['in_regime']['variance_share']:.1%} of residual variance; out-of-regime: "
        f"{thesis['out_of_regime']['share']:.1%} carrying "
        f"{thesis['out_of_regime']['variance_share']:.1%} (LIM-034).",
        fontsize=8,
    )
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.90))
    _save(fig, out)
    plt.close(fig)


# --------------------------------------------------------------------------
# Figure 5 — native XGBoost feature importance (PROJECT.md §30; no SHAP)
# --------------------------------------------------------------------------


def plot_feature_importance(model_dir: Path, out: Path) -> dict[str, Any] | None:
    """Native gain/cover importance of the stored thesis booster.

    PROJECT.md §30 permits exactly this view and nothing further: "native
    XGBoost gain/cover importance only; NO SHAP views" (LOCKED-07). The
    stored model file is itself an experiment artifact, so this stays within
    the ADR-045 stored-artifacts-only rule. The caption states the claim
    altitude: importance describes the fitted prediction function over the
    healthy training population — it is not diagnostic evidence and not a
    residual attribution.
    """
    try:
        import xgboost
    except ImportError:
        return None
    path = model_dir / "thesis" / "__multi__.ubj"
    if not path.is_file():
        return None
    booster = xgboost.Booster()
    booster.load_model(str(path))
    gain = booster.get_score(importance_type="gain")
    cover = booster.get_score(importance_type="cover")
    features = sorted(gain, key=gain.get)

    fig, (ax_gain, ax_cover) = plt.subplots(1, 2, figsize=(9.0, 3.8), sharey=True)
    y = np.arange(len(features))
    ax_gain.barh(y, [gain[f] for f in features], color="#0B6672", alpha=0.85)
    ax_cover.barh(y, [cover.get(f, 0.0) for f in features], color="#8A5606", alpha=0.85)
    ax_gain.set_yticks(y)
    ax_gain.set_yticklabels([f.replace("_", " ") for f in features], fontsize=8)
    _style(ax_gain, "mean split gain", "gain", "")
    _style(ax_cover, "mean split cover", "cover", "")
    fig.suptitle(
        "Native XGBoost importance of the multi-target thesis NBM (gain/cover only — "
        "PROJECT.md §30, LOCKED-07).\nDescribes the fitted prediction function over the healthy "
        "training population; aggregated across both targets;\nnot diagnostic evidence and not "
        "a residual attribution.",
        fontsize=8,
    )
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.86))
    _save(fig, out)
    plt.close(fig)
    return {"gain": gain, "cover": cover, "model_file": path.name}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, default=REPO_ROOT / "artifacts")
    parser.add_argument("--experiment", default=None)
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

    summary_path = directory / "evaluation" / "first_run_summary.json"
    if not summary_path.is_file():
        raise SystemExit(f"Missing {summary_path}; run the experiment first")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    written: list[str] = []
    plot_model_comparison(summary, plots / "model_rmse_comparison.png")
    written.append("model_rmse_comparison.png")

    suite_path = directory / "evaluation" / "robustness_suite.json"
    suite: dict[str, Any] | None = None
    mode_stats: dict[str, Any] | None = None
    if suite_path.is_file():
        suite = json.loads(suite_path.read_text(encoding="utf-8"))
        if "orthogonal" in suite.get("arms", {}) and "FAILED" not in suite["arms"]["orthogonal"]:
            plot_operating_curves(suite, plots / "rq2_operating_curves.png")
            written.append("rq2_operating_curves.png")
            mode_stats = suite["arms"]["orthogonal"].get("mode_statistics")
    if "rq2_operating_curves.png" not in written:
        print(
            "SKIPPED rq2_operating_curves: no completed `orthogonal` arm in "
            f"{suite_path} (run run_robustness_suite.py --arms orthogonal)"
        )

    channel_stats = plot_channel_scatter(
        directory, mode_stats, plots / "residual_channel_scatter.png"
    )
    written.append("residual_channel_scatter.png")

    regime_path = directory / "evaluation" / "regime_split.json"
    regime: dict[str, Any] | None = None
    if regime_path.is_file():
        regime = json.loads(regime_path.read_text(encoding="utf-8"))
        plot_regime_split(regime, plots / "rmse_by_regime.png")
        written.append("rmse_by_regime.png")
    else:
        print(f"SKIPPED rmse_by_regime: no {regime_path} (run run_regime_split.py)")

    importance = plot_feature_importance(directory / "model", plots / "feature_importance.png")
    if importance is not None:
        written.append("feature_importance.png")
    else:
        print(f"SKIPPED feature_importance: no thesis booster under {directory / 'model'}")

    manifest = {
        "experiment_id": experiment,
        "inputs": {
            "first_run_summary": summary_path.name,
            "robustness_suite": suite_path.name if suite is not None else None,
            "regime_split": regime_path.name if regime is not None else None,
            "thesis_model": importance["model_file"] if importance is not None else None,
            "residual_parquets": ["training", "validation", "test"],
        },
        "partition_display": PARTITION_DISPLAY,
        "formats": list(SAVE_FORMATS),
        "headline_period": HEADLINE_PERIOD,
        "fpr_rung": FPR_RUNG,
        "scatter_subsample": {"max_points": SCATTER_MAX_POINTS, "seed": SCATTER_SEED},
        "channel_scatter_stats": channel_stats,
        "figures": sorted(written),
        "note": (
            "Deliberately NOT rendered, and why: class-balance plots (one "
            "labelled event, not a class), confusion matrices and detection "
            "ROC/AUC (no event-level ground-truth axis exists below the "
            "Phase 0.5 threshold; ADR-014), and training curves (the XGBoost "
            "tuning trials are recorded in metadata.json)."
        ),
    }
    (plots / "comparison_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"Wrote {len(written)} figures to {plots}")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
