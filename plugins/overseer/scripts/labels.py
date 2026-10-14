"""The repo-label rule shared by the host (``/api/exec`` resolver) and the
container client (``OVERSEER_REMOTE_REPO``). Stdlib only, so the remote client
can import it without pulling in the board code."""
from __future__ import annotations

import re

LABEL_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def valid_label(name: object) -> bool:
    """A repo label as exec accepts it: the charset, and not ``.`` or ``..``."""
    return isinstance(name, str) and name not in (".", "..") and LABEL_RE.fullmatch(name) is not None
