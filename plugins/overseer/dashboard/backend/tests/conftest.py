from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cli_client import run_overseer
from app.main import create_app


@pytest.fixture(autouse=True)
def _isolate_overseer_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin every path overseer resolves its central state from to this test's
    ``tmp_path``, for EVERY test.

    ``run_overseer`` shells out to the overseer CLI, which inherits this
    process's environment. Overseer resolves its board.db from
    ``OVERSEER_DB`` -> ``OVERSEER_CENTRAL`` -> ``$CLAUDE_CONFIG_DIR/overseer/...``
    (see ``scripts.db.board_db_path`` / ``scripts.config.central_root``). The
    developer running this suite has a real ``CLAUDE_CONFIG_DIR`` (their
    personal ``~/.claude*`` tree), so without pinning, a fixture that runs
    ``init`` writes a pytest-tmp-named board into that real config dir instead
    of the tmp root it thinks it is using (WF-051). Pinning all three into the
    inherited environment scopes every overseer read/write to this test.

    Mirrors the plugin-level ``tests/conftest.py`` autouse isolation fixture.
    """
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-ambient-config"))
    monkeypatch.setenv("OVERSEER_DB", str(tmp_path / "board.db"))
    monkeypatch.setenv("OVERSEER_CENTRAL", str(tmp_path / "state"))
    monkeypatch.delenv("CLAUDE_CODE_TASK_LIST_ID", raising=False)
    monkeypatch.delenv("CENSUS_STORE", raising=False)


@pytest.fixture()
def root(_isolate_overseer_state: None, tmp_path: Path) -> Path:
    """A tmp repo root with `.workflow/` initialised.

    overseer `init` calls `git check-ignore`, so the tmp root needs a git
    repo before init runs. Depends on ``_isolate_overseer_state`` so the
    environment is pinned to ``tmp_path`` before ``init`` shells out.
    """
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    run_overseer(tmp_path, "init")
    return tmp_path


@pytest.fixture()
def client(root: Path) -> TestClient:
    return TestClient(create_app(root))
