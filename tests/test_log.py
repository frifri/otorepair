"""Tests for otorepair.log — verbosity-based logging."""

from otorepair.log import debug, get_verbosity, set_verbosity, status


class TestStatus:
    def test_prints_with_prefix(self, capsys):
        status("hello")
        captured = capsys.readouterr()
        assert "[otorepair]" in captured.out
        assert "hello" in captured.out


class TestDebug:
    def test_hidden_at_verbosity_0(self, capsys):
        set_verbosity(0)
        debug("secret")
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_shown_at_verbosity_1(self, capsys):
        set_verbosity(1)
        debug("visible")
        captured = capsys.readouterr()
        assert "visible" in captured.out
        assert "[otorepair:debug]" in captured.out
        set_verbosity(0)

    def test_level_2_hidden_at_verbosity_1(self, capsys):
        set_verbosity(1)
        debug("detailed", level=2)
        captured = capsys.readouterr()
        assert captured.out == ""
        set_verbosity(0)

    def test_level_2_shown_at_verbosity_2(self, capsys):
        set_verbosity(2)
        debug("detailed", level=2)
        captured = capsys.readouterr()
        assert "detailed" in captured.out
        set_verbosity(0)

    def test_level_3_shown_at_verbosity_3(self, capsys):
        set_verbosity(3)
        debug("raw data", level=3)
        captured = capsys.readouterr()
        assert "raw data" in captured.out
        set_verbosity(0)

    def test_higher_verbosity_shows_lower_levels(self, capsys):
        set_verbosity(3)
        debug("level 1", level=1)
        debug("level 2", level=2)
        debug("level 3", level=3)
        captured = capsys.readouterr()
        assert "level 1" in captured.out
        assert "level 2" in captured.out
        assert "level 3" in captured.out
        set_verbosity(0)


class TestSetGetVerbosity:
    def test_default_is_zero(self):
        set_verbosity(0)
        assert get_verbosity() == 0

    def test_set_and_get(self):
        set_verbosity(2)
        assert get_verbosity() == 2
        set_verbosity(0)
