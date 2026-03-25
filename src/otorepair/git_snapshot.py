"""Git-aware snapshot and rollback for fix attempts.

Before the agent modifies code, we snapshot the working tree via ``git stash``.
If the fix fails, the snapshot is restored so broken changes don't accumulate.
On success the stash is dropped.

The module is intentionally lenient: if the workspace is not a git repo, or git
is unavailable, all operations silently no-op so the rest of otorepair still
works.
"""

import subprocess
from pathlib import Path

from otorepair.log import debug, status

# Unique message prefix so we can identify our stashes unambiguously.
_STASH_MSG_PREFIX = "otorepair-pre-fix-snapshot"


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )


def is_git_repo(cwd: Path) -> bool:
    """Return True if *cwd* is inside a git working tree."""
    try:
        r = _run_git(["rev-parse", "--is-inside-work-tree"], cwd)
        return r.returncode == 0 and r.stdout.strip() == "true"
    except (OSError, subprocess.TimeoutExpired):
        return False


def _has_changes(cwd: Path) -> bool:
    """Return True if there are staged or unstaged changes (including untracked)."""
    try:
        # Check tracked changes
        r = _run_git(["status", "--porcelain"], cwd)
        return r.returncode == 0 and bool(r.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return False


def create_snapshot(cwd: Path) -> str | None:
    """Stash the current working tree state before a fix attempt.

    Returns a stash identifier string on success, or ``None`` if no snapshot
    was created (clean tree, not a git repo, etc.).
    """
    if not is_git_repo(cwd):
        debug("Snapshot skipped: not a git repo")
        return None

    if not _has_changes(cwd):
        debug("Snapshot skipped: clean working tree")
        # Even with a clean tree we return a sentinel so rollback knows the
        # tree was clean and can restore to that state.
        return "clean"

    try:
        r = _run_git(
            ["stash", "push", "--include-untracked", "-m", _STASH_MSG_PREFIX],
            cwd,
        )
        if r.returncode != 0:
            debug(f"git stash failed: {r.stderr.strip()}")
            return None
        debug(f"Snapshot created: {r.stdout.strip()}")
        return "stash"
    except (OSError, subprocess.TimeoutExpired) as e:
        debug(f"Snapshot failed: {e}")
        return None


def rollback(cwd: Path, snapshot_id: str | None) -> bool:
    """Restore the working tree to the pre-fix state.

    Returns True if the rollback succeeded (or was unnecessary).
    """
    if snapshot_id is None:
        # No snapshot was taken — nothing to roll back.
        return True

    if snapshot_id == "clean":
        # Tree was clean before the fix.  Discard everything the agent wrote.
        try:
            # Reset tracked changes
            _run_git(["checkout", "."], cwd)
            # Remove untracked files the agent may have created
            _run_git(["clean", "-fd"], cwd)
            status("Rolled back failed fix (working tree was clean).")
            debug("Rollback: checkout + clean completed")
            return True
        except (OSError, subprocess.TimeoutExpired) as e:
            debug(f"Rollback (clean) failed: {e}")
            return False

    # snapshot_id == "stash"
    try:
        # First discard whatever the agent wrote
        _run_git(["checkout", "."], cwd)
        _run_git(["clean", "-fd"], cwd)
        # Now pop our stash to restore the original state
        r = _run_git(["stash", "pop"], cwd)
        if r.returncode != 0:
            debug(f"git stash pop failed: {r.stderr.strip()}")
            return False
        status("Rolled back failed fix (pre-fix changes restored).")
        debug(f"Rollback: stash pop completed: {r.stdout.strip()}")
        return True
    except (OSError, subprocess.TimeoutExpired) as e:
        debug(f"Rollback (stash) failed: {e}")
        return False


def discard_snapshot(cwd: Path, snapshot_id: str | None) -> None:
    """Drop the snapshot after a successful fix — the agent's changes are kept."""
    if snapshot_id is None or snapshot_id == "clean":
        return
    try:
        r = _run_git(["stash", "drop"], cwd)
        debug(f"Snapshot dropped: {r.stdout.strip()}")
    except (OSError, subprocess.TimeoutExpired) as e:
        debug(f"Failed to drop snapshot (non-fatal): {e}")
