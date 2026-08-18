"""Structured logging with experiment-ID context binding (M-04).

Every pipeline run under an experiment binds its experiment ID with
:func:`bind_experiment` (or the combined :func:`experiment_logging`), and the
ID travels with every record emitted from nested calls — including a JSON-lines
log file written inside the experiment's artifact directory (PROJECT.md §15).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

APP_LOGGER_NAME = "app"

_experiment_id: ContextVar[str | None] = ContextVar("experiment_id", default=None)


def current_experiment_id() -> str | None:
    """Experiment ID bound in the current context, if any."""
    return _experiment_id.get()


class ExperimentContextFilter(logging.Filter):
    """Injects the bound experiment ID into every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.experiment_id = _experiment_id.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line; timestamps are UTC ISO-8601."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        experiment_id = getattr(record, "experiment_id", None)
        if experiment_id is not None:
            payload["experiment_id"] = experiment_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True)


def setup_logging(level: str = "INFO", json_console: bool = False) -> logging.Logger:
    """Configure the application root logger (idempotent)."""
    logger = logging.getLogger(APP_LOGGER_NAME)
    logger.setLevel(level)
    logger.handlers.clear()
    handler = logging.StreamHandler()
    if json_console:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s [exp=%(experiment_id)s] %(message)s"
            )
        )
    handler.addFilter(ExperimentContextFilter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_logger(name: str) -> logging.Logger:
    """A child logger under the application namespace."""
    return logging.getLogger(f"{APP_LOGGER_NAME}.{name}")


@contextmanager
def bind_experiment(experiment_id: str) -> Iterator[None]:
    """Bind an experiment ID to the current context for the duration."""
    token = _experiment_id.set(experiment_id)
    try:
        yield
    finally:
        _experiment_id.reset(token)


class BufferingHandler(logging.Handler):
    """Holds formatted records in memory until a destination is known.

    The pipeline runs to completion BEFORE an experiment ID is minted (nothing
    touches the artifact root unless the whole run succeeds), so the entire
    scientific phase — ingestion, validation, cleaning, healthy-state
    construction, the seasonal-coverage warning — used to log to console only
    and never reached ``run.log``. The stored log of the EXP-20260817-001
    headline run was a single line: the LIMITATIONS append from the
    persistence phase (ADR-043).
    """

    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(JsonFormatter())
        self.addFilter(ExperimentContextFilter())
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(self.format(record))


@contextmanager
def buffered_logs() -> Iterator[BufferingHandler]:
    """Capture application logs in memory for later attachment to a run."""
    handler = BufferingHandler()
    app_logger = logging.getLogger(APP_LOGGER_NAME)
    app_logger.addHandler(handler)
    try:
        yield handler
    finally:
        app_logger.removeHandler(handler)
        handler.close()


@contextmanager
def experiment_logging(
    experiment_id: str, artifact_dir: Path, replay: BufferingHandler | None = None
) -> Iterator[Path]:
    """Bind the experiment ID and mirror all application logs to a JSON-lines
    file inside the experiment's artifact directory (M-04 acceptance 1).

    ``replay`` prepends records captured before the experiment directory
    existed, so the artifact holds the whole run rather than its final phase.
    """
    artifact_dir.mkdir(parents=True, exist_ok=True)
    log_path = artifact_dir / "run.log"
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ExperimentContextFilter())
    app_logger = logging.getLogger(APP_LOGGER_NAME)
    app_logger.addHandler(handler)
    try:
        if replay is not None and replay.records:
            with log_path.open("a", encoding="utf-8") as stream:
                stream.write("\n".join(replay.records) + "\n")
        with bind_experiment(experiment_id):
            yield log_path
    finally:
        app_logger.removeHandler(handler)
        handler.close()
