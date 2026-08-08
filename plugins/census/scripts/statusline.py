"""Idempotent install/removal of the census block in a status-line script.

Pure text transforms so they are unit-testable without touching the user's real
``~/.claude/statusline-command.sh``. The block is delimited by sentinel comments
so removal is exact and re-install is a no-op.
"""
from __future__ import annotations

START = "# --- census: record status-line payload (managed by `census`; do not edit) ---"
END = "# --- end census ---"
INGEST = "printf '%s' \"$input\" | census ingest 2>/dev/null || true"

# The line most status-line scripts use to slurp stdin; we insert just after it
# so `$input` is already populated. Absent that, we append to the end.
DEFAULT_ANCHOR = "input=$(cat)"


def block() -> str:
    return f"{START}\n{INGEST}\n{END}\n"


def is_installed(text: str) -> bool:
    return START in text


def add_block(text: str, anchor: str = DEFAULT_ANCHOR) -> str:
    """Insert the census block after ``anchor`` (or append). Idempotent."""
    if is_installed(text):
        return text
    payload = block()

    if anchor and anchor in text:
        out: list[str] = []
        inserted = False
        for line in text.splitlines(keepends=True):
            out.append(line if line.endswith("\n") else line + "\n")
            if not inserted and anchor in line:
                out.append("\n" + payload)
                inserted = True
        return "".join(out)

    separator = "" if text == "" or text.endswith("\n") else "\n"
    return f"{text}{separator}\n{payload}"


def remove_block(text: str) -> str:
    """Strip the census block (between sentinels, inclusive). Idempotent."""
    if not is_installed(text):
        return text
    out: list[str] = []
    skipping = False
    for line in text.splitlines(keepends=True):
        if START in line:
            if out and out[-1].strip() == "":  # reclaim the blank line add_block inserted
                out.pop()
            skipping = True
            continue
        if skipping:
            if END in line:
                skipping = False
            continue
        out.append(line)
    return "".join(out)
