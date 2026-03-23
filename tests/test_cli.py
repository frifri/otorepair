"""Tests for otorepair.cli — argument parsing and entry point."""

import sys
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from otorepair.cli import main
from otorepair.log import get_verbosity, set_verbosity


class TestCliArgumentParsing:
    def test_no_args_exits_with_error(self):
        with patch("sys.argv", ["otorepair"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code != 0

    def test_version_flag(self):
        with patch("sys.argv", ["otorepair", "--version"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0


class TestCliVerboseFlag:
    def test_default_verbosity_is_zero(self):
        with (
            patch("sys.argv", ["otorepair", "cmd"]),
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch("asyncio.run", return_value=0),
        ):
            main()
        assert get_verbosity() == 0

    def test_single_v(self):
        with (
            patch("sys.argv", ["otorepair", "-v", "cmd"]),
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch("asyncio.run", return_value=0),
        ):
            main()
        assert get_verbosity() == 1
        set_verbosity(0)

    def test_double_v(self):
        with (
            patch("sys.argv", ["otorepair", "-vv", "cmd"]),
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch("asyncio.run", return_value=0),
        ):
            main()
        assert get_verbosity() == 2
        set_verbosity(0)

    def test_triple_v(self):
        with (
            patch("sys.argv", ["otorepair", "-vvv", "cmd"]),
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch("asyncio.run", return_value=0),
        ):
            main()
        assert get_verbosity() == 3
        set_verbosity(0)


class TestCliClaudeCheck:
    def test_returns_1_when_claude_not_found(self, capsys):
        with (
            patch("sys.argv", ["otorepair", "python app.py"]),
            patch("shutil.which", return_value=None),
        ):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "claude" in captured.err.lower()

    def test_returns_1_when_agent_not_found_for_cursor(self, capsys, monkeypatch):
        monkeypatch.delenv("OTOREPAIR_BACKEND", raising=False)
        with (
            patch("sys.argv", ["otorepair", "--backend", "cursor", "python app.py"]),
            patch("shutil.which", return_value=None),
        ):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "agent" in captured.err.lower()

    def test_invalid_otorepair_backend_env(self, capsys, monkeypatch):
        monkeypatch.setenv("OTOREPAIR_BACKEND", "not-a-backend")
        with patch("sys.argv", ["otorepair", "cmd"]):
            result = main()

        assert result == 1
        assert "OTOREPAIR_BACKEND" in capsys.readouterr().err

    def test_backend_flag_overrides_env(self, monkeypatch):
        monkeypatch.setenv("OTOREPAIR_BACKEND", "cursor")

        def which_only(name: str) -> str | None:
            return f"/bin/{name}" if name in ("claude", "agent") else None

        with (
            patch("sys.argv", ["otorepair", "--backend", "claude", "cmd"]),
            patch("shutil.which", side_effect=which_only),
            patch("asyncio.run", return_value=0),
        ):
            result = main()

        assert result == 0

    def test_env_selects_cursor_backend(self, monkeypatch):
        monkeypatch.setenv("OTOREPAIR_BACKEND", "cursor")

        def which_only(name: str) -> str | None:
            return "/bin/agent" if name == "agent" else None

        status_ok = CompletedProcess(
            args=["agent", "status"],
            returncode=0,
            stdout="",
            stderr="",
        )
        with (
            patch("sys.argv", ["otorepair", "cmd"]),
            patch("shutil.which", side_effect=which_only),
            patch("otorepair.backends.subprocess.run", return_value=status_ok),
            patch("asyncio.run", return_value=0),
        ):
            result = main()

        assert result == 0

    def test_cursor_auth_failure_exits_before_run(
        self, capsys, monkeypatch, tmp_path
    ):
        monkeypatch.delenv("CURSOR_API_KEY", raising=False)
        repo = tmp_path / "repo"
        repo.mkdir()
        status_fail = CompletedProcess(
            args=["agent", "status"],
            returncode=1,
            stdout="",
            stderr="not logged in",
        )

        def which_only(name: str) -> str | None:
            return "/bin/agent" if name == "agent" else None

        with (
            patch(
                "sys.argv",
                [
                    "otorepair",
                    "--backend",
                    "cursor",
                    "--workspace",
                    str(repo),
                    "cmd",
                ],
            ),
            patch("shutil.which", side_effect=which_only),
            patch("otorepair.backends.subprocess.run", return_value=status_fail),
            patch("asyncio.run") as mock_ar,
        ):
            result = main()

        assert result == 1
        err = capsys.readouterr().err
        assert "not logged in" in err
        mock_ar.assert_not_called()

    def test_calls_run_when_claude_found(self):
        with (
            patch("sys.argv", ["otorepair", "python app.py"]),
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch("otorepair.cli.run", return_value=0) as mock_run,
            patch("asyncio.run", return_value=0) as mock_asyncio_run,
        ):
            result = main()

        assert result == 0
        mock_asyncio_run.assert_called_once()

    def test_keyboard_interrupt_returns_130(self):
        with (
            patch("sys.argv", ["otorepair", "python app.py"]),
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch("asyncio.run", side_effect=KeyboardInterrupt),
        ):
            result = main()

        assert result == 130


class TestCliWorkspace:
    def test_returns_1_when_workspace_missing(self, capsys, tmp_path):
        missing = tmp_path / "gone"
        with (
            patch("sys.argv", ["otorepair", "--workspace", str(missing), "cmd"]),
            patch("shutil.which", return_value="/usr/bin/claude"),
        ):
            result = main()

        assert result == 1
        assert "does not exist" in capsys.readouterr().err

    def test_returns_1_when_workspace_not_dir(self, capsys, tmp_path):
        f = tmp_path / "notadir"
        f.write_text("x")
        with (
            patch("sys.argv", ["otorepair", "--workspace", str(f), "cmd"]),
            patch("shutil.which", return_value="/usr/bin/claude"),
        ):
            result = main()

        assert result == 1
        assert "not a directory" in capsys.readouterr().err.lower()

    def test_valid_workspace_runs(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OTOREPAIR_WORKSPACE", raising=False)
        ws = tmp_path / "repo"
        ws.mkdir()
        with (
            patch("sys.argv", ["otorepair", "--workspace", str(ws), "cmd"]),
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch("asyncio.run", return_value=0),
        ):
            assert main() == 0
