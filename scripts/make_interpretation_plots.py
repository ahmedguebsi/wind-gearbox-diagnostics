"""RQ3 interpretation figures — ruleset v2 episode outcomes (ADR-049/ADR-050).

WHY THIS EXISTS. The bounded-positive RQ3 claim and both halves of LIM-038
existed only as JSON: the v2 representation differentiates (four output kinds
with per-episode ordering evidence, where v1 returned one undifferentiated
candidate set — LIM-030), episode volume is far above operator-guidance level,
and Type A episodes concentrate on Kelmarsh 4 while Kelmarsh 1 produces none.
Chapter 5 needs those three facts visible, with the claim altitude printed on
the figure itself.

CLAIM ALTITUDE (ADR-050 outcome, carried into every caption): these are
EXPLORATORY, representation-level results. Detection value of the modes is
untested (ADR-035 condition c); n(maintenance-confirmed faults) = 0, so no
output is a validated diagnosis; eligibility is never a success rate
(ADR-049). EVENT-001 wording follows ADR-050(e): the system abstained from
unsupported positive attribution — never "correctly said I don't know".

Reads STORED ARTIFACTS ONLY (``evaluation/ruleset_v2_evaluation.json``) and
writes into the experiment's own ``plots/`` directory; the manifest goes to
``interpretation_manifest.json`` so the other plot manifests are never
clobbered.

Usage (from backend/):
    uv run python ../scripts/make_interpretation_plots.py --experiment EXP-YYYYMMDD-NNN
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

REPO_ROOT = Path(__file__).resolve().parents[1]

DPI = 150

TYPE_LABELS = {
    "A_positive_candidate": "Type A — positive candidate",
    "B_ambiguous_candidates": "Type B — ambiguous candidates",
    "C_no_candidate": "Type C — no candidate (R5)",
}
TYPE_COLORS = {
    "A_positive_candidate": "#8E2727",
    "B_ambiguous_candidates": "#8A5606",
    "C_no_candidate": "#6B7D82",
}
RULE_COLORS = {
    "FMEA-001": "#0B6672",
    "FMEA-002": "#8E2727",
    "FMEA-003": "#8A5606",
    "FMEA-004": "#4C7A8A",
    "": "#6B7D82",  # Type C episodes carry no top rule
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


def plot_episode_outcomes(payload: dict[str, Any], out: Path) -> None:
    """Outcome mix and per-turbine concentration in one figure.

    Left: episodes by outcome type, Type B split by its leading rule so the
    differentiation claim is inspectable (v1 could not produce this split —
    LIM-030). Right: the same counts per turbine — the LIM-038 evidence that
    Type A concentrates on Kelmarsh 4 and is absent on Kelmarsh 1.
    """
    summary = payload["summary"]
    by_type = summary["episodes_by_type"]
    by_rule = payload["aggregates"]["episodes_by_top_rule"]
    by_type_turbine = payload["aggregates"]["episodes_by_type_and_turbine"]
    coverage = summary["coverage"]

    fig, (ax_mix, ax_turbine) = plt.subplots(
        1, 2, figsize=(11.0, 4.2), gridspec_kw={"width_ratios": [1.0, 1.4]}
    )

    # Left panel: A (single rule), B stacked by leading rule, C.
    order = ["A_positive_candidate", "B_ambiguous_candidates", "C_no_candidate"]
    y = np.arange(len(order))[::-1]
    b_rules = {k: v for k, v in by_rule.items() if k and k != "FMEA-002"}
    for i, kind in zip(y, order, strict=True):
        if kind == "B_ambiguous_candidates":
            left = 0
            for rule, n in sorted(b_rules.items()):
                ax_mix.barh(i, n, left=left, color=RULE_COLORS[rule], alpha=0.85, height=0.55)
                if n > 1000:  # narrower segments would clip their annotation
                    ax_mix.annotate(
                        f"{rule}-led\n{n:,}",
                        (left + n / 2, i),
                        ha="center",
                        va="center",
                        fontsize=7,
                        color="white",
                    )
                left += n
            total = left
        else:
            total = by_type[kind]
            ax_mix.barh(i, total, color=TYPE_COLORS[kind], alpha=0.85, height=0.55)
        ax_mix.annotate(
            f"{total:,}", (total, i), textcoords="offset points", xytext=(4, 0), fontsize=8
        )
    ax_mix.legend(
        handles=[
            plt.Rectangle((0, 0), 1, 1, color=RULE_COLORS[r], alpha=0.85, label=f"{r}-led")
            for r in sorted(b_rules)
        ],
        fontsize=7,
        frameon=False,
        loc="upper right",
        title="Type B split",
        title_fontsize=7,
    )
    ax_mix.set_yticks(y)
    ax_mix.set_yticklabels(
        [
            f"{TYPE_LABELS[k].split(' — ')[0]}\n{TYPE_LABELS[k].split(' — ')[1]}"
            + ("\n(all FMEA-002-led)" if k == "A_positive_candidate" else "")
            for k in order
        ],
        fontsize=8,
    )
    _style(ax_mix, f"Episodes by outcome ({summary['n_episodes']:,} total)", "episodes", "")

    # Right panel: grouped per-turbine counts.
    turbines = sorted(coverage["per_turbine"])
    x = np.arange(len(turbines))
    width = 0.27
    for offset, kind in zip((-width, 0.0, width), order, strict=True):
        counts = [by_type_turbine.get(kind, {}).get(t, 0) for t in turbines]
        ax_turbine.bar(
            x + offset,
            counts,
            width=width,
            color=TYPE_COLORS[kind],
            alpha=0.85,
            label=TYPE_LABELS[kind].split(" — ")[0],
        )
    ax_turbine.set_xticks(x)
    ax_turbine.set_xticklabels([t.replace("Kelmarsh ", "K") for t in turbines], fontsize=8)
    ax_turbine.legend(fontsize=8, frameon=False)
    _style(
        ax_turbine,
        "Per turbine — Type A concentrates on Kelmarsh 4;\nKelmarsh 1 produces none (LIM-038)",
        "",
        "episodes",
    )

    withheld = coverage["n_withheld"]
    withheld_active = coverage["n_withheld_active"]
    fig.suptitle(
        "Ruleset v2 interpretation episodes — EXPLORATORY, representation level only "
        "(ADR-050; ordering evidence per episode).\n"
        f"R_OOD: {withheld:,} samples withheld as outside the NBM's fitted support, "
        f"{withheld_active:,} of them exceedances (ADR-049; eligibility is not a success "
        "rate).\nDetection value untested (ADR-035 c); 0 maintenance-confirmed faults — no "
        "output is a validated diagnosis.",
        fontsize=8,
    )
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.87))
    _save(fig, out)
    plt.close(fig)


def plot_event001_window(payload: dict[str, Any], out: Path) -> None:
    """Outcome shares inside the EVENT-001 window against the base rates.

    The load-bearing fact is the zero: no Type A episode overlaps the window,
    worded per ADR-050(e) as abstention from unsupported positive attribution.
    The FMEA-003 skew is descriptively coherent and is NOT confirmation
    (LIM-036: EVENT-001's documented primary indicators are not thermal).
    """
    summary = payload["summary"]
    event = payload["event_001"]
    order = ["A_positive_candidate", "B_ambiguous_candidates", "C_no_candidate"]
    n_total = summary["n_episodes"]
    n_event = event["episodes_overlapping_window"]
    base = [summary["episodes_by_type"][k] / n_total for k in order]
    window = [event["episodes_by_type"].get(k, 0) / n_event for k in order]

    fig, ax = plt.subplots(figsize=(7.8, 3.9))
    x = np.arange(len(order))
    width = 0.36
    ax.bar(
        x - width / 2,
        base,
        width=width,
        color="#6B7D82",
        alpha=0.85,
        label=f"all monitoring episodes (n = {n_total:,})",
    )
    ax.bar(
        x + width / 2,
        window,
        width=width,
        color="#0B6672",
        alpha=0.85,
        label=f"EVENT-001 window (n = {n_event:,})",
    )
    for xi, share in zip(x + width / 2, window, strict=True):
        if share == 0.0:
            ax.annotate(
                "0 episodes",
                (xi, 0.0),
                textcoords="offset points",
                xytext=(0, 4),
                ha="center",
                fontsize=8,
                color="#0B6672",
            )
    ax.set_xticks(x)
    ax.set_xticklabels([TYPE_LABELS[k].split(" — ")[0] for k in order], fontsize=8)
    ax.set_ylim(0.0, max(*base, *window) * 1.25)
    ax.legend(fontsize=8, frameon=False)
    _style(ax, "Episode outcome shares: EVENT-001 window vs base rate", "", "share of episodes")
    fig.suptitle(
        "Zero positive-candidate episodes in the window: the system abstained from "
        "unsupported positive attribution\n(ADR-050 e). Overlap is not confirmation — "
        "EVENT-001's documented primary indicators are not thermal (LIM-036).",
        fontsize=8,
    )
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.88))
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
    directory = args.artifacts / experiment
    source = directory / "evaluation" / "ruleset_v2_evaluation.json"
    if not source.is_file():
        raise SystemExit(f"Missing {source}; run run_ruleset_v2_evaluation.py first")
    payload = json.loads(source.read_text(encoding="utf-8"))

    plots = directory / "plots"
    plots.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    plot_episode_outcomes(payload, plots / "rq3_episode_outcomes.png")
    written.append("rq3_episode_outcomes.png")
    plot_event001_window(payload, plots / "rq3_event001_window.png")
    written.append("rq3_event001_window.png")

    manifest = {
        "experiment_id": experiment,
        "inputs": {"ruleset_v2_evaluation": source.name},
        "status": payload["status"],
        "standing_limits": payload["standing_limits"],
        "v1_outcome_reported_first": payload["v1_outcome_reported_first"],
        "formats": list(SAVE_FORMATS),
        "figures": sorted(written),
    }
    (plots / "interpretation_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"Wrote {len(written)} figures to {plots}")
    print(json.dumps({k: manifest[k] for k in ("experiment_id", "figures")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
