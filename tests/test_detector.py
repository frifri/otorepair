"""Tests for otorepair.detector — error detection and triage parsing."""

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from otorepair.backends import CursorBackend
from otorepair.detector import ErrorDetector, TriageResult
from otorepair.patterns import MAX_BUFFER_LINES, SETTLE_TIMEOUT


# ---------------------------------------------------------------------------
# TriageResult dataclass
# ---------------------------------------------------------------------------


class TestTriageResult:
    def test_defaults(self):
        t = TriageResult(is_error=False)
        assert not t.is_error
        assert t.error_summary == ""
        assert t.traceback_text == ""

    def test_with_values(self):
        t = TriageResult(is_error=True, error_summary="bad", traceback_text="tb")
        assert t.is_error
        assert t.error_summary == "bad"
        assert t.traceback_text == "tb"


# ---------------------------------------------------------------------------
# ErrorDetector — initialization
# ---------------------------------------------------------------------------


class TestErrorDetectorInit:
    def test_starts_not_triggered(self):
        d = ErrorDetector()
        assert not d.heuristic_triggered

    def test_starts_not_settled(self):
        d = ErrorDetector()
        assert not d.is_settled()

    def test_buffer_starts_empty(self):
        d = ErrorDetector()
        assert d.get_buffered_context() == ""


# ---------------------------------------------------------------------------
# ErrorDetector — feed_line & buffer
# ---------------------------------------------------------------------------


class TestFeedLineBuffer:
    def test_stdout_added_to_buffer(self):
        d = ErrorDetector()
        d.feed_line("hello stdout", is_stderr=False)
        assert "hello stdout" in d.get_buffered_context()

    def test_stderr_added_to_buffer(self):
        d = ErrorDetector()
        d.feed_line("hello stderr", is_stderr=True)
        assert "hello stderr" in d.get_buffered_context()

    def test_buffer_respects_max_size(self):
        d = ErrorDetector()
        for i in range(MAX_BUFFER_LINES + 20):
            d.feed_line(f"line {i}", is_stderr=False)
        lines = d.get_buffered_context().splitlines()
        assert len(lines) == MAX_BUFFER_LINES
        # Oldest lines should be dropped
        assert "line 0" not in d.get_buffered_context()
        assert f"line {MAX_BUFFER_LINES + 19}" in d.get_buffered_context()

    def test_multiple_lines_joined_by_newline(self):
        d = ErrorDetector()
        d.feed_line("aaa", is_stderr=False)
        d.feed_line("bbb", is_stderr=False)
        assert d.get_buffered_context() == "aaa\nbbb"


# ---------------------------------------------------------------------------
# ErrorDetector — heuristic detection
# ---------------------------------------------------------------------------


class TestHeuristicDetection:
    def test_traceback_triggers(self):
        d = ErrorDetector()
        d.feed_line("Traceback (most recent call last):", is_stderr=True)
        assert d.heuristic_triggered

    def test_file_line_triggers(self):
        d = ErrorDetector()
        d.feed_line('  File "app.py", line 42', is_stderr=True)
        assert d.heuristic_triggered

    def test_error_line_triggers(self):
        d = ErrorDetector()
        d.feed_line("ValueError: bad value", is_stderr=True)
        assert d.heuristic_triggered

    def test_fatal_keyword_triggers(self):
        d = ErrorDetector()
        d.feed_line("CRITICAL: database down", is_stderr=True)
        assert d.heuristic_triggered

    def test_stderr_keyword_triggers(self):
        d = ErrorDetector()
        d.feed_line("ModuleNotFoundError: No module named 'foo'", is_stderr=True)
        assert d.heuristic_triggered

    def test_stdout_does_not_trigger(self):
        d = ErrorDetector()
        d.feed_line("ValueError: bad value", is_stderr=False)
        assert not d.heuristic_triggered

    def test_normal_stderr_does_not_trigger(self):
        d = ErrorDetector()
        d.feed_line("Starting server on port 8000", is_stderr=True)
        assert not d.heuristic_triggered


# ---------------------------------------------------------------------------
# ErrorDetector — ignore patterns
# ---------------------------------------------------------------------------


class TestIgnorePatterns:
    def test_deprecation_warning_ignored(self):
        d = ErrorDetector()
        d.feed_line("DeprecationWarning: old API", is_stderr=True)
        assert not d.heuristic_triggered

    def test_user_warning_ignored(self):
        d = ErrorDetector()
        d.feed_line("UserWarning: be careful", is_stderr=True)
        assert not d.heuristic_triggered

    def test_watching_for_changes_ignored(self):
        d = ErrorDetector()
        d.feed_line("Watching for file changes with StatReloader", is_stderr=True)
        assert not d.heuristic_triggered

    def test_system_checks_ignored(self):
        d = ErrorDetector()
        d.feed_line("Performing system checks...", is_stderr=True)
        assert not d.heuristic_triggered

    def test_ignore_takes_priority_over_keyword(self):
        # "DeprecationWarning" contains "Warning" but should be ignored
        d = ErrorDetector()
        d.feed_line(
            "DeprecationWarning: something Error: in the message", is_stderr=True
        )
        assert not d.heuristic_triggered


# ---------------------------------------------------------------------------
# ErrorDetector — settle logic
# ---------------------------------------------------------------------------


class TestSettleLogic:
    def test_not_settled_immediately(self):
        d = ErrorDetector()
        d.feed_line("ValueError: x", is_stderr=True)
        assert d.heuristic_triggered
        assert not d.is_settled()

    def test_not_settled_without_trigger(self):
        d = ErrorDetector()
        assert not d.is_settled()

    def test_settled_after_timeout(self):
        d = ErrorDetector()
        d.feed_line("ValueError: x", is_stderr=True)
        # Simulate passage of time by directly setting the timer
        d._settle_timer = time.monotonic() - SETTLE_TIMEOUT - 0.1
        assert d.is_settled()

    def test_new_stderr_resets_settle_timer(self):
        d = ErrorDetector()
        d.feed_line("Traceback (most recent call last):", is_stderr=True)
        old_timer = d._settle_timer
        # Feed another line (non-matching stderr during burst)
        d.feed_line("  some context line", is_stderr=True)
        assert d._settle_timer >= old_timer


# ---------------------------------------------------------------------------
# ErrorDetector — _parse_triage_response
# ---------------------------------------------------------------------------


class TestParseTriageResponse:
    def test_no_response(self):
        d = ErrorDetector()
        result = d._parse_triage_response("")
        assert not result.is_error

    def test_no_answer(self):
        d = ErrorDetector()
        result = d._parse_triage_response("NO")
        assert not result.is_error

    def test_no_answer_case_insensitive(self):
        d = ErrorDetector()
        result = d._parse_triage_response("no")
        assert not result.is_error

    def test_no_with_whitespace(self):
        d = ErrorDetector()
        result = d._parse_triage_response("  NO  ")
        assert not result.is_error

    def test_error_with_summary_and_traceback(self):
        d = ErrorDetector()
        response = "ERROR\nImportError in main.py\nTraceback line 1\nTraceback line 2"
        result = d._parse_triage_response(response)
        assert result.is_error
        assert result.error_summary == "ImportError in main.py"
        assert "Traceback line 1" in result.traceback_text
        assert "Traceback line 2" in result.traceback_text

    def test_error_with_summary_only(self):
        d = ErrorDetector()
        result = d._parse_triage_response("ERROR\nSomething broke")
        assert result.is_error
        assert result.error_summary == "Something broke"
        assert result.traceback_text == ""

    def test_error_without_summary(self):
        d = ErrorDetector()
        result = d._parse_triage_response("ERROR")
        assert result.is_error
        assert result.error_summary == "Unknown error"

    def test_error_case_insensitive(self):
        d = ErrorDetector()
        result = d._parse_triage_response("error\nSummary")
        assert result.is_error

    def test_ambiguous_response_treated_as_no(self):
        d = ErrorDetector()
        result = d._parse_triage_response("I think there might be an error")
        assert not result.is_error

    def test_multiline_ambiguous_treated_as_no(self):
        d = ErrorDetector()
        result = d._parse_triage_response("MAYBE\nSomething happened")
        assert not result.is_error


# ---------------------------------------------------------------------------
# ErrorDetector — triage (mocked subprocess)
# ---------------------------------------------------------------------------


class TestTriage:
    @pytest.mark.asyncio
    async def test_triage_returns_parsed_result(self):
        d = ErrorDetector()
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"ERROR\nBad import\nline1\nline2", b"")

        with patch(
            "otorepair.detector.asyncio.create_subprocess_exec", return_value=mock_proc
        ):
            result = await d.triage("some context")

        assert result.is_error
        assert result.error_summary == "Bad import"

    @pytest.mark.asyncio
    async def test_triage_returns_no(self):
        d = ErrorDetector()
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"NO", b"")

        with patch(
            "otorepair.detector.asyncio.create_subprocess_exec", return_value=mock_proc
        ):
            result = await d.triage("some context")

        assert not result.is_error

    @pytest.mark.asyncio
    async def test_triage_timeout_returns_not_error(self):
        d = ErrorDetector()

        async def _raise_timeout(*args, **kwargs):
            raise asyncio.TimeoutError()

        with patch(
            "otorepair.detector.asyncio.create_subprocess_exec",
            side_effect=_raise_timeout,
        ):
            result = await d.triage("context")

        assert not result.is_error

    @pytest.mark.asyncio
    async def test_triage_oserror_returns_not_error(self):
        d = ErrorDetector()

        with patch(
            "otorepair.detector.asyncio.create_subprocess_exec",
            side_effect=OSError("claude not found"),
        ):
            result = await d.triage("context")

        assert not result.is_error

    @pytest.mark.asyncio
    async def test_triage_cursor_backend_argv(self, tmp_path):
        ws = tmp_path / "app"
        ws.mkdir()
        d = ErrorDetector(CursorBackend(workspace=ws))

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"NO", b"")

        with patch(
            "otorepair.detector.asyncio.create_subprocess_exec", return_value=mock_proc
        ) as mock_exec:
            await d.triage("ctx")

        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert args[0] == "agent"
        assert "-p" in args
        assert "--trust" in args
        assert "--workspace" in args
        ws_idx = args.index("--workspace")
        assert args[ws_idx + 1] == str(ws.resolve())

    @pytest.mark.asyncio
    async def test_triage_passes_subprocess_cwd(self, tmp_path):
        cwd = tmp_path / "root"
        cwd.mkdir()
        d = ErrorDetector(subprocess_cwd=cwd)
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"NO", b"")

        with patch(
            "otorepair.detector.asyncio.create_subprocess_exec", return_value=mock_proc
        ) as mock_exec:
            await d.triage("ctx")

        assert mock_exec.call_args.kwargs.get("cwd") == str(cwd.resolve())


# ---------------------------------------------------------------------------
# ErrorDetector — reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_state(self):
        d = ErrorDetector()
        d.feed_line("ValueError: x", is_stderr=True)
        d.feed_line("some context", is_stderr=False)
        assert d.heuristic_triggered
        assert d.get_buffered_context() != ""

        d.reset()
        assert not d.heuristic_triggered
        assert not d.is_settled()
        assert d.get_buffered_context() == ""
