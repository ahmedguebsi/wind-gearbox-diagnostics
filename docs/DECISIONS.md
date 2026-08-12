# DECISIONS.md — Architecture/Methodology Decision Record (ADR) Log

Every open methodological decision gets an entry: status (OPEN / CLOSED),
options, evidence required to close it, and — when closed — the Chapter 3
justification. Closing an item without recording the justification is
prohibited (PROJECT.md §34).

Entry template:

```text
## ADR-NNN — <title>
Status:            OPEN | CLOSED (<date>)
Question:          <the decision to make>
Options:           <enumerated options>
Evidence to close: <what real data / Chapter 3 analysis is required>
Decision:          <filled when CLOSED>
Justification:     <Chapter 3 reference / literature citation when CLOSED>
Affected modules:  <M-xx IDs>
```

---

## ADR-001 — Source partition for normalization/threshold statistics

Status:            OPEN
Question:          Are residual-normalization and threshold statistics fitted
                   on the healthy TRAINING block (v1.0 default) or the healthy
                   VALIDATION block (panel-reviewer recommendation, avoiding
                   in-sample optimism from training residuals being biased
                   small)? (PROJECT.md §22; MIGRATION_LOG.md G1; risk R6.)
Options:           training | validation
Evidence to close: Comparison of in-control false-alarm behaviour under both
                   settings on real healthy Kelmarsh data; Chapter 3 argument.
Decision:          —
Justification:     —
Affected modules:  M-19b (normalizers), M-20 (EWMA limits), M-03 (config enum
                   `threshold_stats_source`, default `training` pending closure)

## ADR-002 — Model set: thesis model and its single baseline

Status:            CLOSED (2026-08-11) — decision queue D-02
Question:          Which baseline NBM(s) contextualise RQ1 accuracy?
Options considered: Random Forest + an ANN/ANFIS-style literature baseline
                   (PROJECT.md §18 as written); a single linear reference.
Decision:          Author ruling (2026-08-11), REVISED from the proposal.
                   Exactly TWO models, no multi-model comparison:
                   - XGBoost multi-target NBM        → model_kind THESIS
                   - Multiple linear regression on the same exogenous
                     predictors                       → model_kind BASELINE
                   Random Forest is dropped. The proposed MLP/ANN baseline is
                   dropped.
Justification:     The baseline contextualises RQ1 accuracy: it establishes
                   how much thermal variance is linear in operating
                   conditions versus captured non-linearly, and thereby
                   indicates how much residual spread is irreducible physics
                   rather than modelling error. It is a measuring stick for
                   residual trustworthiness, not a model competition. Linear
                   regression is the minimal reference that does this — no
                   hyperparameters and no architecture decisions, so nothing
                   about the comparison is tunable after the fact.
Why Bangalore & Tjernberg (2015) was NOT reimplemented (examiners may ask):
                   that paper's ANN NBM is a NARX formulation, feeding lagged
                   values of the target temperature back as model inputs.
                   Guard 8 (LOCKED-06) prohibits target-derived features,
                   because an autoregressive NBM tracks its own target
                   through slow fault-driven drift and suppresses the very
                   residual signal this thesis detects — the concern Chapter 2
                   §2.4 evidences (Felgueira et al., 2019; Wang et al., 2018).
                   Reimplementing it faithfully would violate the lock;
                   reimplementing it without the lagged terms would no longer
                   be that paper's model. It is therefore cited as
                   motivating precedent, not reproduced as a comparator.
Deviation noted:   PROJECT.md §18 as written lists Random Forest plus one
                   literature-anchored baseline. This ruling supersedes that
                   text. No LOCKED constraint is affected (LOCKED-01 fixes
                   only that XGBoost is THE thesis model and others are
                   comparators). Reported to the author, not silently
                   resolved; PROJECT.md §18 is the author's to amend.
                   IMPLEMENTATION_PLAN.md M-17 updated accordingly.
Affected modules:  M-17 (rewritten: one BASELINE, linear regression);
                   M-16 unchanged; M-28 comparison tables (two models only).

## ADR-003 — LightGBM as an optional later comparator

Status:            CLOSED (2026-08-11) — decision queue D-03
Question:          Is a LightGBM comparator added alongside the baseline?
                   Permitted only with ADR justification (PROJECT.md §5).
Options:           add | omit
Decision:          OMIT (author ruling, 2026-08-11).
Justification:     Chapters 1–2 identify no RQ1 need the two-model set cannot
                   meet, and ADR-002 establishes that the baseline exists as
                   a measuring stick rather than a competition. Adding a
                   third model would widen the multiple-comparison surface
                   (risk R9) for no evidential gain.
Affected modules:  none (M-17 remains a single BASELINE model).

## ADR-009 — Modelling data span

Status:            CLOSED (2026-08-11)
Question:          Which period of the Kelmarsh holdings is used?
Decision:          Author ruling (2026-08-11): **2016-05-03 to 2021-06-30**,
                   all six turbines, everything in between. Year folders
                   2016–2021 are treated uniformly, with no special handling
                   for any of them.
Justification:     The pre-May-2016 period is excluded because the gear-oil
                   thermal channels are empty there — 100% null from the 2016
                   file start until 2016-05-03 09:40 on every turbine
                   (LIM-005). This is a **stated data constraint, not a
                   selection**: there is no thermal signal to model or
                   monitor before that date, so the boundary is imposed by
                   the data rather than chosen among alternatives.
Consequence:       The span covers five seasonal cycles, which clears the
                   PROJECT.md §14 seasonal-coverage WARNING (training windows
                   drawn from it can exceed 12 months and span all calendar
                   months). LIM-004's twelve-month concern is retired;
                   LIM-007's uneven-holdings note stands for the 2021 half
                   year at the end of the span.
Affected modules:  M-09 (ingestion span filter), M-13 (splitting), M-12
                   (healthy-state population).

## ADR-010 — Split constraint: the 2019 code-1860 window is TEST

Status:            CLOSED (2026-08-11) — recorded BEFORE any split is computed
Question:          Where must the chronological split place the code-1860
                   occurrences (Kelmarsh 1, 2019)?
Decision:          Author ruling (2026-08-11): the chronological split must
                   place the 1860 event in the **TEST/monitoring period**,
                   with healthy training data preceding it.
Justification:     Recorded in advance so the split is documented as a stated
                   design constraint rather than reconstructed after results
                   exist. It is the only gearbox-indexed candidate in the
                   holdings with usable preceding thermal coverage (median
                   798 h, max 1,848 h of continuous covered SCADA before its
                   occurrences), so a split placing it in training would
                   leave no candidate monitoring target at all.
Scope note:        This constrains split *placement* only. It is NOT a
                   designation: code 1860 is a filter-restriction alarm, not
                   maintenance-verified gearbox damage, and what it
                   represents remains open under D-04.
Guard interaction: Chronological ordering (LOCKED-04) is unaffected — the
                   constraint fixes which side of the boundary the window
                   falls on, never the ordering itself.
Affected modules:  M-13 (split configuration), M-27 (evaluation targets).

## ADR-011 — Author-derived files excluded from census reading

Status:            CLOSED (2026-08-11)
Question:          How are the non-source files found in the export folders
                   treated?
Decision:          Author confirmation (2026-08-11). Classified
                   EXCLUDED_AUTHOR_DERIVED — inventoried and hashed for
                   provenance, never read:
                   `DATA_DICTIONARY_2020.csv`,
                   `DATA_DICTIONARY_Turbine_5.csv`, `Untitled-1.txt`.
                   The `.venv`, `.venv-1` and `.vscode` directories in the
                   2016 folder are development artefacts: counted and
                   reported in aggregate, never itemised, hashed, or read.
Justification:     These are the author's own derived outputs, not Cubico
                   source data; reading them would risk circulating derived
                   numbers as if they were source facts.
Affected modules:  `scripts/dataset_census.py` (`classify`,
                   `is_environment_noise`).

## ADR-008 — Initial FMEA rule base

Status:            CLOSED (2026-08-11) — decision queue D-01
Question:          Which residual-pattern → candidate-mechanism rules does
                   the interpretation layer ship with? (PROJECT.md §26;
                   Chapter 2 §2.7 states Chapter 3 formalises the Table 2.3
                   signatures into an operational rule base.)
Decision:          ACCEPTED as proposed (author ruling, 2026-08-11).
                   Formalise Chapter 2 Table 2.3's five patterns as the
                   initial YAML rule base, every rule `validated: false`:
                   1. Gear-teeth wear — sustained positive, load-dependent
                      oil-temperature residual; bearing residuals rising in
                      lag (Qiu et al., 2016; Qiu et al., 2014).
                   2. HSS bearing failure — bearing residual leads; oil
                      residual smaller and later (Bangalore & Tjernberg,
                      2015; Qiu et al., 2014).
                   3. LSS/planetary bearing failure — LSS bearing residual
                      leading where instrumented, else weak oil-only
                      signature (Qiu et al., 2014).
                   4. Lubrication-system degradation — broad simultaneous
                      positive residuals across oil and bearing channels
                      (Qiu et al., 2014; Shafiee & Dinmohammadi, 2014).
                   5. Electrical/generator-side influence — generator-side
                      residuals without gearbox-led ordering; exclusion
                      pattern (Qiu et al., 2016).
Mandatory caveat:  every rule's rationale carries the overlap caveat — three
                   of five gearbox failure modes share the oil-temperature
                   signature (Feng et al., 2013) — so differentiation rests
                   on the coordinated pattern, never a single residual.
Justification:     Chapter 2 assembles these signatures from published
                   failure-mode knowledge and drivetrain thermophysics; they
                   are the literature seed the thesis positions itself on.
                   `validated: false` until each rule's ADR-005 sign-off
                   cites its specific source; outputs stay plausibility-
                   graded hypotheses (Chapter 1 §1.5 scope boundary).
Affected modules:  M-25 (rule base), M-26 (interpreter).
Dependency note:   which of the five rules are instantiable depends on the
                   channels the final dataset provides (census evidence) —
                   subsetting is a mapping/config matter, not a change to
                   this decision.

## ADR-004 — Canonical schema version log

Status:            OPEN (standing log)
Question:          Standing record of `schema_version` bumps (semver) required
                   by PROJECT.md §8. Each schema change appends an entry here
                   with its rationale.
Current version:   1.2.0 (stamped by M-06 `app/data/schema.py`)
Version log:
  - 1.0.0 (2026-08-11) initial canonical schema: structural variables, the
    thesis-identified upstream predictors, and the two required thermal
    targets.
  - 1.1.0 (2026-08-11) added `plausible_range` to `CanonicalVariable`, so a
    variable's physically impossible bounds are declared alongside the
    variable itself rather than duplicated inside the validation layer.
    Minor bump: additive, no variable renamed or removed. Detected by the
    pinned schema-hash drift test, which is what that test exists for.
  - 1.2.0 (2026-08-12) recorded the ADR-012 target designation in the
    variable descriptions: `gearbox_bearing_temperature` is the rear
    (high-speed-shaft-side) gearbox bearing — the raw Kelmarsh column
    assignment lives in the M-07 mapping config, never in the schema — and
    `gearbox_oil_temperature` notes the ADR-012 exclusion of oil-inlet
    temperature as a target. Minor bump: descriptive only, no variable
    renamed, added, or removed.
Affected modules:  M-06, M-07, M-10 (RangeRule reads bounds from the schema),
                   M-29

## ADR-005 — FMEA rule sign-off log

Status:            OPEN (standing log)
Question:          Standing record of FMEA rule validations (Guard 7). A rule's
                   `validated` flag flips to true only through an entry here
                   citing the specific literature source (PROJECT.md §26).
                   Never invent references.
Entries:           none yet
Affected modules:  M-25, M-26

## ADR-006 — Chapter 1 Objective 2 conflict (MAPE + SHAP)

Status:            CLOSED (2026-08-11)
Question:          Chapter 1 as drafted (Objective 2) names MAPE among the NBM
                   accuracy metrics and SHAP-based explainability for physical
                   credibility. Both conflict with PROJECT.md v2.0 (§19 metric
                   set; LOCKED-07 SHAP prohibition).
Options:           follow Chapter 1 as drafted | follow LOCKED-01…10
Decision:          PROJECT.md v2.0 LOCKED-01…10 is authoritative (author
                   ruling, 2026-08-11). Chapter 1 predates the panel review;
                   its Objective 2 wording will be corrected by the author
                   separately. All code and specs build against the locks:
                   - Metrics: RMSE, MAE, R², bias. NO MAPE anywhere (M-18
                     acceptance criteria stand: MetricSet exposes exactly
                     these four fields).
                   - NO SHAP, no XAI, no attribution module, no shap
                     dependency. Physical credibility comes from causal
                     predictor separation (M-14) and condition-sliced error
                     diagnostics (M-18).
                   - RQ1 model is multi-target XGBoost (M-16).
                   - RQ2 comparisons route through matched-FPR only (M-23).
Justification:     Celsius is an interval scale, so MAPE has no meaningful
                   zero; SHAP explains the prediction, not the residual, and
                   the residual is the diagnostic signal. Chapter 2's own
                   review supports the SHAP exclusion: attribution identifies
                   influential inputs, not physical mechanisms.
Affected modules:  M-14, M-16, M-18, M-23
Process note:      Thesis chapters are never edited, rewritten, or patched
                   from this repository. Chapter/spec conflicts are logged
                   here and reported — never silently resolved (PROJECT.md
                   preamble; LOCKED-09 register discipline applies to all
                   user-facing text).
Source text read:  "Chapter 1 Introduction.docx" (SHA-256 prefix c01b9cc5d268,
                   2026-07-27) — identical copies in Thesis\Code and
                   Thesis\AI project files\Chapter 1 papers.

## ADR-007 — Canonical thesis source files

Status:            CLOSED (2026-08-11)
Question:          Multiple copies/variants of Chapters 1 and 2 existed with
                   misleading names ("updated", "FINAL_integrated"). Which
                   files are the canonical thesis text for all software and
                   requirements work?
Decision:          Author confirmation (2026-08-11). Canonical files:
                   - Chapter 1: "Chapter 1 Introduction.docx" (2026-07-27)
                     SHA-256 c01b9cc5d268684100095f069ad97953
                             f0ad57b511a2a3fd9840ab029a846da4
                   - Chapter 2: "Chapter_2_draft.docx" (2026-07-29 20:47)
                     SHA-256 6510fa47df560b3870f141deb1935a01
                             eabb5f5f695afa7819fc7fb991e4ddfb
                   "Chapter1_updated_sections.docx" and
                   "Chapter_2_FINAL_integrated.docx" are OLDER variants being
                   archived by the author — do not read them again.
Justification:     Hash comparison showed the Thesis\Code and AI-project-file
                   copies of each canonical file are byte-identical; the
                   misleadingly named variants predate them.
Affected:          docs/THESIS_REQUIREMENTS.md source references; any future
                   chapter reading. Chapter 3 does not exist yet; its
                   decision content is tracked in
                   docs/CHAPTER3_DECISION_QUEUE.md.

## ADR-012 — Thermal target designation: bearing channel and oil-inlet exclusion

Status:            CLOSED (2026-08-12) — resolves LIM-001
Question:          Which physical channels are the two required thermal
                   targets (PROJECT.md §8), given that no Kelmarsh column is
                   named as a gearbox bearing temperature (LIM-001)?
Options:           Bearing target: Rear bearing temperature | Front bearing
                   temperature | Rotor bearing temp. Oil side: sump oil only
                   | sump oil + oil inlet.
Decision:          Author ruling (2026-08-12). The two targets are:
                   - gearbox_oil_temperature     ← "Gear oil temperature"
                   - gearbox_bearing_temperature ← "Rear bearing temperature"
Justification:     The power-bin correlation structure, not the overall
                   correlation, is the deciding evidence
                   (docs/evidence/EVIDENCE_D04_AND_TARGETS.json). Rear
                   bearing maintains 0.88–0.98 correlation with gear oil
                   across every power bin. Front bearing collapses from 0.99
                   at idle to 0.06 above 1500 kW — at rated power, where
                   gearbox thermal faults matter most, it carries essentially
                   no relationship to oil temperature and is evidently
                   measuring a different thermal node.
                   Gear oil inlet temperature is EXCLUDED as a target: it
                   correlates −0.42 with active power and falls monotonically
                   from 53.4 °C to 39.3 °C as load rises while sump oil stays
                   flat — a cooling-system response, not gearbox thermal
                   state, moving inversely to the quantity of interest. It is
                   not setpoint-controlled, but is disqualified on physical
                   grounds.
Affected modules:  M-06 (schema 1.2.0 designation notes — see ADR-004 log),
                   M-07 (the Kelmarsh mapping config assigns the designated
                   raw columns when authored), M-16/M-17 (target set),
                   M-22 (coordinated state vector), M-25 (rule signatures).
LIM-001:           mitigation status updated to MITIGATED.

## ADR-013 — Ground-truth definition and tiering

Status:            CLOSED (2026-08-12) — decision queue D-04
Question:          What counts as a labelled gearbox event, and how is
                   anomaly-detection ground truth separated from
                   mechanism-level ground truth? (PROJECT.md §27.1, §7.5;
                   queue D-04.)
Options:           status-code-derived events only; status codes qualified by
                   duration/severity criteria; maintenance-confirmed events
                   only; two-tier structure per record type.
Decision:          Author ruling (2026-08-12).
                   (a) Events are STATUS-CODE-DERIVED, qualified by duration
                       and preceding-thermal-coverage criteria.
                   (b) Tier: ALARM-LEVEL ONLY throughout. This dataset
                       contains no maintenance-confirmed events (LIM-002), so
                       mechanism-level ground truth is unavailable and no
                       claim of confirmed failure appears anywhere in the
                       evidence chain.
                   (c) Designated event: EVENT-001 — code 1860 "Oil filter
                       gear choked", Kelmarsh 1, 2019-02-24 16:46:28 to
                       2019-05-30 07:34:04. ONE event, not three: the
                       occurrences are separated by 4.9 and 7.45 days across
                       a 95-day span with the alarm active ~82 days — a
                       single continuous degradation episode with brief
                       clearances.
                   (d) All other gearbox-indexed candidates are EXCLUDED for
                       zero preceding thermal coverage (LIM-005): the
                       gear-oil channels are empty before 2016-05-03 and
                       every 2016 gearbox occurrence falls inside that
                       window.
Justification:     LIM-002 (no maintenance free text anywhere in the
                   exports), LIM-003 (sparse gearbox-code coverage), LIM-005
                   (zero preceding thermal coverage for the 2016 candidates),
                   and the occurrence structure recorded in
                   docs/evidence/EVIDENCE_D04_AND_TARGETS.json. Recorded
                   BEFORE any model was fitted.
Consistency:       ADR-010 stands — the chronological split places EVENT-001
                   in TEST. Its scope note ("what 1860 represents remains
                   open under D-04") is resolved by this entry: code 1860 is
                   and remains a filter-restriction alarm; the ground-truth
                   tier is alarm-level, never mechanism-level.
Affected modules:  M-24 (tier tags — alarm-level is the only reachable tier
                   for this dataset), M-27 (event set), M-13 (split
                   constraint via ADR-010); unblocks D-05 and D-06.

## ADR-014 — Evaluation design: DESCRIPTIVE CASE STUDY

Status:            CLOSED (2026-08-12) — decision queue D-05
Question:          The pre-committed Phase 0.5 decision rule (PROJECT.md
                   §7.5, §27.2): ≥2 independent labelled gearbox events →
                   quantitative event-based evaluation; <2 → descriptive
                   case-study design.
Decision:          ONE labelled event (EVENT-001, ADR-013) < 2, so the rule
                   selects the DESCRIPTIVE branch (author ruling,
                   2026-08-12). `inferential_allowed = false` in M-27. No
                   inferential detection-rate or lead-time population claims
                   anywhere in the thesis evidence chain.
                   The matched-FPR operating curves on healthy data (M-23)
                   remain fully quantitative and are the primary RQ2
                   evidence; EVENT-001 is the qualitative case study,
                   structured by the matched-FPR framework per PROJECT.md
                   §25.
                   Case-study analysis focuses on the ONSET of occurrence 1;
                   occurrences 2–3 are reported as continuation, not as
                   independent evidence (occurrence 3 coincides with abnormal
                   operation — LIM-008).
Justification:     The decision rule was fixed in PROJECT.md §7.5 before any
                   results existed; the census event count selects the branch
                   mechanically. Closing this BEFORE any model is fitted is
                   the entire point of the Phase 0.5 gate.
Affected modules:  M-27 (`inferential_allowed` gating), M-23 (curves remain
                   quantitative), M-28 (claim phrasing in tables),
                   LIMITATIONS.md (LIM-008 small-n / data-quality entries).

## ADR-015 — Phase 0.5 dataset due-diligence gate: APPROVED

Status:            CLOSED (2026-08-12)
Question:          May modelling-adjacent work (healthy-state construction
                   onward) proceed past the Phase 0.5 gate (PROJECT.md §7.5)?
Decision:          APPROVED by the author (2026-08-12).
Justification:     The census is complete and its evidence is on file
                   (docs/evidence/KELMARSH_2020_CENSUS.json,
                   KELMARSH_STATUS_VOCABULARY_2016_2021.json,
                   EVIDENCE_D04_AND_TARGETS.json); D-04 and D-05 are closed
                   with recorded justifications (ADR-013, ADR-014); and the
                   evaluation design was pre-committed before any model was
                   fitted, which is what the gate exists to guarantee. The
                   modelling data span is fixed by ADR-009 (2016-05-03 to
                   2021-06-30, all six turbines; the pre-May-2016 exclusion
                   is a stated data constraint, not a selection).
Affected modules:  the block on modelling-adjacent work is lifted; build
                   proceeds M-14 → M-29/M-30/M-31 → M-15…M-20 per
                   IMPLEMENTATION_PLAN.md §22.

## ADR-016 — RQ2 success criterion, pre-specified

Status:            CLOSED (2026-08-12) — recorded BEFORE any matched-FPR
                   comparison output exists (M-23 is built; no comparison
                   has been run on real data).
Question:          By what pre-committed criterion is the coordinated
                   multi-target pipeline judged to provide more useful
                   diagnostic evidence than single-signal monitoring (RQ2,
                   PROJECT.md §25)? Unspecified until now; an examiner will
                   ask which criterion was committed in advance.
Decision:          Author ruling (2026-08-12).
                   PRIMARY criterion (quantitative, healthy data only):
                   at matched false-alarm operating points across the swept
                   range, the coordinated pipeline is considered to provide
                   more informative diagnostic evidence if it produces
                   fewer isolated single-signal excursions while retaining
                   equivalent sensitivity to sustained coordinated
                   deviations. Reported as FULL operating curves (M-23
                   already refuses to emit matched points without them),
                   never a single point.
                   SECONDARY criterion (descriptive, EVENT-001 only):
                   whether the coordinated pipeline's first persistent
                   exceedance precedes the code-1860 alarm, and by how much
                   — reported as two timestamps and their difference. A
                   factual observation about one episode, not a capability
                   claim. `inferential_allowed` remains false per ADR-014.
                   EXPLICITLY NOT CRITERIA (deliberate, dated exclusions —
                   not gaps): detection rate across events, and mean lead
                   time. Both require multiple independent labelled events
                   and are unavailable in this dataset (ADR-013: the
                   labelled event set is exactly {EVENT-001}; ADR-014
                   selected the descriptive branch accordingly).
Justification:     Pre-specifying the success criterion before any
                   comparison output exists is what makes the RQ2 answer
                   evidence rather than post-hoc selection — the same
                   discipline the Phase 0.5 gate applied to the evaluation
                   design (ADR-014). The primary criterion is measurable on
                   healthy data alone, so it stays fully quantitative under
                   the descriptive-branch constraint; the secondary
                   criterion is scoped to what one episode can honestly
                   support.
Affected modules:  M-23 (comparison outputs are judged against this
                   criterion; full curves mandatory), M-27 (EVENT-001
                   timestamps; `inferential_allowed` gating), M-28 (claim
                   phrasing in tables), thesis Chapters 3 and 5.

## ADR-017 — Event-matching window

Status:            CLOSED (2026-08-12) — decision queue D-06
Question:          How is a detection matched to a known event: window
                   length before the event, persistence qualification for
                   "first detection", per-type windows? (PROJECT.md §27.2;
                   queue D-06.)
Decision:          Author ruling (2026-08-12).
                   (a) WINDOW: 14 days preceding the event start timestamp.
                       A detection matches EVENT-001 if its first
                       persistent exceedance falls within
                       [event_start − 14 days, event_start].
                   (b) PERSISTENCE QUALIFICATION: a detection qualifies
                       only if the exceedance is sustained per the
                       configured EWMA persistence criterion — isolated
                       single-sample crossings do not count as detections.
                   (c) GRID ALIGNMENT: detections resolve to the 10-minute
                       SCADA grid while event timestamps are
                       second-resolution; lead times are therefore
                       quantised to 10 minutes and are reported as such.
                   (d) SENSITIVITY: 14 days is provisional-marked. The
                       M-27 sensitivity suite sweeps it (7 / 14 / 30 days)
                       and reports whether the EVENT-001 case-study
                       conclusion is stable across that range.
Justification:     From the D-06 census evidence (docs/evidence/
                   KELMARSH_STATUS_VOCABULARY_2016_2021.*,
                   EVIDENCE_D04_AND_TARGETS.json):
                   - occurrence 1 has 798.3 h (33.3 days) of continuous
                     covered SCADA before onset, so a 14-day window sits
                     well inside available coverage;
                   - the nearest unrelated long disturbance is the icing
                     pair (codes 6682/6690, 2019-02-03, 9.7 h) 9 days
                     before onset; a window beyond ~14 days would begin
                     capturing it, conflating icing thermal response with
                     lubrication degradation (confounder logged as
                     LIM-010);
                   - median preceding coverage across all 6,930
                     Stop/Warning rows is 222.8 h (9.3 days), so 14 days
                     is generous relative to typical event spacing without
                     being unbounded.
Affected modules:  M-27 (event matching, lead-time computation,
                   `event_match_window_days` config with provisional
                   marker; sensitivity grid 7/14/30), M-23 (event columns
                   attach at matched operating points via M-27),
                   LIMITATIONS.md (LIM-010).
