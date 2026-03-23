# Otorepair

Auto-healing dev loop CLI. Monitors your running process, detects errors, and invokes an agent CLI to triage and patch sources — **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** by default, or **[Cursor Agent](https://cursor.com/docs/cli/overview)** (`agent`).

## How it works

```
Start command → Monitor output → Detect error → Agent fixes it → Reload
                     ↑                                              │
                     └──────────────────────────────────────────────┘
```

1. Runs your command as a subprocess, streaming stdout/stderr to your terminal
2. **Heuristic pre-filter** watches stderr for suspicious patterns (tracebacks, error keywords)
3. When triggered, an **LLM triages** the output (Claude Haiku on the Claude backend) to confirm it's a real error
4. If confirmed (or if the process crashed), the **agent fixes** the source files
5. Fix output is **streamed** (plain lines with Claude; NDJSON with Cursor) so you can see progress
6. If the process is still alive, hot-reload picks up the changes. If it crashed, otorepair restarts it
7. **Circuit breaker** stops after 3 consecutive failed fix attempts

## Requirements

- Python 3.12+
- On your PATH: **`claude`** ([Claude Code](https://docs.anthropic.com/en/docs/claude-code)) and/or **`agent`** ([Cursor CLI](https://cursor.com/docs/cli/installation)), depending on `--backend`

## Installation

```bash
uv tool install -e .
```

For development (includes test dependencies):

```bash
uv pip install -e ".[dev]"
```

## Usage

```bash
otorepair "python manage.py runserver"
otorepair "uvicorn app:main --reload"
otorepair "flask run --debug"
```

At startup, otorepair prints **backend**, **triage/fix model**, then `Watching: …`. With **Cursor**, an extra line shows **workspace** (`cwd` + `agent --workspace`). **`--workspace` / `OTOREPAIR_WORKSPACE`** still set **cwd** for both backends (monitored command and agent subprocesses).

**Agent & workspace (optional)**

| CLI / env | Notes |
|-----------|-------|
| `--backend` / `OTOREPAIR_BACKEND` | `claude` (default) or `cursor` |
| `--workspace` / `OTOREPAIR_WORKSPACE` | **Both backends:** cwd for the watched command and agent subprocesses. **Cursor only:** also `agent --workspace`. |
| `--fix-timeout` / `OTOREPAIR_FIX_TIMEOUT` | Max seconds for each fix attempt (default: 120) |
| Cursor only | `CURSOR_API_KEY` or `agent login`; `OTOREPAIR_CURSOR_TRIAGE_MODEL` optional |

otorepair will display all output from your command normally. When an error is detected, you'll see:

```
[otorepair] Process crashed. Attempting fix (attempt 1/3)...
  | Looking at the traceback, the issue is a missing import...
  | I'll fix the import in src/main.py...
[otorepair] Fix applied in 4.2s.
[otorepair] Process restarted (PID 12345)
```

### Command-line reference

```
usage: otorepair [-h] [-v] [--backend {claude,cursor}] [--workspace DIR]
                 [--fix-timeout SECS] [--version] command

positional arguments:
  command                The command to run and monitor (e.g. 'python manage.py runserver')

options:
  -h, --help             Show help message and exit
  -v, --verbose          Increase verbosity (-v, -vv, -vvv)
  --backend {claude,cursor}
                         Agent CLI backend (default: claude)
  --workspace DIR        Project root directory
  --fix-timeout SECS     Max seconds per fix attempt (default: 120, or $OTOREPAIR_FIX_TIMEOUT)
  --version              Show version and exit
```

### Verbose mode

Use `-v` flags for debug output when troubleshooting:

```bash
otorepair -v "python app.py"     # Key events (subprocess spawn, exit codes)
otorepair -vv "python app.py"    # Detailed (stdin bytes, stderr, triage results)
otorepair -vvv "python app.py"   # Full debug (prompt text, raw data, buffer contents)
```

## Error detection

Two-tier system to balance speed and accuracy:

- **Tier 1 — Heuristic pre-filter**: Fast regex/keyword matching for `Traceback`, `Error:`, `Exception:`, `Fatal:`, etc. Zero cost, zero latency. Catches candidates, not final decisions.
- **Tier 2 — LLM triage**: Only runs when the heuristic triggers. Sends the suspicious output to the triage model (Haiku when using Claude) to decide if it's worth fixing.

Process crashes (non-zero exit) skip triage entirely and go straight to the fix pipeline.

### Detected patterns

The heuristic tier watches stderr for these patterns:

- Python tracebacks (`Traceback (most recent call last):`)
- Error keywords (`Error:`, `Exception:`, `CRITICAL`, `FATAL`)
- File references in stack traces (`File "...", line ...`)

The rolling buffer keeps up to 100 lines of recent stderr output. A 2-second "settle timeout" waits for the full error output before triggering triage.

## Fix history

Otorepair maintains a persistent log of fix attempts in `.otorepair/history.json` within your workspace. When the agent encounters a new error, relevant past attempts (both successes and failures) are included as context in the prompt. This helps the agent avoid repeating failed strategies and learn from what worked before.

The history file is created automatically on the first fix attempt. It stores up to 50 entries and is safe to delete at any time.

## Circuit breaker

If the same error persists after 3 consecutive fix attempts, otorepair stops and shows you the error. If the error *changes* between attempts (meaning progress is being made), the counter resets.

## Examples

Two runnable examples are included to demonstrate different error scenarios:

### Crash on start (missing env var)

The process crashes immediately because `PORT` is not set — this triggers the **crash path** (no LLM triage, straight to fix):

```bash
otorepair "python examples/crash_on_start/app.py"
```

The agent will typically fix it by changing `os.environ["PORT"]` to `os.environ.get("PORT", "8765")`.

### Live error (runtime exception)

An HTTP server that raises `RuntimeError` on GET requests — this triggers the **live error path** (heuristic + LLM triage + fix):

```bash
# Terminal 1: start otorepair
otorepair "python examples/broken_http_server/server.py"

# Terminal 2: trigger the error
curl -s http://127.0.0.1:8765/
```

The server stays running while otorepair detects the traceback on stderr and patches the handler.

## Architecture

```
cli.py          Parse args, resolve backend, launch async loop
  │
  ▼
loop.py         Main event loop: start process → monitor → detect → fix → reload
  │
  ├── runner.py         Subprocess lifecycle (start, stop, signal handling)
  ├── detector.py       Two-tier error detection (heuristic + LLM triage)
  ├── fixer.py          Spawn agent CLI, stream output, apply fix
  ├── backends.py       Backend config (Claude / Cursor CLI commands & args)
  ├── circuit_breaker.py  Track consecutive failures, halt after 3
  ├── history.py        Persistent fix history (.otorepair/history.json)
  ├── patterns.py       Regex patterns for heuristic error matching
  └── log.py            Verbosity levels and status output
```

## Troubleshooting

**`claude` or `agent` not found on PATH**

Install the required CLI tool:
- Claude Code: `npm install -g @anthropic-ai/claude-code`
- Cursor Agent: see [Cursor CLI installation](https://cursor.com/docs/cli/installation)

**Cursor authentication errors**

Run `agent login` or set the `CURSOR_API_KEY` environment variable.

**Fix attempts time out**

The agent has 120 seconds by default to produce a fix. Use `--fix-timeout 300` (or `OTOREPAIR_FIX_TIMEOUT=300`) to allow more time for large codebases. You can also try `--workspace` to point to a smaller subdirectory, or increase verbosity (`-vvv`) to see what the agent is doing.

**Circuit breaker keeps triggering**

The same error appeared 3 times in a row. Check the error output — it may be something the agent can't fix automatically (e.g., missing system dependency, network issue). Fix it manually and restart.

**Process output not detected as an error**

Otorepair watches **stderr** only. If your application logs errors to stdout, they won't be detected. Most frameworks log errors to stderr by default. Otorepair also sets `PYTHONUNBUFFERED=1` to ensure output is not buffered.

## Running tests

```bash
uv pip install -e ".[dev]"
pytest
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and contribution guidelines.
