"""Has a file changed since the agent read it? Compares the blob of a whole-file Read with
the file now. Partial reads cannot tell, so they answer "unknown"."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess

from scripts.replay.transcript import ToolCall

_PREFIX = re.compile(r"^\s*\d+\t")


_READ_CAP = 2000  # Read's default line cap: a read that reaches it may be truncated


def full_read_blob(call: ToolCall) -> str | None:
    if call.name != "Read" or "offset" in call.input or "limit" in call.input:
        return None
    lines = call.result_text.split("\n")
    stripped: list[str] = []
    last = 0
    for line in lines:
        m = _PREFIX.match(line)
        if m is None:
            return None  # reminder block, truncation notice, empty-file message
        stripped.append(line[m.end():])
        last = int(m.group().strip())
    if last >= _READ_CAP:
        return None
    data = "\n".join(stripped).encode("utf-8")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()  # git's blob id


def _resolve(path: str, cwd: str) -> str:
    return os.path.realpath(path if os.path.isabs(path) else os.path.join(cwd, path))


def drifted(calls: list[ToolCall], path: str, cwd: str) -> str:
    want = _resolve(path, cwd)
    seen = None
    for call in calls:
        target = call.input.get("file_path")
        if call.name == "Read" and isinstance(target, str) \
                and _resolve(target, call.cwd or cwd) == want:
            blob = full_read_blob(call)
            if blob is not None:
                seen = blob
    if seen is None:
        return "unknown"
    try:
        now = subprocess.run(["git", "hash-object", "--", want], cwd=cwd, capture_output=True,
                             text=True, timeout=10, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return "no" if now == seen else "yes"
