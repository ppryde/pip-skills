"""The remote side of a "prod-access" pull (WF-122): runs on the box itself,
fed to whatever ``python3`` it has via ``ssh <host> -- python3 -`` (the
script text on stdin — see ``scripts.remote.bundle_source``). It ONLY READS:
nothing here ever opens a file for writing, deletes anything, or makes a
network call of its own. It must stay Python 3.8-compatible source (no
walrus, no ``match``, no ``dataclass(slots)``): a real box in the wild runs
whatever system python3 it shipped with.

This file is never imported — the client concatenates it AFTER
``redact.py``'s source into one script, so `slim_line`, `slim_meta`,
`iter_complete_lines`, `MAX_LINE_BYTES` and `FIDELITIES` are already in this
module's global namespace by the time the code below runs (see
``scripts.remote.bundle_source``, which is the one place that ordering is
load-bearing). Nothing here does ``import redact``: on the remote box there
is no file to import it from.

Protocol (see the README's "Remote boxes" section for the worked example):

Request — one JSON object, base64-encoded, passed as ``sys.argv[1]`` (never
on stdin: stdin IS the script text, and ``python3 -`` reads it to EOF before
the interpreter starts, so nothing can follow it on the same stream)::

    {"claude_dir": "/opt/wf-state/.config/claude", "fidelity": "minimal",
     "state": {"<relpath>": {"offset": N, "size": M}, ...},
     "max_bytes": 8000000, "deadline_s": 45}

``state`` is the ORIGINAL-file byte offset the client has already consumed
for each relpath it knows about (a file the client has never seen is simply
absent — read from 0).

Response — newline-delimited JSON to stdout, one frame per line::

    {"t": "list", "files": [{"relpath", "size", "mtime"}, ...]}
    {"t": "file", "file", "from_offset", "to_offset", "lines": [...], "truncated": bool}
    {"t": "meta", "file", "content": "<slimmed JSON text>" | null}
    {"t": "account", "profile": {...} | null}
    {"t": "done", "partial": bool, "files_sent": N, "bytes_sent": N}
    {"t": "error", "error": "<message>"}

A malformed request, an unreadable claude_dir, or any other failure is
reported as one ``error`` frame; the process still exits 0 — a nonzero exit
or garbled stdout is what the CLIENT treats as "this remote failed this
round" (see ``scripts.remote``), so a caught, reported error is the well-
behaved outcome, not the exceptional one.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import re
import sys
import time

# Same alphabet `claude` writes transcripts in (see scripts/volumes.py's
# identical regexes for the local-disk equivalent of this listing) — a name
# outside it is not a transcript this agent will ever read, however it got
# there. `_SEG` deliberately excludes "/", so `_MAIN_RE`/`_SUBAGENT_RE` cannot
# be tricked into stepping outside `projects/` no matter what `claude_dir`
# says: those two patterns are matched against a path ALREADY MADE RELATIVE TO
# `projects/`, so a leading ".." would have to survive as a literal "..",
# which `_SEG`'s exclusion of "/" keeps confined to one segment, and the
# `_RELPATH_RE` used for meta files rejects outright.
_SEG = r"[A-Za-z0-9._-]+"
_MAIN_RE = re.compile(r"^(?P<slug>" + _SEG + r")/(?P<session>" + _SEG + r")\.jsonl$")
_SUBAGENT_RE = re.compile(r"^(?P<slug>" + _SEG + r")/(?P<session>" + _SEG
                         + r")/subagents/agent-(?P<agent>[A-Za-z0-9_-]+)\.jsonl$")
_META_RE = re.compile(r"^(?P<slug>" + _SEG + r")/(?P<session>" + _SEG
                     + r")/subagents/agent-(?P<agent>[A-Za-z0-9_-]+)\.meta\.json$")

DEFAULT_MAX_BYTES = 8_000_000
DEFAULT_DEADLINE_S = 45.0
READ_BLOCK = 1 << 20


class _Deadline:
    """A wall-clock budget shared across every file this call reads, so one
    huge transcript cannot starve the rest of a sync round."""

    def __init__(self, deadline_s):
        self.stop_at = time.time() + max(0.0, float(deadline_s))

    def expired(self):
        return time.time() >= self.stop_at


def _iter_project_files(projects_root):
    """Every ``*.jsonl`` under ``projects_root`` whose path (relative to it)
    matches the main-transcript or subagent shape, plus every subagent
    ``.meta.json`` — as ``(relpath, kind, size, mtime)``, ``kind`` one of
    ``"jsonl"``/``"meta"``. Anything else on disk (a stray file, a `claude`
    version that lays things out differently) is silently skipped: this
    walks READS, it never assumes the shape of a directory it did not ask
    Claude Code to write."""
    out = []
    for dirpath, _dirnames, filenames in os.walk(projects_root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, projects_root).replace(os.sep, "/")
            if name.endswith(".jsonl") and (_MAIN_RE.match(rel) or _SUBAGENT_RE.match(rel)):
                kind = "jsonl"
            elif name.endswith(".meta.json") and _META_RE.match(rel):
                kind = "meta"
            else:
                continue
            try:
                st = os.stat(full)
            except OSError:
                continue
            out.append((rel, kind, st.st_size, st.st_mtime))
    return out


def _read_jsonl_frame(full_path, relpath, offset, size, fidelity, deadline, bytes_left):
    """One ``file`` frame for ``relpath`` as ``(frame_or_None, sent_bytes,
    finished)`` — ``finished`` is False whenever this file has more
    (original) bytes past ``to_offset`` that this call did not get to, so the
    caller can tell "budget ran out mid-file" apart from "this file is fully
    caught up", which the RETURNED BYTE COUNT alone cannot: a small
    redacted-output count can still mean a large unread remainder (redaction
    shrinks lines a lot), and reading exactly `bytes_left` original bytes can
    still land mid-line. ``None`` for the frame itself means there is nothing
    NEW to send (offset already at size, and it did not shrink)."""
    start = 0 if offset > size else offset
    truncated = offset > size
    if start >= size and not truncated:
        return None, 0, True
    lines_out = []
    sent_bytes = 0
    to_offset = start
    try:
        handle = open(full_path, "rb")  # noqa: SIM115 - OSError here is caught separately from the read loop
    except OSError:
        return None, 0, True
    with handle:
        limit = max(0, min(bytes_left, size - start))
        for raw, end in iter_complete_lines(  # noqa: F821 - defined by redact.py, bundled ahead of this file
            handle, start, limit if limit else 1, deadline.expired, READ_BLOCK):
            to_offset = end
            if raw is None:
                continue
            slimmed = slim_line(raw, fidelity)  # noqa: F821 - see module docstring
            if slimmed is not None:
                lines_out.append(slimmed)
                sent_bytes += len(slimmed)
            if sent_bytes >= bytes_left or deadline.expired():
                break
    finished = to_offset >= size
    if not lines_out and to_offset == start and not truncated:
        return None, 0, finished
    return ({"t": "file", "file": relpath, "from_offset": start, "to_offset": to_offset,
            "lines": lines_out, "truncated": truncated}, sent_bytes, finished)


def _read_meta_frame(full_path, relpath, known_size, size, fidelity):
    """One ``meta`` frame — None when the file has not changed size since the
    client last saw it (meta files are tiny and rewritten whole, not
    appended, so a size check is the whole change test)."""
    if known_size == size:
        return None
    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return None
    content = slim_meta(text, fidelity)  # noqa: F821 - see module docstring
    return {"t": "meta", "file": relpath, "content": content}


def _account_profile_text(claude_dir):
    try:
        with open(os.path.join(claude_dir, ".claude.json"), "r", encoding="utf-8",
                  errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


# The ONLY fields ever read out of `.claude.json` — duplicated from
# `store.ACCOUNT_IDENTITY_FIELDS`/`ACCOUNT_PLAN_FIELDS` rather than imported
# (this file imports nothing from chronicle): the remote box must apply this
# whitelist itself, before the text leaves it, not trust the client to.
_ACCOUNT_FIELDS = ("accountUuid", "organizationUuid", "organizationType", "seatTier",
                  "billingType", "organizationRateLimitTier")


def _whitelisted_account_profile(claude_dir):
    text = _account_profile_text(claude_dir)
    if text is None:
        return None
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    oauth = data.get("oauthAccount")
    if not isinstance(oauth, dict):
        return {}
    out = {}
    for key in _ACCOUNT_FIELDS:
        value = oauth.get(key)
        if isinstance(value, str) and value:
            out[key] = value
    return out


def _emit(frame):
    sys.stdout.write(json.dumps(frame, separators=(",", ":")))
    sys.stdout.write("\n")
    sys.stdout.flush()


def run(request):
    claude_dir = request.get("claude_dir")
    fidelity = request.get("fidelity", "minimal")
    state = request.get("state") if isinstance(request.get("state"), dict) else {}
    max_bytes = request.get("max_bytes", DEFAULT_MAX_BYTES)
    deadline_s = request.get("deadline_s", DEFAULT_DEADLINE_S)
    if not isinstance(claude_dir, str) or not claude_dir:
        _emit({"t": "error", "error": "missing claude_dir"})
        return
    if fidelity not in FIDELITIES:  # noqa: F821 - see module docstring
        _emit({"t": "error", "error": f"unknown fidelity: {fidelity!r}"})
        return
    projects_root = os.path.join(claude_dir, "projects")
    python_version = "{}.{}.{}".format(*sys.version_info[:3])
    if not os.path.isdir(projects_root):
        _emit({"t": "list", "files": [], "projects_dir_exists": False,
              "python_version": python_version})
        _emit({"t": "account", "profile": _whitelisted_account_profile(claude_dir)})
        _emit({"t": "done", "partial": False, "files_sent": 0, "bytes_sent": 0})
        return
    entries = _iter_project_files(projects_root)
    _emit({"t": "list", "projects_dir_exists": True, "python_version": python_version,
          "files": [{"relpath": rel, "size": size, "mtime": mtime}
                    for rel, _kind, size, mtime in entries]})
    deadline = _Deadline(deadline_s)
    bytes_left = max(0, int(max_bytes)) if isinstance(max_bytes, (int, float)) else DEFAULT_MAX_BYTES
    files_sent = 0
    bytes_sent = 0
    partial = False
    for relpath, kind, size, mtime in sorted(entries):
        if deadline.expired() or bytes_left <= 0:
            partial = True
            break
        full = os.path.join(projects_root, relpath)
        if kind == "meta":
            known = state.get(relpath, {})
            known_size = known.get("size") if isinstance(known, dict) else None
            frame = _read_meta_frame(full, relpath, known_size, size, fidelity)
            if frame is not None:
                _emit(frame)
                files_sent += 1
            continue
        known = state.get(relpath, {})
        offset = known.get("offset", 0) if isinstance(known, dict) else 0
        if not isinstance(offset, int) or offset < 0:
            offset = 0
        frame, sent, finished = _read_jsonl_frame(full, relpath, offset, size, fidelity, deadline,
                                                  bytes_left)
        if not finished:
            partial = True
        if frame is not None:
            _emit(frame)
            files_sent += 1
            bytes_sent += sent
            bytes_left -= sent
    if deadline.expired() and not partial:
        partial = True
    _emit({"t": "account", "profile": _whitelisted_account_profile(claude_dir)})
    _emit({"t": "done", "partial": partial, "files_sent": files_sent, "bytes_sent": bytes_sent})


def main(argv):
    if len(argv) < 2:
        _emit({"t": "error", "error": "no request argument"})
        return 0
    try:
        request = json.loads(base64.b64decode(argv[1]).decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        _emit({"t": "error", "error": f"bad request: {exc}"})
        return 0
    if not isinstance(request, dict):
        _emit({"t": "error", "error": "request is not an object"})
        return 0
    try:
        run(request)
    except Exception as exc:  # noqa: BLE001 - the contract is: never raise, never crash silently
        _emit({"t": "error", "error": f"{type(exc).__name__}: {exc}"})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
