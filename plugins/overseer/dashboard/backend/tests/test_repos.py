from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cli_client import run_overseer
from app.main import create_app

"""GET /api/repos and per-request `root` validation (security-critical: the
server binds 0.0.0.0 with no auth, so an unvalidated `root` would let any LAN
client point the CLI at an arbitrary filesystem path — see main.py's
`_resolve_root`).

These tests do NOT use the shared `root`/`client` fixtures from conftest.py:
those fixtures create their board under whatever `CLAUDE_CONFIG_DIR` is
ambient at fixture-setup time, which runs before a test body gets a chance to
call `monkeypatch.setenv`. Repo discovery needs an isolated, shared
config-dir-style layout (`$CLAUDE_CONFIG_DIR/overseer/<label>/board.db`) for
TWO separate repos, so every fixture here takes `isolated_config_dir` as an
explicit dependency — pytest resolves that dependency BEFORE the fixture
body runs, so the env var is in place before any `run_overseer` call.
"""


@pytest.fixture()
def isolated_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_dir = tmp_path / "claude-config"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    monkeypatch.delenv("OVERSEER_DB", raising=False)
    return config_dir


def _make_repo(tmp_path: Path, isolated_config_dir: Path, name: str) -> Path:
    repo_root = tmp_path / name
    repo_root.mkdir()
    subprocess.run(["git", "init"], cwd=repo_root, capture_output=True, check=True)
    run_overseer(repo_root, "init")
    return repo_root.resolve()


@pytest.fixture()
def repo_a(tmp_path: Path, isolated_config_dir: Path) -> Path:
    return _make_repo(tmp_path, isolated_config_dir, "repo-a")


@pytest.fixture()
def repo_b(tmp_path: Path, isolated_config_dir: Path) -> Path:
    return _make_repo(tmp_path, isolated_config_dir, "repo-b")


@pytest.fixture()
def boardless_repo(tmp_path: Path, isolated_config_dir: Path) -> Path:
    """A real git repo with NO `board.db` (no `overseer init`) — a repo a
    live census session can point at without it ever showing up in `repos
    --json` discovery. Used to exercise the "unbegun repo" union."""
    repo_root = tmp_path / "boardless-repo"
    repo_root.mkdir()
    subprocess.run(["git", "init"], cwd=repo_root, capture_output=True, check=True)
    return repo_root.resolve()


def _seed_live_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sessions: dict[str, Path]
) -> None:
    """Seed a CENSUS_STORE with one LIVE (fresh `updated_at`) entry per
    ``{session_id: worktree_cwd}`` pair — mirrors test_sessions.py's/
    test_claim.py's env-var seeding so `run_census_all` (shelled from the
    endpoint) sees them through the same subprocess-env-inheritance chain."""
    store = tmp_path / "census" / "status.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    store.write_text(json.dumps({
        "version": 1,
        "limits": {},
        "sessions": {
            sid: {"worktree_cwd": str(cwd), "updated_at": now, "payload": {}}
            for sid, cwd in sessions.items()
        },
    }))
    monkeypatch.setenv("CENSUS_STORE", str(store))


@pytest.fixture()
def repo_a_worktree(tmp_path: Path, repo_a: Path) -> Path:
    """A linked worktree of `repo_a` — mirrors how the dashboard is normally
    launched (from `.claude/worktrees/<name>`), whose path differs from the
    main-repo root that `board.db` records as `meta['repo_root']`.
    `derive_repo_root` (via `git rev-parse --git-common-dir`) must resolve
    this worktree path back to `repo_a`, same as it does for a real
    worktree."""
    worktree_path = tmp_path / "repo-a-worktree"
    subprocess.run(
        ["git", "worktree", "add", str(worktree_path), "-b", "repo-a-wt-branch"],
        cwd=repo_a, capture_output=True, check=True,
    )
    return worktree_path.resolve()


def test_get_repos_lists_all_discovered_boards(repo_a: Path, repo_b: Path) -> None:
    client = TestClient(create_app(repo_a))

    resp = client.get("/api/repos")

    assert resp.status_code == 200
    roots = {r["root"] for r in resp.json()["repos"]}
    assert roots == {str(repo_a), str(repo_b)}


def test_get_repos_marks_the_launch_root_current(repo_a: Path, repo_b: Path) -> None:
    client = TestClient(create_app(repo_a))

    resp = client.get("/api/repos")

    current = {r["root"]: r["current"] for r in resp.json()["repos"]}
    assert current[str(repo_a)] is True
    assert current[str(repo_b)] is False


def test_get_repos_marks_served_worktree_repo_current(
    repo_a: Path, repo_b: Path, repo_a_worktree: Path
) -> None:
    """Serving the dashboard from inside a worktree of `repo_a` must still
    mark `repo_a` `current: true`. `board.db` records the MAIN repo root
    (`repo_a`), never the worktree's own path, so a naive `launch_root ==
    discovered root` comparison always reads `current: false` here — the bug
    this test guards against (task-12)."""
    client = TestClient(create_app(repo_a_worktree))

    resp = client.get("/api/repos")

    current = {r["root"]: r["current"] for r in resp.json()["repos"]}
    assert current[str(repo_a)] is True
    assert current[str(repo_b)] is False


def test_get_repos_when_only_one_board_discovered(repo_a: Path) -> None:
    client = TestClient(create_app(repo_a))

    resp = client.get("/api/repos")

    assert resp.status_code == 200
    repos = resp.json()["repos"]
    assert len(repos) == 1
    assert repos[0]["current"] is True


def test_board_with_known_root_is_accepted(repo_a: Path, repo_b: Path) -> None:
    client = TestClient(create_app(repo_a))
    run_overseer(repo_b, "new-card", "--title", "In repo B")

    resp = client.get("/api/board", params={"root": str(repo_b)})

    assert resp.status_code == 200
    titles = [c["title"] for c in resp.json()["board"]["cards"]]
    assert "In repo B" in titles


def test_board_with_unknown_root_is_rejected(repo_a: Path, tmp_path: Path) -> None:
    client = TestClient(create_app(repo_a))
    rogue = tmp_path / "not-a-discovered-repo"
    rogue.mkdir()

    resp = client.get("/api/board", params={"root": str(rogue)})

    assert resp.status_code == 400
    assert "unknown root" in resp.json()["detail"]


def test_traversal_root_is_rejected(repo_a: Path) -> None:
    """Path-traversal strings that resolve to non-allowlisted locations must
    be rejected, even when textually similar to allowed roots. This guards
    against an attacker using ../ escapes to point the CLI at arbitrary
    filesystem paths (security regression guard).
    """
    client = TestClient(create_app(repo_a))
    # Construct a traversal path that escapes the allowed root to a sibling
    # that is not in the discovery allowlist (only repo_a and repo_b exist).
    traversal_path = f"{repo_a}/../outside-allowlist"

    resp = client.get("/api/board", params={"root": traversal_path})

    assert resp.status_code == 400
    assert "unknown root" in resp.json()["detail"]


def test_mutation_with_unknown_root_is_rejected_and_does_not_shell(
    repo_a: Path, tmp_path: Path
) -> None:
    """The rejected root must never reach the CLI — assert on a card id that
    doesn't even exist in repo_a: if `_resolve_root` didn't gate this and the
    CLI were shelled anyway, it would 400/404 from the CLI itself with a
    DIFFERENT detail message ("no card with id ...", not "unknown root")."""
    client = TestClient(create_app(repo_a))
    rogue = tmp_path / "not-a-discovered-repo"
    rogue.mkdir()

    resp = client.post(
        "/api/card/WF-001/order", params={"root": str(rogue)}, json={"order": 5}
    )

    assert resp.status_code == 400
    assert "unknown root" in resp.json()["detail"]


def test_mutation_with_known_root_is_accepted(repo_a: Path, repo_b: Path) -> None:
    client = TestClient(create_app(repo_a))
    card_id = run_overseer(
        repo_b, "new-card", "--title", "T", "--complexity", "S"
    ).strip()

    resp = client.post(
        f"/api/card/{card_id}/order", params={"root": str(repo_b)}, json={"order": 7}
    )

    assert resp.status_code == 200
    shown = run_overseer(repo_b, "show", card_id, "--json", json_out=True)
    assert shown["order"] == 7


def test_omitted_root_defaults_to_launch_root(repo_a: Path, repo_b: Path) -> None:
    """No `root` query param at all -> the launch root, exactly as before
    this feature existed (backward-compatible default)."""
    client = TestClient(create_app(repo_a))
    run_overseer(repo_a, "new-card", "--title", "Only in A")

    resp = client.get("/api/board")

    titles = [c["title"] for c in resp.json()["board"]["cards"]]
    assert titles == ["Only in A"]


def test_get_card_honours_root(repo_a: Path, repo_b: Path) -> None:
    client = TestClient(create_app(repo_a))
    card_id = run_overseer(repo_b, "new-card", "--title", "B card").strip()

    resp = client.get(f"/api/card/{card_id}", params={"root": str(repo_b)})

    assert resp.status_code == 200
    assert resp.json()["title"] == "B card"


def test_get_repos_lists_unbegun_repo_with_live_session(
    repo_a: Path, boardless_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A board repo plus a LIVE census session in a different, boardless
    repo -> `/api/repos` lists both: the boardless one as `has_board:false`
    with `live_sessions>=1`, the board repo as `has_board:true`."""
    _seed_live_sessions(tmp_path, monkeypatch, {"sess-1": boardless_repo})
    client = TestClient(create_app(repo_a))

    resp = client.get("/api/repos")

    assert resp.status_code == 200
    by_root = {r["root"]: r for r in resp.json()["repos"]}
    assert by_root[str(repo_a)]["has_board"] is True
    unbegun = by_root[str(boardless_repo)]
    assert unbegun["has_board"] is False
    assert unbegun["current"] is False
    assert unbegun["live_sessions"] >= 1
    assert unbegun["label"] == boardless_repo.name


def test_get_repos_board_repo_is_never_double_listed(
    repo_a: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repo that already has a board must not ALSO appear as an unbegun
    entry, even when it has live census sessions of its own."""
    _seed_live_sessions(tmp_path, monkeypatch, {"sess-1": repo_a})
    client = TestClient(create_app(repo_a))

    resp = client.get("/api/repos")

    repos = resp.json()["repos"]
    matches = [r for r in repos if r["root"] == str(repo_a)]
    assert len(matches) == 1
    assert matches[0]["has_board"] is True


def test_get_repos_counts_live_sessions_for_board_repo(
    repo_a: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`live_sessions` on a board repo counts the live census sessions that
    derive to its root."""
    _seed_live_sessions(
        tmp_path, monkeypatch, {"sess-1": repo_a, "sess-2": repo_a}
    )
    client = TestClient(create_app(repo_a))

    resp = client.get("/api/repos")

    by_root = {r["root"]: r for r in resp.json()["repos"]}
    assert by_root[str(repo_a)]["live_sessions"] == 2


def test_board_with_unbegun_root_is_still_rejected(
    repo_a: Path, boardless_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Security regression guard: an "unbegun" repo surfaced by `/api/repos`
    (live session, no board) must NOT be added to `_resolve_root`'s
    allowlist. `GET /api/board?root=<unbegun root>` still 400s — the
    dashboard never fetches the board for an unbegun repo, and this listing
    addition must not open a new shelled-root surface."""
    _seed_live_sessions(tmp_path, monkeypatch, {"sess-1": boardless_repo})
    client = TestClient(create_app(repo_a))

    # Confirm it's actually surfaced as unbegun first (sanity: the listing
    # addition worked), then confirm the board endpoint still rejects it.
    repos_resp = client.get("/api/repos")
    by_root = {r["root"]: r for r in repos_resp.json()["repos"]}
    assert by_root[str(boardless_repo)]["has_board"] is False

    resp = client.get("/api/board", params={"root": str(boardless_repo)})

    assert resp.status_code == 400
    assert "unknown root" in resp.json()["detail"]
