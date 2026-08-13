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
Mitigation status:  MITIGATED (2026-08-12, ADR-012: the author designated
                    "Rear bearing temperature" as `gearbox_bearing_temperature`
                    on power-bin correlation evidence; schema 1.2.0 records
                    the designation, the M-07 mapping config assigns the raw
                    column).

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
Mitigation status:  ACCEPTED (2026-08-12, ADR-013: ground truth is
                    alarm-level ONLY for this dataset; mechanism-level
                    interpretations remain plausibility-graded hypotheses per
                    the Chapter 1 §1.5 scope boundary — the constraint stands
                    and is stated in the thesis).

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
Mitigation status:  ACCEPTED (2026-08-12, ADR-013/ADR-014: the event
                    definition is closed — one labelled event, EVENT-001 —
                    and the pre-committed rule selects the descriptive
                    case-study design; no inferential detection-rate or
                    lead-time claims).

## LIM-004 — Coverage span (superseded in part by LIM-007)

Date discovered:    2026-08-11
Description:        Originally recorded when only calendar year 2020 was held
                    (52,704 rows per turbine, perfectly regular 10-minute
                    interval, zero duplicates and zero gaps on all six
                    turbines). Six year-folders 2016–2021 have since been
                    censused; see LIM-007 for the actual spans, and LIM-005
                    for the thermal-channel availability that bounds the
                    usable modelling period.
Affected RQ(s):     RQ1 (seasonal covariate shift — risk R2), RQ2.
Mitigation status:  SUPERSEDED by LIM-005 / LIM-007.

## LIM-005 — Gear-oil thermal channels are entirely empty before 2016-05-03

Date discovered:    2026-08-11
Description:        In the 2016 export the gear-oil thermal channels ("Gear
                    oil temperature (°C)" and "Gear oil inlet temperature
                    (°C)") are **100% null from the file start until
                    2016-05-03 09:40**, on every turbine checked; monthly
                    non-null fractions for 2016 run 0.000 for January–April,
                    then 0.892 in May and 0.95–0.99 thereafter. Both channels
                    go null together in every year, so this is not an artefact
                    of requiring both.
                    Consequence measured directly: **780 Stop/Warning rows
                    across 2016–2021 have zero continuous covered SCADA
                    immediately preceding them, 731 of them in 2016.** Every
                    January–February 2016 gearbox-indexed occurrence — code
                    1510 "Low gearbox oil pressure" (4 occurrences, Kelmarsh
                    5, incl. the 95.06 h event of 2016-01-28), 1700/1710 "High
                    temp. gear bearing 1/2" (Kelmarsh 2, 2016-01-29/30), 75
                    "Reduced power gearbox", 1825 "Overload gear bypass
                    filter" (6 turbines), 1922 "Particle Gear Alarm 10min" —
                    records **0.0 h** of preceding covered thermal data.
Affected RQ(s):     RQ1, RQ2, RQ3; bears directly on D-04 (ground truth) and
                    D-05 (evaluation design), since an event with no healthy
                    thermal baseline before it cannot serve as an evaluation
                    milestone regardless of what it represents.
Mitigation status:  ACCEPTED (2026-08-12, ADR-013: candidates with zero
                    preceding thermal coverage are excluded from the
                    ground-truth event set; the modelling span starts
                    2016-05-03 per ADR-009 — a stated data constraint, not a
                    selection).

## LIM-006 — Status year-folders overlap at their boundaries

Date discovered:    2026-08-11
Description:        Status-file time ranges are not confined to their folder's
                    nominal year: the 2017 folder's rows start 2016-12-17
                    16:38:07 and the 2021 folder's rows start 2020-06-07
                    12:20:51. Concatenating folders therefore double-counts
                    some occurrences. Measured extent: of 282,235 rows,
                    **213 (turbine, start, code, duration) keys appear more
                    than once, giving 215 duplicate rows** — 9 keys shared
                    between the 2020 and 2021 folders, 1 between 2016 and
                    2017. Long-duration warnings are over-represented among
                    them (e.g. code 7057 at 5,447.7 h appears in both the 2020
                    and 2021 folders).
Affected RQ(s):     RQ2, RQ3 (event counting); any per-year aggregation.
Mitigation status:  MITIGATED (M-09 ingestion deduplicates concatenated files
                    on (turbine, timestamp, code) with content-hash
                    verification and raises on conflicting duplicates;
                    ADR-013 closes the event definition the policy feeds).

## LIM-007 — Actual holdings span 2016-01-03 to 2021-06-30, unevenly

Date discovered:    2026-08-11
Description:        Actual SCADA timestamp spans per year-folder (all six
                    turbines identical within a folder): 2016-01-03 00:00 to
                    2016-12-31 23:50 (52,416 rows); 2017, 2018, 2019 full
                    calendar years (52,560 rows each); 2020 full year (52,704
                    rows); **2021 is a half year — 2021-01-01 00:00 to
                    2021-06-30 23:50, 26,064 rows.** Thermal-channel non-null
                    coverage by folder (Kelmarsh 1): 2016 0.655, 2017 0.988,
                    2018 0.966, 2019 0.954, 2020 0.986, 2021 0.914.
                    Combined with LIM-005, the period in which gear-oil
                    thermal data exists at all is 2016-05-03 onward.
Affected RQ(s):     RQ1 (training-window length and seasonal coverage, §14
                    WARNING), RQ2.
Mitigation status:  OPEN — split design is queue item D-07; whether to obtain
                    the remainder of 2021 (and 2022) from the same Zenodo
                    record is an author decision.

## LIM-008 — EVENT-001 occurrence 3 coincides with abnormal operation

Date discovered:    2026-08-12
Description:        Within EVENT-001 (ADR-013: code 1860 "Oil filter gear
                    choked", Kelmarsh 1, 2019-02-24 to 2019-05-30), the third
                    occurrence has 27.1% null SCADA rows and a mean active
                    power of 375 kW, against 743 kW and 804 kW during
                    occurrences 1 and 2 — by the third occurrence the turbine
                    was operating abnormally, so its thermal record is not
                    comparable to the onset period.
Affected RQ(s):     RQ2, RQ3 (case-study evidence quality).
Mitigation status:  MITIGATED (ADR-014: case-study analysis focuses on the
                    onset of occurrence 1; occurrences 2–3 are reported as
                    continuation of the same episode, not as independent
                    evidence).
Source:             docs/evidence/EVIDENCE_D04_AND_TARGETS.json; author
                    ruling 2026-08-12.

## LIM-009 — CI gates have never run (no GitHub remote)

Date discovered:    2026-08-12
Description:        The repository has no GitHub remote, so the M-36 CI
                    pipeline (ruff, mypy, import-direction contract, pytest,
                    fixture reproduction — PROJECT.md §7, §32) has never
                    executed. All gates currently run locally only, which
                    leaves risk R10 (results irreproducible at write-up)
                    partially unmitigated: no clean-runner verification of
                    `git clone → uv sync → pytest` has ever happened.
Affected RQ(s):     none directly; reproducibility of every result (risk R10).
Mitigation status:  MITIGATED (2026-08-12). Remote created
                    (github.com/khedhrimokhles1997-sudo/wind-gearbox-diagnostics,
                    private) and CI confirmed green on a clean runner — all
                    five gates (ruff check, ruff format, mypy, import-linter,
                    pytest incl. the M-31 fixture-reproduction test) passed:
                    https://github.com/khedhrimokhles1997-sudo/wind-gearbox-diagnostics/actions/runs/31623910742
                    (author-confirmed conclusion: Success).
Source:             manual (author-flagged, 2026-08-12); Actions run
                    31623910742.

## LIM-010 — Icing events 9 days before EVENT-001 onset (known confounder)

Date discovered:    2026-08-12
Description:        Kelmarsh 1 logged an icing pair on 2019-02-03 04:00:30
                    — code 6682 "Icing (dev. electr. power)" (Warning) and
                    code 6690 "Icing (stop)" (Stop), 9.7 h duration — nine
                    days before EVENT-001 occurrence 1's onset
                    (2019-02-24 16:46:28). Icing perturbs the thermal
                    operating regime, so early-February residual behaviour
                    on Kelmarsh 1 may reflect icing thermal response rather
                    than lubrication degradation. Identified from the
                    committed census evidence BEFORE any detection results
                    were examined; it also bounds the ADR-017 matching
                    window (a window beyond ~14 days would capture it).
Affected RQ(s):     RQ2, RQ3 (EVENT-001 case-study interpretation).
Mitigation status:  OPEN — Chapter 5 must distinguish icing thermal
                    response from lubrication degradation when interpreting
                    early-February residual behaviour; recorded here so the
                    distinction is pre-committed, not post-hoc.
Source:             docs/evidence/KELMARSH_STATUS_VOCABULARY_2016_2021.json
                    (long_stop_or_warning_events); ADR-017 evidence review.

## LIM-011 — EWMA in-control false-alarm inflation (EXP-20260812-001)

Date discovered:    2026-08-12
Description:        EWMA in-control false-alarm inflation: empirical rate 0.16174 vs i.i.d. theoretical 0.00270 (59.9x) on the healthy validation block — serial correlation invalidates the theoretical ARL (risk R4); control limits may require widening.
Affected RQ(s):     RQ2 (detection thresholds; risk R4)
Mitigation status:  OPEN — widen limits or justify empirically (PROJECT.md §23)
Source:             M-20 empirical in-control characterization, experiment EXP-20260812-001

## LIM-012 — Status row with end before start (negative duration)

Date discovered:    2026-08-12
Description:        Exactly 1 of 282,234 parsed status rows has Timestamp end BEFORE Timestamp start: Kelmarsh 2, code 20 (Manual stop - remote), start 2016-10-10 13:43:49, end 2016-10-10 13:07:00 (-36.8 min). The M-24 event constructor refuses it; the row is reported verbatim and defines no exclusion window (same cannot-define-a-window policy as rows without ends).
Affected RQ(s):     RQ2 (event/window derivation); negligible extent (1 row)
Mitigation status:  ACCEPTED (single malformed row, excluded from window derivation with the refusal recorded; EXP-20260812-001)
Source:             scripts/run_kelmarsh_experiment.py alarm-window derivation

## LIM-013 — Monitoring-period ambient range exceeds training range

Date discovered:    2026-08-12
Description:        Seasonal coverage check (M-13, PROJECT.md 14) on the EXP-20260812-001 split: training ambient range (-4.1, 37.6) C vs monitoring-period range (-7.9, 44.0) C - the NBM extrapolates at both ambient extremes of the monitoring period, so residual inflation there may reflect seasonal covariate shift rather than degradation (risk R2). Calendar months are fully covered (26-month training window); the shortfall is range, not months.
Confounds on record for the EXP-20260812-001 validation/monitoring
reversal (XGBoost best on healthy validation, linear baseline best on the
2.4-yr monitoring period, DM p≈0):
                    (1) XGBoost was untuned (count 0; ADR-021 closes this);
                    (2) ambient extrapolation, above;
                    (3) the monitoring period deliberately includes
                        anomalous operation (unfiltered by design);
                    (4) — author-added 2026-08-13, judged the most likely —
                        EXP-001's training set had ~337k rows of load
                        transitions removed by the step-change detector
                        (LIM-014/ADR-018), so the tree model saw almost
                        only steady-state behaviour and would degrade
                        sharply on transients, while linear regression
                        degrades gracefully. That training set has since
                        been ruled incorrect (ADR-018).
                    Consequence (author ruling, ADR-021): the next run's
                    comparison is NOT comparable to EXP-001's, and
                    EXP-001's DM result must not be cited as a finding.
Structural finding (2026-08-13, ADR-023 — author-directed): NO ADMISSIBLE
SPLIT CLOSES THIS LIMITATION. The monitoring ambient extremes fall on
2019-11-14, 2020-11-13, 2019-07-25 and 2020-07-24 — all after any split
boundary that satisfies ADR-010 (EVENT-001 in TEST) — and the entire
pre-monitoring span covers only (−4.1, 38.9) °C. The extrapolation is a
property of the dataset combined with the EVENT-001-in-test constraint,
not of the dates chosen; Chapter 5 states it as a structural limitation
of the dataset, not a design shortcoming.
Affected RQ(s):     RQ1, RQ2
Mitigation status:  OPEN - condition-binned normalization (D-12) and the error-vs-ambient diagnostic (PROJECT.md 20) are the named mitigations; discuss in Chapter 5
Source:             M-13 seasonal coverage report, experiment EXP-20260812-001; ADR-021; ADR-023

## LIM-014 — Step-change exclusions dominate healthy-state attrition

Date discovered:    2026-08-12
Description:        In EXP-20260812-001, healthy-state retention over the train/validation periods is 46.2% (391,545 of 847,396 rows). The dominant exclusion is sensor_failure_or_step_change: 337,263 rows (39.8%), from the M-10 step-change heuristic (rolling-median window 144, min magnitude 5.0 C) with +/-1 day exclusion windows. Alarm periods removed 69,705 rows and the 50 kW power floor 48,883. Whether the step-change detector is identifying real recalibrations or over-firing on operational thermal swings is UNREVIEWED - its parameters were never sensitivity-tested and are not provisional-marked.
Affected RQ(s):     RQ1 (training representativeness), RQ2 (thresholds)
Mitigation status:  MITIGATED (2026-08-13, ADR-018: the author reviewed the
                    load-coincidence and persistence evidence and DISABLED
                    step-change exclusion — the detector was firing on
                    load-driven thermal transitions, not recalibrations, so
                    the exclusion was removing normal operating-regime
                    transitions from the healthy training set. The detector
                    remains reporting-only; the two recalibration-like
                    Kelmarsh 6 episodes are excluded by name; the parameters
                    and an enabled/disabled variant are provisional-marked
                    and swept by M-27. Conclusion stability is confirmed at
                    the next headline run's sensitivity pass.)
Source:             M-12 HealthyStateReport, experiment EXP-20260812-001

## LIM-015 — Guard checks cannot see tunables outside the config universe

Date discovered:    2026-08-13
Description:        The M-27 checklist test verifies that provisional-marked
                    config fields and sensitivity grids match exactly — but
                    both sets derive from the same universe (the config
                    schema), so a tunable constant that never entered the
                    config system is invisible to it. This is how the
                    step-change detector parameters ran unswept while
                    driving 39.8% of healthy-state attrition (LIM-014,
                    ADR-018): they were constructor defaults, not config
                    fields. The gap is structural — a consistency check
                    within a declared universe cannot detect that the
                    universe is incomplete — and closing the three
                    step-change parameters does not close the class: other
                    constants remain hard-coded outside the config system
                    (e.g. the M-20 in-control material-inflation threshold,
                    the run script's bootstrap replicate count and seed).
                    Full finding: ADR-019.
Affected RQ(s):     RQ1, RQ2, RQ3 (guard-architecture integrity; which
                    values the sensitivity phase can defend)
Mitigation status:  OPEN — closed per instance as constants are discovered
                    and lifted into marked config fields; the structural
                    limit is stated in Chapter 3's guard discussion
Source:             manual (author-directed during the ADR-018 ruling
                    review); ADR-019

## LIM-016 — EXP-20260812-001 scored monitoring rows on impossible predictors

Date discovered:    2026-08-13
Description:        EXP-20260812-001 had no handling policy for
                    RANGE.IMPOSSIBLE values: 1,462 test-partition rows were
                    scored with generator_speed readings the schema declares
                    physically impossible (all negative; rotor stationary at
                    every one), so residuals and EWMA states at those
                    timestamps were computed from impossible predictor
                    inputs and are not interpretable. In train/validation
                    the 1,764 such rows were kept out of the healthy state
                    only coincidentally — the provisional 50 kW power floor
                    happened to exclude them, and that floor is swept at
                    25/50/100 kW, so the protection could have vanished
                    silently under a sweep.
Affected RQ(s):     RQ1 (monitoring-period metrics include those rows),
                    RQ2 (detection states at those timestamps)
Mitigation status:  MITIGATED (2026-08-13, ADR-020: impossible predictor
                    values are nullified at cleaning and the rows dropped
                    via drop_missing_any_predictor in ALL partitions, with
                    per-partition counts stated in metrics; schema 1.3.0
                    reclassifies standstill jitter in (−5, −1] as in-range.
                    Applies from the next run — EXP-20260812-001's stored
                    artifacts are unchanged by design.)
Source:             EXP-20260812-001 dataset_report (RANGE.IMPOSSIBLE,
                    3,226 rows); raw-file analysis during the Ruling 2
                    review; ADR-020

## LIM-017 — EWMA in-control false-alarm inflation (EXP-20260813-001)

Date discovered:    2026-08-13
Description:        EWMA in-control false-alarm inflation: empirical rate 0.14799 vs i.i.d. theoretical 0.00270 (54.8x) on the healthy validation block — serial correlation invalidates the theoretical ARL (risk R4); control limits may require widening.
Affected RQ(s):     RQ2 (detection thresholds; risk R4)
Mitigation status:  OPEN — widen limits or justify empirically (PROJECT.md §23)
Source:             M-20 empirical in-control characterization, experiment EXP-20260813-001
