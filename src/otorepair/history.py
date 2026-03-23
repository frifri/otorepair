"""Persistent fix history for otorepair.

Tracks past fix attempts in ``.otorepair/history.json`` within the workspace
so the agent can learn from previous successes and failures.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from otorepair.log import debug

# How many recent entries to include as context in fix prompts.
MAX_CONTEXT_ENTRIES = 5

# Maximum entries kept on disk before old ones are pruned.
MAX_HISTORY_SIZE = 50


@dataclass
class HistoryEntry:
    timestamp: float
    error_summary: str
    command: str
    success: bool
    duration: float
    traceback_snippet: str = ""


@dataclass
class FixHistory:
    """Append-only log of fix attempts, persisted to disk."""

    entries: list[HistoryEntry] = field(default_factory=list)

    # --- persistence --------------------------------------------------------

    @staticmethod
    def _history_path(workspace: Path) -> Path:
        return workspace / ".otorepair" / "history.json"

    @classmethod
    def load(cls, workspace: Path) -> FixHistory:
        path = cls._history_path(workspace)
        if not path.exists():
            debug(f"No history file at {path}", level=2)
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            entries = [HistoryEntry(**e) for e in raw]
            debug(f"Loaded {len(entries)} history entries from {path}", level=2)
            return cls(entries=entries)
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            debug(f"Corrupt history file, starting fresh: {exc}")
            return cls()

    def save(self, workspace: Path) -> None:
        path = self._history_path(workspace)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Prune oldest entries if over limit
        if len(self.entries) > MAX_HISTORY_SIZE:
            self.entries = self.entries[-MAX_HISTORY_SIZE:]
        payload = [asdict(e) for e in self.entries]
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        debug(f"Saved {len(self.entries)} history entries to {path}", level=2)

    # --- recording ----------------------------------------------------------

    def record(
        self,
        *,
        error_summary: str,
        command: str,
        success: bool,
        duration: float,
        traceback_snippet: str = "",
        workspace: Path | None = None,
    ) -> None:
        entry = HistoryEntry(
            timestamp=time.time(),
            error_summary=error_summary,
            command=command,
            success=success,
            duration=duration,
            traceback_snippet=traceback_snippet[:500],
        )
        self.entries.append(entry)
        if workspace is not None:
            self.save(workspace)

    # --- context for prompts ------------------------------------------------

    def format_context(self, current_error: str) -> str:
        """Build a short summary of relevant past fix attempts for the agent.

        Prioritises entries whose error_summary overlaps with *current_error*,
        then falls back to the most recent entries.
        """
        if not self.entries:
            return ""

        # Score each entry: exact match > partial overlap > recency.
        current_lower = current_error.lower()

        def _relevance(entry: HistoryEntry) -> tuple[int, float]:
            summary_lower = entry.error_summary.lower()
            if summary_lower == current_lower:
                return (2, entry.timestamp)
            if current_lower in summary_lower or summary_lower in current_lower:
                return (1, entry.timestamp)
            return (0, entry.timestamp)

        ranked = sorted(self.entries, key=_relevance, reverse=True)
        selected = ranked[:MAX_CONTEXT_ENTRIES]

        lines: list[str] = []
        for e in selected:
            status = "SUCCESS" if e.success else "FAILED"
            lines.append(
                f"- [{status}] {e.error_summary} "
                f"(command: {e.command}, {e.duration:.1f}s)"
            )
            if not e.success and e.traceback_snippet:
                # Show a hint of the traceback for failed attempts
                snippet = e.traceback_snippet.split("\n")[-1].strip()
                if snippet:
                    lines.append(f"  last line: {snippet}")

        header = (
            "Previous fix attempts for this project (most relevant first):\n"
        )
        return header + "\n".join(lines)
