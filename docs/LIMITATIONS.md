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
                    CLOSED (2026-08-13): re-confirmed green on the current
                    head — commit 89cb7b3 (the session-7 ruling series,
                    ADR-018…024 + the matched-FPR sweep script), Actions
                    run 31719097400, conclusion Success (author-confirmed).
                    Further confirmation: commit 4e8315c (ADR-025/026,
                    LIM-022, EVENT-001 derivation script), Actions run
                    31726409390, conclusion Success (author-confirmed).
Source:             manual (author-flagged, 2026-08-12); Actions runs
                    31623910742, 31719097400, 31726409390.

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
Mitigation status:  ACCEPTED (2026-08-13 — the confounder MATERIALISED:
                    the fleet evidence answered the pre-committed
                    question, and not in favour of the case study; see
                    LIM-023 for the finding and the reframing).
Chapter 5 obligation (STRONGEST FORM — author ruling 2026-08-13, on the
LIM-023 fleet finding): the case study MUST report (a) that the
detection coincides with a fleet-wide excursion following the icing
episode, (b) that the available evidence does not support attributing
it to gearbox degradation, and (c) that this is the outcome of a
confounder identified BEFORE results were examined. THE 13-DAY LEAD
MUST NEVER APPEAR AS AN EARLY-DETECTION CLAIM.
Supporting descriptive evidence on file: EXP-20260813-002
evaluation/event001_context_stats.json and
plots/event001_context_*.png (Kelmarsh 1 and fleet residual/EWMA
series, 2019-01-15 → 2019-03-10 — the fleet-coherence principle from
docs/evidence/AMBIENT_EXTREME_20190725_WORKED_EXAMPLE.md applied to
residuals).
Source:             docs/evidence/KELMARSH_STATUS_VOCABULARY_2016_2021.json
                    (long_stop_or_warning_events); ADR-017 evidence review;
                    ADR-025 outcome; LIM-023.

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
Narrowing (2026-08-13, EXP-20260813-001 — author-directed record): the
COLD-END extrapolation was ELIMINATED as a side effect of the ADR-020
impossible-predictor policy, ruled for unrelated reasons: the −7.9 °C
monitoring extreme rode on parked rows with impossible negative
generator_speed readings, which the policy drops, leaving the scored
monitoring stream at (−2.35, 43.99) °C — the cold end now inside the
training range. The structural finding applies to the WARM END ONLY:
+6.4 °C beyond the 37.58 °C training maximum.
Case-study reach (2026-08-13, measured): the warm-end confounder DOES NOT
TOUCH the EVENT-001 case study. 593 of 757,683 monitoring rows (0.078%)
exceed the training maximum, all on 10 July–August days in 2019/2020;
ZERO fall inside the ADR-017 match window, whose ambient range is
(4.1, 22.2) °C. The 43.99 °C maximum is a genuine fleet-coherent
heatwave reading (2019-07-25, all six turbines 40–44 °C over a
6.5-hour afternoon spell), not a sensor artefact.
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

## LIM-018 — No artefact screening on predictor channels

Date discovered:    2026-08-13
Description:        The M-10 validation layer screens the thermal TARGET
                    channels for step changes and level shifts, but applies
                    no equivalent artefact screening to PREDICTOR channels.
                    Both predictor artefacts found in this project — the
                    generator_speed stuck-signal episode (269 identical
                    −576.6 RPM readings, a 39.7-h run; ADR-020) and the
                    2019-07-25 ambient extreme check — were identified by
                    manual investigation prompted by run findings, not by
                    an automated rule.
                    Residual risk, plainly: an undetected predictor
                    artefact would propagate into model inputs and
                    therefore into residuals, and nothing in the current
                    pipeline would surface it. Two mitigations incidentally
                    apply — the schema plausible-range checks catch
                    impossible values, and the ADR-020 nullify-then-drop
                    policy removes them — but these catch IMPOSSIBLE
                    values, not plausible-but-wrong ones.
                    Cross-turbine consistency is the demonstrated manual
                    screen: see the 2019-07-25 worked example
                    (docs/evidence/AMBIENT_EXTREME_20190725_WORKED_EXAMPLE.md),
                    kept on file for Chapter 5's data-quality discussion.
Affected RQ(s):     RQ1 (model inputs), RQ2 (residuals and detection
                    states derived from them)
Mitigation status:  ACCEPTED (2026-08-13, author ruling — deliberate,
                    dated omission: the pipeline is complete, the
                    remaining work is analysis, and adding a new detector
                    at this stage would invalidate the headline run for a
                    risk with no evidence of having materialised. The
                    omission is recorded so it is deliberate, not
                    overlooked.)
Source:             manual (author ruling during the ADR-024 review);
                    ADR-020 evidence; 2019-07-25 ambient check

## LIM-020 — Persistence boundary and coincidence requirement interact in the RQ2 criterion

Date discovered:    2026-08-13
Description:        In the EXP-20260813-002 matched-FPR sweep, the
                    coordination requirement (simultaneous breach on both
                    targets) produces systematically SHORTER alarm
                    episodes than single-signal union monitoring at
                    matched episode rates — e.g. median 2.0 vs 13.5
                    samples at λ=0.2 @ 2 FA/turbine-year — because a
                    coincidence episode is the intersection of two
                    exceedances and coordination runs a looser per-signal
                    multiplier to reach the same episode rate. Coordinated
                    episodes therefore fall below the 3-sample persistence
                    boundary and are counted as ISOLATED excursions by the
                    ADR-016 operationalisation. The isolated/sustained
                    boundary and the coincidence requirement interact in a
                    way not anticipated when the operationalisation was
                    fixed.
                    This is recorded as a LIMITATION OF THE PRE-REGISTERED
                    CRITERION, NOT as grounds for revising it: the
                    criterion was fixed before the sweep ran and its
                    verdict stands as computed (ADR-016 Outcome).
                    Alternative-boundary analyses are exploratory only.
Affected RQ(s):     RQ2 (the primary criterion's construct validity)
Mitigation status:  ACCEPTED (author ruling 2026-08-13 — the verdict
                    stands; the interaction is discussed in Chapter 5 as
                    a limitation of the criterion design)
Answered by measurement (2026-08-19, ADR-048): the concern recorded here was
                    that the 3-sample boundary might be carrying the verdict.
                    It is not. Under the corrected ADR-028 denominator the
                    ADR-031 boundary sweep shows the verdict does NOT flip at
                    literature-anchored persistence — it HARDENS. At λ=0.2 the
                    "met" verdicts vanish entirely at 10, 12 and 20 samples
                    (5 not met, 2 not interpretable at each); at λ=0.3 they
                    fall from 3 at boundary 3 to 0 at boundaries 10 and 12.
                    The interaction described above is real, but it works
                    AGAINST coordination only at the short pre-registered
                    boundary; at published-practice boundaries coordination
                    fails the criterion outright. This strengthens the
                    pre-registered negative rather than qualifying it.
Source (addendum):  `artifacts/EXP-20260818-001/evaluation/matched_fpr_sweep.json`,
                    key `exploratory_boundary_sensitivity`.
Source:             EXP-20260813-002 matched_fpr_sweep.json; author
                    ruling 2026-08-13

## LIM-021 — Validation-to-monitoring false-alarm transfer gap

Date discovered:    2026-08-13
Description:        At identical control-limit multipliers, false-alarm
                    rates measured on the ADR-022/024 healthy monitoring
                    slice run 10–50× the rates achieved on the healthy
                    validation block, and the divergence GROWS toward
                    stricter operating points (tail behaviour transfers
                    worse than the bulk). Example: the λ=0.2 point
                    achieving ~10 FA/turbine-year on validation shows
                    ~118 (union) / ~75 (coordinated) FA/turbine-year on
                    the slice; the strictest swept point (λ=0.3,
                    validation ~0.5/ty) still shows ~25–27/ty on the
                    slice. A validation-selected operating point is
                    therefore nominally misleading about monitoring-period
                    false-alarm behaviour.
                    Four candidate explanations the sweep cannot separate:
                    (1) seasonal/covariate shift (LIM-013's warm end);
                    (2) model ageing across 2019–2021 relative to the
                    2016–2018 training window; (3) per-turbine drift;
                    (4) sub-alarm degradation within the "healthy" slice.
                    Separating them is beyond this work's scope.
Affected RQ(s):     RQ2 (operating-point selection and every false-alarm
                    claim); RQ3 (alert volume at any deployed point)
Mitigation status:  OPEN — handled at selection per the author's ruling
                    (2026-08-13): the PRIMARY operating point is selected
                    on the validation block with its measured
                    out-of-period rate reported alongside the nominal
                    target (independence over nominal accuracy); a
                    SECONDARY slice-calibrated point is reported with the
                    weaker independence claim stated plainly. Discussed
                    in Chapter 5.
Source:             EXP-20260813-002 matched_fpr_sweep.json (slice_check
                    columns); author ruling 2026-08-13

## LIM-022 — Descriptive finding: only coordination reaches low out-of-period FA rates

Date discovered:    2026-08-13
Description:        DESCRIPTIVE, POST-HOC finding from the EXP-20260813-002
                    matched-FPR sweep's slice calibration — explicitly NOT
                    the ADR-016 verdict, and it does not amend the
                    pre-registered answer (which is predominantly
                    not-met and stands as computed).
                    On the healthy monitoring slice, single_union cannot
                    reach operationally low false-alarm rates at any
                    multiplier within the swept grid: nothing below
                    ~20/turbine-year at λ=0.1 even at 40σ, nothing below
                    ~10–20/turbine-year at the other lambdas. The
                    coordinated pipeline reaches 0.5–2/turbine-year at
                    every λ. Out-of-period, the coincidence requirement is
                    what makes low-false-alarm operation achievable at
                    all.
                    This is the practically consequential result and
                    belongs in Chapter 5 ALONGSIDE the pre-registered
                    verdict — both reported, neither suppressed.
Affected RQ(s):     RQ2 (the practical case for coordination), RQ3
                    (operational alert volume)
Mitigation status:  ACCEPTED (author ruling 2026-08-13 — recorded with
                    the post-hoc labelling discipline: the pre-registered
                    verdict is stated first wherever this finding
                    appears)
Source:             EXP-20260813-002 matched_fpr_sweep.json
                    (slice_calibration); author ruling 2026-08-13

## LIM-023 — Finding: the 2019-02-11 excursion is fleet-wide, not a Kelmarsh 1 fault signature

Date discovered:    2026-08-13
Description:        FINDING, not a caveat (author ruling 2026-08-13, on
                    the descriptive context series for the LIM-010
                    discussion — EXP-20260813-002
                    evaluation/event001_context_stats.json and
                    plots/event001_context_*.png):
                    EWMA maxima rise from the pre-icing window
                    (2019-01-15 → 02-03) to the icing→detection window
                    (02-03 → 02-11 17:10) on ALL SIX turbines, on BOTH
                    thermal targets, and remain elevated afterwards.
                    Kelmarsh 5's excursion (5.31 bearing / 5.65 oil) is
                    roughly double the event turbine's (2.40 / 2.67);
                    Kelmarsh 1 ranks THIRD on both targets (recorded from
                    the measured table; the ruling as dictated said
                    fourth — corrected against the data at recording).
                    Peak absolute normalized residuals move from 2.4–3.7
                    pre-icing to 9.6–17.2 fleet-wide from 02-03 onward.
                    CONCLUSION FOR THE RECORD (author): by the same
                    fleet-coherence principle used to validate the
                    2019-07-25 ambient reading
                    (docs/evidence/AMBIENT_EXTREME_20190725_WORKED_EXAMPLE.md),
                    the 2019-02-11 residual excursion is a FLEET-WIDE
                    ENVIRONMENTAL RESPONSE, not a Kelmarsh 1 fault
                    signature. The 13-day lead cannot be attributed to
                    the code-1860 lubrication event on this evidence.
                    FRAMING (author): this does not invalidate EVENT-001
                    as a case study — it changes what the case study
                    demonstrates: the episode illustrates that
                    coordinated thermal residuals respond to
                    environmental disturbance in a manner not
                    distinguishable from degradation onset at these
                    operating points — a substantive limitation of
                    thermal-residual monitoring, and it belongs in
                    Chapter 5 as such.
Affected RQ(s):     RQ2, RQ3 (what the EVENT-001 case study evidences);
                    the thesis's thermal-residual monitoring claims
                    broadly.
Mitigation status:  ACCEPTED (author ruling 2026-08-13; the strongest-form
                    Chapter 5 reporting obligation is recorded in
                    LIM-010; the M-27 suite carries a conclusion label
                    tracking whether the fleet-wide character is stable
                    across configurations)
Source:             EXP-20260813-002 event001_context_stats.json /
                    event001_context_*.png; author ruling 2026-08-13

## LIM-019 — EWMA in-control false-alarm inflation (EXP-20260813-002)

Date discovered:    2026-08-13
Description:        EWMA in-control false-alarm inflation: empirical rate 0.14799 vs i.i.d. theoretical 0.00270 (54.8x) on the healthy validation block — serial correlation invalidates the theoretical ARL (risk R4); control limits may require widening.
Affected RQ(s):     RQ2 (detection thresholds; risk R4)
Mitigation status:  OPEN — widen limits or justify empirically (PROJECT.md §23)
Source:             M-20 empirical in-control characterization, experiment EXP-20260813-002

## LIM-024 — EWMA in-control false-alarm inflation (EXP-20260817-001)

Date discovered:    2026-08-17
Description:        EWMA in-control false-alarm inflation: empirical rate 0.16214 vs i.i.d. theoretical 0.00270 (60.1x) on the healthy validation block — serial correlation invalidates the theoretical ARL (risk R4); control limits may require widening.
Affected RQ(s):     RQ2 (detection thresholds; risk R4)
Mitigation status:  OPEN — diagnosed and addressed by ADR-034 (PROPOSED).
                    Measured mean lag-1 phi 0.7703 on the normalized residual
                    predicts 2.07x variance inflation against 2.28x measured,
                    implying 18.87% exceedance against the 16.21% recorded:
                    serial correlation accounts for the whole discrepancy.
                    ADR-034 rules for block-bootstrap empirical limits and
                    rejects prewhitening. Reproduce with
                    scripts/diagnose_residual_dependence.py.
Regime mismatch RULED OUT as a contributor (2026-08-19, ADR-047 Consequence 3):
                    LIM-034 raised the possibility that this inflation is a
                    mixture effect — a tight trained-regime component plus a
                    wide untrained-regime one. It is not, and cannot be. This
                    rate is measured on the healthy VALIDATION block, which is
                    built with the full healthy-state criteria INCLUDING the
                    active-power floor, so every row in it is in-regime by
                    construction (verified: minimum power 50.001 kW, zero rows
                    below the floor). The regime split of ADR-047 does not
                    reduce this figure and no future split will. ADR-034
                    (serial correlation) stands as the SOLE explanation on
                    record, and is now also corroborated externally — see the
                    ADR-026 addendum (Fiocchi et al. raised a CUSUM decision
                    interval from theoretical I=5 to empirical I=15 on this
                    same dataset).
Source:             M-20 empirical in-control characterization, experiment EXP-20260817-001

## LIM-025 — Threshold statistics are fitted on data containing the tuning block

Date discovered:    2026-08-18
Description:        ADR-030 moved candidate scoring to an inner holdout carved
                    from the END of TRAIN, so the healthy VALIDATION block is
                    no longer used for selection. But the ADR-001 default
                    fits normalization and control-limit statistics on
                    `training` — which CONTAINS that inner holdout. The
                    separation ADR-030 bought is therefore partly given back:
                    the thresholds are calibrated on data that includes the
                    block the model was selected to fit well.
                    Extent, measured: the inner holdout is 20% of the healthy
                    training partition (103,628 of 518,141 rows in
                    EXP-20260817-001), so roughly a fifth of the calibration
                    population is selection-touched. The bias direction is the
                    one ADR-030 names — an optimistically low in-control
                    false-alarm rate — at about a fifth of the strength.
                    This is separable at zero data cost by closing ADR-001 to
                    `validation`, which ADR-030 left clean for exactly this
                    purpose. That closure is decision D-11, still OPEN.
Affected RQ(s):     RQ2 (threshold provenance and in-control characterisation)
Mitigation status:  OPEN — closes with D-11/ADR-001. Both branches exist as
                    configuration and both are swept by M-27, so the closure
                    evidence §22 names can be produced in one run.
Source:             source audit 2026-08-18; `runner.py` `_fit_and_predict`
                    and `_residual_stages`; ADR-030.

## LIM-026 — The single event match is a cold-side excursion

Date discovered:    2026-08-18
Description:        FINDING, not a caveat. EVENT-001 is code 1860, "Oil filter
                    gear choked" — a lubrication-flow restriction whose
                    physical signature is a temperature RISE. The detection
                    that matched it is a temperature FALL.
                    Measured from EXP-20260817-001's stored residuals at the
                    λ=0.2 / 3σ configuration: of the 82 persistent detections
                    on Kelmarsh 1 inside the ADR-017 14-day window, 72 are
                    direction −1 and 10 are +1. The matched detection
                    (2019-02-10 20:50 UTC, the one carrying the recorded
                    lead_time_minutes = 19,910) is direction −1. The earliest
                    POSITIVE-direction persistent detection is 2019-02-22
                    05:10, two days before onset rather than thirteen.
                    The project's own FMEA interpreter agrees: its rendering
                    at the matched timestamp reads "gearbox_bearing_temperature
                    LOW (EWMA −1.24); gearbox_oil_temperature normal (EWMA
                    −1.23) ... No candidate mechanism: the anomalous pattern
                    matched no FMEA rule."
                    ADR-017's matching rule is direction-agnostic and was
                    pre-registered that way, so the verdict stands as computed
                    and is NOT revised. What changes is that the direction is
                    now recorded on every match (ADR-037) so this cannot be
                    read as early detection by omission.
Consequence for RQ3:
                    the sole labelled event contributes no positive evidence
                    for mechanism interpretation. The case study's content is
                    what LIM-023 already established — that coordinated thermal
                    residuals respond to environmental disturbance in a manner
                    not distinguishable from degradation onset — and this
                    finding sharpens it: the response was not even of the sign
                    the mechanism predicts.
Affected RQ(s):     RQ2, RQ3 (what the EVENT-001 case study evidences)
Mitigation status:  ACCEPTED — reported as a finding. Chapter 5 must state the
                    direction alongside any mention of the 13.8-day figure,
                    under the LIM-010 strongest-form obligation.
Source:             re-derivation from `artifacts/EXP-20260817-001/residuals/
                    test.parquet` via `persistent_detections`, 2026-08-18;
                    ADR-037.

## LIM-027 — Five provisional parameters cannot be defended by this dataset

Date discovered:    2026-08-18
Description:        PROJECT.md §27.3 states that sensitivity analysis
                    "converts the provisional configuration values of Sections
                    13 and 23 into defended choices". For five of the fourteen
                    provisional parameters it cannot, because they have no
                    lever on this dataset:
                    - `healthy_state.fault_pre_exclusion_days` (grid 15/30/60)
                      and `healthy_state.maintenance_post_exclusion_days`
                      (1/2/4): no caller anywhere constructs fault or
                      maintenance exclusion windows. The dataset carries no
                      maintenance-confirmed failures (LIM-002) and the
                      designated episode is applied as a manual window, so the
                      pre-fault and post-maintenance machinery never runs.
                      Verified by inspecting every `PipelineInputs`
                      construction in the repository.
                    - `healthy_state.step_change_exclusion_days`,
                      `validation.step_change_window_samples` and
                      `validation.step_change_min_magnitude_c`: ADR-018
                      disabled step-change exclusion, and the suite sweeps one
                      parameter at a time around that base, so all three are
                      inert except inside the arm that switches exclusion back
                      on.
                    Before ADR-040 all five produced identical outcomes at
                    every swept value and were reported as STABLE — which
                    reads as robustness evidence for parameters that were
                    merely switched off.
Affected RQ(s):     RQ1, RQ2 (which configuration values the sensitivity phase
                    can actually defend)
Mitigation status:  MITIGATED as reporting (ADR-040: the suite now labels them
                    NOT_APPLICABLE with a stated reason and excludes them from
                    the conclusion-flip register). The underlying constraint is
                    ACCEPTED and permanent for this dataset: Chapter 3 must
                    state that these five values are inherited from PROJECT.md
                    and are undefended by experiment, rather than implying the
                    sweep defended them.
Source:             source audit 2026-08-18; ADR-040.

## LIM-028 — Detection scores operating states the model never trained on

Date discovered:    2026-08-18
Description:        Two rules of the specification interact in a way neither
                    anticipates. PROJECT.md §13 builds the healthy training
                    population by excluding alarm periods and every row below
                    the 50 kW power floor; PROJECT.md §14 keeps the TEST
                    partition UNFILTERED, because anomalous rows there are the
                    signal being monitored.
                    The consequence is that the NBM is fitted only on
                    above-floor, alarm-free operation and is then asked to
                    score every monitoring row, including parked, curtailed,
                    alarmed and negative-power samples. On EXP-20260817-001
                    the healthy slice retains 538,045 of 740,463 monitoring
                    rows, so roughly 27% of the detection stream is a regime
                    the model never saw. The PHASE 10 EDA records that 10.8%
                    of samples carry negative active power and 17.1% fall
                    below the floor.
                    The size of the effect is visible in the metrics: thesis
                    RMSE is 2.165 °C on the healthy slice and 7.285 °C on the
                    unfiltered stream the detector actually reads — a 3.4x
                    degradation on the population that generates the alarms.
                    A material share of the 19,326 false-alarm episodes is
                    therefore extrapolation, not degradation.
Affected RQ(s):     RQ2 (every false-alarm claim), RQ3 (alert volume)
Mitigation status:  OPEN — no mitigation is applied. The candidates are an
                    operating-state gate on the DETECTION path (which §14
                    arguably forbids), or reporting detection results
                    separately for in-regime and out-of-regime rows. Neither
                    is adopted here: both are methodological choices reserved
                    to the author. Stated so the false-alarm rate is not read
                    as a pure detector property.
Source:             source audit 2026-08-18; EXP-20260817-001 metrics;
                    `docs/evidence/KELMARSH_EDA_2016_2021.json`
                    (operating_regime).

## LIM-029 — Monitoring-period dispersion: a regime STEP plus a slower drift

Date discovered:    2026-08-18
Description:        FINDING, with the decomposition stated because the headline
                    number is misleading on its own.
                    Annual residual σ on the unfiltered monitoring stream rises
                    across the period, on all six turbines and both targets:
                      bearing σ  1.99 (train) → 5.35 (2019) → 6.59 → 9.64 (2021)
                      oil σ      2.41 (train) → 4.23 (2019) → 5.13 → 7.33 (2021)
                    Read alone, that looks like steady model ageing. The §20
                    dispersion figure (ADR-045) shows it is not, and the
                    decomposition below is what the figure prompted:

                    (a) TYPICAL DAYS BARELY MOVE. Median daily σ runs
                        1.50 (train) → 1.81 (2019) → 1.71 (2020) → 2.41 (2021)
                        for bearing; 1.71 → 2.00 → 1.92 → 2.48 for oil. A
                        30-day rolling median of the fleet is close to flat
                        until early 2021.
                    (b) THE TAIL IS WHAT MOVES. The fraction of residuals
                        exceeding |10 °C| runs
                        0.155% (train) → 7.08% (2019) → 8.10% → 15.82% (2021)
                        for bearing; 0.514% → 4.59% → 5.92% → 13.54% for oil.

                    Two mechanisms, of different sizes:
                    - A STEP at the train/monitor boundary — 0.155% to 7.08%
                      extreme residuals immediately, with no time for ageing.
                      This is LIM-028: the training population is
                      healthy-filtered and the monitoring stream is not, so
                      roughly 27% of the scored rows are operating states the
                      model never saw. This is the DOMINANT term.
                    - A genuine DRIFT on top of it: extremes roughly double
                      again from 2019 to 2021 and typical-day σ rises ~33%,
                      which the regime difference alone does not explain and
                      which is consistent with the model ageing LIM-021 lists.
                      This is the SECONDARY term.

                    Kelmarsh 1 — the EVENT-001 turbine — is LESS dispersed than
                    the fleet in every year, so neither term is a fault
                    signature. The pooled median drifts negative in step
                    (bearing −0.090 → −0.247 → −0.718) and LOW exceedances
                    outnumber HIGH by about 3.5 : 1 on the monitoring stream.
Consequence:        the dominant variance in the monitoring period is
                    OPERATING-REGIME MISMATCH, not gearbox condition and not
                    primarily ageing. An earlier draft of this entry attributed
                    it mainly to ageing; the daily decomposition does not
                    support that and the entry is corrected here rather than
                    quietly amended. No detection claim on this dataset can be
                    attributed to degradation without addressing both terms.
Affected RQ(s):     RQ1 (what the unfiltered-period metrics measure), RQ2
                    (every detection claim), RQ3
Mitigation status:  OPEN. Two separable measurements would close it, neither
                    commissioned here: (i) report detection results split by
                    in-regime / out-of-regime rows, which isolates the step;
                    (ii) a refit-horizon study (refit at 2019-01 / 2020-01 /
                    2021-01, report σ per horizon), which isolates the drift.
                    Together they are the most transferable result available
                    from this dataset — how long a statically-fitted SCADA NBM
                    stays valid, and how much of its apparent decay is really
                    regime mismatch — and are recommended as the first item of
                    future work.
Source:             aggregation of `artifacts/EXP-20260817-001/residuals/
                    test.parquet` by year, turbine and day, 2026-08-18;
                    `plots/*_residual_over_time.png` (ADR-045).

## LIM-030 — The FMEA rule base cannot discriminate at the measured channel correlation

Date discovered:    2026-08-18
Description:        ADR-035 measured the cross-target residual correlation at
                    r = 0.932–0.952 and drew the consequence for RQ2. The
                    consequence for RQ3 was not drawn, and it is at least as
                    binding.
                    Of the five ADR-008 rules, four are instantiable (FMEA-005
                    needs generator-side residual channels that are not
                    modelled). Of those four:
                    - FMEA-001 (gear-teeth wear) requires oil HIGH with bearing
                      `any`;
                    - FMEA-002 (HSS bearing) requires bearing HIGH with oil
                      `any`;
                    - FMEA-004 (lubrication degradation) requires BOTH HIGH.
                    At r ≈ 0.95 an oil-high state implies a bearing-high state
                    almost always, so all three fire together on essentially
                    every positive excursion. FMEA-003 requires oil HIGH with
                    bearing NORMAL — a near-empty region of a joint
                    distribution ADR-035 describes as "a thin cigar on the
                    diagonal".
                    The interpretation layer therefore returns the same
                    undifferentiated candidate set whenever it fires. Its
                    temporal qualifiers (lead / lag / sustained), which are
                    what Chapter 2 Table 2.3 actually uses to separate the
                    mechanisms, are carried as TEXT and are not mechanically
                    matched — the ruleset header states this, but the
                    consequence for RQ3's discriminating power does not appear
                    anywhere.
                    Compounding it: the bearing target is a designated
                    main-shaft channel ("Rear bearing temperature", ADR-012),
                    not an internal gearbox bearing, so FMEA-002 and FMEA-003
                    describe a node this dataset does not instrument (LIM-001).
Affected RQ(s):     RQ3 (the central claim), RQ2
Mitigation status:  OPEN. RQ3 as posed cannot be answered affirmatively on
                    this dataset by this rule base. The honest options are to
                    reduce the RQ3 claim to a demonstration of the mechanism
                    (which the code supports and Guard 7 labels correctly), or
                    to implement the ADR-035 orthogonal-mode arm, whose
                    differential mode is the only quantity available here that
                    could discriminate a bearing-specific signature. Neither is
                    adopted without an author ruling.
Source:             `app/fmea/rulesets/initial_v1.yaml` read against ADR-035's
                    measured correlations, 2026-08-18.

## LIM-031 — A no-model baseline matches the NBM on detection behaviour

Date discovered:    2026-08-18
Description:        FINDING, from the B3 arm the EXPERIMENT_PROTOCOL §4 listed
                    as required and that had never been run
                    (`scripts/run_robustness_suite.py --arms b3`).
                    A detector using NO model, NO training period and NO tuning
                    — the leave-one-out fleet-median deviation of the raw
                    target, `actual - median(peer turbines at the same
                    timestamp)` — was pushed through the IDENTICAL normalizer,
                    EWMA detector and matched-FPR sweep as the NBM residual, so
                    the two arms differ only in how the expected value was
                    formed. Measured on the healthy validation block:

                      residual sigma, bearing   fleet 2.446 vs NBM 2.076 degC
                      residual sigma, oil       fleet 2.255 vs NBM 2.578 degC
                      in-control rate           fleet 0.17302 vs NBM 0.16214
                      inflation vs nominal      fleet 64.1x  vs NBM 60.1x
                      multiplier @10 FA/ty      fleet 8.89   vs NBM 10.76

                    On the gearbox OIL target — one of the two thesis targets —
                    the trivial baseline produces a TIGHTER residual than the
                    tuned multi-target XGBoost NBM. On bearing the NBM is 15%
                    tighter. Both arms show the same ~60x in-control inflation,
                    so that pathology is a property of the thermal signal, not
                    of the model.
Scope, stated fairly:
                    this does not make the NBM worthless, and the two
                    quantities are not interchangeable. The fleet-relative
                    deviation uses CONTEMPORANEOUS cross-turbine information:
                    it can only see single-machine deviations and would be
                    blind to a farm-wide fault mode, which is the same
                    limitation ADR-029 binds its arm to. The NBM needs no peers
                    and would still function on a single-turbine deployment.
Consequence:        the NBM's contribution OVER A NO-MODEL BASELINE is not
                    established by detection behaviour. Any argument that runs
                    from RQ1 accuracy to RQ2 detection capability must now
                    address this, and Chapter 4 should report the comparison
                    rather than leave an examiner to ask for it.
Affected RQ(s):     RQ1 (what the model's accuracy buys), RQ2 (every detection
                    claim)
Mitigation status:  ACCEPTED as a finding and reported. The follow-up that
                    would sharpen it is B4 (persistence without EWMA), which
                    isolates the other untested component of the detector.
Source:             `artifacts/EXP-20260817-001/evaluation/robustness_suite.json`,
                    arm `b3`, 2026-08-18; ADR-046.

## LIM-032 — The multi-target architecture contributes no measurable accuracy

Date discovered:    2026-08-18
Description:        FINDING, from the PROJECT.md §18 per-target ablation
                    (`--arms multi_output`), which the specification requires
                    and which had never been run despite the code path existing
                    and being tested.
                    Two full pipeline runs identical except for
                    `model.multi_output`. Thesis-model RMSE on the ADR-022
                    headline slice:
                      bearing   multi-output 2.1647 vs per-target 2.1611
                      oil       multi-output 2.6904 vs per-target 2.7155
                    Each configuration wins on one target; both margins are
                    under 1% of RMSE and roughly an order of magnitude smaller
                    than the confidence-interval half-width on the same
                    quantity (~0.09 bearing, ~0.11 oil). The baselines
                    reproduce identically across both arms, confirming the runs
                    differed only in the intended parameter.
Consequence:        the thesis cannot claim an ACCURACY benefit from its
                    headline architectural choice. Native multi-output remains
                    defensible on other grounds — one model to fit, store and
                    serve — but "multi-target" is not doing work at the
                    modelling stage.
                    It was never expected to: the multi-target framing was
                    supposed to pay off at the COORDINATION stage. ADR-035 has
                    since measured the two residual channels at r ~ 0.95, which
                    is where that payoff was meant to come from. Between this
                    entry and ADR-035, the space in which the multi-target
                    contribution can live has narrowed to the orthogonal-mode
                    arm ADR-035 registers and which remains unimplemented.
Affected RQ(s):     RQ1, RQ2 (the thesis's central architectural claim)
Mitigation status:  ACCEPTED as a finding. Chapter 4 reports the ablation;
                    Chapter 6 should not claim accuracy benefit from
                    multi-target modelling.
Source:             `artifacts/EXP-20260817-001/evaluation/robustness_suite.json`,
                    arm `multi_output`, 2026-08-18; ADR-046.

## LIM-033 — EWMA in-control false-alarm inflation (EXP-20260818-001)

Date discovered:    2026-08-18
Description:        EWMA in-control false-alarm inflation: empirical rate 0.16214 vs i.i.d. theoretical 0.00270 (60.1x) on the healthy validation block — serial correlation invalidates the theoretical ARL (risk R4); control limits may require widening.
Affected RQ(s):     RQ2 (detection thresholds; risk R4)
Mitigation status:  OPEN — widen limits or justify empirically (PROJECT.md §23).
                    This is the EXP-20260818-001 instance of LIM-024; the
                    diagnosis, the ADR-047 ruling-out of regime mismatch, and
                    the ADR-026 external corroboration all apply verbatim and
                    are recorded once, under LIM-024.
Source:             M-20 empirical in-control characterization, experiment EXP-20260818-001

## LIM-034 — Half the monitoring residual variance comes from 18% of rows the model never trained on

Date discovered:    2026-08-18
Description:        FINDING, and the quantitative root cause behind LIM-028,
                    LIM-029, LIM-031 and the direction result of LIM-026. It is
                    the first thing the PROJECT.md §20 condition diagnostics
                    produced when they were finally run (ADR-045), on
                    EXP-20260818-001.

                    Thesis-model residual on the unfiltered monitoring stream,
                    bearing target, by operating band:

                      band                  rows   share    mean    sigma  |r|>10C
                      negative power      86,007   11.6%  -16.96   10.85    71.6%
                      0-50 kW             46,899    6.3%   -2.21    5.29     8.8%
                      50-250 kW          157,155   21.2%   -0.14    3.14     1.2%
                      250-1000 kW        267,662   36.1%   -0.14    1.98     0.2%
                      >1000 kW           182,740   24.7%   +0.03    1.27     0.0%

                    Two facts follow directly:
                    (a) ABOVE the 50 kW healthy-state floor — the regime the
                        NBM was fitted on — the model is essentially unbiased
                        and tight: mean -0.09 degC, sigma 2.18, and 0.0% of
                        rows beyond |10 degC| at rated power.
                    (b) BELOW the floor the model is catastrophically wrong:
                        mean -11.75 degC overall, and on negative-power rows
                        71.6% of residuals exceed |10 degC|.

                    Those below-floor rows are 17.9% of the detection stream
                    and carry 50.4% OF THE TOTAL RESIDUAL VARIANCE.

Explains, in one measurement:
                    - the 60x in-control false-alarm inflation (LIM-024): the
                      residual distribution the control limits are asked to
                      police is a mixture of a tight trained-regime component
                      and a wide untrained-regime component;
                    - the 19,326 false-alarm episodes;
                    - why LOW exceedances outnumber HIGH by ~3.5:1 — the
                      below-floor mean is -11.75 degC, so the untrained regime
                      produces large NEGATIVE residuals;
                    - why the single EVENT-001 match is direction -1 (LIM-026):
                      cold-side excursions are what this pipeline mostly emits;
                    - why the ambient slice shows worst error at the COLD end
                      (sigma 13.6 degC near 1 degC ambient, best above 20 degC)
                      rather than at the warm end LIM-013 anticipated — cold
                      ambient co-occurs with parked and idling machines;
                    - why the B3 fleet-median-only baseline competes (LIM-031):
                      it has no trained/untrained regime distinction to violate;
                    - the "step" component of LIM-029.

Consequence:        the NBM is NOT poor. It is good where it was trained and is
                    being asked a question it was never fitted to answer on
                    nearly a fifth of the stream. Every false-alarm figure in
                    this project is therefore dominated by regime mismatch
                    rather than by detector behaviour, and no false-alarm rate
                    should be read as a property of the EWMA design until this
                    is separated.
Design tension:     PROJECT.md §13 builds the healthy population above a 50 kW
                    floor; PROJECT.md §14 requires the TEST partition to stay
                    unfiltered because anomalous rows there are the signal.
                    Neither section anticipates the other, and this measurement
                    is the size of the gap between them.
Affected RQ(s):     RQ1 (what the unfiltered-period metrics measure), RQ2 (every
                    false-alarm and detection claim), RQ3 (alert volume and the
                    direction of what is alerted on)
Mitigation status:  PARTIALLY MITIGATED (2026-08-19, ADR-047) — option (a) is
                    IMPLEMENTED. Three candidates were named, all
                    methodological and therefore reserved to the author:
                    (a) report detection results SPLIT by in-regime and
                        out-of-regime rows — no new modelling, immediate.
                        **DONE**: `app/evaluation/regime.py` and
                        `scripts/run_regime_split.py` produce
                        `evaluation/regime_split.json`. See ADR-047 for the
                        measured split and LIM-035 for the one hypothesis it
                        refuted.
                    (b) gate detection on operating state, which PROJECT.md §14
                        arguably forbids and which therefore needs a ruling.
                        STILL OPEN — not taken; it remains the author's call.
                    (c) model the parked/idling regime explicitly rather than
                        excluding it, which is a scope extension. STILL OPEN.
                    WHAT (a) DELIVERED: the RQ1 ordering is confirmed to hold
                    in-regime, the unfiltered-slice Diebold-Mariano reversal is
                    explained (92.6% of the thesis model's test-slice squared
                    error comes from 17.9% of rows outside its support), and
                    the direction asymmetry is now measured — out-of-regime
                    low:high 8.9:1 against in-regime 1.9:1.
                    WHAT (a) DID NOT DELIVER, against expectation: it does not
                    reduce the in-control false-alarm inflation and cannot. See
                    LIM-024 and ADR-047 Consequence 3 — the in-control block is
                    already in-regime by construction, so the aspiration
                    recorded here on 2026-08-18, that (a) "would let every RQ2
                    number be restated as a property of the detector", was
                    OVERSTATED. It restates the TEST-stream figures; the
                    in-control rate is untouched and belongs to ADR-034.
Source:             `artifacts/EXP-20260818-001/evaluation/condition_diagnostics.json`
                    and `plots/*_residual_vs_active_power.png` (ADR-045); band
                    aggregation of `residuals/test.parquet` joined to
                    `evaluation/conditions.parquet`, 2026-08-18. Mitigation (a):
                    `evaluation/regime_split.json` (ADR-047), 2026-08-19.

## LIM-035 — The Chesterman dual-criterion reframing does not survive the regime split

Date discovered:    2026-08-19
Description:        NEGATIVE FINDING, recorded because it refutes a claim this
                    project was about to make.
                    Chesterman et al. (Wind Energy Science 8(6):893, 2023)
                    evaluate a normal behaviour model on TWO things at once:
                    small prediction error on healthy data and LARGE error on
                    unhealthy data, reported as the difference. Under that
                    criterion the thesis model appeared to win the very
                    comparison plain RMSE says it loses — the 0/6 unfiltered
                    -slice Diebold-Mariano reversal — because its pooled
                    separation is by far the largest:

                      pooled (NOT citable)      bearing      oil
                      thesis                    +11.3149   +6.9669
                      elastic_net                +5.9097   +5.4680
                      baseline (OLS)             +5.6422   +4.9358

                    Computed correctly — WITHIN the fitted operating regime,
                    per ADR-047, so that "unhealthy" means degraded rather than
                    parked — the ordering REVERSES and the thesis model comes
                    LAST on both targets:

                      in-regime (citable)       bearing      oil
                      baseline (OLS)             +0.2323   +0.1884
                      elastic_net                +0.2250   +0.1624
                      thesis                     +0.1854   +0.0552

                    The pooled advantage was entirely an artefact of
                    extrapolation. The thesis model's larger separation was not
                    greater sensitivity to abnormal behaviour; it was greater
                    failure on rows below the training floor, which make up
                    65.7% of the "unhealthy" complement (132,906 of 202,418
                    rows).
Consequence:        the dual-criterion reframing must NOT be used to answer the
                    unfiltered-slice reversal. The defensible answer to that
                    reversal is ADR-047 Consequence 1 — the RQ1 ordering holds
                    in-regime, and 92.6% of the thesis model's test-slice
                    squared error comes from 17.9% of rows outside its support.
                    A separate reading also stands on its own: on this dataset
                    a linear reference separates healthy from unhealthy
                    behaviour marginally BETTER than the tuned NBM, which is a
                    real limitation of the thesis model for detection use and
                    is consistent with LIM-031 (the fleet-median-only detector
                    competing) and with the B3 arm.
Affected RQ(s):     RQ1 (how the unfiltered-slice result is explained), RQ2
                    (the NBM's value for detection specifically)
Mitigation status:  NOT MITIGABLE — it is a measurement, not a defect. Recorded
                    so the pooled figure cannot be cited by mistake; the
                    artifact retains it only under the key
                    `pooled_uncorrected` with an explicit warning string.
Source:             `artifacts/EXP-20260818-001/evaluation/regime_split.json`,
                    key `separation_delta_pe`; ADR-047.

## LIM-036 — The single labelled event belongs to the one failure mode this project's own literature review calls non-thermal

Date discovered:    2026-08-19
Description:        FINDING. EVENT-001 (ADR-013) is code 1860, "Oil filter gear
                    choked" — a lubrication-system restriction, recorded as a
                    Warning, with no maintenance confirmation available
                    (LIM-002: the Comment column is empty in 0 of 57,515 rows,
                    so the mechanism-level tier is unconstructible).
                    Chapter 2's own Table 2.4 classifies the five monitorable
                    gearbox failure modes. For "Lubrication system
                    degradation" it records the documented evidence as
                    "Mechanism documented; DIRECT SIGNALS NOT THERMAL", and the
                    signals per published practice as "Oil condition
                    indicators". Chapter 2 Table 2.5 maps the same mode to the
                    SCADA signals "Oil pressure level; oil-filter status", with
                    no CMS signal.
                    This project models exactly two thermal channels. The one
                    labelled event it possesses therefore belongs to the one
                    failure mode its own literature review states is not
                    thermally monitorable.
                    The FMEA layer's behaviour is consistent with that: the
                    rule that describes this mechanism, FMEA-004
                    (`lubrication_system_degradation`), requires oil HIGH AND
                    bearing HIGH. The matched detection is bearing LOW (EWMA
                    -1.24) with oil normal (EWMA -1.23), and the interpreter
                    recorded "No candidate mechanism: the anomalous pattern
                    matched no FMEA rule."
Why this matters:   it is a stronger and more citable explanation for the RQ3
                    outcome than LIM-026's direction finding alone. LIM-026
                    records THAT the match points the wrong way; this records
                    WHY the channels could not have seen the mechanism in the
                    first place. It also bears on the RQ3 framing choice:
                    implementing lag and load-slope features so the FMEA
                    qualifiers become computable would be building
                    discrimination for a mechanism the review says thermal
                    channels cannot resolve.
Affected RQ(s):     RQ3 (primary), RQ2 (what the single event can validate)
Mitigation status:  OPEN — reserved to the author. It is a scope/framing
                    question (PROJECT.md §34), not a code defect. The candidate
                    it most supports is reframing RQ3 as an architecture
                    demonstration with the discrimination gap stated, which
                    METHODOLOGY_REVIEW.md already lists as one of two honest
                    exits.
Source:             `backend/app/evaluation/events.py` EVENT_001 (code 1860,
                    "Oil filter gear choked"); `mokhles_docs/Chapter_2_draft.docx`
                    Tables 2.4 and 2.5; `backend/app/fmea/rulesets/initial_v1.yaml`
                    FMEA-004; `artifacts/EXP-20260818-001/evaluation/event001_diagnostic.txt`.

## LIM-037 — The manufactured mode orthogonality collapses on the monitoring stream

Date discovered:    2026-08-19
Description:        FINDING, from the ADR-035 orthogonal-mode arm
                    (`--arms orthogonal`, base EXP-20260818-001), executed on
                    author instruction 2026-08-19.
                    Where the standardization statistics come from, the
                    rotation behaves exactly as ADR-035 recorded IN ADVANCE:
                    corr(common, differential) = 9.1e-17 on training (machine
                    zero) and -0.065 on healthy validation; sd(common) 1.390
                    and sd(differential) 0.261 against the predicted
                    sqrt(1±r) identities; variance share 96.6% / 3.4%; lag-1
                    phi 0.78 / 0.53.
                    On the MONITORING stream the orthogonality is gone: the
                    two modes correlate at r = 0.835, both dispersions
                    inflate (sd 4.00 and 1.08 against 1.47 and 0.27 on
                    validation), and both modes become almost perfectly
                    persistent (lag-1 0.963 / 0.960). A rotation with
                    training-frozen coefficients diagonalizes only the
                    covariance it was fitted to; the monitoring stream's
                    out-of-regime variance (LIM-034: 17.9% of rows below the
                    training power floor carrying 50.4% of the residual
                    variance) loads on both modes and re-correlates them.
Why this matters:   the rotation was the one quantity ADR-035 identified as
                    able to supply the independent evidence RQ2's
                    coordination premise requires. The arm shows it supplies
                    that independence IN-CONTROL — where the coordination
                    rule now demonstrably does work: 2-of-2 over the modes
                    reaches the 10 FA/turbine-year rung at multiplier 4.54
                    against 12.62 for 1-of-2, where the raw channels gave
                    10.76 against 12.96, nearly indistinguishable — but NOT
                    on the stream where detection actually happens.
                    Independent-evidence coordination on this dataset is a
                    healthy-regime property, not a monitoring property.
                    Secondary observations: pooled in-control inflation is
                    slightly worse for the modes (67.7x) than for the raw
                    channels (60.1x) on the identical validation block, and
                    every pipeline containing the differential mode never
                    reaches zero false alarms even at multiplier 40
                    (0.76 FA/ty) — heavy-tailed bearing-vs-oil divergences
                    survive any credible limit (unscreened predictor/target
                    artefacts, LIM-018, are a candidate explanation).
Affected RQ(s):     RQ2 (the coordination-premise repair), RQ3 (the
                    differential mode is the only discriminating quantity
                    LIM-030 identified)
Mitigation status:  OPEN. The candidate follow-up is the ADR-047 regime
                    split applied to the mode statistics: if the monitoring
                    mode correlation is low in-regime and high out-of-regime,
                    the collapse is one more consequence of LIM-034 and the
                    in-regime slice could still carry an independent-evidence
                    comparison. Not run; reserved to the author.
Source:             `artifacts/EXP-20260818-001/evaluation/robustness_suite.json`,
                    arm `orthogonal`, 2026-08-19. ADR-035 binding conditions
                    (a)-(d) honoured; detection value UNTESTED by declaration
                    (condition c).
