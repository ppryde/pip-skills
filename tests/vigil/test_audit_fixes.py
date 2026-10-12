"""WF-149 audit fixes: bin shim, config-dir transcripts, tail read, titles, snapshot caps."""
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import context as ctx
from scripts import state as st
from scripts.cli import main
from scripts.snapshot import MAX_STATUS_LINES, session_snapshot
from scripts.store import ensure_root

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "vigil"


@pytest.fixture(autouse=True)
def _pin_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))


def _usage_line(tokens):
    return json.dumps({"message": {"usage": {"input_tokens": tokens}}})


class TestBinShim:
    def test_shim_runs_begin_and_context(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        ensure_root(root)
        env = {**os.environ, "HOME": str(tmp_path / "home")}
        for var in ("TMUX", "TMUX_PANE"):
            env.pop(var, None)
        shim = PLUGIN / "bin" / "vigil"
        assert os.access(shim, os.X_OK)
        out = subprocess.run(
            [str(shim), "--root", str(root), "begin"],
            capture_output=True, text=True, env=env, cwd=tmp_path, check=False,
        )
        assert out.returncode == 0 and "vigil active" in out.stdout
        out = subprocess.run(
            [str(shim), "--root", str(root), "context"],
            capture_output=True, text=True, env=env, cwd=tmp_path, check=False,
        )
        assert out.returncode == 0 and out.stdout.startswith("ctx")


class TestConfigDirTranscript:
    def test_config_dir_override(self, tmp_path):
        cwd = tmp_path / "repo"
        cwd.mkdir()
        cfg = tmp_path / "alt"
        proj = cfg / "projects" / ctx.transcript_slug(cwd)
        proj.mkdir(parents=True)
        t = proj / "a.jsonl"
        t.write_text(_usage_line(5) + "\n")
        assert ctx.find_transcript(cwd, tmp_path / "home", cfg) == t
        assert ctx.find_transcript(cwd, tmp_path / "home") is None

    def test_context_cmd_honours_claude_config_dir(self, tmp_path, capsys):
        root = tmp_path / "repo"
        root.mkdir()
        ensure_root(root)
        cfg = tmp_path / "cfg"
        proj = cfg / "projects" / ctx.transcript_slug(root)
        proj.mkdir(parents=True)
        (proj / "a.jsonl").write_text(_usage_line(100000) + "\n")
        assert main(["--root", str(root), "context"]) == 0
        assert "ctx 50%" in capsys.readouterr().out

    def test_hook_transcript_path_wins(self, tmp_path, monkeypatch, capsys):
        root = tmp_path / "repo"
        root.mkdir()
        ensure_root(root)
        st.begin(root)
        cfg = tmp_path / "cfg"
        proj = cfg / "projects" / ctx.transcript_slug(root)
        proj.mkdir(parents=True)
        newer = proj / "newer.jsonl"
        newer.write_text(_usage_line(1000) + "\n")
        mine = tmp_path / "mine.jsonl"
        mine.write_text(_usage_line(150000) + "\n")
        os.utime(mine, (1000, 1000))
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(
            {"cwd": str(root), "transcript_path": str(mine)}
        )))
        assert main(["--root", str(root), "nudge-hook"]) == 0
        assert "75%" in capsys.readouterr().out


class TestTailRead:
    def test_matches_full_scan_on_big_transcript(self, tmp_path):
        t = tmp_path / "t.jsonl"
        lines = [json.dumps({"type": "user", "text": "x" * 500}) for _ in range(2000)]
        lines.insert(1000, _usage_line(1))
        lines.append(_usage_line(4242))
        lines.append("{not json")
        lines.append(json.dumps({"type": "user"}))
        t.write_text("\n".join(lines) + "\n")
        assert ctx.context_tokens(t) == 4242

    def test_usage_beyond_first_chunk_found(self, tmp_path):
        t = tmp_path / "t.jsonl"
        filler = json.dumps({"text": "y" * 1000})
        body = [_usage_line(777)] + [filler] * 300  # > 64KB of tail filler
        t.write_text("\n".join(body) + "\n")
        assert t.stat().st_size > 64 * 1024
        assert ctx.context_tokens(t) == 777

    def test_no_usage_and_missing_file(self, tmp_path):
        t = tmp_path / "t.jsonl"
        t.write_text("junk\n" * 5000)
        assert ctx.context_tokens(t) is None
        assert ctx.context_tokens(tmp_path / "nope.jsonl") is None


class TestTitleSanitising:
    def test_hash_doubled(self):
        assert st._sanitize_title("#{pane_pid}") == "##{pane_pid}"

    def test_control_chars_removed(self):
        assert st._sanitize_title("a\x1b[31mb\x00c") == "a[31mbc"

    def test_leading_dash_preserved(self):
        assert st._sanitize_title("-x foo") == "-x foo"

    def test_cap_never_splits_pair(self):
        out = st._sanitize_title("#" * 100)
        assert out is not None
        assert len(out) <= st.MAX_TITLE_LENGTH
        assert out == "##" * (len(out) // 2)

    def test_stop_hook_passes_double_dash(self):
        assert '-- "$title"' in (PLUGIN / "hooks" / "stop.sh").read_text()


class TestSnapshotBounds:
    def test_status_capped(self, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
        (tmp_path / "base.txt").write_text("x")
        subprocess.run(["git", "add", "base.txt"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
        for i in range(100):
            (tmp_path / f"f{i}.txt").write_text("x")
        snap = session_snapshot(tmp_path)
        assert f"... {100 - MAX_STATUS_LINES} more" in snap
