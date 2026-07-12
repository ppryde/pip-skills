import pytest

from scripts.store import ensure_root


@pytest.fixture(autouse=True)
def _no_real_tmux(monkeypatch):
    """Strip every env var the tmux-touching code paths read, for EVERY test.

    The developer runs this suite from inside a live tmux session, so tests
    inherit a real TMUX/TMUX_PANE pointing at the developer's own terminal.
    Any test that reaches a dispatch path (the WF-013 resume kick, stop.sh's
    /clear send) with that inherited env types REAL keystrokes into the
    developer's pane — observed live: 3 kick prompts per full-suite run from
    pre-existing source=clear session-start tests that were never written
    with the kick in mind.

    Deleting these here makes every tmux dispatch structurally unreachable by
    default, regardless of future code changes: a test must explicitly opt in
    (shim tmux on PATH, private-socket wrapper via VIGIL_TMUX_BIN) to exercise
    those paths. monkeypatch scopes the deletion per-test, and it also cleans
    os.environ for subprocess-based tests that build their env from it.
    """
    for var in ("TMUX", "TMUX_PANE", "VIGIL_TMUX_BIN", "VIGIL_KICK_DELAY"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def repo(tmp_path):
    ensure_root(tmp_path)
    return tmp_path
