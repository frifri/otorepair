import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from otorepair.backends import AgentBackend, ClaudeBackend
from otorepair.log import debug


@dataclass
class FixResult:
    success: bool
    output: str
    duration: float


def _print_fix_output(line: str) -> None:
    """Print a line of agent output with muted styling."""
    print(f"\033[2m  | {line}\033[0m", flush=True)


def _extract_assistant_text_chunk(obj: dict) -> str:
    """Best-effort text delta from a Cursor stream-json assistant event."""
    if obj.get("type") != "assistant":
        return ""
    msg = obj.get("message")
    if not isinstance(msg, dict):
        return ""
    parts = msg.get("content")
    if not isinstance(parts, list) or not parts:
        return ""
    block = parts[0]
    if not isinstance(block, dict):
        return ""
    text = block.get("text")
    return text if isinstance(text, str) else ""


def format_stream_json_fix_event(obj: dict) -> str | None:
    """
    Turn one decoded Cursor ``stream-json`` object into a human log line.

    Returns ``None`` to skip (or when assistant text is handled separately).
    """
    t = obj.get("type")
    st = obj.get("subtype")

    if t == "assistant":
        return None

    if t == "tool_call":
        if st != "started":
            return None
        tc = obj.get("tool_call")
        if not isinstance(tc, dict):
            return "[tool] (started)"
        for label, key in (
            ("write", "writeToolCall"),
            ("read", "readToolCall"),
            ("bash", "bashToolCall"),
            ("grep", "grepToolCall"),
        ):
            inner = tc.get(key)
            if isinstance(inner, dict):
                args = inner.get("args")
                if isinstance(args, dict):
                    hint = (
                        args.get("path")
                        or args.get("filePath")
                        or args.get("command")
                        or args.get("cmd")
                    )
                    if hint:
                        return f"[tool:{label}] {hint}"
                return f"[tool:{label}]"
        return "[tool] started"

    if t == "system" and st == "init":
        model = obj.get("model")
        if isinstance(model, str) and model:
            return f"[session] model={model}"
        return None

    if t == "result":
        ms = obj.get("duration_ms")
        if ms is not None:
            return f"[done] {ms}ms"
        return "[done]"

    return None


async def attempt_fix(
    error_summary: str,
    traceback_text: str,
    original_command: str,
    *,
    backend: AgentBackend | None = None,
    subprocess_cwd: Path | None = None,
    timeout: float = 120.0,
    history_context: str = "",
) -> FixResult:
    prompt = (
        "The following Python application encountered an error while running.\n\n"
        f"Command: {original_command}\n\n"
        f"Error: {error_summary}\n\n"
        f"Traceback:\n{traceback_text}\n\n"
    )

    if history_context:
        prompt += (
            f"{history_context}\n\n"
            "Use the history above to avoid repeating failed fix strategies.\n\n"
        )

    prompt += (
        "Please fix this error. Look at the relevant source files, understand the "
        "issue, and make the necessary code changes."
    )

    start = monotonic()
    agent = backend or ClaudeBackend()
    argv = agent.fix_argv()

    debug(f"Spawning fix: {' '.join(argv)}")
    debug(f"Prompt ({len(prompt)} bytes):\n{prompt}", level=3)

    popen_kw: dict = dict(
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    if subprocess_cwd is not None:
        popen_kw["cwd"] = os.fspath(subprocess_cwd)

    try:
        proc = await asyncio.create_subprocess_exec(*argv, **popen_kw)
    except OSError as e:
        debug(f"Failed to spawn {agent.executable}: {e}")
        return FixResult(
            success=False,
            output=f"Failed to run {agent.executable} CLI: {e}",
            duration=monotonic() - start,
        )

    debug(f"Agent process started (PID {proc.pid})")

    # Send prompt and close stdin so the agent knows input is complete
    proc.stdin.write(prompt.encode())
    await proc.stdin.drain()
    proc.stdin.close()
    debug(f"Prompt sent ({len(prompt)} bytes), stdin closed", level=2)

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    human_lines: list[str] = []

    use_stream_json = agent.fix_uses_stream_json_stdout()

    async def _read_stdout_plain() -> None:
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            _print_fix_output(line)
            stdout_lines.append(line)
            human_lines.append(line)

    async def _read_stdout_stream_json() -> None:
        pending_assistant: list[str] = []

        def flush_assistant() -> None:
            if not pending_assistant:
                return
            chunk = "".join(pending_assistant)
            pending_assistant.clear()
            if not chunk.strip():
                return
            for piece in chunk.split("\n"):
                if piece.strip():
                    _print_fix_output(piece)
                    human_lines.append(piece)

        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            stdout_lines.append(line)
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                _print_fix_output(line[:500])
                human_lines.append(line[:500])
                continue

            if not isinstance(obj, dict):
                continue

            delta = _extract_assistant_text_chunk(obj)
            if delta:
                pending_assistant.append(delta)
                continue

            flush_assistant()
            formatted = format_stream_json_fix_event(obj)
            if formatted:
                _print_fix_output(formatted)
                human_lines.append(formatted)

        flush_assistant()

    async def _read_stderr() -> None:
        while True:
            raw = await proc.stderr.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            debug(f"agent stderr: {line}", level=2)
            stderr_lines.append(line)

    read_out = _read_stdout_stream_json if use_stream_json else _read_stdout_plain

    try:
        debug(f"Waiting for agent output (timeout={timeout}s)...")
        await asyncio.wait_for(
            asyncio.gather(read_out(), _read_stderr(), proc.wait()),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        debug(
            f"Timeout after {monotonic() - start:.1f}s, killing agent (PID {proc.pid})"
        )
        proc.kill()
        await proc.wait()
        return FixResult(
            success=False,
            output=f"Fix timed out after {timeout:.0f} seconds",
            duration=monotonic() - start,
        )

    duration = monotonic() - start
    if use_stream_json and human_lines:
        output = "\n".join(human_lines)
    else:
        output = "\n".join(stdout_lines)

    debug(
        f"Agent exited with code {proc.returncode} after {duration:.1f}s "
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
