# THESIS_REQUIREMENTS.md — Software Requirements Source of Truth

> **STATUS: PARTIAL.** Derived from thesis Chapter 1 (Introduction) and
> Chapter 2 (Literature Review draft), read 2026-08-11, under the governing
> rule that **PROJECT.md v2.0 LOCKED-01…10 is authoritative** (ADR-006).
> **Chapter 3 (methodology) is the blocking input for full requirements** —
> every field that cannot be fixed without it, or without the Phase 0.5
> dataset census, is marked UNKNOWN. Chapter/spec conflicts are recorded
> here and in docs/DECISIONS.md, never silently resolved; thesis chapters
> are never edited from this repository.
>
> Source texts: "Chapter 1 Introduction.docx" (sha-prefix c01b9cc5d268,
> 2026-07-27); "Chapter_2_draft.docx" (sha-prefix 6510fa47df56, 2026-07-29).

## 1. Research problem and gaps (Chapter 1 §1.3; substantiated in Chapter 2)

- **Gap 1 — diagnostic interpretation.** An anomaly alert is not a diagnosis;
  fault identification consumes 70–90% of fault-handling time. Post-hoc
  attribution (SHAP/LIME-class) reveals influential inputs, not physical
  mechanisms; black-box outputs undermine appropriate operator reliance.
- **Gap 2 — multi-variable thermal residual analysis.** Gearbox degradation
  redistributes heat across thermally coupled signals; prevailing methods
  monitor residuals per-signal, causing missed detections and false alarms.
  Chapter 2 §2.8 synthesis: no published method combines coordinated
  multi-target thermal residual analysis (R1) with residual-to-mechanism
  mapping (R2) — the thesis occupies that intersection.

## 2. Aim and objectives (Chapter 1 §1.4, as they bind the software)

**Aim:** develop and evaluate a SCADA-based gearbox condition-monitoring
framework integrating multi-target normal behaviour modelling with an
FMEA-informed interpretation layer.

| Objective | Software binding | Modules |
|-----------|------------------|---------|
| O1: healthy-state SCADA dataset + causal predictor/target separation | Cleaning, healthy-state construction, Guards 1/2/8 | M-10…M-14 |
| O2: multi-target NBM predicting gearbox oil and bearing temperatures; accuracy via **RMSE, MAE, R², bias** | Multi-target XGBoost NBM (LOCKED-01); MetricSet exposes exactly these four fields | M-15…M-18 |
| O3: residual streams characterising abnormal behaviour | Residual engine, normalization, EWMA (LOCKED-02), coordinated states | M-19a…M-22 |
| O4: FMEA-informed interpretation mapping coordinated residual patterns to candidate mechanisms; assessed via lead time and false-alarm rate | FMEA KB + interpreter (LOCKED-03); matched-FPR framework; event evaluation | M-23…M-27 |

> **⚠ Recorded deviation (ADR-006, CLOSED).** Chapter 1 as drafted words
> Objective 2 with **MAPE** and **SHAP-based explainability**. Both are
> overridden by the locks (§19 metrics; LOCKED-07): the chapter predates the
> panel review and its wording is pending author correction. Physical
> credibility is demonstrated by causal predictor separation (M-14) and
> condition-sliced error diagnostics (M-18), not attribution. This deviation
> is recorded so the gap between chapter text and built software stays
> visible until the chapter is corrected.

## 3. Research questions (Chapter 1 §1.5; locked forms govern)

| RQ | Locked form for the software | Chapter 1 drafting note |
|----|------------------------------|-------------------------|
| RQ1 | Accuracy of a multi-target **XGBoost** NBM for healthy gearbox thermal behaviour | Chapter 1 wording is model-agnostic; LOCKED-01 fixes XGBoost (M-16) |
| RQ2 | Coordinated vs single-signal residual evidence **at matched false-alarm operating points** | Chapter 1 wording lacks the matched-FPR qualifier; M-23 is the sole comparison route |
| RQ3 | Can FMEA-informed interpretation enrich alerts with physically plausible candidate mechanisms | Consistent with LOCKED-03 |

**Scope boundary (Chapter 1 §1.5, verbatim constraint):** detection
performance is evaluated quantitatively against maintenance and alarm
records, but available ground truth cannot verify mechanism-level diagnoses —
interpretations are evaluated **only for physical plausibility and internal
consistency**. Enforced structurally: "confirmed" is unrepresentable in the
CandidateMechanism confidence enum (M-26).

## 4. Methodology Alignment Table (LOCKED constraint → implementing components)

Module IDs refer to IMPLEMENTATION_PLAN.md. Status: ✅ implemented and
exercised on real data, ⚠ implemented but not exercised.
*(Status column corrected 2026-08-18: it still read "🔜 planned" for modules
completed weeks earlier. A requirements table that understates what is built
is as misleading as one that overstates it.)*

| Lock | Constraint | Implementing component(s) | Status | Thesis-text alignment |
|------|-----------|---------------------------|--------|----------------------|
| LOCKED-01 | Multi-target XGBoost is THE thesis NBM | M-16 (`model_kind == THESIS`, sole THESIS registrant); registry meta-test asserts exactly one THESIS registrant | ✅ | Ch1 RQ1 model-agnostic wording; locked form governs (§3 above) |
| LOCKED-02 | EWMA + control limits PRIMARY | M-20; `DetectionConfig.method` admits only `"ewma"` | ✅ detector / ⚠ the M-21 comparators exist but no run script exercises them, so the PRIMARY designation is not yet defended by comparison (§28) | Ch2 §2.3 grounds EWMA-on-residuals — aligned |
| LOCKED-03 | FMEA rules SOLE interpretation | M-25/M-26; no attribution imports | ✅ mechanism / ⚠ LIM-030: at the measured r ≈ 0.95 the rule base cannot discriminate between mechanisms on this dataset | Ch2 §2.7 motivates knowledge-based route — aligned |
| LOCKED-04 | Chronological validation only | M-13 + `SplitPolicyGuard` (Guard 3) | ✅ | Ch1/Ch2 silent; Ch3 expected to specify — UNKNOWN detail |
| LOCKED-05 | Exogenous-only predictors | M-14 validator; `fit_model` chokepoint with a meta-test forbidding any other `.fit(` caller | ✅ | Ch2 §2.4 evidence (Felgueira 2019; Wang 2018) — aligned |
| LOCKED-06 | No target-derived features (Guard 8) | M-14; `CausalSeparationError`; negative tests parametrised over every transform class | ✅ | Ch2 Table 2.2 flags lagged-target NARX precedent as coupled — aligned |
| LOCKED-07 | No SHAP/XAI anywhere | Structural absence; MAPE meta-test over the models layer | ✅ | **⚠ Ch1 Objective 2 still conflicts as drafted — ADR-006, open since 2026-08-11, chapter not yet corrected.** Ch2's critique of attribution supports the lock |
| LOCKED-08 | No synthetic fault labels | Fixture policy; every fixture docstring carries the watermark | ✅ | Not addressed in Ch1/Ch2 (software-side constraint) |
| LOCKED-09 | "Causal separation" register | M-14 vocabulary; user-facing docs reviewed | ✅ | Ch1/Ch2 use "causal separation"/"causal structure" — aligned |
| LOCKED-10 | Out of scope: oil debris, pressure differentials, deployment, SHAP | No implementing modules | ✅ absence | Ch2 mentions oil-debris only as CMS-side context — aligned |

> **Guard coverage note (added 2026-08-18, ADR-041).** Of the eight PROJECT.md
> §33 guards, seven fire on real runs. Guard 5 did not: it inspected only
> `known_fault_period` windows, which no caller constructs on this dataset, so
> every run reported an empty findings list that read as a clean check. Its
> scope now includes ADR-024 designated event spans. A guard that cannot fire
> is not a guard, and the alignment table should not have implied otherwise.

## 5. Expected inputs and outputs

**Inputs (Chapter 1 Table 1-2 + candidate Kelmarsh census):** 10-minute SCADA
channels — wind speed, rotor/generator speed, active power, pitch angle,
nacelle and ambient temperatures, gearbox oil temperature, gearbox/HSS
bearing temperatures; alarm/status logs; maintenance records.
UNKNOWN pending Chapter 3 + Phase 0.5: final dataset identity and turbine
selection, exact channel mapping, source timezone, event ground-truth format
and tiers, labelled gearbox event count.

**Outputs:** NBM accuracy tables with CIs and DM tests; raw/normalized/EWMA
residual series; coordinated state sequences; matched-FPR operating curves;
DiagnosticEvents with candidate mechanisms (hypothesis language only); event
evaluation with lead times; sensitivity analyses; thesis exports (PROJECT.md §31).

## 6. Evaluation requirements

Fixed by Chapter 1 §1.5 + PROJECT.md: quantitative detection evaluation
against maintenance/alarm records where event count permits (Phase 0.5 rule);
matched-FPR comparison for RQ2 (§25, M-23); blocked bootstrap CIs and
Diebold–Mariano tests (§19, M-28); event-level metrics incl. lead time and
false-alarm rate — the two indicators Chapter 1 O4 names explicitly (M-27);
sensitivity analysis over provisional parameters (§27.3); descriptive-only
fallback below the event threshold.

## 7. Knowledge sources for the FMEA layer (Chapter 2 §2.7)

Chapter 2 Table 2.3 assembles the literature seed mapping for M-25 rules:
gear-teeth wear (sustained positive load-dependent oil-temp residual, bearing
lag), HSS bearing failure (bearing residual leads, oil smaller/later),
LSS/planetary bearing failure (weak oil-only signature unless instrumented),
lubrication degradation (broad simultaneous positive residuals), electrical/
generator-side influence (generator-side residuals without gearbox-led
ordering — exclusion pattern). Sources: Qiu et al. 2014/2016; Bangalore &
Tjernberg 2015; Shafiee & Dinmohammadi 2014; Feng et al. 2013 (Table 2.4:
three of five gearbox failure modes share the oil-temperature signature).

Constraints Chapter 2 itself records, inherited by the rule base: FMEA
risk-priority knowledge is subjective; SCADA ground truth cannot confirm
mechanisms → plausibility-only evaluation (§3 scope boundary); rules ship
`validated: false` until the ADR-005 sign-off cites the specific source.

## 8. Open decisions (Chapter 3: unwritten vs undecided)

Chapter 3 does not exist yet, and its blocking content is the **decisions**
it must state, not the prose. Those decisions are enumerated in
[CHAPTER3_DECISION_QUEUE.md](CHAPTER3_DECISION_QUEUE.md) (D-01…D-14),
grouped by the evidence that closes each (LITERATURE / CENSUS / EXPERIMENT)
and sorted by viva risk, with the queue's stop condition stated at its top.

Undecided ≠ unwritten: everything in §§1–7 above is already fixed by
Chapters 1–2 and the PROJECT.md locks; only queue items remain open.
Provisional parameters keep their PROJECT.md values with markers intact
until the author closes the corresponding item in docs/DECISIONS.md. The
five-phase methodology narrative itself (Chapter 1 §1.6 reference) remains
unwritten but adds no software requirement beyond the queued decisions.
