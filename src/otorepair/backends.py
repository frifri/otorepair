"""Pluggable agent CLI backends (Claude Code vs Cursor Agent)."""

from __future__ import annotations

import os
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal

BackendId = Literal["claude", "cursor"]


def resolve_backend_id(cli_backend: str | None) -> tuple[BackendId | None, str | None]:
    """
    Decide which backend to use.

    Precedence: explicit CLI ``--backend`` > ``OTOREPAIR_BACKEND`` > ``claude``.

    Returns:
        (backend_id, error_message). error_message is set when the env var is
        non-empty but invalid.
    """
    if cli_backend is not None:
        return cli_backend, None

    raw = os.environ.get("OTOREPAIR_BACKEND", "").strip()
    if not raw:
        return "claude", None

    key = raw.lower()
    if key in ("claude", "cursor"):
        return key, None

    return None, (
        f"Invalid OTOREPAIR_BACKEND={raw!r}. "
        "Use 'claude' or 'cursor', or unset it."
    )


def resolve_workspace(cli_workspace: str | None) -> tuple[Path | None, str | None]:
    """
    Resolve the project root used for the monitored process cwd and (for
    Cursor) ``agent --workspace``.

    Precedence: ``--workspace`` > ``$OTOREPAIR_WORKSPACE`` > current working
    directory.

    Returns:
        ``(path, None)`` on success, or ``(None, error_message)``.
    """
    if cli_workspace is not None:
        raw = cli_workspace
    else:
        env = os.environ.get("OTOREPAIR_WORKSPACE", "").strip()
        raw = env if env else None

    if raw is None:
        return Path.cwd().resolve(), None

    path = Path(raw).expanduser()
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError) as e:
        return None, f"Invalid workspace path {raw!r}: {e}"

    if not resolved.exists():
        return None, f"Workspace path does not exist: {resolved}"
    if not resolved.is_dir():
        return None, f"Workspace path is not a directory: {resolved}"
    return resolved, None


def check_cursor_cli_authenticated(
    workspace: Path,
    *,
    agent_bin: str = "agent",
    timeout: float = 15.0,
) -> tuple[bool, str]:
    """
    Best-effort check that Cursor Agent can run headless fixes.

    Returns:
        ``(True, "")`` if ``CURSOR_API_KEY`` is set or ``agent status`` succeeds.
        ``(False, message)`` with a user-facing error string otherwise.
    """
    if os.environ.get("CURSOR_API_KEY", "").strip():
        return True, ""

    try:
        completed = subprocess.run(
            [agent_bin, "status"],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.fspath(workspace),
            env=os.environ,
        )
    except subprocess.TimeoutExpired:
        return (
            False,
            "Timed out checking `agent status`. Is the Cursor CLI responsive?\n"
            "Set CURSOR_API_KEY or run `agent login`.",
        )
    except OSError as e:
        return (
            False,
            f"Could not run `{agent_bin} status`: {e}\n"
            "Set CURSOR_API_KEY or run `agent login`.",
        )

    if completed.returncode == 0:
        return True, ""

    hint = (completed.stderr or completed.stdout or "").strip()
    tail = f"\n{hint[:800]}" if hint else ""
    return (
        False,
        "Cursor agent does not appear to be authenticated.\n"
        f"`{agent_bin} status` exited with code {completed.returncode}.{tail}\n"
        "Set CURSOR_API_KEY or run `agent login` "
        "(https://cursor.com/docs/cli/reference/authentication).",
    )


class AgentBackend(ABC):
    """How to spawn the agent CLI for triage and fix attempts."""

    @property
    @abstractmethod
    def executable(self) -> str:
        """Binary name for ``shutil.which``."""

    @abstractmethod
    def triage_argv(self) -> list[str]:
        """Arguments for triage (prompt still sent on stdin)."""

    @abstractmethod
    def fix_argv(self) -> list[str]:
        """Arguments for fix (prompt still sent on stdin)."""

    @abstractmethod
    def spawn_error_hint(self) -> str:
        """One-line install hint when the executable is missing."""

    def fix_uses_stream_json_stdout(self) -> bool:
        """Whether ``attempt_fix`` stdout is NDJSON (Cursor ``stream-json``)."""
        return False

    @abstractmethod
    def session_summary_lines(
        self,
        *,
        workdir: Path,
        agent_executable_path: str | None = None,
    ) -> list[str]:
        """Human-readable lines for the startup session banner (``status``)."""


class ClaudeBackend(AgentBackend):
    @property
    def executable(self) -> str:
        return "claude"

    def triage_argv(self) -> list[str]:
        return ["claude", "-p", "--model", "haiku"]

    def fix_argv(self) -> list[str]:
        return [
            "claude",
            "-p",
            "--allowedTools",
            "Edit,Read,Write,Bash,Glob,Grep",
        ]

    def spawn_error_hint(self) -> str:
        return "https://docs.anthropic.com/en/docs/claude-code"

    def session_summary_lines(
        self,
        *,
        workdir: Path,
        agent_executable_path: str | None = None,
    ) -> list[str]:
        _ = workdir  # Claude loop still uses cwd as only Cursor uses workspaces.
        exe = agent_executable_path or self.executable
        return [
            f"Agent backend: Claude Code ({exe})",
            "Triage model: haiku",
            "Fix model: Claude Code CLI default (otorepair does not pass --model)",
        ]


class CursorBackend(AgentBackend):
    def __init__(self, workspace: Path | None = None) -> None:
        self._workspace = (workspace or Path.cwd()).resolve()

    @property
    def executable(self) -> str:
        return "agent"

    def triage_argv(self) -> list[str]:
        cmd = [
            "agent",
            "-p",
            "--trust",
            "--workspace",
            str(self._workspace),
        ]
        model = os.environ.get("OTOREPAIR_CURSOR_TRIAGE_MODEL", "").strip()
        if model:
            cmd.extend(["--model", model])
        return cmd

    def fix_argv(self) -> list[str]:
        return [
            "agent",
            "-p",
            "--force",
            "--trust",
            "--workspace",
            str(self._workspace),
            "--output-format",
            "stream-json",
            "--stream-partial-output",
        ]

    def fix_uses_stream_json_stdout(self) -> bool:
        return True

    def spawn_error_hint(self) -> str:
        return "https://cursor.com/docs/cli/installation"

    def session_summary_lines(
        self,
        *,
        workdir: Path,
        agent_executable_path: str | None = None,
    ) -> list[str]:
        exe = agent_executable_path or self.executable
        triage_model = os.environ.get("OTOREPAIR_CURSOR_TRIAGE_MODEL", "").strip()
        triage_label = triage_model if triage_model else "Cursor CLI default"
        return [
            f"Agent backend: Cursor ({exe})",
            f"Workspace (cwd + agent --workspace): {workdir}",
            f"Triage model: {triage_label}",
            "Fix model: Cursor CLI default (otorepair does not pass --model)",
        ]


def get_backend(backend_id: BackendId, *, workspace: Path | None = None) -> AgentBackend:
    if backend_id == "claude":
        return ClaudeBackend()
    return CursorBackend(workspace=workspace)
