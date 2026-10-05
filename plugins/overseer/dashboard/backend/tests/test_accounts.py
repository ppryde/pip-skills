"""WF-116 multi-account support: `GET /api/accounts` (the union of chronicle's
account history and every watched config dir's current login), the
`account=` filter on `/api/sessions` (live census sessions), and the same
filter passed through to `/api/chronicle/summary`+`/api/chronicle/sessions`.

Every uuid/plan here is obviously fake (public repo) — see chronicle's own
`tests/chronicle/test_ingest.py` for the same convention.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import cli_client

_CHRONICLE_CLI = cli_client.find_plugin("chronicle")


def _record(kind: str, uuid: str, ts: str, **extra: object) -> dict[str, object]:
    base: dict[str, object] = {
        "type": kind, "uuid": uuid, "timestamp": ts, "sessionId": "sess1",
        "cwd": "/repo", "gitBranch": "main", "version": "2.1.258", "entrypoint": "cli",
    }
    base.update(extra)
    return base


def _ingest_one_session(tmp_path: Path, session_id: str = "sess1") -> None:
    """Write and ingest a two-line transcript under chronicle's pinned
    CHRONICLE_DB/CLAUDE_CONFIG_DIR (same shape as test_chronicle.py's
    `_seed`, minus the repo_root stamp — accounts don't need one)."""
    transcript = tmp_path / "projects" / "-repo" / f"{session_id}.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    usage = {"input_tokens": 1, "cache_read_input_tokens": 1,
              "cache_creation_input_tokens": 1, "output_tokens": 1}
    records = [
        _record("user", f"u-{session_id}", "2026-09-01T10:00:00Z",
                 sessionId=session_id, message={"role": "user", "content": "hi"}),
        _record("assistant", f"a-{session_id}", "2026-09-01T10:00:05Z", sessionId=session_id, message={
            "id": f"m-{session_id}", "model": "claude-opus-5", "role": "assistant", "usage": usage,
            "content": [{"type": "text", "text": "hi"}]}),
    ]
    transcript.write_text("".join(json.dumps(r) + "\n" for r in records))
    subprocess.run(
        [sys.executable, str(_CHRONICLE_CLI), "ingest", "--transcript", str(transcript)],
        check=True, capture_output=True, text=True, env=dict(os.environ),
    )


def _stamp_account(session_id: str, account_uuid: str) -> None:
    """Force a session's `account_uuid` directly — used for the "chronicle
    knows this uuid but no dir is currently logged into it" case, which a
    real ingest (needing a live `.claude.json`) can't produce on demand."""
    conn = sqlite3.connect(os.environ["CHRONICLE_DB"])
    conn.execute("UPDATE sessions SET account_uuid = ? WHERE session_id = ?",
                 (account_uuid, session_id))
    conn.commit()
    conn.close()


def _write_oauth(config_dir: Path, account_uuid: str, plan: str | None = None) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    oauth: dict[str, str] = {"accountUuid": account_uuid, "emailAddress": "nope@example.invalid"}
    if plan:
        oauth["organizationType"] = plan
    (config_dir / ".claude.json").write_text(json.dumps({"oauthAccount": oauth}))


def test_accounts_empty_by_default(client: TestClient) -> None:
    assert client.get("/api/accounts").json() == {"accounts": []}


def test_accounts_lists_live_login_with_no_chronicle_history(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dir = Path(os.environ["CLAUDE_CONFIG_DIR"])
    _write_oauth(config_dir, "11111111-uuid", plan="claude_max")

    body = client.get("/api/accounts").json()

    assert body["accounts"] == [{
        "account_uuid": "11111111-uuid",
        "short_uuid": "11111111",
        "plan": "claude_max",
        "config_dirs": [str(config_dir)],
        "sessions": 0,
        "last_activity_at": None,
    }]


def test_accounts_lists_chronicle_history_with_no_live_login(
    client: TestClient, tmp_path: Path
) -> None:
    _ingest_one_session(tmp_path)
    _stamp_account("sess1", "22222222-uuid")

    body = client.get("/api/accounts").json()

    assert len(body["accounts"]) == 1
    entry = body["accounts"][0]
    assert entry["account_uuid"] == "22222222-uuid"
    assert entry["short_uuid"] == "22222222"
    assert entry["plan"] is None
    assert entry["config_dirs"] == []
    assert entry["sessions"] == 1


def test_accounts_merges_history_and_live_login_for_the_same_uuid(
    client: TestClient, tmp_path: Path
) -> None:
    config_dir = Path(os.environ["CLAUDE_CONFIG_DIR"])
    _write_oauth(config_dir, "33333333-uuid", plan="claude_pro")
    _ingest_one_session(tmp_path)
    _stamp_account("sess1", "33333333-uuid")

    body = client.get("/api/accounts").json()

    assert body["accounts"] == [{
        "account_uuid": "33333333-uuid",
        "short_uuid": "33333333",
        "plan": "claude_pro",
        "config_dirs": [str(config_dir)],
        "sessions": 1,
        "last_activity_at": pytest.approx(body["accounts"][0]["last_activity_at"]),
    }]


def test_accounts_lists_every_matching_dir_for_one_uuid(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two config dirs logged into the SAME account (e.g. a machine and a
    container sharing one login) both appear in `config_dirs`."""
    primary = Path(os.environ["CLAUDE_CONFIG_DIR"])
    other = tmp_path / "claude-other"
    monkeypatch.delenv("CLAUDE_CONFIG_DIRS", raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIRS", str(other))
    _write_oauth(primary, "44444444-uuid")
    _write_oauth(other, "44444444-uuid")

    body = client.get("/api/accounts").json()

    assert len(body["accounts"]) == 1
    assert set(body["accounts"][0]["config_dirs"]) == {str(primary), str(other)}


def test_accounts_never_carries_email_or_name(
    client: TestClient, tmp_path: Path
) -> None:
    config_dir = Path(os.environ["CLAUDE_CONFIG_DIR"])
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / ".claude.json").write_text(json.dumps({
        "oauthAccount": {
            "accountUuid": "55555555-uuid",
            "emailAddress": "person@example.invalid",
            "fullName": "A Real Person",
            "organizationName": "Acme Corp",
        }
    }))

    body = json.dumps(client.get("/api/accounts").json())

    assert "example.invalid" not in body
    assert "A Real Person" not in body
    assert "Acme Corp" not in body


def test_sessions_account_filter_scopes_to_the_matching_config_dir(
    client: TestClient, root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live census sessions are scoped to `account`'s config dir(s) — the
    same multi-account census merge `test_sessions_merge_across_watched_
    config_dirs` (test_sessions.py) exercises, now filtered."""
    monkeypatch.delenv("CENSUS_STORE", raising=False)
    primary = Path(os.environ["CLAUDE_CONFIG_DIR"])
    personal = tmp_path / "claude-personal"
    now = time.time()
    cwd = os.path.realpath(str(root))

    def _store(config_dir: Path, sid: str, name: str) -> None:
        path = config_dir / "census" / "status.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "version": 1, "limits": {},
            "sessions": {sid: {"worktree_cwd": cwd, "updated_at": now,
                                 "payload": {"session_name": name}}},
        }))

    _store(primary, "s-work", "work")
    _store(personal, "s-home", "home")
    (primary / "overseer").mkdir(parents=True, exist_ok=True)
    (primary / "overseer" / "config.json").write_text(json.dumps({"claude_dirs": [str(personal)]}))
    _write_oauth(primary, "work-uuid")
    _write_oauth(personal, "home-uuid")

    unfiltered = client.get("/api/sessions").json()["sessions"]
    assert {s["id"] for s in unfiltered} == {"s-work", "s-home"}

    work_only = client.get("/api/sessions", params={"account": "work-uuid"}).json()["sessions"]
    assert [s["id"] for s in work_only] == ["s-work"]

    home_only = client.get("/api/sessions", params={"account": "home-uuid"}).json()["sessions"]
    assert [s["id"] for s in home_only] == ["s-home"]

    unknown = client.get("/api/sessions", params={"account": "nope-uuid"}).json()["sessions"]
    assert unknown == []


def test_chronicle_routes_pass_account_through(
    client: TestClient, root: Path, tmp_path: Path
) -> None:
    """`account=` on the chronicle routes filters to the session(s) chronicle
    stamped with that uuid (`--account` on the CLI, see chronicle's own
    tests/chronicle/test_report.py for the store-level behaviour)."""
    _ingest_one_session(tmp_path, "sess1")
    _stamp_account("sess1", "aaaa-uuid")
    conn = sqlite3.connect(os.environ["CHRONICLE_DB"])
    conn.execute("UPDATE sessions SET repo_root = ?", (str(root.resolve()),))
    conn.commit()
    conn.close()

    matching = client.get("/api/chronicle/summary", params={"account": "aaaa-uuid"}).json()
    assert matching["totals"]["sessions"] == 1

    other = client.get("/api/chronicle/summary", params={"account": "zzzz-uuid"}).json()
    assert other["totals"]["sessions"] == 0

    sessions = client.get("/api/chronicle/sessions", params={"account": "aaaa-uuid"}).json()
    assert [s["session_id"] for s in sessions["sessions"]] == ["sess1"]


def test_chronicle_account_too_long_is_400(client: TestClient) -> None:
    resp = client.get("/api/chronicle/summary", params={"account": "x" * 200})
    assert resp.status_code == 400
