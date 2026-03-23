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
| Cursor only | `CURSOR_API_KEY` or `agent login`; `OTOREPAIR_CURSOR_TRIAGE_MODEL` optional |

otorepair will display all output from your command normally. When an error is detected, you'll see:

```
[otorepair] Process crashed. Attempting fix (attempt 1/3)...
  | Looking at the traceback, the issue is a missing import...
  | I'll fix the import in src/main.py...
[otorepair] Fix applied in 4.2s.
[otorepair] Process restarted (PID 12345)
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

## Circuit breaker

If the same error persists after 3 consecutive fix attempts, otorepair stops and shows you the error. If the error *changes* between attempts (meaning progress is being made), the counter resets.

## Running tests

```bash
uv pip install -e ".[dev]"
pytest
```
