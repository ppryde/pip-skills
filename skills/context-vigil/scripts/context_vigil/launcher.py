"""Launch preference: how (and whether) Claude starts inside tmux.

Never imposed. The default leaves the bare `claude` command alone and adds a
separate `claude-tmux`; taking over `claude` itself is an explicit opt-in.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from context_vigil import paths, tmux
from context_vigil.install import Change, DamagedMarkers, damaged_note, remove_marked_block

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
type `/clear`; I resume automatically after that. Once tmux is installed, run
`context-vigil launcher` to pick how Claude launches."""


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


def plan_rc(choice: str) -> Optional[Change]:
    path = rc_path()
    if path is None:
        return None
    before = path.read_text() if path.exists() else ""
    after = strip_rc(before)
    if after is None:
        raise DamagedMarkers(damaged_note(path))
    line = alias_line(choice)
    if line:
        block = f"{RC_START}\n{line}\n{RC_END}\n"
        if after and not after.endswith("\n"):
            # No trailing newline to begin with: leave the block unterminated
            # too, so strip_rc can give the file back byte for byte.
            after = f"{after}\n\n{block[:-1]}"
        else:
            after = f"{after}\n{block}"
    return Change(path, before, after)


def _tmux_install_hint() -> str:
    return ("brew install tmux" if sys.platform == "darwin"
            else "sudo apt install tmux  (or your distro's package manager)")


def walkthrough_text() -> str:
    if not tmux.installed():
        return NO_TMUX.format(install=_tmux_install_hint())
    lead = ("You're inside tmux now, so auto mode already works for this session.\n\n"
            if tmux.reachable() else "")
    return lead + WALKTHROUGH
