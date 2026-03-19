"""Simple verbosity-based logging for otorepair."""

_verbosity = 0


def set_verbosity(level: int) -> None:
    global _verbosity
    _verbosity = level


def get_verbosity() -> int:
    return _verbosity


def status(msg: str) -> None:
    """Always-visible status message (cyan prefix)."""
    print(f"\033[96m[otorepair]\033[0m {msg}", flush=True)


def debug(msg: str, level: int = 1) -> None:
    """Print debug message if verbosity >= level.

    Levels:
        1 (-v)   : Key events (subprocess spawned, fix completed, etc.)
        2 (-vv)  : Detailed events (stdin sent, bytes count, triage result)
        3 (-vvv) : Full debug (prompt contents, raw data, internal state)
    """
    if _verbosity >= level:
        print(f"\033[90m[otorepair:debug] {msg}\033[0m", flush=True)
