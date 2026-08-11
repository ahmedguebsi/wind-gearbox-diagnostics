"""Application-wide exception taxonomy (M-01; ARCHITECTURE.md §12).

Methodology violations are exceptions: they stop execution unconditionally.
Data-quality issues are Findings (INFO/WARNING/ERROR data, defined with the
validation layer), not exceptions. This separation keeps "the data is
imperfect" distinct from "the science is being done wrong".

Every application exception must be defined here and importable from this
single location; a meta-test scans the codebase for ad-hoc Exception
subclasses defined elsewhere.
"""

from __future__ import annotations


class AppError(Exception):
    """Base class for all application errors.

    Accepts arbitrary keyword context fields, preserved on ``self.context``
    and appended to the message for diagnostics.
    """

    def __init__(self, message: str, **context: object) -> None:
        self.context: dict[str, object] = context
        if context:
            details = ", ".join(f"{key}={value!r}" for key, value in context.items())
            message = f"{message} [{details}]"
        self.message = message
        super().__init__(message)


class ConfigError(AppError):
    """Malformed or unresolvable configuration (M-03)."""


class SchemaError(AppError):
    """Canonical schema version or variable-role violation (M-06/M-07)."""


class TimezoneError(AppError):
    """Naive datetime, unknown timezone, or missing ``source_timezone``.

    PROJECT.md §8: if the source timezone is unknown, ingestion stops and
    asks — it is never guessed.
    """


class ProvenanceError(AppError):
    """Hash mismatch, missing provenance, or unavailable code identity (M-08)."""


class CausalSeparationError(AppError):
    """Guards 1, 2, 8 (PROJECT.md §33): causal predictor-target separation
    violated (target-as-predictor, future information, or any target-derived
    feature)."""


class SplitPolicyError(AppError):
    """Guard 3 (LOCKED-04): non-chronological split requested for a
    thesis-official experiment."""


class ThresholdProvenanceError(AppError):
    """Guard 4: normalization/threshold statistics derived from a non-healthy
    (fault/test) partition."""


class FmeaRuleError(AppError):
    """Malformed FMEA ruleset or sign-off policy violation (M-25)."""


class ReproductionMismatch(AppError):
    """``reproduce EXP-ID`` regenerated results that do not match the stored
    artifacts (M-31)."""
