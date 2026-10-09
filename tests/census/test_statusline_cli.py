"""`census statusline`: ingest, then draw, in one process."""
import io
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts import cli
from scripts import store as st

CLI = Path(__file__).resolve().parents[2] / "plugins" / "census" / "scripts" / "cli.py"
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def payload(**over):
    base = {
        "session_id": "s1",
        "cwd": "/definitely/not/a/repo/here",
        "model": {"display_name": "Opus 5.5"},
        "context_window": {"used_percentage": 42},
        "cost": {"total_cost_usd": 3.1, "total_duration_ms": 7_200_000},
    }
    base.update(over)
    return base


@pytest.fixture
def run(store_file, monkeypatch, capsysbinary):
    """Run `statusline` in-process on a payload; returns the plain-text output."""
    monkeypatch.setenv("CENSUS_STATUSLINE_COLOR", "never")

    def _run(raw, *argv):
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw.encode() if isinstance(raw, str) else raw)))
        assert cli.main(["statusline", *argv]) == 0
        return capsysbinary.readouterr().out.decode("utf-8")

    return _run


def test_ingests_then_draws(run):
    out = run(json.dumps(payload()))
    assert out.startswith("🧠 ••••ᗧ••••• 42%")
    assert st.for_session("s1")["payload"]["model"]["display_name"] == "Opus 5.5"


def test_output_is_two_lines_with_a_trailing_newline(run):
    out = run(json.dumps(payload()))
    assert out.endswith("\n") and len(out.rstrip("\n").split("\n")) == 2


def test_limits_come_from_the_store_even_when_the_payload_has_none(run):
    resets = time.time() + 3 * 3600
    run(json.dumps(payload(rate_limits={"five_hour": {"used_percentage": 23, "resets_at": resets}})))
    out = run(json.dumps(payload()))
    assert "⏳" in out and "23%" in out


def test_garbage_stdin_prints_the_fallback_not_a_traceback(run):
    assert run("{not json") == "🤖 Claude\n"


def test_empty_stdin_prints_the_fallback(run):
    assert run("") == "🤖 Claude\n"


def test_non_object_payload_prints_the_fallback(run):
    assert run("[1, 2]") == "🤖 Claude\n"


def test_ingest_failure_does_not_stop_the_draw(run, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("store on fire")

    monkeypatch.setattr(cli.st, "ingest", boom)
    # ingest quarantines itself; even if it did not, cmd_statusline must still draw
    try:
        out = run(json.dumps(payload()))
    except RuntimeError:
        pytest.fail("ingest failure escaped")
    assert "🧠" in out


def test_draw_failure_does_not_undo_the_ingest(run, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("drawer on fire")

    monkeypatch.setattr(cli.rd, "statusline", boom)
    assert run(json.dumps(payload())) == "🤖 Opus 5.5\n"
    assert st.for_session("s1") is not None


def test_pointer_is_published(run):
    run(json.dumps(payload()))
    assert st.pointer_path().exists()


def test_unicode_survives_a_cp1252_console(store_file, monkeypatch):
    """stdin and stdout both claim cp1252; the bytes on the wire are still UTF-8."""
    stdin = io.TextIOWrapper(io.BytesIO(json.dumps(payload(model={"display_name": "Opus ✨"})).encode("utf-8")), encoding="cp1252")
    sink = io.BytesIO()
    stdout = io.TextIOWrapper(sink, encoding="cp1252")
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setenv("CENSUS_STATUSLINE_COLOR", "never")
    assert cli.main(["statusline"]) == 0
    stdout.flush()
    assert "Opus ✨" in sink.getvalue().decode("utf-8")
    assert st.for_session("s1")["payload"]["model"]["display_name"] == "Opus ✨"


class TestSideChannel:
    def test_off_when_unset(self, run, tmp_path):
        run(json.dumps(payload()))
        assert not (tmp_path / "side").exists()

    def test_writes_the_raw_payload_by_session_id(self, run, tmp_path, monkeypatch):
        side = tmp_path / "side"
        monkeypatch.setenv("AGENT_UI_STATUSLINE_CACHE", str(side))
        raw = json.dumps(payload())
        run(raw)
        assert (side / "s1.json").read_text() == raw
        assert [p.name for p in side.iterdir()] == ["s1.json"]  # no temp file left behind

    def test_unsafe_session_id_is_not_written(self, run, tmp_path, monkeypatch):
        side = tmp_path / "side"
        monkeypatch.setenv("AGENT_UI_STATUSLINE_CACHE", str(side))
        run(json.dumps(payload(session_id="../escape")))
        assert not any(side.rglob("*.json")) and not (tmp_path / "escape.json").exists()

    def test_unwritable_directory_never_breaks_the_line(self, run, tmp_path, monkeypatch):
        blocker = tmp_path / "file"
        blocker.write_text("x")
        monkeypatch.setenv("AGENT_UI_STATUSLINE_CACHE", str(blocker / "sub"))
        assert "🧠" in run(json.dumps(payload()))


class TestPreview:
    def test_preview_uses_the_live_limits_and_records_nothing(self, store_file, monkeypatch, capsysbinary):
        monkeypatch.setenv("CENSUS_STATUSLINE_COLOR", "never")
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"")))
        resets = time.time() + 3600
        st.ingest(json.dumps(payload(rate_limits={"seven_day": {"used_percentage": 9, "resets_at": resets}})))
        before = sorted(p.name for p in st.census_dir().rglob("*") if "gitcache" not in str(p))
        assert cli.main(["statusline", "--preview"]) == 0
        out = capsysbinary.readouterr().out.decode()
        assert "📅" in out and "Opus 5.5" in out and "💸" in out
        assert sorted(p.name for p in st.census_dir().rglob("*") if "gitcache" not in str(p)) == before


def test_real_process_end_to_end(tmp_path):
    """The shipped entry point, as Claude Code runs it, with a pinned environment."""
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "USERPROFILE": str(tmp_path / "home"),
        "CLAUDE_CONFIG_DIR": str(tmp_path / "cfg"),
        "CENSUS_STORE": str(tmp_path / "store"),
        "AGENT_UI_STATUSLINE_CACHE": str(tmp_path / "side"),
        "CENSUS_STATUSLINE_COLOR": "never",
    }
    env.pop("NO_COLOR", None)
    done = subprocess.run(
        [sys.executable, str(CLI), "statusline"],
        input=json.dumps(payload()).encode(),
        capture_output=True,
        env=env,
        timeout=20,
    )
    assert done.returncode == 0 and not done.stderr
    text = ANSI.sub("", done.stdout.decode("utf-8"))
    assert text.startswith("🧠") and "🦾 Opus 5.5" in text
    assert (tmp_path / "store" / "sessions" / "s1.json").exists()
    assert (tmp_path / "side" / "s1.json").exists()


def test_side_channel_failure_in_the_cli_never_escapes(run, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setenv("AGENT_UI_STATUSLINE_CACHE", "/nonexistent-side")
    monkeypatch.setattr(cli.rd, "write_side_channel", boom)
    assert "🧠" in run(json.dumps(payload()))


def test_closed_stdout_is_not_a_traceback(store_file, monkeypatch):
    class Dead:
        buffer = None

        def write(self, *_):
            raise BrokenPipeError

        def flush(self):
            raise BrokenPipeError

        def fileno(self):
            raise OSError

    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(payload()).encode())))
    monkeypatch.setattr(sys, "stdout", Dead())
    assert cli.main(["statusline"]) == 0


def _boom_read():
    raise ValueError("x")


def test_anything_unexpected_still_exits_zero_with_a_line(run, monkeypatch):
    monkeypatch.setattr(cli, "_read_stdin", _boom_read)
    assert run("") == "🤖 Claude\n"


def test_ingest_decodes_utf8_whatever_the_console_code_page(store_file, monkeypatch):
    raw = json.dumps(payload(model={"display_name": "Opus ✨"})).encode("utf-8")
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw), encoding="cp1252"))
    assert cli.main(["ingest"]) == 0
    assert st.for_session("s1")["payload"]["model"]["display_name"] == "Opus ✨"


def test_install_statusline_alias_keeps_crlf_and_odd_bytes(tmp_path, monkeypatch):
    script = tmp_path / "s.sh"
    original = b"#!/bin/bash\r\ninput=$(cat)\r\n# caf\xe9\r\n"
    script.write_bytes(original)
    assert cli.main(["install-statusline", "--path", str(script)]) == 0
    assert b"# caf\xe9\r\n" in script.read_bytes() and b"census ingest" in script.read_bytes()
    assert cli.main(["install-statusline", "--path", str(script), "--uninstall"]) == 0
    assert script.read_bytes() == original
