"""Every user-facing line (spec §4) and the one emitter for hook systemMessages.

User-facing text is shown on screen (terminal, desktop, phone) and never reaches the
model. Model-facing text lives in hooks.py and stays plain.
"""
from __future__ import annotations

import json

MAX_LEN = 300

NOTICE_FIRST = ('🕯️ context-vigil · context at {pct}% (threshold {threshold}%) · say '
                '"hand over" to pass the torch 🔥 — or keep going 🚀')
NOTICE_REPEAT = ('🕯️ context-vigil · now at {pct}% ⬆️ · say "hand over" whenever '
                 "you're ready 📜")
SAVED_TYPE_CLEAR = ('📜 Handover saved — type /clear, then send any message (e.g. "go") '
                    'to pick it back up ✨ (run Claude inside tmux for hands-free '
                    'handovers 🤖)')
SAVED_DIALOG_OPEN = ('📜 Handover saved — a dialog is open, so /clear was not typed for '
                     'you: answer it, then type /clear ✨')
LAST_LIGHT_PREPARED = ('🌅 Last light: a handover is ready 📜 — carry on as normal, or '
                       '/clear to resume from it ✨')


def system_message(text: str) -> str:
    """The hook's whole stdout: one JSON object whose only key is ``systemMessage``.

    ``json.dumps`` does all escaping; the text is cut to ``MAX_LEN`` characters."""
    return json.dumps({"systemMessage": text[:MAX_LEN]})
