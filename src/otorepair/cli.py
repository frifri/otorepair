import argparse
import asyncio
import os
import shutil
import sys

from otorepair import __version__
from otorepair.backends import (
    check_cursor_cli_authenticated,
    get_backend,
    resolve_backend_id,
    resolve_workspace,
)
from otorepair.log import set_verbosity, status
from otorepair.loop import run


_DEFAULT_FIX_TIMEOUT = 120.0


def _resolve_fix_timeout(cli_value: float | None) -> float:
    """Resolve fix timeout: CLI flag > env var > default (120s)."""
    if cli_value is not None:
        return cli_value
    raw = os.environ.get("OTOREPAIR_FIX_TIMEOUT", "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return _DEFAULT_FIX_TIMEOUT


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="otorepair",
        description="Auto-healing dev loop — monitors your command and fixes errors automatically.",
    )
    parser.add_argument(
        "command",
        help="The command to run and monitor (e.g. 'python manage.py runserver')",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v, -vv, -vvv)",
    )
    parser.add_argument(
        "--backend",
        choices=("claude", "cursor"),
        default=None,
        help=(
            "Agent CLI: claude (Claude Code) or cursor (Cursor agent). "
            "Default: $OTOREPAIR_BACKEND if set, else claude."
        ),
    )
    parser.add_argument(
        "--workspace",
        metavar="DIR",
        default=None,
        help=(
            "Project root: cwd for the monitored command and Cursor --workspace. "
            "Default: $OTOREPAIR_WORKSPACE if set, else current directory."
        ),
    )
    parser.add_argument(
        "--fix-timeout",
        type=float,
        default=None,
        metavar="SECS",
        help=(
            "Max seconds to wait for the agent to fix an error. "
            "Default: $OTOREPAIR_FIX_TIMEOUT if set, else 120."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"otorepair {__version__}",
    )

    args = parser.parse_args()

    set_verbosity(args.verbose)

    backend_id, env_err = resolve_backend_id(args.backend)
    if env_err:
        print(env_err, file=sys.stderr)
        return 1
    assert backend_id is not None  # guaranteed by resolve_backend_id when env_err is None

    workspace, ws_err = resolve_workspace(args.workspace)
    if ws_err is not None or workspace is None:
        print(ws_err or "Invalid workspace.", file=sys.stderr)
        return 1

    backend = get_backend(backend_id, workspace=workspace)

    agent_path = shutil.which(backend.executable)
    if not agent_path:
        print(
            f"Error: {backend.executable!r} CLI not found on PATH.\n"
            f"Install it from {backend.spawn_error_hint()}",
            file=sys.stderr,
        )
        return 1

    if backend_id == "cursor":
        auth_ok, auth_msg = check_cursor_cli_authenticated(
            workspace, agent_bin=agent_path
        )
        if not auth_ok:
            print(auth_msg, file=sys.stderr)
            return 1

    fix_timeout = _resolve_fix_timeout(args.fix_timeout)

    try:
        return asyncio.run(
            run(
                args.command,
                backend=backend,
                workspace=workspace,
                agent_executable_path=agent_path,
                fix_timeout=fix_timeout,
            )
        )
    except KeyboardInterrupt:
        status("Interrupted. Shutting down.")
        return 130
