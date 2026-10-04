"""Is a Claude Code pane safe to type into? Read from a ``capture-pane -p -e`` screen.

Safe means: the prompt box is on screen (a ``❯`` row directly under a full-width
rule), it holds nothing the person typed (the idle placeholder is drawn dim, SGR 2,
and does not count), and no menu/dialog footer is showing. Anything we cannot read
is unsafe: typing into a dialog can answer a permission prompt or a trust prompt.
"""
from __future__ import annotations

import re
from typing import List, Optional

from context_vigil import tmux

_SGR = re.compile(r"\x1b\[([0-9;]*)m")
_OTHER_ESC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
_RULE = re.compile(r"^\s*─{10,}\s*$")
_FOOTER = re.compile(r"(?i)enter to (select|confirm)|esc to (cancel|continue)")
_BLANKS = " \t\xa0"


def plain(text: str) -> str:
    return _SGR.sub("", _OTHER_ESC.sub("", text))


def typed_text(row: str) -> str:
    """The characters after the first ``❯`` that are NOT drawn dim, stripped."""
    _, _, rest = row.partition("❯")
    rest = _OTHER_ESC.sub("", rest)
    out: List[str] = []
    dim = False
    pos = 0
    for match in _SGR.finditer(rest):
        if not dim:
            out.append(rest[pos:match.start()])
        params = [p for p in match.group(1).split(";") if p] or ["0"]
        for p in params:
            if p == "2":
                dim = True
            elif p in ("0", "22"):
                dim = False
        pos = match.end()
    if not dim:
        out.append(rest[pos:])
    return "".join(out).strip(_BLANKS)


def input_row(screen: str) -> Optional[str]:
    """The prompt box's ``❯`` row (raw, escapes kept): the last ``❯`` row whose
    line above is a full-width rule. None when no prompt box is on screen."""
    raw = screen.splitlines()
    found: Optional[str] = None
    for i in range(1, len(raw)):
        if plain(raw[i]).lstrip(_BLANKS).startswith("❯") and _RULE.match(plain(raw[i - 1])):
            found = raw[i]
    return found


def safe_to_type(screen: str) -> bool:
    row = input_row(screen)
    if row is None:
        return False
    if _FOOTER.search(plain(screen)):
        return False
    return typed_text(row) == ""


def pane_safe(target: str) -> bool:
    screen = tmux.capture(target)
    return screen is not None and safe_to_type(screen)
