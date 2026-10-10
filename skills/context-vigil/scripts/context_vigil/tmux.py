"""tmux detection and fire-and-forget keystroke dispatch.

``$TMUX`` set only proves a client existed; ``has-session`` proves the server
is alive. Dispatch is detached (own session, all streams to /dev/null) so the
hook returns immediately and nothing can corrupt the hook's JSON stdout.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from typing import List, Optional

BIN_ENV = "CONTEXT_VIGIL_TMUX_BIN"  # test seam: point at a stub


def binary() -> str:
    return os.environ.get(BIN_ENV, "tmux")


def installed() -> bool:
    return shutil.which(binary()) is not None


def pane() -> Optional[str]:
    return os.environ.get("TMUX_PANE") or None


def reachable() -> bool:
    if not os.environ.get("TMUX") or not pane():
        return False
    try:
        result = subprocess.run(
            [binary(), "has-session"], timeout=5, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        return False
    return result.returncode == 0


def send_detached(target: str, keystrokes: List[List[str]], delay: str) -> None:
    """Send keys after ``delay``, but only if the pane is still safe to type into then.

    The callers check the pane before the delay; a dialog can open during it. The
    detached shell asks ``cli _pane-safe`` again after the sleep and sends nothing
    when the answer is no (a manual /clear still loads the handover)."""
    tmux = shlex.quote(binary())
    sends = [f"{tmux} send-keys -t {shlex.quote(target)} "
             + " ".join(shlex.quote(k) for k in keys) for keys in keystrokes]
    check = f"{shlex.quote(sys.executable)} -m context_vigil.cli _pane-safe {shlex.quote(target)}"
    script = f"sleep {shlex.quote(delay)}; if {check}; then {'; '.join(sends)}; fi"
    package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ)
    inherited = env.get("PYTHONPATH")
    env["PYTHONPATH"] = package_root + (os.pathsep + inherited if inherited else "")
    subprocess.Popen(
        ["bash", "-c", script], stdin=subprocess.DEVNULL, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )


def in_mode(target: str) -> bool:
    """True when the pane is in a tmux mode (copy mode and friends): typed keys would
    drive that mode, not Claude's prompt. Unknown or empty answers count as not in mode."""
    try:
        result = subprocess.run(
            [binary(), "display-message", "-p", "-t", target, "#{pane_in_mode}"], timeout=5,
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
        )
    except Exception:
        return False
    return result.returncode == 0 and result.stdout.strip() == "1"


def capture(target: str) -> Optional[str]:
    """The pane's visible screen with SGR escapes (``capture-pane -p -e``), or None."""
    try:
        result = subprocess.run(
            [binary(), "capture-pane", "-p", "-e", "-t", target], timeout=5,
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
        )
    except Exception:
        return None
    return result.stdout if result.returncode == 0 else None
