from __future__ import annotations

import json
import time
from pathlib import Path

from context_vigil import census, context


def _ingest(repo: Path, sid: str, pct: float) -> None:
    census.ingest(json.dumps({
        "session_id": sid, "workspace": {"current_dir": str(repo)},
        "context_window": {"used_percentage": pct},
    }))


def _transcript(tmp: Path, tokens: int) -> Path:
    path = tmp / "t.jsonl"
    path.write_text("\n".join([
        json.dumps({"message": {"usage": {"input_tokens": 1}}}),
        "not json",
        json.dumps({"message": {"usage": {
            "input_tokens": tokens, "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0}}}),
    ]) + "\n")
    return path


def test_census_by_session_wins(repo: Path) -> None:
    _ingest(repo, "a", 41.6)
    _ingest(repo, "b", 80)
    assert context.current_percent(repo, "a", None, 200000) == 42


def test_transcript_fallback_when_no_census(repo: Path, iso: Path) -> None:
    path = _transcript(iso, 50000)
    assert context.current_percent(repo, "zz", str(path), 200000) == 25


def test_transcript_fallback_when_census_stale(repo: Path, iso: Path) -> None:
    census.ingest(json.dumps({
        "session_id": "a", "workspace": {"current_dir": str(repo)},
        "context_window": {"used_percentage": 90},
    }), now=time.time() - 3600)
    path = _transcript(iso, 20000)
    assert context.current_percent(repo, "a", str(path), 200000) == 10


def test_no_reading_is_none(repo: Path) -> None:
    assert context.current_percent(repo, None, None, 200000) is None
    assert context.current_percent(repo, None, "/nope.jsonl", 200000) is None


def test_context_line() -> None:
    assert context.context_line(None, 35) == "ctx unknown"
    assert context.context_line(20, 35) == "ctx 20%"
    assert context.context_line(40, 35) == "ctx 40% — over the 35% threshold"
