"""M-01 tests: exception taxonomy (ARCHITECTURE.md §12)."""

import ast
from pathlib import Path

import pytest

from app.core import errors
from app.core.errors import (
    AppError,
    CausalSeparationError,
    ConfigError,
    FmeaRuleError,
    ProvenanceError,
    ReproductionMismatch,
    SchemaError,
    SplitPolicyError,
    ThresholdProvenanceError,
    TimezoneError,
)

ALL_ERRORS = [
    ConfigError,
    SchemaError,
    TimezoneError,
    ProvenanceError,
    CausalSeparationError,
    SplitPolicyError,
    ThresholdProvenanceError,
    FmeaRuleError,
    ReproductionMismatch,
]


@pytest.mark.parametrize("exc_type", ALL_ERRORS)
def test_every_exception_is_an_app_error(exc_type):
    assert issubclass(exc_type, AppError)
    assert issubclass(exc_type, Exception)


def test_context_fields_preserved_and_in_message():
    exc = TimezoneError("Unknown source timezone", timezone="Mars/Olympus")
    assert exc.context == {"timezone": "Mars/Olympus"}
    assert "Mars/Olympus" in str(exc)
    assert "Unknown source timezone" in str(exc)


def test_no_context_leaves_message_clean():
    exc = AppError("plain message")
    assert str(exc) == "plain message"
    assert exc.context == {}


def test_no_ad_hoc_exceptions_outside_taxonomy():
    """M-01 acceptance 2 (meta-test): no module in ``app`` defines a direct
    Exception/BaseException subclass outside core/errors.py."""
    app_root = Path(errors.__file__).resolve().parents[1]
    offenders: list[str] = []
    for py_file in app_root.rglob("*.py"):
        if py_file.resolve() == Path(errors.__file__).resolve():
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                base_names = {base.id for base in node.bases if isinstance(base, ast.Name)}
                if base_names & {"Exception", "BaseException"}:
                    offenders.append(f"{py_file.name}:{node.name}")
    assert offenders == [], f"Ad-hoc exceptions outside core/errors.py: {offenders}"
