"""Install / uninstall census: the launcher shim and the status-line block.

Every function plans first and changes files only with ``apply=True``. Reports
name files and census's own lines; they never echo the user's status-line text.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import tempfile
from pathlib import Path
from typing import Any

from scripts import render
from scripts import statusline as sl

SHIM_MARKER = "# census launcher (managed by `census install`; do not edit)"


def _sh_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


_VERSION_DIR = re.compile(r"^[0-9][0-9.]*$")

# Run by the launcher when the install-time CLI is gone: print the highest-version
# live `<root>/<ver>/scripts/cli.py`. Same rule as `_version_key` in overseer's
# cli_client: numeric compare, non-numeric parts sort as 0. No single quotes in it.
_PICK_NEWEST = (
    "import os,sys\n"
    "r=sys.argv[1]\n"
    "k=lambda n:tuple(int(p) if p.isdigit() else 0 for p in n.split(\".\"))\n"
    "c=[(k(v),os.path.join(r,v,\"scripts\",\"cli.py\")) for v in os.listdir(r)\n"
    " if not os.path.exists(os.path.join(r,v,\".orphaned_at\"))\n"
    " and os.path.isfile(os.path.join(r,v,\"scripts\",\"cli.py\"))]\n"
    "print(max(c)[1] if c else \"\")\n"
)


def versioned_root(cli: Path) -> str:
    """The directory holding versioned copies when ``cli`` sits in one
    (``<root>/<version>/scripts/cli.py``), else ''."""
    parents = cli.parents
    if len(parents) > 2 and _VERSION_DIR.match(parents[1].name):
        return str(parents[2])
    return ""


def shim_text(cli: Path) -> str:
    """A POSIX sh launcher for ``cli``. Finds python3, else python (Windows Git
    Bash), at run time. In a marketplace layout the version directory it was
    installed from is removed on upgrade, so when ``$CLI`` is gone it falls back
    to the newest live version under ``$ROOT``. Exits 0 silently when nothing is
    found so a status line's ``|| true`` guard never prints anything."""
    return (
        "#!/usr/bin/env sh\n"
        f"{SHIM_MARKER}\n"
        f"CLI={_sh_quote(str(cli))}\n"
        f"ROOT={_sh_quote(versioned_root(cli))}\n"
        "for py in python3 python; do\n"
        '  if command -v "$py" >/dev/null 2>&1; then\n'
        '    if [ ! -f "$CLI" ] && [ -n "$ROOT" ]; then\n'
        f"      CLI=$(\"$py\" -c {_sh_quote(_PICK_NEWEST)} \"$ROOT\" 2>/dev/null) || CLI=\n"
        "    fi\n"
        '    [ -f "$CLI" ] || exit 0\n'
        '    exec "$py" "$CLI" "$@"\n'
        "  fi\n"
        "done\n"
        "exit 0\n"
    )


def _read_text(path: Path) -> str:
    """Read without newline translation; undecodable bytes survive a round trip."""
    return path.read_bytes().decode("utf-8", "surrogateescape")


def _write_text(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8", "surrogateescape"))


def _is_old_launcher(text: str) -> bool:
    return any(line.startswith("# census launcher") for line in text.splitlines()[:3])


def _shim_owner(shim: Path) -> tuple[str, str]:
    """('none' | 'ours' | 'foreign', text). 'ours' is any census launcher, old or new."""
    try:
        text = _read_text(shim)
    except FileNotFoundError:
        return "none", ""
    except OSError:
        return "foreign", ""
    ours = SHIM_MARKER in text or _is_old_launcher(text)
    return ("ours" if ours else "foreign"), text


def _executable(shim: Path) -> bool:
    return os.name == "nt" or os.access(shim, os.X_OK)


def _install_shim(shim: Path, cli: Path, apply: bool) -> tuple[int, list[str]]:
    verb = "" if apply else "would "
    owner, current = _shim_owner(shim)
    wanted = shim_text(cli)
    if owner == "foreign":
        return 1, [f"refused: {shim} exists and is not a census launcher — move it, or pass --shim"]
    if owner == "ours" and current == wanted:
        if _executable(shim):
            return 0, [f"launcher {shim}: up to date"]
        if apply:
            shim.chmod(0o755)
        return 0, [f"launcher {shim}: {verb}restore the executable bit"]
    if apply:
        shim.parent.mkdir(parents=True, exist_ok=True)
        _write_text(shim, wanted)
        shim.chmod(0o755)
    return 0, [f"launcher {shim}: {verb}{'replace' if owner == 'ours' else 'create'} → {cli}"]


def install(shim: Path, statusline: Path, cli: Path, apply: bool) -> tuple[int, list[str]]:
    """The launcher plus the ingest block in a bash status-line script. The block
    calls the launcher at ``shim``, so ``--shim`` and the script agree."""
    verb = "" if apply else "would "
    ingest = sl.ingest_command(str(shim))
    code, lines = _install_shim(shim, cli, apply)
    if code:
        return code, lines
    if not statusline.exists():
        lines.append(f"no status-line script at {statusline} — add this line after `input=$(cat)`:")
        lines.append(f"  {ingest}")
    else:
        text = _read_text(statusline)
        if sl.is_installed(text):
            lines.append(f"status line {statusline}: census block present")
        else:
            lines.append(f"status line {statusline}: {verb}add the census block after `{sl.DEFAULT_ANCHOR}`")
            if apply:
                _write_text(statusline, sl.add_block(text, ingest=ingest))
    if not apply:
        lines.append("dry run — nothing changed; re-run with --yes")
    return 0, lines


# --- `census install --statusline`: census draws the status line itself --------

PREVIOUS_FILE = "statusline.previous.json"  # the replaced statusLine value, verbatim
STATE_FILE = "statusline.state.json"  # what else census changed, so uninstall can undo exactly that
LAUNCHER_FILE = "launcher.py"  # Windows only: a stable entry point that survives plugin upgrades
SEGMENTS_KEY = "CENSUS_STATUSLINE_SEGMENTS"
REFRESH_INTERVAL = 60


def launcher_py_text(cli: Path) -> str:
    """The Windows twin of the sh launcher: a python file at a path that does not
    move on upgrade. Runs ``cli``, or the newest live version under its marketplace
    root when that directory is gone; exits 0 silently when nothing is found."""
    return (
        "# census launcher (managed by `census install`; do not edit)\n"
        "import os, subprocess, sys\n"
        f"CLI = {str(cli)!r}\n"
        f"ROOT = {versioned_root(cli)!r}\n"
        "def newest(root):\n"
        "    best = None\n"
        "    for v in os.listdir(root):\n"
        "        path = os.path.join(root, v, 'scripts', 'cli.py')\n"
        "        if os.path.exists(os.path.join(root, v, '.orphaned_at')) or not os.path.isfile(path):\n"
        "            continue\n"
        "        key = tuple(int(p) if p.isdigit() else 0 for p in v.split('.'))\n"
        "        if best is None or key > best[0]:\n"
        "            best = (key, path)\n"
        "    return best[1] if best else ''\n"
        "cli = CLI\n"
        "if not os.path.isfile(cli) and ROOT:\n"
        "    try:\n"
        "        cli = newest(ROOT)\n"
        "    except OSError:\n"
        "        cli = ''\n"
        "if cli and os.path.isfile(cli):\n"
        "    sys.exit(subprocess.call([sys.executable, cli] + sys.argv[1:]))\n"
    )


def statusline_command(shim: Path, census: Path, windows: bool | None = None) -> str:
    """The ``statusLine.command``: the sh launcher on POSIX; on Windows ``python`` on
    the stable ``launcher.py`` in the census dir (never the versioned cli.py)."""
    if os.name == "nt" if windows is None else windows:
        return f'python "{census / LAUNCHER_FILE}" statusline'
    return f"{shlex.quote(str(shim))} statusline"


def _tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return []


def _is_ours(setting: Any, shim: Path, census: Path) -> bool:
    """Exactly the command census generates for this launcher (either platform's
    form), compared token by token — a path that merely starts with ours is not ours."""
    command = setting.get("command") if isinstance(setting, dict) else None
    if not isinstance(command, str):
        return False
    got = _tokens(command)
    return bool(got) and any(got == _tokens(statusline_command(shim, census, windows=w)) for w in (False, True))


def _load_settings(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"refused: no settings file at {path} — nothing changed"
    except (OSError, ValueError):
        return None, f"refused: {path} is not readable JSON — nothing changed"
    if not isinstance(data, dict):
        return None, f"refused: {path} is not a JSON object — nothing changed"
    return data, ""


def _atomic_bytes(path: Path, payload: bytes) -> None:
    """Write bytes by atomic replace, through a symlink and keeping the file's mode."""
    target = Path(os.path.realpath(path))
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        try:
            shutil.copymode(target, tmp)
        except OSError:
            pass
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _atomic_json(path: Path, data: Any) -> None:
    _atomic_bytes(path, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def _read_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_state(census: Path) -> dict[str, Any]:
    state = _read_json_file(census / STATE_FILE)
    return state if isinstance(state, dict) else {}


def validate_segments(spec: str) -> str:
    """The unknown names in ``spec`` ('' when all are known)."""
    names = [n.strip() for line in spec.split("/") for n in line.split(",")]
    return ", ".join(n for n in names if n and n not in render.SEGMENTS)


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _preflight(settings: Path, census: Path, shim: Path) -> str:
    """'' when every folder census will write to is writable, else why not."""
    for folder in (census, Path(os.path.realpath(settings)).parent, shim.parent):
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return f"refused: cannot create {folder} ({exc.strerror or exc}) — nothing changed"
        if not os.access(folder, os.W_OK):
            return f"refused: {folder} is not writable — nothing changed"
    return ""


def install_statusline(
    shim: Path,
    cli: Path,
    settings: Path,
    census: Path,
    replace: bool,
    segments: str | None,
    apply: bool,
    windows: bool | None = None,
) -> tuple[int, list[str]]:
    """Install the shim and point ``statusLine`` in ``settings`` at ``census statusline``.

    Plans everything before changing anything: an unreadable settings file, a
    foreign launcher, a foreign ``statusLine`` without ``replace``, an unknown
    segment name or an unwritable folder refuses with no change at all. Once
    writing, a failure rolls back what was already written."""
    verb = "" if apply else "would "
    data, problem = _load_settings(settings)
    if data is None:
        return 1, [problem]
    if segments is not None and (bad := validate_segments(segments)):
        return 1, [f"refused: unknown segment(s) {bad} — known: {', '.join(render.SEGMENTS)}"]
    if segments is not None and "env" in data and not isinstance(data["env"], dict):
        return 1, [f"refused: env in {settings} is not an object — left alone, nothing changed"]
    owner, _ = _shim_owner(shim)
    if owner == "foreign":
        return 1, [f"refused: {shim} exists and is not a census launcher — move it, or pass --shim"]
    present = "statusLine" in data
    current = data.get("statusLine")
    ours = _is_ours(current, shim, census)
    foreign = present and current is not None and not ours
    if foreign and not replace:
        return 1, [f"refused: {settings} already has a statusLine — re-run with --replace to back it up and swap"]
    if apply and (problem := _preflight(settings, census, shim)):
        return 1, [problem]

    _, lines = _install_shim(shim, cli, False)
    wanted = {
        "type": "command",
        "command": statusline_command(shim, census, windows),
        "refreshInterval": REFRESH_INTERVAL,
    }
    state = _read_state(census)
    original = settings.read_bytes()
    backup = None
    if current == wanted:
        lines.append(f"statusLine in {settings}: up to date")
    else:
        if not foreign:
            lines.append(f"statusLine in {settings}: {verb}{'update' if ours else 'set'} → {wanted['command']}")
            if present and current is None:
                state["statusline_was_null"] = True
        else:
            lines.append(f"statusLine in {settings}: {verb}replace (old value saved to {census / PREVIOUS_FILE})")
            backup = current
        data["statusLine"] = wanted
    changed = current != wanted
    if segments is not None:
        env = data.get("env")
        env_dict = env if isinstance(env, dict) else {}
        if env_dict.get(SEGMENTS_KEY) != segments:
            lines.append(f"env.{SEGMENTS_KEY} in {settings}: {verb}set to {segments!r}")
            if not state.get("segments_written"):
                state["segments_written"] = True
                state["segments_previous"] = env_dict.get(SEGMENTS_KEY)
                state["env_created"] = not isinstance(env, dict)
            env_dict[SEGMENTS_KEY] = segments
            data["env"] = env_dict
            changed = True
    if not apply:
        lines.append("dry run — nothing changed; re-run with --yes")
        return 0, lines

    undo: list[Any] = []
    try:
        for name in (PREVIOUS_FILE, STATE_FILE, LAUNCHER_FILE):
            before = (census / name).read_bytes() if (census / name).exists() else None
            undo.append((census / name, before))
        if backup is not None:
            _atomic_json(census / PREVIOUS_FILE, backup)
        if changed:
            _atomic_bytes(settings, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
            undo.append((settings, original))
            if state:
                _atomic_json(census / STATE_FILE, state)
        if os.name == "nt" if windows is None else windows:
            _write_text(census / LAUNCHER_FILE, launcher_py_text(cli))
        _install_shim(shim, cli, True)
    except Exception as exc:  # noqa: BLE001 - roll back, then say so
        for path, before in reversed(undo):
            try:
                if before is None:
                    _unlink_quiet(path)
                else:
                    _atomic_bytes(path, before)
            except OSError:
                pass
        return 1, [f"failed: {exc} — rolled back; nothing changed"]
    return 0, lines


def restore_statusline(
    shim: Path, settings: Path, census: Path, apply: bool
) -> tuple[bool, list[str], bool]:
    """Undo ``install_statusline``: put the backed-up ``statusLine`` back, or remove
    the one census added; remove ``env.CENSUS_STATUSLINE_SEGMENTS`` if census wrote it.
    Only when the current ``statusLine`` is still census's own — otherwise report and
    leave it. Runs before any purge, which would delete the backup.

    Returns ``(ok, lines, keep_backup)``: ``ok`` is False when a backup or the settings
    could not be read (the caller must not go on to delete anything); ``keep_backup``
    is True when the saved value was not restored and must survive a purge."""
    verb = "" if apply else "would "
    previous_path, state_path = census / PREVIOUS_FILE, census / STATE_FILE
    has_previous = previous_path.exists()
    state = _read_state(census)
    if not has_previous and not state and not settings.exists():
        return True, [], False
    data, problem = _load_settings(settings)
    if data is None:
        if has_previous or state:
            return False, [problem.replace("nothing changed", "left alone")], True
        return True, [], False
    current = data.get("statusLine")
    ours = _is_ours(current, shim, census)
    old = _read_json_file(previous_path) if has_previous else None
    if ours and has_previous and old is None:  # never write null over a statusLine, never lose the file
        return False, [f"statusLine in {settings}: backup {previous_path} unreadable — left alone"], True
    lines: list[str] = []
    changed = False
    if ours:
        if has_previous:
            lines.append(f"statusLine in {settings}: {verb}restore the previous value")
            data["statusLine"] = old
        elif state.get("statusline_was_null"):
            lines.append(f"statusLine in {settings}: {verb}restore the null it replaced")
            data["statusLine"] = None
        else:
            lines.append(f"statusLine in {settings}: {verb}remove (census added it)")
            data.pop("statusLine", None)
        changed = True
    elif has_previous:
        lines.append(
            f"statusLine in {settings}: no longer census's — left alone (old value kept in {previous_path})"
        )
    if state.get("segments_written"):
        env = data.get("env")
        if isinstance(env, dict) and SEGMENTS_KEY in env:
            had = state.get("segments_previous") is not None
            lines.append(f"env.{SEGMENTS_KEY} in {settings}: {verb}{'restore' if had else 'remove'}")
            if had:
                env[SEGMENTS_KEY] = state["segments_previous"]
            else:
                del env[SEGMENTS_KEY]
                if not env and state.get("env_created"):
                    del data["env"]
            changed = True
    if apply:
        if changed:
            _atomic_json(settings, data)
        if ours or not has_previous:
            for leftover in (previous_path, state_path, census / LAUNCHER_FILE):
                _unlink_quiet(leftover)
    return True, lines, has_previous and not ours


def uninstall(
    shim: Path,
    statusline: Path,
    purge_dir: Path | None,
    apply: bool,
    *,
    settings: Path | None = None,
    census: Path | None = None,
) -> tuple[int, list[str]]:
    lines: list[str] = []
    verb = "" if apply else "would "
    keep_backup = False
    if settings is not None and census is not None:
        # first: a purge would delete the backup the restore needs
        ok, restored, keep_backup = restore_statusline(shim, settings, census, apply)
        lines.extend(restored)
        if not ok:
            lines.append("stopped: the status line could not be restored, so nothing else was removed")
            return 1, lines
    owner, _ = _shim_owner(shim)
    if owner == "ours":
        lines.append(f"launcher {shim}: {verb}remove")
        if apply:
            shim.unlink()
    elif owner == "foreign":
        lines.append(f"launcher {shim}: not a census launcher — left alone")
    text = _read_text(statusline) if statusline.exists() else ""
    if sl.is_installed(text):
        stripped = sl.remove_block(text)
        if stripped == text:
            lines.append(f"status line {statusline}: census block is incomplete (no end marker) — left alone")
        else:
            lines.append(f"status line {statusline}: {verb}remove the census block")
            if apply:
                _write_text(statusline, stripped)
    if purge_dir is not None and purge_dir.exists():
        lines.extend(_purge(purge_dir, apply, keep_backup))
    if not lines:
        lines.append("nothing to remove")
    if not apply:
        lines.append("dry run — nothing changed; re-run with --yes")
    return 0, lines


_OWNED_FILES = (
    "cli.path",
    PREVIOUS_FILE,
    STATE_FILE,
    LAUNCHER_FILE,
    "limits.json",
    "status.json",
    "status.json.lock",
    "status.json.v1-migrated",
    ".migrate.lock",
)
# the temp-file prefixes census itself uses in its folder (the sessions/, limits/ and
# gitcache/ subfolders are removed whole); any other hidden *.tmp belongs to someone else
_TMP_PREFIXES = (".cli.path.", ".statusline.", ".status.", ".limits.")


def _owned_entries(directory: Path) -> list[Path]:
    """Census's own entries inside ``directory`` — never anything else."""
    found = [directory / name for name in _OWNED_FILES]
    found.append(directory / "sessions")
    found.append(directory / "limits")
    found.append(directory / "gitcache")
    try:
        found.extend(
            p
            for p in directory.iterdir()
            if p.name.endswith(".tmp") and p.name.startswith(_TMP_PREFIXES)
        )
    except OSError:
        pass
    return [p for p in found if p.is_dir() or p.is_file() or p.is_symlink()]


def _foreign_session(entry: Any, mine: str) -> bool:
    """A session record that names a different account. One with no account (or that
    is not a record at all) is not shown to be someone else's, so it is ours to purge."""
    account = entry.get("account") if isinstance(entry, dict) else None
    return isinstance(account, str) and account != mine


def _other_accounts(directory: Path, mine: str) -> bool:
    """Does any session or limits file in ``directory`` belong to another account?"""
    try:
        for path in (directory / "sessions").iterdir():
            if path.name.startswith(".") or not path.name.endswith(".json"):
                continue
            entry = _read_json_file(path)
            if _foreign_session(entry, mine):
                return True
        for path in (directory / "limits").iterdir():
            if not path.name.startswith(".") and path.name.endswith(".json") and path.stem != mine:
                return True
    except OSError:
        pass
    return False


def _scoped_entries(directory: Path, mine: str, keep_backup: bool) -> list[Path]:
    """Only this account's records, for a store several accounts share (``CENSUS_STORE``)."""
    found: list[Path] = [directory / "limits" / f"{mine}.json"]
    try:
        for path in (directory / "sessions").iterdir():
            if path.name.endswith(".json") and not path.name.startswith("."):
                entry = _read_json_file(path)
                if not _foreign_session(entry, mine):
                    found.append(path)
    except OSError:
        pass
    found.extend(directory / name for name in (PREVIOUS_FILE, STATE_FILE, LAUNCHER_FILE))
    if keep_backup:
        found = [p for p in found if p.name != PREVIOUS_FILE]
    return [p for p in found if p.is_file()]


def _purge(directory: Path, apply: bool, keep_backup: bool = False) -> list[str]:
    """Delete only what census owns in ``directory``; remove the directory itself
    only if that leaves it empty. ``CENSUS_STORE`` can point anywhere (even at
    ``$HOME/census.json``), so the directory is never removed wholesale.

    A folder shared by several accounts is purged account-scoped: only this
    account's limits file and the sessions it wrote go; everything else stays."""
    from scripts import store as st

    verb = "" if apply else "would "
    mine = st.account_info()["key"]
    scoped = _other_accounts(directory, mine)
    owned = _scoped_entries(directory, mine, keep_backup) if scoped else _owned_entries(directory)
    if keep_backup and not scoped:
        owned = [p for p in owned if p.name != PREVIOUS_FILE]
    lines = []
    if scoped:
        lines.append(f"data {directory}: shared with other accounts — purging only this account's records")
    for path in owned:
        lines.append(f"data {path}: {verb}delete")
        if apply:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
    remaining = {p.name for p in directory.iterdir()} - {p.name for p in owned}
    if remaining:
        lines.append(f"data {directory}: kept — it holds other files")
    else:
        lines.append(f"data {directory}: {verb}remove (empty)")
        if apply:
            directory.rmdir()
    return lines
