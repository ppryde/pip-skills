"""Round-3 chunk E: filesystem-only worktree key, headless handoff location, census
ranking, message-model switch, child-session detection, snapshot budget, prune lock."""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, List

import pytest

from context_vigil import census, cli, context, hooks, paths, session, snapshot, state

from .test_context_window import _identity, _ingest, _usage, _write


# --- NEW-10: worktree_key is a pure filesystem walk-up ---------------------------

def _no_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> None:
        raise AssertionError("worktree_key must not spawn a subprocess")
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)


def test_worktree_key_never_calls_subprocess(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (repo / ".git").mkdir()
    sub = repo / "a"
    sub.mkdir()
    _no_subprocess(monkeypatch)
    assert paths.worktree_key(sub) == os.path.realpath(str(repo))


def test_worktree_key_normal_repo_and_subdir(repo: Path) -> None:
    (repo / ".git").mkdir()
    deep = repo / "a" / "b"
    deep.mkdir(parents=True)
    assert paths.worktree_key(deep) == os.path.realpath(str(repo))
    assert paths.worktree_key(repo) == os.path.realpath(str(repo))


def test_worktree_key_linked_worktree_is_its_own_root(repo: Path, iso: Path) -> None:
    (repo / ".git" / "worktrees" / "wt").mkdir(parents=True)
    wt = iso / "wt"
    (wt / "src").mkdir(parents=True)
    (wt / ".git").write_text(f"gitdir: {repo}/.git/worktrees/wt\n")
    assert paths.worktree_key(wt / "src") == os.path.realpath(str(wt))


def test_worktree_key_submodule_resolves_to_the_superproject(repo: Path) -> None:
    (repo / ".git" / "modules" / "sub").mkdir(parents=True)
    sub = repo / "sub"
    (sub / "pkg").mkdir(parents=True)
    (sub / ".git").write_text("gitdir: ../.git/modules/sub\n")
    assert paths.worktree_key(sub / "pkg") == os.path.realpath(str(repo))
    assert paths.worktree_key(sub) == paths.worktree_key(repo)


def test_worktree_key_orphan_submodule_keeps_its_own_dir(repo: Path) -> None:
    (repo / ".git").write_text("gitdir: /elsewhere/.git/modules/x\n")
    assert paths.worktree_key(repo) == os.path.realpath(str(repo))


def test_worktree_key_non_repo_is_the_resolved_cwd(repo: Path) -> None:
    (repo / "plain").mkdir()
    assert paths.worktree_key(repo / "plain") == os.path.realpath(str(repo / "plain"))


# --- NEW-2: the staleness horizon is applied BEFORE ranking -----------------------

def test_stale_active_sibling_does_not_hide_a_fresh_one(repo: Path) -> None:
    now = 1_000_000.0
    _ingest(repo, "A", 10, now=now - 600)
    _ingest(repo, "B", 70, now=now - 5)
    store = census._load(census.store_path())
    store["sessions"]["A"]["active_at"] = now - 300
    store["sessions"]["B"]["active_at"] = now - 7200
    census._atomic_write(census.store_path(), store)
    assert census.context_percent(repo, now=now) == 70


# --- NEW-3: a message.model change is a model change ------------------------------

def test_message_model_switch_alone_re_resolves_the_window(repo: Path, iso: Path) -> None:
    session.learn_window("claude-sonnet-5-5", 200_000)
    path = _write(iso / "t.jsonl", [_identity("claude-opus-5-5[1m]"),
                                    _usage(100_000, "claude-opus-5-5")])
    assert context.current_percent(repo, "S", str(path), 500_000) == 10
    assert session.load("S")["window"] == 1_000_000
    with open(path, "a") as f:
        f.write(_usage(100_000, "claude-sonnet-5-5") + "\n")      # /model sonnet: no new identity
    assert context.current_percent(repo, "S", str(path), 500_000) == 50
    record = session.load("S")
    assert record["window"] == 200_000 and record["model_id"] is None


# --- NEW-1: the headless handoff is per worktree, markers per session id ----------

def _headless(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "sdk-cli")


def _notes(iso: Path) -> Path:
    notes = iso / "notes.md"
    notes.write_text(
        "## Goal\nx\n\n## Current State\nx\n\n## Failed Attempts\n- none\n\n"
        "## Decisions\nx\n\n## Open Questions\nx\n\n## Next Step\ndo it\n")
    return notes


def test_headless_handoff_reaches_the_next_headless_session(
        repo: Path, iso: Path, run_cli, monkeypatch: pytest.MonkeyPatch) -> None:
    env = {"CLAUDE_CODE_ENTRYPOINT": "sdk-cli", "CLAUDE_SESSION_ID": "A"}
    saved = run_cli("handover", "--file", str(_notes(iso)), cwd=repo, env=env)
    assert saved.returncode == 0, saved.stderr
    assert "--resume" in saved.stdout and len(saved.stdout.strip().splitlines()) == 1
    assert "/clear" not in saved.stdout
    _headless(monkeypatch)
    out = hooks.session_start({"cwd": str(repo), "session_id": "B", "source": "startup"})
    assert out is not None and "handover --resume" in out
    loaded = run_cli("handover", "--resume", cwd=repo, env={**env, "CLAUDE_SESSION_ID": "B"})
    assert loaded.returncode == 0 and "do it" in loaded.stdout
    assert hooks.session_start({"cwd": str(repo), "session_id": "C", "source": "startup"}) is None


def test_headless_discard_by_a_later_session(repo: Path, iso: Path, run_cli) -> None:
    env = {"CLAUDE_CODE_ENTRYPOINT": "sdk-cli", "CLAUDE_SESSION_ID": "A"}
    run_cli("handover", "--file", str(_notes(iso)), cwd=repo, env=env)
    gone = run_cli("handover", "--discard", cwd=repo, env={**env, "CLAUDE_SESSION_ID": "B"})
    assert gone.returncode == 0
    again = run_cli("handover", "--resume", cwd=repo, env={**env, "CLAUDE_SESSION_ID": "B"})
    assert again.returncode != 0


def test_interactive_and_headless_handoffs_never_cross(
        repo: Path, iso: Path, run_cli, monkeypatch: pytest.MonkeyPatch) -> None:
    run_cli("handover", "--file", str(_notes(iso)), cwd=repo,
            env={"CLAUDE_CODE_ENTRYPOINT": "sdk-cli", "CLAUDE_SESSION_ID": "A"})
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
    assert hooks.session_start({"cwd": str(repo), "session_id": "I", "source": "startup"}) is None
    state.request_clear(paths.scope_dir(repo), "INTERACTIVE DOC")
    _headless(monkeypatch)
    out = hooks.session_start({"cwd": str(repo), "session_id": "B", "source": "startup"})
    assert out is not None and "INTERACTIVE DOC" not in out
    assert not state.clear_requested(paths.headless_scope(repo, "A"))


def test_headless_handover_keeps_markers_per_session_id(
        repo: Path, iso: Path, run_cli) -> None:
    run_cli("handover", "--file", str(_notes(iso)), cwd=repo,
            env={"CLAUDE_CODE_ENTRYPOINT": "sdk-cli", "CLAUDE_SESSION_ID": "A"})
    assert not state.clear_requested(paths.headless_scope(repo, "A"))
    assert not state.clear_requested(paths.scope_dir(repo))


# --- NEW-5: a child whose env lacks the entrypoint is detected from its transcript -

def test_child_detected_from_transcript_never_touches_the_parent_scope(
        repo: Path, iso: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXT_VIGIL_SESSION", "cc-repo-1")
    parent = paths.scope_dir(repo)
    state.request_clear(parent, "PARENT HANDOFF")
    state.set_gate(parent)
    before = sorted(p.name for p in parent.iterdir())
    transcript_path = _write(iso / "c.jsonl", [_usage(150_000)], "sdk-cli")
    child = {"cwd": str(repo), "session_id": "child", "transcript_path": str(transcript_path)}
    assert hooks.session_start({**child, "source": "startup"}) is None
    assert sorted(p.name for p in parent.iterdir()) == before
    out = hooks.nudge({**child, "hook_event_name": "PostToolUse"})
    assert out is not None                                   # the child is nudged ...
    assert sorted(p.name for p in parent.iterdir()) == before   # ... in its own scope
    assert state.gate_active(paths.headless_scope(repo, "child"))


# --- NEW-9: one git time budget per snapshot ------------------------------------

def test_snapshot_stops_calling_git_after_the_first_timeout(
        repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: List[Any] = []

    def slow(*args: Any, **kwargs: Any) -> Any:
        calls.append(args[0])
        if "--is-inside-work-tree" in args[0]:
            return subprocess.CompletedProcess(args[0], 0, "true\n", "")
        raise subprocess.TimeoutExpired(args[0], 1)

    monkeypatch.setattr(subprocess, "run", slow)
    text = snapshot.session_snapshot(repo)
    assert "Working directory" in text and "Working tree" not in text
    assert len(calls) == 2          # the probe, the first timeout, then nothing more
    snapshot.session_snapshot(repo)
    assert len(calls) == 4          # a new snapshot gets a new budget


# --- GEN-B1-015: a lock is unlinked only while it is held ------------------------

def test_prune_unlinks_a_lock_only_while_holding_it(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record = session.blank()
    session.save("old", record)
    lock = paths.session_lock_path("old")
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.touch()
    old = time.time() - session.RECORD_TTL_SECONDS - 100
    os.utime(paths.session_record_path("old"), (old, old))
    held: List[bool] = []
    real_unlink = Path.unlink

    def watching(self: Path, *a: Any, **k: Any) -> Any:
        if self == lock:
            with open(lock, "a") as probe:
                try:
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    held.append(False)           # we could take it: nobody holds it
                except OSError:
                    held.append(True)
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", watching)
    session.prune()
    assert held == [True] and not lock.exists()
