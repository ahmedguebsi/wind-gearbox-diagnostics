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

Module IDs refer to IMPLEMENTATION_PLAN.md. Status: ✅ implemented, 🔜 planned.

| Lock | Constraint | Implementing component(s) | Status | Thesis-text alignment |
|------|-----------|---------------------------|--------|----------------------|
| LOCKED-01 | Multi-target XGBoost is THE thesis NBM | M-16 (`model_kind == THESIS`, sole THESIS registrant); xgboost mandatory dep | 🔜 (dep ✅) | Ch1 RQ1 model-agnostic wording; locked form governs (§3 above) |
| LOCKED-02 | EWMA + control limits PRIMARY | M-20; `DetectionConfig.method` admits only `"ewma"` | 🔜 (config lock ✅) | Ch2 §2.3 grounds EWMA-on-residuals (Lu & Reynolds 1999) — aligned |
| LOCKED-03 | FMEA rules SOLE interpretation | M-25/M-26; no attribution imports | 🔜 | Ch2 §2.7 motivates knowledge-based route — aligned |
| LOCKED-04 | Chronological validation only | M-13 + `SplitPolicyGuard` | 🔜 (error type ✅) | Ch1/Ch2 silent; Ch3 expected to specify — UNKNOWN detail |
| LOCKED-05 | Exogenous-only predictors | M-14 validator | 🔜 | Ch2 §2.4 evidence (Felgueira 2019; Wang 2018) — aligned |
| LOCKED-06 | No target-derived features (Guard 8) | M-14; `CausalSeparationError` | 🔜 (error type ✅) | Ch2 Table 2.2 flags lagged-target NARX precedent as coupled — aligned |
| LOCKED-07 | No SHAP/XAI anywhere | Structural absence + CI scans | ✅ absence / 🔜 scan | **⚠ Ch1 Objective 2 conflicts as drafted — ADR-006, pending author correction.** Ch2 critique of attribution supports the lock |
| LOCKED-08 | No synthetic fault labels | Fixture policy; Guard 6 watermarking | 🔜 | Not addressed in Ch1/Ch2 (software-side constraint) |
| LOCKED-09 | "Causal separation" register | M-14 vocabulary test; docs review | 🔜 | Ch1/Ch2 use "causal separation"/"causal structure" — aligned |
| LOCKED-10 | Out of scope: oil debris, pressure differentials, deployment, SHAP | No implementing modules | ✅ absence | Ch2 mentions oil-debris only as CMS-side context — aligned |

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

## 8. UNKNOWN — blocked on Chapter 3 (methodology)

- The five-phase methodology structure and per-phase specifics (Ch1 §1.6
  references it; text not yet available)
- Final healthy-state exclusion values (provisional in config until §27.3
  sensitivity + Ch3 justification)
- Chronological split periods / fractions for thesis experiments
- EWMA λ and control-limit choices and their Ch3 justification
- Normalization statistics source — ADR-001 remains OPEN
- The operational FMEA rule base content and thresholds (Ch2 Table 2.3 is the
  seed; Ch3 "formalises these implied signatures into an operational rule
  base" per Ch2 §2.7)
- Event-matching windows and ground-truth tier definitions
- Dataset selection and census values (Phase 0.5 gate, also blocking)
