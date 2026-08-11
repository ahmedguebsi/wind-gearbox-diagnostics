"""Data provenance capture (M-08; PROJECT.md §10).

Every raw file is SHA-256 hashed at ingestion and the record travels with the
data: raw → cleaned → healthy is a chain, so any downstream artifact can name
the exact bytes it came from. Raw files are never modified.

Provenance is mandatory, enforced structurally: :class:`CanonicalDataset`
(M-09) cannot be constructed without a record.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import ProvenanceError
from app.core.time import utc_now

CHUNK_BYTES = 1 << 20


def sha256_of_file(path: Path) -> str:
    """SHA-256 of a file, streamed so large SCADA exports do not load whole."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ProvenanceError("Cannot hash source file", path=str(path)) from exc
    return digest.hexdigest()


class ProvenanceRecord(BaseModel):
    """Identity of one ingested source file (PROJECT.md §10 field set)."""

    model_config = ConfigDict(frozen=True)

    sha256: str
    source_path: str
    source_filename: str
    size_bytes: int
    ingested_at_utc: datetime
    source_timezone: str
    encoding: str
    schema_version: str
    mapping_hash: str
    supplier_note: str = ""

    @classmethod
    def capture(
        cls,
        path: Path,
        *,
        source_timezone: str,
        encoding: str,
        schema_version: str,
        mapping_hash: str,
        supplier_note: str = "",
    ) -> ProvenanceRecord:
        if not path.is_file():
            raise ProvenanceError("Source file not found", path=str(path))
        return cls(
            sha256=sha256_of_file(path),
            source_path=str(path.resolve()),
            source_filename=path.name,
            size_bytes=path.stat().st_size,
            ingested_at_utc=utc_now(),
            source_timezone=source_timezone,
            encoding=encoding,
            schema_version=schema_version,
            mapping_hash=mapping_hash,
            supplier_note=supplier_note,
        )

    def verify(self) -> None:
        """Re-hash the source file and raise if it no longer matches."""
        path = Path(self.source_path)
        if not path.is_file():
            raise ProvenanceError("Source file missing at verification", path=self.source_path)
        current = sha256_of_file(path)
        if current != self.sha256:
            raise ProvenanceError(
                "Source file content changed since ingestion",
                path=self.source_path,
                expected=self.sha256,
                actual=current,
            )


class ProvenanceChain(BaseModel):
    """Ordered lineage from raw sources through each transformation stage.

    ``sources`` holds one record per raw file. ``stages`` records each
    downstream transformation as (stage name, content hash of its output), so
    a cleaned or healthy dataset names both its ancestors and its own identity.
    """

    model_config = ConfigDict(frozen=True)

    sources: tuple[ProvenanceRecord, ...]
    stages: tuple[tuple[str, str], ...] = Field(default_factory=tuple)

    @property
    def source_hashes(self) -> tuple[str, ...]:
        return tuple(record.sha256 for record in self.sources)

    def extended(self, stage: str, content_hash: str) -> ProvenanceChain:
        """A new chain with one more stage appended; ancestry preserved."""
        return ProvenanceChain(sources=self.sources, stages=(*self.stages, (stage, content_hash)))

    def verify_sources(self) -> None:
        for record in self.sources:
            record.verify()
