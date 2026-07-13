import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.cli import main
from scripts.models import Card
from scripts.store import find_card_path, state_root

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
HOOK_SCRIPT = PLUGIN_ROOT / "hooks" / "checklist-sync.sh"
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
    return Card.from_text(find_card_path(state_root(repo), card_id).read_text()).checklist


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
        result = self._run_script(payload, env, tmp_path)
        assert result.returncode == 0
        assert _checklist(tmp_path) == [
            {"task": "7", "subject": "write tests", "status": "pending"},
        ]
