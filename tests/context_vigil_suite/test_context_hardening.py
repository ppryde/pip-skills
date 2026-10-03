"""Confident/unconfident windows, locked session records, and measurement edge cases."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

from context_vigil import census, context, hooks, paths, session, transcript

from .conftest import SKILL
from .test_context_window import _identity, _ingest, _usage, _write


# --- I1: confident / unconfident window -----------------------------------------

def test_config_fallback_then_census_upgrades_and_fixes(repo: Path, iso: Path) -> None:
    path = _write(iso / "t.jsonl", [_usage(110_000)])
    assert context.current_percent(repo, "s", str(path), 200_000) == 55
    record = session.load("s")
    assert (record["window"], record["window_source"], record["window_confident"]) == (
        200_000, "config", False)
    _ingest(repo, "s", 1, size=1_000_000, now=time.time() - 60)   # transcript is newer
    assert context.current_percent(repo, "s", str(path), 200_000) == 11
    record = session.load("s")
    assert (record["window"], record["window_source"], record["window_confident"]) == (
        1_000_000, "census", True)
    _ingest(repo, "other", 1, size=200_000, model="claude-q")      # later learned: ignored
    assert context.current_percent(repo, "s", str(path), 200_000) == 11


def test_confident_1m_is_not_overridden_by_later_config_or_learned(repo: Path, iso: Path) -> None:
    path = _write(iso / "t.jsonl", [_identity("claude-opus[1m]"), _usage(100_000)])
    assert context.current_percent(repo, "s", str(path), 200_000) == 10
    assert session.load("s")["window_confident"] is True
    _ingest(repo, "other", 1, size=200_000, model="claude-opus")
    assert context.current_percent(repo, "s", str(path), 50_000) == 10


def test_confident_200k_widens_only_on_evidence(repo: Path, iso: Path) -> None:
    _ingest(repo, "s", 1, size=200_000, now=time.time() - 60)
    path = _write(iso / "t.jsonl", [_usage(100_000)])
    assert context.current_percent(repo, "s", str(path), 1_000_000) == 50
    with path.open("a") as fh:
        fh.write(_usage(300_000) + "\n")
    assert context.current_percent(repo, "s", str(path), 1_000_000) == 30
    record = session.load("s")
    assert (record["window"], record["window_source"], record["window_confident"]) == (
        1_000_000, "evidence", True)


def test_headless_unseen_model_stays_unconfident_on_config(repo: Path, iso: Path) -> None:
    path = _write(iso / "t.jsonl", [_identity("claude-new"), _usage(100_000)], "sdk-cli")
    for _ in range(2):
        assert context.current_percent(repo, "s", str(path), 200_000) == 50
    record = session.load("s")
    assert (record["window_source"], record["window_confident"]) == ("config", False)


# --- I2: atomic record updates and nudge gate -----------------------------------

_NUDGE = (
    "import json, os, sys, time\n"
    "from context_vigil import hooks, state\n"
    "real = state.set_gate\n"
    "def slow(scope):\n"
    "    time.sleep(0.05); real(scope)\n"
    "state.set_gate = slow\n"
    "payload = sys.stdin.read(); open(sys.argv[1], 'w').close()\n"
    "deadline = time.time() + 20\n"
    "while not os.path.exists(sys.argv[2]) and time.time() < deadline: pass\n"
    "out = hooks.nudge(json.loads(payload))\n"
    "print('NUDGED' if out else 'QUIET')"
)


def test_parallel_nudges_emit_exactly_once_and_keep_last_nudged(repo: Path, iso: Path) -> None:
    transcript_path = _write(iso / "t.jsonl", [_identity("claude-x[1m]"), _usage(750_000)])
    payload = json.dumps({"session_id": "s", "cwd": str(repo), "transcript_path": str(transcript_path),
                          "hook_event_name": "PostToolUse"})
    env = dict(os.environ, PYTHONPATH=str(SKILL / "scripts"), CONTEXT_VIGIL_THRESHOLD="40")
    go = iso / "go"
    readies = [iso / f"ready-{i}" for i in range(8)]
    procs: List[subprocess.Popen] = []
    try:
        for ready in readies:
            proc = subprocess.Popen([sys.executable, "-c", _NUDGE, str(ready), str(go)],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    env=env, text=True)
            proc.stdin.write(payload)
            proc.stdin.close()
            procs.append(proc)
        deadline = time.time() + 30
        while not all(r.exists() for r in readies):
            assert time.time() < deadline, "children never became ready"
            time.sleep(0.01)
        go.touch()
        outs = [proc.communicate(timeout=30)[0].strip() for proc in procs]
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
    assert outs.count("NUDGED") == 1, outs
    assert session.load("s")["last_nudged_pct"] == 75   # 750k of a [1m] window


def test_lock_failure_skips_the_update_and_never_raises(repo: Path, iso: Path, monkeypatch) -> None:
    path = _write(iso / "t.jsonl", [_usage(40_000)])
    monkeypatch.setattr(session, "_LOCK_ATTEMPTS", 2)
    monkeypatch.setattr(session, "_LOCK_DELAY_SECONDS", 0.001)
    import fcntl
    paths.sessions_dir().mkdir(parents=True, exist_ok=True)
    held = open(paths.session_lock_path("s"), "a")
    fcntl.flock(held, fcntl.LOCK_EX)
    try:
        assert context.current_percent(repo, "s", str(path), 200_000) == 20
        assert session.load("s")["transcript_offset"] is None      # nothing saved
        assert hooks.nudge({"session_id": "s", "cwd": str(repo),
                            "transcript_path": str(path)}) is None
    finally:
        held.close()


# --- M2: head read grows ----------------------------------------------------------

def test_large_first_record_still_detects_headless(repo: Path, iso: Path) -> None:
    path = iso / "t.jsonl"
    first = json.dumps({"type": "user", "text": "x" * 200_000, "entrypoint": "sdk-cli"})
    path.write_text(first + "\n" + _usage(1_000) + "\n")
    context.current_percent(repo, "s", str(path), 200_000)
    record = session.load("s")
    assert record["headless"] is True and record["head_checked"] is True


def test_unreadable_giant_head_is_marked_checked(repo: Path, iso: Path) -> None:
    path = iso / "t.jsonl"
    path.write_text("x" * (transcript.HEAD_CAP + 10))
    context.current_percent(repo, "s", str(path), 200_000)
    record = session.load("s")
    assert record["headless"] is None and record["head_checked"] is True


# --- M3: no transcript path -------------------------------------------------------

def test_cli_without_transcript_path_honours_the_staleness_horizon(repo: Path) -> None:
    _ingest(repo, "s", 42, now=time.time() - census.STALE_HORIZON_SECONDS - 60)
    assert context.current_percent(repo, "s", None, 200_000) is None
    _ingest(repo, "s", 42)
    assert context.current_percent(repo, "s", None, 200_000) == 42


# --- M4: replacement ----------------------------------------------------------------

def test_replaced_larger_file_resets_offset_and_peaks(repo: Path, iso: Path) -> None:
    path = _write(iso / "t.jsonl", [_usage(300_000)])
    assert context.current_percent(repo, "s", str(path), 200_000) == 30
    replacement = iso / "new.jsonl"
    _write(replacement, [_usage(10_000)] + [json.dumps({"type": "user", "t": "y" * 200})] * 10
           + [_usage(20_000)])
    os.replace(replacement, path)                      # same path, new inode, larger
    record = session.load("s")
    assert record["transcript_offset"] < path.stat().st_size
    context.current_percent(repo, "s", str(path), 200_000)
    record = session.load("s")
    assert record["last_usage_tokens"] == 20_000 and record["max_usage_tokens"] == 20_000


def test_path_change_resets_peaks(repo: Path, iso: Path) -> None:
    first = _write(iso / "a.jsonl", [_usage(300_000)])
    context.current_percent(repo, "s", str(first), 200_000)
    second = _write(iso / "b.jsonl", [_usage(10_000)])
    context.current_percent(repo, "s", str(second), 200_000)
    assert session.load("s")["max_usage_tokens"] == 10_000


# --- M5 / M6 / M7 -------------------------------------------------------------------

def test_freshness_tolerance_is_at_most_half_a_second() -> None:
    assert context._FRESH_TOLERANCE_SECONDS <= 0.5


def test_unreadable_usage_keeps_the_last_good_reading(repo: Path, iso: Path) -> None:
    path = _write(iso / "t.jsonl", [_usage(40_000)])
    assert context.current_percent(repo, "s", str(path), 200_000) == 20
    with path.open("a") as fh:
        fh.write(json.dumps({"message": {"usage": {"input_tokens": "NaN-ish"}}}) + "\n")
    assert context.current_percent(repo, "s", str(path), 200_000) == 20
    assert session.load("s")["last_usage_tokens"] == 40_000


def test_backward_scan_is_capped_and_progress_recorded(iso: Path) -> None:
    path = iso / "t.jsonl"
    filler = json.dumps({"type": "user", "text": "x" * 990}) + "\n"
    with open(path, "w") as f:
        for _ in range(20_000):                         # ~20 MB, no usage record at all
            f.write(filler)
    tail = transcript.read_tail(str(path))
    assert tail is not None and not tail.has_usage
    assert tail.bytes_read <= transcript.MAX_BACK + transcript.CHUNK
    assert tail.offset == path.stat().st_size            # next hook starts here, not at 0


# --- M8: has_statusline is load-bearing ----------------------------------------------

def test_census_is_not_consulted_before_the_first_ingest(repo: Path, iso: Path, monkeypatch) -> None:
    calls: List[Optional[str]] = []
    real = census.for_session
    monkeypatch.setattr(census, "for_session", lambda sid, *a, **k: (calls.append(sid), real(sid))[1])
    path = _write(iso / "t.jsonl", [_usage(40_000)])
    context.current_percent(repo, "s", str(path), 200_000)
    assert calls == []
    _ingest(repo, "s", 77, now=time.time() + 5)
    assert context.current_percent(repo, "s", str(path), 200_000) == 77
    assert calls == ["s"]


# --- round 3: N1 unconfident window, N2 lock scope, N3 rewrite, N4 prune, N5 wait ----

def _nudge_payload(repo: Path, path: Path) -> dict:
    return {"cwd": str(repo), "session_id": "s", "transcript_path": str(path),
            "hook_event_name": "UserPromptSubmit"}


def test_interactive_session_with_unconfirmed_window_gets_no_nudge(repo: Path, iso: Path) -> None:
    path = _write(iso / "t.jsonl", [_usage(150_000)])           # unknown model, 75% on config
    assert hooks.nudge(_nudge_payload(repo, path)) is None
    assert session.load("s")["last_nudged_pct"] is None
    from context_vigil import state
    assert not state.gate_active(paths.scope_dir(repo))
    _ingest(repo, "s", 15, size=1_000_000)                      # status line reports in: 15%
    assert hooks.nudge(_nudge_payload(repo, path)) is None


def test_headless_session_keeps_the_config_fallback_nudge(repo: Path, iso: Path) -> None:
    path = _write(iso / "t.jsonl", [_usage(150_000)], entrypoint="sdk-cli")
    out = hooks.nudge(_nudge_payload(repo, path))
    assert out is not None and "75%" in out
    assert session.load("s")["last_nudged_pct"] == 75


def test_context_line_marks_an_unconfirmed_window() -> None:
    assert context.context_line(75, 35, confident=False) == "ctx ~75% (window unconfirmed)"
    assert context.context_line(75, 35) == "ctx 75% — over the 35% threshold"


def test_reading_flags_the_config_fallback_as_unconfident(repo: Path, iso: Path) -> None:
    path = _write(iso / "t.jsonl", [_usage(150_000)])
    reading = context.current_reading(repo, "s", str(path), 200_000)
    assert reading.pct == 75 and reading.confident is False and reading.headless is False


def test_note_session_runs_outside_the_census_lock(repo: Path, monkeypatch) -> None:
    import fcntl
    held = []

    def probe(payload: dict) -> None:
        path = census.store_path()
        with open(path.with_name(path.name + ".lock"), "a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held.append(False)
            except OSError:
                held.append(True)
    monkeypatch.setattr(census, "_note_session", probe)
    _ingest(repo, "s", 10)
    assert held == [False]


def test_in_place_rewrite_with_new_head_resets_offset_and_peaks(repo: Path, iso: Path) -> None:
    path = _write(iso / "t.jsonl", [_usage(300_000)])
    context.current_percent(repo, "s", str(path), 200_000)
    ino = os.stat(path).st_ino
    with open(path, "w") as f:                                   # same inode, new session, larger
        f.write(json.dumps({"type": "user", "entrypoint": "cli", "sessionId": "other"}) + "\n")
        for _ in range(20):
            f.write(json.dumps({"type": "user", "t": "y" * 100}) + "\n")
        f.write(_usage(20_000) + "\n")
    assert os.stat(path).st_ino == ino
    context.current_percent(repo, "s", str(path), 200_000)
    record = session.load("s")
    assert record["last_usage_tokens"] == 20_000 and record["max_usage_tokens"] == 20_000


def test_shrunken_file_with_same_head_resets_peaks(repo: Path, iso: Path) -> None:
    path = _write(iso / "t.jsonl", [_usage(300_000)] + [json.dumps({"type": "user", "t": "z" * 50})] * 5)
    context.current_percent(repo, "s", str(path), 200_000)
    _write(path, [_usage(10_000)])                               # same head line, smaller
    context.current_percent(repo, "s", str(path), 200_000)
    assert session.load("s")["max_usage_tokens"] == 10_000


def test_prune_leaves_lock_files_of_live_records_alone(repo: Path) -> None:
    session.save("live", session.blank())
    with session.locked("live"):
        pass
    lock = paths.session_lock_path("live")
    scope_lock = paths.session_lock_path("_windows")
    scope_lock.write_text("")
    old = time.time() - 30 * 24 * 3600
    os.utime(lock, (old, old))
    os.utime(scope_lock, (old, old))
    session.prune()
    assert lock.exists() and scope_lock.exists()


def test_prune_removes_a_free_lock_with_its_pruned_record(repo: Path) -> None:
    session.save("ancient", session.blank())
    with session.locked("ancient"):
        pass
    old = time.time() - 8 * 24 * 3600
    os.utime(paths.session_record_path("ancient"), (old, old))
    session.prune()
    assert not paths.session_record_path("ancient").exists()
    assert not paths.session_lock_path("ancient").exists()


def test_prune_keeps_a_held_lock_of_a_pruned_record(repo: Path) -> None:
    session.save("ancient", session.blank())
    old = time.time() - 8 * 24 * 3600
    os.utime(paths.session_record_path("ancient"), (old, old))
    with session.locked("ancient") as got:
        assert got
        session.prune()
        assert paths.session_lock_path("ancient").exists()
    assert not paths.session_record_path("ancient").exists()


def test_hook_lock_wait_is_about_one_second() -> None:
    assert session._LOCK_ATTEMPTS * session._LOCK_DELAY_SECONDS <= 1.0
