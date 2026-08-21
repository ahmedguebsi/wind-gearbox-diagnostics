# PROJECT.md — CLAUDE CODE MASTER SPECIFICATION (REVISED v2.0)
# MSc Thesis — Wind Turbine Gearbox Diagnostic Application

**Revision status:** v2.0 — incorporates all 18 accepted panel-review recommendations.
**Supersedes:** CLAUDE_CODE_MASTER_PROMPT.md (v1.0).
**Authority:** THE THESIS METHODOLOGY IS AUTHORITATIVE. Where this specification and the thesis Chapter 3 methodology conflict, the thesis wins, and the conflict must be reported — never silently resolved.

We are starting this project FROM ZERO. No existing application should be assumed to exist.

I have provided the MSc thesis document. Read it carefully before writing code.

Your task is to design and implement the software required to execute the thesis methodology:

**SCADA-Based Wind Turbine Gearbox Condition Monitoring using Multi-Target Normal Behaviour Modelling, Coordinated Thermal Residual Analysis, and an FMEA-Informed Interpretation Layer.**

The software must allow us to conduct the MSc experiments, evaluate the research questions, visualize the results, and generate reproducible outputs for the thesis.

Do not treat assumptions as facts. Decisions the thesis leaves open remain configurable until real data and Chapter 3 establish them. Decisions the thesis has LOCKED (Section 0) are not configurable.

---

# 0. LOCKED METHODOLOGY CONSTRAINTS (NON-NEGOTIABLE)

These are fixed by the dissertation methodology. The software must implement them as its destination, not as options.

```text
LOCKED-01  The thesis NBM is a MULTI-TARGET XGBoost model (RQ1).
           Other models exist only as baselines/comparators.

LOCKED-02  EWMA smoothing of residuals with statistical control limits
           is the PRIMARY persistence/anomaly treatment (thesis Phase 3).
           Consecutive-exceedance and rolling-window rules are
           comparators only.

LOCKED-03  FMEA-informed rules are the SOLE interpretation mechanism (RQ3).

LOCKED-04  Chronological time-series validation ONLY.
           Random train/test splitting is prohibited for thesis experiments.

LOCKED-05  Predictors are EXOGENOUS ONLY (causally upstream of the
           thermal targets).

LOCKED-06  No target-derived features. No lagged target temperatures.
           "Thermal-lag-aware features" means lagged/rolled UPSTREAM
           variables (e.g., lagged active power, lagged rotor speed),
           NEVER lagged oil or bearing temperatures.

LOCKED-07  SHAP / XAI attribution is OUT OF SCOPE and must not appear
           anywhere in the thesis evidence chain, the pipeline, the
           exports, or the dashboard.

LOCKED-08  No synthetic fault labels. Synthetic data exists only as
           clearly-marked software test fixtures.

LOCKED-09  Causal predictor–target separation is a robustness/design
           principle that produces physically meaningful residuals.
           In code comments, docs, and reports, do not describe it as
           a "leakage crisis" or a research gap. Internal validator
           names may use "leakage" as a software term; user-facing
           documentation uses "causal separation".

LOCKED-10  Out of thesis scope entirely: oil debris analysis, oil
           pressure differentials, deployment packaging, SHAP/XAI.
```

---

# 1. UNDERSTAND THE RESEARCH FIRST

Before writing application code, extract from the thesis:

- research problem, gaps, objectives, and research questions
- expected inputs and outputs
- methodological constraints (cross-check against Section 0)
- evaluation requirements
- assumptions and limitations
- unresolved methodological decisions

Create:

```text
docs/THESIS_REQUIREMENTS.md
```

This document is the software requirements source of truth. It MUST include a **Methodology Alignment Table**: every LOCKED constraint mapped to the software component(s) that implement or enforce it.

Also create:

```text
docs/DECISIONS.md
```

An Architecture/Methodology Decision Record (ADR) log. Every open methodological decision gets an entry with: status (OPEN / CLOSED), options, evidence required to close it, and — when closed — the Chapter 3 justification.

Also create and maintain from day one:

```text
docs/LIMITATIONS.md
```

A living register of every known threat to validity discovered during development (data quality issues, small event counts, seasonal coverage shortfalls, sensor artefacts, evaluation caveats). Each entry: description, date discovered, affected research question(s), mitigation status. This file feeds the thesis limitations/discussion chapter directly.

Do not invent requirements that contradict the thesis.

---

# 2. CORE RESEARCH PIPELINE

```text
Raw SCADA data
        ↓
Provenance capture (SHA-256, source record)
        ↓
Schema mapping (versioned canonical schema)
        ↓
UTC timestamp normalization
        ↓
Data validation (incl. step-change / recalibration detection)
        ↓
Data cleaning (audit-trailed)
        ↓
Operating-state filtering
        ↓
Healthy-state construction
        ↓
Causal predictor/target separation (exogenous-only enforcement)
        ↓
Chronological train/validation/test split (+ seasonal coverage check)
        ↓
Multi-target XGBoost Normal Behaviour Model
        ↓
Expected healthy thermal behaviour
        ↓
Actual − Expected
        ↓
Multi-target residual streams
        ↓
Residual normalization
        ↓
EWMA smoothing + statistical control limits  ← PRIMARY
        ↓
Single-signal anomaly detection
        ↓
Coordinated multi-signal detection
        ↓
Residual pattern characterization
        ↓
FMEA-informed interpretation
        ↓
Candidate physical failure mechanisms
        ↓
Comparison with alarm/maintenance records
        ↓
Matched-FPR comparison, sensitivity analysis, statistical testing
        ↓
Research metrics, confidence intervals, and visualizations
```

This pipeline is the heart of the application.

---

# 3. RESEARCH QUESTIONS

### RQ1
How accurately can a multi-target **XGBoost** Normal Behaviour Model represent healthy gearbox thermal behaviour using SCADA data?

### RQ2
Do coordinated residual patterns across thermally coupled signals provide more useful diagnostic evidence than monitoring each signal independently — compared **at matched false-alarm operating points**?

### RQ3
Can FMEA-informed interpretation enrich anomaly alerts with physically plausible candidate failure mechanisms?

Every major implementation decision should support one or more of these questions.

---

# 4. DO NOT BUILD A NORMAL CRUD WEB APPLICATION

Priority order:

```text
Scientific validity
↓
Reproducibility
↓
Data correctness
↓
Experiment management
↓
Evaluation
↓
Visualization
↓
UI polish
```

Do not spend early stages on login screens, user management, animations, dashboards, or microservices. The dashboard carries zero thesis assessment weight; it is a late-stage convenience only.

---

# 5. TECHNOLOGY STACK

## Scientific/backend

```text
Python 3.12 (pinned exact version)
XGBoost            ← mandatory core dependency (thesis model, LOCKED-01)
Pandas
NumPy
scikit-learn       (baselines, metrics, utilities)
SciPy
statsmodels        (EWMA control charts, Diebold–Mariano support, autocorrelation)
Pydantic
PyYAML
joblib
PyArrow / Parquet
Matplotlib
Plotly where interactive plots are useful
FastAPI            (late milestone only)
```

REMOVED from stack: SHAP (LOCKED-07).

Optional later comparator only (with ADR justification): LightGBM. Deep learning is prohibited (Section 39).

## Tooling (mandatory from Phase 1)

```text
uv (or pip-tools)  → committed lockfile
ruff               → lint + format
mypy               → type checking
pytest + coverage
pre-commit         → hooks running ruff/mypy on commit
GitHub Actions     → CI on every push/PR: lint, type-check, full test suite
```

## Database

SQLite for metadata only (datasets, experiment records, model records, evaluation runs). Large SCADA data: CSV for import, Parquet internally. Do not put millions of SCADA observations into SQLite.

## Frontend

Do NOT start with the frontend. Later: React + TypeScript, Vite, FastAPI REST, Plotly. Keep frontend and scientific code separated.

---

# 6. INITIAL PROJECT STRUCTURE

```text
wind-gearbox-diagnostics/
│
├── .github/workflows/        # CI pipeline (mandatory, Phase 1)
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/             # config, logging, versioning
│   │   ├── data/             # ingestion, schema, validation, cleaning, provenance
│   │   ├── models/           # NBM abstraction, XGBoost, baselines
│   │   ├── experiments/      # tracking, reproduction
│   │   ├── residuals/        # residual engine, normalization, EWMA
│   │   ├── detection/        # thresholds, coordinated analysis, matched-FPR
│   │   ├── fmea/             # knowledge base + interpretation engine
│   │   ├── evaluation/       # event evaluation, bootstrap CIs, DM tests,
│   │   │                     # sensitivity analysis
│   │   └── services/
│   ├── tests/
│   ├── pyproject.toml
│   └── uv.lock               # committed lockfile (mandatory)
│
├── frontend/                 # created later
├── configs/
├── data/
│   ├── raw/                  # never modified; hashed at ingestion
│   ├── processed/
│   └── README.md             # data provenance + access conditions
├── artifacts/
├── docs/                     # THESIS_REQUIREMENTS.md, DECISIONS.md,
│                             # LIMITATIONS.md, ARCHITECTURE.md
├── scripts/
├── README.md
├── .pre-commit-config.yaml
├── .gitignore
└── docker-compose.yml only when actually useful
```

NOTE: there is deliberately NO `explainability/` module (LOCKED-07).

Do not create dozens of empty classes merely to match this structure. Create modules as they become needed.

---

# 7. MILESTONE 1 — PROJECT AND RESEARCH FOUNDATION

Implement FIRST:

- Git repository
- Python 3.12 pinned; environment created via uv; **`uv.lock` committed**
- backend package
- pytest + coverage configuration
- ruff + mypy + pre-commit hooks
- **GitHub Actions CI**: on every push/PR run lint, type-check, and the full test suite; a red pipeline blocks merging
- configuration loading
- structured logging
- README with exact reproduction commands
- `.env.example` if environmental settings exist

Environment reproducibility requirement: a fresh machine must reach a green test suite with exactly:

```text
git clone → uv sync → pytest
```

---

# 7.5 PHASE 0.5 — DATASET DUE-DILIGENCE GATE (BLOCKING)

Before any modelling-adjacent work (healthy-state construction onward), perform a formal census of the candidate real dataset(s) and STOP for review.

Produce `docs/DATASET_DUE_DILIGENCE.md` containing:

```text
turbine count and identifiers
total duration and date range per turbine
sampling interval(s)
available thermal channels (oil temperature, bearing temperature, others)
available upstream predictor channels
alarm/status record availability and format
maintenance record availability and format
COUNT OF LABELLED GEARBOX EVENTS (the binding constraint)
timezone and DST behaviour of timestamps
known data quality issues
licensing / redistribution conditions
```

Decision rule recorded in `docs/DECISIONS.md`:

```text
≥ 2 independent labelled gearbox events
    → quantitative event-based evaluation design is viable

< 2 labelled gearbox events
    → evaluation is pre-committed to a DESCRIPTIVE CASE-STUDY design;
      no inferential detection-rate or lead-time claims;
      LIMITATIONS.md updated accordingly
```

This gate exists so the evaluation design is chosen BEFORE results exist, not after. Do not proceed past this gate without explicit approval.

---

# 8. CANONICAL SCADA DATA MODEL (VERSIONED)

We do not yet know the real dataset's exact column names. DO NOT hard-code dataset-specific names.

Create a canonical SCADA schema with an explicit **schema version**:

```yaml
schema_version: 1.0.0
```

- Every dataset mapping, every processed Parquet file, and every experiment record stores the schema version it was produced under.
- Schema changes bump the version (semver) and are logged in `docs/DECISIONS.md`.
- Loading data produced under an older schema version raises a clear warning.

Variable roles:

```text
timestamp
turbine_id
predictor
target
status
alarm
maintenance
excluded
```

Likely upstream predictors (thesis-identified):

```text
wind speed, rotor speed, generator speed, active power,
pitch angle, ambient temperature, nacelle temperature
```

Thermal targets include at least:

```text
gearbox oil temperature
gearbox bearing temperature
```

Actual names must come from the dataset. Implement a mapping layer:

```yaml
schema_version: 1.0.0

dataset:
  timestamp_column: TimeStamp
  turbine_column: TurbineID
  source_timezone: Europe/London     # MANDATORY field

columns:
  WindSpeedAvg:
    canonical: wind_speed
    role: predictor
    unit: m/s
  ActivePowerAvg:
    canonical: active_power
    role: predictor
    unit: kW
  GearOilTemp:
    canonical: gearbox_oil_temperature
    role: target
    unit: C
```

## UTC normalization (mandatory)

- All timestamps are converted to UTC at ingestion using the declared `source_timezone`.
- All internal storage, splitting, residual computation, and evaluation operate on UTC.
- DST transitions are handled explicitly: autumn fold-back duplicates and spring gaps are detected and reported in the DatasetReport, never silently dropped.
- If `source_timezone` is unknown, ingestion STOPS and asks — do not guess.

---

# 9. CAUSAL SEPARATION (GUARDED)

The NBM uses variables causally upstream from the thermal targets — this is the thesis's causal-separation design principle (LOCKED-05, LOCKED-09), ensuring residuals are physically meaningful.

Create a feature-validation system. It must reject:

- the target itself as a predictor
- future target values
- **any target-derived feature (lags, rolling statistics, differences, transforms of any thermal target)** — Guard 8
- thermally downstream variables
- information unavailable at inference time

Thermal-lag-aware feature engineering is permitted ONLY on upstream variables:

```text
ALLOWED:     lagged active power, rolling-mean rotor speed,
             lagged ambient temperature
PROHIBITED:  lagged gearbox oil temperature,
             rolling gearbox bearing temperature,
             oil-temperature differences
```

Rationale (record in code docstring): an autoregressive NBM tracking its own target follows slow fault-driven drift and suppresses exactly the residual signal the thesis is designed to detect.

```python
validate_feature_configuration(predictors, targets)
```

raises on any violation. Tests are mandatory, including tests that deliberately attempt each prohibited feature class.

---

# 10. DATASET INGESTION AND PROVENANCE

Ingestion supports CSV and Parquet initially (XLSX later if required).

## Data provenance (mandatory)

At ingestion, record for every raw file:

```text
SHA-256 hash
original filename and path
file size
ingestion timestamp (UTC)
declared source timezone
schema version and mapping config used
who/what supplied the file (free-text provenance note)
```

Provenance records are stored in SQLite and echoed into every downstream experiment's metadata. `data/README.md` documents dataset origin, licensing, and access conditions so the thesis data-availability statement is honest. Raw files are never modified.

## DatasetReport

On load, generate:

```text
number of rows / columns
date range (UTC)
number of turbines
sampling intervals
missing values
duplicate timestamps
duplicate turbine/timestamp combinations
invalid timestamps
DST duplicates and gaps
data gaps
constant columns
low-variance columns
possible sensor anomalies (incl. step changes — Section 11)
```

Never silently clean the source file.

---

# 11. DATA VALIDATION

Reusable validation rules.

### Timestamps
- parsing failures, duplicates, incorrect order, irregular sampling, large gaps
- **timezone/DST checks**: fold-back duplicates, spring-forward gaps, mixed-offset timestamps

### Sensors
- missing observations, constant sensors, impossible values, obvious outliers, sudden unrealistic jumps
- **step-change / recalibration detection**: detect sustained level shifts in temperature channels (e.g., rolling-median change-point heuristic). A sensor replacement or recalibration produces a step that mimics or masks a fault. Detected steps are reported with timestamp and magnitude, flagged for healthy-state review, and logged to LIMITATIONS.md if unresolved. They are NEVER auto-corrected.

### Turbine
- missing IDs, inconsistent identifiers

### Research schema
- missing targets, missing configured predictors, duplicated roles, causal-separation violations

Findings returned as INFO / WARNING / ERROR. Do not simply delete invalid observations.

---

# 12. DATA CLEANING

Configurable, audit-trailed cleaning pipeline. Each operation records:

```text
rule, number of affected rows, reason, before count, after count
```

The cleaned dataset must remain traceable to the raw dataset (via provenance hash chain).

---

# 13. HEALTHY-STATE DATASET CONSTRUCTION

`HealthyStateBuilder` supports exclusion based on:

```text
known fault periods
alarm periods
maintenance periods
shutdown
invalid operating states
sensor failure and detected step-change windows
possible curtailment
time preceding known failures
time immediately after maintenance
```

Rules configurable:

```yaml
healthy_state:
  exclude_alarm_periods: true
  fault_pre_exclusion_days: 30        # provisional; sensitivity-tested (Section 27)
  maintenance_post_exclusion_days: 2  # provisional; sensitivity-tested
  operating_conditions:
    minimum_active_power: 50          # provisional; sensitivity-tested
```

Final values need research justification (Chapter 3 + sensitivity analysis).

Generate `HealthyStateReport`: totals, accepted, excluded, retention %, exclusion reason counts, date ranges, turbines.

---

# 14. CHRONOLOGICAL SPLITTING (WITH SEASONAL COVERAGE CHECK)

Random shuffled splits are prohibited for thesis experiments (LOCKED-04).

```text
healthy training period → healthy validation period → test/monitoring period
```

```yaml
split:
  strategy: chronological
  train_fraction: 0.70
  validation_fraction: 0.15
  test_fraction: 0.15
```

Also support explicit dates. Prevent overlapping periods.

## Seasonal coverage check (mandatory)

After any split, automatically verify and report:

```text
- training window duration in months
- calendar-month coverage of the training window
- ambient temperature range covered by training vs. test
```

Emit WARNING if the training window spans < 12 months or lacks seasonal coverage present in the test window, with the explicit note: residual inflation in the test period may reflect seasonal covariate shift rather than degradation. Warnings are logged to LIMITATIONS.md.

Support rolling-origin (blocked time-series) splits as an optional evaluation mode for RQ1 accuracy estimates where data volume allows.

---

# 15. EXPERIMENT SYSTEM

Every experiment stores:

```text
experiment ID, creation timestamp (UTC)
dataset ID/version and SHA-256 provenance chain
schema version
turbine IDs, date range
predictors, targets
cleaning configuration
healthy-state configuration
split configuration + seasonal coverage report
model type, hyperparameters
random seed for EVERY stochastic component (model seed, subsample seed,
    bootstrap seed) — one global seed is insufficient
library versions (python, numpy, pandas, scikit-learn, xgboost, scipy,
    statsmodels) captured at runtime
residual configuration
EWMA configuration (λ, control-limit definition)
threshold configuration
FMEA ruleset version
metrics
git commit hash
```

Experiment directory:

```text
artifacts/
└── EXP-YYYYMMDD-001/
    ├── config.yaml
    ├── metadata.json          # includes provenance, versions, seeds
    ├── metrics.json           # includes CIs and test statistics
    ├── model/
    ├── predictions/
    ├── residuals/
    ├── plots/
    └── evaluation/
```

## Experiment reproduction command (mandatory)

Implement:

```text
python -m app.experiments reproduce EXP-YYYYMMDD-001
```

Behaviour:
1. Rebuilds the environment expectation check (warns on library-version mismatch vs. stored metadata).
2. Re-runs the experiment from its stored config against the hashed dataset.
3. Diffs regenerated metrics against stored `metrics.json`.
4. Reports EXACT MATCH / TOLERANCE MATCH / MISMATCH.

A reproducibility test in CI runs this on a small fixture experiment and asserts exact prediction match. We must be able to reproduce a thesis result months later.

---

# 16. STOP POINT FOR MILESTONE 1

Verify we can:

1. load a SCADA-like dataset with provenance capture
2. map its columns under a versioned schema
3. normalize timestamps to UTC with DST handling
4. validate it (including step-change detection)
5. clean it with an audit trail
6. identify candidate healthy observations
7. separate predictors and targets (exogenous-only enforced)
8. reject every prohibited feature class (Guard 8 tests)
9. create chronological splits with seasonal coverage reporting
10. save experiment metadata and reproduce a fixture experiment

Synthetic data may be used ONLY to test software functionality, labelled:

```text
SYNTHETIC TEST DATA — NOT VALID THESIS EVIDENCE
```

Synthetic FAULT LABELS are prohibited in all contexts (LOCKED-08) — fixtures test mechanics (thresholds fire, rules match), never detection performance claims.

---

# 17. MILESTONE 2 — NORMAL BEHAVIOUR MODELLING

Common model interface:

```python
class NormalBehaviourModel:
    def fit(self, X, y): ...
    def predict(self, X): ...
    def save(self, path): ...
    @classmethod
    def load(cls, path): ...
```

The architecture allows algorithms to change without rewriting the pipeline — but the destination is fixed (Section 18).

---

# 18. MODELS — XGBOOST MANDATORY, BASELINES AS COMPARATORS

**The thesis NBM is multi-target XGBoost (LOCKED-01). This is not open.**

Implement (amended 2026-08-11 per ADR-002; supersedes the earlier
three-model list of Random Forest plus a literature-anchored baseline):

```text
1. XGBoost multi-target NBM        ← THE thesis model
2. Multiple linear regression on the same exogenous predictors
                                   ← the single BASELINE comparator
```

The model set is exactly two. The baseline exists to contextualize XGBoost performance for RQ1, never to replace it: it establishes how much thermal variance is linear in operating conditions versus captured non-linearly, and thereby indicates how much residual spread is irreducible physics rather than modelling error. It is a measuring stick for residual trustworthiness, not a model competition — linear regression is the minimal reference that does this, with no hyperparameters and no architecture decisions. Bangalore & Tjernberg's (2015) NARX ANN was considered and NOT reimplemented: its lagged-target inputs violate Guard 8 (see ADR-002 for the full reasoning an examiner may ask for).

Hyperparameter tuning happens on the healthy validation block only; the number of configurations evaluated is recorded in experiment metadata (silent multiple-comparison guard). The baseline has nothing to tune, so it contributes no configurations to that count.

Multi-target strategy: support (A) native multi-output and (B) one-model-per-target as an ablation; the thesis headline model is the multi-target configuration.

Deep learning remains prohibited.

---

# 19. NBM METRICS

Per thermal target:

```text
RMSE
MAE
R²
bias (mean error)
```

**MAPE is REMOVED for temperature targets.** Celsius is an interval scale; percentage error relative to °C is physically meaningless and unstable near 0 °C. Do not compute or report it. (If a genuinely ratio-scaled variable ever enters scope, MAPE may be reconsidered via ADR.)

## Blocked bootstrap confidence intervals (mandatory)

All headline accuracy metrics are reported with confidence intervals from a **moving-block bootstrap** on the chronologically ordered test residuals (block length chosen from residual autocorrelation, recorded in config). Naive i.i.d. bootstrap is prohibited for time-series residuals.

## Diebold–Mariano testing (where appropriate)

Model-vs-model accuracy comparisons (XGBoost vs. each baseline, per target) use the **Diebold–Mariano test** on the loss-differential series with autocorrelation-robust (HAC) variance. Report DM statistic and p-value alongside the metric table. Where series are short or assumptions are strained, report descriptively and log the caveat to LIMITATIONS.md rather than forcing a test.

Store predictions: timestamp (UTC), turbine_id, actual, predicted, model, experiment_id.

---

# 20. MODEL DIAGNOSTICS

Plots:

```text
actual vs predicted
prediction error distribution
prediction over time
error vs active power
error vs wind speed
error vs ambient temperature   ← doubles as the seasonal-shift diagnostic
```

We need to know whether model error changes by operating condition (heteroscedasticity check feeding normalization design).

---

# 21. MILESTONE 3 — RESIDUAL ENGINE

*(Former SHAP milestone removed per LOCKED-07. Model physical-credibility discussion in the thesis rests on causal predictor selection and the diagnostics of Section 20, not on XAI attribution.)*

For every target:

```text
residual = actual − expected_healthy_value
```

Preserve: timestamp (UTC), turbine, target, actual, prediction, raw residual, normalized residual. Never overwrite raw residuals after normalization.

---

# 22. RESIDUAL NORMALIZATION

Configurable alternatives:

```text
standard deviation based
robust MAD based
quantile / percentile based
condition-binned variants (per power/ambient bin) if heteroscedasticity
    diagnostics justify them
```

Normalization and threshold statistics must come from HEALTHY data only. Never from fault/test periods.

OPEN ADR (docs/DECISIONS.md, flagged by review, awaiting Chapter 3 confirmation): whether normalization statistics are computed on the healthy TRAINING block (as v1.0 specified) or the healthy VALIDATION block (reviewer-recommended, to avoid in-sample optimism from training residuals being biased small). Implement both as configuration; the thesis choice is closed via the ADR, not silently in code.

---

# 23. EWMA — PRIMARY PERSISTENCE/ANOMALY TREATMENT

**EWMA smoothing of normalized residuals with statistical control limits is the PRIMARY method (LOCKED-02, thesis Phase 3).** It is not one candidate among several.

Implement:

```yaml
detection:
  method: ewma                 # PRIMARY — thesis methodology
  ewma_lambda: 0.2             # provisional; sensitivity-tested
  control_limit_sigma: 3       # provisional; sensitivity-tested
  normalization: mad           # configurable per Section 22
```

Requirements:
- EWMA control limits use the standard EWMA control-chart variance formulation (steady-state and time-varying limit options).
- Because 10-minute thermal residuals are serially correlated, the effective in-control false-alarm behaviour must be measured empirically on the healthy validation block and reported — do not assume i.i.d. theoretical ARL holds. Record findings in LIMITATIONS.md if limits require widening.
- Raw and normalized residual series are preserved alongside EWMA series.

Comparators (implemented for the comparison study, clearly labelled NON-PRIMARY):

```text
consecutive threshold exceedances
N anomalies within rolling window
rolling residual mean
```

Threshold families remain configurable (2σ/3σ/MAD/percentiles) with the final choice justified by evidence and Chapter 3.

---

# 24. MILESTONE 4 — COORDINATED THERMAL RESIDUALS

Central thesis contribution. Do not evaluate thermal residuals only independently.

Multi-target representation:

```text
gearbox_oil_temperature:     EWMA residual = +3.1 → state HIGH
gearbox_bearing_temperature: EWMA residual = +2.7 → state HIGH
```

Coordinated state: `[HIGH, HIGH]` / numerically `[+1, +1]` where −1 = abnormally low, 0 = normal, +1 = abnormally high. Preserve continuous residuals alongside discrete states.

---

# 25. SINGLE VS MULTI-TARGET DETECTION — MATCHED-FPR COMPARISON

Two explicit pipelines against the same data and event records:

```text
Baseline:  single-signal EWMA residual monitoring
Proposed:  coordinated multi-target EWMA residual monitoring
```

## Matched false-alarm-rate methodology (mandatory)

Comparing raw alarm counts at arbitrary thresholds is confounded by threshold choice. Therefore:

1. For each pipeline, sweep the detection threshold/control-limit parameter across a defined grid.
2. Measure the false-alarm rate of each configuration on healthy (non-event) periods.
3. Compare pipelines **at matched false-alarm operating points** (e.g., equal false alarms per turbine-year).
4. At each matched point report: detected events, missed events, lead time, alarm persistence/duration.
5. Report the full operating curves, not just one point.

Do not design the evaluation so multi-target automatically wins. The experiment must be fair, and the matched-FPR design is what makes it fair.

Where the event count is below the Phase 0.5 quantitative threshold, the comparison is reported descriptively per the pre-committed case-study design, with the matched-FPR framework still used to structure the narrative.

---

# 26. MILESTONE 5 — FMEA KNOWLEDGE BASE AND INTERPRETATION ENGINE

FMEA-informed rules are the SOLE interpretation mechanism (LOCKED-03). No statistical attribution methods substitute for or supplement them in the thesis evidence chain.

Structured rules (YAML/JSON), never scattered if/else:

```yaml
rules:
  - id: FMEA-001
    mechanism: bearing_friction_or_degradation
    residual_pattern:
      gearbox_bearing_temperature: { state: HIGH }
      gearbox_oil_temperature:     { state: HIGH }
    confidence: preliminary
    rationale: >
      Coordinated positive thermal deviations may be physically
      compatible with increased mechanical losses.
    source: TBD            # must eventually cite Evidence Bank literature
    validated: false
```

Rules without literature validation display `PRELIMINARY — DEMONSTRATION ONLY — NOT SCIENTIFICALLY VALIDATED`. The `validated` flag flips only through a documented sign-off recorded in docs/DECISIONS.md, citing the specific literature source. Never invent references.

Interpretation engine — input: continuous residuals, discrete states, EWMA/persistence information, operating conditions. Output: candidate mechanism(s), matched rule(s), supporting evidence, contradictory evidence, confidence category, rationale.

Never output "Confirmed bearing failure." Candidate mechanisms are hypotheses.

---

# 27. MILESTONE 6 — EVENTS, EVALUATION, AND SENSITIVITY ANALYSIS

## 27.1 Alarm and maintenance events

Canonical event structures: alarms, status codes, maintenance, known failures, component replacement, inspection. Keep anomaly-detection ground truth separate from mechanism-level diagnostic ground truth (different reliability).

## 27.2 Event-based evaluation

Event-level (not only point-level) metrics: detected events, missed events, false alarm events, first detection timestamp, known event timestamp, detection lead time (known event time − first persistent anomaly time; positive = early detection), duration, number of alarms.

Small-n reporting policy: below the Phase 0.5 event threshold, event metrics are reported descriptively with no inferential claims; the constraint is stated in LIMITATIONS.md and the thesis.

## 27.3 Sensitivity analysis (dedicated phase, mandatory)

Systematically vary and report detection-outcome stability across:

```text
fault_pre_exclusion_days        (e.g., 15 / 30 / 60)
maintenance_post_exclusion_days
minimum_active_power floor
EWMA λ
control-limit multiplier
normalization method (σ / MAD / percentile)
```

Output: sensitivity tables + tornado-style summaries showing which parameters materially change conclusions. Parameters that flip conclusions are flagged in LIMITATIONS.md and discussed in the thesis. This converts the provisional configuration values of Sections 13 and 23 into defended choices.

---

# 28. MILESTONE 7 — RESEARCH COMPARISON

Automatic comparison experiments:

```text
XGBoost vs Random Forest vs literature baseline
multi-target vs per-target ablation
EWMA vs consecutive-exceedance comparators
σ vs MAD vs percentile normalization
matched-FPR operating curves
```

Auto-generated tables including CIs and DM results:

```text
Experiment | Model | RMSE Oil [CI] | RMSE Bearing [CI] | DM vs XGB (p) |
FA/turbine-yr | Detected | Missed | Median Lead Time
```

This later becomes thesis tables without manual number copying.

---

# 29. MILESTONE 8 — APPLICATION API (LATE)

Only after the scientific core works reliably. Areas: /datasets, /validation, /experiments, /models, /predictions, /residuals, /diagnostics, /events, /evaluation. Heavy training handled without blocking normal API usage; no distributed infrastructure.

---

# 30. MILESTONE 9 — WEB DASHBOARD (LAST, OPTIONAL)

React frontend, only after all thesis evidence exists. Sections: dataset (upload, mapping, quality report), healthy state (rules, periods, reasons), experiments (config, run, compare), model (metrics, actual-vs-predicted, feature importance — native XGBoost gain/cover importance only; NO SHAP views), residuals (actual/prediction/raw/normalized/EWMA/limits), coordinated analysis (synchronized multi-target plots), diagnostics (timestamp, severity, persistence, pattern, candidate mechanisms, evidence), events overlay (alarms, maintenance, known failures).

The dashboard carries zero thesis assessment weight. Any schedule pressure resolves in favour of Sections 17–28.

---

# 31. THESIS EXPORTS

Export: CSV, JSON, PNG, SVG where practical.

Artifacts: model metrics with CIs, DM test tables, experiment comparison, predictions, residual data (raw/normalized/EWMA), anomalies, matched-FPR operating curves, sensitivity tables, event evaluation, thermal plots, FMEA matches, configuration snapshots.

REMOVED: SHAP charts (LOCKED-07).

Eventually support publication/thesis-friendly tables.

---

# 32. TESTING

Every scientific component needs tests. CI runs them all on every push.

```text
Data:      schema mapping, schema-version handling, UTC/DST conversion,
           invalid timestamps, duplicates, missing columns,
           causal-separation violations (every Guard 8 feature class),
           step-change detection, healthy-state filtering,
           chronological splitting, seasonal coverage check
Models:    training, multi-output predictions, metric calculation
           (assert MAPE absent for temperature targets),
           model save/load, exact-match reproducibility
Residuals: actual − prediction, normalization variants, EWMA values and
           control limits against hand-computed references,
           threshold logic, persistence comparators, pattern encoding
Stats:     blocked bootstrap CI coverage on synthetic AR series,
           DM test against reference implementation
FMEA:      rule match, non-match, multiple matches, candidate ranking,
           unvalidated-rule labelling
Events:    event matching, false alarms, lead time, missed events,
           matched-FPR sweep mechanics
Repro:     `reproduce` command on fixture experiment → EXACT MATCH
API later: request validation, experiment lifecycle, endpoints
```

---

# 33. SCIENTIFIC GUARDS

### Guard 1 — A target cannot also be a predictor.
### Guard 2 — Known future information cannot enter model inputs.
### Guard 3 — Official thesis experiments cannot use random temporal splitting.
### Guard 4 — Normal-behaviour thresholds cannot be fitted using test/fault periods.
### Guard 5 — Known failure intervals trigger warnings if included in healthy training.
### Guard 6 — Synthetic results must display: `SYNTHETIC — NOT THESIS EVIDENCE`.
### Guard 7 — FMEA rules without literature validation must display: `UNVALIDATED RULE`.
### Guard 8 — **No target-derived features of any kind.** The feature validator rejects lagged targets, rolling/aggregate statistics of targets, target differences, and any transform of a thermal target used as model input. Thermal-lag awareness is implemented exclusively through lagged upstream variables. Violations raise errors; tests cover every prohibited class.

---

# 34. WHAT YOU MUST NOT DO

Do NOT:

- invent the real dataset, maintenance events, alarm records, FMEA literature, final threshold values
- **treat the ML algorithm as undecided — it is XGBoost (LOCKED-01)**
- **treat the persistence method as undecided — it is EWMA (LOCKED-02)**
- fabricate thesis results
- use synthetic results as research evidence
- **create synthetic fault labels under any circumstances (LOCKED-08)**
- violate causal separation (Guards 1, 2, 8)
- optimize on the test set
- use random temporal train/test splits
- **compute or report MAPE for temperature targets**
- **implement, import, or reference SHAP or any XAI attribution in the pipeline, exports, or dashboard (LOCKED-07)**
- claim plausible diagnoses are confirmed failures
- describe causal separation as a "leakage crisis" or research gap in any user-facing documentation (LOCKED-09)
- add deep learning, Kubernetes, microservices, Redis, queues, or cloud infrastructure
- spend significant effort on frontend polish before the research pipeline works
- proceed past the Phase 0.5 gate without approval
- close an OPEN item in docs/DECISIONS.md without recording the justification

---

# 35. IMPLEMENTATION ROADMAP (REVISED)

```text
PHASE 0     Read thesis; THESIS_REQUIREMENTS.md with Methodology
            Alignment Table; DECISIONS.md; LIMITATIONS.md
PHASE 0.5   DATASET DUE-DILIGENCE GATE (blocking; evaluation design
            pre-committed)
PHASE 1     Repository foundation: lockfile, ruff, mypy, pre-commit,
            pytest, GitHub Actions CI, logging, config
PHASE 2     Versioned canonical SCADA schema + mapping layer
PHASE 3     Ingestion + provenance capture (SHA-256) + UTC/DST
            normalization
PHASE 4     Dataset validation incl. step-change detection
PHASE 5     Cleaning pipeline (audit-trailed)
PHASE 6     Healthy-state construction
PHASE 7     Causal predictor validation (Guards 1–2, 8)
PHASE 8     Chronological splitting + seasonal coverage check
            (+ rolling-origin option)
PHASE 9     Experiment tracking + `reproduce` command
PHASE 10    EDA incl. residual autocorrelation, thermal channel
            cross-correlation, ambient dependence
PHASE 11    NBM abstraction
PHASE 12    XGBoost multi-target NBM (thesis model)
PHASE 13    Baselines: Random Forest + literature-anchored comparator
PHASE 14    Model metrics (no MAPE) + blocked bootstrap CIs +
            Diebold–Mariano comparisons + condition diagnostics
PHASE 15    Residual generation
PHASE 16    Residual normalization (incl. condition-binned option;
            ADR on statistics source)
PHASE 17    EWMA smoothing + control limits (PRIMARY) + empirical
            in-control false-alarm characterization
PHASE 18    Comparator persistence rules (non-primary)
PHASE 19    Coordinated multi-target residual representation
PHASE 20    Matched-FPR single-vs-multi comparison framework
PHASE 21    Structured FMEA knowledge base
PHASE 22    FMEA interpretation engine
PHASE 23    Alarm/maintenance event integration
PHASE 24    Event-based evaluation (+ small-n policy)
PHASE 25    Sensitivity analysis suite
PHASE 26    Experiment comparison + auto-generated thesis tables
PHASE 27    FastAPI (late)
PHASE 28    React dashboard (last, optional, zero thesis weight)
PHASE 29    Thesis exports
PHASE 30    Final validation: full reproduction pass of all headline
            experiments via `reproduce`; LIMITATIONS.md review
```

---

# 36. HOW TO WORK

Do not attempt all phases in one response or one huge commit. Work incrementally.

For every phase:

1. Review thesis requirements relevant to that phase (and Section 0 locks).
2. Explain the implementation decision.
3. Implement production-quality code.
4. Write tests.
5. Run tests (and confirm CI is green).
6. Fix errors; re-run.
7. Update documentation, including DECISIONS.md and LIMITATIONS.md where applicable.
8. Report what was implemented.
9. State unresolved research assumptions explicitly.
10. Continue with the next safe development step.

Do not ask approval for trivial implementation details.

STOP and ask only when proceeding requires REAL information we do not have:

- real SCADA file
- actual sensor meanings and source timezone
- turbine model
- maintenance records
- alarm/status definitions
- validated FMEA mappings
- methodological decisions reserved for Chapter 3 (open ADRs)
- Phase 0.5 gate approval

Do not make those things up.

---

# 37. RISK REGISTER

| ID | Risk | Likelihood | Impact | Mitigation | Owner/Tracking |
|----|------|-----------|--------|------------|----------------|
| R1 | Real dataset contains < 2 labelled gearbox events → quantitative RQ2/RQ3 evaluation impossible | High | Critical | Phase 0.5 gate pre-commits case-study design before results exist; small-n reporting policy; LIMITATIONS.md | DECISIONS.md |
| R2 | Seasonal covariate shift inflates test residuals, mimicking degradation | Medium | High | Seasonal coverage check (§14); error-vs-ambient diagnostic (§20); condition-binned normalization option | LIMITATIONS.md |
| R3 | Sensor recalibration/replacement step changes mimic or mask faults | Medium | High | Step-change detection (§11); flagged windows reviewed for healthy-state exclusion | LIMITATIONS.md |
| R4 | Serial correlation invalidates theoretical EWMA control-limit false-alarm behaviour | High | Medium | Empirical in-control characterization on healthy validation data (§23); blocked bootstrap for all CIs | §23 report |
| R5 | Register drift: software "leakage" vocabulary bleeding into thesis prose | Medium | High | LOCKED-09; user-facing docs use "causal separation"; migration log audit | Docs review |
| R6 | Threshold statistics from training residuals are optimistically small (in-sample bias) | Medium | Medium | Open ADR (§22): both sources implemented; choice closed via Chapter 3 justification | DECISIONS.md |
| R7 | Timezone/DST mishandling corrupts chronological splits and lead-time calculations | Medium | High | Mandatory UTC normalization (§8); DST checks (§11); stop-and-ask if timezone unknown | CI tests |
| R8 | Dashboard/API scope creep consumes thesis-evidence time | High | High | Phases 27–28 explicitly last and optional; priority rule in §30 | Roadmap |
| R9 | Hyperparameter search silently overfits the validation block | Medium | Medium | Configuration count recorded in metadata (§18); tuning restricted to validation block | Experiment metadata |
| R10 | Results irreproducible at write-up time (drifted environment/library versions) | Medium | Critical | Committed lockfile; per-experiment library versions and seeds; `reproduce` command; CI reproducibility test | CI |
| R11 | Unvalidated FMEA rules mistaken for validated science | Medium | High | Guard 7; `validated` flag flips only via documented literature sign-off | DECISIONS.md |
| R12 | Provisional config values (exclusion windows, λ, limits) become unexamined final values | High | Medium | Mandatory sensitivity analysis phase (§27.3) converts provisional values into defended choices | Sensitivity report |

---

# 38. FIRST DEVELOPMENT SESSION — START NOW

Perform ONLY the foundation:

1. Read the complete thesis document.
2. Create `docs/THESIS_REQUIREMENTS.md` including the Methodology Alignment Table (every LOCKED item → implementing component).
3. Create `docs/DECISIONS.md` (seeded with the open ADRs named in this spec) and `docs/LIMITATIONS.md` (empty register with template).
4. Create `docs/ARCHITECTURE.md` showing the complete scientific data flow and software modules.
5. Initialize the repository, pinned Python environment, committed lockfile, pre-commit hooks, and **GitHub Actions CI**.
6. Implement configuration handling.
7. Implement the versioned canonical SCADA schema definitions.
8. Implement configurable raw-column → canonical-column mapping with mandatory `source_timezone` and UTC conversion.
9. Implement initial CSV/Parquet loading with SHA-256 provenance capture.
10. Implement dataset validation: timestamps, UTC/DST, duplicates, missing values, sampling, required columns, predictors, targets, basic sensor validation, step-change detection.
11. Implement strict causal-separation protection including Guard 8 (all target-derived feature classes rejected).
12. Write comprehensive tests (including Guard 8 negative tests).
13. Create a SMALL synthetic fixture strictly for automated tests, marked `SYNTHETIC TEST DATA — DO NOT USE AS RESEARCH RESULTS`, containing NO fault labels.
14. Run the complete test suite locally and confirm CI passes.
15. Update README with exact commands for installation (`uv sync`), tests, validation, and experiment reproduction.
16. Report: files created, architecture implemented, tests executed, results, scientific safeguards implemented, assumptions made, information still required, next phase.

DO NOT start the frontend. DO NOT invent FMEA rules. DO NOT optimize ML models. DO NOT create fake thesis results. DO NOT proceed past Phase 0.5 without the dataset census and approval.

The objective of this first session is a clean, tested, CI-guarded, research-grade data foundation on which the locked MSc methodology can safely be implemented.
