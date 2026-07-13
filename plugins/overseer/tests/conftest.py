import pytest


@pytest.fixture(autouse=True)
def _no_ambient_task_env(monkeypatch):
    """Strip CLAUDE_CONFIG_DIR / CLAUDE_CODE_TASK_LIST_ID for EVERY test.

    The checklist-sync hook resolves its on-disk task-list directory from
    these two env vars. The developer running this suite may have either set
    for real (a personal ``CLAUDE_CONFIG_DIR``, or a task list adopted by a
    live orchestrate session) — inheriting them here would point a test's
    task-file lookup at the developer's own ``~/.claude*`` tree instead of the
    tmp root it thinks it's using. Deleting them makes every lookup
    structurally scoped to what a test explicitly sets via
    ``monkeypatch.setenv``, mirroring vigil's precedent of stripping ambient
    env in an autouse fixture so tests can never leak into real state.
    """
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_TASK_LIST_ID", raising=False)
