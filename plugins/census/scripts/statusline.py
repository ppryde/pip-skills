"""Idempotent install/removal of the census block in a status-line script.

Pure text transforms so they are unit-testable without touching the user's real
``~/.claude/statusline-command.sh``. The block is delimited by sentinel comments
so removal is exact and re-install is a no-op.
"""
from __future__ import annotations

import shlex

START = "# --- census: record status-line payload (managed by `census`; do not edit) ---"
END = "# --- end census ---"
INGEST = "printf '%s' \"$input\" | census ingest 2>/dev/null || true"

# The line most status-line scripts use to slurp stdin; we insert just after it
# so `$input` is already populated. Absent that, we append to the end.
DEFAULT_ANCHOR = "input=$(cat)"


def ingest_command(shim: str | None = None) -> str:
    """The pipe-to-ingest line; ``shim`` is the launcher it must call (default: ``census`` on PATH)."""
    if shim is None:
        return INGEST
    return INGEST.replace("| census ingest", f"| {shlex.quote(shim)} ingest")


def block(ingest: str = INGEST) -> str:
    return f"{START}\n{ingest}\n{END}\n"


def is_installed(text: str) -> bool:
    return START in text


def _is_anchor(line: str, anchor: str) -> bool:
    """A real use of the anchor, not a comment that mentions it."""
    stripped = line.strip()
    return not stripped.startswith("#") and stripped.startswith(anchor)


def add_block(text: str, anchor: str = DEFAULT_ANCHOR, ingest: str = INGEST) -> str:
    """Insert the census block after ``anchor`` (or append). Idempotent. Every
    existing line is kept byte for byte; only the block and the separators it
    needs are added."""
    if is_installed(text):
        return text
    payload = block(ingest)

    if anchor:
        out: list[str] = []
        inserted = False
        for line in text.splitlines(keepends=True):
            out.append(line)
            if not inserted and _is_anchor(line, anchor):
                if not line.endswith("\n"):  # the anchor is an unterminated last line
                    out.append("\n\n" + payload[:-1])
                else:
                    out.append("\n" + payload)
                inserted = True
        if inserted:
            return "".join(out)

    separator = "" if text == "" or text.endswith("\n") else "\n"
    return f"{text}{separator}\n{payload}"


def remove_block(text: str) -> str:
    """Strip the census block (START through END, inclusive). Idempotent. A START
    with no END after it is not a block census wrote: the text is returned unchanged."""
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if START in line), None)
    if start is None:
        return text
    end = next((i for i in range(start + 1, len(lines)) if END in lines[i]), None)
    if end is None:
        return text
    head = lines[:start]
    if head and head[-1].strip() == "":  # reclaim the blank line add_block inserted
        head.pop()
    if not lines[end].endswith("\n") and head and head[-1].endswith("\n"):
        head[-1] = head[-1][:-1]  # add_block terminated an unterminated last line; undo that
    rest = lines[end + 1:]
    return "".join(head + rest)
