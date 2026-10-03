"""Pure helpers of the dev-only live smoke harness (no tmux, no claude)."""
from __future__ import annotations

from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

from .conftest import SKILL


def _load():  # type: ignore[no-untyped-def]
    path = str(SKILL / "dev" / "live-smoke")
    spec = spec_from_loader("live_smoke", SourceFileLoader("live_smoke", path))
    assert spec is not None
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


ls = _load()


def test_settings_mirror_install_hooks() -> None:
    from_install = (SKILL / "scripts").as_posix()
    import sys
    sys.path.insert(0, from_install)
    try:
        from context_vigil import install
    finally:
        sys.path.remove(from_install)
    s = ls.build_settings(2, Path("/d"))
    assert ls.HOOKS == install.HOOKS
    for event, matcher, name in install.HOOKS:
        entry = s["hooks"][event][0]
        assert entry.get("matcher") == matcher
        assert entry["hooks"][0]["command"] == f'"{ls.LAUNCHER}" hook {name}'
    assert s["env"]["CONTEXT_VIGIL_COOLDOWN_SECONDS"] == "0"
    assert s["statusLine"]["command"].endswith('capture.sh"')


def test_slug_and_claude_args() -> None:
    assert ls.project_slug("/a/b.c_d") == "-a-b-c-d"
    narrow = ls.claude_args(Path("/s.json"), "haiku", False)
    assert "--allowedTools" in narrow and "--dangerously-skip-permissions" not in narrow
    assert "--dangerously-skip-permissions" in ls.claude_args(Path("/s.json"), "haiku", True)


def test_state_helpers_hide_secrets() -> None:
    rec = {"headless": False, "api_token": "x", "env": "y", "nested": {"a": 1}, "n": 3}
    assert ls.safe_fields(rec) == {"headless": False, "n": 3}
    doc = {"w": [{"context_window": {"used_percentage": 4, "x": {"y": 1}}}]}
    assert ls.find_window_dicts(doc) == [{"used_percentage": 4}]
