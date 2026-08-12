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
import re
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


class FilenamePattern(BaseModel):
    """Turbine identity derived from the source filename (per-turbine export
    files with no turbine column inside). ``pattern`` is a regex with at
    least one capture group; ``template`` expands the match (re backrefs) to
    the turbine identifier, so file naming like ``..._Kelmarsh_1_...`` can
    yield the identifier "Kelmarsh 1" used by status records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pattern: str
    template: str = r"\1"

    def extract(self, filename: str) -> str:
        match = re.search(self.pattern, filename)
        if match is None:
            raise SchemaError(
                "Filename does not match the declared turbine pattern",
                filename=filename,
                pattern=self.pattern,
            )
        return match.expand(self.template)


class DatasetSection(BaseModel):
    """Dataset-level declarations of a mapping config.

    The file-format fields describe how the export is written, not what it
    contains: vendor exports may precede the header with comment lines, may
    prefix the header row itself, and may spell missing values as a literal
    token. Declaring them here keeps dataset specifics out of code (M-07).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp_column: str
    source_timezone: str
    turbine_column: str | None = None
    turbine_id_constant: str | None = None
    #: Third turbine-identity mode: per-turbine export files named by
    #: turbine, with no turbine column inside (e.g. the Kelmarsh exports).
    turbine_id_from_filename: FilenamePattern | None = None
    #: Lines to skip before the header row (e.g. vendor comment banner).
    skip_lines: int = 0
    #: Prefix to strip from the first header cell when the header row is
    #: itself written as a comment line.
    header_comment_prefix: str | None = None
    #: Literal strings that denote missing/erroneous values.
    missing_value_tokens: tuple[str, ...] = ("NaN",)
    #: Declared source encoding. When set, ingestion reads with EXACTLY this
    #: encoding (a mismatch fails loudly); when None, strict detection
    #: applies. Silent character replacement stays prohibited either way.
    encoding: str | None = None


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

    def to_canonical(
        self,
        raw_frame: pd.DataFrame,
        schema: CanonicalSchema,
        *,
        turbine_id: str | None = None,
    ) -> pd.DataFrame:
        """Return a new frame with canonical column names (pre-UTC).

        The source frame is never modified. Raw columns not named in the
        mapping are not carried into the canonical frame. Missing declared
        columns raise :class:`SchemaError` listing every absentee.
        ``turbine_id`` supplies the per-file identity in filename mode
        (extracted by ingestion via :class:`FilenamePattern`).
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
        if self.dataset.turbine_id_from_filename is not None:
            if turbine_id is None:
                raise SchemaError(
                    "Mapping declares turbine_id_from_filename but no turbine "
                    "identity was supplied for this file"
                )
            canonical[schema.turbine_id_name] = turbine_id
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
    identity_modes = sum(
        1
        for mode in (
            mapping.dataset.turbine_column,
            mapping.dataset.turbine_id_constant,
            mapping.dataset.turbine_id_from_filename,
        )
        if mode is not None
    )
    if identity_modes != 1:
        raise SchemaError(
            "Mapping must declare exactly one of turbine_column, "
            "turbine_id_constant, or turbine_id_from_filename",
            path=str(path),
        )
    pattern = mapping.dataset.turbine_id_from_filename
    if pattern is not None:
        try:
            compiled = re.compile(pattern.pattern)
        except re.error as exc:
            raise SchemaError(
                "turbine_id_from_filename pattern is not a valid regex",
                pattern=pattern.pattern,
            ) from exc
        if compiled.groups < 1:
            raise SchemaError(
                "turbine_id_from_filename pattern needs a capture group",
                pattern=pattern.pattern,
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
