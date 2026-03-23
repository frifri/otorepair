# Contributing to Otorepair

## Development setup

```bash
git clone <repo-url>
cd otorepair
uv pip install -e ".[dev]"
```

## Running tests

```bash
pytest
```

Tests use `pytest` with `pytest-asyncio` (async mode is set to `auto` in `pyproject.toml`). All tests run without network access or external CLIs.

## Project structure

```
src/otorepair/
├── cli.py              CLI entry point and argument parsing
├── loop.py             Main async event loop (monitor → detect → fix → reload)
├── runner.py           Subprocess lifecycle management
├── detector.py         Two-tier error detection (regex + LLM triage)
├── fixer.py            Agent CLI invocation and output streaming
├── backends.py         Backend definitions (Claude Code, Cursor Agent)
├── circuit_breaker.py  Consecutive failure tracking
├── patterns.py         Regex patterns for heuristic matching
└── log.py              Verbosity and status output
```

## Design principles

- **Zero external dependencies** — stdlib only at runtime. This keeps installation trivial and avoids version conflicts.
- **Async throughout** — the main loop, process monitoring, and agent invocation all use `asyncio` to avoid blocking.
- **Two-tier detection** — cheap regex first, LLM triage only when needed. Keeps latency low and avoids unnecessary API calls.
- **Backend-agnostic** — the core loop doesn't know which agent CLI it's talking to. Backends define their own commands and output formats.

## Adding a new backend

1. Add a new class in `backends.py` implementing the same interface as `ClaudeBackend` / `CursorBackend`
2. Register it in `get_backend()`
3. Add the backend ID to the `--backend` choices in `cli.py`
4. Add tests in `tests/test_backends.py`

## Code style

- Type hints on all function signatures
- No external linters or formatters are configured — keep code consistent with the existing style
- Prefer `asyncio.subprocess` over `subprocess` for anything that runs during the main loop

## Submitting changes

1. Fork the repository and create a feature branch
2. Make your changes with clear, focused commits
3. Ensure all tests pass (`pytest`)
4. Open a pull request with a description of what changed and why
