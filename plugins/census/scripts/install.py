"""Install / uninstall census: the launcher shim and the status-line block.

Every function plans first and changes files only with ``apply=True``. Reports
name files and census's own lines; they never echo the user's status-line text.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

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


def install(shim: Path, statusline: Path, cli: Path, apply: bool) -> tuple[int, list[str]]:
    lines: list[str] = []
    verb = "" if apply else "would "
    owner, current = _shim_owner(shim)
    wanted = shim_text(cli)
    if owner == "foreign":
        return 1, [f"refused: {shim} exists and is not a census launcher — move it, or pass --shim"]
    if owner == "ours" and current == wanted:
        lines.append(f"launcher {shim}: up to date")
    else:
        lines.append(f"launcher {shim}: {verb}{'replace' if owner == 'ours' else 'create'} → {cli}")
        if apply:
            shim.parent.mkdir(parents=True, exist_ok=True)
            _write_text(shim, wanted)
            shim.chmod(0o755)
    if not statusline.exists():
        lines.append(f"no status-line script at {statusline} — add this line after `input=$(cat)`:")
        lines.append(f"  {sl.INGEST}")
    else:
        text = _read_text(statusline)
        if sl.is_installed(text):
            lines.append(f"status line {statusline}: census block present")
        else:
            lines.append(f"status line {statusline}: {verb}add the census block after `{sl.DEFAULT_ANCHOR}`")
            if apply:
                _write_text(statusline, sl.add_block(text))
    if not apply:
        lines.append("dry run — nothing changed; re-run with --yes")
    return 0, lines


def uninstall(shim: Path, statusline: Path, purge_dir: Path | None, apply: bool) -> tuple[int, list[str]]:
    lines: list[str] = []
    verb = "" if apply else "would "
    owner, _ = _shim_owner(shim)
    if owner == "ours":
        lines.append(f"launcher {shim}: {verb}remove")
        if apply:
            shim.unlink()
    elif owner == "foreign":
        lines.append(f"launcher {shim}: not a census launcher — left alone")
    text = _read_text(statusline) if statusline.exists() else ""
    if sl.is_installed(text):
        lines.append(f"status line {statusline}: {verb}remove the census block")
        if apply:
            _write_text(statusline, sl.remove_block(text))
    if purge_dir is not None and purge_dir.exists():
        lines.extend(_purge(purge_dir, apply))
    if not lines:
        lines.append("nothing to remove")
    if not apply:
        lines.append("dry run — nothing changed; re-run with --yes")
    return 0, lines


_OWNED_FILES = (
    "cli.path",
    "limits.json",
    "status.json",
    "status.json.lock",
    "status.json.v1-migrated",
    ".migrate.lock",
)


def _owned_entries(directory: Path) -> list[Path]:
    """Census's own entries inside ``directory`` — never anything else."""
    found = [directory / name for name in _OWNED_FILES]
    found.append(directory / "sessions")
    found.append(directory / "limits")
    try:
        found.extend(p for p in directory.iterdir() if p.name.startswith(".") and p.name.endswith(".tmp"))
    except OSError:
        pass
    return [p for p in found if p.is_dir() or p.is_file() or p.is_symlink()]


def _purge(directory: Path, apply: bool) -> list[str]:
    """Delete only what census owns in ``directory``; remove the directory itself
    only if that leaves it empty. ``CENSUS_STORE`` can point anywhere (even at
    ``$HOME/census.json``), so the directory is never removed wholesale."""
    verb = "" if apply else "would "
    owned = _owned_entries(directory)
    lines = []
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
