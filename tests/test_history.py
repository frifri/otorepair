"""Tests for otorepair.history — persistent fix history."""

import json

import pytest

from otorepair.history import (
    MAX_CONTEXT_ENTRIES,
    MAX_HISTORY_SIZE,
    FixHistory,
    HistoryEntry,
)


# ---------------------------------------------------------------------------
# HistoryEntry dataclass
# ---------------------------------------------------------------------------


class TestHistoryEntry:
    def test_creation(self):
        e = HistoryEntry(
            timestamp=1000.0,
            error_summary="ValueError: x",
            command="python app.py",
            success=True,
            duration=2.5,
        )
        assert e.success is True
        assert e.traceback_snippet == ""

    def test_with_traceback(self):
        e = HistoryEntry(
            timestamp=1000.0,
            error_summary="err",
            command="cmd",
            success=False,
            duration=1.0,
            traceback_snippet="File app.py line 1\nValueError",
        )
        assert "ValueError" in e.traceback_snippet


# ---------------------------------------------------------------------------
# FixHistory — persistence
# ---------------------------------------------------------------------------


class TestFixHistoryPersistence:
    def test_save_and_load(self, tmp_path):
        history = FixHistory()
        history.record(
            error_summary="ImportError: no module named foo",
            command="python app.py",
            success=True,
            duration=3.0,
            workspace=tmp_path,
        )

        loaded = FixHistory.load(tmp_path)
        assert len(loaded.entries) == 1
        assert loaded.entries[0].error_summary == "ImportError: no module named foo"
        assert loaded.entries[0].success is True

    def test_load_missing_file(self, tmp_path):
        loaded = FixHistory.load(tmp_path)
        assert len(loaded.entries) == 0

    def test_load_corrupt_file(self, tmp_path):
        path = tmp_path / ".otorepair" / "history.json"
        path.parent.mkdir(parents=True)
        path.write_text("not valid json {{{", encoding="utf-8")

        loaded = FixHistory.load(tmp_path)
        assert len(loaded.entries) == 0

    def test_load_invalid_entries(self, tmp_path):
        path = tmp_path / ".otorepair" / "history.json"
        path.parent.mkdir(parents=True)
        path.write_text('[{"bad": "data"}]', encoding="utf-8")

        loaded = FixHistory.load(tmp_path)
        assert len(loaded.entries) == 0

    def test_creates_directory_if_missing(self, tmp_path):
        history = FixHistory()
        history.record(
            error_summary="err",
            command="cmd",
            success=True,
            duration=1.0,
            workspace=tmp_path,
        )

        assert (tmp_path / ".otorepair" / "history.json").exists()

    def test_multiple_entries(self, tmp_path):
        history = FixHistory()
        history.record(
            error_summary="err1",
            command="cmd",
            success=False,
            duration=1.0,
            workspace=tmp_path,
        )
        history.record(
            error_summary="err2",
            command="cmd",
            success=True,
            duration=2.0,
            workspace=tmp_path,
        )

        loaded = FixHistory.load(tmp_path)
        assert len(loaded.entries) == 2
        assert loaded.entries[0].error_summary == "err1"
        assert loaded.entries[1].error_summary == "err2"


# ---------------------------------------------------------------------------
# FixHistory — pruning
# ---------------------------------------------------------------------------


class TestFixHistoryPruning:
    def test_prunes_to_max_size(self, tmp_path):
        history = FixHistory()
        for i in range(MAX_HISTORY_SIZE + 10):
            history.entries.append(
                HistoryEntry(
                    timestamp=float(i),
                    error_summary=f"err{i}",
                    command="cmd",
                    success=True,
                    duration=1.0,
                )
            )

        history.save(tmp_path)
        loaded = FixHistory.load(tmp_path)
        assert len(loaded.entries) == MAX_HISTORY_SIZE
        # Should keep the most recent entries
        assert loaded.entries[0].error_summary == "err10"


# ---------------------------------------------------------------------------
# FixHistory — recording
# ---------------------------------------------------------------------------


class TestFixHistoryRecord:
    def test_record_appends(self):
        history = FixHistory()
        history.record(
            error_summary="err",
            command="cmd",
            success=True,
            duration=1.0,
        )
        assert len(history.entries) == 1

    def test_record_truncates_traceback(self):
        history = FixHistory()
        history.record(
            error_summary="err",
            command="cmd",
            success=False,
            duration=1.0,
            traceback_snippet="x" * 1000,
        )
        assert len(history.entries[0].traceback_snippet) == 500

    def test_record_saves_when_workspace_given(self, tmp_path):
        history = FixHistory()
        history.record(
            error_summary="err",
            command="cmd",
            success=True,
            duration=1.0,
            workspace=tmp_path,
        )
        assert (tmp_path / ".otorepair" / "history.json").exists()

    def test_record_does_not_save_without_workspace(self):
        history = FixHistory()
        history.record(
            error_summary="err",
            command="cmd",
            success=True,
            duration=1.0,
        )
        # No crash, just appends in memory
        assert len(history.entries) == 1

    def test_record_sets_timestamp(self):
        history = FixHistory()
        history.record(
            error_summary="err",
            command="cmd",
            success=True,
            duration=1.0,
        )
        assert history.entries[0].timestamp > 0


# ---------------------------------------------------------------------------
# FixHistory — format_context
# ---------------------------------------------------------------------------


class TestFixHistoryFormatContext:
    def test_empty_history(self):
        history = FixHistory()
        assert history.format_context("any error") == ""

    def test_single_success(self):
        history = FixHistory()
        history.entries.append(
            HistoryEntry(
                timestamp=1000.0,
                error_summary="ValueError: x",
                command="python app.py",
                success=True,
                duration=2.5,
            )
        )
        ctx = history.format_context("ValueError: x")
        assert "SUCCESS" in ctx
        assert "ValueError: x" in ctx
        assert "Previous fix attempts" in ctx

    def test_single_failure_with_snippet(self):
        history = FixHistory()
        history.entries.append(
            HistoryEntry(
                timestamp=1000.0,
                error_summary="ImportError",
                command="cmd",
                success=False,
                duration=1.0,
                traceback_snippet="File app.py line 1\nImportError: foo",
            )
        )
        ctx = history.format_context("ImportError")
        assert "FAILED" in ctx
        assert "last line:" in ctx
        assert "ImportError: foo" in ctx

    def test_relevance_ranking_exact_match_first(self):
        history = FixHistory()
        history.entries.append(
            HistoryEntry(
                timestamp=1000.0,
                error_summary="unrelated error",
                command="cmd",
                success=True,
                duration=1.0,
            )
        )
        history.entries.append(
            HistoryEntry(
                timestamp=2000.0,
                error_summary="ValueError: x",
                command="cmd",
                success=False,
                duration=1.0,
            )
        )
        ctx = history.format_context("ValueError: x")
        lines = ctx.strip().splitlines()
        # The exact match should appear first (after header)
        assert "ValueError: x" in lines[1]

    def test_relevance_ranking_partial_match(self):
        history = FixHistory()
        history.entries.append(
            HistoryEntry(
                timestamp=1000.0,
                error_summary="totally different",
                command="cmd",
                success=True,
                duration=1.0,
            )
        )
        history.entries.append(
            HistoryEntry(
                timestamp=2000.0,
                error_summary="ValueError: something",
                command="cmd",
                success=True,
                duration=1.0,
            )
        )
        ctx = history.format_context("ValueError")
        lines = ctx.strip().splitlines()
        # Partial match should rank higher
        assert "ValueError" in lines[1]

    def test_max_context_entries(self):
        history = FixHistory()
        for i in range(MAX_CONTEXT_ENTRIES + 5):
            history.entries.append(
                HistoryEntry(
                    timestamp=float(i),
                    error_summary=f"err{i}",
                    command="cmd",
                    success=True,
                    duration=1.0,
                )
            )
        ctx = history.format_context("something")
        # Count bullet lines
        bullet_lines = [l for l in ctx.splitlines() if l.startswith("- [")]
        assert len(bullet_lines) == MAX_CONTEXT_ENTRIES

    def test_success_entries_no_snippet(self):
        history = FixHistory()
        history.entries.append(
            HistoryEntry(
                timestamp=1000.0,
                error_summary="err",
                command="cmd",
                success=True,
                duration=1.0,
                traceback_snippet="some trace",
            )
        )
        ctx = history.format_context("err")
        # Success entries don't show traceback snippets
        assert "last line:" not in ctx
