# THESIS_REQUIREMENTS.md — Software Requirements Source of Truth

> **STATUS: BLOCKED — AWAITING THE THESIS DOCUMENT.**
> PROJECT.md §1 requires this document to be derived from the MSc thesis
> (research problem, gaps, objectives, RQs, expected inputs/outputs,
> methodological constraints, evaluation requirements, assumptions,
> unresolved decisions). The thesis document has not yet been provided to the
> repository. Requirements must not be invented (PROJECT.md §1: "Do not
> invent requirements that contradict the thesis"). The sections below are
> the mandated structure, populated only with what PROJECT.md itself fixes.

## 1. Research questions (from PROJECT.md §3)

- **RQ1** — How accurately can a multi-target XGBoost Normal Behaviour Model
  represent healthy gearbox thermal behaviour using SCADA data?
- **RQ2** — Do coordinated residual patterns across thermally coupled signals
  provide more useful diagnostic evidence than monitoring each signal
  independently — compared at matched false-alarm operating points?
- **RQ3** — Can FMEA-informed interpretation enrich anomaly alerts with
  physically plausible candidate failure mechanisms?

## 2. Methodology Alignment Table (LOCKED constraint → implementing components)

Module IDs refer to IMPLEMENTATION_PLAN.md. Status: ✅ implemented, 🔜 planned.

| Lock | Constraint | Implementing component(s) | Status |
|------|-----------|---------------------------|--------|
| LOCKED-01 | Multi-target XGBoost is THE thesis NBM | M-16 `models.xgboost_nbm` (`model_kind == THESIS`, sole THESIS-kind registrant); xgboost is a mandatory dependency (`backend/pyproject.toml`) | 🔜 (dependency ✅) |
| LOCKED-02 | EWMA + control limits is the PRIMARY treatment | M-20 `residuals.ewma`; `DetectionConfig.method` admits only `"ewma"` today (`app/core/config.py`) | 🔜 (config lock ✅) |
| LOCKED-03 | FMEA rules are the SOLE interpretation mechanism | M-25/M-26 `fmea.*`; no statistical-attribution imports (dependency scan) | 🔜 |
| LOCKED-04 | Chronological validation only | M-13 `data.splitting` + `SplitPolicyGuard` (Guard 3); `SplitPolicyError` in `app/core/errors.py` | 🔜 (error type ✅) |
| LOCKED-05 | Exogenous-only predictors | M-14 `data.guards` FeatureConfigurationValidator | 🔜 |
| LOCKED-06 | No target-derived features (Guard 8) | M-14 `data.guards`; `CausalSeparationError` in `app/core/errors.py` | 🔜 (error type ✅) |
| LOCKED-07 | No SHAP/XAI anywhere | Structural absence: no `explainability/` module, no SHAP dependency in `pyproject.toml`; CI scans (M-36) | ✅ (absence) / 🔜 (scan) |
| LOCKED-08 | No synthetic fault labels | Fixture policy (ARCHITECTURE.md §11.2); Guard 6 watermarking | 🔜 |
| LOCKED-09 | "Causal separation" register in user-facing text | M-14 message-vocabulary test; docs review | 🔜 |
| LOCKED-10 | Out of scope: oil debris, pressure differentials, deployment, SHAP | No implementing modules exist; scope guarded by review | ✅ (absence) |

## 3. Expected inputs and outputs — **awaiting thesis**

To be extracted from the thesis Chapter 3 and the Phase 0.5 dataset census
(`docs/DATASET_DUE_DILIGENCE.md`, not yet written).

## 4. Evaluation requirements — **awaiting thesis**

Fixed so far by PROJECT.md: matched-FPR comparison for RQ2 (§25), blocked
bootstrap CIs and Diebold-Mariano tests (§19), event-based evaluation with
small-n descriptive fallback (§27.2), sensitivity analysis (§27.3).

## 5. Assumptions, limitations, unresolved decisions

Tracked in `docs/LIMITATIONS.md` and `docs/DECISIONS.md` respectively.
