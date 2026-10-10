"""Parse the machine-readable `allowed-exceptions` block of a reviewer file.

Every reviewer ends with:

    ## Allowed exceptions
    One sentence saying what is excused and why.

    ```allowed-exceptions
    GEN-009   # reason, free text after '#'
    ```

Zero or more rule ids, one per line. Blank lines and comment-only lines are
not entries, so an empty (or comment-only) block means "none". Exactly one
block per file. Under `pragmatic` strictness a finding whose `rule_id` is
listed is capped at `warning` (see strictness.py)."""
from __future__ import annotations

import re
from pathlib import Path

from scripts.contract import rule_id_of

_OPEN = re.compile(r"^```allowed-exceptions[ \t]*$")
_CLOSE = re.compile(r"^```[ \t]*$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ExceptionsError(Exception):
    """The reviewer file's allowed-exceptions block is absent or malformed."""


def parse_allowed_exceptions(text: str) -> dict[str, str]:
    """Rule id -> reason. Raises ExceptionsError on no block, two blocks, an
    unterminated block, or an entry that is not a rule id."""
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        if current is None:
            if _OPEN.match(line):
                current = []
        elif _CLOSE.match(line):
            blocks.append(current)
            current = None
        else:
            current.append(line)
    if current is not None:
        raise ExceptionsError("allowed-exceptions block is not closed")
    if not blocks:
        raise ExceptionsError("no ```allowed-exceptions block")
    if len(blocks) > 1:
        raise ExceptionsError(f"{len(blocks)} allowed-exceptions blocks; exactly one is allowed")
    out: dict[str, str] = {}
    for raw in blocks[0]:
        entry, _, reason = raw.partition("#")
        entry = entry.strip()
        if not entry:
            continue
        if rule_id_of(entry) != entry:
            raise ExceptionsError(f"not a rule id: {entry!r}")
        out[entry] = reason.strip()
    return out


def load_allowed_exceptions(
    reviewers_dir: Path, names: list[str], warnings: list[str] | None = None
) -> dict[str, set[str]]:
    """Exceptions keyed by bare reviewer name, as `apply_strictness` expects.

    A reviewer with no file here (a clone persona, whose "what they let go"
    list stays a subagent-side gate) contributes an empty set. A custom file
    with a missing or malformed block runs as "no exceptions" and appends a
    warning rather than failing the review."""
    out: dict[str, set[str]] = {}
    for name in names:
        out[name] = set()
        if not _NAME.match(name) or ".." in name:
            continue
        path = Path(reviewers_dir) / f"{name}.md"
        if not path.is_file():
            continue
        try:
            out[name] = set(parse_allowed_exceptions(path.read_text()))
        except ExceptionsError as exc:
            if warnings is not None:
                warnings.append(f"{path.name}: {exc}; treating as no exceptions")
    return out
