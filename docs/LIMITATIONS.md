# LIMITATIONS.md — Living Register of Threats to Validity

Every known threat to validity discovered during development is recorded here:
data quality issues, small event counts, seasonal coverage shortfalls, sensor
artefacts, evaluation caveats. This file feeds the thesis limitations and
discussion chapters directly (PROJECT.md §1).

Automated producers append entries here as they come online: validation
step-change findings (M-10), seasonal coverage warnings (M-13), EWMA
in-control inflation findings (M-20), small-n constraints and
conclusion-flipping sensitivity parameters (M-27/M-28).

Entry template:

```text
## LIM-NNN — <short title>
Date discovered:    YYYY-MM-DD
Description:        <what the threat is and how it was found>
Affected RQ(s):     RQ1 | RQ2 | RQ3
Mitigation status:  OPEN | MITIGATED (<how>) | ACCEPTED (<why>)
Source:             <module/report/manual>
```

---

Entries LIM-001…LIM-004 record facts observed in the Phase 0.5 census of the
Kelmarsh 2020 export (`docs/evidence/KELMARSH_2020_CENSUS.json`). They state
what the data contains; the decisions they bear on remain the author's
(docs/CHAPTER3_DECISION_QUEUE.md).

## LIM-001 — No channel named as a gearbox bearing temperature

Date discovered:    2026-08-11
Description:        In the Kelmarsh 2020 SCADA export (299 columns, all six
                    turbines) **no column name contains both "gear" and
                    "bearing"**. Bearing-temperature channels present:
                    "Front bearing temperature (°C)", "Rear bearing
                    temperature (°C)", "Generator bearing front/rear
                    temperature (°C)", "Rotor bearing temp (°C)". Gear-named
                    thermal channels present: "Gear oil temperature (°C)" and
                    "Gear oil inlet temperature (°C)".
                    PROJECT.md §8 names *gearbox bearing temperature* as a
                    required thermal target, and the M-06 canonical schema
                    enforces `gearbox_bearing_temperature` as a required
                    TARGET variable. The census does not designate any column
                    as that target — designation is a mapping decision
                    (M-07) reserved to the author.
Affected RQ(s):     RQ1, RQ2 (coordinated multi-target analysis presumes two
                    thermal targets), RQ3 (Table 2.3 patterns 2 and 3 rely on
                    a bearing residual).
Mitigation status:  OPEN — author designation required. Until then the M-06
                    schema is left unchanged (changing it to match the data
                    would resolve a spec/data conflict silently).

## LIM-002 — No maintenance free text in the status export

Date discovered:    2026-08-11
Description:        Across all 57,515 status rows from the six 2020 status
                    files, the `Comment` column is non-empty in **0 rows**.
                    A `Service comment` column **does not exist** in this
                    export; the eighth field is `Service contract category`
                    (a categorical, blank in 43,093 of 57,515 rows). The 2016
                    export was previously reported to have the same
                    100%-missing commentary. Consequently the dataset carries
                    no free-text maintenance or repair evidence.
Affected RQ(s):     RQ2, RQ3 (mechanism-level ground truth); bears directly
                    on queue item D-04.
Mitigation status:  OPEN — reinforces the Chapter 1 §1.5 scope boundary that
                    mechanism-level interpretations can be assessed for
                    plausibility only.

## LIM-003 — Sparse event duration and gearbox-code coverage in 2020

Date discovered:    2026-08-11
Description:        (a) Only 8,094 of 57,515 status rows (14.1%) carry a
                    populated `Timestamp end` and `Duration`; the remaining
                    49,421 hold the literal "-", so most rows have no
                    measurable duration. (b) Of the gearbox-related codes
                    reported for 2016, the following are **absent** from the
                    2020 export: 1510 (low gearbox oil pressure), 1710, 1800,
                    1620, 1825, 1920, 1922, 75, 1560, 1565. Present in 2020:
                    1552 "Gearbox warm-up stage" (21 rows, 6 turbines), 1555
                    "Gear heating enabled" (84 rows, 5 turbines), 1700 "High
                    temp. gear bearing 1" (**1 row**, Kelmarsh 6,
                    2020-12-24 05:14:40, 38m11s, Status=Warning), 5760
                    "Hydraulic oil flushing operation" (47 rows, 6 turbines).
Affected RQ(s):     RQ2, RQ3; bears on D-04 (ground truth) and D-05 (whether
                    the ≥2-event quantitative branch is reachable).
Mitigation status:  OPEN — event definition and counting are author
                    decisions; no inference drawn here.

## LIM-004 — Twelve months of coverage only

Date discovered:    2026-08-11
Description:        The holding is calendar year 2020 only: 52,704 rows per
                    turbine at a perfectly regular 10-minute interval,
                    2020-01-01 00:00 to 2020-12-31 23:50 UTC, zero duplicate
                    timestamps and zero gaps on all six turbines. Because a
                    chronological split allocates only part of this to
                    training, the training window will span **fewer than 12
                    months**, which triggers the PROJECT.md §14 seasonal
                    coverage WARNING. Years 2016–2022 are available from the
                    same Zenodo record.
Affected RQ(s):     RQ1 (seasonal covariate shift inflating test residuals —
                    risk R2), RQ2 (false-alarm behaviour across seasons).
Mitigation status:  OPEN — acquiring further years is an author decision,
                    pending before splitting (queue item D-07).
