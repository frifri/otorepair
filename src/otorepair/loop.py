import asyncio
import signal
from pathlib import Path

from otorepair.backends import AgentBackend, ClaudeBackend
from otorepair.circuit_breaker import CircuitBreaker
from otorepair.detector import ErrorDetector
from otorepair.fixer import attempt_fix
from otorepair.history import FixHistory
from otorepair.log import debug, status
from otorepair.patterns import DEATH_CONTEXT_LINES
from otorepair.runner import ProcessRunner


def _extract_error_signature(traceback_text: str) -> str:
    lines = traceback_text.strip().splitlines()
    for line in reversed(lines):
        stripped = line.strip()
        if (
            stripped
            and not stripped.startswith("File ")
            and not stripped.startswith("^")
        ):
            return stripped
    return traceback_text[:200] if traceback_text else ""


async def _read_stream(
    stream: asyncio.StreamReader,
    detector: ErrorDetector,
    is_stderr: bool,
    stop_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        try:
            raw = await asyncio.wait_for(stream.readline(), timeout=0.5)
        except asyncio.TimeoutError:
            continue

        if not raw:
            break

        line = raw.decode("utf-8", errors="replace").rstrip("\n")

        if is_stderr:
            print(f"\033[91m{line}\033[0m", flush=True)
        else:
            print(line, flush=True)

        detector.feed_line(line, is_stderr=is_stderr)


async def _wait_for_settle(
    detector: ErrorDetector,
    stop_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        await asyncio.sleep(0.5)
        if detector.heuristic_triggered and detector.is_settled():
            return


async def _handle_crash(
    detector: ErrorDetector,
    breaker: CircuitBreaker,
    command: str,
    backend: AgentBackend,
    subprocess_cwd: Path,
    fix_timeout: float = 120.0,
    history: FixHistory | None = None,
) -> bool:
    context = detector.get_buffered_context()
    lines = context.splitlines()
    recent = "\n".join(lines[-DEATH_CONTEXT_LINES:])

    error_sig = _extract_error_signature(recent)
    debug(f"Error signature: {error_sig}", level=2)
    debug(f"Buffered context ({len(lines)} lines):\n{recent}", level=3)

    if breaker.is_tripped():
        debug("Circuit breaker already tripped, skipping fix")
        return False

    status(f"Process crashed. Attempting fix (attempt {breaker.attempts + 1}/3)...")

    history_context = history.format_context(error_sig) if history else ""

    result = await attempt_fix(
        error_summary=error_sig,
        traceback_text=recent,
        original_command=command,
        backend=backend,
        subprocess_cwd=subprocess_cwd,
        timeout=fix_timeout,
        history_context=history_context,
    )

    breaker.record_attempt(result.success, error_sig)

    if history is not None:
        history.record(
            error_summary=error_sig,
            command=command,
            success=result.success,
            duration=result.duration,
            traceback_snippet=recent,
            workspace=subprocess_cwd,
        )

    if result.success:
        status(f"Fix applied in {result.duration:.1f}s.")
        return True
    else:
        status(f"Fix attempt failed: {result.output[:200]}")
        debug(f"Full fix output:\n{result.output}", level=2)
        return not breaker.is_tripped()


async def _handle_live_error(
    detector: ErrorDetector,
    breaker: CircuitBreaker,
    command: str,
    backend: AgentBackend,
    subprocess_cwd: Path,
    fix_timeout: float = 120.0,
    history: FixHistory | None = None,
) -> bool:
    context = detector.get_buffered_context()
    status("Suspicious output detected. Running triage...")
    debug(f"Triage context ({len(context)} chars):\n{context}", level=3)

    triage = await detector.triage(context)
    detector.reset()

    debug(
        f"Triage result: is_error={triage.is_error}, summary={triage.error_summary!r}",
        level=2,
    )

    if not triage.is_error:
        status("Triage: not an actionable error. Continuing.")
        return True

    error_sig = _extract_error_signature(triage.traceback_text or triage.error_summary)

    if breaker.is_tripped():
        debug("Circuit breaker already tripped, skipping fix")
        return False

    status(
        f"Error confirmed: {triage.error_summary}\n"
        f"       Attempting fix (attempt {breaker.attempts + 1}/3)..."
    )

    history_context = history.format_context(error_sig) if history else ""

    result = await attempt_fix(
        error_summary=triage.error_summary,
        traceback_text=triage.traceback_text,
        original_command=command,
        backend=backend,
        subprocess_cwd=subprocess_cwd,
        timeout=fix_timeout,
        history_context=history_context,
    )

    breaker.record_attempt(result.success, error_sig)

    if history is not None:
        history.record(
            error_summary=error_sig,
            command=command,
            success=result.success,
            duration=result.duration,
            traceback_snippet=triage.traceback_text,
            workspace=subprocess_cwd,
        )

    if result.success:
        status(f"Fix applied in {result.duration:.1f}s. Waiting for hot-reload...")
        return True
    else:
        status(f"Fix attempt failed: {result.output[:200]}")
        debug(f"Full fix output:\n{result.output}", level=2)
        return not breaker.is_tripped()


async def run(
    command: str,
    backend: AgentBackend | None = None,
    workspace: Path | None = None,
    agent_executable_path: str | None = None,
    fix_timeout: float = 120.0,
) -> int:
    agent_backend = backend or ClaudeBackend()
    workdir = (workspace or Path.cwd()).resolve()
    for line in agent_backend.session_summary_lines(
        workdir=workdir,
        agent_executable_path=agent_executable_path,
    ):
        status(line)
    status(f"Watching: {command}")
    if fix_timeout != 120.0:
        status(f"Fix timeout: {fix_timeout:.0f}s")
    runner = ProcessRunner(command, cwd=workdir)
    detector = ErrorDetector(agent_backend, subprocess_cwd=workdir)
    breaker = CircuitBreaker()
    history = FixHistory.load(workdir)

    # Handle signals for clean shutdown
    # First Ctrl+C: graceful shutdown. Second Ctrl+C: force exit.
    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _handle_signal():
        if shutdown.is_set():
            # Second signal — force exit
            status("Forced shutdown.")
            runner.force_kill()
            raise SystemExit(130)
        shutdown.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    process = await runner.start()
    status(f"Process started (PID {runner.pid})")

    while not shutdown.is_set():
        stop_event = asyncio.Event()

        stdout_task = asyncio.create_task(
            _read_stream(
                process.stdout, detector, is_stderr=False, stop_event=stop_event
            )
        )
        stderr_task = asyncio.create_task(
            _read_stream(
                process.stderr, detector, is_stderr=True, stop_event=stop_event
            )
        )
        wait_task = asyncio.create_task(process.wait())
        settle_task = asyncio.create_task(
            _wait_for_settle(detector, stop_event=stop_event)
        )

        shutdown_task = asyncio.create_task(shutdown.wait())

        done, pending = await asyncio.wait(
            [wait_task, settle_task, shutdown_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Cancel whichever didn't fire
        for task in pending:
            task.cancel()

        if shutdown_task in done:
            stop_event.set()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            break

        if wait_task in done:
            # Process exited
            stop_event.set()

            # Let readers drain remaining output
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

            exit_code = process.returncode
            if exit_code == 0:
                status("Process exited cleanly.")
                return 0

            status(f"Process exited with code {exit_code}.")

            should_continue = await _handle_crash(
                detector, breaker, command, agent_backend, workdir,
                fix_timeout=fix_timeout, history=history,
            )
            if not should_continue:
                status(
                    "Circuit breaker tripped after 3 consecutive failed fixes. Giving up."
                )
                return 1

            detector.reset()
            process = await runner.restart()
            status(f"Process restarted (PID {runner.pid})")

        elif settle_task in done:
            # Error detected while process is alive
            should_continue = await _handle_live_error(
                detector, breaker, command, agent_backend, workdir,
                fix_timeout=fix_timeout, history=history,
            )
            if not should_continue:
                stop_event.set()
                await runner.stop()
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
                status(
                    "Circuit breaker tripped after 3 consecutive failed fixes. Giving up."
                )
                return 1

            # Process is still alive — continue monitoring
            # Cancel old tasks and loop to create fresh ones
            stop_event.set()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

    # Shutdown requested
    await runner.stop()
    return 130
