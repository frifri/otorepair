import asyncio
import time
from collections import deque
from dataclasses import dataclass

from otorepair.log import debug
from otorepair.patterns import (
    ERROR_LINE,
    FATAL_KEYWORDS,
    FILE_LINE_PATTERN,
    IGNORE_PATTERNS,
    MAX_BUFFER_LINES,
    SETTLE_TIMEOUT,
    STDERR_ERROR_KEYWORDS,
    TRACEBACK_START,
)


@dataclass
class TriageResult:
    is_error: bool
    error_summary: str = ""
    traceback_text: str = ""


class ErrorDetector:
    def __init__(self) -> None:
        self._buffer: deque[str] = deque(maxlen=MAX_BUFFER_LINES)
        self._settle_timer: float | None = None
        self._heuristic_triggered = False

    @property
    def heuristic_triggered(self) -> bool:
        return self._heuristic_triggered

    def feed_line(self, line: str, is_stderr: bool) -> None:
        self._buffer.append(line)

        if not is_stderr:
            return

        if self._should_ignore(line):
            return

        if self._check_heuristic(line):
            self._heuristic_triggered = True
            self._settle_timer = time.monotonic()

        elif self._heuristic_triggered:
            # Non-matching stderr line during a burst — reset settle timer
            self._settle_timer = time.monotonic()

    def _should_ignore(self, line: str) -> bool:
        return any(p.search(line) for p in IGNORE_PATTERNS)

    def _check_heuristic(self, line: str) -> bool:
        if TRACEBACK_START.search(line):
            return True
        if FILE_LINE_PATTERN.search(line):
            return True
        if ERROR_LINE.search(line):
            return True
        if FATAL_KEYWORDS.search(line):
            return True
        return any(kw in line for kw in STDERR_ERROR_KEYWORDS)

    def is_settled(self) -> bool:
        if not self._heuristic_triggered or self._settle_timer is None:
            return False
        return (time.monotonic() - self._settle_timer) >= SETTLE_TIMEOUT

    def get_buffered_context(self) -> str:
        return "\n".join(self._buffer)

    async def triage(self, context: str) -> TriageResult:
        prompt = (
            "You are analyzing output from a running Python process. "
            "Determine if the following output contains an actual error that needs "
            "fixing in the source code, or if it's just a warning/informational message.\n\n"
            f"Output:\n---\n{context}\n---\n\n"
            "If this is an error that needs fixing in source code, respond with EXACTLY this format:\n"
            "ERROR\n"
            "<one-line summary of the error>\n"
            "<the relevant traceback or error text>\n\n"
            "If this is NOT an error (just a warning, info message, or normal output), "
            "respond with EXACTLY:\nNO"
        )

        debug("Spawning triage: claude -p --model haiku")
        debug(f"Triage prompt ({len(prompt)} bytes):\n{prompt}", level=3)

        try:
            proc = await asyncio.create_subprocess_exec(
                "claude",
                "-p",
                "--model",
                "haiku",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            debug(f"Triage process started (PID {proc.pid})")
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode()),
                timeout=30.0,
            )
            response = stdout.decode().strip()
            debug(f"Triage response ({len(response)} chars): {response!r}", level=2)
            if stderr:
                debug(f"Triage stderr: {stderr.decode().strip()}", level=2)
        except asyncio.TimeoutError:
            debug("Triage timed out after 30s")
            return TriageResult(is_error=False)
        except OSError as e:
            debug(f"Triage failed to spawn: {e}")
            return TriageResult(is_error=False)

        return self._parse_triage_response(response)

    def _parse_triage_response(self, response: str) -> TriageResult:
        lines = response.strip().splitlines()
        if not lines:
            return TriageResult(is_error=False)

        if lines[0].strip().upper() == "NO":
            return TriageResult(is_error=False)

        if lines[0].strip().upper() == "ERROR":
            summary = lines[1].strip() if len(lines) > 1 else "Unknown error"
            traceback_text = "\n".join(lines[2:]) if len(lines) > 2 else ""
            return TriageResult(
                is_error=True,
                error_summary=summary,
                traceback_text=traceback_text,
            )

        # Ambiguous response — treat as not an error
        return TriageResult(is_error=False)

    def reset(self) -> None:
        self._buffer.clear()
        self._settle_timer = None
        self._heuristic_triggered = False
