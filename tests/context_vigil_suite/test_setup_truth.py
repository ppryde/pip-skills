"""Setup tells the truth: what is live now, what needs a new shell or session, and
what `status` can actually see. Findings F1-F10 of the setup review plus the
general review's inline-status-line item and minors.

Fake HOME / CLAUDE_CONFIG_DIR / data root only (``iso``); tmux is always a stub.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from context_vigil import census, handover, hooks, install, launcher, paths, state

from .conftest import SKILL, statusline_payload
from .conftest import read_settings as _settings

SPEC = SKILL.parents[1] / "docs" / "superpowers" / "specs" / "2026-10-02-context-vigil-design.md"
TMUX_ENV = {"TMUX": "/tmp/fake-tmux,1,0", "TMUX_PANE": "%9",
            "CONTEXT_VIGIL_SESSION": "cc-repo-1"}


@pytest.fixture
def tmux_stub(iso: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tmux on 'PATH' (via the seam) whose has-session succeeds; logs nothing."""
    stub = iso / "tmux"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    monkeypatch.setenv("CONTEXT_VIGIL_TMUX_BIN", str(stub))
    return stub


@pytest.fixture
def inside_tmux(tmux_stub: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setenv("TMUX", TMUX_ENV["TMUX"])
    monkeypatch.setenv("TMUX_PANE", TMUX_ENV["TMUX_PANE"])
    return {"TMUX": TMUX_ENV["TMUX"], "TMUX_PANE": TMUX_ENV["TMUX_PANE"]}


def _notes(iso: Path) -> Path:
    notes = iso / "notes.md"
    notes.write_text("## Goal\nMove the work.\n\n## Failed Attempts\nNone\n\n"
                     "## Next Step\ncarry on with step two\n")
    return notes


# --- F1 / F6 / F10: install --yes says what is live now --------------------------

def test_install_yes_says_live_now_and_how_to_check(run_cli, cfg: Path) -> None:
    out = run_cli("install", "--yes").stdout
    assert "new sessions" not in out
    assert "live in this session" in out
    assert "/hooks" in out and "restart Claude" in out
    assert "\npython: /" in out


def test_install_yes_with_launcher_says_the_alias_needs_a_new_shell(run_cli, zsh: Path) -> None:
    out = run_cli("install", "--yes", "--launcher", "on-demand").stdout
    assert "new shell" in out and f"source {zsh}" in out
    assert "cannot run `claude-tmux`" in out


def test_install_yes_says_this_session_stays_manual_only_with_tmux(run_cli, zsh: Path,
                                                                  tmux_stub: Path) -> None:
    with_tmux = run_cli("install", "--yes", "--launcher", "on-demand").stdout
    assert "This session stays manual" in with_tmux
    without = run_cli("install", "--yes", "--launcher", "on-demand",
                      env={"CONTEXT_VIGIL_TMUX_BIN": str(tmux_stub) + "-missing"}).stdout
    assert "This session stays manual" not in without


def test_install_yes_without_launcher_does_not_mention_a_shell(run_cli, cfg: Path) -> None:
    out = run_cli("install", "--yes", "--launcher", "not-now").stdout
    assert "new shell" not in out


# --- F2: never claim auto mode before the hooks exist ----------------------------

def test_walkthrough_never_claims_auto_mode(inside_tmux: dict) -> None:
    assert "already works" not in launcher.walkthrough_text()
    assert "auto mode" not in launcher.walkthrough_text().split("How do you want")[0]


@pytest.mark.parametrize("args", [("install",), ("launcher",)])
def test_dry_run_and_launcher_inside_tmux_make_no_auto_claim(run_cli, inside_tmux: dict,
                                                             cfg: Path, args: tuple) -> None:
    out = run_cli(*args).stdout
    assert "already works" not in out and "mode: auto" not in out, args


def test_install_yes_inside_tmux_claims_auto_only_conditionally(run_cli, inside_tmux: dict,
                                                                cfg: Path) -> None:
    out = run_cli("install", "--yes").stdout
    assert "already works" not in out
    assert "auto mode works in this session once `/hooks`" in out


def test_status_inside_tmux_without_hooks_is_not_auto(run_cli, inside_tmux: dict,
                                                      repo: Path) -> None:
    out = run_cli("status", cwd=repo).stdout
    assert "mode: auto" not in out
    assert "hooks are not installed" in out


# --- F3: status reports live truth ------------------------------------------------

def test_status_before_install(run_cli, repo: Path, cfg: Path) -> None:
    out = run_cli("status", cwd=repo).stdout
    assert "installed: no" in out
    assert f"hooks: 0/4 in {cfg / 'settings.json'}" in out
    assert "status line: missing" in out
    assert "last status-line reading for this worktree: none yet" in out
    assert "re-run install" not in out


def _drop_stop_hook(data: dict) -> None:
    del data["hooks"]["Stop"]


def _drop_all_hooks(data: dict) -> None:
    del data["hooks"]["Stop"]
    del data["hooks"]


@pytest.mark.parametrize("edit, expected", [
    (None, ["installed: yes", "hooks: 4/4 in {settings}", "status line: capture"]),
    (_drop_stop_hook, ["installed: partial", "hooks: 3/4", "MISSING — re-run install"]),
    (_drop_all_hooks, ["installed: no", "hooks: 0/4", "MISSING — re-run install"]),
], ids=["intact", "stop-hook-removed", "hooks-removed"])
def test_status_after_install_counts_hooks_from_settings(run_cli, repo: Path, cfg: Path,
                                                         edit, expected: list) -> None:
    assert run_cli("install", "--yes").returncode == 0
    if edit is not None:
        data = _settings(cfg)
        edit(data)
        (cfg / "settings.json").write_text(json.dumps(data))
    out = run_cli("status", cwd=repo).stdout
    for needle in expected:
        assert needle.format(settings=cfg / "settings.json") in out, needle


def test_status_hooks_pointing_at_a_moved_skill_do_not_count(run_cli, repo: Path,
                                                            cfg: Path) -> None:
    stale = {"hooks": [{"type": "command", "command": '"/old/scripts/context-vigil" hook stop'}]}
    (cfg / "settings.json").write_text(json.dumps({"hooks": {"Stop": [stale]}}))
    assert "hooks: 0/4" in run_cli("status", cwd=repo).stdout


def test_status_unreadable_settings_says_so(run_cli, repo: Path, cfg: Path) -> None:
    (cfg / "settings.json").write_text("{nope")
    result = run_cli("status", cwd=repo)
    assert result.returncode == 0
    assert "hooks: unreadable" in result.stdout


def _plain_echo(data: dict) -> None:
    data["statusLine"]["command"] = "echo hi"


def _hand_wired(data: dict) -> None:
    data["statusLine"]["command"] = "input=$(cat); " + install.ingest_command("input")


@pytest.mark.parametrize("edit, present, absent", [
    (None, ["status line: spliced"], []),
    (_plain_echo, ["status line: missing", "WARNING: status line not feeding context-vigil"],
     []),
    (_hand_wired, ["status line: manual"], ["WARNING"]),
], ids=["spliced", "not-feeding", "manual"])
def test_status_line_kinds(run_cli, repo: Path, cfg: Path, edit, present: list,
                           absent: list) -> None:
    script = cfg / "sl.sh"
    script.write_text("input=$(cat)\necho hi\n")
    (cfg / "settings.json").write_text(json.dumps(
        {"statusLine": {"type": "command", "command": f"bash {script}"}}))
    assert run_cli("install", "--yes").returncode == 0
    if edit is not None:
        data = _settings(cfg)
        edit(data)
        (cfg / "settings.json").write_text(json.dumps(data))
    out = run_cli("status", cwd=repo).stdout
    for needle in present:
        assert needle in out, needle
    for needle in absent:
        assert needle not in out, needle


def test_status_last_reading_for_this_worktree(run_cli, repo: Path) -> None:
    sub = repo / "sub"
    sub.mkdir()
    (repo / ".git").mkdir()
    run_cli("ingest", stdin=statusline_payload(sub, "x", 10))
    out = run_cli("status", cwd=repo).stdout
    assert "last status-line reading for this worktree: " in out
    line = next(ln for ln in out.splitlines() if ln.startswith("last status-line reading"))
    assert line.endswith("s ago") and "none yet" not in line


def test_status_flags_a_session_that_never_got_a_reading(run_cli, repo: Path) -> None:
    assert run_cli("install", "--yes").returncode == 0
    hooks.session_start({"cwd": str(repo), "session_id": "s1", "source": "startup"})
    started = state.started_marker(paths.scope_dir(repo))
    old = time.time() - 600
    os.utime(started, (old, old))
    out = run_cli("status", cwd=repo).stdout
    assert "WARNING: status line not feeding context-vigil" in out
    run_cli("ingest", stdin=statusline_payload(repo, "s1", 10))
    assert "WARNING" not in run_cli("status", cwd=repo).stdout


def test_status_shows_the_interpreter_path(run_cli, repo: Path) -> None:
    line = next(ln for ln in run_cli("status", cwd=repo).stdout.splitlines()
                if ln.startswith("python: "))
    assert Path(line.split("python: ", 1)[1].split(" ", 1)[0]).exists()


# --- F4: a plain-scope handover reaches a tmux-pane session -----------------------

def test_plain_handover_is_offered_to_a_tmux_session_and_resumable(
        run_cli, repo: Path, iso: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    saved = run_cli("handover", "--file", str(_notes(iso)), cwd=repo)
    assert saved.returncode == 0, saved.stderr
    plain = paths.worktree_dir(repo)
    assert state.read_handoff(plain) is not None and state.clear_flag(plain).exists()
    for name, value in TMUX_ENV.items():
        monkeypatch.setenv(name, value)
    assert paths.scope_dir(repo) != plain
    out = hooks.session_start({"cwd": str(repo), "session_id": "t1", "source": "startup"})
    assert out is not None and "Move the work." in out and "NOT been loaded" in out
    assert state.read_handoff(plain) is not None            # offered, never loaded
    loaded = run_cli("handover", "--resume", cwd=repo, env=TMUX_ENV)
    assert loaded.returncode == 0 and "carry on with step two" in loaded.stdout
    assert state.read_handoff(plain) is None
    assert not state.clear_flag(plain).exists()              # its stale /clear request too


def test_clear_in_a_tmux_session_never_loads_the_worktree_handover(
        repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state.request_clear(paths.worktree_dir(repo), "PLAIN DOC")
    for name, value in TMUX_ENV.items():
        monkeypatch.setenv(name, value)
    assert hooks.session_start({"cwd": str(repo), "session_id": "t1", "source": "clear"}) is None
    assert state.read_handoff(paths.worktree_dir(repo)) == "PLAIN DOC"


def test_discard_falls_back_to_the_worktree_handover(run_cli, repo: Path) -> None:
    state.request_clear(paths.worktree_dir(repo), "PLAIN DOC")
    gone = run_cli("handover", "--discard", cwd=repo, env=TMUX_ENV)
    assert gone.returncode == 0
    assert state.read_handoff(paths.worktree_dir(repo)) is None
    assert run_cli("handover", "--resume", cwd=repo, env=TMUX_ENV).returncode == 1


def test_own_handover_wins_over_the_worktree_one(run_cli, repo: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    state.request_clear(paths.worktree_dir(repo), "PLAIN DOC")
    for name, value in TMUX_ENV.items():
        monkeypatch.setenv(name, value)
    state.write_handoff(paths.scope_dir(repo), "PANE DOC")
    out = run_cli("handover", "--resume", cwd=repo, env=TMUX_ENV).stdout
    assert "PANE DOC" in out and "PLAIN DOC" not in out


def test_stale_worktree_clear_request_is_cleared_at_tmux_session_start(
        repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plain = paths.worktree_dir(repo)
    paths.ensure_dir(plain)
    state.clear_flag(plain).touch()        # armed, its handoff long gone
    old = time.time() - 60
    os.utime(state.clear_flag(plain), (old, old))
    for name, value in TMUX_ENV.items():
        monkeypatch.setenv(name, value)
    hooks.session_start({"cwd": str(repo), "session_id": "t1", "source": "startup"})
    assert not state.clear_flag(plain).exists()


def test_stop_ignores_a_clear_request_whose_handover_is_gone(repo: Path) -> None:
    scope = paths.scope_dir(repo)
    state.request_clear(scope, "doc")
    state.consume_handoff(scope)           # e.g. resumed from a tmux session
    assert hooks.stop({"cwd": str(repo), "session_id": "s1"}) is None
    assert not state.clear_flag(scope).exists()


def test_status_sees_a_worktree_handover_from_a_tmux_session(run_cli, repo: Path) -> None:
    state.request_clear(paths.worktree_dir(repo), "PLAIN DOC")
    assert "pending handover: yes" in run_cli("status", cwd=repo, env=TMUX_ENV).stdout


# --- F5: an existing claude wrapper ---------------------------------------------

@pytest.mark.parametrize("definition", [
    'claude() { CLAUDE_CONFIG_DIR=~/.claude-x command claude "$@"; }',
    "function claude {\n  command claude \"$@\"\n}",
    "function claude() { command claude; }",
    "  alias claude='claude --verbose'",
    'claude () { command claude "$@"; }',
])
def test_always_is_refused_over_an_existing_claude(zsh: Path, definition: str) -> None:
    zsh.write_text(f"export FOO=1\n{definition}\n")
    with pytest.raises(install.InstallError) as exc:
        launcher.plan_rc("always")
    assert f"{zsh}:2" in str(exc.value) and "claude" in str(exc.value)


def test_on_demand_over_a_claude_wrapper_adds_a_config_dir_step(zsh: Path) -> None:
    zsh.write_text('export FOO=1\n\nclaude() { CLAUDE_CONFIG_DIR=~/.c command claude "$@"; }\n')
    change = launcher.plan_rc("on-demand")
    assert change is not None
    assert any(f"{zsh}:3" in n and "CLAUDE_CONFIG_DIR" in n for n in change.notes)
    plan = install.plan_install(threshold=None, launcher="on-demand")
    assert any(f"{zsh}:3" in m for m in plan.manual)


def test_on_demand_is_refused_over_a_foreign_claude_tmux(zsh: Path) -> None:
    zsh.write_text("alias claude-tmux='tmux new claude'\n")
    with pytest.raises(install.InstallError) as exc:
        launcher.plan_rc("on-demand")
    assert f"{zsh}:1" in str(exc.value)


@pytest.mark.parametrize("line", [
    "alias claude-tmux='x'", "claudette() { :; }", "# claude() is mine", "export CLAUDE=1",
    "alias cl='claude'",
])
def test_lookalikes_are_not_claude_definitions(zsh: Path, line: str) -> None:
    zsh.write_text(f"{line}\n")
    assert launcher.claude_definitions(zsh.read_text()).get("claude") is None


def test_our_own_block_is_not_a_conflict(zsh: Path) -> None:
    install.apply(install.Plan(changes=[launcher.plan_rc("always")]))  # type: ignore[list-item]
    assert launcher.plan_rc("always") is not None
    assert launcher.plan_rc("on-demand") is not None


def test_cli_launcher_always_refusal_is_clean(run_cli, zsh: Path) -> None:
    zsh.write_text("claude() { command claude; }\n")
    result = run_cli("launcher", "always", "--yes", "--confirm-always")
    assert result.returncode == 1 and f"{zsh}:1" in result.stderr
    assert "alias claude=" not in zsh.read_text()


def test_cli_install_on_demand_relays_the_wrapper_step(run_cli, zsh: Path) -> None:
    zsh.write_text("claude() { command claude; }\n")
    out = run_cli("install", "--launcher", "on-demand").stdout
    assert f"MANUAL STEP: you define `claude` yourself at {zsh}:1" in out


# --- General minor 1: bash on macOS ---------------------------------------------

def test_bash_on_macos_gets_the_login_shell_caveat(home: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setattr(launcher.sys, "platform", "darwin")
    change = launcher.plan_rc("on-demand")
    assert change is not None and any(".bash_profile" in n for n in change.notes)
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    change = launcher.plan_rc("on-demand")
    assert change is not None and not change.notes


# --- F7 / F8: no advice that points at something that does not exist -------------

def test_status_before_install_does_not_recommend_claude_tmux(run_cli, repo: Path,
                                                              tmux_stub: Path) -> None:
    out = run_cli("status", cwd=repo, env={"CONTEXT_VIGIL_TMUX_BIN": str(tmux_stub)}).stdout
    assert "launch with claude-tmux" not in out
    assert "`install` adds a `claude-tmux` launcher" in out


def test_no_tmux_text_says_this_session_stays_manual() -> None:
    text = launcher.walkthrough_text()
    assert "This session stays manual" in text and "`claude-tmux`" in text
    assert "restart Claude" in text


# --- General minor 6: injection caps --------------------------------------------

def test_injection_is_capped_at_twice_max_tokens(run_cli, repo: Path) -> None:
    run_cli("config", "set", "handover.max_tokens", "100", cwd=repo)
    scope = paths.scope_dir(repo)
    state.request_clear(scope, "## Goal\nbig\n" + "x" * 5000 + "\n")
    out = hooks.session_start({"cwd": str(repo), "session_id": "s1", "source": "clear"})
    assert out is not None
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    body = ctx.split("\n\n", 1)[1]
    assert len(body) <= 2 * 100 * handover.CHARS_PER_TOKEN + 200
    assert "[truncated by context-vigil" in body
    state.write_handoff(scope, "y" * 5000)
    printed = run_cli("handover", "--resume", cwd=repo).stdout
    assert "[truncated by context-vigil" in printed and printed.count("y") <= 850


def test_small_handover_is_injected_whole(repo: Path) -> None:
    scope = paths.scope_dir(repo)
    state.request_clear(scope, "## Goal\nsmall\n")
    out = hooks.session_start({"cwd": str(repo), "session_id": "s1", "source": "clear"})
    assert out is not None and "truncated" not in out


def test_waiting_notice_caps_the_branch() -> None:
    doc = "## Goal\nShip.\n\n- Branch: `" + "b" * 500 + "`\n"
    text = handover.summary(doc, None)
    assert "b" * 81 not in text and len(text) < 250


# --- Docs: SKILL.md, README, spec ------------------------------------------------

def _doc(name: str) -> str:
    return (SKILL / name).read_text()


def test_docs_say_live_now_not_new_sessions() -> None:
    for text in (_doc("SKILL.md"), _doc("README.md"), SPEC.read_text()):
        assert "take effect in new sessions" not in text
        assert "in new sessions" not in text
    assert "/hooks" in _doc("SKILL.md") and "/hooks" in _doc("README.md")


def test_skill_md_carries_the_setup_protocol() -> None:
    text = _doc("SKILL.md")
    assert "## Moving this work into a tmux session" in text
    assert "resume the handover" in text and "claude-tmux" in text
    assert "never nudged" in text                     # inline status line: MANUAL STEP required
    assert "cannot run `claude-tmux`" in text
    assert "trust" in text
    assert "headless" in text.lower() and "no /clear" in text


def test_manual_step_text_says_it_is_required(cfg: Path) -> None:
    (cfg / "settings.json").write_text(json.dumps(
        {"statusLine": {"type": "command", "command": "echo hi"}}))
    manual = " ".join(install.plan_install(threshold=None).manual)
    assert "Required" in manual and "never nudged" in manual


def test_readme_covers_layout_attach_wrapper_and_trust() -> None:
    text = _doc("README.md")
    for needle in ("windows.json", "sessions/<session_id>.json", "claude-tmux attach",
                   "binary from PATH", "trust", "never nudged", "new shell"):
        assert needle in text, needle


def test_spec_matches_the_install_flow() -> None:
    text = SPEC.read_text()
    assert "--confirm-always" in text.split("## CLI surface", 1)[1].split("## Configuration")[0]
    assert "  dev/" in text
    assert "without `--yes`" in text


def test_census_last_seen_is_none_without_readings(repo: Path) -> None:
    assert census.last_seen(repo) is None
