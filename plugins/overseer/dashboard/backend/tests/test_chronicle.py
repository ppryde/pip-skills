"""`/api/chronicle/*` — the optional session-telemetry page's API.

chronicle is a SOFT sibling-plugin dependency: every route must degrade to an
"unavailable" shape (never 500) when the plugin is missing or its store is
empty, and must read from the CHRONICLE_DB the conftest pins to tmp_path.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import cli_client

_CHRONICLE_CLI = Path(__file__).resolve().parents[4] / "chronicle" / "scripts" / "cli.py"


def _record(kind: str, uuid: str, ts: str, **extra: object) -> dict[str, object]:
    base: dict[str, object] = {
        "type": kind, "uuid": uuid, "timestamp": ts, "sessionId": "sess1",
        "cwd": "/repo", "gitBranch": "main", "version": "2.1.258", "entrypoint": "cli",
    }
    base.update(extra)
    return base


def _seed(root: Path, tmp_path: Path, *, repo_root: str) -> None:
    """Write a two-turn transcript and ingest it via chronicle's CLI, then
    stamp the repo root (the transcript's cwd isn't a git repo)."""
    transcript = tmp_path / "projects" / "-repo" / "sess1.jsonl"
    transcript.parent.mkdir(parents=True)
    usage = {"input_tokens": 5, "cache_read_input_tokens": 500,
             "cache_creation_input_tokens": 50, "output_tokens": 20}
    records = [
        _record("user", "u1", "2026-09-01T10:00:00Z", message={"role": "user", "content": "hi"}),
        _record("assistant", "a1", "2026-09-01T10:00:05Z", message={
            "id": "m1", "model": "claude-opus-5", "role": "assistant", "usage": usage,
            "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]}),
        _record("assistant", "a2", "2026-09-01T10:00:09Z", message={
            "id": "m2", "model": "claude-opus-5", "role": "assistant", "usage": usage,
            "content": [{"type": "text", "text": "done"}]}),
    ]
    transcript.write_text("".join(json.dumps(r) + "\n" for r in records))
    subprocess.run(
        [sys.executable, str(_CHRONICLE_CLI), "ingest", "--transcript", str(transcript)],
        check=True, capture_output=True, text=True, env=dict(os.environ),
    )
    import sqlite3
    conn = sqlite3.connect(os.environ["CHRONICLE_DB"])
    conn.execute("UPDATE sessions SET repo_root = ?", (repo_root,))
    conn.commit()
    conn.close()


def test_sync_pulls_new_transcripts(client: TestClient, root: Path, tmp_path: Path,
                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /api/chronicle/sync ingests what's on disk under the (pinned)
    config dir's projects folder, and reports what changed."""
    projects = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects"
    transcript = projects / "-repo" / "sess1.jsonl"
    transcript.parent.mkdir(parents=True)
    usage = {"input_tokens": 1, "cache_read_input_tokens": 10,
             "cache_creation_input_tokens": 1, "output_tokens": 2}
    transcript.write_text(json.dumps(_record("assistant", "a1", "2026-09-01T10:00:05Z", message={
        "id": "m1", "model": "claude-opus-5", "role": "assistant", "usage": usage,
        "content": [{"type": "text", "text": "hi"}]})) + "\n")

    first = client.post("/api/chronicle/sync")
    assert first.status_code == 200
    body = first.json()
    assert body["sessions"] == ["sess1"]
    assert body["changed"] == 1
    assert body["synced_at"] > 0

    again = client.post("/api/chronicle/sync").json()
    assert again["changed"] == 0
    status = client.get("/api/chronicle/status").json()
    assert status["turns"] == 1
    assert status["synced_at"] == again["synced_at"]


def test_sync_is_not_token_gated(root: Path) -> None:
    # Deliberate: sync writes only what the transcripts already say, is
    # idempotent and cheap, so the page's timed sync must work from a browser
    # that can read the page but holds no token. Board mutations stay gated.
    from app.main import create_app
    gated = TestClient(create_app(root, token="secret"))
    assert gated.post("/api/chronicle/sync").status_code == 200
    assert gated.post("/api/chronicle/sync", headers={"X-Overseer-Token": "secret"}).status_code == 200


def test_status_reports_missing_store(client: TestClient) -> None:
    body = client.get("/api/chronicle/status").json()
    assert body["installed"] is True
    assert body["exists"] is False


def test_status_after_seed(client: TestClient, root: Path, tmp_path: Path) -> None:
    _seed(root, tmp_path, repo_root=str(root.resolve()))
    body = client.get("/api/chronicle/status").json()
    assert body["installed"] is True
    assert body["exists"] is True
    assert body["sessions"] == 1
    assert body["turns"] == 2


def test_summary_and_sessions_scoped_to_launch_root(client: TestClient, root: Path,
                                                    tmp_path: Path) -> None:
    _seed(root, tmp_path, repo_root=str(root.resolve()))
    summary = client.get("/api/chronicle/summary").json()
    assert summary["totals"]["sessions"] == 1
    assert summary["totals"]["turns"] == 2
    assert summary["totals"]["cache_read_tokens"] == 1000
    assert summary["tools"] == [{"tool_name": "Bash", "calls": 1, "sessions": 1}]
    sessions = client.get("/api/chronicle/sessions").json()["sessions"]
    assert [s["session_id"] for s in sessions] == ["sess1"]
    assert sessions[0]["repo_root"] == str(root.resolve())


def test_other_repo_is_hidden_unless_scope_all(client: TestClient, root: Path,
                                               tmp_path: Path) -> None:
    _seed(root, tmp_path, repo_root="/somewhere/else")
    assert client.get("/api/chronicle/summary").json()["totals"]["sessions"] == 0
    assert client.get("/api/chronicle/sessions").json()["sessions"] == []
    assert client.get("/api/chronicle/summary?scope=all").json()["totals"]["sessions"] == 1
    assert len(client.get("/api/chronicle/sessions?scope=all").json()["sessions"]) == 1


def test_branch_filter(client: TestClient, root: Path, tmp_path: Path) -> None:
    # The seeded transcript records gitBranch "main" on every line.
    _seed(root, tmp_path, repo_root=str(root.resolve()))
    assert client.get("/api/chronicle/summary?branch=main").json()["totals"]["sessions"] == 1
    assert client.get("/api/chronicle/summary?branch=feat/other").json()["totals"]["sessions"] == 0
    assert client.get("/api/chronicle/sessions?branch=main").json()["sessions"][0]["git_branch"] == "main"
    assert client.get("/api/chronicle/sessions?branch=feat/other").json()["sessions"] == []
    # Composes with scope=all, and an absurd value is refused rather than passed on.
    assert client.get("/api/chronicle/summary?scope=all&branch=main").json()["totals"]["sessions"] == 1
    assert client.get(f"/api/chronicle/summary?branch={'x' * 300}").status_code == 400


def test_days_window(client: TestClient, root: Path, tmp_path: Path) -> None:
    _seed(root, tmp_path, repo_root=str(root.resolve()))
    # The seeded session is dated 2026-09-01; a 1-day window from "now"
    # (test time is later) excludes it, an enormous window includes it.
    assert client.get("/api/chronicle/summary?days=1").json()["totals"]["sessions"] == 0
    assert client.get("/api/chronicle/summary?days=3650").json()["totals"]["sessions"] == 1
    assert client.get("/api/chronicle/summary?days=0").status_code == 400
    assert client.get("/api/chronicle/sessions?limit=0").status_code == 400


def test_unknown_root_is_400(client: TestClient) -> None:
    resp = client.get("/api/chronicle/summary?root=/not/allowed")
    assert resp.status_code == 400


def test_session_detail(client: TestClient, root: Path, tmp_path: Path) -> None:
    _seed(root, tmp_path, repo_root=str(root.resolve()))
    detail = client.get("/api/chronicle/session/sess1").json()
    assert detail["session_id"] == "sess1"
    assert [t["context_tokens"] for t in detail["turn_series"]] == [555, 555]
    assert detail["tools"] == [{"tool_name": "Bash", "calls": 1}]


def test_session_detail_missing_and_invalid(client: TestClient) -> None:
    assert client.get("/api/chronicle/session/nope").status_code == 404
    assert client.get("/api/chronicle/session/..%2Fetc").status_code in (400, 404)


def test_plugin_absent_degrades(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_client, "_CHRONICLE_CLI", Path("/nonexistent/cli.py"))
    assert client.get("/api/chronicle/status").json() == {"installed": False, "exists": False}
    assert client.get("/api/chronicle/summary").json() == {"totals": None}
    assert client.get("/api/chronicle/sessions").json() == {"sessions": []}
    assert client.get("/api/chronicle/session/sess1").status_code == 404
    assert client.post("/api/chronicle/sync").status_code == 503


def test_sync_refuses_to_overlap(client: TestClient, root: Path, tmp_path: Path) -> None:
    """The ungated sync runs one at a time per server: a second request while
    one is in flight is told to come back (429), never a second subprocess
    racing the same store."""
    _seed(root, tmp_path, repo_root=str(root.resolve()))
    lock = client.app.state.chronicle_sync_lock
    assert lock.acquire(blocking=False)
    try:
        assert client.post("/api/chronicle/sync").status_code == 429
    finally:
        lock.release()
    assert client.post("/api/chronicle/sync").status_code == 200


class TestChronicleOnlyRoots:
    """WF-108. Chronicle records sessions for any repo Claude Code ran in,
    board or no board. Refusing to NAME those made the largest repo in a real
    store reachable only under "All repos" — present in the data, unreachable
    from the UI. The chronicle routes now validate against the union of board
    roots and chronicle's own; the board's routes are deliberately unchanged.
    """

    def _boardless(self, tmp_path: Path) -> Path:
        other = tmp_path / "boardless-repo"
        other.mkdir()
        return other.resolve()

    def test_chronicle_can_be_scoped_to_a_repo_with_no_board(
        self, client: TestClient, root: Path, tmp_path: Path
    ) -> None:
        other = self._boardless(tmp_path)
        _seed(root, tmp_path, repo_root=str(other))

        body = client.get("/api/chronicle/sessions", params={"root": str(other)})
        assert body.status_code == 200          # was 400 "unknown root"
        assert [s["repo_root"] for s in body.json()["sessions"]] == [str(other)]

        summary = client.get("/api/chronicle/summary", params={"root": str(other)})
        assert summary.status_code == 200
        assert summary.json()["totals"]["sessions"] == 1

    def test_the_board_still_refuses_that_root(
        self, client: TestClient, root: Path, tmp_path: Path
    ) -> None:
        # The point of the change is that ONE route family widened. A root with
        # no board.db has no board to serve, and this server can bind 0.0.0.0
        # with no auth — so /api/board must still refuse it.
        other = self._boardless(tmp_path)
        _seed(root, tmp_path, repo_root=str(other))
        assert client.get("/api/board", params={"root": str(other)}).status_code == 400
        assert client.get("/api/sessions", params={"root": str(other)}).status_code == 400

    def test_a_root_neither_source_knows_is_still_refused(
        self, client: TestClient, root: Path, tmp_path: Path
    ) -> None:
        _seed(root, tmp_path, repo_root=str(root.resolve()))
        stranger = tmp_path / "never-heard-of-it"
        stranger.mkdir()
        for route in ("/api/chronicle/sessions", "/api/chronicle/summary"):
            resp = client.get(route, params={"root": str(stranger)})
            assert resp.status_code == 400, route
            assert "unknown root" in resp.json()["detail"]

    def test_repos_lists_a_chronicle_only_root_and_flags_it(
        self, client: TestClient, root: Path, tmp_path: Path
    ) -> None:
        other = self._boardless(tmp_path)
        _seed(root, tmp_path, repo_root=str(other))
        # Keyed by root, not label: `derive_repo_label` resolves a tmp dir to
        # its parent's name, which is a fixture artefact, not the thing under test.
        repos = {r["root"]: r for r in client.get("/api/repos").json()["repos"]}
        entry = repos[str(other)]
        assert entry["has_board"] is False       # no board.db — the holding page still applies
        assert entry["chronicled"] is True       # but the Chronicle may be scoped to it
        assert entry["live_sessions"] == 0       # census knows nothing of it
