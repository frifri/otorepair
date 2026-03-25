"""Tests for otorepair.git_snapshot — git-aware rollback of failed fixes."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from otorepair.git_snapshot import (
    _STASH_MSG_PREFIX,
    create_snapshot,
    discard_snapshot,
    is_git_repo,
    rollback,
)


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
    )


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with one commit."""
    _git(["init"], tmp_path)
    _git(["config", "user.email", "test@test.com"], tmp_path)
    _git(["config", "user.name", "Test"], tmp_path)
    _git(["config", "commit.gpgsign", "false"], tmp_path)
    (tmp_path / "file.txt").write_text("original\n")
    _git(["add", "file.txt"], tmp_path)
    _git(["commit", "-m", "init"], tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# is_git_repo
# ---------------------------------------------------------------------------


class TestIsGitRepo:
    def test_true_for_git_repo(self, git_repo: Path):
        assert is_git_repo(git_repo) is True

    def test_false_for_plain_dir(self, tmp_path: Path):
        assert is_git_repo(tmp_path) is False

    def test_false_on_os_error(self, tmp_path: Path):
        with patch("otorepair.git_snapshot._run_git", side_effect=OSError("no git")):
            assert is_git_repo(tmp_path) is False


# ---------------------------------------------------------------------------
# create_snapshot
# ---------------------------------------------------------------------------


class TestCreateSnapshot:
    def test_returns_none_for_non_repo(self, tmp_path: Path):
        assert create_snapshot(tmp_path) is None

    def test_returns_clean_for_clean_tree(self, git_repo: Path):
        assert create_snapshot(git_repo) == "clean"

    def test_returns_stash_for_dirty_tree(self, git_repo: Path):
        (git_repo / "file.txt").write_text("modified\n")
        result = create_snapshot(git_repo)
        assert result == "stash"
        # The stash should exist
        r = _git(["stash", "list"], git_repo)
        assert _STASH_MSG_PREFIX in r.stdout

    def test_stashes_untracked_files(self, git_repo: Path):
        (git_repo / "new_file.py").write_text("print('hi')\n")
        result = create_snapshot(git_repo)
        assert result == "stash"
        # The untracked file should be gone (stashed)
        assert not (git_repo / "new_file.py").exists()

    def test_returns_none_on_git_failure(self, git_repo: Path):
        (git_repo / "file.txt").write_text("modified\n")
        with patch(
            "otorepair.git_snapshot._run_git",
            side_effect=[
                # is_git_repo call
                subprocess.CompletedProcess([], 0, stdout="true\n"),
                # _has_changes call
                subprocess.CompletedProcess([], 0, stdout="M file.txt\n"),
                # stash push fails
                subprocess.CompletedProcess([], 1, stderr="stash error"),
            ],
        ):
            assert create_snapshot(git_repo) is None


# ---------------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------------


class TestRollback:
    def test_noop_when_no_snapshot(self, git_repo: Path):
        assert rollback(git_repo, None) is True

    def test_clean_snapshot_discards_agent_changes(self, git_repo: Path):
        snapshot_id = create_snapshot(git_repo)
        assert snapshot_id == "clean"

        # Simulate agent modifying a file and creating a new one
        (git_repo / "file.txt").write_text("agent broke this\n")
        (git_repo / "agent_new.py").write_text("bad code\n")

        assert rollback(git_repo, snapshot_id) is True
        assert (git_repo / "file.txt").read_text() == "original\n"
        assert not (git_repo / "agent_new.py").exists()

    def test_stash_snapshot_restores_original_changes(self, git_repo: Path):
        # User had uncommitted work
        (git_repo / "file.txt").write_text("user work in progress\n")
        snapshot_id = create_snapshot(git_repo)
        assert snapshot_id == "stash"

        # After stash, tree is clean — file reverted to committed state
        assert (git_repo / "file.txt").read_text() == "original\n"

        # Simulate agent writing different changes
        (git_repo / "file.txt").write_text("agent broke this\n")

        assert rollback(git_repo, snapshot_id) is True
        # User's original work should be restored
        assert (git_repo / "file.txt").read_text() == "user work in progress\n"

    def test_rollback_handles_os_error(self, git_repo: Path):
        with patch(
            "otorepair.git_snapshot._run_git", side_effect=OSError("no git")
        ):
            assert rollback(git_repo, "clean") is False


# ---------------------------------------------------------------------------
# discard_snapshot
# ---------------------------------------------------------------------------


class TestDiscardSnapshot:
    def test_noop_when_no_snapshot(self, git_repo: Path):
        # Should not raise
        discard_snapshot(git_repo, None)

    def test_noop_for_clean_snapshot(self, git_repo: Path):
        discard_snapshot(git_repo, "clean")

    def test_drops_stash_on_success(self, git_repo: Path):
        (git_repo / "file.txt").write_text("modified\n")
        snapshot_id = create_snapshot(git_repo)
        assert snapshot_id == "stash"

        # Stash should exist
        r = _git(["stash", "list"], git_repo)
        assert _STASH_MSG_PREFIX in r.stdout

        discard_snapshot(git_repo, snapshot_id)

        # Stash should be gone
        r = _git(["stash", "list"], git_repo)
        assert _STASH_MSG_PREFIX not in r.stdout


# ---------------------------------------------------------------------------
# Integration: full snapshot → fix fails → rollback cycle
# ---------------------------------------------------------------------------


class TestSnapshotRollbackCycle:
    def test_full_cycle_clean_tree(self, git_repo: Path):
        """Clean tree → snapshot → agent changes → rollback → back to clean."""
        snapshot_id = create_snapshot(git_repo)

        # Agent makes changes
        (git_repo / "file.txt").write_text("broken\n")
        (git_repo / "extra.py").write_text("junk\n")

        # Fix failed — roll back
        rollback(git_repo, snapshot_id)

        assert (git_repo / "file.txt").read_text() == "original\n"
        assert not (git_repo / "extra.py").exists()

    def test_full_cycle_dirty_tree(self, git_repo: Path):
        """Dirty tree → snapshot → agent changes → rollback → user changes restored."""
        (git_repo / "file.txt").write_text("wip\n")
        (git_repo / "user_new.py").write_text("user code\n")

        snapshot_id = create_snapshot(git_repo)
        assert snapshot_id == "stash"

        # Agent overwrites
        (git_repo / "file.txt").write_text("agent version\n")

        rollback(git_repo, snapshot_id)

        assert (git_repo / "file.txt").read_text() == "wip\n"
        assert (git_repo / "user_new.py").read_text() == "user code\n"

    def test_full_cycle_success_keeps_changes(self, git_repo: Path):
        """Clean tree → snapshot → agent fixes → discard snapshot → changes kept."""
        snapshot_id = create_snapshot(git_repo)

        (git_repo / "file.txt").write_text("fixed by agent\n")

        discard_snapshot(git_repo, snapshot_id)

        assert (git_repo / "file.txt").read_text() == "fixed by agent\n"
