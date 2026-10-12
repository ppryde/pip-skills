"""Test isolation: pin every state/config dir into tmp_path BEFORE any code runs, and make a
stray `gh` call fail loudly, so a test never touches the developer's real ~/.claude* tree or
GitHub. See pip-skills CLAUDE.md 'Test isolation'."""
import subprocess

import pytest

_REAL_RUN = subprocess.run


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path_factory, monkeypatch):
    iso = tmp_path_factory.mktemp("iso")  # outside the test's own tmp_path
    home = iso / "home"
    cfg = iso / "config"
    home.mkdir()
    cfg.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("REVIEW_CLONE_ROOT", str(cfg / "review-clone"))
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    monkeypatch.delenv("OVERSEER_DB", raising=False)

    def guarded(cmd, *a, **k):
        if cmd and cmd[0] == "gh":
            raise AssertionError(f"a test reached the real gh: {cmd[:4]}")
        return _REAL_RUN(cmd, *a, **k)

    monkeypatch.setattr(subprocess, "run", guarded)
    return cfg
