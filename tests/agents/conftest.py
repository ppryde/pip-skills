"""pip-agents test fixtures.

Every test runs with CLAUDE_CONFIG_DIR, HOME, OVERSEER_CENTRAL and OVERSEER_DB pinned into tmp_path (repo
CLAUDE.md "Test isolation"), so nothing here can reach a real config dir. A test that leaves a new file inside
the plugin tree fails. Modules are loaded by path under unique names, because the plugins share the generic
package name `scripts` and cannot share an import path.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "pip-agents"
CONTRACT = PLUGIN / "contract"
EXAMPLES = CONTRACT / "examples"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _tree() -> set[Path]:
    return {p for p in PLUGIN.rglob("*") if p.is_file() and "__pycache__" not in p.parts and ".pytest_cache" not in p.parts}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("OVERSEER_CENTRAL", str(tmp_path / "overseer"))
    monkeypatch.setenv("OVERSEER_DB", str(tmp_path / "overseer" / "board.db"))
    before = _tree()
    yield
    leaked = _tree() - before
    assert not leaked, f"test left files in the plugin tree: {sorted(map(str, leaked))}"


@pytest.fixture(scope="session")
def vr():
    return load("pip_agents_validate_result", PLUGIN / "scripts" / "validate_result.py")


@pytest.fixture(scope="session")
def ba():
    return load("pip_agents_build_agents", ROOT / "tools" / "build_agents.py")


@pytest.fixture(scope="session")
def batching():
    return load("pip_agents_batching", ROOT / "tools" / "batching.py")
