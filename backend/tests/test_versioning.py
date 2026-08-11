"""M-05 tests: identity capture for experiment metadata (PROJECT.md §15)."""

import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.errors import ProvenanceError
from app.core.versioning import (
    REQUIRED_LIBRARIES,
    capture_library_versions,
    capture_version_stamp,
)


def _git(args: list[str], cwd: Path) -> None:
    git_exe = shutil.which("git")
    assert git_exe is not None, "git required for versioning tests"
    subprocess.run(
        [
            git_exe,
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@test.invalid",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "fixture-repo"
    repo.mkdir()
    _git(["init", "-b", "main"], repo)
    (repo / "tracked.txt").write_text("initial\n", encoding="utf-8")
    _git(["add", "."], repo)
    _git(["commit", "-m", "initial"], repo)
    return repo


class TestLibraryVersions:
    def test_all_required_library_keys_present(self):
        versions = capture_library_versions()
        assert set(versions) == {"python", *REQUIRED_LIBRARIES}
        assert all(versions.values())

    def test_spec_named_libraries_are_covered(self):
        """PROJECT.md §15 names these seven runtime versions explicitly."""
        assert set(REQUIRED_LIBRARIES) == {
            "numpy",
            "pandas",
            "scikit-learn",
            "xgboost",
            "scipy",
            "statsmodels",
        }


class TestVersionStamp:
    def test_clean_repo_stamp_complete_and_not_dirty(self, fixture_repo: Path):
        stamp = capture_version_stamp(schema_version="1.0.0", repo_root=fixture_repo)
        assert stamp.schema_version == "1.0.0"
        assert stamp.app_version
        assert stamp.python_version.startswith("3.12")
        assert len(stamp.git_commit) == 40
        assert stamp.git_dirty is False
        assert set(stamp.library_versions) == {"python", *REQUIRED_LIBRARIES}

    def test_dirty_flag_detected_on_modified_repo(self, fixture_repo: Path):
        (fixture_repo / "tracked.txt").write_text("modified\n", encoding="utf-8")
        stamp = capture_version_stamp(schema_version="1.0.0", repo_root=fixture_repo)
        assert stamp.git_dirty is True

    def test_non_repo_directory_raises_provenance_error(self, tmp_path: Path):
        bare = tmp_path / "not-a-repo"
        bare.mkdir()
        with pytest.raises(ProvenanceError):
            capture_version_stamp(schema_version="1.0.0", repo_root=bare)

    def test_stamp_is_frozen(self, fixture_repo: Path):
        stamp = capture_version_stamp(schema_version="1.0.0", repo_root=fixture_repo)
        with pytest.raises(Exception, match="frozen"):
            stamp.git_dirty = True  # type: ignore[misc]
