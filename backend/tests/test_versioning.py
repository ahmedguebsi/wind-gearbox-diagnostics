"""M-05 tests: identity capture for experiment metadata (PROJECT.md §15)."""

import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.errors import ProvenanceError
from app.core.versioning import (
    REQUIRED_LIBRARIES,
    VersionStamp,
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


class TestWorkingTreeCleanliness:
    """ADR-044: a citable run needs a recoverable code state, and the two kinds
    of 'dirty' are not equally disqualifying.

    Uncommitted changes to TRACKED files mean the recorded commit does not
    describe the code that ran — that voids reproducibility. Untracked files do
    not: on this repository they are the author's documents and the governing
    specification, which the README states live outside the repo by design.
    Conflating them made the gate unusable in exactly the situation it exists
    for.
    """

    @staticmethod
    def _repo(tmp_path, *, files: dict[str, str], commit: bool) -> Path:
        import subprocess

        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
        (tmp_path / "seed.txt").write_text("seed", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-qm", "seed"], cwd=tmp_path, check=True)
        for name, content in files.items():
            (tmp_path / name).write_text(content, encoding="utf-8")
        if commit:
            subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
            subprocess.run(["git", "commit", "-qm", "change"], cwd=tmp_path, check=True)
        return tmp_path

    def test_untracked_files_alone_do_not_mark_the_code_state_dirty(self, tmp_path):
        repo = self._repo(tmp_path, files={"author_notes.docx": "x"}, commit=False)
        stamp = capture_version_stamp(schema_version="1.3.0", repo_root=repo)
        assert stamp.git_untracked_files == 1
        assert stamp.git_tracked_dirty is False  # the gate must NOT block
        assert stamp.git_dirty is True  # but the fact is still recorded

    def test_modified_tracked_file_marks_the_code_state_dirty(self, tmp_path):
        repo = self._repo(tmp_path, files={}, commit=False)
        (repo / "seed.txt").write_text("modified", encoding="utf-8")
        stamp = capture_version_stamp(schema_version="1.3.0", repo_root=repo)
        assert stamp.git_tracked_dirty is True
        assert stamp.git_untracked_files == 0

    def test_clean_tree_is_clean_on_both_counts(self, tmp_path):
        repo = self._repo(tmp_path, files={"new_module.py": "x = 1\n"}, commit=True)
        stamp = capture_version_stamp(schema_version="1.3.0", repo_root=repo)
        assert stamp.git_tracked_dirty is False
        assert stamp.git_untracked_files == 0
        assert stamp.git_dirty is False

    def test_pre_adr_044_stamp_still_loads(self):
        """The ADR-039 lesson applied: new fields must not orphan old records."""
        legacy = {
            "app_version": "0.1.0",
            "schema_version": "1.3.0",
            "python_version": "3.12.13",
            "git_commit": "a" * 40,
            "git_dirty": True,
            "library_versions": {},
        }
        stamp = VersionStamp.model_validate(legacy)
        assert stamp.git_tracked_dirty is False
        assert stamp.git_untracked_files == 0
