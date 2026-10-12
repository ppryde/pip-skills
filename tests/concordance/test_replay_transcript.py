import time
from pathlib import Path

import pytest

from scripts.replay import transcript as tr

from .replay_support import Transcript


def _projects(tmp_path: Path) -> Path:
    return tmp_path / "config" / "projects"


def test_pairs_calls_with_results_across_subagents(tmp_path: Path) -> None:
    t = Transcript(_projects(tmp_path), "s1", tmp_path)
    t.call("Read", {"file_path": "/x/a.py"}, "     1\tprint(1)\n")
    t.call("Grep", {"pattern": "refund"}, "Found 1 file\n/x/a.py", agent="abc")
    t.write()
    files = tr.session_files("s1", _projects(tmp_path))
    s = tr.load("s1", files)
    assert [(c.name, c.agent_id, c.seq) for c in s.calls] == [("Read", "", 0), ("Grep", "abc", 0)]
    assert s.calls[0].result_text.endswith("print(1)\n") and s.calls[0].cwd == str(tmp_path)


def test_list_content_counts_text_only(tmp_path: Path) -> None:
    t = Transcript(_projects(tmp_path), "s2", tmp_path)
    t.call("Read", {"file_path": "/x/i.png"},
           [{"type": "text", "text": "hello"}, {"type": "image", "source": {"data": "Zm9v"}}])
    t.write()
    s = tr.load("s2", tr.session_files("s2", _projects(tmp_path)))
    assert s.calls[0].result_text == "hello"


def test_bad_lines_are_skipped(tmp_path: Path) -> None:
    t = Transcript(_projects(tmp_path), "s3", tmp_path)
    t.call("Bash", {"command": "ls"}, "a\nb")
    t.write(extra_lines=["{not json", '{"type": "assistant", "message": {"content": [{"ty'])
    s = tr.load("s3", tr.session_files("s3", _projects(tmp_path)))
    assert len(s.calls) == 1 and s.bad_lines == 2


def test_unanswered_call_has_empty_result(tmp_path: Path) -> None:
    t = Transcript(_projects(tmp_path), "s4", tmp_path)
    t.call("Bash", {"command": "ls"}, "ok")
    t.records.pop()  # drop the tool_result
    t.write()
    s = tr.load("s4", tr.session_files("s4", _projects(tmp_path)))
    assert s.calls[0].result_text == ""


def test_finished_needs_900s_idle(tmp_path: Path) -> None:
    t = Transcript(_projects(tmp_path), "s5", tmp_path)
    t.call("Bash", {"command": "ls"}, "ok")
    t.write(age_s=60)
    files = tr.session_files("s5", _projects(tmp_path))
    assert not tr.is_finished(files)
    assert tr.is_finished(files, now=time.time() + 900)


def test_missing_session_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        tr.session_files("nope", _projects(tmp_path))
    with pytest.raises(FileNotFoundError):
        tr.session_files("nope", main=tmp_path / "nope.jsonl")


def test_explicit_main_still_finds_subagents(tmp_path: Path) -> None:
    t = Transcript(_projects(tmp_path), "s6", tmp_path)
    t.call("Bash", {"command": "ls"}, "ok", agent="zz")
    main = t.write()
    assert [a for a, _ in tr.session_files("s6", main=main)] == ["", "zz"]
