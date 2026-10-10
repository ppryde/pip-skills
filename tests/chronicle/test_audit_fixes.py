"""Regression tests for the WF-143 audit fixes: hostile remote paths, unicode
line separators, dry-run dedupe, `open` URL checks, cost-state redaction,
the artifact-result lookup and the Python version guard."""
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

import pytest

from scripts import chrome_profile, cli, ingest, redact, store, volumes
from scripts import remote as remote_mod
from scripts.remote import SSHResult
from scripts.transcript import fold

from .conftest import _assistant, _user

T0 = "2026-09-01T10:00:00.000Z"
T1 = "2026-09-01T10:01:00.000Z"


# --- CH-1 / CH-16: remote file frames ---------------------------------------

@pytest.fixture
def mirror(tmp_path: Path) -> Path:
    root = tmp_path / "mirror"
    (root / "projects").mkdir(parents=True)
    return root


class TestRemoteFramePaths:
    @pytest.mark.parametrize("bad", [
        "../../../escaped.txt", "/etc/passwd", "a/../../b.jsonl", "-repo/../../x.jsonl",
        "-repo/s1.txt", 7, None, "",
    ])
    def test_file_frames_with_hostile_paths_are_refused(self, mirror, tmp_path, bad):
        state = {"files": {}, "meta": {}}
        frame = {"file": bad, "lines": ["{}"], "to_offset": 3, "truncated": True}
        with pytest.raises(ValueError):
            remote_mod._append_file_frame(mirror, state, frame)
        assert state["files"] == {}
        assert not (tmp_path / "escaped.txt").exists()

    @pytest.mark.parametrize("bad", ["../../x.meta.json", "/abs/x.meta.json", "-repo/x.jsonl.tmp"])
    def test_meta_frames_with_hostile_paths_are_refused(self, mirror, bad):
        state = {"files": {}, "meta": {}}
        with pytest.raises(ValueError):
            remote_mod._apply_meta_frame(mirror, state, {"file": bad, "content": "x"}, 1)
        assert state["meta"] == {}

    def test_a_hostile_truncated_frame_unlinks_nothing_outside_the_mirror(self, mirror, tmp_path):
        victim = tmp_path / "victim.jsonl"
        victim.write_text("keep me")
        frame = {"file": "../../victim.jsonl", "lines": [], "to_offset": 0, "truncated": True}
        with pytest.raises(ValueError):
            remote_mod._append_file_frame(mirror, {"files": {}, "meta": {}}, frame)
        assert victim.read_text() == "keep me"

    @pytest.mark.parametrize("frame", [
        {"file": "-repo/s1.jsonl", "lines": ["{}"], "to_offset": True},
        {"file": "-repo/s1.jsonl", "lines": ["{}"], "to_offset": -1},
        {"file": "-repo/s1.jsonl", "lines": "abc", "to_offset": 3},
        {"file": "-repo/s1.jsonl", "lines": [1], "to_offset": 3},
    ])
    def test_malformed_offsets_and_lines_are_refused(self, mirror, frame):
        with pytest.raises(ValueError):
            remote_mod._append_file_frame(mirror, {"files": {}, "meta": {}}, frame)

    def test_a_hostile_frame_is_reported_as_a_garbled_response(self, tmp_path):
        remote = store.normalise_remote(
            "prod1", "prod1.example", claude_dir=str(tmp_path / "box"),
            mirror_dir=str(tmp_path / "mirror2"))
        frames = [{"t": "file", "file": "../../../escaped.txt", "lines": ["x"], "to_offset": 2},
                  {"t": "done", "partial": False}]
        out = "".join(json.dumps(f) + "\n" for f in frames).encode()

        def transport(argv, stdin, timeout):
            return SSHResult(0, out, b"")

        result = remote_mod._pull_once(remote, transport=transport,
                                       state={"files": {}, "meta": {}})
        assert result.ok is False
        assert "garbled response" in (result.error or "")
        assert not (tmp_path / "escaped.txt").exists()

    def test_good_frames_still_write_and_meta_round_trips(self, mirror):
        state = {"files": {}, "meta": {}}
        rel = "-repo/s1.jsonl"
        remote_mod._append_file_frame(
            mirror, state, {"file": rel, "lines": ["{}", "{}"], "to_offset": 6})
        assert (mirror / "projects" / rel).read_text() == "{}\n{}\n"
        assert state["files"][rel] == {"offset": 6, "mirror_bytes": 6}
        meta = "-repo/s1/subagents/agent-ab12.meta.json"
        remote_mod._apply_meta_frame(mirror, state, {"file": meta, "content": '{"a":1}'}, 7)
        assert (mirror / "projects" / meta).read_text() == '{"a":1}'
        assert not list((mirror / "projects").rglob("*.tmp"))

    def test_meta_writes_do_not_leak_file_descriptors(self, mirror):
        if not os.path.isdir("/dev/fd"):
            pytest.skip("no /dev/fd")
        state = {"files": {}, "meta": {}}
        meta = "-repo/s1/subagents/agent-ab12.meta.json"
        before = len(os.listdir("/dev/fd"))
        for _ in range(50):
            remote_mod._apply_meta_frame(mirror, state, {"file": meta, "content": "{}"}, 2)
        assert len(os.listdir("/dev/fd")) <= before + 1


# --- CH-3: unicode line separators ------------------------------------------

class TestLineSplitting:
    def test_only_newline_cuts_a_line(self):
        chunk = 'a b\u0085c d\n"e"\nrest'.encode()
        lines, off = ingest._complete_lines(chunk, 10)
        assert lines == ['a b\u0085c d', '"e"']
        assert off == 10 + len('a b\u0085c d\n"e"\n'.encode())

    def test_interior_empty_lines_are_kept_like_splitlines(self):
        assert ingest._complete_lines(b"a\n\nb\n", 0) == (["a", "", "b"], 5)

    def test_no_newline_yields_nothing(self):
        assert ingest._complete_lines(b"partial", 4) == ([], 4)

    def test_a_record_with_raw_u2028_and_u0085_is_ingested(self, builder):
        path = (builder.prompt("u1", T0).turn("m1", T0).turn("m2", T1).turn("m3", T1)
                .write())
        text = path.read_text()
        assert "thinking..." in text
        path.write_text(text.replace("thinking...", "x y\u0085z w"), encoding="utf-8")
        conn = store.connect()
        ingest.ingest_session(conn, path)
        row = conn.execute("SELECT turns FROM sessions WHERE session_id = 's1'").fetchone()
        assert row["turns"] == 3


# --- CH-9: artifact result lookup -------------------------------------------

class TestArtifactResults:
    def _artifact(self, mid, tool_id):
        return _assistant(mid, ts=T0, blocks=[{"type": "tool_use", "id": tool_id, "name": "Artifact",
                                               "input": {"file_path": "/x.html", "title": mid}}])

    def test_results_find_their_turn_among_many(self):
        url = "https://claude.ai/code/artifact/f7ec8e3d-b032-4432-94a1-c81758132da3"
        recs = [json.dumps(_assistant(f"filler{i}", ts=T0)) for i in range(300)]
        recs.append(json.dumps(self._artifact("mA", "a1")))
        recs.append(json.dumps(self._artifact("mB", "a2")))
        recs.append(json.dumps(_user("r1", ts=T1, toolUseResult={}, content=[
            {"type": "tool_result", "tool_use_id": "a1", "content": f"Published at {url}"}])))
        recs.append(json.dumps(_user("r2", ts=T1, toolUseResult={}, content=[
            {"type": "tool_result", "tool_use_id": "a2", "content": "boom", "is_error": True}])))
        facts = fold(recs)
        assert facts.turns[("", "mA")].artifacts["a1"].url == url
        assert "a2" not in facts.turns[("", "mB")].artifacts


# --- RC-1: dedupe dry run is read only --------------------------------------

class TestDedupeDryRun:
    def test_dry_run_on_a_missing_store_creates_nothing(self, capsys):
        assert not store.db_path().exists()
        assert cli.main(["dedupe"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["applied"] is False and out["groups"] == 0 and out["rows_removed"] == 0
        assert not store.db_path().exists()

    def test_dry_run_on_a_populated_store_matches_and_writes_nothing(self, builder, capsys):
        conn = store.connect()
        ingest.ingest_session(conn, builder.prompt("u1", T0).turn("m1", T0).write())
        conn.close()
        before = store.db_path().read_bytes()
        assert cli.main(["dedupe"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["applied"] is False and out["groups"] == 0
        assert store.db_path().read_bytes() == before

    def test_apply_still_creates_the_store(self, capsys):
        assert cli.main(["dedupe", "--apply"]) == 0
        assert json.loads(capsys.readouterr().out)["applied"] is True
        assert store.db_path().exists()


# --- RC-3: the UTC daily query documented in queries.md ----------------------

def test_the_documented_utc_daily_query_runs(builder):
    from scripts import report
    conn = store.connect()
    ingest.ingest_session(conn, builder.prompt("u1", T0).turn("m1", T0).write())
    utc = report._costs_by(conn, "date(t.ts,'unixepoch')", " WHERE t.ts >= ?", [0],
                           extra="t.ts IS NOT NULL")
    assert list(utc) == ["2026-09-01"]
    assert utc["2026-09-01"]["cost_usd"] > 0


# --- CH-8: open refuses non-https / dash URLs --------------------------------

class TestOpenUrl:
    @pytest.mark.parametrize("url", [
        "--renderer-cmd-prefix=x", "javascript:alert(1)", "file:///etc/passwd",
        "http://claude.ai/x", "https://", "https://a b", "-https://x", "",
    ])
    def test_hostile_urls_are_refused_before_anything_runs(self, url, monkeypatch, capsys):
        def boom(*a, **k):
            raise AssertionError("open must not run")
        monkeypatch.setattr("scripts.cli.subprocess.run", boom)
        assert cli.main(["open", "--", url]) == 2
        assert "error" in json.loads(capsys.readouterr().err)

    def test_a_normal_https_url_is_accepted_and_the_argv_is_unchanged(self):
        url = "https://claude.ai/code/artifact/abc"
        chrome_profile.check_url(url)
        assert chrome_profile.open_command(url, "Profile 1") == [
            "open", "-na", "Google Chrome", "--args", "--profile-directory=Profile 1", url]


# --- CH-12: cost-state redaction ---------------------------------------------

class TestCostStateRedaction:
    REAL: ClassVar[dict] = {"type": "cost-state", "totalCostUSD": 1.5, "startTime": 1700000000,
            "modelUsage": {"claude-opus-5": {"inputTokens": 10, "costUSD": 0.5,
                                             "webSearchRequests": 0}}}

    @pytest.mark.parametrize("fidelity", list(redact.FIDELITIES))
    def test_real_shaped_records_are_unchanged(self, fidelity):
        assert redact.slim(dict(self.REAL), fidelity) == self.REAL

    @pytest.mark.parametrize("fidelity", list(redact.FIDELITIES))
    def test_strings_hidden_in_cost_fields_are_dropped(self, fidelity):
        rec = {"type": "cost-state", "totalCostUSD": "secret", "startTime": True,
               "modelUsage": {"m": {"costUSD": 1, "note": "secret prompt text"},
                              "leak": "secret"}}
        out = redact.slim(rec, fidelity)
        assert "totalCostUSD" not in out and "startTime" not in out
        assert out["modelUsage"] == {"m": {"costUSD": 1}}
        assert "secret" not in json.dumps(out)


# --- CH-7: Python version guard ----------------------------------------------

def test_cli_guard_exits_2_with_a_json_error_on_old_python():
    script = (
        "import sys, runpy\n"
        "sys.version_info = (3, 8, 0, 'final', 0)\n"
        f"runpy.run_path({str(Path(cli.__file__))!r}, run_name='not_main')\n"
    )
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, check=False)
    assert proc.returncode == 2
    assert "Python >= 3.10" in json.loads(proc.stderr.strip().splitlines()[-1])["error"]


# --- pin: docker image --------------------------------------------------------

def test_the_default_docker_image_is_an_exact_tag():
    assert volumes.DEFAULT_IMAGE == "alpine:3.20.3"
    assert cli.build_parser().parse_args(
        ["pull-volume", "--volume", "wf", "--dest", "/tmp/x"]).image == "alpine:3.20.3"
