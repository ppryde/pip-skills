"""Thin subprocess client for the overseer and vigil CLIs.

The dashboard backend is a CLIENT of these CLIs — it never imports overseer
or vigil internals and never touches `.workflow/` directly. Every read and
write goes through `subprocess.run([sys.executable, cli_py, "--root", root,
<verb>, <args...>])`, preserving overseer's single-writer invariant.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

# backend/app/cli_client.py -> parents: [0]=app [1]=backend [2]=dashboard [3]=overseer
_OVERSEER_ROOT = Path(__file__).resolve().parents[3]
_OVERSEER_CLI = _OVERSEER_ROOT / "scripts" / "cli.py"
# The one overseer module this client imports rather than shells: the list of
# watched Claude config dirs (`config.claude_dirs`), a pure read of env + one
# JSON file, needed to fan the census read out per account. Same sys.path
# arrangement main.py uses for `scripts.store`.
if str(_OVERSEER_ROOT) not in sys.path:
    sys.path.insert(0, str(_OVERSEER_ROOT))
from scripts import config as overseer_config  # noqa: E402  (must follow sys.path setup above)
# parents[4]=plugins
_VIGIL_CLI = Path(__file__).resolve().parents[4] / "vigil" / "scripts" / "cli.py"
_CENSUS_CLI = Path(__file__).resolve().parents[4] / "census" / "scripts" / "cli.py"
_CHRONICLE_CLI = Path(__file__).resolve().parents[4] / "chronicle" / "scripts" / "cli.py"

_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]*\Z")


class CliError(Exception):
    """Raised when a CLI invocation fails, times out, or gets a bad id."""

    def __init__(self, returncode: int, stderr: str) -> None:
        super().__init__(stderr)
        self.returncode = returncode
        self.stderr = stderr


def check_id(card_id: str) -> None:
    """Reject ids containing glob/path metacharacters before they reach the store's glob."""
    if not _ID_RE.match(card_id):
        raise CliError(2, "invalid card id")


def _run(cli_py: Path, cli_name: str, root: Path, args: tuple[str, ...],
          json_out: bool, timeout: int) -> Any:
    try:
        result = subprocess.run(
            [sys.executable, str(cli_py), "--root", str(root), *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise CliError(504, f"{cli_name} {' '.join(args)} timed out") from None
    except OSError as exc:
        raise CliError(500, f"cannot run {cli_py.name}: {exc}") from exc
    if result.returncode != 0:
        raise CliError(result.returncode, result.stderr.strip())
    if json_out:
        return json.loads(result.stdout)
    return result.stdout


def run_overseer(root: Path, *args: str, json_out: bool = False, timeout: int = 15) -> Any:
    return _run(_OVERSEER_CLI, "overseer", root, args, json_out, timeout)


def run_vigil(root: Path, *args: str, json_out: bool = False, timeout: int = 15) -> Any:
    return _run(_VIGIL_CLI, "vigil", root, args, json_out, timeout)


def _census_env(config_dir: Path | None) -> dict[str, str]:
    """The environment for one census read: the ambient one, or with
    `CLAUDE_CONFIG_DIR` pointed at a specific account's store (and any
    `CENSUS_STORE` pin dropped, since that names ONE store)."""
    env = dict(os.environ)
    if config_dir is not None:
        env["CLAUDE_CONFIG_DIR"] = str(config_dir)
        env.pop("CENSUS_STORE", None)
    return env


def _census_read(args: list[str], config_dir: Path | None, timeout: int) -> dict[str, Any] | None:
    """One `census read …` subprocess; None on any failure, like every census
    read here."""
    try:
        result = subprocess.run(
            [sys.executable, str(_CENSUS_CLI), "read", *args],
            capture_output=True, text=True, timeout=timeout, env=_census_env(config_dir),
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) and data else None


def _watched_dirs() -> list[Path]:
    """The Claude config dirs to read census from — one when `CENSUS_STORE`
    pins a single store (tests), else every watched account, primary first.
    Never raises: census is a soft dependency all the way down."""
    if os.environ.get("CENSUS_STORE"):
        return []
    try:
        return overseer_config.claude_dirs()
    except Exception:  # noqa: BLE001 — a broken machine config must not 500 the board
        return []


def run_census(root: Path, timeout: int = 10) -> dict[str, Any] | None:
    """Read census's entry for ``root``'s worktree — from whichever watched
    account's store has one, primary first; None if none does or census is
    unavailable. A repo worked only from a second account still gets its
    context/rate-limit readout this way.

    census is a SOFT dependency: it does not take the ``--root`` convention (it is
    ``census read --worktree <cwd>``), and a missing plugin, empty store, timeout,
    or any failure yields None rather than raising — so the board read never
    depends on census being installed.
    """
    dirs = _watched_dirs()
    if not dirs:
        return _census_read(["--worktree", str(root)], None, timeout)
    for config_dir in dirs:
        data = _census_read(["--worktree", str(root)], config_dir, timeout)
        if data:
            return data
    return None


def run_census_all(timeout: int = 10) -> dict[str, Any] | None:
    """Read all sessions from census across all worktrees AND every watched
    Claude config dir (multi-account: each account's sessions land in its own
    census store); None if census is unavailable everywhere.

    The stores are merged into one `{"sessions": {...}, "limits": ...}`: each
    session entry gains `config_dir` (the dir whose store it came from) so a
    second account's session on the same repo is one more row in the same
    list, not a separate world. `limits` are the PRIMARY account's — rate
    windows are per account, and the bar has one pair of rest pills. With
    `CENSUS_STORE` pinned (tests) there is one store by definition, so it is
    read once, untagged.

    census is a SOFT dependency: like run_census, a missing plugin, empty store,
    timeout, or any failure yields None rather than raising.
    """
    dirs = _watched_dirs()
    if not dirs:
        return _census_read([], None, timeout)
    # One subprocess per account, run together: a slow or hung store in one
    # account costs its own timeout, not one per account in series.
    with ThreadPoolExecutor(max_workers=len(dirs)) as pool:
        reads = list(pool.map(lambda d: _census_read([], d, timeout), dirs))
    merged: dict[str, Any] | None = None
    for index, (config_dir, data) in enumerate(zip(dirs, reads, strict=True)):
        if index == 0:
            # The PRIMARY's store is the envelope (its `limits`, `version`…)
            # even when it has no sessions yet; other stores only ever
            # contribute sessions.
            merged = {**(data or {}), "sessions": {}}
        if not data:
            continue
        assert merged is not None
        for sid, entry in (data.get("sessions") or {}).items():
            if sid in merged["sessions"]:
                continue  # the same session id in two stores: first (primary) wins
            merged["sessions"][sid] = {**entry, "config_dir": str(config_dir)}
    if merged is None or (not merged["sessions"] and not merged.get("limits")):
        return None
    return merged


def chronicle_installed() -> bool:
    """Whether the chronicle plugin's CLI is present beside this checkout.

    The Chronicle page is OPTIONAL: the dashboard grows it only when the
    plugin exists (same sibling-plugin resolution as census/vigil above).
    """
    return _CHRONICLE_CLI.is_file()


def run_chronicle(*args: str, timeout: int = 20) -> Any:
    """Run a chronicle READ verb and return its parsed JSON; None if unavailable.

    chronicle is a SOFT dependency like census: a missing plugin, a timeout,
    a non-zero exit, or bad JSON yields None rather than raising, so the
    board never depends on it and the Chronicle page degrades to "not
    installed" / "no data yet". Report verbs and the explicit Sync action go
    through here — the dashboard never triggers an ingest on its own.
    """
    if not chronicle_installed():
        return None
    try:
        result = subprocess.run(
            [sys.executable, str(_CHRONICLE_CLI), *args],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
