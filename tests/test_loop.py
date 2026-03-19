"""Tests for otorepair.loop — orchestrator helper functions."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from otorepair.circuit_breaker import CircuitBreaker
from otorepair.detector import ErrorDetector, TriageResult
from otorepair.fixer import FixResult
from otorepair.log import status
from otorepair.loop import (
    _extract_error_signature,
    _handle_crash,
    _handle_live_error,
    _read_stream,
    _wait_for_settle,
)


# ---------------------------------------------------------------------------
# _extract_error_signature
# ---------------------------------------------------------------------------


class TestExtractErrorSignature:
    def test_returns_last_meaningful_line(self):
        tb = (
            "Traceback (most recent call last):\n"
            '  File "app.py", line 10, in <module>\n'
            "ValueError: invalid literal for int()"
        )
        sig = _extract_error_signature(tb)
        assert sig == "ValueError: invalid literal for int()"

    def test_skips_file_lines(self):
        tb = (
            '  File "app.py", line 10\n'
            "    x = int('abc')\n"
            "        ^^^^^^^^\n"
            "ValueError: bad value"
        )
        sig = _extract_error_signature(tb)
        assert sig == "ValueError: bad value"

    def test_skips_caret_lines(self):
        tb = "    ^^^^^^^\nSyntaxError: invalid syntax"
        sig = _extract_error_signature(tb)
        assert sig == "SyntaxError: invalid syntax"

    def test_empty_string(self):
        assert _extract_error_signature("") == ""

    def test_whitespace_only(self):
        sig = _extract_error_signature("   \n  \n  ")
        # Falls through to the fallback (first 200 chars)
        assert sig == "   \n  \n  "[:200]

    def test_single_line(self):
        assert _extract_error_signature("KeyError: 'x'") == "KeyError: 'x'"

    def test_long_fallback_truncates(self):
        long_text = "x" * 300
        sig = _extract_error_signature(long_text)
        # Single line "xxx..." — it's not a File line and not "^", so it's returned directly
        assert sig == long_text

    def test_only_file_and_caret_lines_falls_back(self):
        tb = '  File "app.py", line 1\n    ^^^^^^'
        sig = _extract_error_signature(tb)
        # Both lines are skipped, falls back to first 200 chars
        assert sig == tb[:200]


# ---------------------------------------------------------------------------
# _print_status
# ---------------------------------------------------------------------------


class TestStatus:
    def test_prints_with_prefix(self, capsys):
        status("hello world")
        captured = capsys.readouterr()
        assert "[otorepair]" in captured.out
        assert "hello world" in captured.out


# ---------------------------------------------------------------------------
# _handle_crash
# ---------------------------------------------------------------------------


class TestHandleCrash:
    @pytest.mark.asyncio
    async def test_returns_false_when_tripped(self):
        detector = ErrorDetector()
        breaker = CircuitBreaker()
        # Trip the breaker
        for _ in range(CircuitBreaker.MAX_RETRIES):
            breaker.record_attempt(success=False, error_signature="e")

        result = await _handle_crash(detector, breaker, "cmd")
        assert result is False

    @pytest.mark.asyncio
    async def test_successful_fix_returns_true(self):
        detector = ErrorDetector()
        detector.feed_line("ValueError: x", is_stderr=True)
        breaker = CircuitBreaker()

        fix_result = FixResult(success=True, output="Fixed!", duration=2.0)
        with patch("otorepair.loop.attempt_fix", return_value=fix_result):
            result = await _handle_crash(detector, breaker, "python app.py")

        assert result is True
        assert breaker.attempts == 0  # success resets

    @pytest.mark.asyncio
    async def test_failed_fix_not_tripped_returns_true(self):
        detector = ErrorDetector()
        detector.feed_line("ValueError: x", is_stderr=True)
        breaker = CircuitBreaker()

        fix_result = FixResult(success=False, output="Could not fix", duration=1.0)
        with patch("otorepair.loop.attempt_fix", return_value=fix_result):
            result = await _handle_crash(detector, breaker, "cmd")

        # First failure — not tripped yet
        assert result is True
        assert breaker.attempts == 1

    @pytest.mark.asyncio
    async def test_failed_fix_trips_breaker_returns_false(self):
        detector = ErrorDetector()
        detector.feed_line("ValueError: x", is_stderr=True)
        breaker = CircuitBreaker()
        # Pre-load with failures close to the limit
        breaker.record_attempt(success=False, error_signature="ValueError: x")
        breaker.record_attempt(success=False, error_signature="ValueError: x")

        fix_result = FixResult(success=False, output="nope", duration=1.0)
        with patch("otorepair.loop.attempt_fix", return_value=fix_result):
            result = await _handle_crash(detector, breaker, "cmd")

        assert result is False
        assert breaker.is_tripped()


# ---------------------------------------------------------------------------
# _handle_live_error
# ---------------------------------------------------------------------------


class TestHandleLiveError:
    @pytest.mark.asyncio
    async def test_triage_says_no_returns_true(self):
        detector = ErrorDetector()
        detector.feed_line("some output", is_stderr=True)
        breaker = CircuitBreaker()

        triage_result = TriageResult(is_error=False)
        with patch.object(detector, "triage", return_value=triage_result):
            result = await _handle_live_error(detector, breaker, "cmd")

        assert result is True

    @pytest.mark.asyncio
    async def test_triage_confirms_error_and_fix_succeeds(self):
        detector = ErrorDetector()
        detector.feed_line("ValueError: x", is_stderr=True)
        breaker = CircuitBreaker()

        triage_result = TriageResult(
            is_error=True,
            error_summary="ValueError in app.py",
            traceback_text="ValueError: x",
        )
        fix_result = FixResult(success=True, output="Fixed", duration=1.0)

        with (
            patch.object(detector, "triage", return_value=triage_result),
            patch("otorepair.loop.attempt_fix", return_value=fix_result),
        ):
            result = await _handle_live_error(detector, breaker, "cmd")

        assert result is True

    @pytest.mark.asyncio
    async def test_triage_confirms_error_fix_fails_not_tripped(self):
        detector = ErrorDetector()
        detector.feed_line("error output", is_stderr=True)
        breaker = CircuitBreaker()

        triage_result = TriageResult(
            is_error=True,
            error_summary="NameError",
            traceback_text="NameError: x",
        )
        fix_result = FixResult(success=False, output="failed", duration=1.0)

        with (
            patch.object(detector, "triage", return_value=triage_result),
            patch("otorepair.loop.attempt_fix", return_value=fix_result),
        ):
            result = await _handle_live_error(detector, breaker, "cmd")

        assert result is True  # not tripped yet
        assert breaker.attempts == 1

    @pytest.mark.asyncio
    async def test_returns_false_when_breaker_already_tripped(self):
        detector = ErrorDetector()
        detector.feed_line("error", is_stderr=True)
        breaker = CircuitBreaker()
        for _ in range(CircuitBreaker.MAX_RETRIES):
            breaker.record_attempt(success=False, error_signature="e")

        triage_result = TriageResult(
            is_error=True,
            error_summary="err",
            traceback_text="tb",
        )

        with patch.object(detector, "triage", return_value=triage_result):
            result = await _handle_live_error(detector, breaker, "cmd")

        assert result is False

    @pytest.mark.asyncio
    async def test_detector_reset_after_triage(self):
        detector = ErrorDetector()
        detector.feed_line("ValueError: x", is_stderr=True)
        breaker = CircuitBreaker()

        triage_result = TriageResult(is_error=False)
        with patch.object(detector, "triage", return_value=triage_result):
            await _handle_live_error(detector, breaker, "cmd")

        # Detector should have been reset after triage
        assert not detector.heuristic_triggered
        assert detector.get_buffered_context() == ""


# ---------------------------------------------------------------------------
# _read_stream
# ---------------------------------------------------------------------------


class TestReadStream:
    @pytest.mark.asyncio
    async def test_reads_lines_into_detector(self):
        detector = ErrorDetector()
        stop_event = asyncio.Event()

        # Create a fake stream using StreamReader
        reader = asyncio.StreamReader()
        reader.feed_data(b"line one\nline two\n")
        reader.feed_eof()

        await _read_stream(reader, detector, is_stderr=False, stop_event=stop_event)

        ctx = detector.get_buffered_context()
        assert "line one" in ctx
        assert "line two" in ctx

    @pytest.mark.asyncio
    async def test_stderr_triggers_heuristic(self):
        detector = ErrorDetector()
        stop_event = asyncio.Event()

        reader = asyncio.StreamReader()
        reader.feed_data(b"ValueError: something\n")
        reader.feed_eof()

        await _read_stream(reader, detector, is_stderr=True, stop_event=stop_event)

        assert detector.heuristic_triggered

    @pytest.mark.asyncio
    async def test_stops_on_event(self):
        detector = ErrorDetector()
        stop_event = asyncio.Event()
        stop_event.set()

        reader = asyncio.StreamReader()
        # Don't feed EOF — the stop_event should cause exit

        # Should complete quickly due to stop_event
        await asyncio.wait_for(
            _read_stream(reader, detector, is_stderr=False, stop_event=stop_event),
            timeout=2.0,
        )


# ---------------------------------------------------------------------------
# _wait_for_settle
# ---------------------------------------------------------------------------


class TestWaitForSettle:
    @pytest.mark.asyncio
    async def test_returns_when_settled(self):
        detector = ErrorDetector()
        stop_event = asyncio.Event()

        # Trigger heuristic and set settle timer to the past
        detector.feed_line("ValueError: x", is_stderr=True)
        import time

        detector._settle_timer = time.monotonic() - 5.0

        await asyncio.wait_for(
            _wait_for_settle(detector, stop_event),
            timeout=2.0,
        )

    @pytest.mark.asyncio
    async def test_respects_stop_event(self):
        detector = ErrorDetector()
        stop_event = asyncio.Event()

        # Set stop after a short delay
        async def set_stop():
            await asyncio.sleep(0.2)
            stop_event.set()

        asyncio.create_task(set_stop())

        await asyncio.wait_for(
            _wait_for_settle(detector, stop_event),
            timeout=2.0,
        )
