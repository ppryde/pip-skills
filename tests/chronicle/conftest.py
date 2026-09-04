import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_chronicle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin every path chronicle resolves to this test's ``tmp_path``.

    ``CHRONICLE_DB`` is the store file; ``CLAUDE_CONFIG_DIR`` is where the
    projects (transcripts) dir is derived from. Without both, a test could
    read the developer's real transcripts or write a db into ``~/.claude``.
    """
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("CHRONICLE_DB", str(tmp_path / "config" / "chronicle" / "sessions.db"))


def _assistant(message_id: str, *, ts: str, model: str = "claude-opus-5", blocks=None,
               usage=None, session_id: str = "s1", agent_id: str | None = None, **extra):
    record = {
        "type": "assistant",
        "uuid": f"u-{message_id}-{len(blocks or [])}",
        "timestamp": ts,
        "sessionId": session_id,
        "cwd": "/repo",
        "gitBranch": "main",
        "version": "2.1.258",
        "entrypoint": "cli",
        "requestId": f"req-{message_id}",
        "message": {
            "id": message_id,
            "model": model,
            "role": "assistant",
            "content": blocks or [{"type": "text", "text": "hi"}],
            "stop_reason": "end_turn",
            "usage": usage or {
                "input_tokens": 3,
                "cache_read_input_tokens": 1000,
                "cache_creation_input_tokens": 200,
                "output_tokens": 40,
                "output_tokens_details": {"thinking_tokens": 10},
            },
        },
    }
    if agent_id:
        record["agentId"] = agent_id
        record["isSidechain"] = True
    record.update(extra)
    return record


def _user(uuid: str, *, ts: str, content="hello", session_id: str = "s1", **extra):
    record = {
        "type": "user",
        "uuid": uuid,
        "timestamp": ts,
        "sessionId": session_id,
        "cwd": "/repo",
        "gitBranch": "main",
        "version": "2.1.258",
        "entrypoint": "cli",
        "message": {"role": "user", "content": content},
    }
    record.update(extra)
    return record


class TranscriptBuilder:
    """Assemble a transcript JSONL (and optional subagent files) under a
    projects dir shaped exactly like ``~/.claude/projects/<slug>/``."""

    def __init__(self, projects: Path, slug: str = "-repo", session_id: str = "s1"):
        self.projects = projects
        self.session_id = session_id
        self.dir = projects / slug
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / f"{session_id}.jsonl"
        self.records: list = []

    def prompt(self, uuid: str, ts: str, text: str = "do it"):
        self.records.append(_user(uuid, ts=ts, content=text, session_id=self.session_id))
        return self

    def tool_result(self, uuid: str, ts: str, tool_use_id: str = "t1", content: str = "ok"):
        self.records.append(_user(
            uuid, ts=ts, session_id=self.session_id,
            content=[{"type": "tool_result", "tool_use_id": tool_use_id, "content": content}],
            toolUseResult={"stdout": content},
        ))
        return self

    def artifact(self, message_id: str, ts: str, *, tool_id: str, title: str = "Report",
                 action: str | None = None, url: str | None = None, **kw):
        """An Artifact tool call in its own turn, with the result the harness
        prints (the published URL) when ``url`` is given."""
        inp = {"file_path": "/tmp/x.html", "title": title, "favicon": "📊"}
        if action:
            inp["action"] = action
        if url and action is None:
            inp["url"] = url  # a redeploy names the existing url in the CALL
        blocks = [{"type": "tool_use", "id": tool_id, "name": "Artifact", "input": inp}]
        self.records.append(_assistant(message_id, ts=ts, blocks=blocks, session_id=self.session_id, **kw))
        return self

    def turn(self, message_id: str, ts: str, *, tools=(), split: bool = True, **kw):
        """One API call. With ``split`` (the real shape) every content block is
        its own JSONL line sharing the message id and usage."""
        blocks = [{"type": "text", "text": "thinking..."}]
        for i, name in enumerate(tools):
            blocks.append({"type": "tool_use", "id": f"{message_id}-tool{i}", "name": name, "input": {}})
        if split:
            for block in blocks:
                self.records.append(_assistant(message_id, ts=ts, blocks=[block],
                                               session_id=self.session_id, **kw))
        else:
            self.records.append(_assistant(message_id, ts=ts, blocks=blocks,
                                           session_id=self.session_id, **kw))
        return self

    def raw(self, record):
        self.records.append(record)
        return self

    def write(self) -> Path:
        self.path.write_text("".join(json.dumps(r) + "\n" for r in self.records))
        return self.path

    def append(self, record) -> None:
        with open(self.path, "a") as handle:
            handle.write(json.dumps(record) + "\n")

    def subagent(self, agent_id: str, message_ids: list[str], ts: str) -> Path:
        folder = self.dir / self.session_id / "subagents"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"agent-{agent_id}.jsonl"
        lines = [
            json.dumps(_assistant(mid, ts=ts, session_id=self.session_id, agent_id=agent_id))
            for mid in message_ids
        ]
        path.write_text("".join(line + "\n" for line in lines))
        return path


@pytest.fixture
def projects(tmp_path: Path) -> Path:
    path = tmp_path / "config" / "projects"
    path.mkdir(parents=True)
    return path


@pytest.fixture
def builder(projects: Path) -> TranscriptBuilder:
    return TranscriptBuilder(projects)
