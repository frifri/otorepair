"""Tests for otorepair.cli — argument parsing and entry point."""

import sys
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
