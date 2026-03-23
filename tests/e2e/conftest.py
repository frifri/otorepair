"""Shared fixtures for E2E tests.

The key trick: we create a temporary ``bin/`` directory containing a ``claude``
shim script that delegates to ``fake_claude.py``.  Tests set environment
variables to control the fake's behaviour, then call ``otorepair.loop.run()``
(or the CLI entry-point) which spawns the real async machinery — the only thing
replaced is the external agent binary.
"""
from __future__ import annotations

import os
import shutil
import stat
import sys
import textwrap
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
FAKE_CLAUDE = HERE / "fake_claude.py"


@pytest.fixture()
def fake_claude_bin(tmp_path: Path) -> Path:
    """Return a temp ``bin/`` directory containing a ``claude`` executable.

    The executable is a thin shell wrapper that invokes ``fake_claude.py``
    with the same Python interpreter running the tests.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    claude_shim = bin_dir / "claude"
    claude_shim.write_text(
        textwrap.dedent(f"""\
            #!/usr/bin/env bash
            exec {sys.executable} {FAKE_CLAUDE} "$@"
        """)
    )
    claude_shim.chmod(claude_shim.stat().st_mode | stat.S_IEXEC)
    return bin_dir


@pytest.fixture()
def e2e_env(fake_claude_bin: Path) -> dict[str, str]:
    """Return an env dict with fake claude on PATH and sane defaults."""
    env = os.environ.copy()
    # Prepend our fake bin so ``claude`` resolves to the shim
    env["PATH"] = f"{fake_claude_bin}{os.pathsep}{env.get('PATH', '')}"
    # Defaults — tests override as needed
    env.setdefault("FAKE_CLAUDE_FIX_EXIT", "0")
    env.setdefault("FAKE_CLAUDE_TRIAGE_RESPONSE", "NO")
    return env


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """A temporary workspace directory with fixture files copied in."""
    ws = tmp_path / "workspace"
    shutil.copytree(FIXTURES, ws)
    return ws
