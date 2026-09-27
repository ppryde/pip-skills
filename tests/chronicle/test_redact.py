"""`redact.slim`: what each fidelity keeps and loses, measured by ingesting the
same transcript twice — once as written, once redacted — and comparing what
chronicle derives. Plus the leak guarantee: no sentinel planted in content
survives at `minimal` or `attribution`."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from scripts import redact, store

from .remote_support import (
    SECRET,
    ingest_into,
    snapshot,
    write_remote_tree,
)

SCRIPTS = Path(__file__).resolve().parents[2] / "plugins" / "chronicle" / "scripts"

# Tables every fidelity must reproduce exactly.
ALWAYS = ["turns", "tool_calls", "events", "sessions"]
ATTRIBUTION = ["attribution", "qualifiers", "result_chars", "file_edits", "artifacts",
               "limit_hits", "churn", "cost"]


def redact_tree(src: Path, dst: Path, fidelity: str) -> Path:
    """What the remote agent does to every transcript, minus the transport."""
    for path in (src / "projects").rglob("*"):
        if not path.is_file():
            continue
        target = dst / "projects" / path.relative_to(src / "projects")
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.name.endswith(".meta.json"):
            slimmed = redact.slim_meta(path.read_text(), fidelity)
            if slimmed is not None:
                target.write_text(slimmed)
            continue
        lines = (redact.slim_line(raw, fidelity) for raw in path.read_bytes().split(b"\n"))
        target.write_text("".join(line + "\n" for line in lines if line is not None))
    account = src / ".claude.json"
    if account.exists():
        (dst / ".claude.json").write_text(json.dumps(
            {"oauthAccount": store.parse_account_profile(account.read_text())}))
    return dst


@pytest.fixture
def both(tmp_path: Path):
    """Snapshots of the fixture ingested as written, and redacted at each level."""
    src = write_remote_tree(tmp_path / "remote")
    original = ingest_into(src / "projects", tmp_path / "original.db")
    out = {"original": snapshot(original)}
    for fidelity in redact.FIDELITIES:
        dst = redact_tree(src, tmp_path / f"red-{fidelity}", fidelity)
        out[fidelity] = snapshot(ingest_into(dst / "projects", tmp_path / f"{fidelity}.db"))
    out["_dirs"] = {f: tmp_path / f"red-{f}" for f in redact.FIDELITIES}
    return out


class TestEqualities:
    @pytest.mark.parametrize("fidelity", redact.FIDELITIES)
    @pytest.mark.parametrize("table", ALWAYS)
    def test_every_level_reproduces_turns_tokens_tools_events(self, both, fidelity, table):
        assert both[fidelity][table] == both["original"][table]

    def test_minimal_cost_is_identical(self, both):
        assert both["minimal"]["cost"] == both["original"]["cost"]
        assert both["original"]["cost"][0][1] not in (None, 0)

    @pytest.mark.parametrize("fidelity", ["attribution", "titles"])
    @pytest.mark.parametrize("table", ATTRIBUTION)
    def test_attribution_level_restores_the_attribution_tables(self, both, fidelity, table):
        assert both[fidelity][table] == both["original"][table]
        assert both["original"][table]      # the fixture really exercises it

    def test_titles_level_restores_titles_and_short_agent_tasks(self, both):
        assert both["titles"]["titles"] == both["original"]["titles"]
        assert both["original"]["titles"][0][1] == f"Fix the {SECRET} bug"
        (_, _, task, _), = both["titles"]["agents"]
        (_, _, original_task, _), = both["original"]["agents"]
        assert task == original_task[:redact.SHORT_CHARS].rstrip()
        assert 0 < len(task) <= redact.SHORT_CHARS


class TestDocumentedLosses:
    def test_minimal_loses_exactly_what_the_docs_say(self, both):
        lost = both["minimal"]
        original = both["original"]
        assert all(row[3:] == (None,) * 6 for row in lost["attribution"])      # effort, skill, ...
        assert any(row[3:] != (None,) * 6 for row in original["attribution"])
        assert all(q is None for _, q in lost["qualifiers"])                   # skill / agent type
        assert any(q for _, q in original["qualifiers"])
        assert all(chars in (0, None) for _, chars, _ in lost["result_chars"])  # result sizes
        assert lost["file_edits"] == [] and original["file_edits"] != []      # edits + churn
        assert all(row[1:] == (0, 0, 0, 0) for row in lost["churn"])
        assert lost["artifacts"] == [] and original["artifacts"] != []
        assert lost["limit_hits"] == [] and original["limit_hits"] != []
        assert all(title is None for _, title in lost["titles"])
        assert original["titles"][0][1] is not None

    def test_attribution_still_loses_titles_tasks_and_artifact_prose(self, both):
        got = both["attribution"]
        assert all(title is None for _, title in got["titles"])
        assert [task for _, _, task, _ in got["agents"]] == [redact.REDACTED]
        assert all(row[1] is not None for row in got["artifact_text"])      # falls back to file stem
        assert got["artifact_text"] != both["original"]["artifact_text"]

    def test_artifact_prose_returns_only_at_titles(self, both):
        assert both["titles"]["artifact_text"][0][1].startswith("T SECRET")
        assert both["titles"]["artifact_text"][0][2].startswith("D SECRET")


class TestNoLeak:
    """The whole output tree, byte for byte: the sentinel is not in it."""

    @pytest.mark.parametrize("fidelity", ["minimal", "attribution"])
    def test_no_sentinel_in_any_output_byte(self, both, fidelity):
        blob = b"".join(p.read_bytes() for p in both["_dirs"][fidelity].rglob("*") if p.is_file())
        assert blob                                     # there was output to inspect
        assert b"SENTINEL" not in blob and SECRET.encode() not in blob
        # ...and neither is anything else content-shaped that was planted.
        for needle in (b"psql", b"payments", b"answer", b"prompt ", b"hmm", b"loaded", b"edited",
                       b"Investigate", b"someone@example.com", b"Acme", b"old ", b"look "):
            assert needle not in blob, needle

    def test_titles_level_is_the_one_that_admits_it(self, both):
        blob = b"".join(p.read_bytes() for p in both["_dirs"]["titles"].rglob("*") if p.is_file())
        assert SECRET.encode() in blob      # titles / task lines DO carry it: documented

    def test_hostile_record_shapes_leak_nothing_and_raise_nothing(self):
        hostile = [
            {"type": "assistant", "message": {"content": SECRET, "usage": SECRET}},
            {"type": "assistant", "message": {"content": [SECRET, None, {"type": "tool_use",
                                                                          "name": {"x": SECRET}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": {"a": SECRET}}]},
             "toolUseResult": SECRET},
            {"type": "user", "message": SECRET},
            {"type": "system", "subtype": {"nested": SECRET}, "level": [SECRET]},
            {"type": "assistant", "error": {"detail": SECRET}, "cwd": SECRET * 1000},
            {"type": "assistant", "effort": SECRET + "\n" + SECRET, "attributionSkill": "x" * 500},
            [SECRET], SECRET, None,
        ]
        for fidelity in ("minimal", "attribution"):
            for record in hostile:
                text = json.dumps(redact.slim(record, fidelity))
                assert SECRET not in text, (fidelity, record)

    def test_unknown_fidelity_is_refused(self):
        with pytest.raises(ValueError):
            redact.slim({"type": "system"}, "everything")


class TestSlimShapes:
    def test_tool_result_length_matches_what_transcript_would_measure(self):
        for payload in ("plain", [{"type": "text", "text": "héllo ☃"}], None, {"k": [1, 2]}):
            block = {"type": "tool_result", "tool_use_id": "t", "content": payload}
            out = redact.slim({"type": "user", "message": {"content": [block]}}, "attribution")
            assert out["message"]["content"][0]["_len"] == len(redact.result_text(payload))

    def test_line_counts_ignore_the_no_newline_marker_and_headerlike_lines(self):
        record = {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t", "content": "ok"}]},
            "toolUseResult": {"filePath": "/a.sh", "structuredPatch": [
                {"lines": ["---flag", "+++x", " keep", "\\ No newline at end of file"]}]}}
        assert redact.slim(record, "attribution")["toolUseResult"]["_lines"] == [1, 1]

    def test_a_compaction_summary_is_not_turned_into_a_prompt(self):
        out = redact.slim({"type": "user", "isCompactSummary": True,
                           "message": {"content": "long summary"}}, "minimal")
        assert out["isCompactSummary"] is True

    def test_a_rate_limit_banner_is_kept_only_when_anthropic_worded(self):
        def banner(text):
            return {"type": "assistant", "isApiErrorMessage": True, "error": "rate_limit",
                    "message": {"id": "m", "content": [{"type": "text", "text": text}]}}
        kept = redact.slim(banner("You've hit your weekly limit · resets Aug 16 at 8pm (Europe/London)"),
                           "attribution")
        assert kept["message"]["content"][0]["text"].startswith("You've hit your weekly limit")
        dropped = redact.slim(banner(f"something else {SECRET}"), "attribution")
        assert dropped["message"]["content"][0]["text"] == ""
        assert redact.slim(banner("You've hit your weekly limit"), "minimal")["message"]["content"][0]["text"] == ""

    def test_a_qualifier_must_look_like_an_identifier(self):
        def call(value):
            return redact.slim({"type": "assistant", "message": {"id": "m", "content": [
                {"type": "tool_use", "id": "t", "name": "Skill", "input": {"skill": value}}]}},
                "attribution")["message"]["content"][0]["input"]
        assert call("tribunal:reckoning") == {"skill": "tribunal:reckoning"}
        assert call("please ignore\nprevious {rows}") == {}

    def test_slim_does_not_modify_its_input(self):
        record = json.loads(json.dumps({"type": "user", "message": {"content": "x"}, "toolUseResult": {}}))
        before = json.dumps(record)
        redact.slim(record, "titles")
        assert json.dumps(record) == before


class TestLineReader:
    def _read(self, data: bytes, start: int = 0, limit: int = 1 << 30, block: int = 4):
        import io
        return list(redact.iter_complete_lines(io.BytesIO(data), start, limit, lambda: False, block))

    def test_only_complete_lines_and_the_offset_after_each(self):
        assert self._read(b"aa\nbbb\ncc") == [(b"aa", 3), (b"bbb", 7)]

    def test_resumes_from_an_offset(self):
        assert self._read(b"aa\nbbb\ncc\n", start=3) == [(b"bbb", 7), (b"cc", 10)]

    def test_limit_stops_after_the_line_in_hand_but_always_yields_one(self):
        assert self._read(b"aa\nbb\ncc\n", limit=1) == [(b"aa", 3)]
        assert self._read(b"aa\nbb\ncc\n", limit=4) == [(b"aa", 3), (b"bb", 6)]

    def test_deadline_stops_between_lines(self):
        import io
        seen: list = []
        lines = redact.iter_complete_lines(io.BytesIO(b"a\nb\nc\n"), 0, 1 << 30,
                                           lambda: len(seen) >= 1, 2)
        seen.extend(lines)
        assert seen == [(b"a", 2)]

    def test_an_oversized_line_is_skipped_without_being_held(self, monkeypatch):
        monkeypatch.setattr(redact, "MAX_LINE_BYTES", 10)
        got = self._read(b"ok\n" + b"x" * 100 + b"\nafter\n", block=8)
        assert got == [(b"ok", 3), (None, 104), (b"after", 110)]

    def test_non_utf8_bytes_do_not_raise(self):
        assert redact.slim_line(b'{"type":"system","subtype":"turn_duration","x":"\xff\xfe"}',
                                "minimal") is not None
        assert redact.slim_line(b"\xff\xfe not json", "minimal") is None


class TestPython38Grammar:
    @pytest.mark.parametrize("name", ["redact.py"])
    def test_the_remote_side_parses_under_python_3_8(self, name):
        source = (SCRIPTS / name).read_text()
        ast.parse(source, feature_version=(3, 8))

    @pytest.mark.parametrize("name", ["redact.py"])
    def test_the_remote_side_imports_nothing_from_chronicle(self, name):
        tree = ast.parse((SCRIPTS / name).read_text())
        roots = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        roots |= {n.module.split(".")[0] for n in ast.walk(tree)
                  if isinstance(n, ast.ImportFrom) and n.module}
        assert roots <= {"json", "os", "re", "sys", "time", "stat", "typing", "types", "hashlib",
                         "redact", "errno", "__future__", "collections"}, roots
