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


def test_redact_masks_secret_shapes() -> None:
    text = ("key sk-FAKE-canary-123456 and AKIAFAKECANARY123456 then "
            "MY_API_KEY=abc OTHER_TOKEN_X=def SECRET=ghi plain=ok")
    out = ls.redact(text)
    for bad in ("sk-FAKE-canary-123456", "AKIAFAKECANARY123456", "=abc", "=def", "=ghi"):
        assert bad not in out
    assert "plain=ok" in out and "[redacted]" in out


def test_peek_redacts_pane_text(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    import argparse
    pane = "hello\nexport X_TOKEN=sk-FAKE-canary-99\n"
    monkeypatch.setattr(ls, "pane_text", lambda lines=60: pane)
    ls.cmd_peek(argparse.Namespace(n=10))
    out = capsys.readouterr().out
    assert "sk-FAKE-canary" not in out and "hello" in out


def test_wait_timeout_tail_is_redacted(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    pane = "AWS_SECRET_ACCESS_KEY=sk-FAKE-canary-77\n"
    monkeypatch.setattr(ls, "pane_text", lambda lines=60: pane)
    ok, why = ls.wait_until(lambda: False, 0, "x", 0)
    assert not ok and "sk-FAKE-canary" not in why


def test_state_helpers_hide_secrets() -> None:
    rec = {"headless": False, "api_token": "x", "env": "y", "nested": {"a": 1}, "n": 3}
    assert ls.safe_fields(rec) == {"headless": False, "n": 3}
    doc = {"w": [{"context_window": {"used_percentage": 4, "x": {"y": 1}}}]}
    assert ls.find_window_dicts(doc) == [{"used_percentage": 4}]
