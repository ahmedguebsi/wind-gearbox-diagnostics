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

## Candidate dataset (pending Phase 0.5 due diligence)

| Field | Value |
|-------|-------|
| Name | Kelmarsh wind farm SCADA + status logs (6 turbines) |
| Years sighted | 2016 (SCADA + status logs), 2020 (SCADA) |
| Sampling | 10-minute SCADA; event-timestamped status logs |
| Source / supplier | **TO BE CONFIRMED** (files currently in user's local Downloads; formal origin, DOI/URL, and version required) |
| Licence / redistribution | **TO BE CONFIRMED** before any data is committed or published |
| Source timezone | **TO BE CONFIRMED** — ingestion stops and asks; never guessed (PROJECT.md §8) |

The formal census (turbines, durations, channels, event counts, timezone/DST
behaviour, quality issues, licensing) belongs in
`docs/DATASET_DUE_DILIGENCE.md` and gates all modelling work (PROJECT.md §7.5).

## Per-file provenance record (captured at ingestion, M-08)

```text
SHA-256 hash, original filename and path, file size,
ingestion timestamp (UTC), declared source timezone,
schema version + mapping config used, supplier note
```
