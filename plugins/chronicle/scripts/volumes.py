"""Read a Docker named volume's transcripts IN PLACE, through short-lived
read-only helper containers.

A named volume lives inside Docker's VM (on macOS its mountpoint is not a host
path), so no host process can open its files. `pull-volume` copied them out by
hand and went stale the day nobody re-ran it. This reads them where they are:
one helper-container call lists every transcript with its mtime and size, and
a second reads only the byte ranges `ingest` says it has not seen — so a sync
with nothing new is one listing and no reads.

Every helper mounts the volume ``:ro`` with networking off, and both values a
caller controls (the volume name and the Claude dir) are validated before they
reach an argv (`store.normalise_volume`). The Claude dir is passed to the
script as ``$1``, never interpolated into its text.

Nothing here raises past `VolumeError`: docker absent, volume missing, a
helper that times out or exits non-zero all become one, which `ingest.sync`
turns into a per-volume entry in its ``volume_errors`` and moves on.
"""
from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property

from scripts import store

DEFAULT_IMAGE = "alpine:3.20.3"  # exact tag, not floating `latest`
# The dashboard gives the whole `chronicle sync` 120s; these keep any single
# helper well inside that, so a wedged docker daemon costs one volume one sync.
LIST_TIMEOUT_SECONDS = 30
READ_TIMEOUT_SECONDS = 100
ACCOUNT_TIMEOUT_SECONDS = 30

# The image is validated for the same reason as the volume, and more urgently:
# it sits at the one argv position where docker is still parsing its own options.
_IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-/:@]*$")
# What `claude` names things: slugs are the cwd with every non-alphanumeric
# turned into "-", sessions are uuids, agents are short ids. Anything outside
# this alphabet is not a transcript we wrote, and is never fed to the read script.
_SEG = r"[A-Za-z0-9._-]+"
_MAIN_RE = re.compile(rf"^(?P<slug>{_SEG})/(?P<session>{_SEG})\.jsonl$")
_SUBAGENT_RE = re.compile(
    rf"^(?P<slug>{_SEG})/(?P<session>{_SEG})/subagents/agent-(?P<agent>[A-Za-z0-9_-]+)\.jsonl$"
)

_RELPATH_RE = re.compile(rf"^{_SEG}(/{_SEG})*$")


def _safe_relpath(relpath: str) -> bool:
    """A transcript-shaped path with no ``.``/``..`` segment: `_SEG` alone
    would let ``..`` through, and the read script ``cd``s into the volume."""
    return bool(_RELPATH_RE.match(relpath)) and not any(
        part in (".", "..") for part in relpath.split("/"))


_LIST_SCRIPT = """cd "/v/$1/projects" 2>/dev/null || exit 0
find . -mindepth 2 -maxdepth 4 -type f -name '*.jsonl' -exec stat -c '%Y %s %n' {} +"""

# stdin: `<offset> <relpath>` per line. stdout: `<length> <relpath>\\n` then
# exactly that many bytes, per file that exists. `tail -c +N` is 1-based.
_READ_SCRIPT = """cd "/v/$1/projects" || exit 1
while read -r offset path; do
  [ -f "./$path" ] || continue
  tail -c +$((offset + 1)) "./$path" > /tmp/chunk
  printf '%s %s\\n' "$(stat -c %s /tmp/chunk)" "$path"
  cat /tmp/chunk
done"""

_ACCOUNT_SCRIPT = 'cat "/v/$1/.claude.json" 2>/dev/null || true'


class VolumeError(Exception):
    """A volume could not be read. The message is fit to show a person."""


@dataclass(frozen=True)
class RemoteFile:
    relpath: str     # relative to the volume's `<claude_dir>/projects`
    mtime: float
    size: int

    @property
    def meta_relpath(self) -> str:
        return self.relpath.removesuffix(".jsonl") + ".meta.json"


@dataclass(frozen=True)
class RemoteSession:
    session_id: str
    slug: str
    main: RemoteFile
    subagents: tuple[tuple[str, RemoteFile], ...]

    @property
    def files(self) -> list[RemoteFile]:
        return [self.main, *(f for _, f in self.subagents)]


def group_sessions(files: Sequence[RemoteFile]) -> list[RemoteSession]:
    """Main transcripts with their subagent files folded in, like the local
    walk: a subagent file whose main transcript is absent is not reached."""
    by_rel = {f.relpath: f for f in files}
    subs: dict[str, list[tuple[str, RemoteFile]]] = {}
    for relpath, file in sorted(by_rel.items()):
        match = _SUBAGENT_RE.match(relpath)
        if match:
            parent = f"{match['slug']}/{match['session']}.jsonl"
            subs.setdefault(parent, []).append((match["agent"], file))
    return [
        RemoteSession(match["session"], match["slug"], file, tuple(subs.get(relpath, [])))
        for relpath, file in sorted(by_rel.items())
        if (match := _MAIN_RE.match(relpath))
    ]


def _exec(cmd: list[str], *, stdin: bytes, timeout: int) -> subprocess.CompletedProcess[bytes]:
    """The one place a process is spawned — and so the one seam the tests
    replace. Nothing else in this module (or its tests) reaches `subprocess`."""
    return subprocess.run(cmd, input=stdin, capture_output=True, timeout=timeout, check=False)


def _docker(cmd: list[str], *, stdin: bytes = b"",
            timeout: int) -> subprocess.CompletedProcess[bytes]:
    try:
        return _exec(cmd, stdin=stdin, timeout=timeout)
    except FileNotFoundError as exc:
        raise VolumeError("docker not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise VolumeError(f"docker timed out after {timeout}s") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise VolumeError(f"docker failed: {exc}") from exc


def _stderr(completed: subprocess.CompletedProcess[bytes]) -> str:
    return completed.stderr.decode(errors="replace").strip()[:500] or "docker failed"


def volume_exists(name: str) -> bool:
    """Whether Docker has a volume called ``name``. Raises `VolumeError` when
    Docker itself is unavailable (not installed, daemon down).

    Checked before any `docker run -v`, because that CREATES a missing named
    volume — a typo would otherwise silently mint an empty one and read it."""
    completed = _docker(["docker", "volume", "inspect", name], timeout=LIST_TIMEOUT_SECONDS)
    if completed.returncode == 0:
        return True
    if b"no such volume" in completed.stderr.lower():
        return False
    raise VolumeError(_stderr(completed))


class VolumeSource:
    """One configured volume, read through helper containers."""

    def __init__(self, name: str, claude_dir: str = store.DEFAULT_VOLUME_CLAUDE_DIR,
                 image: str = DEFAULT_IMAGE) -> None:
        volume = store.normalise_volume(name, claude_dir)   # ValueError on injection
        if not _IMAGE_RE.match(image):
            raise ValueError(f"invalid image: {image!r}")
        self.name = volume.name
        self.claude_dir = volume.claude_dir
        self.image = image
        self.label = volume.label

    @classmethod
    def of(cls, volume: store.Volume) -> VolumeSource:
        return cls(volume.name, volume.claude_dir)

    def key(self, relpath: str) -> str:
        """The stable synthetic path a transcript's cursor is filed under."""
        return f"{self.label}/{relpath}"

    def _run(self, script: str, *, stdin: bytes = b"", timeout: int) -> bytes:
        cmd = ["docker", "run", "--rm", "-i", "--network", "none",
               "-v", f"{self.name}:/v:ro", self.image, "sh", "-c", script, "sh", self.claude_dir]
        completed = _docker(cmd, stdin=stdin, timeout=timeout)
        if completed.returncode != 0:
            raise VolumeError(_stderr(completed))
        return completed.stdout

    def check(self) -> None:
        """Raise `VolumeError` unless the volume exists (once per source)."""
        if not self._exists:
            raise VolumeError(f"docker volume not found: {self.name}")

    @cached_property
    def _exists(self) -> bool:
        return volume_exists(self.name)

    def list_files(self) -> list[RemoteFile]:
        """Every transcript under ``<claude_dir>/projects`` in ONE helper call.
        Lines outside the alphabet `claude` writes are ignored; a line that
        does not parse at all means the output is not what we asked for."""
        self.check()
        raw = self._run(_LIST_SCRIPT, timeout=LIST_TIMEOUT_SECONDS)
        out: list[RemoteFile] = []
        try:
            for line in raw.decode(errors="replace").splitlines():
                mtime, size, path = line.split(" ", 2)
                relpath = path.removeprefix("./")
                if _safe_relpath(relpath) and (
                        _MAIN_RE.match(relpath) or _SUBAGENT_RE.match(relpath)):
                    out.append(RemoteFile(relpath, float(mtime), int(size)))
        except ValueError as exc:
            raise VolumeError(f"unexpected listing from {self.label}: {exc}") from exc
        return out

    def read(self, requests: Sequence[tuple[str, int]]) -> dict[str, bytes]:
        """The bytes of each ``(relpath, offset)`` from ``offset`` on, in one
        helper call. A file that vanished is simply absent from the result."""
        if not requests:
            return {}
        for relpath, offset in requests:
            # Belt and braces: the listing filter already guarantees this, and
            # `.meta.json` names are derived from it — but this is stdin to a
            # shell loop, so nothing unvetted goes through.
            if not _safe_relpath(relpath) or offset < 0:
                raise VolumeError(f"refusing to read {relpath!r}")
        stdin = "".join(f"{offset} {relpath}\n" for relpath, offset in requests).encode()
        raw = self._run(_READ_SCRIPT, stdin=stdin, timeout=READ_TIMEOUT_SECONDS)
        out: dict[str, bytes] = {}
        pos = 0
        try:
            while pos < len(raw):
                newline = raw.index(b"\n", pos)
                length_text, relpath = raw[pos:newline].decode().split(" ", 1)
                length = int(length_text)
                start = newline + 1
                if start + length > len(raw):
                    raise ValueError("output truncated")
                out[relpath] = raw[start:start + length]
                pos = start + length
        except ValueError as exc:
            raise VolumeError(f"unexpected read from {self.label}: {exc}") from exc
        return out

    def read_account(self) -> dict[str, str] | None:
        """The volume's account facts, whitelisted, or None when unreadable.

        The helper prints the whole ``.claude.json`` — which also holds an
        email address, a full name and an organisation name — but only
        `store.parse_account_profile`'s whitelist survives past this line:
        nothing else is stored, logged, or returned. Soft: an account we could
        not read costs a plan badge, not the transcripts."""
        try:
            text = self._run(_ACCOUNT_SCRIPT, timeout=ACCOUNT_TIMEOUT_SECONDS)
        except VolumeError:
            return None
        return store.parse_account_profile(text.decode(errors="replace"))
