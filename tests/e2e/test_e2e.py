"""End-to-end tests for the otorepair loop.

These tests exercise the real async machinery (ProcessRunner, ErrorDetector,
CircuitBreaker, FixHistory, attempt_fix) end-to-end.  The only thing replaced
is the ``claude`` binary — a shim delegates to ``fake_claude.py`` whose
behaviour is configured via environment variables.

Tests are intentionally run as subprocesses (``asyncio.create_subprocess_exec``
calling the ``otorepair`` entry-point) so that signal handling, PATH lookup,
and the full CLI path are covered.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _run_otorepair(
    command: str,
    *,
    env: dict[str, str],
    workspace: Path,
    timeout: float = 30.0,
    extra_args: list[str] | None = None,
) -> tuple[int, str, str]:
    """Run ``python -m otorepair <command>`` as a subprocess.

    Returns (exit_code, stdout, stderr).
    """
    argv = [
        sys.executable, "-m", "otorepair",
        *(extra_args or []),
        "--fix-timeout", "10",
        "--workspace", str(workspace),
        command,
    ]
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=str(workspace),
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        pytest.fail(f"otorepair timed out after {timeout}s")

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    return proc.returncode, stdout, stderr


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCleanExit:
    """Process exits 0 on first run → otorepair exits 0, no fix attempted."""

    @pytest.mark.asyncio
    async def test_clean_exit(self, e2e_env: dict, workspace: Path) -> None:
        app = workspace / "clean_app.py"
        rc, stdout, stderr = await _run_otorepair(
            f"{sys.executable} {app}",
            env=e2e_env,
            workspace=workspace,
        )
        assert rc == 0
        assert "all good" in stdout
        # Should see "exited cleanly" status message
        assert "exited cleanly" in stdout.lower() or "exited cleanly" in stderr.lower()


class TestCrashAndFix:
    """Process crashes → fake agent fixes it → restart succeeds."""

    @pytest.mark.asyncio
    async def test_crash_then_fix(self, e2e_env: dict, workspace: Path) -> None:
        app = workspace / "crash_missing_config.py"
        fix_script = workspace / "fix_create_config.py"

        # Tell fake claude how to fix
        e2e_env["FAKE_CLAUDE_FIX_SCRIPT"] = str(fix_script)
        e2e_env["FAKE_CLAUDE_FIX_EXIT"] = "0"

        rc, stdout, stderr = await _run_otorepair(
            f"{sys.executable} {app}",
            env=e2e_env,
            workspace=workspace,
        )

        # After fix, second run should succeed → exit 0
        assert rc == 0
        assert "started" in stdout
        # Verify the config file was created by the fake agent
        config = workspace / "config.txt"
        assert config.exists()
        assert config.read_text().strip() == "ok"


class TestCircuitBreaker:
    """Agent always fails → circuit breaker trips after 3 attempts → exit 1."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_trips(
        self, e2e_env: dict, workspace: Path,
    ) -> None:
        app = workspace / "always_crashes.py"

        # Agent always fails (exit 1, no fix script)
        e2e_env["FAKE_CLAUDE_FIX_EXIT"] = "1"

        rc, stdout, stderr = await _run_otorepair(
            f"{sys.executable} {app}",
            env=e2e_env,
            workspace=workspace,
            timeout=60.0,
        )

        assert rc == 1
        combined = stdout + stderr
        assert "circuit breaker" in combined.lower() or "giving up" in combined.lower()
