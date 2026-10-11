import json

from scripts.context import (
    context_line,
    context_percent,
    context_tokens,
    find_transcript,
    transcript_slug,
)


def _write_transcript(path, *usages):
    lines = []
    for u in usages:
        lines.append(json.dumps({
            "type": "assistant",
            "message": {"usage": u},
        }))
    path.write_text("\n".join(lines) + "\n")


class TestSlug:
    def test_non_alnum_becomes_dash(self, tmp_path):
        slug = transcript_slug(tmp_path)
        assert "/" not in slug
        assert set(slug) <= set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-")


class TestFindTranscript:
    def test_none_when_no_project_dir(self, tmp_path):
        assert find_transcript(tmp_path / "repo", tmp_path / "home") is None

    def test_picks_newest_jsonl(self, tmp_path):
        cwd = tmp_path / "repo"
        cwd.mkdir()
        home = tmp_path / "home"
        proj = home / ".claude" / "projects" / transcript_slug(cwd)
        proj.mkdir(parents=True)
        old = proj / "old.jsonl"
        new = proj / "new.jsonl"
        old.write_text("{}\n")
        new.write_text("{}\n")
        import os
        os.utime(old, (1000, 1000))
        os.utime(new, (2000, 2000))
        assert find_transcript(cwd, home) == new


class TestContextTokens:
    def test_sums_last_usage(self, tmp_path):
        t = tmp_path / "t.jsonl"
        _write_transcript(
            t,
            {"input_tokens": 10, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
            {"input_tokens": 5, "cache_read_input_tokens": 40000,
             "cache_creation_input_tokens": 1000},
        )
        assert context_tokens(t) == 41005

    def test_none_when_no_usage(self, tmp_path):
        t = tmp_path / "t.jsonl"
        t.write_text('{"type":"user"}\n')
        assert context_tokens(t) is None

    def test_none_when_missing_file(self, tmp_path):
        assert context_tokens(tmp_path / "nope.jsonl") is None

    def test_skips_malformed_lines(self, tmp_path):
        t = tmp_path / "t.jsonl"
        t.write_text(
            'not json\n'
            + json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 100}}})
            + "\n"
        )
        assert context_tokens(t) == 100

    def test_none_when_usage_field_non_numeric(self, tmp_path):
        t = tmp_path / "t.jsonl"
        t.write_text(
            '{"type":"assistant","message":{"usage":{"input_tokens":"abc"}}}\n'
        )
        assert context_tokens(t) is None


class TestPercentAndLine:
    def test_percent(self):
        assert context_percent(70000, 200000) == 35

    def test_line_under_threshold_hides_note(self):
        assert context_line(20, 35) == "ctx 20%"

    def test_line_over_threshold_shows_note(self):
        line = context_line(40, 35)
        assert line.startswith("ctx 40%")
        assert "35%" in line

    def test_line_unknown(self):
        assert context_line(None, 35) == "ctx unknown"


class TestWindowDetection:
    """VG-4: the transcript fallback detects the window; 200k only when unknown."""

    @staticmethod
    def _line(tokens, model=None):
        message = {"usage": {"input_tokens": tokens}}
        if model:
            message["model"] = model
        return json.dumps({"message": message})

    def test_unknown_window_defaults_to_200k(self):
        from scripts.context import detect_window
        assert detect_window(100000, [None, "claude-opus-4"]) == 200000

    def test_one_m_suffix_on_payload_model(self):
        from scripts.context import detect_window
        assert detect_window(100000, ["claude-opus-4[1m]", None]) == 1_000_000

    def test_one_m_suffix_on_transcript_model(self):
        from scripts.context import detect_window
        assert detect_window(100000, [None, "claude-sonnet[1M]"]) == 1_000_000

    def test_usage_over_200k_proves_extended_window(self):
        from scripts.context import detect_window
        assert detect_window(350000, [None]) == 1_000_000

    def test_explicit_config_wins(self):
        from scripts.context import detect_window
        assert detect_window(350000, ["x[1m]"], configured=400000) == 400000

    def test_payload_model_id_forms(self):
        from scripts.context import payload_model_id
        assert payload_model_id({"model": "m[1m]"}) == "m[1m]"
        assert payload_model_id({"model": {"id": "m"}}) == "m"
        assert payload_model_id({"model": 3}) is None

    def test_context_reading_returns_model(self, tmp_path):
        from scripts.context import context_reading
        t = tmp_path / "t.jsonl"
        t.write_text(self._line(10, "old") + "\n" + self._line(20, "claude-x[1m]") + "\n")
        assert context_reading(t) == (20, "claude-x[1m]")

    def test_cli_1m_session_not_over_100_percent(self, repo, tmp_path, monkeypatch, capsys):
        # 300k tokens used on a 1M window is 30%, not the 150% a flat 200k gives.
        from scripts.cli import main
        from scripts.config import set_config
        set_config(repo, "context.threshold", "10")
        t = tmp_path / "t.jsonl"
        t.write_text(self._line(300000, "claude-opus[1m]") + "\n")
        monkeypatch.setenv("CENSUS_CLI", str(tmp_path / "no-such-census"))
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(
            {"cwd": str(repo), "transcript_path": str(t), "hook_event_name": "UserPromptSubmit"})))
        from scripts import state as st
        st.begin(repo)
        assert main(["--root", str(repo), "nudge-hook"]) == 0
        out = capsys.readouterr().out
        assert "30%" in out and "150%" not in out

    def test_cli_unknown_window_below_200k_uses_200k(self, repo, tmp_path, monkeypatch, capsys):
        from scripts.cli import main
        t = tmp_path / "t.jsonl"
        t.write_text(self._line(100000) + "\n")
        monkeypatch.setenv("CENSUS_CLI", str(tmp_path / "no-such-census"))
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(
            {"cwd": str(repo), "transcript_path": str(t)})))
        from scripts import state as st
        st.begin(repo)
        assert main(["--root", str(repo), "nudge-hook"]) == 0
        assert "50%" in capsys.readouterr().out

    def test_cli_explicit_window_config_is_honoured(self, repo, tmp_path, monkeypatch, capsys):
        from scripts.cli import main
        from scripts.config import set_config
        set_config(repo, "context.window", "400000")
        set_config(repo, "context.threshold", "10")
        t = tmp_path / "t.jsonl"
        t.write_text(self._line(100000, "m[1m]") + "\n")
        monkeypatch.setenv("CENSUS_CLI", str(tmp_path / "no-such-census"))
        monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(
            {"cwd": str(repo), "transcript_path": str(t)})))
        from scripts import state as st
        st.begin(repo)
        assert main(["--root", str(repo), "nudge-hook"]) == 0
        assert "25%" in capsys.readouterr().out
