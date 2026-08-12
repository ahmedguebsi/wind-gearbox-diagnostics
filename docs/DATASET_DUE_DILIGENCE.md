# DATASET_DUE_DILIGENCE.md — Phase 0.5 Dataset Census (Kelmarsh)

> **Provenance of this document.** Assembled RETROACTIVELY on 2026-08-12 from
> the committed Phase 0.5 census evidence. The census itself, the decisions,
> and the gate approval all preceded this document; the document adds no new
> facts. Every figure below is traceable to a committed artifact:
>
> - `docs/evidence/KELMARSH_2020_CENSUS.json` — committed in `c40d053`
> - `docs/evidence/KELMARSH_STATUS_VOCABULARY_2016_2021.json` and
>   `…csv.gz` — committed in `47b3ade`
> - `docs/evidence/EVIDENCE_D04_AND_TARGETS.json` — committed in `3e14f7e`
> - `docs/LIMITATIONS.md` LIM-001…LIM-008 and `docs/DECISIONS.md`
>   ADR-009…ADR-015 — committed in the same sequence, gate approval in
>   `2e2ce70`
>
> Nothing here is written from memory or inferred beyond those artifacts.
> Where the evidence does not establish a §7.5 field, the field says so.

Dataset: **Kelmarsh wind farm SCADA + status exports** (Greenbyte-format
CSVs, year-folders `Kelmarsh_SCADA_2016_3082` … `Kelmarsh_SCADA_2021_3087`,
censused read-only from the author's local copies; every inventoried file is
SHA-256 hashed in the evidence JSONs, and each census run verified its
inputs byte-unchanged before and after).

---

## 1. Turbine count and identifiers

Six turbines: **Kelmarsh 1 … Kelmarsh 6**, declared turbine type **Senvion
MM92** (per-file `turbine_declared` / `turbine_type_declared` header fields,
`KELMARSH_2020_CENSUS.json → scada_census`). File naming carries stable
per-turbine suffixes 228–233.

## 2. Total duration and date range per turbine

SCADA spans are identical for all six turbines within each year-folder
(`KELMARSH_STATUS_VOCABULARY_2016_2021.json → scada_coverage_per_year`):

| Year folder | First timestamp | Last timestamp | Rows/turbine |
|---|---|---|---|
| 2016 | 2016-01-03 00:00 | 2016-12-31 23:50 | 52,416 |
| 2017 | 2017-01-01 00:00 | 2017-12-31 23:50 | 52,560 |
| 2018 | 2018-01-01 00:00 | 2018-12-31 23:50 | 52,560 |
| 2019 | 2019-01-01 00:00 | 2019-12-31 23:50 | 52,560 |
| 2020 | 2020-01-01 00:00 | 2020-12-31 23:50 | 52,704 |
| 2021 | 2021-01-01 00:00 | 2021-06-30 23:50 | 26,064 (half year) |

Holdings therefore span **2016-01-03 to 2021-06-30** (LIM-007). The
**modelling span is 2016-05-03 to 2021-06-30** (ADR-009): the gear-oil
thermal channels are 100% null before 2016-05-03 09:40 on every turbine
(LIM-005), a stated data constraint, not a selection.

## 3. Sampling interval(s)

10-minute SCADA. In the 2020 export the interval is perfectly regular:
modal interval `00:10:00` for 52,703 of 52,703 deltas, zero duplicate
timestamps, zero unparseable timestamps, zero gaps above the modal interval,
on every turbine (`KELMARSH_2020_CENSUS.json → scada_census → timestamps`).
Status records are event-timestamped (to the second), not sampled.

## 4. Available thermal channels

299 columns per SCADA file. Thermal channels relevant to the gearbox
question, as named in the export (LIM-001; census `per_column`):

- `Gear oil temperature (°C)` and `Gear oil inlet temperature (°C)` — the
  only gear-named thermal channels.
- `Front bearing temperature (°C)`, `Rear bearing temperature (°C)` — main
  shaft/gearbox-end bearings; **no column name contains both "gear" and
  "bearing"** (LIM-001).
- `Generator bearing front/rear temperature (°C)`, `Rotor bearing temp (°C)`.

Per-year thermal availability (fraction of samples with every gear-named
thermal channel non-null, Kelmarsh 1; `scada_coverage_per_year`):

| Year | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 |
|---|---|---|---|---|---|---|
| Covered fraction | 0.655 | 0.988 | 0.966 | 0.954 | 0.986 | 0.914 |

The 2016 deficit is the pre-May-2016 emptiness (LIM-005): both gear-oil
channels are jointly null from file start until 2016-05-03 09:40 on every
turbine (monthly non-null fractions 0.000 for Jan–Apr 2016, 0.892 in May,
0.95–0.99 thereafter).

**Target designation (ADR-012, closed 2026-08-12):**
`gearbox_oil_temperature` ← `Gear oil temperature (°C)`;
`gearbox_bearing_temperature` ← `Rear bearing temperature (°C)`. The
deciding evidence is the power-bin correlation structure
(`EVIDENCE_D04_AND_TARGETS.json → target_designation_evidence → pooled →
by_power_bin`, n = 1,733,184 pooled rows):

| Power bin (kW) | Front bearing r | Rear bearing r |
|---|---|---|
| ≤ 0 | 0.989 | 0.978 |
| 0–50 | 0.948 | 0.943 |
| 50–250 | 0.897 | 0.951 |
| 250–500 | 0.745 | 0.885 |
| 500–1000 | 0.451 | 0.895 |
| 1000–1500 | 0.146 | 0.922 |
| > 1500 | 0.057 | 0.918 |

Rear bearing holds 0.88–0.98 correlation with gear oil in every bin; front
bearing collapses from 0.99 at idle to 0.06 above 1500 kW. `Gear oil inlet
temperature (°C)` is EXCLUDED as a target: it correlates −0.416 with power
and its per-bin mean falls monotonically from 53.4 °C (50–250 kW) to
39.3 °C (>1500 kW) while sump oil stays flat (51–57 °C) — cooling-circuit
response, not gearbox thermal state (ADR-012).

## 5. Available upstream predictor channels

All thesis-identified predictors (PROJECT.md §8) are present in the export,
with 10-minute means plus Max/Min/StdDev aggregates (census `per_column`;
exact names):

- `Wind speed (m/s)` (2020 null fraction 0.0089 on Kelmarsh 1)
- `Power (kW)`
- `Rotor speed (RPM)`
- `Generator RPM (RPM)`
- `Blade angle (pitch position) A/B/C (°)`
- `Ambient temperature (converter) (°C)`
- `Nacelle ambient temperature (°C)`, `Nacelle temperature (°C)`

The full 299-column inventory with per-column null fractions, ranges, and
constancy flags is in `KELMARSH_2020_CENSUS.json → scada_census`.

## 6. Alarm/status record availability and format

Per-turbine status CSVs per year folder (36 files, 2016–2021), Greenbyte
format. Totals: **282,235 rows, 188 distinct codes** across 2016–2021
(`KELMARSH_STATUS_VOCABULARY_2016_2021.json`); 57,515 rows / 89 codes in
2020 alone (`KELMARSH_2020_CENSUS.json → status_inventory`).

- `Status` takes exactly four values (2020 counts): Informational 56,079;
  Stop 730; Warning 570; Communication 136. **There is no Error and no
  Fault tier** (M-24 note).
- Vendor taxonomies: `IEC category` (8 values incl. blank; blank rows carry
  the largest total duration, 6,856 h) and `Service contract category`
  (22 values across 2016–2021, blank in 43,093 of 57,515 rows in 2020).
- Only 8,094 of 57,515 rows (14.1%) carry a populated `Timestamp end` and
  `Duration`; the remaining 49,421 hold the literal `-` (LIM-003).
- Status year-folders overlap at boundaries (2017 folder starts 2016-12-17;
  2021 folder starts 2020-06-07): 215 duplicate rows across 213 keys
  (LIM-006); ingestion deduplicates on (turbine, timestamp, code) with
  content-hash verification (M-09).

## 7. Maintenance record availability and format

**None.** The `Comment` free-text column is non-empty in **0 of 57,515**
rows (2020; the 2016 export was previously verified identical), and no
`Service comment` column exists in these exports (LIM-002). The dataset
carries no free-text maintenance or repair evidence, so mechanism-level
ground truth is unavailable (ADR-013 tier ruling).

## 8. COUNT OF LABELLED GEARBOX EVENTS (the binding constraint)

**One (1).** EVENT-001 (ADR-013): code **1860 "Oil filter gear choked"**,
Kelmarsh 1, three occurrences recorded verbatim in
`EVIDENCE_D04_AND_TARGETS.json → d04_evidence → occurrences`:

| Occurrence | Start | End | Duration |
|---|---|---|---|
| 1 | 2019-02-24 16:46:28 | 2019-04-04 12:35:45 | 931.8 h |
| 2 | 2019-04-09 10:09:03 | 2019-05-21 10:06:24 | 1,008.0 h |
| 3 | 2019-05-28 20:55:45 | 2019-05-30 07:34:04 | 34.6 h |

Counted as ONE event, not three: gaps between occurrences are 4.9 and 7.45
days across a 95-day span with the alarm active ~82 days — a single
continuous degradation episode with brief clearances (ADR-013). Code 1860
is a filter-restriction **Warning**, not maintenance-verified damage; the
ground-truth tier is alarm-level only.

All other gearbox-indexed candidates are excluded for zero preceding
thermal coverage: 780 Stop/Warning rows across 2016–2021 have 0.0 h of
continuous covered SCADA before them, 731 of them in 2016, including every
January–February 2016 gearbox-indexed occurrence (LIM-005; per-occurrence
preceding-coverage hours in `KELMARSH_STATUS_VOCABULARY_2016_2021.csv.gz`).

Within EVENT-001, occurrence 3 coincides with abnormal operation: 27.1%
null SCADA rows and mean power 375 kW in its 60-day window, against 743 kW
and 804 kW for occurrences 1–2 (`d04_evidence →
preceding_channel_statistics`; LIM-008).

## 9. Timezone and DST behaviour of timestamps

Every 2020 SCADA and status file declares **UTC** in its Greenbyte header
(comment line 5; census `timezone`: single distinct declared value across
all 12 files — "declared, not assumed"). DST fold-backs and spring gaps are
therefore not applicable at source; ingestion (M-09) nevertheless carries
mandatory `source_timezone` declaration and DST anomaly detection for any
future non-UTC source.

## 10. Known data quality issues

The living register is `docs/LIMITATIONS.md`; census-derived entries:

- LIM-001 — no channel named as a gearbox bearing temperature (resolved by
  designation, ADR-012).
- LIM-002 — no maintenance free text anywhere in the exports.
- LIM-003 — 85.9% of status rows carry no duration; sparse gearbox-code
  coverage in 2020 (e.g. code 1700 appears once).
- LIM-005 — gear-oil thermal channels entirely empty before 2016-05-03;
  780 status rows with zero preceding thermal coverage.
- LIM-006 — status year-folder boundary overlap (215 duplicate rows).
- LIM-007 — uneven holdings; 2021 is a half year.
- LIM-008 — EVENT-001 occurrence 3 coincides with abnormal operation.

## 11. Licensing / redistribution conditions

**Kelmarsh wind farm data, Cubico Sustainable Investments Ltd, published on
Zenodo: DOI 10.5281/zenodo.5841833 (all-versions DOI, resolves to the
latest version), licence CC-BY-4.0.** Confirmed by the author 2026-08-12 —
this is the one field in this document that comes from author confirmation
rather than the census artifacts, because the censused local copies carried
no licence file (the census read folders under the author's Downloads).
CC-BY-4.0 permits use and redistribution with attribution; the thesis
data-availability statement can cite the DOI directly. Raw data is still
never committed to this repository (provenance hashes only, PROJECT.md
§10).

---

## Gate decision (recorded in docs/DECISIONS.md)

The §7.5 decision rule is: **≥ 2 independent labelled gearbox events →
quantitative event-based evaluation; < 2 → descriptive case-study design.**

- **D-04 closed (ADR-013, 2026-08-12):** ground truth is status-code-derived,
  qualified by duration and preceding-thermal-coverage criteria; tier is
  alarm-level ONLY (no maintenance confirmation exists, LIM-002); the
  labelled event set is exactly {EVENT-001}.
- **D-05 closed (ADR-014, 2026-08-12):** one event < 2, so the pre-committed
  rule selects the **DESCRIPTIVE CASE-STUDY** branch mechanically.
  `inferential_allowed = false` (M-27): no inferential detection-rate or
  lead-time population claims anywhere in the evidence chain. The
  matched-FPR operating curves on healthy data (M-23) remain fully
  quantitative and are the primary RQ2 evidence; EVENT-001 is the
  qualitative case study, focused on the onset of occurrence 1 with
  occurrences 2–3 reported as continuation (LIM-008).
- **Gate APPROVED (ADR-015, 2026-08-12):** census complete, evidence on
  file, D-04/D-05 closed with recorded justifications, and the evaluation
  design pre-committed before any model was fitted — which is what this
  gate exists to guarantee. Modelling data span per ADR-009.

The reasoning for the descriptive branch is not a judgment that the data is
poor; it is the pre-committed rule doing its job: with a single alarm-level
event, detection-rate and lead-time statistics would have no population to
generalize to, so the thesis claims are scoped to what one well-documented
episode plus fully quantitative healthy-data operating curves can support.
