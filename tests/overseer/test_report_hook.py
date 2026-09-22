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


def _block(obj: dict) -> str:
    return f"some findings...\n```overseer-report\n{json.dumps(obj)}\n```\n"


def _hook(repo, monkeypatch, payload, capsys=None):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(repo), **payload})))
    if capsys is not None:
        capsys.readouterr()
    assert main(["--root", str(repo), "report-hook"]) == 0
    return capsys.readouterr() if capsys is not None else None


def _card(repo):
    return db.load_card(db.connect(repo, migrate=False), "WF-001")


def _detail(repo, stage, name, text=""):
    d = dispatch_dir(repo, "WF-001", stage)
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text)
    return d / name


def test_reviewer_verdict_lands_in_review_log_usage_and_pending(repo, tmp_path, monkeypatch, capsys):
    path = _detail(repo, "impl-review", "r1-A.md", "findings body")
    obj = {
        "schema": "overseer.reviewer/1", "card": "WF-001", "stage": "impl-review",
        "round": 1, "slot": "A", "status": "found wanting",
        "counts": {"critical": 1, "important": 2, "minor": 0},
        "detail": str(path), "learned": [{"statement": "x is y", "tags": ["t"]}],
    }
    out = _hook(repo, monkeypatch, {
        "agent_type": "overseer:overseer-reviewer", "agent_id": "a1",
        "agent_transcript_path": str(_transcript(tmp_path)),
        "last_assistant_message": _block(obj),
    }, capsys)
    assert out.out == ""
    card = _card(repo)
    assert "- A: found wanting 1C 2I 0M → " + str(path) in card.sections["## Review log"]
    assert card.budget_actual == 0  # reviewer spend is measurement only
    [entry], _ = load_usage(state_root(repo))
    assert entry["card"] == "WF-001" and entry["role"] == "reviewer" and entry["round"] == 1
    assert (entry["tokens"], entry["budget_tokens"]) == (9542, 542)
    assert entry["source"] == "hook"
    [fact] = load_pending(repo)
    assert (fact.statement, fact.tags, fact.source) == ("x is y", ["t"], str(path))


def test_implementer_spend_feeds_budget_and_progress(repo, tmp_path, monkeypatch, capsys):
    path = _detail(repo, "implementation", "c2.md", "done")
    obj = {
        "schema": "overseer.implementer/1", "card": "WF-001", "stage": "implementation",
        "chunk": 2, "status": "DONE", "tests": {"passed": 5, "total": 5},
        "commits": ["abc1234"], "detail": str(path), "learned": [],
    }
    _hook(repo, monkeypatch, {
        "agent_type": "overseer:overseer-implementer", "agent_id": "a2",
        "agent_transcript_path": str(_transcript(tmp_path)),
        "last_assistant_message": _block(obj),
    }, capsys)
    card = _card(repo)
    assert card.budget_actual == 542
    assert "chunk 2 — DONE tests 5/5 abc1234" in card.sections["## Progress log"]


def test_planner_writes_plan_section(repo, tmp_path, monkeypatch):
    path = _detail(repo, "planning", "plan.md", "## Chunks\n1. build it")
    obj = {
        "schema": "overseer.planner/1", "card": "WF-001", "stage": "planning",
        "status": "DONE", "detail": str(path), "learned": [],
    }
    _hook(repo, monkeypatch, {
        "agent_type": "overseer:overseer-planner", "agent_id": "a3",
        "agent_transcript_path": str(_transcript(tmp_path)),
        "last_assistant_message": _block(obj),
    })
    assert _card(repo).sections["## Plan"] == "### Chunks\n1. build it"


def test_planner_learned_comes_from_json_not_detail_text(repo, tmp_path, monkeypatch):
    path = _detail(repo, "planning", "plan.md", "## Chunks\n1. build it\n")
    obj = {
        "schema": "overseer.planner/1", "card": "WF-001", "stage": "planning",
        "status": "DONE", "detail": str(path),
        "learned": [{"statement": "the calibration figure was stale", "tags": ["planning"]}],
    }
    _hook(repo, monkeypatch, {
        "agent_type": "overseer:overseer-planner", "agent_id": "a3",
        "agent_transcript_path": str(_transcript(tmp_path)),
        "last_assistant_message": _block(obj),
    })
    section = _card(repo).sections["## Plan"]
    assert section == "### Chunks\n1. build it"
    [fact] = load_pending(repo)
    assert fact.statement == "the calibration figure was stale"


def test_verifier_writes_verification_section(repo, tmp_path, monkeypatch):
    path = _detail(repo, "verification", "verification.md", "pytest: 619 passed")
    obj = {
        "schema": "overseer.verifier/1", "card": "WF-001", "stage": "verification",
        "status": "PASS", "detail": str(path), "learned": [],
    }
    _hook(repo, monkeypatch, {
        "agent_type": "overseer:overseer-verifier", "agent_id": "a4",
        "agent_transcript_path": str(_transcript(tmp_path)),
        "last_assistant_message": _block(obj),
    })
    assert _card(repo).sections["## Verification"] == "pytest: 619 passed"


def test_tripwire_is_recorded(repo, tmp_path, monkeypatch):
    path = _detail(repo, "implementation", "c1.md", "done")
    obj = {
        "schema": "overseer.implementer/1", "card": "WF-001", "stage": "implementation",
        "chunk": 1, "status": "DONE", "tests": {"passed": 1, "total": 1},
        "commits": [], "detail": str(path), "learned": [],
    }
    _hook(repo, monkeypatch, {
        "agent_type": "overseer:overseer-implementer", "agent_id": "a5",
        "agent_transcript_path": str(_transcript(tmp_path, create=5000)),
        "last_assistant_message": _block(obj),
    })
    [entry], _ = load_usage(state_root(repo))
    assert entry["tripwire"] is True  # 5042 ≥ 2 × 1k estimate


def test_missing_detail_file_is_noted_but_verdict_still_recorded(repo, tmp_path, monkeypatch):
    d = dispatch_dir(repo, "WF-001", "impl-review")
    missing = d / "r1-A.md"  # never written
    obj = {
        "schema": "overseer.reviewer/1", "card": "WF-001", "stage": "impl-review",
        "round": 1, "slot": "A", "status": "approved",
        "counts": {"critical": 0, "important": 0, "minor": 0},
        "detail": str(missing), "learned": [],
    }
    _hook(repo, monkeypatch, {
        "agent_type": "overseer:overseer-reviewer", "agent_id": "a7",
        "agent_transcript_path": str(_transcript(tmp_path)),
        "last_assistant_message": _block(obj),
    })
    [entry], _ = load_usage(state_root(repo))
    assert entry["error"] == "detail file missing"
    assert f"- A: approved 0C 0I 0M → {missing}" in _card(repo).sections["## Review log"]


def test_non_overseer_agent_is_silent_and_records_nothing(repo, monkeypatch, capsys):
    out = _hook(repo, monkeypatch, {"agent_type": "general-purpose", "last_assistant_message": "hi"}, capsys)
    assert out.out == ""
    entries, _ = load_usage(state_root(repo))
    assert entries == []


class TestBoundedRetry:
    """WF-113 rework §7: exactly one bounce per invalid/missing report,
    guarded by `stop_hook_active` so it can never loop."""

    def test_no_block_first_attempt_bounces_once(self, repo, monkeypatch, capsys):
        out = _hook(repo, monkeypatch, {
            "agent_type": "overseer:overseer-reviewer", "agent_id": "a6",
            "last_assistant_message": "I reviewed everything and it looks great overall.",
            "stop_hook_active": False,
        }, capsys)
        decision = json.loads(out.out)
        assert decision["decision"] == "block"
        assert "overseer-report" in decision["reason"]
        entries, _ = load_usage(state_root(repo))
        assert entries == []  # nothing recorded on the bounce itself

    def test_invalid_schema_first_attempt_names_every_error(self, repo, monkeypatch, capsys):
        obj = {"schema": "overseer.reviewer/1", "card": "WF-001", "stage": "impl-review",
               "status": "LGTM", "extra": 1}  # missing round/slot/counts/detail/learned, bad enum, unknown field
        out = _hook(repo, monkeypatch, {
            "agent_type": "overseer:overseer-reviewer", "agent_id": "a6",
            "last_assistant_message": _block(obj),
            "stop_hook_active": False,
        }, capsys)
        decision = json.loads(out.out)
        assert decision["decision"] == "block"
        for needle in ("missing field 'round'", "missing field 'slot'", "unknown field", "one of"):
            assert needle in decision["reason"]

    def test_still_invalid_on_retry_is_recorded_silently(self, repo, monkeypatch, capsys):
        message = "I reviewed everything and it looks great overall."
        out = _hook(repo, monkeypatch, {
            "agent_type": "overseer:overseer-reviewer", "agent_id": "a6",
            "last_assistant_message": message,
            "stop_hook_active": True,
        }, capsys)
        assert out.out == ""
        [entry], _ = load_usage(state_root(repo))
        assert entry["card"] is None and entry["unparsed"] == message[:500]
        assert entry["errors"]
        assert "- A:" not in _card(repo).body

    def test_valid_report_never_blocks_even_with_stop_hook_active(self, repo, tmp_path, monkeypatch, capsys):
        path = _detail(repo, "verification", "verification.md", "pytest: ok")
        obj = {
            "schema": "overseer.verifier/1", "card": "WF-001", "stage": "verification",
            "status": "PASS", "detail": str(path), "learned": [],
        }
        out = _hook(repo, monkeypatch, {
            "agent_type": "overseer:overseer-verifier", "agent_id": "a9",
            "agent_transcript_path": str(_transcript(tmp_path)),
            "last_assistant_message": _block(obj),
            "stop_hook_active": True,
        }, capsys)
        assert out.out == ""
        assert _card(repo).sections["## Verification"] == "pytest: ok"


def test_usage_warns_about_unparsed_reports(repo, monkeypatch, capsys):
    _hook(repo, monkeypatch, {
        "agent_type": "overseer:overseer-fixer", "agent_id": "a8",
        "last_assistant_message": "no block here",
        "stop_hook_active": True,
    }, capsys)
    capsys.readouterr()
    assert main(["--root", str(repo), "usage"]) == 0
    assert "1 unparsed agent report" in capsys.readouterr().err


def test_shell_wrapper_exits_zero_silently_on_garbage():
    result = subprocess.run(
        [BASH, str(PLUGIN_ROOT / "hooks" / "report.sh")], input="not json",
        capture_output=True, text=True, check=False,
        env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
             "OVERSEER_PYTHON": sys.executable},
    )
    assert (result.returncode, result.stdout) == (0, "")


def test_shell_wrapper_passes_the_block_decision_through(repo):
    payload = json.dumps({
        "cwd": str(repo), "agent_type": "overseer:overseer-reviewer", "agent_id": "a1",
        "last_assistant_message": "no block here", "stop_hook_active": False,
    })
    result = subprocess.run(
        [BASH, str(PLUGIN_ROOT / "hooks" / "report.sh")], input=payload,
        capture_output=True, text=True, check=False,
        env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
             "OVERSEER_PYTHON": sys.executable, "OVERSEER_CENTRAL": str(repo / "state"),
             "OVERSEER_DB": str(repo / "board.db")},
    )
    assert result.returncode == 0
    decision = json.loads(result.stdout)
    assert decision["decision"] == "block"


def test_hooks_json_registers_subagent_stop():
    hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    commands = [h["command"] for entry in hooks["SubagentStop"] for h in entry["hooks"]]
    assert commands == ["${CLAUDE_PLUGIN_ROOT}/hooks/report.sh"]
