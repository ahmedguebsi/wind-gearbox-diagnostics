# SESSION_STATUS.md — Handoff (written 2026-08-12, end of session)

> **⚠ HISTORICAL SNAPSHOT — DO NOT READ AS CURRENT STATE (banner added
> 2026-08-18).** This file describes the repository as it stood on
> 2026-08-12 and is retained as the handoff record of that session, not
> corrected in place. Everything below is superseded on at least these
> points: the suite is now 542 tests at 95.50% coverage (not 378); the schema
> is 1.3.0 (not 1.2.0); decisions run to ADR-048 and limitations to LIM-036
> (not ADR-017); D-07 is CLOSED (ADR-023);
> five experiments have been run since. Current state lives in
> [`DECISIONS.md`](DECISIONS.md), [`LIMITATIONS.md`](LIMITATIONS.md),
> [`EXPERIMENT_PROTOCOL.md`](EXPERIMENT_PROTOCOL.md) and the README.
>
> One item below was still open five days later and is worth naming: the
> "sign-convention wrinkle to reconcile" recorded in *In flight /
> half-finished* shipped again in the 2026-08-17 headline run before being
> fixed under ADR-036. A known defect parked in a handoff note is a defect
> that ships.

Snapshot for the next session. Authoritative sources remain DECISIONS.md,
LIMITATIONS.md, CHAPTER3_DECISION_QUEUE.md, and the experiment artifacts;
this file is a pointer, not a record of decisions.

## Build state

- **378 tests green** (full suite, 96% coverage); ruff, ruff-format, mypy
  (strict), and import-linter all pass locally; CI confirmed green on a
  clean runner (Actions run 31623910742 — LIM-009 MITIGATED).
- Modules DONE: **M-01…M-31** — core, data layer (incl. Guards 1/2/3/4/8),
  models (XGBoost THESIS + linear BASELINE, exactly two per ADR-002),
  residuals (normalizers + EWMA primary), detection (single, comparators,
  coordinated, matched-FPR with fairness symmetry test), FMEA (ADR-008
  five-rule base, all `validated: false`; interpreter with operator
  rendering), evaluation (M-24 events two-tier, M-27 event eval +
  sensitivity, M-28 bootstrap/DM/comparison), experiments (tracker, store,
  fully wired runner, `reproduce` with EXACT-MATCH prediction diff).
- NOT started: M-32 (FastAPI), M-33 (dashboard), M-34 (exports).
- Schema **1.2.0** (ADR-012 designation). Decisions: ADR-001…ADR-017;
  queue Groups A and B closed except **D-07 (split periods)**; Group C
  (D-08…D-14) open. RQ2 success criterion pre-specified (ADR-016);
  event-matching window closed (ADR-017: 14 d, persistence-qualified,
  10-min quantised leads, 7/14/30 sweep).
- Head commit at handoff: `3a20d8b` (+ this file's commit). **Push status
  managed by the author via GitHub Desktop** — commits from `d769e14`
  onward may need pushing; this machine's MinGit cannot push
  non-interactively.

## Kelmarsh run: COMPLETED

**EXP-20260812-001** (2026-08-12) — first real pipeline run, approved
predictor set (7), split 2018-07-01 / 2019-02-01 (EVENT-001 in TEST per
ADR-010), Stop+Warning-with-ends alarm windows. Artifacts:

    artifacts/EXP-20260812-001/        (repo root; NOT in git, by design)
      config.yaml, metadata.json, metrics.json
      model/ predictions/ residuals/ (parquet)
      evaluation/first_run_summary.json   <- RQ1 CIs, DM, EVENT-001, in-control
      evaluation/event001_diagnostic.txt  <- operator rendering (see caveat)

Reproduce: `uv run python -m app.experiments reproduce EXP-20260812-001
--root ../artifacts` (from backend/). Runner script:
`scripts/run_kelmarsh_experiment.py` (refuses to run without
`--approved-by`).

Headline results: XGBoost beats baseline on healthy VALIDATION (oil RMSE
2.30 vs 2.57; bearing 1.91 vs 2.29) but the **linear baseline generalizes
better on the 2.4-yr unfiltered monitoring period** (bearing 5.10 vs 7.18;
DM p≈0) — XGBoost was UNTUNED (count 0) and the monitoring ambient range
exceeds training (LIM-013). In-control false-alarm rate **16.2% vs 0.27%
theoretical (59.9×, LIM-011)** — the λ=0.2/3σ operating point is unusable;
EVENT-001 "matched" (lead 13.8 d) but with 20,472 FA episodes that match
is uninformative at this operating point, and the rendered diagnostic is a
LOW-LOW pattern during the icing window (LIM-010) with an honest
no-candidate-mechanism output.

## In flight / half-finished

- **Author decisions pending from the run** (do NOT resolve silently):
  1. Step-change detector review — it excluded **39.8% of train/val rows**
     (LIM-014); parameters are not provisional-marked.
  2. `generator_speed` plausible bounds — 3,226 rows outside (−1, 5000)
     RPM was the run's only validation ERROR.
  3. XGBoost hyperparameter tuning on the validation block (§18) before
     any RQ1 headline claim.
  4. Which period headlines RQ1 (validation vs monitoring metrics).
  5. D-07: ratify or change the provisional split dates.
- **Matched-FPR sweep has never been run** — M-23 is built and tested but
  no operating curves exist yet; LIM-011 makes this the gating analysis.
- **Sensitivity suite (M-27) never run on real data** — grids ready for
  all 7 provisional parameters incl. the ADR-017 7/14/30 window.
- `condition_binned` normalization is NOT wired into the runner (raises
  fail-early; awaits D-12).
- M-13 seasonal warnings do not auto-append to LIMITATIONS.md (LIM-013 was
  logged manually this session; wiring is small if wanted).
- Sign-convention wrinkle to reconcile: `MetricSet.bias` =
  mean(predicted − actual), but the run script's bootstrap bias =
  mean(actual − predicted). Both documented, opposite signs.
- Comparators (M-21) exist but are not exercised by the runner or any run
  script yet (non-primary; comparison study later).
- EVENT-001 Chapter 5 figure: rendering machinery works; the *meaningful*
  figure needs a defensible operating point first.

## Next session, in order

1. Collect the five author rulings above (esp. step-change review — it is
   the biggest lever on training data — and XGBoost tuning).
2. Run the **matched-FPR sweep** on EXP-20260812-001's residual/EWMA
   outputs (single vs coordinated pipelines, healthy periods), pick
   operating points, then re-derive the EVENT-001 match, lead time, and
   diagnostic rendering there (ADR-016 criteria; full curves reported).
3. Run the **sensitivity suite** (M-27) around the base config, incl. the
   7/14/30 window sweep; conclusion-flips auto-append to LIMITATIONS.md.
4. Push commits (GitHub Desktop) and confirm CI green on the new head.
5. If rulings change config: re-run via the script (new EXP id), never by
   editing artifacts.
