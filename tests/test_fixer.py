"""Tests for otorepair.fixer — Claude Code invocation for fixes."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from otorepair.fixer import FixResult, _print_fix_output, attempt_fix


# ---------------------------------------------------------------------------
# Helpers — build mock processes with real StreamReaders
# ---------------------------------------------------------------------------


def _make_mock_proc(
    stdout_data: bytes = b"",
    stderr_data: bytes = b"",
    returncode: int = 0,
) -> MagicMock:
    """Create a mock process with real StreamReaders for stdout/stderr."""
    stdout = asyncio.StreamReader()
    stdout.feed_data(stdout_data)
    stdout.feed_eof()

    stderr = asyncio.StreamReader()
    stderr.feed_data(stderr_data)
    stderr.feed_eof()

    proc = MagicMock()
    proc.stdout = stdout
    proc.stderr = stderr
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()
    proc.stdin.close = MagicMock()
    proc.wait = AsyncMock(return_value=returncode)
    proc.returncode = returncode
    proc.kill = MagicMock()
    return proc


# ---------------------------------------------------------------------------
# FixResult dataclass
# ---------------------------------------------------------------------------


class TestFixResult:
    def test_creation(self):
        r = FixResult(success=True, output="fixed", duration=1.5)
        assert r.success is True
        assert r.output == "fixed"
        assert r.duration == 1.5


# ---------------------------------------------------------------------------
# _print_fix_output
# ---------------------------------------------------------------------------


class TestPrintFixOutput:
    def test_prints_with_dim_styling(self, capsys):
        _print_fix_output("hello from claude")
        captured = capsys.readouterr()
        assert "hello from claude" in captured.out
        assert "\033[2m" in captured.out  # dim
        assert "|" in captured.out  # visual prefix


# ---------------------------------------------------------------------------
# attempt_fix — success
# ---------------------------------------------------------------------------


class TestAttemptFixSuccess:
    @pytest.mark.asyncio
    async def test_successful_fix(self):
        mock_proc = _make_mock_proc(stdout_data=b"I fixed the error\n", returncode=0)

        with patch(
            "otorepair.fixer.asyncio.create_subprocess_exec", return_value=mock_proc
        ):
            result = await attempt_fix(
                error_summary="ImportError",
                traceback_text="Traceback...",
                original_command="python app.py",
            )

        assert result.success
        assert "I fixed the error" in result.output
        assert result.duration > 0

    @pytest.mark.asyncio
    async def test_fix_passes_correct_args(self):
        mock_proc = _make_mock_proc(returncode=0)

        with patch(
            "otorepair.fixer.asyncio.create_subprocess_exec", return_value=mock_proc
        ) as mock_exec:
            await attempt_fix(
                error_summary="NameError",
                traceback_text="tb",
                original_command="python run.py",
            )

        mock_exec.assert_called_once_with(
            "claude",
            "-p",
            "--allowedTools",
            "Edit,Read,Write,Bash,Glob,Grep",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    @pytest.mark.asyncio
    async def test_prompt_sent_via_stdin(self):
        mock_proc = _make_mock_proc(returncode=0)

        with patch(
            "otorepair.fixer.asyncio.create_subprocess_exec", return_value=mock_proc
        ):
            await attempt_fix(
                error_summary="NameError: x is not defined",
                traceback_text="File app.py line 10",
                original_command="python app.py",
            )

        # Check the prompt was written to stdin
        written = mock_proc.stdin.write.call_args[0][0].decode()
        assert "NameError: x is not defined" in written
        assert "File app.py line 10" in written
        assert "python app.py" in written

        # Verify stdin was drained and closed
        mock_proc.stdin.drain.assert_awaited_once()
        mock_proc.stdin.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_multiline_output_captured(self):
        mock_proc = _make_mock_proc(
            stdout_data=b"line 1\nline 2\nline 3\n",
            returncode=0,
        )

        with patch(
            "otorepair.fixer.asyncio.create_subprocess_exec", return_value=mock_proc
        ):
            result = await attempt_fix(
                error_summary="err",
                traceback_text="tb",
                original_command="cmd",
            )

        assert result.success
        assert "line 1\nline 2\nline 3" == result.output

    @pytest.mark.asyncio
    async def test_output_printed_to_terminal(self, capsys):
        mock_proc = _make_mock_proc(stdout_data=b"fixing things\n", returncode=0)

        with patch(
            "otorepair.fixer.asyncio.create_subprocess_exec", return_value=mock_proc
        ):
            await attempt_fix(
                error_summary="err",
                traceback_text="tb",
                original_command="cmd",
            )

        captured = capsys.readouterr()
        assert "fixing things" in captured.out


# ---------------------------------------------------------------------------
# attempt_fix — failure
# ---------------------------------------------------------------------------


class TestAttemptFixFailure:
    @pytest.mark.asyncio
    async def test_nonzero_exit_code(self):
        mock_proc = _make_mock_proc(
            stdout_data=b"could not fix\n",
            returncode=1,
        )

        with patch(
            "otorepair.fixer.asyncio.create_subprocess_exec", return_value=mock_proc
        ):
            result = await attempt_fix(
                error_summary="err",
                traceback_text="tb",
                original_command="cmd",
            )

        assert not result.success
        assert "could not fix" in result.output

    @pytest.mark.asyncio
    async def test_stderr_included_on_failure(self):
        mock_proc = _make_mock_proc(
            stdout_data=b"",
            stderr_data=b"authentication error\n",
            returncode=1,
        )

        with patch(
            "otorepair.fixer.asyncio.create_subprocess_exec", return_value=mock_proc
        ):
            result = await attempt_fix(
                error_summary="err",
                traceback_text="tb",
                original_command="cmd",
            )

        assert not result.success
        assert "stderr:" in result.output
        assert "authentication error" in result.output

    @pytest.mark.asyncio
    async def test_stderr_not_included_on_success(self):
        mock_proc = _make_mock_proc(
            stdout_data=b"fixed\n",
            stderr_data=b"some warning\n",
            returncode=0,
        )

        with patch(
            "otorepair.fixer.asyncio.create_subprocess_exec", return_value=mock_proc
        ):
            result = await attempt_fix(
                error_summary="err",
                traceback_text="tb",
                original_command="cmd",
            )

        assert result.success
        assert "stderr:" not in result.output


# ---------------------------------------------------------------------------
# attempt_fix — timeout
# ---------------------------------------------------------------------------


class TestAttemptFixTimeout:
    @pytest.mark.asyncio
    async def test_timeout_kills_process(self):
        # StreamReaders that never get EOF — simulates a hanging process
        stdout = asyncio.StreamReader()
        stderr = asyncio.StreamReader()

        mock_proc = MagicMock()
        mock_proc.stdout = stdout
        mock_proc.stderr = stderr
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()
        mock_proc.stdin.close = MagicMock()
        mock_proc.wait = AsyncMock(side_effect=lambda: asyncio.sleep(999))
        mock_proc.kill = MagicMock()
        mock_proc.returncode = -9

        with patch(
            "otorepair.fixer.asyncio.create_subprocess_exec", return_value=mock_proc
        ):
            result = await attempt_fix(
                error_summary="err",
                traceback_text="tb",
                original_command="cmd",
                timeout=0.05,  # Very short timeout for test speed
            )

        assert not result.success
        assert "timed out" in result.output.lower()
        mock_proc.kill.assert_called_once()


# ---------------------------------------------------------------------------
# attempt_fix — OSError
# ---------------------------------------------------------------------------


class TestAttemptFixOSError:
    @pytest.mark.asyncio
    async def test_claude_not_found(self):
        with patch(
            "otorepair.fixer.asyncio.create_subprocess_exec",
            side_effect=OSError("No such file or directory: 'claude'"),
        ):
            result = await attempt_fix(
                error_summary="err",
                traceback_text="tb",
                original_command="cmd",
            )

        assert not result.success
        assert "claude" in result.output.lower()
        assert result.duration > 0
