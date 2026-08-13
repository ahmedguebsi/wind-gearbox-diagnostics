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
Current version:   1.3.0 (stamped by M-06 `app/data/schema.py`)
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
  - 1.3.0 (2026-08-13) ADR-020 widened `generator_speed` plausible_range
    from (−1, 5000) to (−5, 5000): sensor jitter around zero on parked
    turbines — 2,621 flagged rows in (−10, −1], overwhelmingly (−2, −1],
    across all six machines and all six years — is routine, not physically
    impossible, so the −1 bound mis-stated the schema's own claim. Minor
    bump: one variable's bounds changed; nothing renamed, added, or
    removed. Caught by the pinned schema-hash drift test and re-pinned
    with this entry. The Kelmarsh mapping config's declared version
    follows; its column assignments are unchanged from the approved 1.2.0
    mapping.
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
Operationalisation (author ruling 2026-08-13, recorded BEFORE the first
matched-FPR sweep ran):
                   An "isolated excursion" is an alarm episode shorter
                   than the ADR-017(b) persistence qualification
                   (persistence_min_samples = 3); a "sustained episode"
                   is an episode of >= 3 consecutive samples. The PRIMARY
                   criterion is met at a matched operating point if BOTH
                   hold:
                   (a) the coordinated pipeline's isolated-excursion
                       count is lower than single_union's, AND
                   (b) the coordinated pipeline's sustained-episode count
                       is within ±20% of single_union's.
                   If (a) holds but (b) fails, the result is reported as
                   "fewer isolated excursions at reduced sustained
                   sensitivity" — a trade-off, not a criterion met. If
                   (a) fails, the criterion is not met. The verdict is
                   reported PER MATCHED POINT PER LAMBDA, never
                   aggregated to a single yes/no.
                   Interpretability condition: coordinated detection
                   requires simultaneous breach on both targets, so it
                   mechanically produces fewer episodes of every kind at
                   any fixed multiplier — the comparison only means
                   something if the matching is exact. Each matched point
                   therefore reports the ACHIEVED false-alarm rate of
                   both pipelines alongside the target, and any pair
                   whose achieved rates differ by more than 5% (relative
                   to the larger) is labelled NOT INTERPRETABLE rather
                   than read as a result.
                   Baseline: "single-signal monitoring" is operationalised
                   as single_union (alarm when either target's stream
                   exceeds — coordination threshold 1 of 2), the
                   operational meaning of monitoring each signal
                   independently; per-target curves are reported as
                   context. FPR target ladder: {200, 100, 50, 20, 10, 5,
                   2, 1, 0.5} false-alarm episodes per turbine-year,
                   measured on the healthy validation block; sub-1/yr
                   rungs are reported with their single-event resolution
                   stated rather than omitted.
Outcome (2026-08-13, EXP-20260813-002 matched-FPR sweep — author-accepted
as the RQ2 answer):
                   The pre-registered PRIMARY criterion is PREDOMINANTLY
                   NOT MET. Of 24 reachable matched pairs across the
                   three lambdas: met at 2 (λ=0.1 @ 2/ty; λ=0.3 @ 20/ty),
                   not met at 10, not interpretable (achieved rates >5%
                   apart) at 12. At every interpretable loose-to-mid rung
                   the coordinated pipeline produced MORE isolated
                   excursions than single_union — criterion (a) fails —
                   driven by systematically shorter coincidence episodes
                   (e.g. median 2.0 vs 13.5 samples at λ=0.2 @ 2/ty).
                   The criterion and operationalisation were fixed before
                   the sweep ran; the verdict stands as computed; NO
                   POST-HOC REDEFINITION was made. The operationalisation
                   interaction is registered as LIM-020 and the
                   validation-to-monitoring FA transfer gap (10–50× at
                   identical multipliers) as LIM-021. Fairness symmetry
                   check passed at all three lambdas. Any
                   alternative-boundary analysis is exploratory only,
                   reported separately with the pre-registered verdict
                   stated first.
Robustness (author-accepted 2026-08-13): the exploratory boundary
                   sensitivity shows the not-met pattern HOLDS at
                   isolated/sustained boundaries 2, 5, and 10 samples —
                   every not-met point stays not-met at all four
                   boundaries; only the two met points are unstable. The
                   pre-registered verdict is therefore not an artefact of
                   the 3-sample boundary choice.

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

## ADR-018 — Step-change exclusion disabled; detector is reporting-only

Status:            CLOSED (2026-08-13) — resolves LIM-014 (Ruling 1 of the
                   EXP-20260812-001 pending author rulings)
Question:          Do the M-10 step-change detector's exclusions stand as a
                   healthy-state criterion? In EXP-20260812-001 they were
                   the dominant attrition: 337,263 of 847,396 train/val
                   rows (39.8%), from 3,187 detections whose parameters
                   were never reviewed (LIM-014).
Evidence:          Load-coincidence and persistence analysis of the
                   detections (random n=99 sample, seed 42, plus all 189
                   detections >= 30 C; detector windows replicated exactly,
                   p95 reproduction error 0.07 C):
                   - 94% of detections coincide with an active-power step
                     >= 100 kW across the same windows; median |dP| 365 kW
                     on 2.05 MW machines; signed dT–dP correlation 0.40.
                   - The operating-state pattern is explicit: positive
                     temperature steps run 76 kW -> 360 kW (coming to
                     load); negative steps 313 kW -> 6 kW (going idle).
                   - Shift retention decays to 48% at 7 days and 47% at 30
                     days; a recalibration predicts a stable offset near
                     100% at every horizon.
                   - 1 of 99 sampled detections is recalibration-like
                     (persistent shift without a coincident power move).
                   - The >= 30 C subset is worse, not better: 97% load
                     coincidence, 99% sign agreement, correlation 0.72 —
                     the largest steps are start-up warm-ups and shutdown
                     cool-downs, so raising the magnitude threshold does
                     not rescue the exclusion.
Decision:          Author ruling (2026-08-13).
                   (a) Step-change exclusion is DISABLED as a healthy-state
                       criterion (`healthy_state.exclude_step_changes:
                       false`). The detector remains ACTIVE as a REPORTING
                       rule: findings and step records appear in every
                       DatasetReport; no rows are excluded on their basis.
                       The exclusion was removing normal operating-regime
                       transitions from the healthy training set, biasing
                       the NBM toward steady-state behaviour and
                       mis-calibrating it during transients — precisely
                       where residuals are read.
                   (b) The recalibration-like candidates are NOT silently
                       readmitted. The two Kelmarsh 6 episodes are excluded
                       by name as `manual_exclusion_windows` (reason
                       `author_designated_artefact`), recorded in the run
                       config with this ADR as citation:
                       - K6-artefact-2021-02-05: 2021-02-04 17:50 to
                         2021-02-06 19:00 UTC — bearing −45.1 C (17:50) and
                         oil −34.8 C (19:00) within ~1 h at |dP| ~70 kW,
                         ~90% of the shift retained at 30 days.
                       - K6-artefact-2021-03-05: 2021-03-04 06:20 to
                         2021-03-06 06:20 UTC — bearing +36.4 C at dP = 0,
                         shift retained at 30 days.
                       Bounds follow the ±1-day convention around the
                       detection timestamps (the February pair is one
                       episode covering both channels). Under the current
                       provisional split these windows fall in the
                       monitoring period, where no healthy-state exclusion
                       applies — they bind if any future split (D-07)
                       brings 2021 into train/validation, and they remove
                       585 of Kelmarsh 6's 26,064 rows of 2021 holdings
                       (2.24%) wherever they apply.
                   (c) The detector parameters stay provisional-marked with
                       their sweep grids (window 72/144/288, magnitude
                       2.5/5.0/10.0, exclusion days 0.5/1.0/2.0), and the
                       sensitivity suite additionally sweeps
                       `exclude_step_changes` enabled/disabled — the suite
                       must show the disabled-exclusion conclusion is
                       stable, not only vary parameters within the
                       disabled regime.
Reproducibility:   EXP-20260812-001's stored resolved config predates
                   `exclude_step_changes`; under the post-ADR schema it
                   materializes the new default (false) and would rebuild a
                   different healthy population. That experiment reproduces
                   exactly at its recorded commit
                   (metadata environment.git_commit 1cf94ae5d…), which is
                   what per-experiment git hashes exist for. Defaults
                   embody closed rulings; snapshots pin their own code.
Affected modules:  M-03 (config: `exclude_step_changes`,
                   `ManualExclusionWindow`), M-12 (builder gates the
                   exclusion; applies manual windows with
                   `author_designated_artefact` attribution), M-10
                   (unchanged mechanics; reporting role now normative),
                   M-27 (DEFAULT_GRIDS adds the enabled/disabled sweep),
                   scripts/run_kelmarsh_experiment.py (named windows).
LIM-014:           mitigation status updated to MITIGATED.

## ADR-019 — Methodological finding: guard checks cannot see outside their declared universe

Status:            CLOSED (2026-08-13) — recorded finding (author-directed),
                   for Chapter 3's guard-architecture discussion
Question:          Why did the M-27 checklist test (acceptance 2) fail to
                   flag the step-change detector parameters as unswept
                   provisional values, despite being built precisely to
                   prevent unswept tunables?
Finding:           The checklist verifies bidirectional consistency between
                   two sets — provisional-marked config fields and
                   sensitivity grids — but BOTH sets derive from the same
                   universe: the Pydantic config schema. The step-change
                   parameters lived outside that universe, as constructor
                   defaults (`StepChangeRule(window=144, min_magnitude=5.0)`)
                   and a keyword default (`step_change_days=1.0`), so the
                   discovery walk never saw them and there was nothing for
                   the grid check to be inconsistent with. PROJECT.md names
                   its provisional values in §13 and §23 and describes the
                   §11 step-change heuristic without flagging its
                   constants, so neither spec nor test pointed at them.
                   A consistency check within a declared universe cannot
                   detect that the universe is incomplete. The gap became
                   visible only when the first real run exposed the
                   parameters' leverage (39.8% attrition, LIM-014).
Residual risk:     Structural, and explicitly not closed by fixing these
                   three parameters: other constants remain hard-coded
                   outside the config system (illustrative, not
                   exhaustive: the M-20 in-control
                   `material_inflation_threshold = 2.0`; the run script's
                   `BOOTSTRAP_REPLICATES = 1000` and seed; status-file
                   parsing constants). Each is invisible to the checklist
                   for the same reason the step-change parameters were.
                   Register entry: LIM-015.
Affected:          Chapter 3 (guard architecture discussion: what the
                   checklist guarantees and what it structurally cannot),
                   M-27 (unchanged code; its acceptance criterion is now
                   documented as consistency, not completeness).

## ADR-020 — generator_speed bounds and the impossible-value handling policy

Status:            CLOSED (2026-08-13) — Ruling 2 of the EXP-20260812-001
                   pending author rulings (the run's only validation ERROR:
                   3,226 rows outside the declared plausible range)
Question:          Do the (−1, 5000) RPM bounds stand, and what — if any —
                   policy acts on RANGE.IMPOSSIBLE values? Until this
                   ruling no policy existed: findings were reported and all
                   3,226 rows entered the modelling data.
Evidence:          All 3,226 flagged values are negative (none ≥ 5000);
                   two distinct populations (measured across all 36 raw
                   files):
                   - 2,621 rows in (−10, −1], overwhelmingly (−2, −1] —
                     parked-turbine sensor jitter around zero, on all six
                     machines in all six years (active power < 50 kW at
                     every flagged row; median −0.7 kW).
                   - 605 rows ≤ −10 RPM, including 269 identical readings
                     at −576.6 and a 238-sample run (~39.7 h, Kelmarsh 5,
                     from 2017-01-25 20:20). Rotor speed is ZERO at every
                     one of them (max 1.469 RPM); −576 generator RPM would
                     require rotor ≈ −5.4 RPM through the ~106:1 ratio —
                     impossible, so these are stuck or faulted signals,
                     not measurement.
                   In EXP-20260812-001 the train/validation instances were
                   excluded from the healthy state only because the 50 kW
                   power floor happened to remove them — coincidental
                   protection by a provisional parameter swept at
                   25/50/100 kW — and 1,462 rows were scored in the test
                   partition, so residuals there were computed from
                   impossible predictors and are not interpretable
                   (LIM-016).
Decision:          Author ruling (2026-08-13). Two populations, two
                   treatments:
                   (a) SCHEMA: `generator_speed` plausible_range widened
                       from (−1, 5000) to (−5, 5000) — standstill jitter
                       is routine, not physically impossible; the −1 bound
                       mis-stated the schema's own claim. Schema 1.3.0
                       (ADR-004 log); pinned hash re-pinned; the Kelmarsh
                       mapping config's declared schema version follows
                       with column assignments unchanged.
                   (b) HANDLING POLICY (new): RANGE.IMPOSSIBLE values on
                       any predictor are set to missing at cleaning
                       (`nullify_impossible_predictor_values`), then
                       removed by the existing `drop_missing_any_predictor`
                       rule with its audit trail — in ALL partitions,
                       monitoring included. A value the schema declares
                       physically impossible cannot serve as a model input
                       anywhere. The cleaning layer refuses the nullify
                       operation unless the drop rule follows it, so the
                       policy cannot silently half-apply.
                   (c) The 605 deep negatives remain out of range under
                       the widened bound and are handled by (b).
                   (d) REPORTING: when the policy is active, the runner
                       states the dropped-row count per split partition in
                       metrics (`cleaning.impossible_predictor_rows_dropped_
                       by_partition`), so the number is visible rather than
                       inferred. The audit's nullify entry records values
                       nullified per column. (Cleaning precedes splitting,
                       so the per-partition statement lives in metrics.json
                       beside the audit, not inside it.)
Under this policy, EXP-20260812-001's 3,226 flagged rows resolve as: 2,620
rows in (−5, −1] become in-range and stay; 606 rows below −5 are dropped
(under the current provisional split: 354 train / 32 validation / 220 test
— the one row in (−10, −5], Kelmarsh 5 at −8.4 RPM on 2018-06-15, falls in
train).
Affected modules:  M-06 (schema 1.3.0), M-07 (mapping version follows),
                   M-10 (RangeRule unchanged; reads the new bounds),
                   M-11 (nullify operation + ordering guard + audit
                   detail), M-30 (per-partition metric),
                   scripts/run_kelmarsh_experiment.py (operation added),
                   LIMITATIONS.md (LIM-016).

## ADR-021 — XGBoost tuning: pre-registered grid, selection rule, seed policy

Status:            CLOSED (2026-08-13) — Ruling 3 of the EXP-20260812-001
                   pending author rulings
Question:          Is XGBoost tuned on the healthy validation block before
                   any RQ1 headline claim (PROJECT.md §18), and under what
                   grid, budget, and selection rule? EXP-20260812-001 ran
                   untuned (count 0) on repo-default hyperparameters.
Decision:          Author ruling (2026-08-13). TUNE, with a small
                   pre-registered grid.
                   (a) GRID (12 candidates, recorded per R9):
                       max_depth 4/6/8 × learning_rate 0.03/0.05 ×
                       subsample 0.8/1.0; n_estimators 600 as a ceiling
                       with early stopping on the validation block
                       (early_stopping_rounds 50, an implementation
                       default recorded in config, author-changeable);
                       colsample_bytree fixed 0.8. The swept parameters
                       are those governing generalisation (depth,
                       shrinkage, row subsampling). The grid is
                       deliberately small: R9's concern is silent multiple
                       comparison on a single validation block, and a
                       12-candidate budget is defensible where a
                       200-candidate search would not be.
                       `tuning_configurations_evaluated = 12` in metadata.
                   (b) SELECTION RULE — changed from the implemented
                       pooled-RMSE default, which weights targets by error
                       scale (oil would dominate bearing): the score is
                       the MEAN OF PER-TARGET RMSE, EACH NORMALISED BY
                       THAT TARGET'S BASELINE (linear regression)
                       VALIDATION RMSE. Equal target weight; interpretable
                       as mean improvement over baseline. Config-specified
                       (`model.tuning.selection`), not hard-coded; the
                       pooled alternative remains selectable.
                   (c) SEED POLICY: one fixed seed (42) for all tuning
                       fits, recorded per candidate in the trial records.
                       No seed averaging — it would multiply the effective
                       comparison count without a corresponding record.
                   (d) The grid lives in config (`model.tuning`), so the
                       exact search is part of every experiment's resolved
                       config and provenance; per-candidate trial records
                       (hyperparameters, seed, score, best_iteration) are
                       persisted in metadata and the saved model.
Validation/monitoring reversal: NOT attributed to tuning. A fourth
                   confound is added to LIM-013's record — author-judged
                   the most likely: EXP-001's training set had ~337k rows
                   of load transitions removed by the step-change detector
                   (ADR-018), so the tree model saw almost only
                   steady-state behaviour and would degrade sharply on
                   transients, while linear regression degrades
                   gracefully. That training set has since been ruled
                   incorrect. The next run's comparison is therefore not
                   comparable to EXP-20260812-001's, and **EXP-001's DM
                   result must not be cited as a finding**.
Implementation:    `tune_model` chokepoint (M-15 companion): causal
                   validation first; matrices assembled from train and
                   validation only — structurally no test data can reach a
                   tuning search. The scored winner's fitted trees are
                   adopted directly (the model selected IS the model
                   used). The baseline fits first in the runner because
                   the selection rule divides by its per-target validation
                   RMSE; `include_baseline: false` with the ADR-021
                   selection is refused fail-early.
Affected modules:  M-03 (TuningConfig/TuningSelection), M-15 (tune_model
                   chokepoint; FitReport.tuning_trials), M-16 (tune
                   rework: selection metrics, early stopping, trial
                   records), M-29 (ModelMetadata.tuning_trials), M-30
                   (runner wiring), LIMITATIONS.md (LIM-013 fourth
                   confound).

## ADR-022 — RQ1 headline: the healthy-filtered monitoring slice

Status:            CLOSED (2026-08-13) — Ruling 4 of the EXP-20260812-001
                   pending author rulings
Question:          Which period's accuracy metrics headline RQ1? After
                   ADR-021 the healthy validation block is the selection
                   block (its metrics are optimistically biased — risk R9
                   realised), and the unfiltered monitoring period
                   measures a different quantity (behaviour on everything
                   that followed, conflating model error with real
                   anomalies and the LIM-013 confounds). No existing
                   partition was both healthy and untouched by selection.
Decision:          Author ruling (2026-08-13).
                   (a) HEADLINE: XGBoost and baseline accuracy computed on
                       the HEALTHY-FILTERED SUBSET OF THE MONITORING
                       PERIOD — the same healthy-state criteria applied to
                       train/validation (post-ADR-018 configuration),
                       applied to 2019-02-01 onward. Metrics: RMSE, MAE,
                       R², bias per target, with moving-block bootstrap
                       CIs and Diebold–Mariano per PROJECT.md §19. This is
                       the only construction that is both healthy by the
                       same criteria used throughout and wholly untouched
                       by fitting or selection — the quantity RQ1 names.
                   (b) ROLLING-ORIGIN: NOT commissioned (deliberate
                       decline of the PROJECT.md §14 option, not an
                       oversight): it refits the model across folds and
                       therefore answers how well the METHOD generalises,
                       not how well THIS model represents healthy
                       behaviour.
                   (c) THREE-PERIOD REPORTING: the RQ1 table reports all
                       three periods with explicit labels —
                       healthy validation: "selection-biased after tuning
                       (ADR-021)"; healthy-filtered monitoring: HEADLINE;
                       unfiltered monitoring: "conflates model error with
                       anomalous operation and LIM-013 confounds; not an
                       RQ1 measure". Reporting all three with labels is
                       more honest than reporting one, and the gap between
                       them is itself Chapter 4 material.
                   (d) PARTITION INTEGRITY (critical): the healthy slice
                       is an RQ1 METRICS path only. Detection, residual
                       generation, EWMA, coordinated analysis, and all
                       RQ2/RQ3 evaluation run on the FULL unfiltered
                       monitoring stream per PROJECT.md §14. Enforced
                       structurally: the slice is computed after the
                       detection stages, feeds nothing back, subsets the
                       already-computed test predictions (models never
                       re-run), and a test asserts the detection path
                       consumed every unfiltered monitoring row while the
                       slice excluded its below-floor rows.
Implementation:    Runner computes the slice with the same
                   HealthyStateBuilder configuration; slice predictions
                   persist as predictions/{thesis,baseline}_monitoring_
                   healthy.parquet; metrics carry an ``rq1`` section with
                   the headline designation, the period labels, and the
                   slice's rows/retention/exclusion counts (the fraction
                   of the monitoring period removed is stated, not
                   inferred). The Kelmarsh run script now collects alarm
                   windows across the FULL ADR-009 span so
                   monitoring-period windows exist for the slice;
                   pre-monitoring healthy-state construction is unaffected
                   (windows outside train/validation match no rows there).
Pre-run estimate:  from the raw holdings under the post-ADR-018/020
                   configuration, the monitoring period holds ~740.5k
                   usable rows, of which ~100.3k fall in alarm/manual
                   windows and a further ~100.5k below the 50 kW floor —
                   healthy-slice retention ≈ 72.9% (539.6k rows). The
                   authoritative numbers are produced by the next run and
                   recorded in its metrics.
Affected modules:  M-30 (slice computation, rq1 metrics section,
                   partition-integrity semantics), M-28 (three-period RQ1
                   table with labels; CIs/DM on the slice per §19),
                   scripts/run_kelmarsh_experiment.py (span-wide alarm
                   windows), thesis Chapters 3–4.

## ADR-023 — D-07 ratified: split dates 2018-07-01 / 2019-02-01

Status:            CLOSED (2026-08-13) — decision queue D-07 (Ruling 5 of
                   the EXP-20260812-001 pending author rulings; closes
                   queue Group B)
Question:          Ratify or change the provisional chronological split:
                   TRAIN to 2018-07-01, VALIDATION to 2019-02-01, TEST/
                   monitoring from there (explicit dates; PROJECT.md §14).
Decision:          Author ruling (2026-08-13): RATIFIED as run.
Justification:     - Later training ends buy at most +1.3 °C at the warm
                     end of ambient coverage (fully captured by a
                     2018-09-01 boundary) and nothing at the cold end,
                     while validation shrinks from 215 days toward 31.
                   - Validation now serves three functions — ADR-021
                     tuning and early stopping, M-20 in-control
                     characterisation, and the open ADR-001 statistics
                     branch — so its size and seasonal coverage are
                     load-bearing for all three.
                   - Training spans 25.9 months covering all 12 calendar
                     months twice, clearing the §14 seasonal check.
                   - VALIDATION_END sits 9.7 days before the ADR-017
                     match window opens, so threshold-fitting data and
                     detection-judging data do not overlap.
                   - The LIM-010 icing pair (2019-02-03) stays in the
                     monitoring period, 21.7 days before onset and safely
                     outside the 14-day match window, where it belongs
                     for the Chapter 5 confounder discussion.
                   - The §14 default 70/15/15 fractions are INFEASIBLE
                     for this dataset: the 70% boundary lands in late
                     2019 and would put EVENT-001 in training, violating
                     ADR-010. Explicit dates are required, not merely
                     preferred.
Structural finding (author-directed; recorded as a finding, not a caveat):
                   NO ADMISSIBLE SPLIT CLOSES LIM-013. The monitoring
                   ambient extremes fall on 2019-11-14, 2020-11-13,
                   2019-07-25, and 2020-07-24 — all after any boundary
                   that satisfies ADR-010 — and the entire pre-monitoring
                   span covers only (−4.1, 38.9) °C against the
                   monitoring period's (−7.9, 44.0) °C. The ambient
                   extrapolation is therefore a property of the dataset
                   combined with the EVENT-001-in-test constraint, not of
                   the dates chosen. Chapter 5 states it as a structural
                   limitation of the dataset, not a design shortcoming.
                   LIM-013 updated accordingly.
Affected modules:  M-13 (split configuration — unchanged, now ratified),
                   scripts/run_kelmarsh_experiment.py (provisional marker
                   on the dates removed), LIMITATIONS.md (LIM-013),
                   docs/CHAPTER3_DECISION_QUEUE.md (Group B complete).

## ADR-024 — EVENT-001 clearance gaps excluded from the RQ1 slice

Status:            CLOSED (2026-08-13) — author ruling on the
                   EXP-20260813-001 slice check
Question:          EXP-20260813-001's EVENT-001 slice check found the
                   detection stream holds 11,280 rows inside the event
                   window while the RQ1 healthy slice retained 1,580 of
                   them — the clearance gaps between the three
                   occurrences (4.9 + 7.45 days, turbine producing, no
                   active Stop/Warning), which pass every healthy
                   criterion. Do they count as healthy for RQ1?
Decision:          Author ruling (2026-08-13): EXCLUDE them. ADR-013
                   designates EVENT-001 as ONE continuous degradation
                   episode (2019-02-24 16:46:28 → 2019-05-30 07:34:04).
                   Rows from within that span cannot be counted as
                   healthy for RQ1 regardless of whether an alarm was
                   active at that moment — the clearance gaps are periods
                   when the filter restriction had been temporarily
                   relieved, not periods of healthy operation. Retaining
                   them would contradict the event designation.
                   The full ADR-013 episode span is a named exclusion
                   window (`ManualExclusionWindow`, reason
                   `author_designated_event_span`, citing ADR-013) in the
                   run configuration.
Scope (critical):  The exclusion applies ONLY to the RQ1 metrics slice.
                   The detection stream continues to consume the full
                   unfiltered monitoring partition including the entire
                   event window — structurally guaranteed (the detection
                   path never passes through the healthy-state builder)
                   and asserted by test: detection sees every
                   event-window row, the slice sees none.
Affected modules:  M-03 (`ManualExclusionWindow.reason`), M-12 (reason
                   routing; `author_designated_event_span` in the
                   attribution order), M-30 (slice via the standard
                   builder), scripts/run_kelmarsh_experiment.py (the
                   EVENT-001 span window), tests (slice-only assertion).
Supersession:      EXP-20260813-001's monitoring_healthy metrics were
                   computed WITHOUT this exclusion; the re-run under this
                   ADR becomes the RQ1 headline. Whether the headline
                   shifts materially is reported with the re-run — a
                   negligible shift is itself recorded, since it shows
                   the headline is not sensitive to this decision.
Outcome:           EXP-20260813-002 (2026-08-13). Slice check: detection
                   stream 11,280 event-window rows, slice 0 — as ruled.
                   Slice 538,045 rows (72.66%); the event span claimed
                   1,772 rows under disjoint attribution (the 1,580
                   formerly counted healthy plus 192 previously
                   attributed to the power floor). Headline shift:
                   NEGLIGIBLE — bearing RMSE 2.1459 → 2.1468 (+0.04%),
                   oil 2.6283 → 2.6298 (+0.06%); R² moves in the fourth
                   decimal; DM statistics −33.71 → −33.66 and −20.39 →
                   −20.37 (p ≈ 0 throughout). The RQ1 headline is not
                   sensitive to this decision, which is itself on the
                   record. Validation and unfiltered-test metrics are
                   bit-identical to EXP-20260813-001, confirming the
                   exclusion touched the metrics slice only.

## ADR-025 — Detection operating points selected (PRIMARY and SECONDARY)

Status:            CLOSED (2026-08-13) — author selection on the
                   EXP-20260813-002 matched-FPR sweep (ADR-016
                   Operationalisation; LIM-021 handling ruling)
Question:          Which operating points anchor the detection results:
                   the EVENT-001 descriptive derivation (ADR-016
                   secondary criterion) and every alarm-behaviour claim?
Decision:          Author selection (2026-08-13).
                   PRIMARY — λ = 0.2, matched at 10 false-alarm episodes
                   per turbine-year on the healthy validation block:
                   - single_union 11.25σ (validation 9.70/ty → measured
                     slice rate 117.8/ty)
                   - coordinated 10.05σ (validation 10.27/ty → measured
                     slice rate 75.2/ty)
                   Rationale: λ=0.2 is the pre-registered default and the
                   M-20 in-control characterisation was performed at it;
                   10/ty sits above the coarse-rung boundary (resolution
                   0.285/ty, ~35 expected events — well clear of the <10
                   flag); both pipelines achieve within 3% of target, so
                   the composition comparison is interpretable. Stricter
                   rungs at this λ are coarse; looser rungs are
                   operationally meaningless.
                   SECONDARY — λ = 0.2, calibrated at 10/ty on the
                   healthy monitoring slice:
                   - coordinated 20.81σ (slice 9.48/ty)
                   - single_union UNREACHABLE at ≤30σ — reported as a
                     RESULT, not a gap in the sweep.
                   The SECONDARY point uses monitoring-period healthy
                   data: a weaker independence claim, stated wherever it
                   appears; the slice excludes the full ADR-013 event
                   span, so no event-tuning is possible.
Reporting rule:    every table reports the nominal target BESIDE the
                   measured slice rates — the gap IS the LIM-021 finding,
                   not a caveat on it.
Affected:          EVENT-001 derivation (descriptive, ADR-016 secondary,
                   `inferential_allowed = false`), M-28 comparison
                   tables, Chapter 5.
Outcome (2026-08-13, EVENT-001 derivation accepted as reported; recorded
without softening):
                   At the validation-matched PRIMARY point both pipelines
                   detect ~13 days ahead of the code-1860 alarm —
                   coordinated first persistent exceedance 2019-02-11
                   17:10 UTC (lead 12.98 d), single_union 2019-02-11
                   15:30 (lead 13.05 d, marginally earlier). At the
                   slice-calibrated SECONDARY point the coordinated
                   pipeline does NOT detect within the 14-day window (0
                   persistent exceedances), while single_union at the
                   same multiplier — not rate-matched; unreachable at
                   10 FA/ty on the slice — does (13.0 d).
                   Mechanistically consistent with LIM-022: the
                   coincidence requirement trades sensitivity for
                   specificity, producing BOTH the lower out-of-period
                   false-alarm rates AND the missed marginal detection.
                   Descriptive throughout; `inferential_allowed` false.
                   The Chapter 5 icing qualification is recorded in
                   LIM-010 and binds every presentation of the 13-day
                   lead.

## ADR-026 — Methodological finding: EWMA control-chart theory degrades on serially correlated SCADA residuals

Status:            CLOSED (2026-08-13) — recorded finding
                   (author-directed), for Chapter 3
Finding:           The selected multipliers (10–21σ across the PRIMARY
                   and SECONDARY points) are not control limits in any
                   recognisable control-chart sense. EWMA control-chart
                   theory is built on i.i.d. assumptions, and it degrades
                   severely on serially correlated 10-minute SCADA
                   thermal residuals: the 54.8× in-control false-alarm
                   inflation at the theoretical 3σ point (LIM-011/017/019)
                   and the 10–21σ multipliers required to reach
                   operational false-alarm rates are TWO MEASUREMENTS OF
                   THE SAME PHENOMENON. In effect, the "σ multiplier"
                   functions as an empirically calibrated quantile knob,
                   not a statistically meaningful limit; the empirical
                   in-control characterisation mandated by PROJECT.md §23
                   is what carries the inferential weight.
Affected:          Chapter 3 (EWMA methodology discussion; the LOCKED-02
                   primary treatment is retained with its limits defended
                   empirically, not theoretically), Chapter 5.

## ADR-027 — Nacelle-temperature ablation (specified before execution)

Status:            CLOSED (2026-08-13) — author specification. The order
                   was originally given at mapping approval in session
                   Q&A only; it is recorded here BEFORE execution so it
                   exists on paper (the LIM-015/ADR-019 lesson applied to
                   author orders).
Varied:            the predictor set — with and without
                   `nacelle_temperature` (refit, full pipeline, ADR-021
                   tuning inside).
Compared:          the RQ1 three-period table (ADR-022: healthy
                   validation, healthy-filtered monitoring slice
                   HEADLINE, unfiltered monitoring), both targets, with
                   blocked-bootstrap CIs and Diebold–Mariano per §19.
Conclusion label:  whether the RQ1 slice ordering (XGBoost vs baseline)
                   holds in both configurations.
Rationale:         nacelle air is partially drivetrain-heated and is
                   therefore the least strictly exogenous of the seven
                   predictors (the caveat recorded at mapping approval);
                   if it is materially heated, it would soften residuals
                   precisely when the gearbox runs hot.
Execution:         a separate, labelled ABLATION — explicitly NOT run
                   through the provisional-parameter registry (the
                   grid-coverage guard rightly refuses predictor-set
                   sweeps). Runs AFTER the registered M-27 sweeps.
Affected:          M-30 (ablation runs via the standard pipeline),
                   M-28 (comparison table), Chapter 3 (predictor
                   defence), Chapter 5.
