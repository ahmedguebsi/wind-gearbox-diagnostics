# data/ — Dataset Provenance and Access Conditions

This directory documents dataset origin, licensing, and access conditions so
the thesis data-availability statement is honest (PROJECT.md §10). Raw files
are **never modified**; every file is SHA-256 hashed at ingestion (M-08) and
`data/raw/` contents are excluded from git.

## Layout

```text
data/
├── raw/        # original files, byte-immutable, hashed at ingestion; not in git
└── processed/  # Parquet outputs, regenerable, provenance-chained; not in git
```

## Dataset (Phase 0.5 due diligence complete — docs/DATASET_DUE_DILIGENCE.md)

| Field | Value |
|-------|-------|
| Name | Kelmarsh wind farm SCADA + status logs (6 × Senvion MM92) |
| Holdings censused | Year folders 2016–2021 (2021 is a half year); modelling span 2016-05-03 to 2021-06-30 (ADR-009) |
| Sampling | 10-minute SCADA; event-timestamped status logs (to the second) |
| Source / supplier | Cubico Sustainable Investments Ltd, published on Zenodo — DOI [10.5281/zenodo.5841833](https://doi.org/10.5281/zenodo.5841833) (all-versions DOI, resolves to latest; author-confirmed 2026-08-12) |
| Licence / redistribution | **CC-BY-4.0** (author-confirmed 2026-08-12) |
| Source timezone | UTC, declared in every file's Greenbyte header (census `KELMARSH_2020_CENSUS.json → timezone`; declared, not assumed) |

The formal census (turbines, durations, channels, event counts, timezone/DST
behaviour, quality issues, licensing) is `docs/DATASET_DUE_DILIGENCE.md`;
the Phase 0.5 gate was approved 2026-08-12 (ADR-015).

## Per-file provenance record (captured at ingestion, M-08)

```text
SHA-256 hash, original filename and path, file size,
ingestion timestamp (UTC), declared source timezone,
schema version + mapping config used, supplier note
```
