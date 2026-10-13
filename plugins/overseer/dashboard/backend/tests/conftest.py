from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cli_client import run_overseer
from app.main import create_app

# <repo>/plugins/census/scripts/cli.py: backend/tests -> backend -> dashboard -> overseer -> plugins
_CENSUS_CLI = Path(__file__).resolve().parents[4] / "census" / "scripts" / "cli.py"


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
    # Hermetic census lookup (WF-286): vigil and overseer's liveness probe find
    # census via CENSUS_CLI, else the cli.path pointer under the (pinned, empty)
    # config dir or CENSUS_STORE, else `census` on PATH. Left to that chain these
    # tests only passed on a machine with a pointer or a PATH entry; pin the
    # repo's own CLI, as tests/overseer/conftest.py and tests/vigil/conftest.py do.
    monkeypatch.setenv("CENSUS_CLI", str(_CENSUS_CLI))
    # Multi-account: the extra-config-dirs list `config.claude_dirs()` reads
    # (and the CLI subprocesses inherit). Left ambient, `central_root` could
    # land a test's board in the developer's real second account's tree.
    monkeypatch.delenv("CLAUDE_CONFIG_DIRS", raising=False)
    # chronicle (optional sibling plugin) resolves its store from CHRONICLE_DB
    # -> $CLAUDE_CONFIG_DIR/chronicle/sessions.db; the config dir is already
    # pinned above, but pin the file too so no test can reach a real store.
    monkeypatch.setenv("CHRONICLE_DB", str(tmp_path / "chronicle.db"))
    # `chronicle sync` (what the sync route runs) refreshes list prices from the
    # network at most daily; a test must never reach it.
    monkeypatch.setenv("CHRONICLE_NO_PRICING_REFRESH", "1")
    # Same idea, ABSOLUTE: `chronicle sync` also pulls configured remote boxes
    # over ssh (WF-122). No test here configures one, but this is the backstop
    # that guarantees the sync route can never open a real ssh connection.
    monkeypatch.setenv("CHRONICLE_NO_REMOTES", "1")


@pytest.fixture(autouse=True)
def _fresh_board_discovery() -> None:
    """`boards.discover` caches for a few seconds; no test may see another's."""
    from scripts import boards
    boards._discover_cache_clear()


@pytest.fixture(autouse=True)
def _loopback_test_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """The app-wide LAN guard (WF-100 C4) refuses a caller whose address is not
    LAN. Starlette's TestClient reports the host "testclient", so every test
    that names no client would 403. Default it to loopback here, once; the
    guard tests pass `client=` explicitly."""
    from starlette.testclient import TestClient as _StarletteClient

    original = _StarletteClient.__init__

    def init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.setdefault("client", ("127.0.0.1", 50000))
        original(self, *args, **kwargs)

    monkeypatch.setattr(_StarletteClient, "__init__", init)


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
