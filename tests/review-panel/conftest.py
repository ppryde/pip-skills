"""Test isolation: pin every state/config dir into tmp_path BEFORE any code
runs, so a test never reads or writes the developer's real ~/.claude* tree.
See pip-skills CLAUDE.md 'Test isolation' for why this is mandatory."""
import pytest


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("REVIEW_CLONE_ROOT", str(cfg / "review-clone"))
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    monkeypatch.delenv("OVERSEER_DB", raising=False)
    return cfg
