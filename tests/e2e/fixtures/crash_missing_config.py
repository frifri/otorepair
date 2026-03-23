"""App that crashes because config.txt is missing.

The fake agent fix: create config.txt with "ok".
After fix + restart the app prints "started" and exits 0.
"""
import sys
from pathlib import Path

config = Path(__file__).parent / "config.txt"
if not config.exists():
    print("ERROR: config.txt not found", file=sys.stderr)
    raise SystemExit(1)

value = config.read_text().strip()
if value != "ok":
    print(f"ERROR: bad config value: {value!r}", file=sys.stderr)
    raise SystemExit(1)

print("started")
