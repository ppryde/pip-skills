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
from .test_pane import BUSY, IDLE, TYPED


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


def test_stop_busy_in_the_hook_and_idle_after_the_delay_sends_clear(
        repo: Path, fake_tmux: Path, iso: Path,  # noqa: F811
        monkeypatch: pytest.MonkeyPatch) -> None:
    # While the Stop hook runs the footer still reads "esc to interrupt" (live,
    # 2.1.296): the in-hook check must not hold on it, the re-check sees it idle.
    monkeypatch.setenv("CONTEXT_VIGIL_CLEAR_DELAY", "1")
    (iso / "idle-shot.txt").write_text(BUSY)
    state.request_clear(paths.scope_dir(repo), "doc")
    assert hooks.stop(_payload(repo)) is None
    (iso / "idle-shot.txt").write_text(IDLE)
    deadline = time.time() + 5
    while time.time() < deadline and not (fake_tmux.exists() and "/clear" in fake_tmux.read_text()):
        time.sleep(0.05)
    assert "send-keys -t %7 /clear Enter" in fake_tmux.read_text()


def test_stop_does_not_send_when_a_turn_starts_during_the_delay(
        repo: Path, fake_tmux: Path, iso: Path,  # noqa: F811
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXT_VIGIL_CLEAR_DELAY", "1")
    state.request_clear(paths.scope_dir(repo), "doc")
    assert hooks.stop(_payload(repo)) is None            # idle now: dispatch armed
    (iso / "idle-shot.txt").write_text(BUSY)             # the person submits a prompt
    time.sleep(2.5)
    assert not fake_tmux.exists() or "send-keys" not in fake_tmux.read_text()


def _sequence_tmux(iso: Path, monkeypatch: pytest.MonkeyPatch, screens: list[str]) -> tuple[Path, Path]:
    """capture-pane n prints screens[n] (the last repeating); other calls are logged."""
    for i, text in enumerate(screens):
        (iso / f"seq-{i}.txt").write_text(text)
    log, counter, last = iso / "tmux.log", iso / "captures", len(screens) - 1
    stub = iso / "tmux"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = capture-pane ]; then '
        f'n=$(cat "{counter}" 2>/dev/null || echo 0); echo $((n+1)) > "{counter}"; '
        f'[ "$n" -gt {last} ] && n={last}; cat "{iso}/seq-$n.txt"; exit 0; fi\n'
        '[ "$1" = display-message ] && { echo 0; exit 0; }\n'
        f'echo "$@" >> "{log}"\nexit 0\n')
    stub.chmod(0o755)
    monkeypatch.setenv("CONTEXT_VIGIL_TMUX_BIN", str(stub))
    monkeypatch.setenv("CONTEXT_VIGIL_BUSY_WAIT", "3")
    return log, counter


def test_send_detached_retries_busy_then_sends(iso: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from context_vigil import tmux
    log, counter = _sequence_tmux(iso, monkeypatch, [BUSY, BUSY, IDLE])
    tmux.send_detached("%7", [["/clear", "Enter"]], "0")
    deadline = time.time() + 6
    while time.time() < deadline and not log.exists():
        time.sleep(0.05)
    assert log.read_text().splitlines() == ["send-keys -t %7 /clear Enter"]
    assert int(counter.read_text()) == 3


def test_send_detached_busy_for_the_whole_window_sends_nothing(
        iso: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from context_vigil import tmux
    log, counter = _sequence_tmux(iso, monkeypatch, [BUSY])
    monkeypatch.setenv("CONTEXT_VIGIL_BUSY_WAIT", "2")   # whole seconds: 1-2s in practice
    tmux.send_detached("%7", [["/clear", "Enter"]], "0")
    time.sleep(3.5)
    tries = int(counter.read_text())
    assert tries >= 2
    time.sleep(0.8)
    assert int(counter.read_text()) == tries   # gave up
    assert not log.exists()


def test_send_detached_busy_then_typed_drops_at_once(
        iso: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from context_vigil import tmux
    log, counter = _sequence_tmux(iso, monkeypatch, [BUSY, TYPED, IDLE])
    tmux.send_detached("%7", [["/clear", "Enter"]], "0")
    time.sleep(2.5)
    assert int(counter.read_text()) == 2       # no retry after typed text
    assert not log.exists()


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
