# EXPERIMENT_PROTOCOL.md — Frozen Experimental Protocol

> **STATUS: PROPOSED (2026-08-16).** This document states the controlled
> protocol under which model comparisons are run, so that a difference between
> two experiments is attributable to the **model**, not to uncontrolled
> preprocessing or evaluation changes. It records what is already implemented
> and what is proposed; proposed items are marked and require an author ruling
> in `docs/DECISIONS.md` before they bind.
>
> Governing rule, unchanged: only the author closes decisions (PROJECT.md §34).

---

## 1. Why this document exists

Different preprocessing and pipeline decisions produce substantially different
results. Without a frozen protocol, a comparison between two models silently
becomes a comparison between two pipelines. This file fixes every component
that is **not** the object of study, so the object of study is isolated.

The enforcement mechanism already exists: every experiment stores a resolved
configuration and its SHA-256 hash. **Two experiments are comparable only if
their config hashes differ solely in the `model` section.**

---

## 2. The pipeline, stage by stage

```text
DATASET → PREPROCESSING → FEATURE SET → SPLIT → TRAINING → TUNING
        → MODEL → RESIDUALS → DETECTION → EVALUATION
```

| Stage | Status | Frozen value |
|-------|--------|--------------|
| Dataset | FROZEN | Kelmarsh, 6 turbines, 2016-05-03 → 2021-06-30 (ADR-009); 36 SCADA + 36 status CSVs; SHA-256 verified per file at every run |
| Cleaning | FROZEN | Four ordered operations: `drop_unparseable_timestamps` → `drop_missing_any_target` → `nullify_impossible_predictor_values` → `drop_missing_any_predictor` (ADR-020). Every removal audited with before/after counts |
| Imputation | FROZEN — none | No interpolation anywhere. An interpolated predictor is a fabricated model input; an interpolated target is a fabricated residual |
| Input scaling | FROZEN — none | Gradient-boosted trees are scale-invariant. Required only if a regularised linear model is admitted (see §6) |
| Outlier removal | FROZEN — none beyond schema bounds | Only values the schema declares physically impossible are acted on. Statistical (IQR/z-score) removal is prohibited: it deletes the excursions the system exists to detect |
| Resampling / augmentation / balancing | FROZEN — none | Regression on healthy data; no classes exist to balance. Resampling would break the temporal structure the blocked bootstrap relies on |
| Dimensionality reduction | FROZEN — none | Seven physically-named predictors; PCA would destroy the causal interpretability Guard 8 and the FMEA layer depend on |
| Healthy-state config | FROZEN per experiment series | All 11 parameters at their ADR values. Varied **only** inside the M-27 sensitivity suite, never inside a model comparison |
| Feature set | FROZEN per arm | 7 exogenous predictors, 2 thermal targets. Ablation arms are separate labelled experiments, never mixed into one comparison |
| Split | FROZEN | Chronological explicit dates, no shuffling: TRAIN < 2018-07-01 ≤ VALIDATION < 2019-02-01 ≤ TEST (ADR-023). Healthy-state filtering on TRAIN+VALIDATION only; TEST stays unfiltered for detection |
| Residual definition | FROZEN | `residual = actual − predicted`, per target |
| Normalization | FROZEN | MAD (×1.4826), statistics fitted on TRAIN (ADR-001 default) |
| Detection | FROZEN | EWMA λ=0.2, steady-state limits, persistence 3 samples (ADR-017b) |
| Evaluation | FROZEN | Three labelled accuracy periods (ADR-022); matched-FPR operating curves; blocked bootstrap + Diebold–Mariano |
| Seed | FROZEN | 42 everywhere |
| Bootstrap | FROZEN | 1000 replicates, seed 42 |
| Tuning budget | FROZEN | The 12 pre-registered candidates (ADR-021) |
| **Model family** | **VARIES** | The object of comparison |
| **Hyperparameters within the grid** | **VARIES** | Selected by the frozen protocol, recorded per candidate |

---

## 3. Leakage controls, and how each is enforced

| Vector | Control | Enforcement |
|--------|---------|-------------|
| Test data reaching model fitting | Tuning API accepts only train and validation frames | Structural — no parameter exists through which test data could enter |
| Future information in features | Lag/difference steps must be ≥1; rolling windows trailing and ≥2 | Guard 2 raises |
| Target information in inputs | No lag, rolling statistic, difference or transform of any target | Guard 8 raises; fail-closed on unresolvable sources |
| Threshold statistics from non-healthy data | Normalizer and control-limit fits validate their source partition | Guard 4 raises |
| Random splitting on a thesis run | Split strategy validated before any file is opened | Guard 3 raises |
| Known failure interval surviving into training | Window-match check | Guard 5 emits a WARNING finding |
| Scaler fitted across the split boundary | Not applicable today (no scaling) | Would arise only with a regularised linear model — fit on TRAIN only |

**Open leakage issue (PROPOSED fix, §6):** the healthy VALIDATION block
currently performs four jobs — scoring the 12 tuning candidates, supplying the
early-stopping signal, providing the M-20 in-control characterisation, and (if
ADR-001 closes to `validation`) supplying threshold statistics. The first two
are *selection*; the last two are *calibration*. Performing both on one block
calibrates detection thresholds on data the model was selected to fit well,
which biases the measured in-control false-alarm rate downward.

---

## 4. Minimum experiment matrix

The smallest set that supports the thesis claims. Anything not listed here
produces numbers without evidence and should not be run.

### Baselines (required)

| ID | Experiment | Supports | Rationale |
|----|-----------|----------|-----------|
| B1 | Linear reference NBM | RQ1 | Establishes how much thermal variance is linear in operating conditions versus captured non-linearly (ADR-002) |
| B2 | Single-signal union monitoring | RQ2 | The pre-registered comparison baseline (ADR-016) |
| B3 | Fleet-median-only detector — *no NBM at all* | RQ2 | **DONE 2026-08-18** (ADR-046) — `--arms b3`. **Outcome: comparable to the NBM throughout, and BETTER on the oil target** (residual σ 2.255 vs 2.578 °C; bearing 2.446 vs 2.076). Same ~60× in-control inflation in both arms. Registered as LIM-031 |
| B4 | Persistence-only detector — threshold + persistence, no EWMA | RQ2 | PROPOSED. Isolates what the EWMA smoothing actually contributes. The M-21 comparators exist and are tested but have never been exercised by any run script |

### Main approach (required)

| ID | Experiment | Supports |
|----|-----------|----------|
| M1 | Multi-output XGBoost NBM, three-period accuracy | RQ1 |
| M2 | Coordinated two-target detection at matched false-alarm points | RQ2 |
| M3 | EVENT-001 descriptive case study at selected operating points | RQ2 secondary, RQ3 |

### Ablations (required)

| ID | Ablation | Supports | Status |
|----|----------|----------|--------|
| A1 | With / without `nacelle_temperature` | RQ1 predictor defence | **DONE** (ADR-027) — outcome recorded; artifacts deleted, regenerate before citing |
| A2 | Fleet-relative residuals, leave-one-out median | RQ2, LIM-023 | REGISTERED (ADR-029) — implemented, default off, **not run** |
| A3 | Upstream lag features vs none | RQ1 | PROPOSED |
| A4 | Per-turbine vs pooled residual statistics | RQ2 | MEASURED, not decided. `residual_diagnostics` reports centre spread at 0.87–0.93 pooled scales; P-5 ("justify or abandon pooling") remains open |
| A5 | Coordination threshold 1-of-2 vs 2-of-2 at matched rates | RQ2 | **DONE 2026-08-19** (ADR-048) — re-run under the ADR-028 row-time denominator on EXP-20260818-001. **Outcome: the ADR-016 criterion is predominantly NOT MET** — 6 met of 22 evaluable pairs across λ ∈ {0.1, 0.2, 0.3}. The denominator correction did not change the direction of the pre-registered conclusion. Symmetry check passed at all three λ |
| A6 | Orthogonal common/differential modes vs raw channels | RQ2, RQ3 | **DONE 2026-08-19** (ADR-035) — `--arms orthogonal`, base EXP-20260818-001. **Outcome: the rotation holds in-control and collapses on monitoring.** Mode correlation 9.1e-17 on training, −0.065 on validation, **0.835 on the monitoring stream**; 2-of-2 coordination reaches 10 FA/ty at multiplier 4.54 vs 12.62 for 1-of-2 (raw channels: 10.76 vs 12.96) — the coordination rule does work once the streams are independent, but only in-regime. Detection value UNTESTED by declaration (condition c). Registered as LIM-037 |
| A7 | Block-bootstrap vs analytic EWMA control limits | RQ2 detection validity | PROPOSED (ADR-034) — registered, not run |
| A8 | Multi-output vs one-model-per-target | RQ1 | **DONE 2026-08-18** (ADR-046) — `--arms multi_output`. **Outcome: indistinguishable** — bearing 2.1647 vs 2.1611, oil 2.6904 vs 2.7155; each wins one target, both margins an order of magnitude below the CI half-width. The headline architectural choice buys no accuracy. Registered as LIM-032 |
| A9 | Seed variance on the final model | RQ1 | **DONE 2026-08-18** (ADR-046) — `--arms seeds`, seeds 42/7/2024. **Outcome: the margin holds.** Seed spread 0.0051 / 0.0115 °C against margins of 0.4007 / 0.2310 over OLS — 79× and 20×. The RQ1 accuracy claim is not a seed artefact |

### Sensitivity (required)

| ID | Experiment | Status |
|----|-----------|--------|
| S1 | M-27 suite over the 11 provisional parameters | **DONE** |
| S2 | Isolated/sustained boundary at 2/3/5/10 samples | **DONE** (exploratory) |
| S3 | Boundary extended to 12 and 20 samples | **DONE 2026-08-19** (ADR-048) — literature-anchored values (Nogueira et al. 2025: 20 samples; CARE: 72). **Outcome: the verdict does not flip — it hardens.** At λ=0.2 the "met" verdicts vanish entirely at boundaries 10, 12 and 20; at λ=0.3 they fall from 3 to 0. Answers the LIM-020 construct-validity concern |
| S4 | Every error and detection figure split by operating regime | **DONE 2026-08-19** (ADR-047) — LIM-034 mitigation (a). `scripts/run_regime_split.py`, artifact-only. **Outcome: the RQ1 ordering holds in-regime** (thesis 2.1867 vs OLS 2.5911 bearing); the unfiltered-slice DM reversal is explained (92.6% of thesis test-slice squared error from 17.9% of rows); the direction asymmetry is measured (out-of-regime low:high 8.9:1 vs in-regime 1.9:1). **It does NOT reduce the in-control inflation and cannot** — that block is in-regime by construction. Registered as LIM-035 |

### Explicitly NOT commissioned

Rolling-origin evaluation (declined under ADR-022 — it measures how well the
*method* generalises, not how well *this model* represents healthy behaviour);
LSTM/transformer/autoencoder/GNN architectures; transfer learning across
turbines; AUC-ROC or AUC-PR reporting. Reasons are recorded in
`docs/METHODOLOGY_REVIEW.md`.

---

## 5. Reporting rules

1. **The pre-registered verdict is stated first, always.** Exploratory or
   alternative-boundary analyses follow it and are labelled post-hoc.
2. **Every accuracy figure carries its confidence interval.** The comparison
   layer refuses a bare number by construction.
3. **Nominal targets are reported beside measured rates.** The gap is the
   finding, not a caveat on it.
4. **Unvalidated FMEA rules carry the Guard 7 banner** into every artifact.
5. **`inferential_allowed` is false** while the labelled event count is below
   the pre-committed threshold; the detection-rate accessor raises rather than
   returning a number.

---

## 6. Proposed changes to this protocol

> **STATUS (updated 2026-08-19): all seven are RATIFIED AND EXECUTED.** The
> table below is retained unchanged as the record of what was proposed and
> what effect was predicted BEFORE measurement — which is the point of writing
> predictions down. Ratifying ADRs: P-1 → ADR-028, P-2 → ADR-030,
> P-3 → ADR-029/§P-3 wiring, P-4 → ADR-031, P-5 → measured (A4, still
> undecided), P-6 → ADR-035, P-7 → ADR-032.
>
> **Predictions scored against measurement:**
> - **P-1 held.** Denominator unified; the RQ2 verdict direction was UNCHANGED
>   by the correction (ADR-048), so the defect was real but not verdict-bearing.
> - **P-3 held.** Panel intervals widened per turbine — but the significance
>   claim did NOT weaken as predicted: the oil-target CIs went from overlapping
>   to DISJOINT, and two bearing-target BASELINE intervals were disqualified for
>   too few blocks. The correction strengthened RQ1.
> - **P-4 resolved against its own hedge.** It predicted the boundary "may
>   change the RQ2 verdict". It does not change it — it HARDENS it (ADR-048).
> - **P-6 held exactly.** r = 0.932–0.952 (ADR-035): no metric changed, and the
>   meaning of the RQ2 result changed completely.
> - **P-7 held.** The margin narrowed against Elastic Net relative to OLS, and
>   the thesis model still wins 6/6 turbines on bearing (p ≤ 8.88e−16).
>
> **P-1, P-3 and P-6 were marked blocking for any cited result. All three are
> now discharged**, which is what makes the ADR-048 verdict citable.

Each required an author ruling before it bound. Full reasoning and literature
basis in `docs/METHODOLOGY_REVIEW.md`.

| # | Proposed change | Reason | Expected effect on reported numbers |
|---|-----------------|--------|-------------------------------------|
| P-1 | Unify the false-alarm denominator on **row-time** in both comparison arms | The validation curves currently divide alarm episodes by calendar span while the monitoring-slice check divides by observed row-time | Validation false-alarm rates **rise**; the validation-to-monitoring gap **narrows**. A correction, not a regression |
| P-2 | Move tuning and early stopping to **blocked forward-chaining CV inside TRAIN**; reserve VALIDATION for calibration only | Separates selection from calibration (§3) | In-control false-alarm rate **rises** honestly; thresholds loosen |
| P-3 | Compute blocked bootstrap and Diebold–Mariano **per turbine**, with HAC lags set from measured autocorrelation | The loss series currently interleaves six turbines; the default lag rule covers far less time than the residual dependence | Intervals **widen**; the significance claim weakens |
| P-4 | Report persistence at **12 and 20 samples** alongside the pre-registered 3 | Published practice uses 20 (≈3.3 h) and 72 (≈12 h); ours is 30 minutes | May **change** the RQ2 verdict. Report both; never substitute |
| P-5 | Measure and report **per-turbine residual centre and scale**; justify or abandon pooling | Pooling is acceptable but must be justified, not defaulted | Redistributes alarms across machines; total rate roughly stable |
| P-6 | Compute **residual-to-residual correlation** between the two targets | Decides whether coordination adds independent evidence — the premise of RQ2 | No metric change; determines what the RQ2 result *means* |
| P-7 | Admit a **regularised linear reference** (Elastic Net) alongside OLS | The literature recommends it as the simple reference; OLS is a weaker comparator | Likely **narrows** the XGBoost margin |

**P-1, P-3 and P-6 are blocking for any cited result.** P-1 and P-3 change
numbers that later analyses consume; P-6 changes their interpretation.

---

## 7. Note on expected direction of effect

Five of the seven proposed changes are expected to make the project's numbers
**worse**: stricter denominators, wider intervals, higher measured in-control
false-alarm rates, a narrower model margin, and likely a reduced or eliminated
apparent detection lead under the fleet-relative arm.

They should be adopted regardless. A methodology that reports having weakened
its own headline in the interest of validity is more defensible than one that
does not, and each change corrects a measurement rather than trading accuracy
for rigour.
