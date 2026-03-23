#!/usr/bin/env python3
"""
Fake ``claude`` CLI for E2E tests.

Mimics the interface used by ClaudeBackend:
  - Triage: ``claude -p --model haiku`` — reads prompt on stdin, prints response
  - Fix:    ``claude -p --allowedTools ...`` — reads prompt on stdin, optionally
    edits files, prints output, exits 0 (success) or 1 (failure)

Behavior is controlled via environment variables:

    FAKE_CLAUDE_TRIAGE_RESPONSE
        Raw text printed to stdout for triage calls.
        Default: "NO" (not an error).

    FAKE_CLAUDE_FIX_SCRIPT
        Path to a Python script that gets ``exec``'d during fix calls.
        The script receives ``prompt`` (str) and ``cwd`` (str) in its globals.
        Default: no-op (just prints "Fix applied" and exits 0).

    FAKE_CLAUDE_FIX_EXIT
        Exit code for fix calls.  Default: "0".
"""
import os
import sys


def _is_triage() -> bool:
    return "--model" in sys.argv and "haiku" in sys.argv


def main() -> None:
    prompt = sys.stdin.read()

    if _is_triage():
        response = os.environ.get("FAKE_CLAUDE_TRIAGE_RESPONSE", "NO")
        print(response)
        sys.exit(0)

    # Fix mode
    fix_script = os.environ.get("FAKE_CLAUDE_FIX_SCRIPT", "")
    if fix_script:
        with open(fix_script) as f:
            code = f.read()
        exec(code, {"prompt": prompt, "cwd": os.getcwd()})

    exit_code = int(os.environ.get("FAKE_CLAUDE_FIX_EXIT", "0"))
    if exit_code == 0:
        print("Fix applied successfully.")
    else:
        print("Could not determine a fix.", file=sys.stderr)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
