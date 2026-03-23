"""Tests for otorepair.runner — subprocess lifecycle management."""

import asyncio
import os
import signal
import sys

import pytest

from otorepair.runner import ProcessRunner


# ---------------------------------------------------------------------------
# ProcessRunner — initialization
# ---------------------------------------------------------------------------


class TestProcessRunnerInit:
    def test_not_alive_before_start(self):
        r = ProcessRunner("echo hi")
        assert not r.is_alive

    def test_pid_none_before_start(self):
        r = ProcessRunner("echo hi")
        assert r.pid is None

    def test_returncode_none_before_start(self):
        r = ProcessRunner("echo hi")
        assert r.returncode is None


# ---------------------------------------------------------------------------
# ProcessRunner — start & basic lifecycle
# ---------------------------------------------------------------------------


class TestProcessRunnerStart:
    @pytest.mark.asyncio
    async def test_start_returns_process(self):
        r = ProcessRunner("echo hello")
        proc = await r.start()
        assert proc is not None
        await proc.wait()

    @pytest.mark.asyncio
    async def test_pid_set_after_start(self):
        r = ProcessRunner("sleep 10")
        await r.start()
        assert r.pid is not None
        assert r.pid > 0
        await r.stop()

    @pytest.mark.asyncio
    async def test_is_alive_while_running(self):
        r = ProcessRunner("sleep 10")
        await r.start()
        assert r.is_alive
        await r.stop()

    @pytest.mark.asyncio
    async def test_not_alive_after_exit(self):
        r = ProcessRunner("echo done")
        await r.start()
        # Wait for the short command to finish
        await asyncio.sleep(0.5)
        assert not r.is_alive

    @pytest.mark.asyncio
    async def test_returncode_after_exit(self):
        r = ProcessRunner("true")
        await r.start()
        await asyncio.sleep(0.5)
        assert r.returncode == 0

    @pytest.mark.asyncio
    async def test_nonzero_returncode(self):
        r = ProcessRunner("false")
        await r.start()
        await asyncio.sleep(0.5)
        assert r.returncode != 0

    @pytest.mark.asyncio
    async def test_env_has_pythonunbuffered(self):
        r = ProcessRunner("echo hi")
        # Access private _env to verify
        assert r._env.get("PYTHONUNBUFFERED") == "1"

    @pytest.mark.asyncio
    async def test_start_respects_cwd(self, tmp_path):
        code = "import os; print(os.getcwd(), end='')"
        cmd = f"{sys.executable} -c {repr(code)}"
        r = ProcessRunner(cmd, cwd=tmp_path)
        proc = await r.start()
        out = await proc.stdout.read()
        await proc.wait()
        assert out.decode() == str(tmp_path.resolve())


# ---------------------------------------------------------------------------
# ProcessRunner — stop
# ---------------------------------------------------------------------------


class TestProcessRunnerStop:
    @pytest.mark.asyncio
    async def test_stop_terminates_process(self):
        r = ProcessRunner("sleep 60")
        await r.start()
        assert r.is_alive
        await r.stop()
        assert not r.is_alive

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self):
        r = ProcessRunner("echo done")
        await r.start()
        await asyncio.sleep(0.5)
        # Process already exited — stop should be a no-op
        await r.stop()
        await r.stop()  # Should not raise

    @pytest.mark.asyncio
    async def test_stop_before_start(self):
        r = ProcessRunner("echo hi")
        # Should not raise
        await r.stop()


# ---------------------------------------------------------------------------
# ProcessRunner — restart
# ---------------------------------------------------------------------------


class TestProcessRunnerRestart:
    @pytest.mark.asyncio
    async def test_restart_yields_new_process(self):
        r = ProcessRunner("sleep 10")
        await r.start()
        old_pid = r.pid
        await r.restart()
        assert r.pid != old_pid
        assert r.is_alive
        await r.stop()


# ---------------------------------------------------------------------------
# ProcessRunner — force_kill
# ---------------------------------------------------------------------------


class TestProcessRunnerForceKill:
    @pytest.mark.asyncio
    async def test_force_kill_terminates(self):
        r = ProcessRunner("sleep 60")
        await r.start()
        assert r.is_alive
        r.force_kill()
        # Give OS time to reap the process
        await asyncio.sleep(0.5)
        assert not r.is_alive

    def test_force_kill_before_start(self):
        r = ProcessRunner("echo hi")
        # Should not raise
        r.force_kill()

    @pytest.mark.asyncio
    async def test_force_kill_after_exit(self):
        r = ProcessRunner("true")
        await r.start()
        await asyncio.sleep(0.5)
        # Already exited — should not raise
        r.force_kill()


# ---------------------------------------------------------------------------
# ProcessRunner — stdout/stderr capture
# ---------------------------------------------------------------------------


class TestProcessRunnerOutput:
    @pytest.mark.asyncio
    async def test_stdout_readable(self):
        r = ProcessRunner("echo hello_world")
        proc = await r.start()
        line = await proc.stdout.readline()
        assert b"hello_world" in line
        await proc.wait()

    @pytest.mark.asyncio
    async def test_stderr_readable(self):
        r = ProcessRunner("echo error_output >&2")
        proc = await r.start()
        line = await proc.stderr.readline()
        assert b"error_output" in line
        await proc.wait()
