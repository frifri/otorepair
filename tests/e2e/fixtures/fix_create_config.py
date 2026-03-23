"""Fix script for crash_missing_config: creates the missing config.txt.

Executed by fake_claude.py via exec() — receives ``prompt`` and ``cwd`` globals.
"""
from pathlib import Path

# The fixture app lives next to this script, but otorepair runs the command
# from the workspace dir. The traceback in the prompt tells us the file path.
# For simplicity, we find the fixtures dir from the prompt.
import re

match = re.search(r'File "(.+?)fixtures/', prompt)
if match:
    fixtures_dir = Path(match.group(1)) / "fixtures"
else:
    fixtures_dir = Path(cwd)

config = fixtures_dir / "config.txt"
config.write_text("ok\n")
print(f"Created {config}")
