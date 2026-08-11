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

Latest run: [`docs/evidence/KELMARSH_2020_CENSUS.json`](docs/evidence/KELMARSH_2020_CENSUS.json).

## Experiment reproduction

`python -m app.experiments reproduce EXP-YYYYMMDD-NNN` — arrives with M-31;
CI will then require EXACT MATCH on a fixture experiment.

## Repository layout

```text
backend/app/core/   # Layer 0: errors, UTC time, config, logging, versioning
backend/tests/      # test suite (mirrors module obligations in IMPLEMENTATION_PLAN.md)
configs/            # example experiment configurations
data/               # raw/processed data areas (contents not in git) + provenance README
docs/               # living research documents
scripts/            # one-off utilities (never scientific evidence)
```

## Status

Milestone 1 (foundation) complete: core modules M-01…M-05, quality gates,
CI workflow, seed documents. Next: Phase 0.5 dataset due-diligence gate
(blocking) before any modelling-adjacent work.
