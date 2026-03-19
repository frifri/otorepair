"""Tests for otorepair.backends — CLI selection and argv builders."""

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from otorepair.backends import (
    ClaudeBackend,
    CursorBackend,
    check_cursor_cli_authenticated,
    get_backend,
    resolve_backend_id,
    resolve_workspace,
)


class TestResolveBackendId:
    def test_cli_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("OTOREPAIR_BACKEND", "cursor")
        bid, err = resolve_backend_id("claude")
        assert err is None
        assert bid == "claude"

    def test_env_cursor_when_cli_unset(self, monkeypatch):
        monkeypatch.setenv("OTOREPAIR_BACKEND", "cursor")
        bid, err = resolve_backend_id(None)
        assert err is None
        assert bid == "cursor"

    def test_env_claude_explicit(self, monkeypatch):
        monkeypatch.setenv("OTOREPAIR_BACKEND", "claude")
        bid, err = resolve_backend_id(None)
        assert err is None
        assert bid == "claude"

    def test_default_claude_when_unset(self, monkeypatch):
        monkeypatch.delenv("OTOREPAIR_BACKEND", raising=False)
        bid, err = resolve_backend_id(None)
        assert err is None
        assert bid == "claude"

    def test_env_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("OTOREPAIR_BACKEND", "CuRsOr")
        bid, err = resolve_backend_id(None)
        assert err is None
        assert bid == "cursor"

    def test_invalid_env_returns_error(self, monkeypatch):
        monkeypatch.setenv("OTOREPAIR_BACKEND", "vim")
        bid, err = resolve_backend_id(None)
        assert bid is None
        assert err is not None
        assert "vim" in err


class TestClaudeBackend:
    def test_executable(self):
        assert ClaudeBackend().executable == "claude"

    def test_session_summary_lines(self, tmp_path: Path):
        ws = tmp_path / "proj"
        ws.mkdir()
        lines = ClaudeBackend().session_summary_lines(
            workdir=ws.resolve(),
            agent_executable_path="/usr/bin/claude",
        )
        text = "\n".join(lines)
        assert "Claude Code" in text
        assert "/usr/bin/claude" in text
        assert str(ws.resolve()) not in text  # no workspace/cwd line for Claude
        assert "haiku" in text
        assert "default" in text.lower()

    def test_triage_argv(self):
        assert ClaudeBackend().triage_argv() == [
            "claude",
            "-p",
            "--model",
            "haiku",
        ]

    def test_fix_argv(self):
        assert ClaudeBackend().fix_argv() == [
            "claude",
            "-p",
            "--allowedTools",
            "Edit,Read,Write,Bash,Glob,Grep",
        ]


class TestCursorBackend:
    def test_executable(self):
        assert CursorBackend().executable == "agent"

    def test_fix_argv_includes_force_trust_workspace(self, tmp_path: Path):
        ws = tmp_path / "proj"
        ws.mkdir()
        argv = CursorBackend(workspace=ws).fix_argv()
        assert argv[0] == "agent"
        assert "-p" in argv
        assert "--force" in argv
        assert "--trust" in argv
        idx = argv.index("--workspace")
        assert argv[idx + 1] == str(ws.resolve())
        assert "--output-format" in argv
        assert argv[argv.index("--output-format") + 1] == "stream-json"
        assert "--stream-partial-output" in argv

    def test_fix_uses_stream_json_flag(self, tmp_path: Path):
        ws = tmp_path / "p"
        ws.mkdir()
        assert CursorBackend(workspace=ws).fix_uses_stream_json_stdout() is True

    def test_session_summary_lines_default_triage_model(self, tmp_path: Path):
        ws = tmp_path / "proj"
        ws.mkdir()
        lines = CursorBackend(workspace=ws).session_summary_lines(
            workdir=ws.resolve(),
            agent_executable_path="/bin/agent",
        )
        text = "\n".join(lines)
        assert "Cursor" in text
        assert "/bin/agent" in text
        assert str(ws.resolve()) in text
        assert "agent --workspace" in text  # Cursor-specific flag; path is also cwd
        assert "Cursor CLI default" in text

    def test_session_summary_lines_custom_triage_model(
        self, monkeypatch, tmp_path: Path
    ):
        monkeypatch.setenv("OTOREPAIR_CURSOR_TRIAGE_MODEL", "gpt-4o-mini")
        ws = tmp_path / "w"
        ws.mkdir()
        lines = CursorBackend(workspace=ws).session_summary_lines(
            workdir=ws.resolve(),
        )
        assert any("gpt-4o-mini" in ln for ln in lines)

    def test_triage_argv_no_model_by_default(self, tmp_path: Path):
        ws = tmp_path / "proj"
        ws.mkdir()
        argv = CursorBackend(workspace=ws).triage_argv()
        assert argv[0] == "agent"
        assert "--force" not in argv
        assert "--trust" in argv
        assert "--workspace" in argv

    def test_triage_argv_model_from_env(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("OTOREPAIR_CURSOR_TRIAGE_MODEL", "cheap-model")
        ws = tmp_path / "proj"
        ws.mkdir()
        argv = CursorBackend(workspace=ws).triage_argv()
        assert "--model" in argv
        assert argv[argv.index("--model") + 1] == "cheap-model"


class TestCheckCursorCliAuthenticated:
    def test_api_key_skips_agent_status(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("CURSOR_API_KEY", "sk-test")
        ok, msg = check_cursor_cli_authenticated(tmp_path)
        assert ok is True
        assert msg == ""

    def test_status_success_without_api_key(self, monkeypatch, tmp_path: Path):
        monkeypatch.delenv("CURSOR_API_KEY", raising=False)
        fake = CompletedProcess(
            args=["agent", "status"],
            returncode=0,
            stdout="ok",
            stderr="",
        )
        with patch("otorepair.backends.subprocess.run", return_value=fake) as run:
            ok, msg = check_cursor_cli_authenticated(
                tmp_path, agent_bin="/bin/agent"
            )
        assert ok is True
        assert msg == ""
        run.assert_called_once()
        assert run.call_args[0][0] == ["/bin/agent", "status"]

    def test_status_failure_message(self, monkeypatch, tmp_path: Path):
        monkeypatch.delenv("CURSOR_API_KEY", raising=False)
        fake = CompletedProcess(
            args=["agent", "status"],
            returncode=1,
            stdout="",
            stderr="please login",
        )
        with patch("otorepair.backends.subprocess.run", return_value=fake):
            ok, msg = check_cursor_cli_authenticated(tmp_path)
        assert ok is False
        assert "authenticated" in msg.lower() or "login" in msg.lower()
        assert "please login" in msg


class TestResolveWorkspace:
    def test_default_is_cwd(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("OTOREPAIR_WORKSPACE", raising=False)
        ws, err = resolve_workspace(None)
        assert err is None
        assert ws == tmp_path.resolve()

    def test_cli_overrides_env(self, monkeypatch, tmp_path):
        env_dir = tmp_path / "from_env"
        cli_dir = tmp_path / "from_cli"
        env_dir.mkdir()
        cli_dir.mkdir()
        monkeypatch.setenv("OTOREPAIR_WORKSPACE", str(env_dir))
        ws, err = resolve_workspace(str(cli_dir))
        assert err is None
        assert ws == cli_dir.resolve()

    def test_env_when_cli_unset(self, monkeypatch, tmp_path):
        d = tmp_path / "w"
        d.mkdir()
        monkeypatch.setenv("OTOREPAIR_WORKSPACE", str(d))
        ws, err = resolve_workspace(None)
        assert err is None
        assert ws == d.resolve()

    def test_missing_path_errors(self, tmp_path):
        missing = tmp_path / "nope"
        ws, err = resolve_workspace(str(missing))
        assert ws is None
        assert err is not None
        assert "does not exist" in err

    def test_file_not_directory_errors(self, tmp_path):
        f = tmp_path / "file"
        f.write_text("x")
        ws, err = resolve_workspace(str(f))
        assert ws is None
        assert err is not None
        assert "not a directory" in err


class TestGetBackend:
    def test_claude(self):
        assert isinstance(get_backend("claude"), ClaudeBackend)

    def test_cursor(self, tmp_path: Path):
        b = get_backend("cursor", workspace=tmp_path)
        assert isinstance(b, CursorBackend)
