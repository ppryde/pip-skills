# Overseer Remote Token Auto-Share Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the manual `OVERSEER_REMOTE_TOKEN` copy: the host persists an auto-generated token to a gitignored `<repo>/.overseer/remote-token`; the container reads it through the mounted repo.

**Architecture:** A stdlib-only `scripts/remote_token.py` owns the shared file location + IO. The host launcher persists the token there (stable across restarts); the CLI `--remote` path reads it as a fallback when the env var is unset. `OVERSEER_REMOTE_TOKEN` env still wins.

**Tech Stack:** Python 3.11, argparse, `secrets`, `os`/`pathlib` (stdlib), pytest.

## Global Constraints
- Spec: `docs/superpowers/specs/2026-08-19-overseer-remote-token-autoshare-design.md`.
- Security posture UNCHANGED: token still gates `/api/exec`; LAN guard still first; token check untouched. This changes token *distribution* only.
- Token resolution order (both sides): `OVERSEER_REMOTE_TOKEN` env → `<root>/.overseer/remote-token` file → default (host: generate+persist on non-loopback; container: None). Loopback host bind stays tokenless and writes no file.
- Token file is mode `0600` and gitignored.
- Interpreter: `/Users/philip.pryde/repos/pip-skills/.venv/bin/python`. Test commands:
  - CLI suite: `cd plugins/overseer && /Users/philip.pryde/repos/pip-skills/.venv/bin/python -m pytest -k <expr> -v`
  - Backend suite: `cd plugins/overseer/dashboard/backend && /Users/philip.pryde/repos/pip-skills/.venv/bin/python -m pytest <file> -v`
- Test isolation: pin `CLAUDE_CONFIG_DIR`/`OVERSEER_DB`/`OVERSEER_CENTRAL` to `tmp_path` (autouse fixtures already do this); token files live under a `tmp_path` root.
- Commit after each task.

---

### Task 1: `scripts/remote_token.py` — shared token-file location + IO

**Files:**
- Create: `plugins/overseer/scripts/remote_token.py`
- Test: `tests/overseer/test_remote_token.py`

**Interfaces:**
- Produces: `remote_token_path(root) -> pathlib.Path` (= `<root>/.overseer/remote-token`); `read_remote_token(root) -> str | None` (stripped token, None if missing/empty/unreadable, never raises); `write_remote_token(root, token) -> pathlib.Path` (creates `.overseer/`, writes token, chmod 0600).

- [ ] **Step 1: Write the failing test**

```python
# tests/overseer/test_remote_token.py
import stat

from scripts.remote_token import remote_token_path, read_remote_token, write_remote_token


def test_path_shape(tmp_path):
    assert remote_token_path(tmp_path) == tmp_path / ".overseer" / "remote-token"


def test_read_missing_returns_none(tmp_path):
    assert read_remote_token(tmp_path) is None


def test_read_blank_returns_none(tmp_path):
    p = remote_token_path(tmp_path)
    p.parent.mkdir(parents=True)
    p.write_text("   \n")
    assert read_remote_token(tmp_path) is None


def test_write_then_read_roundtrip(tmp_path):
    returned = write_remote_token(tmp_path, "tok-abc")
    assert returned == remote_token_path(tmp_path)
    assert read_remote_token(tmp_path) == "tok-abc"


def test_write_creates_overseer_dir_and_is_0600(tmp_path):
    p = write_remote_token(tmp_path, "tok-xyz")
    assert p.parent.name == ".overseer" and p.parent.is_dir()
    mode = stat.S_IMODE(p.stat().st_mode)
    assert mode == 0o600, oct(mode)


def test_write_tightens_preexisting_loose_mode(tmp_path):
    p = remote_token_path(tmp_path)
    p.parent.mkdir(parents=True)
    p.write_text("old")
    p.chmod(0o644)
    write_remote_token(tmp_path, "new")
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert read_remote_token(tmp_path) == "new"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/overseer && /Users/philip.pryde/repos/pip-skills/.venv/bin/python -m pytest -k remote_token -v`
Expected: FAIL — `scripts.remote_token` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# plugins/overseer/scripts/remote_token.py
"""Shared location + IO for the remote board API token file.

The host launcher (serve_board_api) persists an auto-generated token to
``<repo>/.overseer/remote-token``; a dev container that mounts the repo reads
the same file via the CLI ``--remote`` path — so the token is never copied by
hand. Stdlib only (no httpx): reading a token must not drag in the HTTP client.
The token still gates /api/exec; this module only distributes it.
"""
from __future__ import annotations

import os
from pathlib import Path

_TOKEN_FILENAME = "remote-token"


def remote_token_path(root: str | os.PathLike[str]) -> Path:
    """Path to the token file for a repo root: ``<root>/.overseer/remote-token``."""
    return Path(root) / ".overseer" / _TOKEN_FILENAME


def read_remote_token(root: str | os.PathLike[str]) -> str | None:
    """The persisted token for ``root``, or None if missing/empty/unreadable.

    Never raises — a missing or unreadable file simply means "no token here".
    """
    try:
        token = remote_token_path(root).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None


def write_remote_token(root: str | os.PathLike[str], token: str) -> Path:
    """Persist ``token`` at ``<root>/.overseer/remote-token`` with mode 0600.

    Creates ``.overseer/`` if needed. Opens with 0600 and re-chmods afterward
    so a pre-existing file with looser permissions is tightened.
    """
    path = remote_token_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(token)
    os.chmod(path, 0o600)
    return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/overseer && /Users/philip.pryde/repos/pip-skills/.venv/bin/python -m pytest -k remote_token -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/scripts/remote_token.py tests/overseer/test_remote_token.py
git commit -m "feat(overseer): scripts/remote_token.py — shared token-file location + 0600 IO"
```

---

### Task 2: Wire persistence (host) + file fallback (container) + gitignore

**Files:**
- Modify: `plugins/overseer/dashboard/serve_board_api.py`
- Modify: `plugins/overseer/scripts/cli.py`
- Modify: `.gitignore`
- Test: `plugins/overseer/dashboard/backend/tests/test_serve_board_api.py` (update existing + add), `tests/overseer/test_remote_dispatch.py` (add)

**Interfaces:**
- Consumes: `scripts.remote_token.read_remote_token` / `write_remote_token` (Task 1).
- Changes: `serve_board_api.resolve_remote_token(host, root)` (now takes `root`); `cli._run_remote(url, raw_argv, root)` (now takes `root`).

- [ ] **Step 1: Write the failing tests**

Update `plugins/overseer/dashboard/backend/tests/test_serve_board_api.py` — the three existing `resolve_remote_token` tests now pass a `root`, plus two new cases:

```python
def test_resolve_remote_token_env_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("OVERSEER_REMOTE_TOKEN", "fixed")
    assert serve_board_api.resolve_remote_token("0.0.0.0", tmp_path) == "fixed"
    assert serve_board_api.resolve_remote_token("127.0.0.1", tmp_path) == "fixed"
    assert not (tmp_path / ".overseer" / "remote-token").exists()  # env path writes nothing


def test_resolve_remote_token_none_on_loopback(monkeypatch, tmp_path):
    monkeypatch.delenv("OVERSEER_REMOTE_TOKEN", raising=False)
    assert serve_board_api.resolve_remote_token("127.0.0.1", tmp_path) is None
    assert not (tmp_path / ".overseer" / "remote-token").exists()


def test_resolve_remote_token_generates_and_persists_on_non_loopback(monkeypatch, tmp_path):
    monkeypatch.delenv("OVERSEER_REMOTE_TOKEN", raising=False)
    tok = serve_board_api.resolve_remote_token("0.0.0.0", tmp_path)
    assert tok and len(tok) >= 20
    from scripts.remote_token import read_remote_token
    assert read_remote_token(tmp_path) == tok  # persisted for the container to read


def test_resolve_remote_token_reuses_existing_file(monkeypatch, tmp_path):
    monkeypatch.delenv("OVERSEER_REMOTE_TOKEN", raising=False)
    from scripts.remote_token import write_remote_token
    write_remote_token(tmp_path, "persisted-tok")
    assert serve_board_api.resolve_remote_token("0.0.0.0", tmp_path) == "persisted-tok"  # stable across restarts
```

Add to `tests/overseer/test_remote_dispatch.py`:

```python
def test_remote_reads_token_from_file_when_env_unset(monkeypatch, tmp_path, capsys):
    from scripts.remote_token import write_remote_token
    from scripts import remote
    write_remote_token(tmp_path, "file-tok")
    monkeypatch.delenv("OVERSEER_REMOTE_TOKEN", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    seen = {}
    monkeypatch.setattr(remote, "exec_remote",
                        lambda url, token, argv, stdin, **k: seen.update(token=token)
                        or remote.RemoteResult("", "", 0))
    assert main(["--root", str(tmp_path), "--remote", "http://h", "board"]) == 0
    assert seen["token"] == "file-tok"


def test_remote_env_token_wins_over_file(monkeypatch, tmp_path):
    from scripts.remote_token import write_remote_token
    from scripts import remote
    write_remote_token(tmp_path, "file-tok")
    monkeypatch.setenv("OVERSEER_REMOTE_TOKEN", "env-tok")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    seen = {}
    monkeypatch.setattr(remote, "exec_remote",
                        lambda url, token, argv, stdin, **k: seen.update(token=token)
                        or remote.RemoteResult("", "", 0))
    assert main(["--root", str(tmp_path), "--remote", "http://h", "board"]) == 0
    assert seen["token"] == "env-tok"
```

- [ ] **Step 2: Run tests to verify they fail**

Run both:
`cd plugins/overseer/dashboard/backend && /Users/philip.pryde/repos/pip-skills/.venv/bin/python -m pytest tests/test_serve_board_api.py -v`
`cd plugins/overseer && /Users/philip.pryde/repos/pip-skills/.venv/bin/python -m pytest -k remote_dispatch -v`
Expected: FAIL — `resolve_remote_token` takes 1 arg / no file fallback / no `--root` threading yet.

- [ ] **Step 3: Implement**

In `serve_board_api.py`, replace `resolve_remote_token` and pass `root` in `main()`:

```python
def resolve_remote_token(host: str, root: Path) -> str | None:
    """The token in effect for this bind: env wins; loopback stays tokenless;
    else reuse the persisted token file or generate one and persist it (0600) so
    a mounted dev container can read it without a manual copy."""
    env = os.environ.get(REMOTE_TOKEN_ENV)
    if env:
        return env
    if host in LOOPBACK_HOSTS:
        return None
    from scripts.remote_token import read_remote_token, write_remote_token
    existing = read_remote_token(root)
    if existing:
        return existing
    token = secrets.token_urlsafe(24)
    write_remote_token(root, token)
    return token
```

In `main()`: `token = resolve_remote_token(args.host, root)` and, when a token is in effect, also print its file location:

```python
    token = resolve_remote_token(args.host, root)
    app = create_service_app(root, host=args.host, token=token)
    if token:
        from scripts.remote_token import remote_token_path
        print(f"board API token: {token}")
        print(f"token file (auto-read by a container mounting this repo): {remote_token_path(root)}")
```

In `cli.py`, thread `root` into `_run_remote` and add the file fallback:

```python
def _run_remote(url: str, raw_argv: list[str], root: Path) -> int:
    """Forward the whole command to the host board API and relay the result."""
    from scripts import remote  # lazy: httpx only needed on the remote path
    from scripts.remote_token import read_remote_token
    token = os.environ.get("OVERSEER_REMOTE_TOKEN") or read_remote_token(root)
    forward = _forwardable_argv(raw_argv)
    stdin = None if sys.stdin.isatty() else sys.stdin.read()
    try:
        res = remote.exec_remote(url, token, forward, stdin)
    except remote.RemoteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if res.stdout:
        sys.stdout.write(res.stdout)
    if res.stderr:
        sys.stderr.write(res.stderr)
    return res.returncode
```

And in `main()`, pass the root to it:

```python
    if getattr(args, "remote", None):
        return _run_remote(args.remote, raw, args.root)
```

In `.gitignore`, add:

```
.overseer/remote-token
```

- [ ] **Step 4: Run tests to verify they pass**

Run both commands from Step 2 → PASS.

- [ ] **Step 5: Regression guards**

Run: `cd plugins/overseer/dashboard/backend && /Users/philip.pryde/repos/pip-skills/.venv/bin/python -m pytest -v` (backend suite green)
Run: `cd plugins/overseer && /Users/philip.pryde/repos/pip-skills/.venv/bin/python -m pytest` (full CLI suite green — the `_run_remote` signature change must not disturb local dispatch)
Run: `cd plugins/overseer && /Users/philip.pryde/repos/pip-skills/.venv/bin/python -m ruff check plugins/overseer/scripts/remote_token.py plugins/overseer/scripts/cli.py plugins/overseer/dashboard/serve_board_api.py` (or the repo's ruff invocation) — clean on changed files.

- [ ] **Step 6: Commit**

```bash
git add plugins/overseer/dashboard/serve_board_api.py plugins/overseer/scripts/cli.py .gitignore \
        plugins/overseer/dashboard/backend/tests/test_serve_board_api.py tests/overseer/test_remote_dispatch.py
git commit -m "feat(overseer): auto-share remote token via mounted repo (env -> file -> default)"
```

---

## Self-Review
- **Spec coverage:** §3 resolution order → Task 2 (host `resolve_remote_token`, container `_run_remote`); §3 shared helper → Task 1; §4 components → Tasks 1-2 + `.gitignore`; §5 security (0600, gitignore, loopback tokenless) → Task 1 write mode + Task 2 loopback branch + gitignore; §6 testing → tests in both tasks.
- **Placeholder scan:** none — all steps carry concrete code/commands.
- **Type consistency:** `remote_token_path`/`read_remote_token`/`write_remote_token` signatures match across Task 1 (definition) and Task 2 (use in `serve_board_api` and `cli`). `resolve_remote_token(host, root)` and `_run_remote(url, raw_argv, root)` updated consistently at their call sites in the same task.
