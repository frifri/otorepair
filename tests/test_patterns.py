"""Tests for otorepair.patterns — regex patterns and constants."""

import re

from otorepair.patterns import (
    DEATH_CONTEXT_LINES,
    ERROR_LINE,
    FATAL_KEYWORDS,
    FILE_LINE_PATTERN,
    IGNORE_PATTERNS,
    MAX_BUFFER_LINES,
    SETTLE_TIMEOUT,
    STDERR_ERROR_KEYWORDS,
    TRACEBACK_START,
)


# ---------------------------------------------------------------------------
# TRACEBACK_START
# ---------------------------------------------------------------------------


class TestTracebackStart:
    def test_matches_standard_traceback(self):
        assert TRACEBACK_START.search("Traceback (most recent call last):")

    def test_no_match_with_prefix(self):
        # ^ anchor means it must be at line start
        assert not TRACEBACK_START.search(
            "2024-01-01 Traceback (most recent call last):"
        )

    def test_no_match_partial(self):
        assert not TRACEBACK_START.search("Traceback")
        assert not TRACEBACK_START.search("Traceback (most recent call")

    def test_no_match_normal_output(self):
        assert not TRACEBACK_START.search("Everything is fine")


# ---------------------------------------------------------------------------
# FILE_LINE_PATTERN
# ---------------------------------------------------------------------------


class TestFileLinePattern:
    def test_matches_standard_file_line(self):
        assert FILE_LINE_PATTERN.search('  File "app.py", line 42')

    def test_matches_deeply_indented(self):
        assert FILE_LINE_PATTERN.search(
            '    File "/usr/lib/python3.10/site.py", line 1'
        )

    def test_matches_nested_path(self):
        assert FILE_LINE_PATTERN.search('  File "/a/b/c/d.py", line 999')

    def test_no_match_without_line(self):
        assert not FILE_LINE_PATTERN.search('  File "app.py"')

    def test_no_match_plain_text(self):
        assert not FILE_LINE_PATTERN.search("some random text")


# ---------------------------------------------------------------------------
# ERROR_LINE
# ---------------------------------------------------------------------------


class TestErrorLine:
    def test_matches_common_errors(self):
        assert ERROR_LINE.search("ValueError: invalid literal")
        assert ERROR_LINE.search("TypeError: unsupported operand")
        assert ERROR_LINE.search("KeyError: 'missing_key'")
        assert ERROR_LINE.search("ModuleNotFoundError: No module named 'foo'")
        assert ERROR_LINE.search("AttributeError: 'NoneType' object")

    def test_matches_exception(self):
        assert ERROR_LINE.search("RuntimeException: something went wrong")

    def test_matches_fault(self):
        assert ERROR_LINE.search("SegmentationFault: core dumped")

    def test_no_match_warning(self):
        assert not ERROR_LINE.search("DeprecationWarning: something old")

    def test_no_match_plain_text(self):
        assert not ERROR_LINE.search("All tests passed")

    def test_no_match_error_in_middle(self):
        # The pattern requires ^word...Error: so this should not match
        assert not ERROR_LINE.search("  some ValueError: text")


# ---------------------------------------------------------------------------
# FATAL_KEYWORDS
# ---------------------------------------------------------------------------


class TestFatalKeywords:
    def test_matches_critical(self):
        assert FATAL_KEYWORDS.search("CRITICAL: database connection lost")
        assert FATAL_KEYWORDS.search("critical: something bad")

    def test_matches_fatal(self):
        assert FATAL_KEYWORDS.search("FATAL: cannot start")
        assert FATAL_KEYWORDS.search("Fatal error")

    def test_matches_panic(self):
        assert FATAL_KEYWORDS.search("PANIC: kernel error")
        assert FATAL_KEYWORDS.search("panic: runtime error")

    def test_no_match_embedded(self):
        assert not FATAL_KEYWORDS.search("not a CRITICAL issue")

    def test_no_match_plain(self):
        assert not FATAL_KEYWORDS.search("everything is fine")


# ---------------------------------------------------------------------------
# STDERR_ERROR_KEYWORDS
# ---------------------------------------------------------------------------


class TestStderrErrorKeywords:
    def test_contains_expected_keywords(self):
        expected = {
            "Traceback",
            "Error:",
            "Exception:",
            "Fatal:",
            "CRITICAL:",
            "SyntaxError",
            "IndentationError",
            "ModuleNotFoundError",
            "ImportError",
            "AttributeError",
            "NameError",
            "OSError",
            "PermissionError",
        }
        assert set(STDERR_ERROR_KEYWORDS) == expected

    def test_keywords_are_strings(self):
        for kw in STDERR_ERROR_KEYWORDS:
            assert isinstance(kw, str)


# ---------------------------------------------------------------------------
# IGNORE_PATTERNS
# ---------------------------------------------------------------------------


class TestIgnorePatterns:
    def test_ignores_deprecation_warning(self):
        assert any(p.search("DeprecationWarning: old thing") for p in IGNORE_PATTERNS)

    def test_ignores_pending_deprecation(self):
        assert any(p.search("PendingDeprecationWarning: soon") for p in IGNORE_PATTERNS)

    def test_ignores_resource_warning(self):
        assert any(p.search("ResourceWarning: unclosed file") for p in IGNORE_PATTERNS)

    def test_ignores_user_warning(self):
        assert any(p.search("UserWarning: something") for p in IGNORE_PATTERNS)

    def test_ignores_insecure_request(self):
        assert any(p.search("InsecureRequestWarning: https") for p in IGNORE_PATTERNS)

    def test_ignores_watching_for_changes(self):
        assert any(
            p.search("Watching for file changes with StatReloader")
            for p in IGNORE_PATTERNS
        )

    def test_ignores_system_checks(self):
        assert any(p.search("Performing system checks...") for p in IGNORE_PATTERNS)

    def test_does_not_ignore_real_error(self):
        assert not any(p.search("ValueError: bad value") for p in IGNORE_PATTERNS)

    def test_all_patterns_are_compiled(self):
        for p in IGNORE_PATTERNS:
            assert isinstance(p, re.Pattern)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_settle_timeout_is_positive(self):
        assert SETTLE_TIMEOUT > 0

    def test_max_buffer_lines_is_positive(self):
        assert MAX_BUFFER_LINES > 0

    def test_death_context_lines_is_positive(self):
        assert DEATH_CONTEXT_LINES > 0

    def test_death_context_lines_within_buffer(self):
        assert DEATH_CONTEXT_LINES <= MAX_BUFFER_LINES
