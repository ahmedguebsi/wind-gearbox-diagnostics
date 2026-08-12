"""Dataset ingestion with provenance and deduplication (M-09; PROJECT.md §8, §10).

Pipeline per file: read (strict encoding) → map raw→canonical (M-07) → UTC
normalize exactly once → stamp provenance (M-08). Across files: concatenate,
then deduplicate.

Deduplication exists because export year-folders overlap at their boundaries
(the Kelmarsh 2017 status file begins 2016-12-17; the 2021 file begins
2020-06-07), so naive concatenation double-counts. Rows sharing the key are
collapsed **only when their content is byte-identical**; a key collision with
differing content raises, because silently picking one would fabricate a
record present in neither source file.

Source files are opened read-only and never modified.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.errors import ProvenanceError, SchemaError
from app.core.logging import get_logger
from app.core.time import localize_to_utc
from app.data.mapping import ColumnMapping
from app.data.provenance import ProvenanceChain, ProvenanceRecord
from app.data.schema import CanonicalSchema, VariableRole

_logger = get_logger("data.ingestion")

#: Encodings tried in order, strictly. Silent character replacement is
#: prohibited: it corrupts degree signs and vendor text leaving no trace.
ENCODING_CANDIDATES: tuple[str, ...] = ("utf-8", "cp1252", "latin-1")


def detect_encoding(path: Path) -> str:
    """First candidate encoding that decodes the whole file strictly."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ProvenanceError("Cannot read source file", path=str(path)) from exc
    for encoding in ENCODING_CANDIDATES:
        try:
            raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        return encoding
    raise SchemaError(
        "Source file is not decodable by any supported encoding",
        path=str(path),
        tried=list(ENCODING_CANDIDATES),
    )


@dataclass(frozen=True)
class DeduplicationReport:
    """What concatenation removed, and on what key."""

    key_columns: tuple[str, ...]
    rows_before: int
    rows_after: int
    duplicates_removed: int
    removed_per_source: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "key_columns": list(self.key_columns),
            "rows_before": self.rows_before,
            "rows_after": self.rows_after,
            "duplicates_removed": self.duplicates_removed,
            "removed_per_source": dict(self.removed_per_source),
        }


@dataclass(frozen=True)
class CanonicalDataset:
    """Canonically named, UTC-normalized data with mandatory provenance.

    Provenance is structural: the dataset cannot be constructed without a
    chain, so no downstream artifact can lose track of its source bytes.
    """

    frame: pd.DataFrame
    schema_version: str
    provenance: ProvenanceChain
    roles: dict[str, VariableRole]
    deduplication: DeduplicationReport | None = None

    def __post_init__(self) -> None:
        if not self.provenance.sources:
            raise ProvenanceError("CanonicalDataset requires at least one provenance record")

    @property
    def content_hash(self) -> str:
        """Stable hash of the frame's contents, for chain extension."""
        hashed = pd.util.hash_pandas_object(self.frame, index=True).to_numpy()
        return hashlib.sha256(hashed.tobytes()).hexdigest()

    def with_frame(self, frame: pd.DataFrame, stage: str) -> CanonicalDataset:
        """A derived dataset whose provenance chain records this stage."""
        derived = CanonicalDataset(
            frame=frame,
            schema_version=self.schema_version,
            provenance=self.provenance,
            roles=self.roles,
            deduplication=self.deduplication,
        )
        return CanonicalDataset(
            frame=frame,
            schema_version=self.schema_version,
            provenance=self.provenance.extended(stage, derived.content_hash),
            roles=self.roles,
            deduplication=self.deduplication,
        )


def _read_frame(path: Path, mapping: ColumnMapping, encoding: str) -> pd.DataFrame:
    read_kwargs: dict[str, Any] = {
        "encoding": encoding,
        "low_memory": False,
        "na_values": list(mapping.dataset.missing_value_tokens),
    }
    if mapping.dataset.skip_lines:
        read_kwargs["skiprows"] = mapping.dataset.skip_lines
    if path.suffix.lower() == ".parquet":
        frame = pd.read_parquet(path)
    else:
        frame = pd.read_csv(path, header=0, **read_kwargs)
    if mapping.dataset.header_comment_prefix:
        prefix = mapping.dataset.header_comment_prefix
        first = list(frame.columns)[:1]
        frame = frame.rename(columns={c: str(c).removeprefix(prefix).lstrip() for c in first})
    return frame


def _to_utc(frame: pd.DataFrame, mapping: ColumnMapping, schema: CanonicalSchema) -> pd.DataFrame:
    """Convert the timestamp column to UTC exactly once."""
    column = schema.timestamp_name
    parsed = pd.to_datetime(frame[column], errors="coerce")
    if parsed.dt.tz is None:
        zone = mapping.dataset.source_timezone
        if zone.upper() == "UTC":
            converted = parsed.dt.tz_localize("UTC")
        else:
            converted = parsed.map(
                lambda value: pd.NaT if pd.isna(value) else localize_to_utc(value, zone)
            )
            converted = pd.to_datetime(converted, utc=True)
    else:
        converted = parsed.dt.tz_convert("UTC")
    result = frame.copy()
    result[column] = converted
    return result


def _apply_span(
    frame: pd.DataFrame,
    schema: CanonicalSchema,
    span_start: date | None,
    span_end: date | None,
) -> pd.DataFrame:
    """Restrict to the modelling span (ADR-009). Bounds are inclusive dates."""
    if span_start is None and span_end is None:
        return frame
    stamps = frame[schema.timestamp_name]
    mask = pd.Series(True, index=frame.index)
    if span_start is not None:
        mask &= stamps >= pd.Timestamp(span_start, tz="UTC")
    if span_end is not None:
        end = pd.Timestamp(datetime.combine(span_end, datetime.max.time()), tz="UTC")
        mask &= stamps <= end
    return frame[mask]


def _row_content_hash(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    return pd.util.hash_pandas_object(frame[columns], index=False)


def deduplicate(
    frame: pd.DataFrame, key_columns: Sequence[str], source_column: str = "__source__"
) -> tuple[pd.DataFrame, DeduplicationReport]:
    """Collapse rows sharing ``key_columns`` when their content matches.

    Raises :class:`ProvenanceError` if two rows share a key but differ in any
    other field — the pipeline must never invent a record by choosing one.
    """
    keys = [c for c in key_columns if c in frame.columns]
    if not keys:
        raise SchemaError("Deduplication key columns absent", key_columns=list(key_columns))
    content_columns = [c for c in frame.columns if c != source_column]
    rows_before = len(frame)

    duplicated_mask = frame.duplicated(subset=keys, keep=False)
    if duplicated_mask.any():
        candidates = frame[duplicated_mask]
        hashes = _row_content_hash(candidates, content_columns)
        grouped = hashes.groupby([candidates[k] for k in keys], observed=True).nunique()
        conflicting = grouped[grouped > 1]
        if not conflicting.empty:
            raise ProvenanceError(
                "Rows share a deduplication key but differ in content; "
                "resolving this silently would fabricate a record present in "
                "neither source file",
                key_columns=keys,
                n_conflicting_keys=len(conflicting),
                example_key=str(conflicting.index[0]),
            )

    deduped = frame.drop_duplicates(subset=keys, keep="first")
    removed_per_source: dict[str, int] = {}
    if source_column in frame.columns:
        dropped = frame.loc[frame.index.difference(deduped.index)]
        removed_per_source = {
            str(name): int(count) for name, count in dropped[source_column].value_counts().items()
        }
    report = DeduplicationReport(
        key_columns=tuple(keys),
        rows_before=rows_before,
        rows_after=len(deduped),
        duplicates_removed=rows_before - len(deduped),
        removed_per_source=removed_per_source,
    )
    if report.duplicates_removed:
        _logger.info(
            "Deduplicated %d rows on %s across %d source file(s)",
            report.duplicates_removed,
            keys,
            len(removed_per_source) or 1,
        )
    return deduped.drop(columns=[source_column], errors="ignore"), report


def ingest_files(
    paths: Sequence[Path],
    mapping: ColumnMapping,
    schema: CanonicalSchema,
    *,
    span_start: date | None = None,
    span_end: date | None = None,
    supplier_note: str = "",
) -> CanonicalDataset:
    """Ingest one or more source files into a single canonical dataset.

    Files are read strictly, mapped, UTC-normalized, optionally restricted to
    the modelling span, concatenated, and deduplicated on
    ``(turbine_id, timestamp)`` — extended with the code column when the
    schema defines one (status/event exports).
    """
    if not paths:
        raise SchemaError("No source files supplied to ingestion")

    frames: list[pd.DataFrame] = []
    records: list[ProvenanceRecord] = []
    for path in paths:
        encoding = mapping.dataset.encoding or detect_encoding(path)
        raw = _read_frame(path, mapping, encoding)
        turbine_id = (
            mapping.dataset.turbine_id_from_filename.extract(path.name)
            if mapping.dataset.turbine_id_from_filename is not None
            else None
        )
        canonical = mapping.to_canonical(raw, schema, turbine_id=turbine_id)
        canonical = _to_utc(canonical, mapping, schema)
        canonical = _apply_span(canonical, schema, span_start, span_end)
        canonical["__source__"] = path.name
        frames.append(canonical)
        records.append(
            ProvenanceRecord.capture(
                path,
                source_timezone=mapping.dataset.source_timezone,
                encoding=encoding,
                schema_version=schema.schema_version,
                mapping_hash=mapping.mapping_hash,
                supplier_note=supplier_note,
            )
        )

    combined = pd.concat(frames, ignore_index=True)
    key_columns = [schema.turbine_id_name, schema.timestamp_name]
    for extra in schema.by_role(VariableRole.STATUS):
        if extra.name in combined.columns:
            key_columns.append(extra.name)
    deduped, report = deduplicate(combined, key_columns)
    deduped = deduped.sort_values([schema.turbine_id_name, schema.timestamp_name]).reset_index(
        drop=True
    )

    roles = {name: schema.variable(name).role for name in deduped.columns if name in schema.names()}
    return CanonicalDataset(
        frame=deduped,
        schema_version=schema.schema_version,
        provenance=ProvenanceChain(sources=tuple(records)),
        roles=roles,
        deduplication=report,
    )
