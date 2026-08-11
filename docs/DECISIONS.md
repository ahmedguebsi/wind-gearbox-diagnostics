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
Current version:   1.1.0 (stamped by M-06 `app/data/schema.py`)
Version log:
  - 1.0.0 (2026-08-11) initial canonical schema: structural variables, the
    thesis-identified upstream predictors, and the two required thermal
    targets.
  - 1.1.0 (2026-08-11) added `plausible_range` to `CanonicalVariable`, so a
    variable's physically impossible bounds are declared alongside the
    variable itself rather than duplicated inside the validation layer.
    Minor bump: additive, no variable renamed or removed. Detected by the
    pinned schema-hash drift test, which is what that test exists for.
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
