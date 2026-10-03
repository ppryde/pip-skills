"""Transcript tail reading, window lookup chain, headless detection, census trust."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import List, Optional

from context_vigil import census, context, session, transcript


def _usage(tokens: int, model: Optional[str] = None) -> str:
    message: dict = {"usage": {"input_tokens": tokens}}
    if model:
        message["model"] = model
    return json.dumps({"type": "assistant", "message": message})


def _identity(model: str) -> str:
    return json.dumps({"type": "attachment",
                       "attachment": {"type": "identity", "identity": {"modelId": model}}})


def _write(path: Path, lines: List[str], entrypoint: Optional[str] = "cli") -> Path:
    head = [json.dumps({"type": "user", "entrypoint": entrypoint})] if entrypoint else []
    path.write_text("\n".join(head + lines) + "\n")
    return path


def _ingest(repo: Path, sid: str, pct: float, size: Optional[int] = None,
            model: Optional[str] = None, now: Optional[float] = None) -> None:
    payload: dict = {"session_id": sid, "workspace": {"current_dir": str(repo)},
                     "context_window": {"used_percentage": pct}}
    if size:
        payload["context_window"]["context_window_size"] = size
    if model:
        payload["model"] = {"id": model}
    census.ingest(json.dumps(payload), now=now)


# --- tail reading --------------------------------------------------------------

def test_large_transcript_reads_only_the_tail(iso: Path) -> None:
    path = iso / "big.jsonl"
    filler = json.dumps({"type": "user", "text": "x" * 990}) + "\n"
    with open(path, "w") as f:
        for _ in range(50_000):  # ~50 MB
            f.write(filler)
        f.write(_usage(60_000) + "\n")
    assert path.stat().st_size > 45_000_000
    start = time.monotonic()
    tail = transcript.read_tail(str(path))
    assert time.monotonic() - start < 2.0
    assert tail is not None and tail.tokens == 60_000
    assert tail.bytes_read < 1_000_000  # tail + a bounded model lookahead
    assert tail.offset == path.stat().st_size


def test_incremental_offset_reads_only_new_bytes(iso: Path) -> None:
    path = _write(iso / "t.jsonl", [_usage(10_000)])
    first = transcript.read_tail(str(path))
    assert first is not None and first.tokens == 10_000
    with open(path, "a") as f:
        f.write(_usage(30_000) + "\n")
    added = len(_usage(30_000)) + 1
    second = transcript.read_tail(str(path), first.offset)
    assert second is not None and second.tokens == 30_000
    assert second.bytes_read == added
    third = transcript.read_tail(str(path), second.offset)
    assert third is not None and not third.has_usage and third.bytes_read == 0


def test_partial_trailing_line_is_left_for_next_time(iso: Path) -> None:
    path = _write(iso / "t.jsonl", [_usage(10_000)])
    first = transcript.read_tail(str(path))
    assert first is not None
    half = _usage(40_000)
    with open(path, "a") as f:
        f.write(half[:15])
    mid = transcript.read_tail(str(path), first.offset)
    assert mid is not None and not mid.has_usage and mid.offset == first.offset
    with open(path, "a") as f:
        f.write(half[15:] + "\n")
    done = transcript.read_tail(str(path), mid.offset)
    assert done is not None and done.tokens == 40_000


def test_partial_trailing_line_on_first_read(iso: Path) -> None:
    path = _write(iso / "t.jsonl", [_usage(10_000)])
    with open(path, "a") as f:
        f.write('{"message": {"usage": {"input_tok')
    tail = transcript.read_tail(str(path))
    assert tail is not None and tail.tokens == 10_000
    assert tail.offset < path.stat().st_size


def test_truncated_file_restarts_from_the_tail(iso: Path) -> None:
    path = _write(iso / "t.jsonl", [_usage(10_000)] * 5)
    stale_offset = path.stat().st_size
    _write(path, [_usage(7_000)])
    assert path.stat().st_size < stale_offset
    tail = transcript.read_tail(str(path), stale_offset)
    assert tail is not None and tail.tokens == 7_000


def test_invalid_utf8_line_is_skipped_not_raised(iso: Path) -> None:
    path = iso / "t.jsonl"
    path.write_bytes(_usage(5_000).encode() + b"\n\xff\xfe broken\n")
    tail = transcript.read_tail(str(path))
    assert tail is not None and tail.tokens == 5_000


def test_unreadable_transcript_is_none(iso: Path) -> None:
    assert transcript.read_tail(str(iso / "missing.jsonl")) is None


def test_session_record_keeps_the_offset_between_calls(repo: Path, iso: Path) -> None:
    path = _write(iso / "t.jsonl", [_usage(40_000)])
    assert context.current_percent(repo, "s1", str(path), 200_000) == 20
    assert session.load("s1")["transcript_offset"] == path.stat().st_size
    with open(path, "a") as f:
        f.write(_usage(80_000) + "\n")
    assert context.current_percent(repo, "s1", str(path), 200_000) == 40


# --- window lookup chain -------------------------------------------------------

def test_window_from_learned_table(repo: Path, iso: Path) -> None:
    _ingest(repo, "other", 5, size=1_000_000, model="claude-x")
    path = _write(iso / "t.jsonl", [_identity("claude-x"), _usage(100_000)])
    assert context.current_percent(repo, "mine", str(path), 200_000) == 10
    record = session.load("mine")
    assert (record["window"], record["window_source"]) == (1_000_000, "learned")


def test_learned_table_matches_without_the_suffix(repo: Path, iso: Path) -> None:
    _ingest(repo, "other", 5, size=1_000_000, model="claude-x")
    path = _write(iso / "t.jsonl", [_identity("claude-x[1m]"), _usage(100_000)])
    assert context.current_percent(repo, "mine", str(path), 200_000) == 10


def test_window_from_1m_suffix(repo: Path, iso: Path) -> None:
    path = _write(iso / "t.jsonl", [_identity("claude-opus[1m]"), _usage(100_000)])
    assert context.current_percent(repo, "s", str(path), 200_000) == 10
    assert session.load("s")["window_source"] == "model-suffix"


def test_window_from_usage_evidence(repo: Path, iso: Path) -> None:
    path = _write(iso / "t.jsonl", [_usage(300_000)])
    assert context.current_percent(repo, "s", str(path), 200_000) == 30
    assert session.load("s")["window_source"] == "evidence"


def test_window_from_message_model_fallback(repo: Path, iso: Path) -> None:
    _ingest(repo, "other", 5, size=1_000_000, model="claude-y")
    path = _write(iso / "t.jsonl", [_usage(100_000, model="claude-y")])
    assert context.current_percent(repo, "mine", str(path), 200_000) == 10


def test_window_falls_back_to_config(repo: Path, iso: Path) -> None:
    path = _write(iso / "t.jsonl", [_usage(100_000)])
    assert context.current_percent(repo, "s", str(path), 200_000) == 50
    assert session.load("s")["window_source"] == "config"


def test_census_window_wins_even_when_stale(repo: Path, iso: Path) -> None:
    _ingest(repo, "s", 1, size=1_000_000, now=time.time() - 3600)
    path = _write(iso / "t.jsonl", [_usage(100_000)])
    assert context.current_percent(repo, "s", str(path), 200_000) == 10
    assert session.load("s")["window_source"] == "census"


def test_missing_or_renamed_identity_record_never_raises(repo: Path, iso: Path) -> None:
    odd = [json.dumps({"attachment": "str"}), json.dumps({"attachment": {"identity": 3}}),
           json.dumps({"attachment": {"identity": {"modelId": 7}}}), _usage(20_000)]
    path = _write(iso / "t.jsonl", odd)
    assert context.current_percent(repo, "s", str(path), 200_000) == 10


def test_ingest_learns_model_window(repo: Path) -> None:
    _ingest(repo, "a", 5, size=1_000_000, model="claude-z")
    assert session.windows() == {"claude-z": 1_000_000}
    assert session.lookup_window("claude-z[1m]") == 1_000_000


# --- headless / statusline -----------------------------------------------------

def test_headless_detection(repo: Path, iso: Path) -> None:
    for entrypoint, expected in (("sdk-cli", True), ("cli", False),
                                 ("claude-desktop", False), ("mystery", None)):
        sid = f"s-{entrypoint}"
        path = _write(iso / f"{entrypoint}.jsonl", [_usage(1_000)], entrypoint)
        context.current_percent(repo, sid, str(path), 200_000)
        assert session.load(sid)["headless"] is expected, entrypoint


def test_headless_session_skips_census(repo: Path, iso: Path) -> None:
    _ingest(repo, "s", 90)
    path = _write(iso / "t.jsonl", [_usage(20_000)], "sdk-cli")
    os.utime(path, (1, 1))  # even an unchanged transcript: headless never trusts census
    assert context.current_percent(repo, "s", str(path), 200_000) == 10


def test_missing_entrypoint_is_unknown_not_headless(repo: Path, iso: Path) -> None:
    path = _write(iso / "t.jsonl", [_usage(20_000)], entrypoint=None)
    context.current_percent(repo, "s", str(path), 200_000)
    record = session.load("s")
    assert record["headless"] is None and record["has_statusline"] is False


def test_ingest_marks_has_statusline(repo: Path) -> None:
    assert session.load("s")["has_statusline"] is False
    _ingest(repo, "s", 10)
    assert session.load("s")["has_statusline"] is True


# --- census trust --------------------------------------------------------------

def test_stale_but_unchanged_census_is_trusted(repo: Path, iso: Path) -> None:
    path = _write(iso / "t.jsonl", [_usage(20_000)])
    old = time.time() - 3600
    os.utime(path, (old - 10, old - 10))
    _ingest(repo, "s", 77, now=old)
    assert context.current_percent(repo, "s", str(path), 200_000) == 77


def test_transcript_newer_than_census_is_not_trusted(repo: Path, iso: Path) -> None:
    path = _write(iso / "t.jsonl", [_usage(20_000)])
    _ingest(repo, "s", 77, now=time.time() - 60)
    assert context.current_percent(repo, "s", str(path), 200_000) == 10


def test_old_session_records_are_pruned(repo: Path) -> None:
    session.save("ancient", session.blank())
    old = time.time() - 8 * 24 * 3600
    os.utime(paths_record("ancient"), (old, old))
    session.save("new", session.blank())
    assert not paths_record("ancient").exists()
    assert paths_record("new").exists()


def paths_record(sid: str) -> Path:
    from context_vigil import paths
    return paths.session_record_path(sid)
