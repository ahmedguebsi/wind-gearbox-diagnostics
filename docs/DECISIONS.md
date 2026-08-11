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

## ADR-002 — Literature-anchored baseline NBM choice

Status:            OPEN
Question:          Which literature-anchored baseline NBM accompanies Random
                   Forest as an RQ1 comparator? (PROJECT.md §18; M-17
                   acceptance 2 requires the rationale and citation recorded
                   here before M-17 is DONE.)
Options:           To be enumerated from the SCADA-NBM literature review
                   (e.g., an ANN-style NBM consistent with established
                   literature). Deep learning is prohibited (PROJECT.md §39
                   reference in §5) — the baseline must respect that bound.
Evidence to close: Thesis literature review; supervisor confirmation.
Decision:          —
Justification:     —
Affected modules:  M-17

## ADR-003 — LightGBM as an optional later comparator

Status:            OPEN
Question:          Is a LightGBM comparator added alongside the mandated
                   baselines? Permitted only with ADR justification
                   (PROJECT.md §5). Default position: NOT added.
Options:           add | omit (default)
Evidence to close: A demonstrated RQ1 need the existing baselines cannot meet.
Decision:          —
Justification:     —
Affected modules:  M-17 (if added)

## ADR-004 — Canonical schema version log

Status:            OPEN (standing log)
Question:          Standing record of `schema_version` bumps (semver) required
                   by PROJECT.md §8. Each schema change appends an entry here
                   with its rationale.
Current version:   1.0.0 (initial; to be stamped by M-06 when implemented)
Affected modules:  M-06, M-07, M-29

## ADR-005 — FMEA rule sign-off log

Status:            OPEN (standing log)
Question:          Standing record of FMEA rule validations (Guard 7). A rule's
                   `validated` flag flips to true only through an entry here
                   citing the specific literature source (PROJECT.md §26).
                   Never invent references.
Entries:           none yet
Affected modules:  M-25, M-26
