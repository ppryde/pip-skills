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
    tmux = shlex.quote(binary())
    steps = [f"sleep {shlex.quote(delay)}"]
    for keys in keystrokes:
        args = " ".join(shlex.quote(k) for k in keys)
        steps.append(f"{tmux} send-keys -t {shlex.quote(target)} {args}")
    subprocess.Popen(
        ["bash", "-c", "; ".join(steps)], stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
