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

## Status

Modules **M-01…M-31 complete**: core, data layer, models (XGBoost THESIS +
linear BASELINE per ADR-002), residuals, detection, FMEA, evaluation, and
experiment management including `reproduce`. Not started: M-32 (FastAPI),
M-33 (dashboard), M-34 (exports) — out of scope for the research instrument.

Phase 0.5 dataset due-diligence gate **APPROVED 2026-08-12** (ADR-015); see
[`docs/DATASET_DUE_DILIGENCE.md`](docs/DATASET_DUE_DILIGENCE.md). Decisions
ADR-001…ADR-027 recorded; queue Groups A and B closed, Group C (D-08…D-14)
open. Four experiments have been run; artifacts are excluded from git by
design (PROJECT.md §15).

Current methodological review and the frozen experiment protocol:
[`docs/METHODOLOGY_REVIEW.md`](docs/METHODOLOGY_REVIEW.md) ·
[`docs/EXPERIMENT_PROTOCOL.md`](docs/EXPERIMENT_PROTOCOL.md).
