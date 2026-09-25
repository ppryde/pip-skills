"""A stand-in for the ``docker`` CLI, serving named volumes from directories
under ``tmp_path``. The subprocess boundary is the ONLY thing mocked: the
scripts `VolumeSource` sends are recognised by identity, and answered by the
same logic they would run in the helper container.

Nothing here (or in any test that uses it) ever reaches a real docker."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from scripts import volumes


class FakeDocker:
    """``volumes`` maps a volume name to the directory standing in for its
    root. ``failure`` is raised (an Exception) or returned (a CompletedProcess)
    for every ``docker run``; ``inspect_failure`` likewise for ``volume inspect``.
    ``account_json`` overrides what the account script prints for a volume."""

    def __init__(self, vols: dict[str, Path] | None = None, *,
                 failure: subprocess.CompletedProcess[bytes] | Exception | None = None,
                 inspect_failure: Exception | None = None) -> None:
        self.volumes = vols or {}
        self.failure = failure
        self.inspect_failure = inspect_failure
        self.calls: list[tuple[list[str], bytes]] = []
        self.timeouts: list[int] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> FakeDocker:
        monkeypatch.setattr(volumes, "_exec", self)
        return self

    # -- inspection helpers for assertions --------------------------------
    def runs(self, script: str) -> list[tuple[list[str], bytes]]:
        return [c for c in self.calls if c[0][1] == "run" and script in c[0]]

    def reads(self) -> list[list[tuple[int, str]]]:
        """Each read call's requests, as (offset, relpath) pairs."""
        out = []
        for _, stdin in self.runs(volumes._READ_SCRIPT):
            out.append([(int(o), p) for o, p in (ln.split(" ", 1) for ln in stdin.decode().splitlines())])
        return out

    # -- the subprocess.run replacement -----------------------------------
    def __call__(self, cmd: list[str], *, stdin: bytes = b"", timeout: int = 0
                 ) -> subprocess.CompletedProcess[bytes]:
        input = stdin
        self.calls.append((list(cmd), input))
        self.timeouts.append(timeout)
        if cmd[1:3] == ["volume", "inspect"]:
            if self.inspect_failure is not None:
                raise self.inspect_failure
            name = cmd[3]
            if name in self.volumes:
                return subprocess.CompletedProcess(cmd, 0, b"[]", b"")
            return subprocess.CompletedProcess(
                cmd, 1, b"", f"Error: No such volume: {name}".encode())
        assert cmd[:2] == ["docker", "run"], cmd
        # Every helper must be read-only and offline.
        volume_arg = cmd[cmd.index("-v") + 1]
        assert volume_arg.endswith(":/v:ro"), f"volume not mounted read-only: {volume_arg}"
        assert cmd[cmd.index("--network") + 1] == "none"
        if isinstance(self.failure, Exception):
            raise self.failure
        if self.failure is not None:
            return self.failure
        name = volume_arg.removesuffix(":/v:ro")
        script, claude_dir = cmd[-3], cmd[-1]
        root = self.volumes[name] / claude_dir
        if script == volumes._LIST_SCRIPT:
            stdout = self._list(root / "projects")
        elif script == volumes._READ_SCRIPT:
            stdout = self._read(root / "projects", input)
        elif script == volumes._ACCOUNT_SCRIPT:
            account = root / ".claude.json"
            stdout = account.read_bytes() if account.exists() else b""
        else:
            raise AssertionError(f"unrecognised helper script: {script!r}")
        return subprocess.CompletedProcess(cmd, 0, stdout, b"")

    @staticmethod
    def _list(projects: Path) -> bytes:
        files = sorted(p for p in projects.rglob("*.jsonl")
                       if 2 <= len(p.relative_to(projects).parts) <= 4)
        return b"".join(
            f"{int(p.stat().st_mtime)} {p.stat().st_size} ./{p.relative_to(projects).as_posix()}\n".encode()
            for p in files
        )

    @staticmethod
    def _read(projects: Path, stdin: bytes) -> bytes:
        out = b""
        for line in stdin.decode().splitlines():
            offset, relpath = line.split(" ", 1)
            path = projects / relpath
            if path.is_file():
                chunk = path.read_bytes()[int(offset):]
                out += f"{len(chunk)} {relpath}\n".encode() + chunk
        return out
