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
from scripts.models import Card

PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "overseer"
HOOK_SCRIPT = PLUGIN_ROOT / "hooks" / "checklist-sync.sh"
PREPUSH_HOOK_SCRIPT = PLUGIN_ROOT / "hooks" / "prepush-snapshot.sh"
BASH = shutil.which("bash") or "/bin/bash"


@pytest.fixture
def repo(tmp_path):
    assert main(["--root", str(tmp_path), "init"]) == 0
    return tmp_path


def run(repo, *argv: str) -> int:
    return main(["--root", str(repo), *argv])


def _stdin(monkeypatch, payload: dict) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))


def _checklist(repo, card_id: str = "WF-001") -> list[dict]:
    return db.load_card(db.connect(repo, migrate=False), card_id).checklist


def _write_task_file(config_dir: Path, list_dir_name: str, task_id: str, metadata: dict) -> None:
    task_dir = config_dir / "tasks" / list_dir_name
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / f"{task_id}.json").write_text(
        json.dumps({"id": task_id, "metadata": metadata})
    )


class TestChecklistSyncHookTaskCreate:
    def test_metadata_card_creates_pending_entry(self, repo, monkeypatch):
        run(repo, "new-card", "--title", "T")
        _stdin(monkeypatch, {
            "cwd": str(repo),
            "tool_name": "TaskCreate",
            "tool_input": {"subject": "write tests", "metadata": {"card": "WF-001"}},
            "tool_response": {"task": {"id": "7"}},
        })
        assert run(repo, "checklist-sync-hook") == 0
        assert _checklist(repo) == [
            {"task": "7", "subject": "write tests", "status": "pending"},
        ]

    def test_no_metadata_card_is_orphan_noop(self, repo, monkeypatch):
        run(repo, "new-card", "--title", "T")
        _stdin(monkeypatch, {
            "cwd": str(repo),
            "tool_name": "TaskCreate",
            "tool_input": {"subject": "orphan task"},
            "tool_response": {"task": {"id": "7"}},
        })
        assert run(repo, "checklist-sync-hook") == 0
        assert _checklist(repo) == []


class TestChecklistSyncHookTaskUpdate:
    def test_status_change_with_task_file_present(self, repo, tmp_path, monkeypatch):
        run(repo, "new-card", "--title", "T")
        run(repo, "checklist", "WF-001", "--task", "7",
            "--subject", "write tests", "--status", "in_progress")
        config_dir = tmp_path / "cfgdir"
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("CLAUDE_CODE_TASK_LIST_ID", "myproj")
        _write_task_file(config_dir, "myproj", "7", {"card": "WF-001"})
        _stdin(monkeypatch, {
            "cwd": str(repo),
            "tool_name": "TaskUpdate",
            "tool_input": {"taskId": "7"},
            "tool_response": {"statusChange": {"from": "in_progress", "to": "completed"}},
        })
        assert run(repo, "checklist-sync-hook") == 0
        assert _checklist(repo) == [
            {"task": "7", "subject": "write tests", "status": "completed"},
        ]

    def test_task_file_gone_falls_back_to_card_scan(self, repo, tmp_path, monkeypatch):
        run(repo, "new-card", "--title", "T")
        run(repo, "checklist", "WF-001", "--task", "7",
            "--subject", "write tests", "--status", "in_progress")
        config_dir = tmp_path / "cfgdir"
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
        monkeypatch.delenv("CLAUDE_CODE_TASK_LIST_ID", raising=False)
        # No task file written anywhere: session-scoped list already deleted
        # it the instant the task completed — the empirically verified case.
        _stdin(monkeypatch, {
            "cwd": str(repo),
            "session_id": "abcdefgh-irrelevant",
            "tool_name": "TaskUpdate",
            "tool_input": {"taskId": "7"},
            "tool_response": {"statusChange": {"from": "in_progress", "to": "completed"}},
        })
        assert run(repo, "checklist-sync-hook") == 0
        assert _checklist(repo) == [
            {"task": "7", "subject": "write tests", "status": "completed"},
        ]

    def test_task_file_gone_and_no_card_has_id_is_noop(self, repo, tmp_path, monkeypatch):
        run(repo, "new-card", "--title", "T")
        config_dir = tmp_path / "cfgdir"
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
        _stdin(monkeypatch, {
            "cwd": str(repo),
            "session_id": "abcdefgh-irrelevant",
            "tool_name": "TaskUpdate",
            "tool_input": {"taskId": "999"},
            "tool_response": {"statusChange": {"from": "pending", "to": "completed"}},
        })
        assert run(repo, "checklist-sync-hook") == 0
        assert _checklist(repo) == []

    def test_no_status_change_and_no_subject_is_noop(self, repo, tmp_path, monkeypatch):
        run(repo, "new-card", "--title", "T")
        run(repo, "checklist", "WF-001", "--task", "7",
            "--subject", "write tests", "--status", "in_progress")
        config_dir = tmp_path / "cfgdir"
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("CLAUDE_CODE_TASK_LIST_ID", "myproj")
        _write_task_file(config_dir, "myproj", "7", {"card": "WF-001"})
        _stdin(monkeypatch, {
            "cwd": str(repo),
            "tool_name": "TaskUpdate",
            "tool_input": {"taskId": "7"},
            "tool_response": {"updatedFields": ["owner"]},
        })
        assert run(repo, "checklist-sync-hook") == 0
        assert _checklist(repo) == [
            {"task": "7", "subject": "write tests", "status": "in_progress"},
        ]

    def test_subject_only_update_preserves_status(self, repo, tmp_path, monkeypatch):
        run(repo, "new-card", "--title", "T")
        run(repo, "checklist", "WF-001", "--task", "7",
            "--subject", "write tests", "--status", "in_progress")
        config_dir = tmp_path / "cfgdir"
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("CLAUDE_CODE_TASK_LIST_ID", "myproj")
        _write_task_file(config_dir, "myproj", "7", {"card": "WF-001"})
        _stdin(monkeypatch, {
            "cwd": str(repo),
            "tool_name": "TaskUpdate",
            "tool_input": {"taskId": "7", "subject": "write tests, revised"},
            "tool_response": {"updatedFields": ["subject"]},
        })
        assert run(repo, "checklist-sync-hook") == 0
        assert _checklist(repo) == [
            {"task": "7", "subject": "write tests, revised", "status": "in_progress"},
        ]

    def test_status_change_to_deleted_removes_entry(self, repo, tmp_path, monkeypatch):
        run(repo, "new-card", "--title", "T")
        run(repo, "checklist", "WF-001", "--task", "7",
            "--subject", "write tests", "--status", "in_progress")
        config_dir = tmp_path / "cfgdir"
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("CLAUDE_CODE_TASK_LIST_ID", "myproj")
        _write_task_file(config_dir, "myproj", "7", {"card": "WF-001"})
        _stdin(monkeypatch, {
            "cwd": str(repo),
            "tool_name": "TaskUpdate",
            "tool_input": {"taskId": "7"},
            "tool_response": {"statusChange": {"from": "in_progress", "to": "deleted"}},
        })
        assert run(repo, "checklist-sync-hook") == 0
        assert _checklist(repo) == []

    def test_unrecognised_status_value_is_noop(self, repo, tmp_path, monkeypatch):
        run(repo, "new-card", "--title", "T")
        run(repo, "checklist", "WF-001", "--task", "7",
            "--subject", "write tests", "--status", "in_progress")
        config_dir = tmp_path / "cfgdir"
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("CLAUDE_CODE_TASK_LIST_ID", "myproj")
        _write_task_file(config_dir, "myproj", "7", {"card": "WF-001"})
        _stdin(monkeypatch, {
            "cwd": str(repo),
            "tool_name": "TaskUpdate",
            "tool_input": {"taskId": "7"},
            "tool_response": {"statusChange": {"from": "in_progress", "to": "blocked"}},
        })
        assert run(repo, "checklist-sync-hook") == 0
        assert _checklist(repo) == [
            {"task": "7", "subject": "write tests", "status": "in_progress"},
        ]


class TestTaskListEnvPrecedence:
    def test_named_list_id_wins_over_session_dir(self, repo, tmp_path, monkeypatch):
        run(repo, "new-card", "--title", "A")  # WF-001
        run(repo, "new-card", "--title", "B")  # WF-002
        run(repo, "checklist", "WF-001", "--task", "7",
            "--subject", "real", "--status", "in_progress")
        run(repo, "checklist", "WF-002", "--task", "7",
            "--subject", "decoy", "--status", "in_progress")
        config_dir = tmp_path / "cfgdir"
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("CLAUDE_CODE_TASK_LIST_ID", "named-list")
        session_id = "sess1234-should-be-ignored"
        _write_task_file(config_dir, "named-list", "7", {"card": "WF-001"})
        _write_task_file(config_dir, f"session-{session_id[:8]}", "7", {"card": "WF-002"})
        _stdin(monkeypatch, {
            "cwd": str(repo),
            "session_id": session_id,
            "tool_name": "TaskUpdate",
            "tool_input": {"taskId": "7"},
            "tool_response": {"statusChange": {"from": "in_progress", "to": "completed"}},
        })
        assert run(repo, "checklist-sync-hook") == 0
        assert _checklist(repo, "WF-001") == [
            {"task": "7", "subject": "real", "status": "completed"},
        ]
        assert _checklist(repo, "WF-002") == [
            {"task": "7", "subject": "decoy", "status": "in_progress"},
        ]

    def test_session_scoped_dir_used_when_list_id_unset(self, repo, tmp_path, monkeypatch):
        run(repo, "new-card", "--title", "A")  # WF-001
        run(repo, "new-card", "--title", "B")  # WF-002
        run(repo, "checklist", "WF-001", "--task", "7",
            "--subject", "real", "--status", "in_progress")
        run(repo, "checklist", "WF-002", "--task", "7",
            "--subject", "decoy", "--status", "in_progress")
        config_dir = tmp_path / "cfgdir"
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
        monkeypatch.delenv("CLAUDE_CODE_TASK_LIST_ID", raising=False)
        session_id = "sess1234-suffix-ignored"
        # A stray "named-list"-shaped dir must NOT be consulted once unset.
        _write_task_file(config_dir, "named-list", "7", {"card": "WF-002"})
        _write_task_file(config_dir, f"session-{session_id[:8]}", "7", {"card": "WF-001"})
        _stdin(monkeypatch, {
            "cwd": str(repo),
            "session_id": session_id,
            "tool_name": "TaskUpdate",
            "tool_input": {"taskId": "7"},
            "tool_response": {"statusChange": {"from": "in_progress", "to": "completed"}},
        })
        assert run(repo, "checklist-sync-hook") == 0
        assert _checklist(repo, "WF-001") == [
            {"task": "7", "subject": "real", "status": "completed"},
        ]
        assert _checklist(repo, "WF-002") == [
            {"task": "7", "subject": "decoy", "status": "in_progress"},
        ]


class TestChecklistSyncHookNeverRaises:
    def test_malformed_stdin_exits_0(self, repo, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO("not json at all"))
        assert run(repo, "checklist-sync-hook") == 0

    def test_missing_tool_response_exits_0(self, repo, monkeypatch):
        run(repo, "new-card", "--title", "T")
        _stdin(monkeypatch, {
            "cwd": str(repo),
            "tool_name": "TaskCreate",
            "tool_input": {"subject": "x", "metadata": {"card": "WF-001"}},
        })
        assert run(repo, "checklist-sync-hook") == 0
        assert _checklist(repo) == []

    def test_unknown_card_in_metadata_exits_0(self, repo, monkeypatch):
        _stdin(monkeypatch, {
            "cwd": str(repo),
            "tool_name": "TaskCreate",
            "tool_input": {"subject": "x", "metadata": {"card": "WF-999"}},
            "tool_response": {"task": {"id": "7"}},
        })
        assert run(repo, "checklist-sync-hook") == 0

    def test_no_overseer_state_dir_exits_0(self, tmp_path, monkeypatch):
        _stdin(monkeypatch, {
            "cwd": str(tmp_path),
            "tool_name": "TaskCreate",
            "tool_input": {"subject": "x", "metadata": {"card": "WF-001"}},
            "tool_response": {"task": {"id": "7"}},
        })
        assert main(["--root", str(tmp_path), "checklist-sync-hook"]) == 0


class TestHooksJson:
    def test_registers_post_tool_use_matcher_and_script(self):
        data = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())
        assert "PostToolUse" in data["hooks"]
        ptu = data["hooks"]["PostToolUse"][0]
        assert ptu["matcher"] == "TaskCreate|TaskUpdate"
        assert ptu["hooks"][0]["command"].endswith("checklist-sync.sh")

    def test_registers_stop_and_user_prompt_submit_hooks(self):
        data = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())
        assert data["hooks"]["Stop"][0]["hooks"][0]["command"].endswith("claim-stop.sh")
        upsub = data["hooks"]["UserPromptSubmit"][0]
        assert upsub["hooks"][0]["command"].endswith("claim-prompt.sh")


def _card(repo, card_id: str = "WF-001") -> Card:
    return db.load_card(db.connect(repo, migrate=False), card_id)


class TestClaimStopHook:
    def _claim(self, repo, card_id: str = "WF-001", session: str = "sess-1") -> None:
        run(repo, "new-card", "--title", "T")
        run(repo, "claim", card_id, "--session", session)

    def test_blocks_once_with_reason_naming_card_and_stamps_nudged(
        self, repo, monkeypatch, capsys
    ):
        self._claim(repo)
        capsys.readouterr()  # discard new-card/claim setup output
        _stdin(monkeypatch, {"cwd": str(repo), "session_id": "sess-1"})
        assert run(repo, "claim-stop-hook") == 0
        out = json.loads(capsys.readouterr().out)
        assert out == {
            "decision": "block",
            "reason": "Claimed for you from the dashboard: pick up WF-001 — "
                      "run resume and work the card.",
        }
        assert _card(repo).claim_nudged is True

    def test_second_stop_is_system_message_not_block(self, repo, monkeypatch, capsys):
        self._claim(repo)
        _stdin(monkeypatch, {"cwd": str(repo), "session_id": "sess-1"})
        assert run(repo, "claim-stop-hook") == 0  # first: blocks + nudges
        capsys.readouterr()
        _stdin(monkeypatch, {"cwd": str(repo), "session_id": "sess-1"})
        assert run(repo, "claim-stop-hook") == 0
        out = json.loads(capsys.readouterr().out)
        assert "decision" not in out
        assert out["systemMessage"] == (
            "overseer: WF-001 is claimed for this session and unacknowledged"
        )

    def test_stop_hook_active_suppresses_block(self, repo, monkeypatch, capsys):
        self._claim(repo)
        capsys.readouterr()
        _stdin(monkeypatch, {
            "cwd": str(repo), "session_id": "sess-1", "stop_hook_active": True,
        })
        assert run(repo, "claim-stop-hook") == 0
        out = json.loads(capsys.readouterr().out)
        assert "decision" not in out
        assert "systemMessage" in out
        assert _card(repo).claim_nudged is False  # never blocked, never nudged

    def test_acked_claim_is_silent(self, repo, monkeypatch, capsys):
        self._claim(repo)
        run(repo, "set-stage", "WF-001", "implementation")  # work verb acks
        capsys.readouterr()
        _stdin(monkeypatch, {"cwd": str(repo), "session_id": "sess-1"})
        assert run(repo, "claim-stop-hook") == 0
        assert capsys.readouterr().out == ""

    def test_no_claim_is_silent(self, repo, monkeypatch, capsys):
        run(repo, "new-card", "--title", "T")
        capsys.readouterr()
        _stdin(monkeypatch, {"cwd": str(repo), "session_id": "sess-1"})
        assert run(repo, "claim-stop-hook") == 0
        assert capsys.readouterr().out == ""

    def test_claim_for_other_session_is_silent(self, repo, monkeypatch, capsys):
        self._claim(repo, session="sess-other")
        capsys.readouterr()
        _stdin(monkeypatch, {"cwd": str(repo), "session_id": "sess-1"})
        assert run(repo, "claim-stop-hook") == 0
        assert capsys.readouterr().out == ""

    def test_missing_session_id_is_silent(self, repo, monkeypatch, capsys):
        self._claim(repo)
        capsys.readouterr()
        _stdin(monkeypatch, {"cwd": str(repo)})
        assert run(repo, "claim-stop-hook") == 0
        assert capsys.readouterr().out == ""

    def test_malformed_stdin_exits_0_silent(self, repo, monkeypatch, capsys):
        monkeypatch.setattr(sys, "stdin", io.StringIO("not json at all"))
        assert run(repo, "claim-stop-hook") == 0
        assert capsys.readouterr().out == ""

    def test_no_overseer_state_dir_exits_0_silent(self, tmp_path, monkeypatch, capsys):
        _stdin(monkeypatch, {"cwd": str(tmp_path), "session_id": "sess-1"})
        assert main(["--root", str(tmp_path), "claim-stop-hook"]) == 0
        assert capsys.readouterr().out == ""

    def test_multiple_unacked_claims_nudges_only_first_names_rest(
        self, repo, monkeypatch, capsys
    ):
        run(repo, "new-card", "--title", "A")  # WF-001
        run(repo, "new-card", "--title", "B")  # WF-002
        run(repo, "claim", "WF-001", "--session", "sess-1")
        run(repo, "claim", "WF-002", "--session", "sess-1")
        capsys.readouterr()
        _stdin(monkeypatch, {"cwd": str(repo), "session_id": "sess-1"})
        assert run(repo, "claim-stop-hook") == 0
        out = json.loads(capsys.readouterr().out)
        assert out["decision"] == "block"
        assert "WF-001" in out["reason"]
        assert "WF-002" in out["reason"]
        assert _card(repo, "WF-001").claim_nudged is True
        assert _card(repo, "WF-002").claim_nudged is False


class TestClaimPromptHook:
    def _claim(self, repo, card_id: str = "WF-001", session: str = "sess-1") -> None:
        run(repo, "new-card", "--title", "T")
        run(repo, "claim", card_id, "--session", session)

    def test_notice_shape_and_text(self, repo, monkeypatch, capsys):
        self._claim(repo)
        capsys.readouterr()
        _stdin(monkeypatch, {
            "cwd": str(repo), "session_id": "sess-1",
            "hook_event_name": "UserPromptSubmit",
        })
        assert run(repo, "claim-prompt-hook") == 0
        out = json.loads(capsys.readouterr().out)
        assert out == {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": "Cards claimed for this session from the "
                                      "dashboard: WF-001 — run resume / pick up.",
            }
        }

    def test_falls_back_to_default_event_name(self, repo, monkeypatch, capsys):
        self._claim(repo)
        capsys.readouterr()
        _stdin(monkeypatch, {"cwd": str(repo), "session_id": "sess-1"})
        assert run(repo, "claim-prompt-hook") == 0
        out = json.loads(capsys.readouterr().out)
        assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"

    def test_repeats_every_prompt_until_acked(self, repo, monkeypatch, capsys):
        self._claim(repo)
        capsys.readouterr()
        _stdin(monkeypatch, {"cwd": str(repo), "session_id": "sess-1"})
        assert run(repo, "claim-prompt-hook") == 0
        assert capsys.readouterr().out != ""
        _stdin(monkeypatch, {"cwd": str(repo), "session_id": "sess-1"})
        assert run(repo, "claim-prompt-hook") == 0
        assert capsys.readouterr().out != ""  # still unacked — fires again

    def test_acked_claim_never_blocks_and_is_silent(self, repo, monkeypatch, capsys):
        self._claim(repo)
        run(repo, "set-stage", "WF-001", "implementation")  # acks
        capsys.readouterr()
        _stdin(monkeypatch, {"cwd": str(repo), "session_id": "sess-1"})
        assert run(repo, "claim-prompt-hook") == 0
        assert capsys.readouterr().out == ""

    def test_no_claim_is_silent(self, repo, monkeypatch, capsys):
        run(repo, "new-card", "--title", "T")
        capsys.readouterr()
        _stdin(monkeypatch, {"cwd": str(repo), "session_id": "sess-1"})
        assert run(repo, "claim-prompt-hook") == 0
        assert capsys.readouterr().out == ""

    def test_missing_session_id_is_silent(self, repo, monkeypatch, capsys):
        self._claim(repo)
        capsys.readouterr()
        _stdin(monkeypatch, {"cwd": str(repo)})
        assert run(repo, "claim-prompt-hook") == 0
        assert capsys.readouterr().out == ""

    def test_malformed_stdin_exits_0_silent(self, repo, monkeypatch, capsys):
        monkeypatch.setattr(sys, "stdin", io.StringIO("garbage{{{"))
        assert run(repo, "claim-prompt-hook") == 0
        assert capsys.readouterr().out == ""

    def test_no_overseer_state_dir_exits_0_silent(self, tmp_path, monkeypatch, capsys):
        _stdin(monkeypatch, {"cwd": str(tmp_path), "session_id": "sess-1"})
        assert main(["--root", str(tmp_path), "claim-prompt-hook"]) == 0
        assert capsys.readouterr().out == ""


class TestHookScriptSmoke:
    def _run_script(self, payload: dict, env: dict, cwd: Path):
        return subprocess.run(
            [BASH, str(HOOK_SCRIPT)], input=json.dumps(payload),
            env=env, cwd=cwd, capture_output=True, text=True,
        )

    def test_broken_python_still_exits_0(self, tmp_path):
        # A CLAUDE_PLUGIN_ROOT with no sibling .venv AND a PATH that cannot
        # resolve `python3` either: the interpreter is genuinely unreachable.
        fake_plugin_root = tmp_path / "fake-plugin-root"
        fake_plugin_root.mkdir()
        payload = {
            "cwd": str(tmp_path),
            "tool_name": "TaskCreate",
            "tool_input": {"subject": "x", "metadata": {"card": "WF-001"}},
            "tool_response": {"task": {"id": "1"}},
        }
        env = dict(os.environ)
        env["CLAUDE_PLUGIN_ROOT"] = str(fake_plugin_root)
        env["PATH"] = str(tmp_path / "no-such-bin")
        result = self._run_script(payload, env, tmp_path)
        assert result.returncode == 0

    def test_valid_taskcreate_payload_exits_0_and_lands_entry(self, tmp_path):
        """Happy-path companion to `test_broken_python_still_exits_0`: the
        real interpreter (repo's `.venv`, resolved via the real
        `CLAUDE_PLUGIN_ROOT`), a real TaskCreate payload, and a tmp state
        root supplied via the payload's `cwd` — end to end through the
        actual shell script, not just `cmd_checklist_sync_hook` in-process.
        """
        assert main(["--root", str(tmp_path), "init"]) == 0
        assert main(["--root", str(tmp_path), "new-card", "--title", "T"]) == 0
        payload = {
            "cwd": str(tmp_path),
            "tool_name": "TaskCreate",
            "tool_input": {"subject": "write tests", "metadata": {"card": "WF-001"}},
            "tool_response": {"task": {"id": "7"}},
        }
        env = dict(os.environ)
        env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
        env["OVERSEER_PYTHON"] = sys.executable
        result = self._run_script(payload, env, tmp_path)
        assert result.returncode == 0
        assert _checklist(tmp_path) == [
            {"task": "7", "subject": "write tests", "status": "pending"},
        ]


class TestClaimStopScriptSmoke:
    HOOK_SCRIPT = PLUGIN_ROOT / "hooks" / "claim-stop.sh"

    def _run_script(self, payload: dict, env: dict, cwd: Path):
        return subprocess.run(
            [BASH, str(self.HOOK_SCRIPT)], input=json.dumps(payload),
            env=env, cwd=cwd, capture_output=True, text=True,
        )

    def test_broken_python_still_exits_0(self, tmp_path):
        fake_plugin_root = tmp_path / "fake-plugin-root"
        fake_plugin_root.mkdir()
        env = dict(os.environ)
        env["CLAUDE_PLUGIN_ROOT"] = str(fake_plugin_root)
        env["PATH"] = str(tmp_path / "no-such-bin")
        result = self._run_script({"cwd": str(tmp_path), "session_id": "sess-1"}, env, tmp_path)
        assert result.returncode == 0

    def test_valid_payload_end_to_end_blocks_via_real_script(self, tmp_path):
        assert main(["--root", str(tmp_path), "init"]) == 0
        assert main(["--root", str(tmp_path), "new-card", "--title", "T"]) == 0
        assert main(["--root", str(tmp_path), "claim", "WF-001", "--session", "sess-1"]) == 0
        env = dict(os.environ)
        env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
        env["OVERSEER_PYTHON"] = sys.executable
        result = self._run_script({"cwd": str(tmp_path), "session_id": "sess-1"}, env, tmp_path)
        assert result.returncode == 0
        out = json.loads(result.stdout)
        assert out["decision"] == "block"
        assert "WF-001" in out["reason"]


class TestClaimPromptScriptSmoke:
    HOOK_SCRIPT = PLUGIN_ROOT / "hooks" / "claim-prompt.sh"

    def _run_script(self, payload: dict, env: dict, cwd: Path):
        return subprocess.run(
            [BASH, str(self.HOOK_SCRIPT)], input=json.dumps(payload),
            env=env, cwd=cwd, capture_output=True, text=True,
        )

    def test_broken_python_still_exits_0(self, tmp_path):
        fake_plugin_root = tmp_path / "fake-plugin-root"
        fake_plugin_root.mkdir()
        env = dict(os.environ)
        env["CLAUDE_PLUGIN_ROOT"] = str(fake_plugin_root)
        env["PATH"] = str(tmp_path / "no-such-bin")
        result = self._run_script({"cwd": str(tmp_path), "session_id": "sess-1"}, env, tmp_path)
        assert result.returncode == 0

    def test_valid_payload_end_to_end_notices_via_real_script(self, tmp_path):
        assert main(["--root", str(tmp_path), "init"]) == 0
        assert main(["--root", str(tmp_path), "new-card", "--title", "T"]) == 0
        assert main(["--root", str(tmp_path), "claim", "WF-001", "--session", "sess-1"]) == 0
        env = dict(os.environ)
        env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
        env["OVERSEER_PYTHON"] = sys.executable
        result = self._run_script({"cwd": str(tmp_path), "session_id": "sess-1"}, env, tmp_path)
        assert result.returncode == 0
        out = json.loads(result.stdout)
        assert "WF-001" in out["hookSpecificOutput"]["additionalContext"]


class TestPrepushSnapshotHook:
    """`prepush-snapshot.sh` is a PreToolUse/Bash hook that snapshots +
    commits the board immediately before a `git push` runs, so the push
    naturally includes the snapshot commit. It must always exit 0."""

    def _git(self, repo: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True,
        )

    def _log_messages(self, repo: Path) -> list[str]:
        result = self._git(repo, "log", "--pretty=%s")
        if result.returncode != 0:
            return []
        return [line for line in result.stdout.splitlines() if line]

    def _run_script(
        self, payload: dict, repo: Path, *, set_plugin_root: bool = True,
    ) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        if set_plugin_root:
            env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
        else:
            env.pop("CLAUDE_PLUGIN_ROOT", None)
        env["OVERSEER_PYTHON"] = sys.executable
        return subprocess.run(
            [BASH, str(PREPUSH_HOOK_SCRIPT)], input=json.dumps(payload),
            env=env, cwd=repo, capture_output=True, text=True,
        )

    @pytest.fixture
    def git_repo(self, tmp_path):
        repo = tmp_path
        self._git(repo, "init", "-q")
        self._git(repo, "config", "user.email", "test@example.com")
        self._git(repo, "config", "user.name", "Test")
        return repo

    def test_snapshots_on_opted_in_push(self, git_repo):
        assert main(["--root", str(git_repo), "init"]) == 0
        assert main(["--root", str(git_repo), "new-card", "--title", "T"]) == 0

        result = self._run_script(
            {"tool_input": {"command": "git push origin main"}}, git_repo,
        )

        assert result.returncode == 0
        assert "chore(overseer): board snapshot" in self._log_messages(git_repo)
        show = self._git(git_repo, "show", "HEAD:.overseer/backups/cards.json")
        assert show.returncode == 0
        assert "WF-001" in show.stdout

    def test_noop_when_not_opted_in(self, git_repo):
        assert main(["--root", str(git_repo), "init"]) == 0
        assert main(["--root", str(git_repo), "new-card", "--title", "T"]) == 0
        (git_repo / ".overseer" / "config.json").unlink()

        result = self._run_script(
            {"tool_input": {"command": "git push origin main"}}, git_repo,
        )

        assert result.returncode == 0
        assert self._log_messages(git_repo) == []

    def test_noop_on_non_push_command(self, git_repo):
        assert main(["--root", str(git_repo), "init"]) == 0
        assert main(["--root", str(git_repo), "new-card", "--title", "T"]) == 0

        result = self._run_script({"tool_input": {"command": "git status"}}, git_repo)

        assert result.returncode == 0
        assert self._log_messages(git_repo) == []

    def test_noop_when_push_is_inside_quoted_arg(self, git_repo):
        # `git push` appears only inside a quoted commit message — a raw-string
        # regex would false-positive; the shlex tokenizer must not (WF-049).
        assert main(["--root", str(git_repo), "init"]) == 0
        assert main(["--root", str(git_repo), "new-card", "--title", "T"]) == 0

        result = self._run_script(
            {"tool_input": {"command": 'git commit -m "remember to git push later"'}},
            git_repo,
        )

        assert result.returncode == 0
        assert self._log_messages(git_repo) == []

    def test_snapshots_when_git_dash_C_quoted_path_push(self, git_repo):
        # A quoted `-C` value containing spaces must not defeat detection
        # (the old `-C[^space]+` regex missed this) (WF-049).
        assert main(["--root", str(git_repo), "init"]) == 0
        assert main(["--root", str(git_repo), "new-card", "--title", "T"]) == 0

        result = self._run_script(
            {"tool_input": {"command": 'git -C "/some path with spaces" push origin main'}},
            git_repo,
        )

        assert result.returncode == 0
        assert "chore(overseer): board snapshot" in self._log_messages(git_repo)

    def test_snapshots_on_cd_then_push_segment(self, git_repo):
        # A push in a later shell segment (`cd x && git push`) still fires.
        assert main(["--root", str(git_repo), "init"]) == 0
        assert main(["--root", str(git_repo), "new-card", "--title", "T"]) == 0

        result = self._run_script(
            {"tool_input": {"command": "cd /tmp && git push origin main"}},
            git_repo,
        )

        assert result.returncode == 0
        assert "chore(overseer): board snapshot" in self._log_messages(git_repo)

    def test_snapshots_on_multiline_push(self, git_repo):
        # A push on its own line of a multiline command must fire — shlex eats
        # newlines, so detection splits on "\n" per line (WF-049 regression).
        assert main(["--root", str(git_repo), "init"]) == 0
        assert main(["--root", str(git_repo), "new-card", "--title", "T"]) == 0

        result = self._run_script(
            {"tool_input": {"command": "git add -A\ngit commit -m wip\ngit push origin main"}},
            git_repo,
        )

        assert result.returncode == 0
        assert "chore(overseer): board snapshot" in self._log_messages(git_repo)

    def test_no_empty_commit_when_board_unchanged(self, git_repo):
        assert main(["--root", str(git_repo), "init"]) == 0
        assert main(["--root", str(git_repo), "new-card", "--title", "T"]) == 0

        payload = {"tool_input": {"command": "git push origin main"}}
        first = self._run_script(payload, git_repo)
        assert first.returncode == 0
        commits_after_first = self._log_messages(git_repo)
        assert "chore(overseer): board snapshot" in commits_after_first

        second = self._run_script(payload, git_repo)
        assert second.returncode == 0
        assert self._log_messages(git_repo) == commits_after_first

    def test_fails_open_when_claude_plugin_root_unset(self, git_repo):
        # `set -u` would otherwise abort the script with "unbound variable"
        # (exit 1) when CLAUDE_PLUGIN_ROOT is missing from the environment —
        # a PreToolUse hook exiting non-zero can BLOCK the tool call, which
        # violates the hard "never block a push" contract.
        assert main(["--root", str(git_repo), "init"]) == 0
        assert main(["--root", str(git_repo), "new-card", "--title", "T"]) == 0

        result = self._run_script(
            {"tool_input": {"command": "git push origin main"}},
            git_repo, set_plugin_root=False,
        )

        assert result.returncode == 0
        assert self._log_messages(git_repo) == []

    def test_worktree_push_snapshots_to_worktree_and_leaves_main_clean(self, git_repo):
        """Root-cause regression: the committed backup is a PER-WORKING-TREE,
        per-branch artifact — it must land on whichever branch you're about
        to `git push` from. A linked worktree pushes its OWN branch, so the
        snapshot must be written+committed under the WORKTREE's own
        `.overseer/backups`, never resolved against the main repo root (which
        would either dirty the main working tree or land the commit on the
        wrong branch). The shared, central board state (board.db, via
        OVERSEER_CENTRAL) is untouched by this — it stays keyed to the main
        root and is visible from both trees, which is exactly why the
        worktree's backup can see the card created against the main root."""
        assert main(["--root", str(git_repo), "init"]) == 0
        assert main(["--root", str(git_repo), "new-card", "--title", "T"]) == 0
        self._git(git_repo, "add", ".overseer/config.json")
        self._git(git_repo, "commit", "-q", "-m", "opt in to overseer")

        worktree = git_repo.parent / "wt"
        added = self._git(git_repo, "worktree", "add", "-b", "feature", str(worktree))
        assert added.returncode == 0, added.stderr

        result = self._run_script(
            {"tool_input": {"command": "git push origin feature"}}, worktree,
        )

        assert result.returncode == 0
        assert "chore(overseer): board snapshot" in self._log_messages(worktree)
        show = self._git(worktree, "show", "HEAD:.overseer/backups/cards.json")
        assert show.returncode == 0
        assert "WF-001" in show.stdout

        # written under the WORKTREE's own backups dir, not the main root's
        assert (worktree / ".overseer" / "backups" / "cards.json").exists()

        # the main working tree must never be dirtied by a push out of a
        # linked worktree
        main_status = self._git(git_repo, "status", "--porcelain", ".overseer/backups")
        assert main_status.stdout == ""
        assert not (git_repo / ".overseer" / "backups").exists()

    def test_snapshot_commit_excludes_other_staged_files(self, git_repo):
        """Root-cause regression: the commit used to be a bare `git commit`
        with no pathspec, so it swept EVERY staged file into the snapshot
        commit (and a gated push would then publish it). The commit must be
        scoped to the backup dir only, and must leave any other staged file
        exactly as it was — staged, uncommitted."""
        assert main(["--root", str(git_repo), "init"]) == 0
        assert main(["--root", str(git_repo), "new-card", "--title", "T"]) == 0
        (git_repo / "secret.txt").write_text("do-not-commit-me")
        self._git(git_repo, "add", "secret.txt")

        result = self._run_script(
            {"tool_input": {"command": "git push origin main"}}, git_repo,
        )

        assert result.returncode == 0
        assert "chore(overseer): board snapshot" in self._log_messages(git_repo)

        show = self._git(git_repo, "show", "--name-only", "--pretty=", "HEAD")
        files = [f for f in show.stdout.splitlines() if f]
        assert files
        assert all(f.startswith(".overseer/backups/") for f in files)
        assert "secret.txt" not in files

        # secret.txt must remain staged — the snapshot commit must not have
        # touched the rest of the index at all.
        staged = self._git(git_repo, "diff", "--cached", "--name-only")
        assert "secret.txt" in staged.stdout.splitlines()

    def test_git_dash_capital_c_push_triggers_snapshot(self, git_repo):
        """Push-detection regex must catch `git -C <dir> push`, not just a
        bare `git push`."""
        assert main(["--root", str(git_repo), "init"]) == 0
        assert main(["--root", str(git_repo), "new-card", "--title", "T"]) == 0

        result = self._run_script(
            {"tool_input": {"command": f"git -C {git_repo} push origin main"}},
            git_repo,
        )

        assert result.returncode == 0
        assert "chore(overseer): board snapshot" in self._log_messages(git_repo)

    def test_resolves_repo_root_from_payload_cwd_not_process_cwd(
        self, git_repo, tmp_path_factory
    ):
        """The hook must resolve the repo root from the JSON payload's `cwd`
        field (matching cli.py's `_hook_root` convention used by the sibling
        hooks), not from the hook process's own cwd — the two can differ.
        `elsewhere` must live outside `git_repo`'s own tree entirely (not
        just be a different subdirectory of it), or `git -C elsewhere`
        would still resolve up to the very same repo and the regression
        this test targets couldn't be observed."""
        assert main(["--root", str(git_repo), "init"]) == 0
        assert main(["--root", str(git_repo), "new-card", "--title", "T"]) == 0

        elsewhere = tmp_path_factory.mktemp("elsewhere")

        result = self._run_script(
            {"cwd": str(git_repo), "tool_input": {"command": "git push origin main"}},
            elsewhere,
        )

        assert result.returncode == 0
        assert "chore(overseer): board snapshot" in self._log_messages(git_repo)
        assert self._log_messages(elsewhere) == []

    def test_init_from_worktree_writes_config_at_canonical_root_and_hook_opts_in(
        self, git_repo
    ):
        """`cmd_init`, run from a linked worktree, must write config.json /
        config.local.json (and gitignore the local one) at the CANONICAL
        main root — not the worktree's own root — because that's also
        where the hook's opt-in gate looks. Config location, the gitignore
        line, and the opt-in gate must all agree on the same root, or
        opt-in from a worktree is incoherent."""
        (git_repo / "README.md").write_text("x")
        self._git(git_repo, "add", "README.md")
        self._git(git_repo, "commit", "-q", "-m", "init")

        # `git_repo.parent` is the shared pytest tmp root, not a per-test
        # dir (`git_repo` fixture == `tmp_path` itself) — a plain "wt" name
        # would collide with the sibling worktree test using the same
        # parent dir in the same test session.
        worktree = git_repo.parent / "wt-init-canonical-root"
        added = self._git(git_repo, "worktree", "add", "-b", "feature", str(worktree))
        assert added.returncode == 0, added.stderr

        assert main(["--root", str(worktree), "init", "--yes"]) == 0
        assert main(["--root", str(worktree), "new-card", "--title", "T"]) == 0

        # (a) config.json lands at the canonical (main) root, not the worktree
        assert (git_repo / ".overseer" / "config.json").exists()
        assert not (worktree / ".overseer" / "config.json").exists()

        # (b) the gitignore line for the local config lands at the canonical root
        assert ".overseer/config.local.json" in (git_repo / ".gitignore").read_text()

        # (c) the hook, fired from the worktree, sees the canonical root's
        # opt-in and DOES snapshot — opt-in is effective from a worktree.
        result = self._run_script(
            {"tool_input": {"command": "git push origin feature"}}, worktree,
        )
        assert result.returncode == 0
        assert "chore(overseer): board snapshot" in self._log_messages(worktree)
