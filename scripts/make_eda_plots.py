"""Dataset / EDA figures for the thesis data chapter — evidence JSONs only.

WHY THIS EXISTS. Every dataset insight the thesis needs — coverage and the
2016 thermal cliff (LIM-005), missingness structure, the idle/generating
operating-regime split, the target-predictor correlation structure that
motivates the exogenous predictor set, the near-unity target coupling that
RQ2's verdict ultimately traces to (ADR-035), fleet coherence (ADR-029),
residual-scale autocorrelation (the block-bootstrap basis), the cleaning and
healthy-state attrition, and the ground-truth scarcity behind ADR-013/014 —
existed only as numbers inside ``docs/evidence/*.json`` and experiment
evaluation artifacts. No figure of any of it existed anywhere in the repo.

FACTS ONLY. The EDA JSON carries the banner "READ-ONLY EDA. Facts only" and
these figures inherit it: they render recorded numbers, never recompute from
the raw CSVs, and never designate anomalies. The attrition figure uses the
APPLIED per-experiment accounting (``cleaning_audit.json``,
``healthy_state_report.json``), not the EDA preview, so its numbers are the
ones the pipeline actually enforced.

Reads STORED ARTIFACTS ONLY:
    docs/evidence/KELMARSH_EDA_2016_2021.json
    docs/evidence/KELMARSH_STATUS_VOCABULARY_2016_2021.json
    artifacts/<EXP>/evaluation/{split,cleaning_audit,healthy_state_report}.json

Writes ``docs/evidence/figures/`` (committed — unlike ``artifacts/``, these
figures describe the dataset, not one run, and the preservation concern in
DEFENSE_READINESS G1 argues for keeping them under version control) plus an
``eda_figures_manifest.json`` recording inputs and the source banner.

Usage (from backend/):
    uv run python ../scripts/make_eda_plots.py --experiment EXP-YYYYMMDD-NNN
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")  # headless: no display is available on a clean runner
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = REPO_ROOT / "docs" / "evidence"

DPI = 150

#: Dated constants a figure marks but no artifact stores as a single field.
#: EVENT-001 episode span per ADR-024 (the manual healthy-state exclusion);
#: thermal-channel availability start per ADR-009/LIM-005 (gear-oil channels
#: are 100% null before this timestamp on every turbine).
EVENT_001_SPAN = (pd.Timestamp("2019-02-24T16:46:28Z"), pd.Timestamp("2019-05-30T07:34:04Z"))
EVENT_001_TURBINE = "Kelmarsh 1"
THERMAL_START = pd.Timestamp("2016-05-03T09:40:00Z")

#: Canonical channel display order: predictors upstream-to-nacelle, then the
#: two thermal targets last, so the target rows sit together in heatmaps.
CHANNEL_ORDER = (
    "wind_speed",
    "rotor_speed",
    "generator_speed",
    "active_power",
    "pitch_angle",
    "ambient_temperature",
    "nacelle_temperature",
    "gearbox_oil_temperature",
    "gearbox_bearing_temperature",
)

#: run_eda.py POWER_BIN_EDGES rendered as category labels.
POWER_BIN_LABELS = {
    "(-inf, 0.0]": "≤ 0",
    "(0.0, 50.0]": "0–50",  # noqa: RUF001 (axis label: real en dash)
    "(50.0, 250.0]": "50–250",  # noqa: RUF001
    "(250.0, 500.0]": "250–500",  # noqa: RUF001
    "(500.0, 1000.0]": "500–1000",  # noqa: RUF001
    "(1000.0, 1500.0]": "1000–1500",  # noqa: RUF001
    "(1500.0, inf]": "> 1500",
}

TURBINE_COLORS = {
    "Kelmarsh 1": "#0B6672",
    "Kelmarsh 2": "#8E2727",
    "Kelmarsh 3": "#8A5606",
    "Kelmarsh 4": "#4C7A8A",
    "Kelmarsh 5": "#6B7D82",
    "Kelmarsh 6": "#54406B",
}


def _style(ax: plt.Axes, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_title(title, fontsize=10)
    ax.set_xlabel(xlabel, fontsize=9)
    ax.set_ylabel(ylabel, fontsize=9)
    ax.grid(alpha=0.25, linewidth=0.5)
    ax.tick_params(labelsize=8)


#: Set to ("png", "svg") by --svg: §31 asks for PNG/SVG "where practical".
SAVE_FORMATS: tuple[str, ...] = ("png",)


def _save(fig: plt.Figure, out: Path) -> None:
    for fmt in SAVE_FORMATS:
        fig.savefig(out.with_suffix(f".{fmt}"), dpi=DPI)


def _short(channel: str) -> str:
    return channel.replace("gearbox_", "gearbox ").replace("_", " ")


# --------------------------------------------------------------------------
# Figure 1 — holdings, thermal coverage, and the ADR-023 split
# --------------------------------------------------------------------------


def plot_dataset_timeline(vocab: dict[str, Any], split: dict[str, Any], out: Path) -> None:
    """One row per turbine; one segment per year file, colored by the recorded
    thermal-target coverage fraction. The 2016 cliff (LIM-005), the ADR-023
    split boundaries, and the EVENT-001 exclusion span become one picture.
    """
    coverage = vocab["scada_coverage_per_year"]
    cmap = plt.get_cmap("YlGnBu")
    turbines = sorted(
        {e["file"].split("_Kelmarsh_")[1][0] for y in coverage.values() for e in y.values()}
    )

    fig, ax = plt.subplots(figsize=(10.5, 4.4))
    for year_folder in sorted(coverage):
        for entry in coverage[year_folder].values():
            turbine_no = entry["file"].split("_Kelmarsh_")[1][0]
            row = turbines.index(turbine_no)
            start = pd.Timestamp(entry["first_timestamp"])
            end = pd.Timestamp(entry["last_timestamp"])
            frac = entry["covered_fraction"]
            ax.barh(
                row,
                (end - start).days,
                left=mdates.date2num(start),
                height=0.62,
                color=cmap(0.15 + 0.85 * frac),
                edgecolor="white",
                linewidth=0.4,
            )
    boundaries = [pd.Timestamp(b) for b in split["boundaries_utc"]]
    # Staggered label heights: the two ADR-023 boundaries sit seven months
    # apart and their labels collide at a shared height.
    for ts, label, height, align in (
        (THERMAL_START, "thermal channels begin\n(ADR-009 / LIM-005)", 0.55, "center"),
        (boundaries[0], "train | validation\n(ADR-023)", 0.55, "right"),
        (boundaries[1], "validation | monitoring\n(ADR-023)", 0.0, "left"),
    ):
        ax.axvline(mdates.date2num(ts.tz_localize(None)), color="#8E2727", lw=1.0, ls="--")
        ax.annotate(
            label,
            (mdates.date2num(ts.tz_localize(None)), len(turbines) - 0.25 + height),
            fontsize=7,
            ha=align,
            va="bottom",
            color="#8E2727",
        )
    k1_row = turbines.index("1")
    ax.barh(
        k1_row,
        (EVENT_001_SPAN[1] - EVENT_001_SPAN[0]).days,
        left=mdates.date2num(EVENT_001_SPAN[0].tz_localize(None)),
        height=0.62,
        color="none",
        edgecolor="#8E2727",
        linewidth=1.4,
        hatch="///",
        label="EVENT-001 episode span (ADR-013/ADR-024)",
    )
    ax.set_yticks(range(len(turbines)))
    ax.set_yticklabels([f"Kelmarsh {t}" for t in turbines], fontsize=8)
    ax.set_ylim(-0.6, len(turbines) + 1.4)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.legend(fontsize=7, frameon=False, loc="upper right")
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(0.0, 1.0))
    fig.colorbar(sm, ax=ax, pad=0.01).set_label("thermal target coverage (fraction)", fontsize=8)
    _style(
        ax,
        "Data holdings and thermal-target coverage per turbine-year, with the ADR-023 split "
        "— facts only",
        "date (UTC)",
        "",
    )
    fig.tight_layout()
    _save(fig, out)
    plt.close(fig)


# --------------------------------------------------------------------------
# Figure 2 — canonical-channel missingness by turbine-year
# --------------------------------------------------------------------------


def plot_channel_missingness(eda: dict[str, Any], out: Path) -> None:
    """Null fraction of the 9 mapped canonical channels per turbine-year file,
    before any cleaning. The 2016 thermal block (34.5% null: pre-May rows,
    LIM-005) and the uniform ~1-2% background are the findings.
    """
    per_file = eda["per_file"].values()
    entries = sorted(per_file, key=lambda e: (e["year_folder"], e["turbine"]))
    years = sorted({e["year_folder"] for e in entries})
    turbines = sorted({e["turbine"] for e in entries})
    columns = [(y, t) for y in years for t in turbines]
    grid = np.full((len(CHANNEL_ORDER), len(columns)), np.nan)
    for e in entries:
        col = columns.index((e["year_folder"], e["turbine"]))
        for row, channel in enumerate(CHANNEL_ORDER):
            frac = e["missingness"]["per_channel_null_fraction"].get(channel)
            if frac is not None:
                grid[row, col] = frac

    fig, ax = plt.subplots(figsize=(11.5, 4.2))
    image = ax.imshow(grid, aspect="auto", cmap="YlOrBr", vmin=0.0, vmax=0.5)
    for i in range(1, len(years)):
        ax.axvline(i * len(turbines) - 0.5, color="white", linewidth=1.6)
    ax.set_xticks(range(len(columns)))
    ax.set_xticklabels([t.replace("Kelmarsh ", "K") for _, t in columns], fontsize=6)
    for i, year in enumerate(years):
        # Year group labels go BELOW the K1-K6 ticks; above they collide
        # with the title.
        ax.annotate(
            year.split("_")[2],
            ((i + 0.5) * len(turbines) - 0.5, len(CHANNEL_ORDER) + 0.9),
            annotation_clip=False,
            ha="center",
            fontsize=8,
        )
    ax.set_yticks(range(len(CHANNEL_ORDER)))
    ax.set_yticklabels([_short(c) for c in CHANNEL_ORDER], fontsize=8)
    fig.colorbar(image, ax=ax, pad=0.01).set_label("null fraction", fontsize=8)
    _style(
        ax,
        "Canonical-channel missingness by turbine-year, before any cleaning — facts only.\n"
        "The 2016 thermal-channel block is the LIM-005 pre-May gap; capped at 0.5 for contrast.",
        "",
        "",
    )
    ax.grid(False)
    fig.tight_layout(rect=(0.0, 0.04, 1.0, 1.0))
    _save(fig, out)
    plt.close(fig)


# --------------------------------------------------------------------------
# Figure 3 — operating regime: power distribution and capacity factors
# --------------------------------------------------------------------------


def plot_operating_regime(eda: dict[str, Any], out: Path) -> None:
    """Left: share of rows per power bin and turbine, with the 50 kW
    healthy-state floor marked — the idle/generating bimodality that motivates
    the floor and later the ADR-047 regime split. Right: the per-turbine
    scalars behind it.
    """
    per_turbine = eda["per_turbine"]
    turbines = sorted(per_turbine)
    bins = list(POWER_BIN_LABELS)

    fig, (ax_bins, ax_scalars) = plt.subplots(
        1, 2, figsize=(11.0, 4.0), gridspec_kw={"width_ratios": [1.5, 1.0]}
    )
    x = np.arange(len(bins))
    for turbine in turbines:
        regime = per_turbine[turbine]["operating_regime"]
        counts = np.array([regime["power_bin_counts"][b] for b in bins], dtype=float)
        ax_bins.plot(
            x,
            counts / counts.sum(),
            marker="o",
            markersize=3,
            linewidth=1.0,
            color=TURBINE_COLORS[turbine],
            label=turbine.replace("Kelmarsh ", "K"),
        )
    ax_bins.axvline(1.5, color="#8E2727", linewidth=0.9, linestyle="--")
    ax_bins.annotate(
        "healthy-state floor (50 kW)",
        (1.5, ax_bins.get_ylim()[1] * 0.97),
        fontsize=7,
        color="#8E2727",
        rotation=90,
        va="top",
        ha="right",
    )
    ax_bins.set_xticks(x)
    ax_bins.set_xticklabels([POWER_BIN_LABELS[b] for b in bins], fontsize=8)
    ax_bins.legend(fontsize=7, frameon=False, ncol=2)
    _style(ax_bins, "Share of rows per active-power bin", "active power (kW)", "share of rows")

    x_t = np.arange(len(turbines))
    for key, label, marker, color in (
        ("capacity_factor", "capacity factor", "o", "#0B6672"),
        ("fraction_below_power_floor", "fraction below 50 kW", "s", "#8A5606"),
        ("fraction_negative_power", "fraction with power ≤ 0", "^", "#6B7D82"),
    ):
        values = [per_turbine[t]["operating_regime"][key] for t in turbines]
        ax_scalars.plot(
            x_t, values, marker=marker, markersize=4, linewidth=1.0, color=color, label=label
        )
    ax_scalars.set_xticks(x_t)
    ax_scalars.set_xticklabels([t.replace("Kelmarsh ", "K") for t in turbines], fontsize=8)
    ax_scalars.set_ylim(0.0, None)
    ax_scalars.legend(fontsize=7, frameon=False)
    _style(ax_scalars, "Per-turbine operating scalars", "", "fraction")
    fig.suptitle(
        "Operating regime across 2016-2021 (rated 2,050 kW assumed) — facts only, "
        "before any cleaning.",
        fontsize=9,
    )
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.94))
    _save(fig, out)
    plt.close(fig)


# --------------------------------------------------------------------------
# Figure 4 — correlation structure: predictors, and the target coupling
# --------------------------------------------------------------------------


def plot_correlation_structure(eda: dict[str, Any], out: Path) -> None:
    """Left: fleet-mean Pearson between each target and each exogenous
    predictor. Right: the target-target correlation by power bin, per turbine
    — the near-unity coupling at idle and rated that ADR-035 later measured on
    residuals ("one heat path, two thermometers") is already visible in the
    raw temperatures.
    """
    per_turbine = eda["per_turbine"]
    turbines = sorted(per_turbine)
    predictors = sorted(eda["canonical_predictors"])
    targets = sorted(eda["canonical_targets"])

    matrix = np.zeros((len(targets), len(predictors)))
    for i, target in enumerate(targets):
        for j, predictor in enumerate(predictors):
            matrix[i, j] = np.mean(
                [
                    per_turbine[t]["target_relationships"]["target_vs_predictor_pearson"][target][
                        predictor
                    ]
                    for t in turbines
                ]
            )

    fig, (ax_heat, ax_bins) = plt.subplots(
        1, 2, figsize=(11.5, 3.9), gridspec_kw={"width_ratios": [1.5, 1.0]}
    )
    image = ax_heat.imshow(matrix, aspect="auto", cmap="RdBu_r", vmin=-1.0, vmax=1.0)
    for i in range(len(targets)):
        for j in range(len(predictors)):
            ax_heat.annotate(
                f"{matrix[i, j]:+.2f}",
                (j, i),
                ha="center",
                va="center",
                fontsize=8,
                color="white" if abs(matrix[i, j]) > 0.55 else "black",
            )
    ax_heat.set_xticks(range(len(predictors)))
    ax_heat.set_xticklabels([_short(p) for p in predictors], fontsize=7, rotation=18)
    ax_heat.set_yticks(range(len(targets)))
    ax_heat.set_yticklabels([_short(t) for t in targets], fontsize=8)
    fig.colorbar(image, ax=ax_heat, pad=0.01).set_label("Pearson r (fleet mean)", fontsize=8)
    ax_heat.set_title("Target vs exogenous predictor (fleet mean)", fontsize=10)
    ax_heat.grid(False)

    bins = list(POWER_BIN_LABELS)
    x = np.arange(len(bins))
    for turbine in turbines:
        by_bin = per_turbine[turbine]["target_relationships"]["by_power_bin"]
        values = [by_bin[b]["pearson"] for b in bins]
        ax_bins.plot(
            x,
            values,
            marker="o",
            markersize=3,
            linewidth=1.0,
            color=TURBINE_COLORS[turbine],
            label=turbine.replace("Kelmarsh ", "K"),
        )
    ax_bins.set_xticks(x)
    ax_bins.set_xticklabels([POWER_BIN_LABELS[b] for b in bins], fontsize=7, rotation=18)
    ax_bins.set_ylim(0.55, 1.0)
    ax_bins.legend(fontsize=7, frameon=False, ncol=2, loc="lower right")
    _style(
        ax_bins,
        "Bearing-oil temperature Pearson by power bin",
        "active power (kW)",
        "Pearson r",
    )
    fig.suptitle(
        "Correlation structure of the raw channels, 2016-2021 — facts only. The right panel "
        "is the raw-temperature\nprecursor of the residual coupling ADR-035 measured "
        "(r = 0.93-0.95) and RQ2's verdict traces to.",
        fontsize=8,
    )
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.88))
    _save(fig, out)
    plt.close(fig)


# --------------------------------------------------------------------------
# Figure 5 — fleet coherence per channel
# --------------------------------------------------------------------------


def plot_fleet_coherence(eda: dict[str, Any], out: Path) -> None:
    """Mean pairwise cross-turbine Pearson per canonical channel with min-max
    whiskers — the measured basis of the fleet-relative reasoning (ADR-029)
    and of LIM-031's no-model fleet-median comparator.
    """
    coherence = eda["fleet_coherence"]
    channels = [c for c in CHANNEL_ORDER if c in coherence]
    means = [coherence[c]["mean_pairwise_pearson"] for c in channels]
    mins = [coherence[c]["min_pairwise_pearson"] for c in channels]
    maxs = [coherence[c]["max_pairwise_pearson"] for c in channels]

    fig, ax = plt.subplots(figsize=(7.6, 3.9))
    y = np.arange(len(channels))
    ax.errorbar(
        means,
        y,
        xerr=[np.subtract(means, mins), np.subtract(maxs, means)],
        fmt="o",
        markersize=5,
        capsize=3,
        linewidth=1.1,
        color="#0B6672",
    )
    for yi, mean in zip(y, means, strict=True):
        ax.annotate(
            f"{mean:.3f}", (mean, yi), textcoords="offset points", xytext=(-6, 6), fontsize=7,
            ha="right",
        )
    ax.set_yticks(y)
    ax.set_yticklabels([_short(c) for c in channels], fontsize=8)
    ax.set_xlim(0.4, 1.03)
    _style(
        ax,
        "Cross-turbine coherence per channel, 2016-2021 — facts only\n"
        "(mean pairwise Pearson over the 6 turbines; whiskers: min-max pair)",
        "pairwise Pearson r",
        "",
    )
    fig.tight_layout()
    _save(fig, out)
    plt.close(fig)


# --------------------------------------------------------------------------
# Figure 6 — autocorrelation of the thermal targets
# --------------------------------------------------------------------------


def plot_autocorrelation(eda: dict[str, Any], out: Path) -> None:
    """ACF of both targets at the recorded lags, raw and detrended-proxy, per
    turbine — the measured persistence behind the block-bootstrap design and
    the EWMA persistence rule. The detrended proxy is run_eda.py's stand-in
    (OLS on power and ambient), NOT the NBM residual.
    """
    per_turbine = eda["per_turbine"]
    turbines = sorted(per_turbine)
    targets = sorted(eda["canonical_targets"])

    fig, axes = plt.subplots(1, len(targets), figsize=(10.5, 3.9), sharey=True)
    for ax, target in zip(np.atleast_1d(axes), targets, strict=True):
        band = None
        for kind, style, color in (("raw", "-", "#0B6672"), ("detrended_proxy", "--", "#8A5606")):
            for turbine in turbines:
                channel = per_turbine[turbine]["autocorrelation_structure"]["channels"][target]
                acf = channel[kind]["acf_at_selected_lags"]
                lags_h = [int(lag) / 6.0 for lag in acf]
                ax.plot(
                    lags_h,
                    list(acf.values()),
                    style,
                    linewidth=0.7,
                    alpha=0.45,
                    color=color,
                    label=(
                        {"raw": "raw", "detrended_proxy": "detrended proxy (OLS stand-in)"}[kind]
                        if turbine == turbines[0]
                        else None
                    ),
                )
                band = channel[kind]["white_noise_band"]
        ax.axhline(band, color="#6B7D82", linewidth=0.7, linestyle=":", label="white-noise band")
        ax.set_xscale("log")
        decorrelation = [
            per_turbine[t]["autocorrelation_structure"]["channels"][target]["raw"][
                "decorrelation_lag_hours"
            ]
            for t in turbines
        ]
        finite = [d for d in decorrelation if d is not None]
        note = (
            f"raw decorrelation lag: median {np.median(finite):.0f} h"
            if finite
            else "raw ACF never decorrelates within the search limit"
        )
        if any(d is None for d in decorrelation):
            note += "\n(some turbines exceed the search limit)"
        ax.annotate(note, (0.03, 0.06), xycoords="axes fraction", fontsize=7)
        ax.legend(fontsize=7, frameon=False)
        _style(ax, _short(target), "lag (hours, log)", "autocorrelation")
    fig.suptitle(
        "Autocorrelation of the thermal targets at the recorded lags, per turbine, "
        "2016-2021 — facts only\n(longest contiguous 10-min run; basis for blocked "
        "bootstrap and HAC choices).",
        fontsize=8,
    )
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.88))
    _save(fig, out)
    plt.close(fig)


# --------------------------------------------------------------------------
# Figure 7 — applied attrition: raw rows to the healthy training population
# --------------------------------------------------------------------------


def plot_attrition(
    cleaning: dict[str, Any], healthy: dict[str, Any], split: dict[str, Any], out: Path
) -> None:
    """The applied funnel, from the experiment's own audit artifacts: cleaning
    (whole holdings, registry order), then the healthy-state filter (train and
    validation windows only — the monitoring stream is never filtered).
    """
    stages: list[tuple[str, int, str]] = []
    for op in cleaning["operations"]:
        removed = op["rows_removed"]
        nullified = op.get("detail", {}).get("values_nullified")
        note = f"−{removed:,}" if removed else ""  # noqa: RUF001 (label: real minus sign)
        if nullified:
            note = f"{note} ({nullified:,} values nullified)".strip()
        stages.append((op["rule"].replace("_", " "), op["rows_after"], note))

    fig, (ax_clean, ax_healthy) = plt.subplots(
        1, 2, figsize=(11.0, 4.0), gridspec_kw={"width_ratios": [1.3, 1.0]}
    )
    y = np.arange(len(stages) + 1)[::-1]
    rows_before = cleaning["operations"][0]["rows_before"]
    ax_clean.barh(y[0], rows_before, color="#6B7D82", alpha=0.75, height=0.55)
    ax_clean.annotate(f"{rows_before:,}", (rows_before, y[0]), xytext=(4, -3),
                      textcoords="offset points", fontsize=8)
    for yi, (_rule, after, note) in zip(y[1:], stages, strict=True):
        ax_clean.barh(yi, after, color="#0B6672", alpha=0.85, height=0.55)
        label = f"{after:,}" + (f"   {note}" if note else "")
        ax_clean.annotate(label, (after, yi), xytext=(4, -3), textcoords="offset points",
                          fontsize=8)
    ax_clean.set_yticks(y)
    ax_clean.set_yticklabels(
        ["source rows (36 files)"] + [f"after {rule}" for rule, _, _ in stages], fontsize=8
    )
    ax_clean.set_xlim(0, rows_before * 1.28)
    _style(ax_clean, "Cleaning (whole holdings, registry order)", "rows", "")

    sizes = split["sizes"]
    entries = [
        ("train + validation window", healthy["total"], "#6B7D82"),
        (
            f"excluded: alarm periods (−{healthy['exclusion_counts']['alarm_period']:,})",  # noqa: RUF001
            None,
            None,
        ),
        (
            "excluded: below 50 kW floor "
            f"(−{healthy['exclusion_counts']['below_minimum_active_power']:,})",  # noqa: RUF001
            None,
            None,
        ),
        ("healthy accepted", healthy["accepted"], "#0B6672"),
        (f"  = training {sizes['train']:,} + validation {sizes['validation']:,}", None, None),
    ]
    y2_positions = []
    labels2 = []
    pos = len(entries)
    for label, value, color in entries:
        pos -= 1
        labels2.append(label)
        y2_positions.append(pos)
        if value is not None:
            ax_healthy.barh(pos, value, color=color, alpha=0.85, height=0.55)
            ax_healthy.annotate(f"{value:,}", (value, pos), xytext=(4, -3),
                                textcoords="offset points", fontsize=8)
    ax_healthy.set_yticks(y2_positions)
    ax_healthy.set_yticklabels(labels2, fontsize=8)
    ax_healthy.set_xlim(0, healthy["total"] * 1.3)
    _style(
        ax_healthy,
        f"Healthy-state filter\n(train/val only; retention {healthy['retention_pct']:.1f}%)",
        "rows",
        "",
    )
    fig.suptitle(
        f"Applied row attrition — cleaning_audit.json (arithmetic holds: "
        f"{cleaning['arithmetic_holds']}) and healthy_state_report.json.\n"
        f"The monitoring stream ({sizes['test']:,} rows) is never healthy-filtered; the "
        "ADR-022 headline slice is computed after detection.",
        fontsize=8,
    )
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.88))
    _save(fig, out)
    plt.close(fig)


# --------------------------------------------------------------------------
# Figure 8 — status-log vocabulary: the ground-truth scarcity
# --------------------------------------------------------------------------


def plot_status_vocabulary(vocab: dict[str, Any], out: Path) -> None:
    """Status-log rows per year and tier (log scale — Informational dominates
    by two orders of magnitude). The evidentiary point is scarcity: 188
    distinct codes, no Error/Fault tier, no maintenance free text (LIM-002),
    and exactly one qualifying labelled gearbox event (EVENT-001, ADR-013), so
    the Phase 0.5 rule selects the descriptive branch (ADR-014).
    """
    rows = vocab["status_vocabulary"]["per_turbine_year"]
    years = sorted({r["year_folder"].split("_")[2] for r in rows})
    tiers = ("Informational", "Warning", "Stop", "Communication")
    tier_colors = {"Informational": "#6B7D82", "Warning": "#8A5606",
                   "Stop": "#8E2727", "Communication": "#4C7A8A"}
    counts = {tier: [] for tier in tiers}
    for year in years:
        year_rows = [r for r in rows if r["year_folder"].split("_")[2] == year]
        for tier in tiers:
            counts[tier].append(sum(r["counts_by_status"].get(tier, 0) for r in year_rows))

    fig, ax = plt.subplots(figsize=(8.0, 3.9))
    x = np.arange(len(years))
    width = 0.2
    for i, tier in enumerate(tiers):
        ax.bar(
            x + (i - 1.5) * width,
            counts[tier],
            width=width,
            color=tier_colors[tier],
            alpha=0.85,
            label=tier,
        )
    ax.set_yscale("log")
    ax.set_ylim(top=ax.get_ylim()[1] * 5)  # headroom so the legend clears the bars
    ax.set_xticks(x)
    ax.set_xticklabels(years, fontsize=8)
    ax.legend(fontsize=7, frameon=False, ncol=4, loc="upper center")
    n_codes = vocab["status_vocabulary"]["n_distinct_codes"]
    total = vocab["status_vocabulary"]["total_status_rows"]
    _style(
        ax,
        f"Status-log rows per year and tier ({total:,} rows, {n_codes} distinct codes; "
        "log scale) — facts only",
        "year",
        "status rows (log)",
    )
    fig.suptitle(
        "The four recorded tiers only — no Error or Fault tier exists; no maintenance free "
        "text (LIM-002).\nExactly one qualifying labelled gearbox event (EVENT-001, ADR-013) "
        "→ descriptive branch (ADR-014).",
        fontsize=8,
    )
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.87))
    _save(fig, out)
    plt.close(fig)


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
    evaluation = args.artifacts / experiment / "evaluation"

    eda_path = EVIDENCE / "KELMARSH_EDA_2016_2021.json"
    vocab_path = EVIDENCE / "KELMARSH_STATUS_VOCABULARY_2016_2021.json"
    eda = json.loads(eda_path.read_text(encoding="utf-8"))
    vocab = json.loads(vocab_path.read_text(encoding="utf-8"))
    split = json.loads((evaluation / "split.json").read_text(encoding="utf-8"))
    cleaning = json.loads((evaluation / "cleaning_audit.json").read_text(encoding="utf-8"))
    healthy = json.loads((evaluation / "healthy_state_report.json").read_text(encoding="utf-8"))

    figures_dir = EVIDENCE / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    for name, render in (
        ("dataset_timeline.png", lambda p: plot_dataset_timeline(vocab, split, p)),
        ("channel_missingness.png", lambda p: plot_channel_missingness(eda, p)),
        ("operating_regime.png", lambda p: plot_operating_regime(eda, p)),
        ("correlation_structure.png", lambda p: plot_correlation_structure(eda, p)),
        ("fleet_coherence.png", lambda p: plot_fleet_coherence(eda, p)),
        ("autocorrelation.png", lambda p: plot_autocorrelation(eda, p)),
        ("data_attrition.png", lambda p: plot_attrition(cleaning, healthy, split, p)),
        ("status_ground_truth.png", lambda p: plot_status_vocabulary(vocab, p)),
    ):
        render(figures_dir / name)
        written.append(name)

    manifest = {
        "inputs": {
            "eda": {"path": str(eda_path.relative_to(REPO_ROOT)),
                    "generated_at_utc": eda["generated_at_utc"],
                    "mapping_hash": eda["mapping_hash"]},
            "status_vocabulary": {"path": str(vocab_path.relative_to(REPO_ROOT)),
                                  "generated_at_utc": vocab["generated_at_utc"]},
            "experiment": experiment,
            "experiment_files": ["split.json", "cleaning_audit.json", "healthy_state_report.json"],
        },
        "source_banner": eda["banner"],
        "constants": {
            "event_001_span_utc_adr_024": [str(EVENT_001_SPAN[0]), str(EVENT_001_SPAN[1])],
            "thermal_start_utc_adr_009": str(THERMAL_START),
        },
        "formats": list(SAVE_FORMATS),
        "figures": sorted(written),
    }
    (figures_dir / "eda_figures_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"Wrote {len(written)} figures to {figures_dir}")
    print(json.dumps(manifest["figures"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
