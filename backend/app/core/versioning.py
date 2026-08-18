"""Identity capture for experiment metadata (M-05; PROJECT.md §15).

Captures, at runtime, everything needed to reproduce a result months later:
application version, canonical schema version, git commit + dirty flag, and
the installed versions of every scientific library the spec names. All fields
are mandatory — a stamp with omissions cannot be constructed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app import __version__ as APP_VERSION
from app.core.errors import ProvenanceError

#: Libraries whose versions PROJECT.md §15 requires in experiment metadata.
REQUIRED_LIBRARIES: tuple[str, ...] = (
    "numpy",
    "pandas",
    "scikit-learn",
    "xgboost",
    "scipy",
    "statsmodels",
)


class VersionStamp(BaseModel):
    """Complete identity record consumed by experiment tracking (M-29)."""

    model_config = ConfigDict(frozen=True)

    app_version: str
    schema_version: str
    python_version: str
    git_commit: str
    git_dirty: bool
    library_versions: dict[str, str]
    #: ADR-044 refinement. ``git_dirty`` is true for ANY working-tree
    #: difference, untracked files included, which conflates two very
    #: different things:
    #:
    #: - UNCOMMITTED MODIFICATIONS to tracked files mean the recorded commit
    #:   does not describe the code that ran. That voids reproducibility.
    #: - UNTRACKED files usually do not. On this repository they are the
    #:   author's own documents and the governing specification, which the
    #:   README states live outside the repository by design.
    #:
    #: Both are recorded; only the first blocks a citable run. Defaults keep
    #: pre-ADR-044 stamps loadable (the ADR-039 lesson).
    git_tracked_dirty: bool = False
    git_untracked_files: int = 0


def _git(args: list[str], cwd: Path) -> str:
    git_exe = shutil.which("git")
    if git_exe is None:
        raise ProvenanceError("git executable not found; code identity cannot be captured")
    result = subprocess.run([git_exe, *args], cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ProvenanceError(
            "git command failed; code identity cannot be captured",
            command=" ".join(args),
            stderr=result.stderr.strip(),
        )
    return result.stdout.strip()


def capture_library_versions() -> dict[str, str]:
    """Installed versions of python plus every required scientific library."""
    versions: dict[str, str] = {"python": sys.version.split()[0]}
    for library in REQUIRED_LIBRARIES:
        try:
            versions[library] = metadata.version(library)
        except metadata.PackageNotFoundError as exc:
            raise ProvenanceError(
                "Required scientific library not installed", library=library
            ) from exc
    return versions


def capture_version_stamp(*, schema_version: str, repo_root: Path | None = None) -> VersionStamp:
    """Capture the full identity stamp for the current run.

    ``schema_version`` is supplied by the canonical SCADA schema module
    (M-06) once it exists; callers must not hard-code it elsewhere.
    """
    cwd = repo_root if repo_root is not None else Path.cwd()
    commit = _git(["rev-parse", "HEAD"], cwd)
    porcelain = [line for line in _git(["status", "--porcelain"], cwd).splitlines() if line.strip()]
    untracked = [line for line in porcelain if line.startswith("??")]
    return VersionStamp(
        app_version=APP_VERSION,
        schema_version=schema_version,
        python_version=sys.version.split()[0],
        git_commit=commit,
        git_dirty=bool(porcelain),
        git_tracked_dirty=len(porcelain) > len(untracked),
        git_untracked_files=len(untracked),
        library_versions=capture_library_versions(),
    )
