import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import db
from scripts.cli import main
from scripts.dispatch import dispatch_dir
from scripts.pending import load_pending
from scripts.store import state_root
from scripts.usage import load_usage

PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "overseer"
BASH = shutil.which("bash") or "/bin/bash"


@pytest.fixture
def repo(tmp_path):
    assert main(["--root", str(tmp_path), "init"]) == 0
    assert main(["--root", str(tmp_path), "new-card", "--title", "T", "--estimate", "1k"]) == 0
    return tmp_path


def _transcript(tmp_path, out=40, create=500, inp=2, read=9000):
    path = tmp_path / "agent.jsonl"
    path.write_text(json.dumps({"type": "assistant", "message": {"id": "m1", "usage": {
        "input_tokens": inp, "cache_read_input_tokens": read,
        "cache_creation_input_tokens": create, "output_tokens": out}}}) + "\n")
    return path


def _hook(repo, monkeypatch, payload):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(repo), **payload})))
    assert main(["--root", str(repo), "report-hook"]) == 0


def _card(repo):
    return db.load_card(db.connect(repo, migrate=False), "WF-001")


def _detail(repo, stage, name, text):
    d = dispatch_dir(repo, "WF-001", stage)
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text)
    return d / name


def test_reviewer_verdict_lands_in_review_log_usage_and_pending(repo, tmp_path, monkeypatch, capsys):
    path = _detail(repo, "impl-review", "r1-A.md",
                   "verdict: found wanting\n...\nLearned: x is y [tags: t]\n")
    _hook(repo, monkeypatch, {
        "agent_type": "overseer:overseer-reviewer", "agent_id": "a1",
        "agent_transcript_path": str(_transcript(tmp_path)),
        "last_assistant_message": f"found wanting 1C 2I 0M → {path}",
    })
    assert capsys.readouterr().out == ""
    card = _card(repo)
    assert f"- A: found wanting 1C 2I 0M → {path}" in card.sections["## Review log"]
    assert card.budget_actual == 0  # reviewer spend is measurement only
    [entry], _ = load_usage(state_root(repo))
    assert entry["card"] == "WF-001" and entry["role"] == "reviewer" and entry["round"] == 1
    assert (entry["tokens"], entry["budget_tokens"]) == (9542, 542)
    assert entry["overrun"] is False and entry["source"] == "hook"
    [fact] = load_pending(repo)
    assert (fact.statement, fact.tags, fact.source) == ("x is y", ["t"], str(path))


def test_implementer_spend_feeds_budget_and_progress(repo, tmp_path, monkeypatch):
    path = _detail(repo, "implementation", "c2.md", "done")
    _hook(repo, monkeypatch, {
        "agent_type": "overseer:overseer-implementer", "agent_id": "a2",
        "agent_transcript_path": str(_transcript(tmp_path)),
        "last_assistant_message": f"DONE tests 5/5 abc1234 → {path}",
    })
    card = _card(repo)
    assert card.budget_actual == 542
    assert "chunk 2 — DONE tests 5/5 abc1234" in card.sections["## Progress log"]


def test_planner_writes_plan_section(repo, tmp_path, monkeypatch):
    path = _detail(repo, "planning", "plan.md", "## Chunks\n1. build it")
    _hook(repo, monkeypatch, {
        "agent_type": "overseer:overseer-planner", "agent_id": "a3",
        "agent_transcript_path": str(_transcript(tmp_path)),
        "last_assistant_message": f"DONE → {path}",
    })
    assert _card(repo).sections["## Plan"] == "### Chunks\n1. build it"


def test_verifier_writes_verification_section(repo, tmp_path, monkeypatch):
    path = _detail(repo, "verification", "verification.md", "pytest: 619 passed")
    _hook(repo, monkeypatch, {
        "agent_type": "overseer:overseer-verifier", "agent_id": "a4",
        "agent_transcript_path": str(_transcript(tmp_path)),
        "last_assistant_message": f"PASS → {path}",
    })
    assert _card(repo).sections["## Verification"] == "pytest: 619 passed"


def test_tripwire_is_recorded(repo, tmp_path, monkeypatch):
    path = _detail(repo, "implementation", "c1.md", "done")
    _hook(repo, monkeypatch, {
        "agent_type": "overseer:overseer-implementer", "agent_id": "a5",
        "agent_transcript_path": str(_transcript(tmp_path, create=5000)),
        "last_assistant_message": f"DONE tests 1/1 - → {path}",
    })
    [entry], _ = load_usage(state_root(repo))
    assert entry["tripwire"] is True  # 5042 ≥ 2 × 1k estimate


@pytest.mark.parametrize("message, error", [
    ("I reviewed everything and it looks great overall.", "does not match"),
    ("approved 0C 0I 0M → /elsewhere/dispatch/WF-001/impl-review/r1-A.md",
     "outside this repo's dispatch directory"),
])
def test_unparsed_reply_is_recorded_not_retried(repo, tmp_path, monkeypatch, capsys, message, error):
    _hook(repo, monkeypatch, {
        "agent_type": "overseer:overseer-reviewer", "agent_id": "a6",
        "agent_transcript_path": str(_transcript(tmp_path)),
        "last_assistant_message": message,
    })
    assert capsys.readouterr().out == ""
    [entry], _ = load_usage(state_root(repo))
    assert entry["card"] is None and error in entry["error"] and entry["unparsed"] == message
    assert "- A:" not in _card(repo).body


def test_missing_detail_file_is_noted_but_verdict_still_recorded(repo, tmp_path, monkeypatch):
    d = dispatch_dir(repo, "WF-001", "impl-review")
    line = "approved 0C 0I 0M → " + str(d / "r1-A.md")
    _hook(repo, monkeypatch, {
        "agent_type": "overseer:overseer-reviewer", "agent_id": "a7",
        "agent_transcript_path": str(_transcript(tmp_path)),
        "last_assistant_message": line,
    })
    [entry], _ = load_usage(state_root(repo))
    assert entry["error"] == "detail file missing" and entry["overrun"] is False
    assert f"- A: {line}" in _card(repo).sections["## Review log"]


def test_non_overseer_agent_is_ignored(repo, monkeypatch):
    _hook(repo, monkeypatch, {"agent_type": "general-purpose", "last_assistant_message": "hi"})
    entries, _ = load_usage(state_root(repo))
    assert entries == []


def test_usage_warns_about_unparsed_and_overruns(repo, tmp_path, monkeypatch, capsys):
    _hook(repo, monkeypatch, {
        "agent_type": "overseer:overseer-fixer", "agent_id": "a8",
        "last_assistant_message": " ".join(["word"] * 30),
    })
    capsys.readouterr()
    assert main(["--root", str(repo), "usage"]) == 0
    assert "1 unparsed agent reply, 1 over the 25-word cap" in capsys.readouterr().err


def test_shell_wrapper_exits_zero_silently_on_garbage(repo):
    result = subprocess.run(
        [BASH, str(PLUGIN_ROOT / "hooks" / "report.sh")], input="not json",
        capture_output=True, text=True, check=False,
        env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
             "OVERSEER_PYTHON": sys.executable},
    )
    assert (result.returncode, result.stdout) == (0, "")


def test_hooks_json_registers_subagent_stop():
    hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    commands = [h["command"] for entry in hooks["SubagentStop"] for h in entry["hooks"]]
    assert commands == ["${CLAUDE_PLUGIN_ROOT}/hooks/report.sh"]
