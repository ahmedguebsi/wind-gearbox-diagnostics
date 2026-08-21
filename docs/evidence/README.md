# docs/evidence — Phase 0.5 census artefacts

Machine-generated, facts-only outputs. No cleaning, no judgment, no inferred
labels, no designations. Every producing run is read-only over its inputs and
records a before/after SHA-256 comparison of every inventoried file.

| Artefact | Produced by | Contents |
|----------|-------------|----------|
| `KELMARSH_2020_CENSUS.json` | `scripts/dataset_census.py` | Single-folder census of the 2020 export: file inventory + hashes, header provenance, full status inventory, per-column SCADA statistics for all 299 columns × 6 turbines |
| `KELMARSH_STATUS_VOCABULARY_2016_2021.json` | `scripts/status_vocabulary.py` | Complete status vocabulary across 2016–2021: every distinct code, both vendor taxonomies, long-event listing, per-turbine-year matrix, year-presence patterns, preceding-SCADA-coverage statistics |
| `KELMARSH_STATUS_VOCABULARY_2016_2021.csv.gz` | `scripts/status_vocabulary.py` | Per-occurrence detail for **every** status row (282,235 rows, untruncated), including each row's preceding continuous covered SCADA hours |
| `KELMARSH_EDA_2016_2021.json` | `scripts/run_eda.py` | Nine-stage exploratory analysis of all 36 turbine-data files (PROJECT.md §35 PHASE 10): inventory/provenance, per-channel statistics, temporal coverage, joint missingness, operating regime, target relationships by power bin, cross-turbine fleet coherence, attrition preview, and autocorrelation structure |
| `figures/` | `scripts/make_eda_plots.py` | Rendered dataset figures for the thesis data chapter — drawn from the JSONs above plus the cited experiment's `split.json`/`cleaning_audit.json`/`healthy_state_report.json`, never recomputed from the raw CSVs; `eda_figures_manifest.json` records inputs and the source banner |

Decompress the CSV with any gzip tool, e.g.:

```powershell
$in = [IO.File]::OpenRead("KELMARSH_STATUS_VOCABULARY_2016_2021.csv.gz")
$out = [IO.File]::Create("KELMARSH_STATUS_VOCABULARY_2016_2021.csv")
$gz = New-Object IO.Compression.GzipStream($in, [IO.Compression.CompressionMode]::Decompress)
$gz.CopyTo($out); $gz.Close(); $out.Close(); $in.Close()
```

The gzip step is storage only — the CSV is complete and untruncated.

## Reading notes

- **Selection applies no code or keyword filter.** The `gearbox_term_index`
  section of the vocabulary JSON is an index into the complete inventory, not
  a filter on it; codes absent from that index are not excluded from anything.
- **"Thermal-candidate channel" is a name-based grouping**, not a designation.
  Which column IS a canonical thermal target is a mapping decision (M-07)
  reserved to the author.
- Findings drawn from these artefacts are recorded factually in
  `../LIMITATIONS.md` (LIM-001…LIM-007). Decisions they bear on remain open in
  `../CHAPTER3_DECISION_QUEUE.md`.
