"""Raw-column → canonical-column mapping (M-07; PROJECT.md §8).

Dataset-specific column names live ONLY in mapping YAML configs — never in
code. A mapping declares the mandatory ``source_timezone`` (stop-and-ask if
unknown: ingestion cannot proceed without it), the raw timestamp column, and
how the turbine identity is obtained (a raw column for multi-turbine files,
or a declared constant for single-turbine export files).

Mapping YAML shape::

    schema_version: 1.0.0
    dataset:
      timestamp_column: <raw name>          # required
      source_timezone: Europe/London        # MANDATORY (TimezoneError if absent)
      turbine_column: <raw name>            # exactly one of these two
      turbine_id_constant: "T01"            #
    columns:
      <RawColumnName>:
        canonical: wind_speed               # must exist in the canonical schema

UTC conversion itself happens once, at ingestion (M-09) — this module only
translates names and carries the declared timezone and mapping hash forward
for provenance.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from app.core.errors import SchemaError, TimezoneError
from app.core.logging import get_logger
from app.core.time import get_zone
from app.data.schema import SCHEMA_VERSION, CanonicalSchema, VariableRole

_logger = get_logger("data.mapping")


class DatasetSection(BaseModel):
    """Dataset-level declarations of a mapping config."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp_column: str
    source_timezone: str
    turbine_column: str | None = None
    turbine_id_constant: str | None = None


class ColumnSpec(BaseModel):
    """One raw column's canonical assignment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    canonical: str


class ColumnMapping(BaseModel):
    """Validated raw→canonical mapping for one dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    dataset: DatasetSection
    columns: dict[str, ColumnSpec]

    def is_outdated(self, current_version: str = SCHEMA_VERSION) -> bool:
        return self.schema_version != current_version

    @property
    def mapping_hash(self) -> str:
        """SHA-256 of the canonical serialization — recorded in provenance
        (M-08) and experiment metadata (PROJECT.md §15)."""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_canonical(self, raw_frame: pd.DataFrame, schema: CanonicalSchema) -> pd.DataFrame:
        """Return a new frame with canonical column names (pre-UTC).

        The source frame is never modified. Raw columns not named in the
        mapping are not carried into the canonical frame. Missing declared
        columns raise :class:`SchemaError` listing every absentee.
        """
        required_raw = [self.dataset.timestamp_column, *self.columns.keys()]
        if self.dataset.turbine_column is not None:
            required_raw.append(self.dataset.turbine_column)
        missing = [c for c in required_raw if c not in raw_frame.columns]
        if missing:
            raise SchemaError(
                "Raw columns declared in mapping are absent from the data",
                missing=sorted(missing),
            )

        rename: dict[str, str] = {self.dataset.timestamp_column: schema.timestamp_name}
        if self.dataset.turbine_column is not None:
            rename[self.dataset.turbine_column] = schema.turbine_id_name
        for raw_name, spec in self.columns.items():
            rename[raw_name] = spec.canonical

        canonical = raw_frame[list(rename.keys())].rename(columns=rename)
        if self.dataset.turbine_id_constant is not None:
            canonical[schema.turbine_id_name] = self.dataset.turbine_id_constant
        return canonical


def load_mapping(path: Path, schema: CanonicalSchema) -> ColumnMapping:
    """Load and validate a mapping YAML against the canonical schema.

    Raises ``TimezoneError`` when ``source_timezone`` is missing, empty, or
    unresolvable (PROJECT.md §8: stop and ask — never guess), and
    ``SchemaError`` for every other structural violation. An outdated
    ``schema_version`` loads with a clear warning.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SchemaError("Mapping file unreadable", path=str(path)) from exc
    try:
        raw: Any = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SchemaError("Mapping file is not valid YAML", path=str(path)) from exc
    if not isinstance(raw, dict):
        raise SchemaError("Mapping root must be a mapping", path=str(path))

    dataset_section = raw.get("dataset")
    tz = dataset_section.get("source_timezone") if isinstance(dataset_section, dict) else None
    if not isinstance(tz, str) or not tz.strip():
        raise TimezoneError(
            "Mapping declares no source_timezone; ingestion must stop and ask "
            "(PROJECT.md §8) — never guess a timezone",
            path=str(path),
        )
    get_zone(tz)  # unresolvable zone name → TimezoneError

    try:
        mapping = ColumnMapping.model_validate(raw)
    except ValidationError as exc:
        raise SchemaError("Invalid mapping configuration", detail=str(exc)) from exc

    _validate_against_schema(mapping, schema, path)

    if mapping.is_outdated():
        _logger.warning(
            "Mapping was written for schema %s but current schema is %s; "
            "review before use (PROJECT.md §8)",
            mapping.schema_version,
            SCHEMA_VERSION,
        )
    return mapping


def _validate_against_schema(mapping: ColumnMapping, schema: CanonicalSchema, path: Path) -> None:
    exactly_one = (mapping.dataset.turbine_column is None) != (
        mapping.dataset.turbine_id_constant is None
    )
    if not exactly_one:
        raise SchemaError(
            "Mapping must declare exactly one of turbine_column or turbine_id_constant",
            path=str(path),
        )

    structural = {schema.timestamp_name, schema.turbine_id_name}
    known = schema.names()
    assigned: dict[str, str] = {}
    for raw_name, spec in mapping.columns.items():
        if spec.canonical not in known:
            raise SchemaError(
                "Mapping assigns an unknown canonical variable",
                raw_column=raw_name,
                canonical=spec.canonical,
            )
        if spec.canonical in structural:
            raise SchemaError(
                "Structural variables are declared in the dataset section, not columns",
                raw_column=raw_name,
                canonical=spec.canonical,
            )
        if spec.canonical in assigned.values():
            raise SchemaError(
                "Two raw columns assigned to the same canonical variable",
                canonical=spec.canonical,
            )
        assigned[raw_name] = spec.canonical

    mapped_roles = {schema.variable(c).role for c in assigned.values()}
    if VariableRole.TARGET not in mapped_roles:
        raise SchemaError(
            "Mapping covers no thermal target; at least one TARGET variable is required",
            path=str(path),
        )
