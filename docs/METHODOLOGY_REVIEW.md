# METHODOLOGY_REVIEW.md — Literature Position and Replicate/Adapt/Discard Record

> **STATUS: PROPOSED (2026-08-16).** An independent methodological review of
> the implemented pipeline against the 2023–2026 literature, produced after a
> source-level audit of the repository at commit `7df11f9`.
>
> **Nothing here is a closed decision.** The project rule stands: only the
> author closes items, recorded in `docs/DECISIONS.md` (PROJECT.md §34). The
> proposals in §5 are drafted in the ADR template so they can be ratified,
> revised, or rejected without rewriting them.

---

## 1. Provenance of this review

Two inputs, both dated 2026-08-15/16:

1. **Source audit** of the working tree at `7df11f9` — all 80 Python modules,
   configuration, tests, CI, and the committed evidence artefacts. Census
   figures in `docs/evidence/` were independently re-derived and matched the
   prose in `DATASET_DUE_DILIGENCE.md` exactly.
2. **Literature investigation**, priority 2023–2026. Six papers retrieved and
   read in full text (marked *primary* below); eight reachable only by
   abstract or index record (marked *secondary* — **verify before citing**).

Two limits on this review, stated so they are not mistaken for findings:

- **The test suite was not executed.** The reviewing environment has neither
  `uv` nor the scientific stack. The "378 tests / 96% coverage" figures are
  quoted from `SESSION_STATUS.md`, not observed. Static count: 375 `def test_`
  functions plus 5 parametrised decorators, consistent with that claim.
- **No experiment artefact was inspected.** `artifacts/` is excluded from git
  by design, so every quantitative claim in the project's own documents was
  taken as reported. Expected directions of effect below are reasoned from the
  mechanism in the code, not measured.

---

## 2. Reference set

| Ref | Work | Grade |
|-----|------|-------|
| P1 | Chesterman, Verstraeten, Daems, Nowé, Helsen (2023). *Overview of normal behavior modeling approaches for SCADA-based wind turbine condition monitoring.* Wind Energy Science 8(6):893. DOI 10.5194/wes-8-893-2023 | primary |
| P2 | Gück, Roelofs, Faulstich (2024). *CARE to Compare: a real-world dataset for anomaly detection in wind turbine data.* arXiv:2404.10320; Data 9(12):138 | primary |
| P3 | Fiocchi, Ladopoulou, Dellaportas (2024, rev. 2025). *Probabilistic Multi-Layer Perceptrons for Wind Farm Condition Monitoring.* arXiv:2404.16496 | primary — **same dataset** |
| P4 | Nogueira, Melani, de Souza (2025). *Wind Turbine Fault Detection Through Autoencoder-Based Neural Network and FMSA.* Sensors 25(14):4499 | primary |
| P5 | Nair, Babu, Panthakkan, Balusamy, Mansoor (2025). *Hybrid Autoencoder-Based Framework for Early Fault Detection in Wind Turbines.* arXiv:2510.15010 | primary |
| P6 | Tautz-Weinert, Watson (2017). *Using SCADA data for wind turbine condition monitoring — a review.* IET RPG 11(4) | secondary |

Also surfaced, secondary grade: multi-output GPR for gearbox oil temperature
(Machines 14(4):386, 2025); CNN-LSTM-attention HSS temperature prediction
(JMSE 13(7):1337, 2025); Random Forest multi-scale gearbox NBM (Mechanics &
Industry, 2024); CUSUM-LoMST gearbox detection on EDP data (Frontiers in
Energy Research 10:904622, 2022); fine-tuned transformer encoder claiming
100% turbine-level accuracy (ScienceDirect, 2026 — **claim requires
verification before use**).

---

## 3. The one paper using our dataset

P3 is the only confirmed publication on the Kelmarsh holdings. The comparison
matters more than the shared source suggests.

| Dimension | P3 | This project |
|-----------|----|--------------|
| Period | 2016-01-03 → 2021-07-01 | 2016-05-03 → 2021-06-30 (gear-oil channels are null before that date) |
| Rows after filtering | 846,968 across six turbines; 163,562 for the single modelled turbine | ~1.73 M pooled pre-clean |
| Turbines modelled | All six as features; **one** as prediction target | All six, pooled into one model |
| Features | 41 operational and environmental variables, selection not justified in the paper | 7 exogenous predictors, guard-enforced |
| **Target** | **Active power (kW)** | **Two gearbox temperatures (°C)** |
| Healthy filtering | Standby, warnings and operational stops removed; week before each forced outage removed | Alarm windows with populated ends, 50 kW floor, 30 d fault pre-window, named artefact/event spans |
| Split | Chronological 80/20, but **training set shuffled before validation selection** | Chronological explicit dates, no shuffling anywhere |
| Detector | CUSUM, k=1/2, decision interval raised from theoretical I=5 to empirical I=15 | EWMA λ=0.2, multiplier raised from 3σ to 10–21σ empirically |
| Fault events | **22** — tower oscillation, yaw/fan overload, pitch control malfunctions | **1** — gearbox-indexed with usable preceding thermal coverage |
| Detection result | 17/22 detected; precision 0.68, recall 0.77; mean lead 15.49 h | Descriptive case study; inferential claims gated off in code |

**The 22-versus-1 discrepancy is a scope difference, not a contradiction.** P3
counts all fault types across the turbine; this project counts gearbox-indexed
events that also have usable preceding thermal coverage. Both are correct for
their respective questions, and the stricter definition is what triggered the
pre-committed descriptive branch (ADR-014).

It also surfaces a strategic option not yet evaluated: widening the ground
truth to **drivetrain-level** events while keeping the thermal-coverage
requirement might reach the ≥2 threshold. This is **not** a licence to redefine
after the fact — the existing rule was fixed before results and stands. It
would be a separate, clearly-labelled analysis with its own pre-registration,
and P3 is the precedent for the wider definition.

**Two independent teams, same dataset, same conclusion on thresholds.** P3
raised its CUSUM decision interval threefold above theory; this project raised
its EWMA multiplier to 10–21σ. Both abandoned theoretical control limits on
serially correlated SCADA residuals. This convergence materially strengthens
ADR-026 and should be cited there.

---

## 4. Replicate / adapt / discard / add — summary

Thirty-three methodological steps were adjudicated. Decisions were made on
scientific defensibility, **not** on which choice raises the metric.

### Keep — already correct and better justified than the alternative

- Chronological splitting with no shuffling anywhere. P3 shuffles before
  selecting validation, which on an autocorrelated 10-minute series places
  near-duplicate observations on both sides of the selection boundary.
- Causal separation of predictors from targets. Every comparator feeds
  component temperatures as model inputs; none discusses the risk that an
  NBM consuming its own target's history tracks fault-driven drift and
  suppresses the residual. This is a deliberate divergence from the whole
  literature and it is defensible.
- Audited cleaning with per-operation row accounting. No comparator reports
  this; several do not report missing-value handling at all.
- Matched false-alarm operating points with full curves. Strictly more
  rigorous than the fixed-percentile thresholds used in P4.
- Pre-registered tuning grid with a recorded evaluated-configuration count —
  a multiple-comparison control no comparator implements.
- Fixed seed and deterministic refits. **No primary paper reports a seed
  policy**, and only P1 reports a systematic hyperparameter search.
- The small-n gate that raises rather than returning a detection rate.

### Adapt — retain the idea, change the implementation

| Step | Change | Basis |
|------|--------|-------|
| False-alarm denominator | One definition (row-time) across both comparison arms | Internal defect: validation curves use calendar span, the slice check uses row-time |
| Selection vs calibration | Tuning and early stopping to blocked CV inside TRAIN; VALIDATION reserved for calibration | P2 holds out a dedicated calibration portion |
| Bootstrap and DM | Per turbine, HAC lags from measured autocorrelation | The loss series interleaves six turbines |
| Persistence boundary | Report 12 and 20 alongside the pre-registered 3 | P4 uses 20 samples; P2 requires 72 |
| Residual statistics | Measure per-turbine centre/scale; justify or abandon pooling | P1 pools **with stated rationale and caveat**; we pool without either |
| Fault pre-exclusion sweep | Extend to 120 days | P1 excludes 4 months before failures |

### Discard — do not implement

| Step | Reason |
|------|--------|
| Component temperatures as inputs | Would raise accuracy and destroy detection sensitivity. Structurally blocked by Guard 8 |
| Statistical (IQR) outlier removal (P4) | Deletes the excursions the system exists to detect; narrows the healthy envelope and inflates monitoring residuals — higher metrics for the wrong reason |
| Missing-value interpolation (P1, P4) | An interpolated predictor is a fabricated input; an interpolated target is a fabricated residual |
| Random k-fold cross-validation (P1) | Leaks by construction on a temporally dependent series |
| Hourly aggregation (P1) | Destroys the 10-minute resolution the event-matching and persistence design depends on. P1 aggregates because it trains on ~6 months; we have 26 |
| PCA / dimensionality reduction (P2) | Seven physically-named predictors; would destroy the causal interpretability Guard 8 and the FMEA layer require |
| AUC-ROC / AUC-PR (P5) | Threshold-free ranking metrics say nothing about alarm volume at a deployable operating point. **P2's authors argue against them for this task** |
| LSTM / transformer / autoencoder / GNN (P5) | Their advantage is exploiting target history, which Guard 8 forbids; adopting them would either violate the methodology or waste the architecture. An autoencoder additionally emits a scalar reconstruction error, not the per-target signed residuals the coordinated state vector requires |
| Transfer learning across turbines (P3) | Six turbines; pooling plus fleet-relative features achieves the same end without a per-turbine selection surface |

### Add — missing and strongly justified

| Step | Justification | Priority |
|------|---------------|----------|
| Residual-to-residual correlation between the two targets | Decides whether coordination adds independent evidence — the premise of RQ2. Measured by no comparator | **Blocking** |
| Leave-one-out fleet-relative residual arm | P1's fleet-median subtraction directly targets the confounder recorded in LIM-023 | High — see §5 ADR-029 |
| Fleet-median-only detector baseline | If deviation from the fleet median matches the full pipeline, that is a first-order finding | High |
| Regularised linear reference (Elastic Net) | P1's actual recommendation; OLS is a weaker comparator than the paper being cited | Medium |
| CARE-style score decomposition as a supplement | Makes our results externally comparable for the first time | Medium |
| Upstream lag features as a declared ablation | Gearbox oil has thermal inertia; Guard 2 permits trailing lags of upstream variables. Never tested | Medium |
| Three-seed variance check on the final model only | Without it there is no answer to whether the model margin exceeds seed noise | Low |

---

## 5. Proposed decisions, in ADR template

> **RATIFIED 2026-08-17.** All four were closed by author ruling and now
> live in `docs/DECISIONS.md` as ADR-028, ADR-029, ADR-030 and ADR-031,
> which are the authoritative entries. The drafts below are retained as
> the record of what was put to the author, unchanged; where they differ
> in wording from the closed entries, DECISIONS.md governs.

Drafted for author ruling. Numbering continues from ADR-027.

### ADR-028 (PROPOSED) — Unify the false-alarm rate denominator

**Question.** The matched-FPR framework measures observation time as calendar
span (`_turbine_years`, `app/detection/matched_fpr.py`), while the sweep
script's out-of-period check measures it as observed row-time
(`slice_rate`, `scripts/run_matched_fpr_sweep.py`). The healthy validation
block is gap-filled by exclusion, so its span exceeds its row-time and the
validation false-alarm rate is understated relative to the slice rate it is
compared against.

**Options.** (a) row-time in both arms; (b) calendar span in both arms;
(c) retain both, reporting each explicitly.

**Evidence to close.** Re-run the sweep under (a) and record the change in the
selected multipliers and in the LIM-021 ratio.

**Consequence if adopted.** Validation false-alarm rates rise; the selected
operating point becomes stricter; the validation-to-monitoring transfer gap
narrows by an amount that must be measured, not assumed. The ADR-025 operating
points would be restated.

**Affected.** M-23, `scripts/run_matched_fpr_sweep.py`, ADR-025, LIM-021.

---

### ADR-029 (PROPOSED) — Fleet-relative residuals as a registered ablation arm

**Question.** P1 subtracts the cross-turbine median per signal before
modelling, removing farm-common components. LIM-023 records that the
EVENT-001 detection was a fleet-wide environmental response. Should the
pipeline adopt fleet-relative residuals?

**Decision sought.** Adopt as a **registered ablation arm**, not as a
replacement for the headline pipeline, with the expected direction of effect
stated **before** the run: fewer false alarms, and a reduced or eliminated
apparent lead on EVENT-001.

**Why an arm and not a swap.** The confounder was discovered *from results*.
Changing the preprocessing in response and then reporting only the new
pipeline would be post-hoc pipeline selection — the practice this project's
pre-registration discipline exists to prevent. Run as a declared arm, the
comparison itself becomes the contribution: a measurement of how much of a
coordinated thermal excursion is farm-common environmental response.

**Implementation requirements.** (a) **Leave-one-out** median, so the event
turbine never contributes to its own reference. (b) Declare explicitly that
fleet-relative residuals use contemporaneous cross-turbine information —
legitimate for single-turbine faults, invalid for a fault mode affecting the
whole farm, and the distinction must be stated wherever the arm is reported.

**Affected.** M-19a/M-19b, M-30, LIM-023, Chapter 5.

---

### ADR-030 (PROPOSED) — Separate model selection from threshold calibration

**Question.** The healthy VALIDATION block currently performs four jobs:
scoring the 12 tuning candidates, supplying the early-stopping signal,
providing the M-20 in-control characterisation, and — under one branch of the
open ADR-001 — supplying threshold statistics. The first two are selection;
the last two are calibration.

**Concern.** Detection thresholds calibrated on data the model was explicitly
selected to fit well will show an optimistically low in-control false-alarm
rate, yielding thresholds that are too tight. This is a candidate mechanism
for the LIM-021 transfer gap that the register does not currently list, and it
is separable at zero data cost.

**Decision sought.** Move tuning and early stopping to blocked
forward-chaining cross-validation **inside TRAIN**; reserve VALIDATION
exclusively for threshold calibration and in-control characterisation.

**Consequence if adopted.** The measured in-control false-alarm rate rises
honestly; thresholds loosen; the LIM-021 gap is expected to narrow.

**Affected.** M-15/M-16 (tuning chokepoint), M-30 (runner partitions),
ADR-001, ADR-021, LIM-021.

---

### ADR-031 (PROPOSED) — Persistence boundary reported at literature-anchored values

**Question.** `persistence_min_samples` is 3 (30 minutes). P4 requires 20
consecutive samples (≈3.3 h); P2 requires 72 (≈12 h) before declaring a
false-alarm event. Ours is an order of magnitude shorter than published
practice, and it defines the isolated/sustained boundary that decides the
ADR-016 criterion.

**Decision sought.** The pre-registered verdict at 3 samples **stands as
computed and is reported first, always**. Extend the existing exploratory
boundary sweep (2/3/5/10) to include 12 and 20 with the literature citation
attached, reported as post-hoc.

**Why not simply change it.** Adopting 20 and presenting the result as the
pre-registered answer would be indefensible. If the verdict flips at
literature-standard persistence, that is a finding about the criterion's
construct validity — already registered as LIM-020 — and belongs in Chapter 5
as such.

**Affected.** ADR-016, ADR-017(b), LIM-020, M-27.

---

## 6. Proposed limitations-register entries

Drafted for author ruling; numbering continues from LIM-023.

### LIM-024 (PROPOSED) — False-alarm rates compared across two denominators

**Description.** The validation operating curves divide alarm episodes by
calendar span while the monitoring-slice check divides by observed row-time.
Because the healthy validation block is gap-filled by exclusion, the two
numbers compared in LIM-021 are not commensurable, and the operating point
selected in ADR-025 sits on the understated side.
**Affected RQ(s).** RQ2 (operating-point selection and every false-alarm claim).
**Mitigation status.** OPEN — proposed ADR-028.
**Source.** Source audit 2026-08-15; `matched_fpr.py` `_turbine_years` vs
`run_matched_fpr_sweep.py` `slice_rate`.

### LIM-025 (PROPOSED) — Selection and calibration share one validation block

**Description.** The healthy validation block scores tuning candidates,
supplies early stopping, and provides the in-control characterisation.
Thresholds are therefore calibrated on data the model was selected to fit,
biasing the measured in-control false-alarm rate downward. This is a fifth
candidate explanation for the LIM-021 transfer gap, not listed there, and
unlike the other four it is separable within the existing data.
**Affected RQ(s).** RQ2 (threshold provenance and transfer behaviour).
**Mitigation status.** OPEN — proposed ADR-030.
**Source.** Source audit 2026-08-15; `runner.py` `_fit_and_predict` and
`_residual_stages`.

---

## 7. Defensibility notes for Chapter 3

Short answers to the questions an examiner is most likely to ask.

**"Why not an LSTM or transformer, given the recent literature?"** Their
advantage is modelling long-range dependence in the target's own history, and
the causal-separation constraint prohibits target-derived inputs. Adopting
them would either violate the constraint or waste the architecture.

**"Paper X reports AUC 0.947; you report no AUC."** Deliberately. The authors
of the benchmark that paper uses argue that threshold-free ranking metrics
have no significance in an operational predictive-maintenance setting. We
report matched false-alarm operating curves, which is the quantity an operator
acts on.

**"P3 found 22 fault events in this dataset; you found one."** They count all
fault types; we count gearbox-indexed events with usable preceding thermal
coverage. Both are correct for their questions, and our stricter definition is
what triggered the pre-committed descriptive branch.

**"Why chronological splitting rather than cross-validation?"** Random k-fold
on a 10-minute series with strong autocorrelation places near-duplicate
observations on both sides of every fold boundary. The one paper using our
exact dataset shuffles before selecting validation; we do not.

**"Your persistence threshold is 30 minutes; published work uses 3–12 hours."**
Correct, and we report the consequence at 3, 12 and 20 samples, with the
pre-registered verdict stated first.

**"Isn't a negative RQ2 result a failed thesis?"** No. It is a pre-registered
test of a premise the literature widely assumes and, as far as our search
established, has never tested at matched false-alarm operating points.

---

## 8. What this review does not establish

- Whether the test suite passes. Not executed here.
- Any quantitative effect of the proposed changes. The artefacts required to
  measure them are not in the repository.
- Whether more papers use the Kelmarsh dataset. One was confirmed; absence of
  further evidence is weak evidence of absence, and several publishers blocked
  retrieval.
- Anything about the eight secondary-grade references beyond what their
  abstracts and index records state.
