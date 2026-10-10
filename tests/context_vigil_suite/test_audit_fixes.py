"""Regression tests for the WF-152 audit fixes (CV-1, 2, 3, 5, 8, 11, 12)."""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from context_vigil import (
    config,
    handover,
    hooks,
    install,
    launcher,
    pane,
    paths,
    session,
    state,
)

from .conftest import read_settings as _settings
from .conftest import write_settings as _write
from .test_context_window import _ingest
from .test_hooks import DIALOG_SCREEN, _payload, fake_tmux  # noqa: F401  (fixture)
from .test_pane import IDLE


def _over(repo: Path, pct: float) -> None:
    _ingest(repo, "s1", pct)


# --- CV-1: the pane is re-checked after the delay ------------------------------

def test_stop_does_not_send_when_dialog_opens_during_the_delay(
        repo: Path, fake_tmux: Path, iso: Path,  # noqa: F811
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXT_VIGIL_CLEAR_DELAY", "1.5")
    scope = paths.scope_dir(repo)
    state.request_clear(scope, "doc")
    assert hooks.stop(_payload(repo)) is None            # idle now: dispatch armed
    (iso / "idle-shot.txt").write_text(DIALOG_SCREEN)    # a dialog opens before the keys fly
    time.sleep(3)
    assert not fake_tmux.exists() or "send-keys" not in fake_tmux.read_text()


# --- CV-2: copy mode is not safe -----------------------------------------------

def test_pane_in_copy_mode_is_unsafe(iso: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shot = iso / "shot.txt"
    shot.write_text(IDLE)
    stub = iso / "tmux"
    stub.write_text(
        '#!/usr/bin/env bash\n'
        f'[ "$1" = capture-pane ] && cat "{shot}"\n'
        '[ "$1" = display-message ] && echo "${PANE_IN_MODE:-0}"\nexit 0\n')
    stub.chmod(0o755)
    monkeypatch.setenv("CONTEXT_VIGIL_TMUX_BIN", str(stub))
    assert pane.pane_safe("%7") is True
    monkeypatch.setenv("PANE_IN_MODE", "1")
    assert pane.pane_safe("%7") is False


# --- CV-3: the bar needs a shipped mod -----------------------------------------

def test_bar_on_without_a_shipped_mod_refuses(cfg: Path) -> None:
    assert not install.mod_dir().is_dir()
    with pytest.raises(install.InstallError, match="vigil bar mod"):
        install.plan_install(threshold=None, bar=True)
    assert not (cfg / "settings.json").exists()


def test_bar_on_with_a_mod_dir_plans(cfg: Path, iso: Path,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    mod = iso / "mod"
    mod.mkdir()
    monkeypatch.setattr(install, "mod_dir", lambda: mod)
    plan = install.plan_install(threshold=None, bar=True)
    assert plan.record["bar"] == str(mod)


def test_questions_omit_the_bar_without_a_mod_dir(run_cli, cfg: Path) -> None:
    out = run_cli("install", "--questions-json").stdout
    assert "--bar on" not in out


# --- CV-5: a shrunk context starts a new nudge cycle ---------------------------

def test_nudge_restarts_after_context_shrinks(repo: Path) -> None:
    config.set_value(repo, "context.threshold", "35")
    _over(repo, 50)
    assert hooks.nudge(_payload(repo)) is not None
    _over(repo, 40)                       # compaction: below the last nudge, above threshold
    assert hooks.nudge(_payload(repo)) is not None
    assert session.load("s1")["last_nudged_pct"] == 40
    _over(repo, 42)
    assert hooks.nudge(_payload(repo)) is None    # the normal repeat step applies again


# --- CV-8: hostile skill dir ---------------------------------------------------

def test_alias_escapes_single_quotes_in_skill_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths, "skill_dir", lambda: Path("/odd/it's here"))
    assert launcher.alias_line("on-demand") == (
        "alias claude-tmux='/odd/it'\\''s here/scripts/claude-tmux'")


@pytest.mark.parametrize("bad", ['/a"b', "/a$b", "/a`b", "/a\\b"])
def test_skill_dir_with_shell_special_characters_refuses(
        cfg: Path, monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setattr(paths, "skill_dir", lambda: Path(bad))
    with pytest.raises(install.InstallError, match="shell-special"):
        install.plan_install(threshold=None)


# --- CV-11: the capture status line is matched exactly -------------------------

def test_wrapper_mentioning_capture_sh_is_not_our_statusline(cfg: Path) -> None:
    wrapper = f'my-wrapper "{paths.skill_dir()}/scripts/capture.sh" --extra'
    assert not install._is_capture(wrapper, {})
    assert install._is_capture(install.capture_command(), {})
    _write(cfg, {"statusLine": {"type": "command", "command": wrapper}})
    install.apply(install.plan_install(threshold=None))
    install.apply(install.plan_uninstall())
    assert _settings(cfg)["statusLine"]["command"] == wrapper


# --- CV-12: the inline fence outgrows the body ---------------------------------

def test_inlined_file_with_backticks_keeps_its_fence(repo: Path, iso: Path) -> None:
    extra = iso / "fenced.md"
    extra.write_text("before\n```python\nx = 1\n```\nafter ````` five")
    doc = handover.assemble(_good_notes(), repo, [extra], include_snapshot=False)
    tail = doc.split("## Inlined:", 1)[1]
    assert "\n``````\nbefore" in tail      # longer than the longest inner run (5)
    assert tail.rstrip().endswith("``````")


def _good_notes() -> str:
    return ("## 🎯 Goal\nShip it.\n\n## Current State\n- ✅ Done: a\n\n"
            "## Failed Attempts\nNone\n\n## ➡️ Next Step\nRun the tests.\n")
