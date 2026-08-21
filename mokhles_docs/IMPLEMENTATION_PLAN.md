# IMPLEMENTATION_PLAN.md
# Wind Turbine Gearbox Diagnostic Application — Module-Level Implementation Plan

**Derived from:** PROJECT.md v2.0 and ARCHITECTURE.md.
**Scope:** module definitions only — no implementation code.
**Rule:** a module is DONE when all its acceptance criteria pass in CI, its tests are green, and its documentation obligations (DECISIONS.md / LIMITATIONS.md entries where named) are met. Modules are built in the order of §22; no module may be started before all its dependencies are DONE unless explicitly marked as parallelizable.

Legend for dependencies: internal modules by ID (M-xx); external libraries named explicitly.

---

## PART A — FOUNDATIONS

---

### M-01 `core.errors` — Exception taxonomy

**Purpose.** Define the application-wide exception hierarchy separating methodology violations (hard stops) from data-quality findings (reported data), per ARCHITECTURE §12.

**Inputs.** None (leaf module).

**Outputs.** Exception classes: `AppError`, `ConfigError`, `SchemaError`, `TimezoneError`, `ProvenanceError`, `CausalSeparationError`, `SplitPolicyError`, `ThresholdProvenanceError`, `FmeaRuleError`, `ReproductionMismatch`.

**Dependencies.** None.

**Tests.** Hierarchy relationships (each subclass is an `AppError`); message formatting carries context fields.

**Acceptance criteria.**
1. Every exception named in ARCHITECTURE §12 exists and is importable from one location.
2. No scientific module defines ad-hoc exceptions outside this hierarchy (meta-test scans for local Exception subclasses).

---

### M-02 `core.time` — UTC utilities

**Purpose.** Enforce the UTC-everywhere rule: conversion helpers, naive-datetime rejection, DST fold/gap identification primitives used by validation.

**Inputs.** Timestamps (aware or naive), IANA timezone names.

**Outputs.** UTC-aware timestamps; DST anomaly descriptors (fold duplicates, spring gaps).

**Dependencies.** M-01; stdlib `zoneinfo`.

**Tests.** Round-trip conversions for a DST-observing zone (e.g., Europe/London) across both transitions; naive input raises `TimezoneError`; unknown zone name raises `TimezoneError`.

**Acceptance criteria.**
1. No internal API accepts naive datetimes (meta-test: helper signatures require aware types).
2. Autumn fold-back and spring-gap fixtures are correctly identified with exact boundary timestamps.

---

### M-03 `core.config` — Typed configuration

**Purpose.** Load YAML into validated Pydantic models mirroring pipeline stages; materialize all defaults; produce the resolved-config hash; carry `provisional: true` markers and ADR-surfacing enums (e.g., `threshold_stats_source`).

**Inputs.** YAML config files; environment overrides.

**Outputs.** Resolved config object tree; canonical `config.yaml` serialization; SHA-256 config hash.

**Dependencies.** M-01; Pydantic, PyYAML.

**Tests.** Defaults materialization (resolved output contains every field); invalid values raise `ConfigError`; hash stability (same logical config → same hash regardless of key order); provisional markers preserved through resolution; `threshold_stats_source` accepts exactly {training, validation}.

**Acceptance criteria.**
1. A resolved `config.yaml` is standalone: re-loading it reproduces an identical object and hash.
2. Every provisional parameter named in PROJECT.md (§13, §23) carries the marker in the resolved output.

---

### M-04 `core.logging` — Structured logging

**Purpose.** Consistent structured logs (JSON-capable) with experiment-ID context binding.

**Inputs.** Log records from all modules.

**Outputs.** Structured log stream; per-experiment log file in the artifact directory.

**Dependencies.** M-01, M-03.

**Tests.** Context binding (experiment ID present on nested calls); level filtering.

**Acceptance criteria.**
1. Any pipeline run under an experiment writes its log inside that experiment's artifact directory.

---

### M-05 `core.versioning` — Identity capture

**Purpose.** Capture schema version, application version, git commit + dirty flag, and runtime library versions (python, numpy, pandas, scikit-learn, xgboost, scipy, statsmodels) for experiment metadata.

**Inputs.** Repository state; installed environment.

**Outputs.** `VersionStamp` structure consumed by M-19.

**Dependencies.** M-01.

**Tests.** All required library keys present; dirty flag detection on a modified fixture repo.

**Acceptance criteria.**
1. `VersionStamp` contains every field required by PROJECT.md §15 with no optional omissions.

---

## PART B — DATA LAYER

---

### M-06 `data.schema` — Versioned canonical schema

**Purpose.** Define canonical SCADA variables, roles (timestamp, turbine_id, predictor, target, status, alarm, maintenance, excluded), units, and the semver `schema_version`; validate role assignments.

**Inputs.** Schema definition (code-level constants + optional YAML extension).

**Outputs.** `CanonicalSchema` object; role lookup; schema version string stamped downstream.

**Dependencies.** M-01, M-03.

**Tests.** Role validation (duplicate roles rejected); thermal targets present (gearbox oil temperature, gearbox bearing temperature); version string is valid semver.

**Acceptance criteria.**
1. Every canonical variable used anywhere downstream resolves through this module (no string literals for canonical names elsewhere — meta-test).
2. Schema changes require a version bump: a test pins the current schema hash to the current version and fails on unversioned drift.

---

### M-07 `data.mapping` — Raw→canonical mapping

**Purpose.** Translate dataset-specific column names to canonical variables via YAML mapping configs carrying mandatory `source_timezone` and `schema_version`.

**Inputs.** Raw dataframe; mapping YAML.

**Outputs.** Canonically named dataframe (pre-UTC); mapping config hash for provenance.

**Dependencies.** M-01, M-03, M-06.

**Tests.** Round-trip mapping on fixture; missing `source_timezone` raises `TimezoneError` (stop-and-ask behaviour); unmapped required roles raise `SchemaError`; old `schema_version` in mapping emits the load warning.

**Acceptance criteria.**
1. A mapping without `source_timezone` cannot proceed to ingestion under any configuration.
2. The mapping hash appears in the resulting dataset's provenance record.

---

### M-08 `data.provenance` — Provenance capture

**Purpose.** SHA-256 hashing of raw files; construction of `ProvenanceRecord` (hash, path, size, ingestion UTC time, source timezone, mapping hash, supplier note); provenance chain propagation raw → cleaned → healthy.

**Inputs.** File paths; mapping metadata; upstream provenance records.

**Outputs.** `ProvenanceRecord`s; chain structures embedded in datasets and experiments; SQLite provenance rows.

**Dependencies.** M-01, M-02, M-05.

**Tests.** Hash correctness vs known digest; chain extension preserves ancestry; tamper detection (modified file → different hash → `ProvenanceError` on verification).

**Acceptance criteria.**
1. Hashing is mandatory: ingestion cannot produce a `CanonicalDataset` lacking a provenance record (constructor contract).
2. `data/README.md` template exists documenting origin/licensing fields for the thesis data-availability statement.

---

### M-09 `data.ingestion` — Loaders

**Purpose.** CSV/Parquet loading → mapping → UTC normalization → **cross-file deduplication** → `CanonicalDataset` + `DatasetReport` skeleton; never modifies source files.

**Inputs.** File path(s); mapping config.

**Outputs.** `CanonicalDataset` (UTC-indexed, provenance-bearing); initial ingest statistics; `DeduplicationReport`.

**Dependencies.** M-02, M-06, M-07, M-08; pandas, pyarrow.

**Deduplication requirement (added 2026-08-11).** Export year-folders overlap at their boundaries — the Kelmarsh 2017 status file begins 2016-12-17 and the 2021 file begins 2020-06-07, so concatenating folders double-counts rows (LIM-006). Concatenation across files therefore:

1. deduplicates on the key `(turbine, timestamp, code)` — for SCADA rows, which carry no code, the key degenerates to `(turbine, timestamp)`;
2. verifies duplicates by **content hash**: rows sharing a key must be byte-identical in every mapped field;
3. **raises** `ProvenanceError` when two rows share a key but differ in content — a silent pick would fabricate a record that exists in neither source file;
4. reports the count removed per key type in the `DeduplicationReport`, which is persisted into experiment metadata.

**Encoding requirement.** Source encoding is detected strictly (UTF-8 first, explicit fallback) and recorded in provenance. Silent character replacement is prohibited: it corrupts degree signs and vendor text without leaving a trace.

**Tests.** CSV and Parquet parity on the same fixture; UTC conversion applied exactly once; source file byte-identical after ingestion; DST-dirty fixture survives ingestion with anomalies recorded, not dropped; **fixture reproducing the code-7057 double-count across the 2020/2021 folder boundary deduplicates to one row and reports the removal**; conflicting-content duplicate raises.

**Acceptance criteria.**
1. Output timestamps are UTC-aware for every supported input timezone fixture.
2. Ingestion of the DST-dirty fixture loses zero rows (anomalies flagged downstream, per PROJECT.md §8).
3. No concatenation path exists that silently drops or silently keeps a conflicting duplicate (meta-test on the ingestion entry points).

---

### M-10 `data.validation` — Rule engine

**Purpose.** Pluggable validation rules producing `Finding`s (INFO/WARNING/ERROR): timestamp rules (parsing, duplicates, order, sampling, gaps, DST fold/gap), sensor rules (missing, constant, impossible values, jumps, **step-change/recalibration detection**), turbine rules, research-schema rules; assemble the full `DatasetReport`.

**Inputs.** `CanonicalDataset`; validation config; feature config (for schema rules).

**Outputs.** `DatasetReport` with findings, DST anomalies, detected step changes (timestamp, channel, magnitude).

**Dependencies.** M-06, M-09; scipy/numpy for change-point heuristic.

**Tests.** Each rule against a violating fixture and a clean fixture; step-change detection on synthetic level shift (detected within tolerance of true changepoint) and non-detection on smooth seasonal fixture; findings never mutate data.

**Acceptance criteria.**
1. Every check listed in PROJECT.md §11 has a corresponding rule class and test pair.
2. Detected step changes are emitted as flagged windows consumable by M-12 (healthy-state review) and produce a LIMITATIONS.md entry template when unresolved.
3. Validation is read-only (dataset hash identical before/after).

---

### M-11 `data.cleaning` — Audit-trailed cleaning

**Purpose.** Configurable cleaning operations, each recording rule, reason, before/after counts; output remains provenance-chained to raw.

**Inputs.** `CanonicalDataset`; cleaning config; `DatasetReport`.

**Outputs.** Cleaned `CanonicalDataset` (new provenance link); `CleaningAudit`.

**Dependencies.** M-08, M-10.

**Tests.** Audit arithmetic (before − removed = after) per operation and in aggregate; disabled rule leaves data untouched; audit serializes into the experiment artifact.

**Acceptance criteria.**
1. No cleaning path exists that removes rows without an audit entry (meta-test on operation registry).
2. Cleaned dataset's provenance chain includes the raw hash.

---

### M-12 `data.healthy_state` — HealthyStateBuilder

**Purpose.** Construct the healthy training population by exclusions (fault periods, alarms, maintenance ± windows, shutdown, invalid states, sensor-failure and step-change windows, curtailment, pre-failure windows); emit `HealthyStateReport`; raise Guard 5 warnings when known failure intervals would enter training.

**Inputs.** Cleaned `CanonicalDataset`; `OperationalEvent`s (M-24); healthy-state config (provisional parameters marked).

**Outputs.** Healthy `CanonicalDataset` subset; `HealthyStateReport` (totals, retention %, exclusion reason counts, ranges, turbines).

**Dependencies.** M-11, M-24 (event structures only — parallelizable via a stub contract).

**Tests.** Each exclusion rule independently; window arithmetic at boundaries (inclusive/exclusive documented and tested); Guard 5 fixture (failure interval overlapping training → WARNING finding); report accounting sums exactly.

**Acceptance criteria.**
1. All nine exclusion bases from PROJECT.md §13 are implemented and individually configurable.
2. Retention accounting is exact: accepted + excluded = total, and exclusion reason counts are disjointly attributed (an observation excluded for multiple reasons has a defined primary-reason policy, documented).
3. Provisional parameters are discoverable by M-27 via their config markers.

---

### M-13 `data.splitting` — Chronological splits + seasonal check

**Purpose.** Chronological fraction-based and explicit-date splits; overlap prevention; **seasonal coverage check** (months, calendar coverage, ambient range train vs test) with WARNING below 12 months; rolling-origin split mode for RQ1; `SplitPolicyGuard` (Guard 3) rejecting non-chronological strategies on thesis-flagged experiments.

**Inputs.** Healthy dataset; `SplitSpec`; `thesis_official` flag.

**Outputs.** `Split` (index ranges) + `SeasonalCoverageReport`.

**Dependencies.** M-02, M-12.

**Tests.** Boundary correctness (no leakage of a single timestamp across partitions); overlap rejection; explicit-date mode; seasonal WARNING on 8-month fixture and silence on 14-month fixture; ambient-range comparison arithmetic; Guard 3: random strategy + thesis flag → `SplitPolicyError`; rolling-origin fold generation count and ordering.

**Acceptance criteria.**
1. Guard 3 is unbypassable on thesis-flagged runs (no config combination reaches a random split — property-style enumeration test over strategy configs).
2. Every split stores its `SeasonalCoverageReport`, and WARNING-level reports auto-append a LIMITATIONS.md entry.

---

### M-14 `data.guards` — FeatureConfigurationValidator (Guards 1, 2, 8)

**Purpose.** The single chokepoint validating `FeatureConfig` before any model fit: rejects target-as-predictor (G1), future information (G2), and **every target-derived feature class** (G8: lags, rolling stats, differences, transforms of any thermal target); permits thermal-lag-aware engineering on upstream variables only; carries the fault-masking rationale in its documentation.

**Inputs.** `FeatureConfig` (with per-feature declared source columns); `CanonicalSchema`.

**Outputs.** None on success; `CausalSeparationError` on violation.

**Dependencies.** M-06.

**Tests.** Negative tests for each prohibited class (lagged target, rolling target, target diff, target transform, target-as-predictor, future-shifted predictor) — each must raise with a class-specific message; positive tests for lagged/rolled upstream features; undeclared feature source → rejection (fail-closed).

**Acceptance criteria.**
1. Fail-closed: a feature without a declared source column cannot pass.
2. Test suite enumerates all G8 classes from PROJECT.md §9; CI fails if a class lacks a negative test (checklist test).
3. User-facing messages use "causal separation" vocabulary (LOCKED-09); a test asserts no user-facing string contains "leakage crisis".

---

## PART C — MODELLING LAYER

---

### M-15 `models.base` + `models.registry` — NBM contract

**Purpose.** The `NormalBehaviourModel` protocol (fit/predict/save/load, seeded, multi-target) with `model_kind ∈ {THESIS, BASELINE}`; registry resolving configured names to classes.

**Inputs.** Feature matrices/targets (typed frames); model config.

**Outputs.** Interface + registry; `FitReport` structure.

**Dependencies.** M-01, M-03, M-14 (validator invoked by the fit entry point).

**Tests.** Registry resolution and unknown-name failure; protocol conformance checks for all registered models; fit entry point calls the validator (spy test) — fitting is impossible without Guard 1/2/8 validation.

**Acceptance criteria.**
1. There is exactly one fit entry point, and it validates features first (meta-test: no registered model's fit is reachable without the chokepoint).
2. `model_kind` is mandatory; registry refuses kind-less registrations.

---

### M-16 `models.xgboost_nbm` — THE thesis model (LOCKED-01)

**Purpose.** Multi-target XGBoost NBM: native multi-output configuration (headline) and per-target ablation mode; seeded determinism; save/load; hyperparameter tuning restricted to the validation block with `tuning_configurations_evaluated` counted.

**Inputs.** Training/validation frames from a chronological `Split`; model config.

**Outputs.** Fitted model artifacts; predictions per target; `FitReport` incl. tuning count.

**Dependencies.** M-13, M-15; xgboost.

**Tests.** Shape contracts (predictions column-per-target); save→load→predict equality; bit-identical predictions under fixed seeds (repeated fits); tuning loop touches only validation indices (index-audit test); tuning count recorded.

**Acceptance criteria.**
1. `model_kind == THESIS`; the only THESIS-kind model in the registry (meta-test).
2. Determinism: two fits with identical config+seed produce byte-identical prediction files.
3. No code path exposes test-partition data to tuning (audited by index-tracking test).

---

### M-17 `models.baselines` — The single baseline comparator

**Purpose.** ONE baseline NBM: **multiple linear regression** on the same exogenous predictors as the thesis model (BASELINE kind), sharing the M-15 contract, for RQ1 contextualization only.

Closed by ADR-002 (2026-08-11, decision queue D-02): the model set is exactly two — XGBoost multi-target NBM (THESIS, M-16) and multiple linear regression (BASELINE). **Random Forest and the previously proposed ANN/MLP baseline are dropped.** This supersedes PROJECT.md §18's baseline list; no LOCKED constraint is affected (LOCKED-01 fixes only that XGBoost is THE thesis model). Rationale, and the reason Bangalore & Tjernberg's NARX ANN was not reimplemented (Guard 8 prohibits its lagged-target inputs), are recorded in ADR-002.

The baseline is a **measuring stick, not a competitor**: it establishes how much thermal variance is linear in operating conditions versus captured non-linearly, indicating how much residual spread is irreducible physics rather than modelling error. Linear regression is the minimal reference that does this — no hyperparameters, no architecture decisions.

**Inputs/Outputs.** As M-16 (multi-target: one fitted regression per thermal target, predictions column-per-target).

**Dependencies.** M-13, M-15; scikit-learn (`LinearRegression`).

**Tests.** Contract conformance; multi-target prediction shape; determinism (no stochastic component — repeated fits must be bit-identical); kind labelling; registry exposes exactly one BASELINE and one THESIS model.

**Acceptance criteria.**
1. Registers as `BASELINE`; comparison outputs (M-28) auto-label it.
2. The registry contains exactly two models (one THESIS, one BASELINE) — a meta-test asserts no third model is registered without an ADR.
3. No hyperparameter search exists for this model (nothing to tune ⇒ nothing to record under the §18 multiple-comparison guard).

---

### M-18 `models.metrics` — Accuracy metrics

**Purpose.** RMSE, MAE, R², bias per thermal target; condition-sliced diagnostics (error vs power/wind/ambient). **MAPE structurally absent** for temperature targets.

**Inputs.** Actual/predicted frames; condition variables.

**Outputs.** `MetricSet`; condition-diagnostic tables feeding plots.

**Dependencies.** M-15; numpy.

**Tests.** Each metric vs hand-computed reference; `MetricSet` field set is exactly {rmse, mae, r2, bias} (assertion test); condition slicing bin arithmetic; ambient-slice output usable as the seasonal-shift diagnostic.

**Acceptance criteria.**
1. Grep/meta-test: no MAPE computation exists anywhere in `models/` or `evaluation/`.
2. Condition diagnostics cover the three variables named in PROJECT.md §20.

---

## PART D — RESIDUALS AND DETECTION

---

### M-19a `residuals.engine` — Residual generation

**Purpose.** `residual = actual − expected_healthy_value` per target; assemble `ResidualFrame` preserving raw residuals permanently.

**Inputs.** Actuals; model predictions.

**Outputs.** `ResidualFrame` (timestamp UTC, turbine, target, actual, prediction, raw residual, slot for normalized).

**Dependencies.** M-16/M-17 outputs.

**Tests.** Identity arithmetic; alignment on turbine+timestamp; raw column immutability after downstream normalization (mutation attempt fails).

**Acceptance criteria.**
1. Raw residuals are write-once: no downstream module can overwrite them (frozen-column contract + test).

---

### M-19b `residuals.normalization` — Normalizers + Guard 4

**Purpose.** σ-, MAD-, percentile-, and condition-binned normalizers; statistics fitted on healthy partitions only, with source partition (training|validation per the open ADR enum) recorded; `ThresholdProvenanceGuard` (Guard 4) rejects fault/test-derived statistics.

**Inputs.** Healthy `ResidualFrame` + `PartitionRef`; residual config.

**Outputs.** Normalized `ResidualFrame`; fitted-statistics record (for metadata).

**Dependencies.** M-13 (partition refs), M-19a.

**Tests.** Each normalizer vs hand-computed reference; condition-binned bin membership; Guard 4 negative test (test-partition ref → `ThresholdProvenanceError`); both ADR branches produce recorded, distinguishable metadata.

**Acceptance criteria.**
1. All four normalizer families from PROJECT.md §22 are selectable by config.
2. Statistics source is always recorded in experiment metadata; absent source is impossible (constructor contract).

---

### M-20 `residuals.ewma` — PRIMARY detector (LOCKED-02)

**Purpose.** EWMA smoothing of normalized residuals with control-chart limits (steady-state and time-varying options); **empirical in-control false-alarm characterization** on healthy validation data (because serial correlation breaks i.i.d. ARL assumptions); emit `EwmaSeries` + `DetectionSeries` labelled `PRIMARY_EWMA`.

**Inputs.** Normalized `ResidualFrame`; EWMA config (λ, limit spec — provisional-marked).

**Outputs.** `EwmaSeries` (values, limits, λ, in-control stats); per-signal `DetectionSeries`.

**Dependencies.** M-19b; statsmodels/numpy.

**Tests.** EWMA recursion vs hand-computed reference sequence; both limit formulations vs references; in-control characterization on healthy fixture returns finite empirical false-alarm rate; autocorrelated fixture demonstrates empirical ≠ theoretical rate (the reason the characterization exists); method label correctness.

**Acceptance criteria.**
1. EWMA is the default detection method in resolved configs; comparators require explicit opt-in.
2. Every EWMA experiment stores its `InControlReport`; a materially inflated empirical false-alarm rate auto-appends a LIMITATIONS.md entry (threshold for "material" defined in config).

---

### M-21 `detection.single` + `detection.comparators` — Per-signal decisions

**Purpose.** Single-signal detection on EWMA series (primary path); consecutive-exceedance, rolling-window-count, and rolling-mean comparators (non-primary, labelled `COMPARATOR_*`).

**Inputs.** `EwmaSeries` / normalized residuals; detection config.

**Outputs.** `DetectionSeries` per target with method labels and state ∈ {−1, 0, +1}.

**Dependencies.** M-20.

**Tests.** State encoding on constructed exceedance fixtures (high, low, normal); each comparator's counting logic at boundaries; labels always present and correct.

**Acceptance criteria.**
1. No `DetectionSeries` exists without a method label (constructor contract).
2. Comparator outputs are visually and programmatically distinguishable from primary outputs everywhere downstream (tables, plots, exports).

---

### M-22 `detection.coordinated` — Multi-target states

**Purpose.** Combine per-target detections into `CoordinatedState` vectors ({−1,0,+1} per target) while preserving continuous EWMA values alongside.

**Inputs.** Per-target `DetectionSeries` + `EwmaSeries`.

**Outputs.** Time-ordered `CoordinatedState` sequence per turbine.

**Dependencies.** M-21.

**Tests.** Vector assembly and target ordering stability; continuous values preserved and matched to states; missing-target handling (explicit gap, never silent zero).

**Acceptance criteria.**
1. Discrete and continuous representations are never separated: any serialization of a coordinated state includes both.

---

### M-23 `detection.matched_fpr` — Fair comparison framework

**Purpose.** Threshold/limit sweeps per pipeline; false-alarm rate measurement on healthy (non-event) periods; operating-curve construction; comparison of single-signal vs coordinated pipelines **at matched false-alarm operating points** (e.g., equal FA per turbine-year); full-curve reporting.

**Inputs.** Detection pipelines (single, coordinated); threshold grid; healthy period set; `OperationalEvent`s.

**Outputs.** `OperatingCurve` per pipeline; `ComparisonReport` at specified FPR targets (detected/missed events, lead times, alarm durations).

**Dependencies.** M-21, M-22, M-24.

**Tests.** Sweep monotonicity (FA rate non-increasing with stricter limits); FA-rate arithmetic on constructed fixtures; matched-point interpolation; curve serialization round-trip; symmetry test — the framework applied to two identical pipelines reports no difference (fairness sanity check per PROJECT.md §25).

**Acceptance criteria.**
1. RQ2 comparisons are producible only through this module (comparison tables refuse raw-count pipeline comparisons — contract in M-28).
2. Full operating curves are always exported alongside any matched-point table.

---

## PART E — INTERPRETATION AND EVALUATION

---

### M-24 `evaluation.events` — Canonical operational events

**Purpose.** Canonical structures for alarms, status codes, maintenance, known failures, replacements, inspections; parsing adapters; separation of anomaly-detection ground truth from mechanism-level ground truth.

**Inputs.** Raw event files (formats per Phase 0.5 census).

**Outputs.** `OperationalEvent` lists with UTC timestamps and ground-truth tier tags.

**Observed status vocabulary (census, 2016–2021; do not assume beyond it).** The `Status` field takes exactly four values — **Informational, Stop, Warning, Communication**. There is **no Error and no Fault tier**; severity cannot be read from a tier name that does not exist. The vendor's own taxonomies (`IEC category`, `Service contract category`) are the available structured classifiers, and both include blank values. The `Comment` free-text field is empty in every row, and a `Service comment` column does not exist in these exports — so the dataset carries no free-text maintenance evidence (LIM-002).

**Dependencies.** M-02, M-08.

**Tests.** Parsing fixtures per format; UTC conversion; tier tagging; provenance capture for event files.

**Acceptance criteria.**
1. The two ground-truth tiers are structurally distinct and cannot be conflated in evaluation calls (type-level separation).

---

### M-25 `fmea.knowledge_base` — Structured FMEA rules

**Purpose.** Load YAML rulesets (id, mechanism, residual_pattern, confidence, rationale, source, validated); schema-validate; stamp `ruleset_version`; enforce Guard 7 labelling (`UNVALIDATED RULE`) and the sign-off policy (validated flips only via DECISIONS.md-recorded literature citation).

**Inputs.** Ruleset YAML files.

**Outputs.** `FmeaKnowledgeBase` with versioned rules; match primitive against `CoordinatedState`.

**Dependencies.** M-22 (state structure); PyYAML.

**Tests.** Malformed YAML rejection (`FmeaRuleError`); match / non-match / multiple-match fixtures; unvalidated label propagation into match results; ruleset version stamping; a rule with `validated: true` but empty `source` is rejected (sign-off enforcement at load).

**Acceptance criteria.**
1. No rule can be both `validated: true` and source-less.
2. Every downstream artifact touching an unvalidated rule carries the Guard 7 banner (traced through M-26 and exports).

---

### M-26 `fmea.interpreter` — Interpretation engine (LOCKED-03)

**Purpose.** Map coordinated residual patterns + persistence + operating context to `DiagnosticEvent`s with ranked `CandidateMechanism`s (supporting and contradictory evidence, confidence category, rationale). Hypothesis language only: "confirmed" is unrepresentable in the confidence enum.

**Inputs.** `CoordinatedState` sequences; `FmeaKnowledgeBase`; operating context.

**Outputs.** `DiagnosticEvent` list.

**Dependencies.** M-22, M-25.

**Tests.** Candidate ranking determinism; contradictory-evidence attachment; confidence enum excludes any confirmed/definite value (enum-membership test); empty-match behaviour (anomaly with no rule match yields an explicit "no candidate mechanism" event, not silence).

**Acceptance criteria.**
1. Interpretation is reachable only through FMEA rules — no statistical attribution imports exist in `fmea/` (dependency scan; LOCKED-03/07).
2. Every `DiagnosticEvent` serializes its matched rule IDs and ruleset version for traceability.

---

### M-27 `evaluation.event_eval` + `evaluation.sensitivity` — Event evaluation & sensitivity

**Purpose.** Event-level metrics (detected/missed/false-alarm events, first-detection time, lead time with sign convention, duration, alarm counts); **small-n policy** switching to descriptive-only mode below the Phase 0.5 threshold; **sensitivity suite** sweeping provisional parameters (exclusion windows, power floor, λ, limit multiplier, normalization method) with tornado summaries and conclusion-flip flagging.

**Inputs.** `DiagnosticEvent`s; `OperationalEvent`s; operating points from M-23; sensitivity grids (auto-discovered from provisional markers).

**Outputs.** `EvaluationResult` (with `inferential_allowed` flag); `SensitivityReport` + tornado tables.

**Dependencies.** M-23, M-24, M-26; M-12/M-13/M-19b/M-20 re-invoked by sensitivity sweeps via M-30.

**Tests.** Event matching windows; lead-time sign (positive = early) on constructed fixtures; missed/false-alarm counting; small-n mode activates at the configured threshold and blocks inferential outputs; sensitivity sweep re-runs are seeded and reproducible; conclusion-flip detector fires on a constructed flipping fixture.

**Acceptance criteria.**
1. Below the event threshold, no code path emits detection-rate confidence intervals or significance claims (`inferential_allowed` gates them structurally).
2. Sensitivity discovers every provisional-marked parameter automatically; a newly added provisional parameter without grid coverage fails a checklist test.
3. Conclusion-flipping parameters auto-append LIMITATIONS.md entries.

---

### M-28 `evaluation.bootstrap` + `evaluation.dm_test` + `evaluation.comparison` — Statistics & thesis tables

**Purpose.** Moving-block bootstrap CIs (block length from residual autocorrelation, recorded); Diebold–Mariano with HAC variance for model-vs-model loss comparisons, with descriptive fallback + LIMITATIONS entry when assumptions strain; cross-experiment comparison tables (metrics + CIs + DM p-values + detection outcomes) with provenance/schema-match refusal and explicit-override logging.

**Inputs.** Residual/loss series; `ExperimentRecord`s; `EvaluationResult`s; `OperatingCurve`s.

**Outputs.** `ConfidenceInterval`s; `DmResult`s; thesis-ready comparison tables (CSV + formatted).

**Dependencies.** M-18, M-19a, M-23, M-27, M-30; numpy, statsmodels.

**Tests.** Bootstrap CI coverage study on synthetic AR(1) (empirical coverage within tolerance of nominal); i.i.d. bootstrap is not selectable for time-series inputs (config rejection test); DM statistic vs reference implementation; HAC lag handling; comparison refusal on mismatched provenance and on raw-count RQ2 comparisons (must route through M-23); baseline auto-labelling from `model_kind`; footnoting of provisional-parameter results.

**Acceptance criteria.**
1. Every headline metric in any generated table carries a blocked-bootstrap CI.
2. No thesis table can silently mix schema versions, datasets, or bypass matched-FPR for RQ2.

---

## PART F — ORCHESTRATION, TRACKING, DELIVERY

---

### M-29 `experiments.tracker` + `experiments.store` — Tracking & artifacts

**Purpose.** `ExperimentRecord` capture (full PROJECT.md §15 field set incl. per-component seeds, environment versions, provenance chain, seasonal report, guard attestations, `thesis_official` flag); artifact directory layout (`EXP-YYYYMMDD-NNN`); SQLite metadata rows as pointers only.

**Inputs.** All stage outputs and configs during a run.

**Outputs.** Complete artifact directory; metadata rows.

**Dependencies.** M-03, M-04, M-05, M-08; all scientific modules (as data sources).

**Tests.** Metadata schema completeness (validation against the §15 contract — missing field fails); ID monotonicity; artifact layout conformance; database-loss resilience (artifacts alone suffice to rebuild metadata rows).

**Acceptance criteria.**
1. An `ExperimentRecord` missing any §15 field cannot be persisted.
2. Deleting the SQLite database and re-indexing from artifacts reproduces equivalent metadata (evidence lives in files).

---

### M-30 `experiments.runner` — Pipeline orchestration

**Purpose.** Execute the end-to-end pipeline from one resolved config: ingest → validate → clean → healthy-state → guard-validate features → split (+seasonal) → fit (thesis + configured baselines) → residuals → normalize → EWMA → detect → coordinate → matched-FPR → FMEA → evaluate → stats; write every artifact through M-29; the only module importing all scientific layers.

**Inputs.** Resolved config; dataset paths; event paths.

**Outputs.** Completed experiment artifact directory.

**Dependencies.** Everything in Parts B–E; M-29.

**Tests.** E2E on synthetic fixture (no fault labels; mechanics only); stage-skip configurations; failure propagation (a guard exception aborts with a clean partial-artifact state and clear error); no random-split helper importable here (meta-test).

**Acceptance criteria.**
1. One command + one config reproduces the full artifact tree on the fixture.
2. Guard failures abort before any model artifact is written (fail-early ordering test).

---

### M-31 `experiments.reproduce` — Reproduction command

**Purpose.** `reproduce EXP-ID`: environment check vs stored versions (warn), dataset hash verification (fail on mismatch), re-run from stored config + seeds, diff metrics and predictions, report EXACT / TOLERANCE / MISMATCH.

**Inputs.** Experiment ID; artifact store.

**Outputs.** Reproduction report with per-file diff detail.

**Dependencies.** M-29, M-30.

**Tests.** EXACT MATCH on untouched fixture experiment; MISMATCH on tampered predictions; `ProvenanceError` on tampered dataset; version-mismatch warning path.

**Acceptance criteria.**
1. CI runs fixture reproduction on every push and requires EXACT MATCH on predictions (PROJECT.md §15, §32).
2. The command is documented in README as one line.

---

### M-32 `services` + `api` — FastAPI surface (LATE)

**Purpose.** Thin use-case coordinators and REST endpoints (/datasets, /validation, /experiments, /models, /predictions, /residuals, /diagnostics, /events, /evaluation) over the finished scientific core; long-running training handled without blocking, without distributed infrastructure.

**Inputs.** HTTP requests.

**Outputs.** JSON responses; artifact downloads.

**Dependencies.** M-29–M-31 DONE first; FastAPI.

**Tests.** Request validation; experiment lifecycle; endpoint contracts; services contain no scientific logic (dependency scan — they only call scientific modules).

**Acceptance criteria.**
1. Nothing in `services/` or `api/` computes science (import scan: no xgboost/scipy/statsmodels imports).
2. All thesis evidence is producible with the API absent (M-30/M-31 CLI suffices).

---

### M-33 `frontend` — Dashboard (LAST, OPTIONAL, zero thesis weight)

**Purpose.** React + TypeScript + Vite + Plotly views per PROJECT.md §30: dataset, healthy state, experiments, model (native gain/cover importance only — **no SHAP views**), residuals (incl. EWMA + limits), coordinated analysis, diagnostics, events overlay.

**Inputs.** M-32 API.

**Outputs.** Dashboard.

**Dependencies.** M-32 DONE; all thesis evidence already generated.

**Tests.** Component rendering; API contract tests; no attribution/XAI component exists (source scan).

**Acceptance criteria.**
1. Started only after Phases 0–26 outputs exist; any schedule conflict resolves against this module (PROJECT.md §30, risk R8).

---

### M-34 Exports — Thesis artifact generation

**Purpose.** CSV/JSON/PNG/SVG exports: metrics with CIs, DM tables, experiment comparisons, predictions, residual data (raw/normalized/EWMA), anomalies, operating curves, sensitivity tables, event evaluations, thermal plots, FMEA matches (Guard 6/7 banners preserved), configuration snapshots; publication-friendly tables.

**Inputs.** Artifact directories; comparison outputs.

**Outputs.** Export files under `evaluation/` and `plots/`.

**Dependencies.** M-28, M-29; matplotlib, plotly.

**Tests.** Round-trip of tabular exports; banner presence on synthetic and unvalidated-rule artifacts; SVG/PNG generation smoke tests; no SHAP-chart export path exists (scan).

**Acceptance criteria.**
1. Every table type named in PROJECT.md §31 has an export function and fixture-backed test.
2. Guard 6/7 banners survive every export format.

---

## PART G — DOCUMENTATION & PROCESS MODULES

---

### M-35 Docs — Living research documents

**Purpose.** Templates and update discipline for `THESIS_REQUIREMENTS.md` (with Methodology Alignment Table), `DECISIONS.md` (ADRs incl. threshold-stats-source, literature-baseline choice, FMEA sign-offs, schema bumps), `LIMITATIONS.md` (auto-appended by M-10, M-13, M-20, M-27, M-28 as specified), `DATASET_DUE_DILIGENCE.md` (Phase 0.5), `ARCHITECTURE.md` maintenance, `data/README.md`.

**Inputs.** Development events; auto-append hooks.

**Outputs.** Current documents in `docs/`.

**Dependencies.** None (process module; hooks land with their owning modules).

**Tests.** Template presence in repo; auto-append hooks covered inside their owning modules' tests.

**Acceptance criteria.**
1. Methodology Alignment Table maps every LOCKED-01…10 item to at least one implementing module ID from this plan, kept current (checklist test comparing table against module registry).
2. Every open ADR named in PROJECT.md exists in DECISIONS.md with status OPEN before the affected module is marked DONE.

---

### M-36 CI/CD & environment — Delivery infrastructure

**Purpose.** GitHub Actions running ruff, mypy, import-linter (dependency contract, ARCHITECTURE §3), pytest+coverage, and the fixture reproduction test on every push/PR; committed `uv.lock`; pinned Python 3.12; pre-commit hooks; red pipeline blocks merge.

**Inputs.** Repository.

**Outputs.** Green/red pipeline status; coverage reports.

**Dependencies.** M-01 onward (guards all of them).

**Tests.** The pipeline is the test; a deliberate lint/type/test/import-direction violation on a branch demonstrates each gate blocks.

**Acceptance criteria.**
1. Fresh-machine bootstrap is exactly `git clone → uv sync → pytest` to green (verified in CI on a clean runner).
2. All five gates (lint, types, import contract, tests, reproduction) are required checks.

---

## 22. BUILD ORDER AND ROADMAP MAPPING

```text
Order  Modules                     PROJECT.md phases
─────  ─────────────────────────   ─────────────────
  1    M-36, M-01…M-05             Phase 1
  2    M-35 (seed docs)            Phase 0
  —    PHASE 0.5 GATE              Phase 0.5 (blocking; M-24 formats informed here)
  3    M-06, M-07, M-08, M-09      Phases 2–3
  4    M-10, M-11                  Phases 4–5
  5    M-24 (stub→full), M-12      Phases 6, 23
  6    M-14, M-13                  Phases 7–8
  7    M-29, M-30 (skeleton),      Phase 9
       M-31
  8    EDA scripts (uses M-09/10)  Phase 10
  9    M-15, M-16, M-17, M-18      Phases 11–14 (M-28 bootstrap/DM early here)
 10    M-19a, M-19b, M-20          Phases 15–17
 11    M-21, M-22, M-23            Phases 18–20
 12    M-25, M-26                  Phases 21–22
 13    M-27                        Phases 24–25
 14    M-28 (comparison), M-34     Phases 26, 29
 15    M-32                        Phase 27
 16    M-33                        Phase 28
 17    Final reproduction pass     Phase 30
       via M-31 on all headline
       experiments
```

Parallelizable pairs: M-24 event structures may be stubbed for M-12 and completed at step 12–13; M-28's bootstrap/DM sub-modules may be built at step 9 alongside metrics.

---

## 23. CROSS-CUTTING ACCEPTANCE CRITERIA (apply to every module)

1. **Lock conformance.** No module introduces SHAP/XAI, MAPE-for-temperature, random thesis splits, target-derived features, synthetic fault labels, or "leakage crisis" user-facing language. CI scans enforce the scannable subset.
2. **Typing and lint clean.** mypy and ruff pass with no per-module ignores added without an ADR.
3. **Determinism.** Any stochastic behaviour takes an explicit seed recorded in experiment metadata.
4. **UTC only.** All timestamps entering or leaving a module are UTC-aware.
5. **Traceability.** Any artifact a module writes identifies its experiment, config hash, and provenance chain.
6. **Documentation.** Module docstrings state the PROJECT.md section(s) implemented; ADR/LIMITATIONS hooks fire where this plan names them.
7. **Definition of DONE.** All module acceptance criteria + cross-cutting criteria pass in CI; roadmap phase report delivered per PROJECT.md §36.
