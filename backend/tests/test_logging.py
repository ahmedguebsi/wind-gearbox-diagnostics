"""M-04 tests: structured logging and experiment-ID context binding."""

import json
import logging
from pathlib import Path

from app.core.logging import (
    APP_LOGGER_NAME,
    bind_experiment,
    current_experiment_id,
    experiment_logging,
    get_logger,
    setup_logging,
)


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _attach_capture() -> _CaptureHandler:
    capture = _CaptureHandler()
    logging.getLogger(APP_LOGGER_NAME).addHandler(capture)
    return capture


def _detach_capture(capture: _CaptureHandler) -> None:
    logging.getLogger(APP_LOGGER_NAME).removeHandler(capture)


class TestContextBinding:
    def test_experiment_id_present_on_nested_calls(self):
        setup_logging(level="INFO")
        capture = _attach_capture()
        try:

            def nested_call():
                get_logger("pipeline.stage").info("from deep inside")

            with bind_experiment("EXP-20260811-001"):
                nested_call()
        finally:
            _detach_capture(capture)
        assert len(capture.records) == 1
        assert capture.records[0].experiment_id == "EXP-20260811-001"

    def test_binding_is_scoped(self):
        assert current_experiment_id() is None
        with bind_experiment("EXP-20260811-002"):
            assert current_experiment_id() == "EXP-20260811-002"
        assert current_experiment_id() is None

    def test_no_binding_yields_none_on_records(self):
        setup_logging(level="INFO")
        capture = _attach_capture()
        try:
            get_logger("x").info("unbound")
        finally:
            _detach_capture(capture)
        assert capture.records[0].experiment_id is None


class TestLevelFiltering:
    def test_below_level_records_suppressed(self):
        setup_logging(level="WARNING")
        capture = _attach_capture()
        try:
            logger = get_logger("filtering")
            logger.info("should not appear")
            logger.warning("should appear")
        finally:
            _detach_capture(capture)
        assert [r.getMessage() for r in capture.records] == ["should appear"]


class TestExperimentLogFile:
    def test_log_written_inside_artifact_directory(self, tmp_path: Path):
        """M-04 acceptance 1: a run under an experiment writes its log inside
        that experiment's artifact directory, as JSON lines carrying the ID."""
        setup_logging(level="INFO")
        artifact_dir = tmp_path / "EXP-20260811-003"
        with experiment_logging("EXP-20260811-003", artifact_dir) as log_path:
            get_logger("runner").info("stage complete")
        assert log_path.parent == artifact_dir
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        payloads = [json.loads(line) for line in lines]
        assert payloads[-1]["message"] == "stage complete"
        assert payloads[-1]["experiment_id"] == "EXP-20260811-003"
        assert payloads[-1]["level"] == "INFO"
        assert payloads[-1]["timestamp"].endswith("+00:00")  # UTC

    def test_handler_removed_after_context(self, tmp_path: Path):
        setup_logging(level="INFO")
        app_logger = logging.getLogger(APP_LOGGER_NAME)
        before = list(app_logger.handlers)
        with experiment_logging("EXP-20260811-004", tmp_path / "exp"):
            assert len(app_logger.handlers) == len(before) + 1
        assert app_logger.handlers == before


class TestBufferedReplay:
    """ADR-043: the whole run reaches run.log, not only its final phase.

    ``run_experiment`` completes the pipeline in memory BEFORE minting an
    experiment ID (nothing touches the artifact root unless the run succeeds),
    so the entire scientific phase logged to console only. EXP-20260817-001's
    stored run.log was one line long.
    """

    def test_records_from_before_the_directory_existed_are_replayed(self, tmp_path):
        from app.core.logging import buffered_logs, experiment_logging, get_logger

        setup_logging()
        logger = get_logger("pipeline")
        with buffered_logs() as buffered:
            logger.warning("seasonal coverage: the model extrapolates")
            logger.info("healthy state: 656293/847011 retained")
        assert len(buffered.records) == 2

        directory = tmp_path / "EXP-20260101-001"
        with experiment_logging("EXP-20260101-001", directory, replay=buffered):
            logger.info("persisting experiment")

        lines = [
            json.loads(line)
            for line in (directory / "run.log").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        messages = [entry["message"] for entry in lines]
        assert "seasonal coverage: the model extrapolates" in messages
        assert "healthy state: 656293/847011 retained" in messages
        assert "persisting experiment" in messages

    def test_replay_is_optional_and_absent_buffer_changes_nothing(self, tmp_path):
        from app.core.logging import experiment_logging, get_logger

        setup_logging()
        directory = tmp_path / "EXP-20260101-002"
        with experiment_logging("EXP-20260101-002", directory):
            get_logger("pipeline").info("only this")
        content = (directory / "run.log").read_text(encoding="utf-8").strip().splitlines()
        assert len(content) == 1
