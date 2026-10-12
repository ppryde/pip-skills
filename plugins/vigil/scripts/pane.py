"""Is a Claude Code pane safe to type into? Pure stdlib, read from ``capture-pane -p -e``.

Ported from skills/context-vigil's pane.py. Safe means: the prompt box is on
screen (a ``❯`` row directly under a full-width rule), it holds nothing the
person typed (the idle placeholder is drawn dim, SGR 2, and does not count), and
no menu/dialog footer or running-turn spinner (``esc to interrupt``) is showing. Anything we cannot read is unsafe: typing
``/clear`` + Enter into a dialog can answer a permission or trust prompt.
"""
from __future__ import annotations

import os
import re
import subprocess

_SGR = re.compile(r"\x1b\[([0-9;:]*)m")
_OTHER_ESC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
_RULE = re.compile(r"^\s*─{10,}\s*$")
# Pattern strings are module constants so tests/vigil/test_shared_constants.py (VG-9)
# can pin plugins/vigil and skills/context-vigil to the same wording.
FOOTER_PATTERN = r"(?i)enter to (select|confirm)|esc to (cancel|continue)"
# A running turn: the spinner line reads "(12s · ↓ 1.2k tokens · esc to interrupt)".
BUSY_PATTERN = r"(?i)esc to interrupt"
_FOOTER = re.compile(FOOTER_PATTERN)
_BUSY = re.compile(BUSY_PATTERN)
_BLANKS = " \t\xa0"
_UNREADABLE = "?"  # typed_text sentinel: an SGR we cannot parse, so the row counts as typed


def plain(text: str) -> str:
    return _SGR.sub("", _OTHER_ESC.sub("", text))


def typed_text(row: str) -> str:
    """The characters after the first ``❯`` that are NOT drawn dim, stripped."""
    _, _, rest = row.partition("❯")
    rest = _OTHER_ESC.sub("", rest)
    out: list[str] = []
    dim = False
    pos = 0
    for match in _SGR.finditer(rest):
        if not dim:
            out.append(rest[pos:match.start()])
        if ":" in match.group(1):
            return _UNREADABLE
        params = [p.lstrip("0") or "0" for p in match.group(1).split(";")] or ["0"]
        i = 0
        while i < len(params):
            p = params[i]
            if p in ("38", "48", "58"):
                kind = params[i + 1] if i + 1 < len(params) else ""
                i += 2 + (1 if kind == "5" else 3 if kind == "2" else 0)
                continue
            if p == "2":
                dim = True
            elif p in ("0", "22"):
                dim = False
            i += 1
        pos = match.end()
    if not dim:
        out.append(rest[pos:])
    return "".join(out).strip(_BLANKS)


def input_row(screen: str) -> str | None:
    """The prompt box's ``❯`` row (raw, escapes kept): the last ``❯`` row whose
    line above is a full-width rule. None when no prompt box is on screen."""
    raw = screen.splitlines()
    found: str | None = None
    for i in range(1, len(raw)):
        if plain(raw[i]).lstrip(_BLANKS).startswith("❯") and _RULE.match(plain(raw[i - 1])):
            found = raw[i]
    return found


def hold_reason(screen: str) -> str | None:
    """Why typing into this screen is unsafe, or None when it is safe."""
    row = input_row(screen)
    if row is None:
        return "no empty prompt box is on screen"
    if _FOOTER.search(plain(screen)):
        return "a dialog or permission prompt is open"
    if _BUSY.search(plain(screen)):
        return "the session is busy (a turn is running)"
    if typed_text(row) != "":
        return "the prompt box is not empty"
    return None


def _tmux(*args: str) -> subprocess.CompletedProcess[str] | None:
    tmux_bin = os.environ.get("VIGIL_TMUX_BIN", "tmux")
    try:
        return subprocess.run(
            [tmux_bin, *args], timeout=5, stdin=subprocess.DEVNULL,
            capture_output=True, text=True,
        )
    except Exception:
        return None


def pane_hold_reason(target: str) -> str | None:
    """None when the pane is safe to type into; otherwise why we must not."""
    mode = _tmux("display-message", "-p", "-t", target, "#{pane_in_mode}")
    if mode is not None and mode.returncode == 0 and mode.stdout.strip() == "1":
        return "the pane is in copy mode"
    shot = _tmux("capture-pane", "-p", "-e", "-t", target)
    if shot is None or shot.returncode != 0:
        return "the pane could not be read (tmux capture-pane failed)"
    return hold_reason(shot.stdout)
