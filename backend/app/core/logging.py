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


@contextmanager
def experiment_logging(experiment_id: str, artifact_dir: Path) -> Iterator[Path]:
    """Bind the experiment ID and mirror all application logs to a JSON-lines
    file inside the experiment's artifact directory (M-04 acceptance 1)."""
    artifact_dir.mkdir(parents=True, exist_ok=True)
    log_path = artifact_dir / "run.log"
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ExperimentContextFilter())
    app_logger = logging.getLogger(APP_LOGGER_NAME)
    app_logger.addHandler(handler)
    try:
        with bind_experiment(experiment_id):
            yield log_path
    finally:
        app_logger.removeHandler(handler)
        handler.close()
