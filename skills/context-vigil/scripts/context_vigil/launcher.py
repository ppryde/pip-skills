"""Launch preference: how (and whether) Claude starts inside tmux.

Never imposed. The default leaves the bare `claude` command alone and adds a
separate `claude-tmux`; taking over `claude` itself is an explicit opt-in.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

from context_vigil import paths, tmux
from context_vigil.install import (
    Change,
    DamagedMarkers,
    InstallError,
    added_lines,
    damaged_note,
    marked_span,
    remove_marked_block,
    removed_block,
)

CHOICES = ("on-demand", "always", "not-now")
RC_START = "# --- context-vigil launcher (managed; do not edit) ---"
RC_END = "# --- end context-vigil launcher ---"

WALKTHROUGH = """\
How do you want to launch Claude for hands-free handovers?

  1. On demand (recommended)
     Adds a `claude-tmux` command. Use it when you want a session that clears
     and resumes itself; plain `claude` keeps working exactly as it does now.

  2. Always
     Makes `claude` itself ALWAYS launch inside tmux — every session, every
     repo. If you only want tmux some of the time, choose 1 and use
     `claude-tmux` instead. (One-off escape: `CLAUDE_NO_TMUX=1 claude`.)

  3. Not now
     Change nothing. You'll get nudges and type `/clear` yourself.

Choose 1–3 [1]:"""
ALWAYS_CONFIRM = "`claude` will always start in tmux from your next shell — continue?"
NO_TMUX = """\
tmux not detected — auto-clear is off. Install it to go hands-free:
  {install}
Manual mode works today: you'll get a nudge, I'll write the handover, and you
type `/clear` and then send any message (e.g. "go") — the handover is injected
after `/clear`, but the resumed turn only starts when you send something. Once tmux is installed,
run `context-vigil launcher` to pick how Claude launches. This session stays manual either
way: start your next one with `claude-tmux`. If tmux is installed and this still says not
detected, it went somewhere outside the PATH Claude was started with — restart Claude from
a new terminal."""


def rc_path() -> Optional[Path]:
    shell = os.path.basename(os.environ.get("SHELL", ""))
    if shell == "zsh":
        return Path(os.environ.get("ZDOTDIR") or Path.home()) / ".zshrc"
    if shell == "bash":
        return Path.home() / ".bashrc"
    return None


def alias_line(choice: str) -> Optional[str]:
    target = paths.skill_dir() / "scripts" / "claude-tmux"
    if choice == "on-demand":
        return f"alias claude-tmux='{target}'"
    if choice == "always":
        return f"alias claude='{target}'"
    return None


def strip_rc(text: str) -> Optional[str]:
    """Text without our block, or None when its markers are damaged."""
    return remove_marked_block(text, RC_START, RC_END, drop_separator=True)


def _is_our_rc_line(line: str) -> bool:
    return line in ("", RC_START, RC_END) or line in {
        alias_line(c) for c in CHOICES if alias_line(c)}


def removal_summary(path: Path, text: str) -> List[str]:
    """Our block's removal, in our own lines only — never a line of the user's rc."""
    span = marked_span(text, RC_START, RC_END, drop_separator=True)
    if span is None:
        return [f"{path}: removes our block"]
    return removed_block(path, text.splitlines()[span[0]:span[1] + 1], _is_our_rc_line)


class LauncherRefused(InstallError):
    """The chosen launcher would silently override the user's own definition."""


_NAMES = ("claude", "claude-tmux")


def _definition(name: str) -> "re.Pattern[str]":
    n = re.escape(name)
    return re.compile(rf"^\s*(?:alias\s+{n}=|function\s+{n}(?![\w-])|{n}\s*\(\s*\))")


_DEFINITIONS = {name: _definition(name) for name in _NAMES}


def claude_definitions(text: str) -> Dict[str, int]:
    """1-based line number of the first user definition (alias, ``name()``,
    ``function name``) of ``claude`` / ``claude-tmux`` in an rc, outside our own
    block. Only numbers leave here: the line itself may export a key."""
    span = marked_span(text, RC_START, RC_END, drop_separator=True)
    found: Dict[str, int] = {}
    for index, line in enumerate(text.splitlines()):
        if span is not None and span[0] <= index <= span[1]:
            continue
        for name, pattern in _DEFINITIONS.items():
            if name not in found and pattern.match(line):
                found[name] = index + 1
    return found


def _check_definitions(choice: str, path: Path, text: str) -> List[str]:
    """Refuse a choice that would shadow the user's own definition; return the
    MANUAL STEP lines an allowed one needs. Paths and line numbers only."""
    found = claude_definitions(text)
    notes: List[str] = []
    if "claude" in found:
        where = f"{path}:{found['claude']}"
        if choice == "always":
            raise LauncherRefused(
                f"`always` refused: you define `claude` yourself at {where}, and the alias "
                "would bypass it (and anything it sets, such as CLAUDE_CONFIG_DIR). Choose "
                "on-demand and use `claude-tmux`, or remove your definition first.")
        if choice == "on-demand":
            notes.append(
                f"you define `claude` yourself at {where}. `claude-tmux` runs the claude "
                "binary from PATH, not that definition: if it sets CLAUDE_CONFIG_DIR (a "
                "second account), export CLAUDE_CONFIG_DIR in your shell instead, so "
                "`claude-tmux` starts the same account.")
    if "claude-tmux" in found and choice == "on-demand":
        raise LauncherRefused(
            f"`on-demand` refused: you already define `claude-tmux` at "
            f"{path}:{found['claude-tmux']}. Rename or remove yours first, or choose not-now.")
    return notes


def _bash_login_note(path: Path) -> List[str]:
    if path.name == ".bashrc" and sys.platform == "darwin":
        return [f"bash on macOS: Terminal opens login shells, which read ~/.bash_profile, "
                f"not {path} — make sure ~/.bash_profile sources ~/.bashrc, or the alias "
                "will not be found."]
    return []


def plan_rc(choice: str) -> Optional[Change]:
    """The rc edit for ``choice``. Its summary names the file and prints only the
    lines we add or remove: an rc file is where API keys are exported."""
    path = rc_path()
    if path is None:
        return None
    before = path.read_text() if path.exists() else ""
    after = strip_rc(before)
    if after is None:
        raise DamagedMarkers(damaged_note(path))
    notes = _check_definitions(choice, path, before)
    summary = removal_summary(path, before) if after != before else []
    line = alias_line(choice)
    if line:
        notes += _bash_login_note(path)
        summary += added_lines(path, len(after.splitlines()), ["", RC_START, line, RC_END])
        block = f"{RC_START}\n{line}\n{RC_END}\n"
        if after and not after.endswith("\n"):
            # No trailing newline to begin with: leave the block unterminated
            # too, so strip_rc can give the file back byte for byte.
            after = f"{after}\n\n{block[:-1]}"
        else:
            after = f"{after}\n{block}"
    return Change(path, before, after, summary, notes)


def _tmux_install_hint() -> str:
    return ("brew install tmux" if sys.platform == "darwin"
            else "sudo apt install tmux  (or your distro's package manager)")


def walkthrough_text() -> str:
    """The launch question. It never says auto mode works: nothing is installed when
    it is shown; only ``install --yes`` (and ``status``) may say so, conditionally."""
    if not tmux.installed():
        return NO_TMUX.format(install=_tmux_install_hint())
    return WALKTHROUGH
