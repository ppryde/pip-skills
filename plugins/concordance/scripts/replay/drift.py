"""Has a file changed since the agent read it? Compares the blob of a whole-file Read with
the file now. Partial reads cannot tell, so they answer "unknown"."""
from __future__ import annotations

import hashlib
import re
import subprocess

from scripts.replay.transcript import ToolCall

_PREFIX = re.compile(r"^\s*\d+\t")


def full_read_blob(call: ToolCall) -> str | None:
    if call.name != "Read" or "offset" in call.input or "limit" in call.input:
        return None
    text = call.result_text
    body = "\n".join(_PREFIX.sub("", line, count=1) for line in text.splitlines())
    if text.endswith("\n"):
        body += "\n"
    data = body.encode("utf-8")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()  # git's blob id


def drifted(calls: list[ToolCall], path: str, cwd: str) -> str:
    seen = None
    for call in calls:
        if call.name == "Read" and call.input.get("file_path") == path:
            blob = full_read_blob(call)
            if blob is not None:
                seen = blob
    if seen is None:
        return "unknown"
    try:
        now = subprocess.run(["git", "hash-object", "--", path], cwd=cwd, capture_output=True,
                             text=True, timeout=10, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return "no" if now == seen else "yes"
