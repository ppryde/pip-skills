"""Round-2 chunk F: window resolution, entrypoints, CLI transcript, census ranking."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import Any, List, Optional

import pytest

from context_vigil import census, context, session, transcript

from .test_context_window import _identity, _ingest, _usage, _write


# --- GEN-I-003: an explicit [1m] suffix wins -----------------------------------

def test_suffixed_model_never_falls_back_to_the_bare_learned_window() -> None:
    session.learn_window("claude-opus-4-6", 200_000)
    assert session.lookup_window("claude-opus-4-6[1m]") is None
    size, source, confident = context.resolve_window(
        None, {"model_id": "claude-opus-4-6[1m]"}, 200_000)
    assert (size, confident) == (1_000_000, True) and source == "model-suffix"


def test_suffixed_identity_beats_bare_message_model(repo: Path, iso: Path) -> None:
    session.learn_window("claude-opus-4-6", 200_000)
    path = _write(iso / "t.jsonl", [_identity("claude-opus-4-6[1m]"),
                                    _usage(70_000, "claude-opus-4-6")])
    assert context.current_percent(repo, "S", str(path), 200_000) == 7
    assert session.load("S")["window"] == 1_000_000


def test_suffixed_exact_entry_still_used() -> None:
    session.learn_window("m[1m]", 1_000_000)
    assert session.lookup_window("m[1m]") == 1_000_000


# --- owner decision 3: a model switch re-resolves the window -------------------

def test_model_switch_re_resolves_a_fixed_window(repo: Path, iso: Path) -> None:
    session.learn_window("big[1m]", 1_000_000)
    session.learn_window("small", 200_000)
    path = _write(iso / "t.jsonl", [_identity("big[1m]"), _usage(100_000)])
    assert context.current_percent(repo, "S", str(path), 500_000) == 10
    record = session.load("S")
    assert record["window"] == 1_000_000 and record["window_model"] == "big[1m]"
    with open(path, "a") as f:
        f.write(_identity("small") + "\n" + _usage(100_000) + "\n")
    assert context.current_percent(repo, "S", str(path), 500_000) == 50
    record = session.load("S")
    assert record["window"] == 200_000 and record["window_model"] == "small"


def test_same_model_keeps_the_fixed_window(repo: Path, iso: Path) -> None:
    session.learn_window("small", 200_000)
    path = _write(iso / "t.jsonl", [_identity("small"), _usage(100_000)])
    context.current_percent(repo, "S", str(path), 500_000)
    session.learn_window("small", 1_000_000)   # a later learned change must not move it
    with open(path, "a") as f:
        f.write(_usage(120_000) + "\n")
    assert context.current_percent(repo, "S", str(path), 500_000) == 60


def test_census_model_change_re_resolves(repo: Path, iso: Path) -> None:
    session.learn_window("small", 200_000)
    path = _write(iso / "t.jsonl", [_usage(100_000)])
    _ingest(repo, "S", 10, size=1_000_000, model="big[1m]")
    os.utime(path, (1, 1))
    context.current_percent(repo, "S", str(path), 500_000)
    os.utime(path, None)
    _ingest(repo, "S", 50, size=200_000, model="small", now=os.stat(path).st_mtime - 5)
    # force the transcript path: census is behind a newer transcript
    assert context.current_percent(repo, "S", str(path), 500_000) == 50
    assert session.load("S")["window"] == 200_000


# --- GEN-I-005: entrypoints -----------------------------------------------------

@pytest.mark.parametrize("entrypoint,expected", [
    ("sdk-cli", True), ("sdk-ts", True), ("sdk-py", True),
    ("cli", False), ("claude-vscode", False), ("claude-desktop", False), ("mystery", None)])
def test_transcript_entrypoints(iso: Path, entrypoint: str, expected: Optional[bool]) -> None:
    path = _write(iso / "t.jsonl", [_usage(1)], entrypoint)
    assert transcript.read_entrypoint(str(path)) == (True, expected)


def test_hook_env_entrypoint_wins_over_the_head(repo: Path, iso: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "sdk-py")
    path = _write(iso / "t.jsonl", [_usage(1_000)], None)   # head says nothing
    reading = context.current_reading(repo, "S", str(path), 200_000)
    assert reading.headless is True and session.load("S")["headless"] is True


# --- GEN-I-006 / B2-017: context/status use the record's transcript -------------

def test_cli_context_reads_the_recorded_transcript(run_cli, repo: Path, iso: Path) -> None:
    path = _write(iso / "t.jsonl", [_usage(100_000)], "sdk-cli")
    assert context.current_percent(repo, "H1", str(path), 200_000) == 50
    out = run_cli("context", "--session-id", "H1", cwd=repo)
    assert "50%" in out.stdout and "unknown" not in out.stdout


def test_current_reading_without_path_uses_the_record(repo: Path, iso: Path) -> None:
    path = _write(iso / "t.jsonl", [_usage(100_000)], "sdk-cli")
    context.current_percent(repo, "H1", str(path), 200_000)
    assert context.current_percent(repo, "H1", None, 200_000) == 50


# --- GEN-B1-003 / B2-012: census ranking -----------------------------------------

def test_fresh_entry_ranks_by_activity_not_timer_rerun(repo: Path) -> None:
    now = 1_000_000.0
    _ingest(repo, "working", 70, now=now - 30)
    _ingest(repo, "idle", 10, now=now - 60)
    for sid, active in (("working", now - 30), ("idle", now - 3000)):
        store = census._load(census.store_path())
        store["sessions"][sid]["active_at"] = active
        census._atomic_write(census.store_path(), store)
    store = census._load(census.store_path())
    store["sessions"]["idle"]["updated_at"] = now - 1       # timer rerun: newest write
    census._atomic_write(census.store_path(), store)
    assert census.context_percent(repo, now=now) == 70


def test_session_id_without_own_entry_never_reads_a_sibling(repo: Path) -> None:
    _ingest(repo, "sibling", 77)
    assert census.context_percent(repo, session_id="missing") is None


# --- GEN-B2-002 / B1-002: no subprocess under the census lock -------------------

def test_git_branch_runs_outside_the_census_lock(repo: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    free: List[bool] = []

    def probe(_cwd: Any) -> None:
        lock = census.store_path().with_name(census.store_path().name + ".lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        with open(lock, "a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                free.append(True)
                fcntl.flock(handle, fcntl.LOCK_UN)
            except OSError:
                free.append(False)
        return None

    monkeypatch.setattr(census, "_git_branch", probe)
    _ingest(repo, "S", 10)
    assert free == [True]


# --- GEN-B1-004: a carried-forward reading is not a fresh one ---------------------

def test_carried_context_is_not_trusted_as_census(repo: Path, iso: Path) -> None:
    path = _write(iso / "t.jsonl", [_usage(20_000)])
    _ingest(repo, "S", 70, size=200_000)
    census.ingest(json.dumps({"session_id": "S", "workspace": {"current_dir": str(repo)}}))
    store = census._load(census.store_path())
    assert store["sessions"]["S"].get("carried") is True
    session.mark_statusline("S")
    assert census.context_percent(repo, session_id="S") is None
    assert context.current_percent(repo, "S", str(path), 200_000) == 10


# --- GEN-B2-009: an unsettled head is re-checked, boundedly -----------------------

def test_partial_head_is_rechecked_then_detected(repo: Path, iso: Path) -> None:
    path = iso / "t.jsonl"
    full = json.dumps({"type": "user", "entrypoint": "sdk-cli"})
    path.write_text(full[:20])                     # first line still being written
    context.current_percent(repo, "S", str(path), 200_000)
    record = session.load("S")
    assert record["head_checked"] is False and record["headless"] is None
    path.write_text(full + "\n" + _usage(1_000) + "\n")
    context.current_percent(repo, "S", str(path), 200_000)
    record = session.load("S")
    assert record["head_checked"] is True and record["headless"] is True


def test_unsettled_head_gives_up_after_a_few_hooks(repo: Path, iso: Path) -> None:
    path = iso / "t.jsonl"
    path.write_text('{"type": "user", "entry')
    for _ in range(8):
        context.current_percent(repo, "S", str(path), 200_000)
    assert session.load("S")["head_checked"] is True
