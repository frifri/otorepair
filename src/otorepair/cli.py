import argparse
import asyncio
import shutil
import sys

from otorepair import __version__
from otorepair.log import set_verbosity, status
from otorepair.loop import run


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
        "--version",
        action="version",
        version=f"otorepair {__version__}",
    )

    args = parser.parse_args()

    set_verbosity(args.verbose)

    if not shutil.which("claude"):
        print(
            "Error: 'claude' CLI not found on PATH.\n"
            "Install it from https://docs.anthropic.com/en/docs/claude-code",
            file=sys.stderr,
        )
        return 1

    try:
        return asyncio.run(run(args.command))
    except KeyboardInterrupt:
        status("Interrupted. Shutting down.")
        return 130
