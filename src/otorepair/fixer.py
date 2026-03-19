import asyncio
from dataclasses import dataclass
from time import monotonic

from otorepair.log import debug, status


@dataclass
class FixResult:
    success: bool
    output: str
    duration: float


def _print_fix_output(line: str) -> None:
    """Print a line of claude output with muted styling."""
    print(f"\033[2m  | {line}\033[0m", flush=True)


async def attempt_fix(
    error_summary: str,
    traceback_text: str,
    original_command: str,
    *,
    timeout: float = 120.0,
) -> FixResult:
    prompt = (
        "The following Python application encountered an error while running.\n\n"
        f"Command: {original_command}\n\n"
        f"Error: {error_summary}\n\n"
        f"Traceback:\n{traceback_text}\n\n"
        "Please fix this error. Look at the relevant source files, understand the "
        "issue, and make the necessary code changes."
    )

    start = monotonic()

    debug("Spawning: claude -p --allowedTools Edit,Read,Write,Bash,Glob,Grep")
    debug(f"Prompt ({len(prompt)} bytes):\n{prompt}", level=3)

    try:
        proc = await asyncio.create_subprocess_exec(
            "claude",
            "-p",
            "--allowedTools",
            "Edit,Read,Write,Bash,Glob,Grep",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as e:
        debug(f"Failed to spawn claude: {e}")
        return FixResult(
            success=False,
            output=f"Failed to run claude CLI: {e}",
            duration=monotonic() - start,
        )

    debug(f"Claude process started (PID {proc.pid})")

    # Send prompt and close stdin so claude knows input is complete
    proc.stdin.write(prompt.encode())
    await proc.stdin.drain()
    proc.stdin.close()
    debug(f"Prompt sent ({len(prompt)} bytes), stdin closed", level=2)

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    async def _read_stdout() -> None:
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            _print_fix_output(line)
            stdout_lines.append(line)

    async def _read_stderr() -> None:
        while True:
            raw = await proc.stderr.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            debug(f"claude stderr: {line}", level=2)
            stderr_lines.append(line)

    try:
        debug(f"Waiting for claude output (timeout={timeout}s)...")
        await asyncio.wait_for(
            asyncio.gather(_read_stdout(), _read_stderr(), proc.wait()),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        debug(
            f"Timeout after {monotonic() - start:.1f}s, killing claude (PID {proc.pid})"
        )
        proc.kill()
        await proc.wait()
        return FixResult(
            success=False,
            output="Fix timed out after 120 seconds",
            duration=monotonic() - start,
        )

    duration = monotonic() - start
    output = "\n".join(stdout_lines)

    debug(
        f"Claude exited with code {proc.returncode} after {duration:.1f}s "
        f"(stdout: {len(stdout_lines)} lines, stderr: {len(stderr_lines)} lines)"
    )

    if proc.returncode != 0 and stderr_lines:
        output += "\nstderr: " + "\n".join(stderr_lines)
        debug(f"stderr contents: {chr(10).join(stderr_lines)}", level=2)

    return FixResult(
        success=proc.returncode == 0,
        output=output,
        duration=duration,
    )
