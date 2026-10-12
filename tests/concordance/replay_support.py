"""Hand-built Claude Code transcripts for replay tests. Shapes copied from real transcripts:
assistant records carry message.content tool_use blocks; user records carry tool_result blocks."""
from __future__ import annotations

import json
import os
from pathlib import Path


class Transcript:
    def __init__(self, projects: Path, session_id: str, cwd: Path) -> None:
        self.dir = projects / "-fixture"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id
        self.cwd = str(cwd)
        self.records: list[dict[str, object]] = []
        self.agents: dict[str, list[dict[str, object]]] = {}
        self._n = 0

    def call(self, name: str, inp: dict[str, object], result: object,
             agent: str = "") -> str:
        self._n += 1
        tid = f"toolu_{self._n:04d}"
        target = self.agents.setdefault(agent, []) if agent else self.records
        target.append({"type": "assistant", "sessionId": self.session_id, "cwd": self.cwd,
                       "message": {"role": "assistant", "content": [
                           {"type": "tool_use", "id": tid, "name": name, "input": inp}]}})
        target.append({"type": "user", "sessionId": self.session_id, "cwd": self.cwd,
                       "message": {"role": "user", "content": [
                           {"type": "tool_result", "tool_use_id": tid, "content": result}]}})
        return tid

    def write(self, age_s: float = 3600.0, extra_lines: list[str] | None = None) -> Path:
        main = self.dir / f"{self.session_id}.jsonl"
        lines = [json.dumps(r) for r in self.records] + list(extra_lines or [])
        main.write_text("\n".join(lines) + "\n", encoding="utf-8")
        paths = [main]
        for agent, recs in self.agents.items():
            sub = self.dir / self.session_id / "subagents" / f"agent-{agent}.jsonl"
            sub.parent.mkdir(parents=True, exist_ok=True)
            sub.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
            paths.append(sub)
        for p in paths:
            t = p.stat().st_mtime - age_s
            os.utime(p, (t, t))
        return main
