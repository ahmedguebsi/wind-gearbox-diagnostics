"""Artifact directory layout and SQLite pointer store (M-29).

Evidence lives in files: the artifact directory is the scientific record;
SQLite holds identities and pointers only, so deleting the database loses
convenience, never evidence (ARCHITECTURE.md §7.2). :meth:`ArtifactStore.reindex`
rebuilds every row from the artifact directories alone (M-29 acceptance 2).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from app.core.config import AppConfig, write_resolved
from app.core.errors import ConfigError
from app.core.time import utc_now
from app.experiments.tracker import EXPERIMENT_ID_RE, ExperimentRecord

#: Mandatory artifact subdirectories (PROJECT.md §15).
ARTIFACT_SUBDIRS: tuple[str, ...] = ("model", "predictions", "residuals", "plots", "evaluation")

METADATA_FILENAME = "metadata.json"
CONFIG_FILENAME = "config.yaml"
METRICS_FILENAME = "metrics.json"

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id TEXT PRIMARY KEY,
    created_at_utc TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    artifact_dir TEXT NOT NULL
)
"""


class ArtifactStore:
    """EXP-YYYYMMDD-NNN artifact directories plus SQLite metadata pointers."""

    def __init__(self, root: Path, db_path: Path | None = None) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path if db_path is not None else self.root / "experiments.sqlite"
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute(_TABLE_SQL)

    # -- identity -----------------------------------------------------------

    def new_experiment_id(self) -> str:
        """Next EXP-YYYYMMDD-NNN, monotonic per day, derived from the artifact
        directories themselves so the database is never authoritative."""
        day = utc_now().strftime("%Y%m%d")
        prefix = f"EXP-{day}-"
        existing = [
            int(path.name[len(prefix) :])
            for path in self.root.iterdir()
            if path.is_dir() and path.name.startswith(prefix) and EXPERIMENT_ID_RE.match(path.name)
        ]
        return f"{prefix}{max(existing, default=0) + 1:03d}"

    def experiment_dir(self, experiment_id: str) -> Path:
        return self.root / experiment_id

    def create_layout(self, experiment_id: str) -> Path:
        """Create the mandatory artifact directory tree."""
        directory = self.experiment_dir(experiment_id)
        if directory.exists():
            raise ConfigError("Experiment directory already exists", experiment_id=experiment_id)
        for sub in ARTIFACT_SUBDIRS:
            (directory / sub).mkdir(parents=True)
        return directory

    # -- persistence --------------------------------------------------------

    def persist(self, record: ExperimentRecord, config: AppConfig, metrics: dict[str, Any]) -> Path:
        """Write metadata.json, config.yaml, and metrics.json; register the
        pointer row. The record is Pydantic-validated, so an incomplete §15
        field set cannot reach this point (M-29 acceptance 1)."""
        directory = self.experiment_dir(record.experiment_id)
        if not directory.is_dir():
            raise ConfigError(
                "Experiment layout missing; call create_layout first",
                experiment_id=record.experiment_id,
            )
        (directory / METADATA_FILENAME).write_text(
            json.dumps(record.model_dump(mode="json"), sort_keys=True, indent=2),
            encoding="utf-8",
        )
        write_resolved(config, directory / CONFIG_FILENAME)
        self.write_metrics(record.experiment_id, metrics)
        self._register(record, directory)
        return directory

    def write_metrics(self, experiment_id: str, metrics: dict[str, Any]) -> None:
        path = self.experiment_dir(experiment_id) / METRICS_FILENAME
        path.write_text(json.dumps(metrics, sort_keys=True, indent=2), encoding="utf-8")

    def write_report(self, experiment_id: str, name: str, payload: dict[str, Any]) -> Path:
        """Write a JSON report under evaluation/ (dataset report, audits...)."""
        path = self.experiment_dir(experiment_id) / "evaluation" / f"{name}.json"
        path.write_text(
            json.dumps(payload, sort_keys=True, indent=2, default=str), encoding="utf-8"
        )
        return path

    def _register(self, record: ExperimentRecord, directory: Path) -> None:
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute(
                "INSERT OR REPLACE INTO experiments VALUES (?, ?, ?, ?, ?)",
                (
                    record.experiment_id,
                    record.created_at_utc.isoformat(),
                    record.schema_version,
                    record.config_hash,
                    str(directory),
                ),
            )

    def registered_ids(self) -> list[str]:
        """Experiment IDs currently registered in the pointer database."""
        with closing(sqlite3.connect(self.db_path)) as connection:
            rows = connection.execute(
                "SELECT experiment_id FROM experiments ORDER BY experiment_id"
            ).fetchall()
        return [str(row[0]) for row in rows]

    # -- retrieval ----------------------------------------------------------

    def load_record(self, experiment_id: str) -> ExperimentRecord:
        path = self.experiment_dir(experiment_id) / METADATA_FILENAME
        if not path.is_file():
            raise ConfigError("Experiment metadata not found", experiment_id=experiment_id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return ExperimentRecord.model_validate(_upgrade_legacy_payload(payload))

    def load_metrics(self, experiment_id: str) -> dict[str, Any]:
        path = self.experiment_dir(experiment_id) / METRICS_FILENAME
        if not path.is_file():
            raise ConfigError("Experiment metrics not found", experiment_id=experiment_id)
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return loaded

    def list_experiments(self) -> list[str]:
        return sorted(
            path.name
            for path in self.root.iterdir()
            if path.is_dir() and EXPERIMENT_ID_RE.match(path.name)
        )

    # -- resilience ---------------------------------------------------------

    def reindex(self) -> int:
        """Rebuild every pointer row from the artifact directories alone."""
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute("DELETE FROM experiments")
        count = 0
        for experiment_id in self.list_experiments():
            record = self.load_record(experiment_id)
            self._register(record, self.experiment_dir(experiment_id))
            count += 1
        return count


#: Metadata schema migrations for records written before a field existed.
#:
#: Experiment records are permanent evidence: a run from three weeks ago must
#: stay loadable, and `reproduce` must keep working on it, or the artifact
#: retention the thesis depends on is worthless. But the M-29 contract is that
#: every PROJECT.md §15 field is REQUIRED — a record missing one cannot be
#: constructed — so a Pydantic default would weaken the contract for new
#: records in order to accommodate old ones.
#:
#: Migrating on load keeps both: the model stays strict, and legacy payloads
#: are upgraded here with an explicit marker saying the field was not recorded
#: rather than a value pretending it was. Caught by running `reproduce` against
#: the pre-ADR-039 headline experiment, which is what that command is for.
def _upgrade_legacy_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Fill fields added after this record was written, marked as unrecorded."""
    if "multiple_comparison_register" not in payload:
        # Pre-ADR-039: only the thesis model's count was kept, in `model`.
        thesis_count = int(payload.get("model", {}).get("tuning_configurations_evaluated", 0))
        payload = {
            **payload,
            "multiple_comparison_register": {
                "per_model": {"thesis": thesis_count},
                "total_configurations_evaluated": thesis_count,
                "untuned_models": (),
                "recorded_before_adr_039": True,
            },
        }
    return payload
