# wind-gearbox-diagnostics

SCADA-based wind turbine gearbox condition monitoring using multi-target
XGBoost Normal Behaviour Modelling, coordinated thermal residual analysis
(EWMA-primary), and an FMEA-informed interpretation layer.

This is an MSc thesis research instrument, not a product. Priorities, in
order: scientific validity → reproducibility → data correctness → experiment
management → evaluation → visualization → UI polish.

The governing specification lives outside this repository in `PROJECT.md`
v2.0 (10 LOCKED methodology constraints), with `ARCHITECTURE.md` and
`IMPLEMENTATION_PLAN.md` (modules M-01…M-36). In-repo living documents:

- [`docs/THESIS_REQUIREMENTS.md`](docs/THESIS_REQUIREMENTS.md) — requirements + Methodology Alignment Table
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — ADR log (open methodological decisions)
- [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) — living register of threats to validity
- [`data/README.md`](data/README.md) — dataset provenance and access conditions

## Reproduction commands (exact)

Requires [uv](https://docs.astral.sh/uv/) and git. uv installs the pinned
Python 3.12 automatically.

```bash
git clone <repo-url>
cd wind-gearbox-diagnostics/backend
uv sync
uv run pytest
```

A fresh machine must reach a green test suite with exactly those commands
(PROJECT.md §7).

## Quality gates (all must pass; CI enforces on every push/PR)

```bash
cd backend
uv run ruff check .          # lint
uv run ruff format --check . # formatting
uv run mypy                  # types (strict)
uv run lint-imports          # dependency-direction contract (ARCHITECTURE.md §3)
uv run pytest                # tests + coverage
```

Pre-commit hooks run the same gates locally: `uv run --project backend pre-commit install`
(run from the repository root).

## Running the pipeline end to end

The steps above give a green test suite on synthetic fixtures. Producing a real
experiment needs the dataset.

### 1. Obtain the data

The holdings are ~4.5 GB and excluded from git, so a checkout plus the Zenodo
download reproduces a run without editing anything. Download the Kelmarsh
record — DOI [10.5281/zenodo.5841833](https://doi.org/10.5281/zenodo.5841833),
CC-BY-4.0 — and unpack the year folders into `dataset/` at the repository root:

```text
dataset/
├── Kelmarsh_SCADA_2016_3082/
├── Kelmarsh_SCADA_2017_3083/
├── ...
└── Kelmarsh_SCADA_2021_3087/
```

That is the default `--downloads` location. Pass `--downloads <path>` for a copy
held elsewhere. Provenance, licensing and access conditions:
[`data/README.md`](data/README.md).

### 2. Run the headline experiment

```bash
cd backend
uv run python ../scripts/run_kelmarsh_experiment.py --approved-by "Name 2026-08-19"
```

Takes roughly 15–20 minutes. Two refusals are deliberate and will stop the run
before any work happens:

- **No `--approved-by`** → refuses. The predictor set, split dates and
  alarm-window policy are author decisions, and a run that does not name its
  approver cannot be cited (PROJECT.md §34).
- **Uncommitted changes to tracked files** → refuses (ADR-044). The commit
  recorded in the metadata would not describe the code that ran. Untracked files
  do not block. `--allow-dirty` overrides for exploratory runs, which are then
  marked as such in the stamp.

### 3. Read the results

Everything lands in `artifacts/EXP-YYYYMMDD-NNN/`. Start with these four:

| File | What it holds |
|------|---------------|
| `metrics.json` | RMSE / MAE / R² / bias per model × target × period; the RQ1 slice and its exclusions; the in-control block; cross-target residual correlations |
| `evaluation/first_run_summary.json` | Panel-bootstrap CIs with reliability flags, per-turbine Diebold–Mariano, the tuning trials, the EVENT-001 block |
| `metadata.json` | Seeds, the multiple-comparison register, the git/library version stamp, cleaning operations, split |
| `evaluation/regime_split.json` | Every error and detection figure split by operating regime (ADR-047) — **read this before quoting any false-alarm number** |

Also written: `model/`, `predictions/`, `residuals/` (parquet), `plots/` (12
figures), `run.log`, and the remaining `evaluation/` reports — cleaning audit,
healthy-state report, split, normalizer stats, in-control report, condition
diagnostics, and the EVENT-001 operator rendering.

### 4. Analyses over a completed run

All read stored artifacts only — no refit, seconds rather than minutes:

```bash
cd backend
uv run python ../scripts/run_regime_split.py      --experiment EXP-YYYYMMDD-NNN
uv run python ../scripts/make_diagnostic_plots.py --experiment EXP-YYYYMMDD-NNN
uv run python ../scripts/run_matched_fpr_sweep.py --experiment EXP-YYYYMMDD-NNN
```

`run_regime_split.py` is the LIM-034 mitigation (ADR-047); it verifies its own
join against the residual frame and aborts rather than report on a bad
alignment. `run_matched_fpr_sweep.py` rebuilds the RQ1 slice membership from the
pipeline's own code and aborts on any row-count disagreement, so it needs the
dataset present.

Further drivers: `run_eda.py` (read-only exploratory census),
`run_nacelle_ablation.py` (ADR-027 predictor ablation),
`diagnose_residual_dependence.py` (the ADR-034 serial-correlation diagnosis),
`run_event001_context_series.py` and `run_event001_selected_points.py`
(EVENT-001 case-study series).

## Phase 0.5 dataset census (read-only, facts only)

```bash
uv run --project backend python scripts/dataset_census.py \
  --folder <export folder> --output <path outside that folder>/census.json
```

Discovers and classifies every file in the folder (source / excluded-derived /
unclassified), hashes them all, then censuses only the source CSVs. Facts
only: no cleaning, no judgment, no inferred labels. Keyword hits are emitted
as candidates for author review, never as designations, and anything needing
an author definition reads `UNKNOWN — requires confirmation`. Inputs are
hashed before and after the run and the equality recorded, so read-only
behaviour is evidenced rather than asserted.

### Complete multi-year status vocabulary

```bash
uv run --project backend python scripts/status_vocabulary.py \
  --folder <year folder> --folder <year folder> ... \
  --output <path outside those folders>/status_vocabulary
```

Inventories the entire status vocabulary across all supplied year folders.
**Selection applies no code filter and no keyword filter** — every distinct
code that appears anywhere is reported, because a gearbox failure may be
logged in wording containing no gearbox term. A keyword index over the
finished inventory is provided as a labelled convenience, never as a filter.
Also reports, per occurrence, how much continuous preceding SCADA data exists
on the affected turbine with the thermal-candidate channels non-null
(continuity spans year boundaries). Writes a JSON inventory plus an
untruncated per-occurrence CSV.

Latest runs are in [`docs/evidence/`](docs/evidence/README.md).

## Experiment reproduction

```bash
cd backend
uv run python -m app.experiments reproduce EXP-YYYYMMDD-NNN --root ../artifacts
```

Re-runs the experiment from its stored resolved config and inputs, then diffs
regenerated metrics against `metrics.json` and requires exact frame equality
on predictions. A source-file hash mismatch is a hard stop, never a warning.
CI runs this on a fixture experiment on every push and requires EXACT MATCH.

Note: reproduction resolves source files by the absolute paths recorded in
provenance, so it currently requires the original data location.

## Repository layout

```text
backend/app/core/         # Layer 0: errors, UTC time, config, logging, versioning
backend/app/data/         # schema, mapping, ingestion+provenance, validation,
                          #   cleaning, healthy-state, splitting, causal guards
backend/app/models/       # fit/tune chokepoints, registry, XGBoost NBM, baseline, metrics
backend/app/residuals/    # residual engine, normalizers + Guard 4, EWMA detector
backend/app/detection/    # single-signal, comparators, coordinated states, matched-FPR
backend/app/fmea/         # YAML rule base + interpretation engine
backend/app/evaluation/   # events, event matching, bootstrap, DM test, comparison, sensitivity
backend/app/experiments/  # pipeline orchestration, artifact store, tracker, reproduce
backend/tests/            # test suite (mirrors module obligations in IMPLEMENTATION_PLAN.md)
configs/                  # example + Kelmarsh experiment configurations
data/                     # raw/processed data areas (contents not in git) + provenance README
docs/                     # living research documents
scripts/                  # experiment drivers and census utilities
```

Dependency direction is contractually enforced: `import-linter` declares the
layer stack in `backend/pyproject.toml` and CI fails on any upward import.

## Model diagnostics and figures (PROJECT.md §20, §31)

```bash
uv run python ../scripts/make_diagnostic_plots.py --experiment EXP-YYYYMMDD-NNN
```

Renders the §20 figures — actual vs predicted, residual distribution, residual
dispersion over time, and residual vs active power / wind speed / ambient
temperature — from **stored artifacts only**, so they regenerate in seconds
without re-running the pipeline and cannot disagree with the metrics beside
them. The runner separately persists the condition-sliced error tables to
`evaluation/condition_diagnostics.json` (ADR-045).

## Registered comparison arms

```bash
cd backend
uv run python ../scripts/run_robustness_suite.py --arms b3 seeds multi_output
uv run python ../scripts/run_matched_fpr_sweep.py       # RQ2 operating curves
uv run python ../scripts/run_sensitivity_suite.py       # M-27 provisional sweep
```

`b3` is the fleet-median-only detector with **no NBM at all** — the first-order
check on whether the model earns its place. `seeds` measures whether the
XGBoost margin exceeds seed noise. `multi_output` is the PROJECT.md §18
per-target ablation. Each is a declared arm reported alongside the headline,
never a replacement for it.

Both completed arms returned results that complicate the thesis's claims, and
both are reported first-class rather than in a caveat (ADR-046):

- **B3** — the no-model baseline is comparable to the NBM throughout and
  **better on the gearbox oil target** (residual σ 2.255 vs 2.578 °C). The
  NBM's contribution over a trivial baseline is not established by detection
  behaviour (LIM-031).
- **A8** — multi-output and one-model-per-target are indistinguishable
  (2.1647 vs 2.1611 bearing; 2.6904 vs 2.7155 oil), so the headline
  architectural choice buys no accuracy (LIM-032).
- **A9** — the XGBoost margin over the linear baseline **survives**: seed
  spread 0.0051 / 0.0115 °C against margins of 0.4007 / 0.2310 °C, i.e. 79×
  and 20×. The RQ1 accuracy claim is not a seed artefact.

Together they narrow the defensible contribution claim: XGBoost is genuinely
more accurate than the linear reference, that advantage does not come from the
multi-target architecture, and it does not translate into better detection than
a no-model fleet baseline.

## Status

Modules **M-01…M-31 complete**: core, data layer, models (XGBoost THESIS +
OLS and Elastic Net BASELINE per ADR-002/ADR-032), residuals, detection, FMEA,
evaluation, and experiment management including `reproduce`. Not started:
M-32 (FastAPI), M-33 (dashboard), M-34 (exports) — out of scope for the
research instrument.

Phase 0.5 dataset due-diligence gate **APPROVED 2026-08-12** (ADR-015); see
[`docs/DATASET_DUE_DILIGENCE.md`](docs/DATASET_DUE_DILIGENCE.md). Decisions
ADR-001…ADR-048 recorded; queue Groups A and B closed, **Group C (D-08…D-14)
open — four of them High viva risk (D-08, D-09, D-10, D-11), so the queue's
own stop condition is not yet met.** Artifacts are excluded from git by design
(PROJECT.md §15), which means a deleted experiment leaves only its prose:
regenerate and retain every cited run before submission.

Current methodological review and the frozen experiment protocol:
[`docs/METHODOLOGY_REVIEW.md`](docs/METHODOLOGY_REVIEW.md) ·
[`docs/EXPERIMENT_PROTOCOL.md`](docs/EXPERIMENT_PROTOCOL.md).

### Known open items an examiner will ask about

These are recorded here rather than only in the registers, because a reader
starts at the README:

- **RQ2 has a citable verdict, and it is negative.** The sweep was re-run on
  2026-08-19 under the ADR-028 row-time denominator (ADR-048): the ADR-016
  criterion is **predominantly NOT MET** — 6 met of 22 evaluable matched pairs
  across λ ∈ {0.1, 0.2, 0.3}. The denominator correction did not change the
  direction of the pre-registered conclusion. At the ADR-031 literature-anchored
  persistence boundaries (10/12/20 samples) the "met" verdicts vanish entirely
  at λ=0.2, so the negative **hardens** rather than flips.
- **RQ2 as posed is still not answered by that verdict.** At the measured
  cross-target residual correlation (r = 0.932–0.952) a 1-of-2 and a 2-of-2 rule
  fire on nearly the same rows, so the sweep measures the *channels*, not the
  coordination rule (ADR-035). LIM-034/ADR-047 add that the swept population is
  17.9% outside the model's fitted operating regime.
- **ADR-042 and ADR-034 are PROPOSED**, so the EWMA control limits remain
  empirically calibrated quantile knobs (ADR-026), not control limits.
- **LIM-026**: the single labelled event's matched detection is a cold-side
  excursion on a hot-side fault mode.
- **LIM-029**: monitoring-period residual dispersion grows ~2.5x from 2019 to
  2021 on every turbine — model ageing, not gearbox condition.
- **LIM-030**: at the measured cross-target residual correlation (r ≈ 0.95) the
  FMEA rule base cannot discriminate between mechanisms.
- **LIM-031**: a fleet-median-only detector with no model matches the NBM, and
  beats it on the oil target.
- **LIM-032**: the multi-target architecture contributes no measurable accuracy
  over per-target modelling.
- **LIM-034 / ADR-047**: 17.9% of the monitoring stream sits below the training
  power floor and carries 50.4% of the residual variance. Every error and
  detection figure is now reported split by operating regime. The RQ1 ordering
  holds in-regime; the unfiltered-slice Diebold-Mariano reversal is explained by
  the split, not by model quality.
- **LIM-035**: the Chesterman dual-criterion (Δ = RMSE unhealthy − RMSE healthy)
  reframing does NOT rescue the unfiltered-slice result. Computed correctly
  within regime the ordering reverses and the thesis model comes last. The
  pooled figure that appeared favourable was extrapolation, not sensitivity.
- **LIM-036**: EVENT-001 (code 1860, "Oil filter gear choked") belongs to the one
  failure mode Chapter 2's own Table 2.4 records as having "direct signals not
  thermal". The project models only thermal channels.
