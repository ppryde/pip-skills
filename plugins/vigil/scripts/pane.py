"""Is a Claude Code pane safe to type into? Pure stdlib, read from ``capture-pane -p -e``.

Ported from skills/context-vigil's pane.py. Safe means: the prompt box is on
screen (a ``❯`` row directly under a full-width rule, which may carry a session
name), it holds nothing the person typed (the idle placeholder is drawn dim, SGR 2,
and does not count), and no menu/dialog footer is showing. The post-delay re-check
also refuses a running turn (``esc to interrupt`` in the footer under the box).
Anything we cannot read is unsafe: typing ``/clear`` + Enter into a dialog can
answer a permission or trust prompt.
"""
from __future__ import annotations

import os
import re
import subprocess

_SGR = re.compile(r"\x1b\[([0-9;:]*)m")
_OTHER_ESC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
# Pattern strings are module constants so tests/vigil/test_shared_constants.py (VG-9)
# can pin plugins/vigil and skills/context-vigil to the same wording.
# A full-width rule; a named session draws its name into the one above the box:
# "──────── Great Refactoring ─" (seen live, Claude Code 2.1.296).
RULE_PATTERN = r"^\s*─{10,}(?:\s.*─)?\s*$"
FOOTER_PATTERN = r"(?i)enter to (select|confirm)|esc to (cancel|continue)"
# A running turn: the footer under the box reads
# "⏵⏵ auto mode on (shift+tab to cycle) · esc to interrupt" (2.1.296).
BUSY_PATTERN = r"(?i)esc to interrupt"
_RULE = re.compile(RULE_PATTERN)
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


def _input_index(raw: list[str]) -> int | None:
    found: int | None = None
    for i in range(1, len(raw)):
        if plain(raw[i]).lstrip(_BLANKS).startswith("❯") and _RULE.match(plain(raw[i - 1])):
            found = i
    return found


def input_row(screen: str) -> str | None:
    """The prompt box's ``❯`` row (raw, escapes kept): the last ``❯`` row whose
    line above is a full-width rule. None when no prompt box is on screen."""
    raw = screen.splitlines()
    i = _input_index(raw)
    return None if i is None else raw[i]


def below_box(screen: str) -> str:
    """The plain text under the prompt box's lower rule (its footer), or under the
    ``❯`` row when no lower rule follows. Transcript text above the box is never in it."""
    raw = screen.splitlines()
    i = _input_index(raw)
    if i is None:
        return ""
    start = i + 1
    for j in range(i + 1, len(raw)):
        if _RULE.match(plain(raw[j])):
            start = j + 1
            break
    return "\n".join(plain(line) for line in raw[start:])


def hold_reason(screen: str, busy: bool = False) -> str | None:
    """Why typing into this screen is unsafe, or None when it is safe.

    ``busy`` also holds on a running turn. Only the post-delay re-check passes it:
    while a Stop hook runs, the footer still reads "esc to interrupt" (seen live,
    2.1.296), so the in-hook check would hold every handover.
    """
    row = input_row(screen)
    if row is None:
        return "no empty prompt box is on screen"
    if _FOOTER.search(plain(screen)):
        return "a dialog or permission prompt is open"
    if busy and _BUSY.search(below_box(screen)):
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


def pane_hold_reason(target: str, busy: bool = False) -> str | None:
    """None when the pane is safe to type into; otherwise why we must not."""
    mode = _tmux("display-message", "-p", "-t", target, "#{pane_in_mode}")
    if mode is not None and mode.returncode == 0 and mode.stdout.strip() == "1":
        return "the pane is in copy mode"
    shot = _tmux("capture-pane", "-p", "-e", "-t", target)
    if shot is None or shot.returncode != 0:
        return "the pane could not be read (tmux capture-pane failed)"
    return hold_reason(shot.stdout, busy)
