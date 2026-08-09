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
