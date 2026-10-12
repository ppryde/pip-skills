"""Read a session's transcripts in memory: tool calls paired with their results. Nothing read
here is ever written anywhere; callers keep only numbers derived from it."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from scripts.paths import config_dir

IDLE_S = 900.0  # chronicle's live horizon: a transcript idle this long is finished


@dataclass(frozen=True)
class ToolCall:
    tool_use_id: str
    agent_id: str          # "" for the main agent, else the subagent file's agent id
    name: str
    input: dict[str, object]
    result_text: str       # text blocks of the tool_result joined with "\n"; "" if none
    cwd: str               # the record's cwd, "" if absent
    seq: int               # order within its agent's transcript, from 0


@dataclass
class Session:
    session_id: str
    calls: list[ToolCall] = field(default_factory=list)
    bad_lines: int = 0


def session_files(session_id: str, projects: Path | None = None,
                  main: Path | None = None) -> list[tuple[str, Path]]:
    if main is None:
        root = projects or config_dir() / "projects"
        mains = sorted(root.glob(f"*/{session_id}.jsonl"))
        if not mains:
            raise FileNotFoundError(f"no transcript for session {session_id} under {root}")
        main = mains[0]
    elif not main.is_file():
        raise FileNotFoundError(f"no transcript at {main}")
    files: list[tuple[str, Path]] = [("", main)]
    for sub in sorted((main.parent / session_id / "subagents").glob("agent-*.jsonl")):
        files.append((sub.stem.removeprefix("agent-"), sub))
    return files


def is_finished(files: list[tuple[str, Path]], now: float | None = None) -> bool:
    t = time.time() if now is None else now
    return all(t - p.stat().st_mtime >= IDLE_S for _, p in files)


def _text_of(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b["text"] for b in content
                         if isinstance(b, dict) and b.get("type") == "text"
                         and isinstance(b.get("text"), str))
    return ""


def _blocks(record: dict[str, object]) -> list[dict[str, object]]:
    msg = record.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def load(session_id: str, files: list[tuple[str, Path]]) -> Session:
    session = Session(session_id)
    for agent_id, path in files:
        pending: dict[str, tuple[str, dict[str, object], str]] = {}
        order: list[str] = []
        results: dict[str, str] = {}
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    session.bad_lines += 1
                    continue
                if not isinstance(rec, dict):
                    session.bad_lines += 1
                    continue
                cwd = rec.get("cwd") if isinstance(rec.get("cwd"), str) else ""
                for b in _blocks(rec):
                    use_id, result_id = b.get("id"), b.get("tool_use_id")
                    if b.get("type") == "tool_use" and isinstance(use_id, str):
                        inp = b.get("input")
                        pending[use_id] = (str(b.get("name", "")),
                                           inp if isinstance(inp, dict) else {}, str(cwd))
                        order.append(use_id)
                    elif b.get("type") == "tool_result" and isinstance(result_id, str):
                        results[result_id] = _text_of(b.get("content"))
        for seq, tid in enumerate(order):
            name, inp, cwd = pending[tid]
            session.calls.append(ToolCall(tid, agent_id, name, inp, results.get(tid, ""),
                                          cwd, seq))
    return session
