# CHAPTER3_DECISION_QUEUE.md — Decisions Chapter 3 Must State

Chapter 3 does not exist yet; it blocks the project through the decisions it
must state, not its prose. This queue converts that blockage into closable
items. Ground rules: PROJECT.md v2.0 LOCKED-01…10 are not decisions and do
not appear here; provisional parameters keep their PROJECT.md values with
markers intact until closed; only the author closes items (recorded in
docs/DECISIONS.md). LITERATURE recommendations below are **proposals for the
author to accept or reject**, not decisions.

> **STOP CONDITION.** The queue is COMPLETE when every High-viva-risk
> decision is either closed with a recorded justification, or explicitly
> documented in LIMITATIONS.md as an accepted constraint. Medium and Low
> items may remain open at submission.

Evidence tags (exactly one per item):
- **LITERATURE** — closable now from Chapters 1–2 / Evidence Bank
- **CENSUS** — needs Phase 0.5 dataset census output
- **EXPERIMENT** — needs results (incl. §27.3 sensitivity analysis)

---

## Group A — LITERATURE (all CLOSED 2026-08-11)

> D-01 ACCEPTED as proposed → ADR-008. D-02 REVISED (two models only:
> XGBoost THESIS + multiple linear regression BASELINE; Random Forest and
> the proposed MLP dropped) → ADR-002. D-03 ACCEPTED, omit → ADR-003.
> The proposal text below is retained as the record of what was put to the
> author; the authoritative decisions are in docs/DECISIONS.md.

### D-01 — FMEA rule base contents — VIVA RISK: **High** — CLOSED (ADR-008)

- **Decision:** which residual-pattern → candidate-mechanism rules the
  interpretation layer ships with. Referenced: PROJECT.md §26 (M-25, M-26);
  Chapter 2 §2.7 ("Chapter 3 formalises these implied signatures into an
  operational rule base").
- **Options:** (a) formalise Chapter 2 Table 2.3's five-pattern mapping as
  the initial rule set; (b) subset to patterns whose signals exist in the
  final dataset; (c) defer all rule content to post-census.
- **Evidence:** LITERATURE.
- **Blocked until closed:** M-25 rule content, M-26 interpretation outputs,
  RQ3 evaluation design.
- **PROPOSAL (accept/reject):** adopt (a) — seed with the five Chapter 2
  Table 2.3 patterns, every rule `validated: false` until its ADR-005
  sign-off, then subset per (b) once the census fixes available channels:
  1. **Gear-teeth wear** — sustained positive, load-dependent oil-temperature
     residual; bearing residuals rising in lag (Qiu et al., 2016; Qiu et al.,
     2014).
  2. **HSS bearing failure** — bearing-temperature residual leads; oil
     residual smaller and later (Bangalore & Tjernberg, 2015; Qiu et al., 2014).
  3. **LSS/planetary bearing failure** — LSS bearing residual leading where
     instrumented, otherwise weak oil-only signature (Qiu et al., 2014).
  4. **Lubrication-system degradation** — broad simultaneous positive
     residuals across oil and bearing channels (Qiu et al., 2014; Shafiee &
     Dinmohammadi, 2014).
  5. **Electrical/generator-side influence** — generator-side residuals
     without gearbox-led ordering; used as an exclusion pattern (Qiu et al.,
     2016).
  Every rule rationale must carry the overlap caveat: three of five gearbox
  failure modes share the oil-temperature signature (Feng et al., 2013), so
  differentiation rests on the coordinated pattern, and outputs remain
  plausibility-graded hypotheses (Chapter 1 §1.5 scope boundary).

### D-02 — ADR-002: baseline NBM — VIVA RISK: **Medium** — CLOSED (ADR-002, revised)

- **Decision:** which literature-anchored baseline accompanies Random Forest
  as an RQ1 comparator. Referenced: PROJECT.md §18 (M-17); ADR-002.
- **Options:** ANN-style NBM (dominant in the cited SCADA-NBM literature);
  ANFIS-style NBM (Schlechtingen & Santos lineage); linear-regression NBM.
- **Evidence:** LITERATURE.
- **Blocked until closed:** M-17 DONE-ness (its acceptance criterion 2
  requires the rationale and citation recorded in DECISIONS.md first).
- **PROPOSAL (accept/reject):** a feed-forward single-hidden-layer MLP ANN
  (scikit-learn `MLPRegressor`, native multi-output, exogenous inputs only),
  anchored on Bangalore & Tjernberg (2015) — the direct gearbox-bearing-
  temperature NBM precedent Chapter 2 features (Figure 2.1) — with
  Santolamazza et al. (2021) and Zaher et al. (2009) as supporting ANN-NBM
  anchors. Two defensibility notes to record on closure: (i) Bangalore &
  Tjernberg's NARX form feeds lagged target values, which Guard 8 prohibits —
  the baseline reproduces the ANN family under exogenous-only inputs,
  consistent with Chapter 2 §2.4 (Felgueira et al., 2019); (ii) a shallow MLP
  is the classical ANN of the cited literature, not deep learning, so the
  deep-learning prohibition is not engaged.

### D-03 — ADR-003: LightGBM comparator — VIVA RISK: **Low** — CLOSED (omit)

- **Decision:** add a LightGBM comparator or omit. Referenced: PROJECT.md §5
  (M-17, if added); ADR-003.
- **Options:** add | omit (spec default).
- **Evidence:** LITERATURE.
- **Blocked until closed:** nothing (default stands until changed).
- **PROPOSAL (accept/reject):** omit. Chapters 1–2 identify no RQ1 need the
  mandated baselines cannot meet; adding it would only widen the
  multiple-comparison surface (risk R9).

---

## Group B — CENSUS (D-04, D-05 CLOSED 2026-08-12; D-06, D-07 remain open)

> D-04 CLOSED → ADR-013: status-code-derived events qualified by duration
> and preceding-thermal-coverage; tier ALARM-LEVEL ONLY; EVENT-001 (code
> 1860, Kelmarsh 1, 2019) is the single labelled event. D-05 CLOSED →
> ADR-014: one event < 2, so the pre-committed rule selects the DESCRIPTIVE
> case-study branch (`inferential_allowed = false`). The author's separate
> target-designation decision is ADR-012 (Rear bearing temperature is the
> bearing target; oil inlet excluded). Phase 0.5 gate APPROVED → ADR-015.
> The proposal text below is retained as the record of what was put to the
> author; the authoritative decisions are in docs/DECISIONS.md.

### D-04 — Ground-truth definition and tiering — VIVA RISK: **High** — CLOSED (ADR-013)

- **Decision:** what counts as a labelled gearbox event, and how
  anomaly-detection ground truth is separated from mechanism-level ground
  truth. Referenced: PROJECT.md §27.1 (M-24); §7.5 census field "count of
  labelled gearbox events".
- **Options:** status-code-derived events only; status codes qualified by
  duration/severity criteria; maintenance-confirmed events only; the spec's
  two-tier structure with tier membership defined per record type.
- **Evidence:** CENSUS. Known constraint to weigh at closure: the 2016
  Kelmarsh status logs' maintenance-commentary column is 100% missing, so
  candidate events are status-log-derived, not maintenance-confirmed.
- **Blocked until closed:** M-24 tier tags, D-05, D-06, event evaluation
  (M-27), the honest phrasing of every detection claim.

### D-05 — Evaluation design: quantitative vs descriptive — VIVA RISK: **High** — CLOSED (ADR-014)

- **Decision:** the pre-committed Phase 0.5 decision rule outcome — ≥2
  independent labelled gearbox events → quantitative event-based evaluation;
  <2 → descriptive case-study design with no inferential detection-rate or
  lead-time claims. Referenced: PROJECT.md §7.5, §27.2 (M-27).
- **Options:** quantitative | descriptive (rule is fixed; the census count
  decides which branch).
- **Evidence:** CENSUS (depends on D-04's event definition).
- **Blocked until closed:** M-27 `inferential_allowed` mode, RQ2/RQ3 claim
  strength, LIMITATIONS.md small-n entry.

### D-06 — Event-matching windows — VIVA RISK: **High**

- **Decision:** how a detection is matched to a known event (window length
  before the event, persistence qualification for "first detection", per-type
  windows). Referenced: PROJECT.md §27.2 (M-27).
- **Options:** fixed pre-event window (days-scale); persistence-qualified
  first-detection; per-event-type windows.
- **Evidence:** CENSUS (event timestamp precision, density, and overlap
  determine what is definable without ambiguity).
- **Blocked until closed:** M-27 event metrics, lead-time computation,
  matched-FPR event columns (M-23 outputs feeding M-27).

### D-07 — Chronological split periods — VIVA RISK: **Medium**

- **Decision:** train/validation/test boundaries — fraction-based (70/15/15
  default) vs explicit dates, and whether rolling-origin evaluation is used
  for RQ1. Referenced: PROJECT.md §14 (M-13).
- **Options:** default fractions; explicit dates placing known events in the
  monitoring period; rolling-origin folds where volume allows.
- **Evidence:** CENSUS (duration, seasonal coverage, event timing per
  turbine).
- **Blocked until closed:** final experiment configs; seasonal-coverage
  warnings that may need LIMITATIONS.md entries.

---

## Group C — EXPERIMENT (needs results; left open, provisional values stand)

### D-08 — Healthy-state fault pre-exclusion window — VIVA RISK: **High**

- **Decision:** `fault_pre_exclusion_days` final value. Referenced:
  PROJECT.md §13 (M-12); provisional 30; sensitivity grid 15/30/60 (§27.3).
- **Options:** 15 | 30 | 60 days (grid extendable).
- **Evidence:** EXPERIMENT (§27.3 sensitivity converts provisional into
  defended; conclusion-flips flagged to LIMITATIONS.md).
- **Blocked until closed:** defended healthy-state rationale for every
  headline experiment.

### D-09 — EWMA λ — VIVA RISK: **High**

- **Decision:** `ewma_lambda` final value. Referenced: PROJECT.md §23
  (M-20); provisional 0.2.
- **Options:** §27.3 sweep grid over λ (spec leaves the grid open).
- **Evidence:** EXPERIMENT (sensitivity + M-20's empirical in-control
  false-alarm characterization on serially correlated residuals).
- **Blocked until closed:** defended detection configuration; threshold
  justification examiners will press on.

### D-10 — Control-limit multiplier and formulation — VIVA RISK: **High**

- **Decision:** `control_limit_sigma` value and steady-state vs time-varying
  limit formulation. Referenced: PROJECT.md §23 (M-20); provisional 3.
- **Options:** 2σ | 3σ | percentile-based; steady-state | time-varying.
- **Evidence:** EXPERIMENT (empirical in-control characterization is the
  spec's mandated defence because i.i.d. ARL assumptions fail; §27.3 sweep).
- **Blocked until closed:** defended detection configuration; matched-FPR
  grid anchoring (M-23).

### D-11 — ADR-001: normalization/threshold statistics source — VIVA RISK: **High**

- **Decision:** statistics fitted on healthy TRAINING vs healthy VALIDATION
  block. Referenced: PROJECT.md §22 (M-19b, M-20); ADR-001; risk R6.
- **Options:** training (v1.0 default) | validation (panel-reviewer
  recommendation against in-sample optimism).
- **Evidence:** EXPERIMENT (ADR-001's recorded closure evidence: compare
  in-control false-alarm behaviour under both settings on real healthy data).
- **Blocked until closed:** ADR-001; defended threshold provenance (Guard 4
  narrative); final detection configs.

### D-12 — Residual normalization method — VIVA RISK: **Medium**

- **Decision:** σ | MAD | percentile | condition-binned. Referenced:
  PROJECT.md §22 (M-19b); config default `mad` (provisional in effect).
- **Options:** the four families; condition-binned contingent on
  heteroscedasticity diagnostics (§20).
- **Evidence:** EXPERIMENT (§20 condition-sliced diagnostics + §27.3 sweep).
- **Blocked until closed:** defended normalization choice in headline
  experiments.

### D-13 — Maintenance post-exclusion window — VIVA RISK: **Medium**

- **Decision:** `maintenance_post_exclusion_days` final value. Referenced:
  PROJECT.md §13 (M-12); provisional 2.
- **Options:** §27.3 sweep grid (spec leaves the grid open).
- **Evidence:** EXPERIMENT.
- **Blocked until closed:** defended healthy-state rationale.

### D-14 — Minimum active power floor — VIVA RISK: **Medium**

- **Decision:** `minimum_active_power_kw` final value (operating-state
  filter). Referenced: PROJECT.md §13 (M-12); provisional 50 kW.
- **Options:** §27.3 sweep grid; census context (turbine rated power) informs
  the grid but the defence is experimental.
- **Evidence:** EXPERIMENT.
- **Blocked until closed:** defended operating-state filter rationale.

---

*Queue scope is fixed to the decisions Chapter 3 must state. ADR-004
(schema-version log) and ADR-005 (FMEA sign-off log) are standing process
logs, not Chapter 3 decisions, and are tracked in DECISIONS.md only.*
