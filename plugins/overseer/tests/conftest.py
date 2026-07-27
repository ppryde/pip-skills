import pytest


@pytest.fixture(autouse=True)
def _no_ambient_task_env(tmp_path, monkeypatch):
    """Isolate every env var a card-verb call site can resolve from ambient
    state, for EVERY test.

    The checklist-sync hook resolves its on-disk task-list directory from
    CLAUDE_CONFIG_DIR / CLAUDE_CODE_TASK_LIST_ID; ``scripts.db.board_db_path``
    falls back to CLAUDE_CONFIG_DIR/overseer/<label>/board.db when
    OVERSEER_DB isn't set; and ``scripts.liveness`` (consulted by ``claim``'s
    stale-reclaim pass) falls back to CLAUDE_CONFIG_DIR/census/status.json
    when CENSUS_STORE isn't set. The developer running this suite may have
    any of these set for real (a personal ``CLAUDE_CONFIG_DIR``, a task list
    adopted by a live orchestrate session, a live census store) — inheriting
    them here would point a test's lookups at the developer's own
    ``~/.claude*`` tree instead of the tmp root it thinks it's using.

    Pointing CLAUDE_CONFIG_DIR at a fresh, never-created subdirectory of this
    test's own ``tmp_path`` (rather than merely deleting it, which would fall
    back to the real ``~/.claude``) makes every one of those lookups
    structurally scoped to this test and guaranteed empty unless the test
    itself populates it — mirroring vigil's precedent of stripping ambient
    env in an autouse fixture so tests can never leak into real state.

    OVERSEER_DB is pinned to this same ``tmp_path`` independently of
    CLAUDE_CONFIG_DIR: several hook tests deliberately repoint
    CLAUDE_CONFIG_DIR mid-test to exercise task-list env precedence, and
    board.db must not follow that move — a card seeded before the repoint
    would otherwise become unreachable to a helper reading the board after
    it. Pinning both independently keeps each concern's isolation orthogonal
    to the other. A test that needs a specific config dir or board path still
    wins by calling ``monkeypatch.setenv`` itself afterwards.
    """
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-ambient-config"))
    monkeypatch.setenv("OVERSEER_DB", str(tmp_path / "board.db"))
    monkeypatch.delenv("CLAUDE_CODE_TASK_LIST_ID", raising=False)
    monkeypatch.delenv("CENSUS_STORE", raising=False)
