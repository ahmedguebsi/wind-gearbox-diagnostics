"""Cross-experiment thesis tables (M-28; PROJECT.md §28; ARCHITECTURE.md §8.4).

Structural guarantees, enforced here rather than by discipline:

- REFUSAL on mismatched provenance: experiments are comparable only when
  they share the schema version and the raw-source hash set; anything else
  raises unless explicitly overridden with a logged justification — no
  accidental apples-to-oranges tables.
- Every headline metric cell carries its blocked-bootstrap CI: the row type
  requires :class:`~app.evaluation.bootstrap.ConfidenceInterval` per metric,
  so a bare number cannot enter a table (M-28 acceptance 1).
- Baselines are auto-labelled from ``model_kind`` — only THESIS-kind results
  feed headline claims.
- RQ2 detection comparisons are producible ONLY from a matched-FPR
  :class:`~app.detection.matched_fpr.ComparisonReport` (M-23): no function
  in this module accepts raw alarm counts (M-28 acceptance 2).
- Results resting on provisional parameters are footnoted from the resolved
  config's ``provisional_parameters`` annotation.

Experiment metadata enters as plain dicts (the ``metadata.json`` payload):
layers communicate through data, and this module sits below the experiments
orchestrator (ARCHITECTURE.md §3).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.core.errors import ConfigError
from app.core.logging import get_logger
from app.detection.matched_fpr import ComparisonReport
from app.evaluation.bootstrap import ConfidenceInterval
from app.evaluation.dm_test import DmResult

_logger = get_logger("evaluation.comparison")


@dataclass(frozen=True)
class MetricWithCI:
    """A headline metric may not exist without its CI (M-28 acceptance 1)."""

    value: float
    ci: ConfidenceInterval

    def as_cell(self) -> str:
        return f"{self.value:.3f} [{self.ci.lower:.3f}, {self.ci.upper:.3f}]"


@dataclass(frozen=True)
class ModelAccuracyRow:
    """One (experiment, model, target) row of the RQ1 accuracy table."""

    experiment_id: str
    model_type: str
    model_kind: str
    target: str
    partition: str
    rmse: MetricWithCI
    mae: MetricWithCI
    r2: MetricWithCI
    bias: MetricWithCI
    dm_vs_thesis: DmResult | None


def _source_hashes(record: dict[str, Any]) -> frozenset[str]:
    try:
        sources = record["dataset"]["provenance"]["sources"]
        return frozenset(str(s["sha256"]) for s in sources)
    except (KeyError, TypeError) as exc:
        raise ConfigError(
            "Experiment metadata lacks a provenance chain",
            experiment=str(record.get("experiment_id")),
        ) from exc


def verify_comparable(
    records: Sequence[dict[str, Any]], *, override_justification: str | None = None
) -> None:
    """Refuse to compare mismatched schema versions or provenance chains.

    An explicit ``override_justification`` bypasses the refusal and is
    LOGGED — never silent (ARCHITECTURE.md §8.4).
    """
    if len(records) < 2:
        return
    schema_versions = {str(r.get("schema_version")) for r in records}
    hash_sets = {_source_hashes(r) for r in records}
    mismatched = len(schema_versions) > 1 or len(hash_sets) > 1
    if not mismatched:
        return
    if override_justification is None or not override_justification.strip():
        raise ConfigError(
            "Experiments are not comparable: schema versions or dataset "
            "provenance chains differ. Comparing them requires an explicit "
            "logged justification (ARCHITECTURE.md §8.4)",
            schema_versions=sorted(schema_versions),
        )
    _logger.warning(
        "Provenance/schema mismatch overridden for comparison table: %s",
        override_justification,
    )


def provisional_footnote(record: dict[str, Any]) -> str:
    """Footnote for results still resting on provisional values (§27.3)."""
    parameters = record.get("resolved_config", {}).get("provisional_parameters", [])
    if not parameters:
        return ""
    return "provisional: " + ", ".join(str(p) for p in parameters)


def build_accuracy_table(
    records: Sequence[dict[str, Any]],
    rows: Sequence[ModelAccuracyRow],
    *,
    override_provenance_mismatch: str | None = None,
) -> pd.DataFrame:
    """The RQ1 thesis accuracy table: metrics [CI], DM vs thesis, labels."""
    verify_comparable(records, override_justification=override_provenance_mismatch)
    footnotes = {str(r.get("experiment_id")): provisional_footnote(r) for r in records}
    table_rows: list[dict[str, Any]] = []
    for row in rows:
        table_rows.append(
            {
                "experiment": row.experiment_id,
                "model": row.model_type,
                "kind": row.model_kind.upper(),
                "target": row.target,
                "partition": row.partition,
                "rmse": row.rmse.as_cell(),
                "mae": row.mae.as_cell(),
                "r2": row.r2.as_cell(),
                "bias": row.bias.as_cell(),
                "dm_vs_thesis_p": (None if row.dm_vs_thesis is None else row.dm_vs_thesis.p_value),
                "footnote": footnotes.get(row.experiment_id, ""),
            }
        )
    return pd.DataFrame(table_rows)


def rq2_table(report: ComparisonReport) -> pd.DataFrame:
    """The ONLY RQ2 detection-comparison table entry point (M-23 routing).

    Takes a matched-FPR ComparisonReport — raw alarm counts are not a
    representable input anywhere in this module. Emits one row per
    (pipeline, FPR target) with the matched multiplier and reachability;
    the full operating curves remain embedded in the report itself and are
    exported alongside (M-23 acceptance 2).
    """
    rows = [
        {
            "pipeline": point.pipeline,
            "fpr_target_per_turbine_year": point.fpr_target,
            "matched_multiplier": point.multiplier,
            "reachable": point.reachable,
        }
        for point in report.matched
    ]
    return pd.DataFrame(rows)
