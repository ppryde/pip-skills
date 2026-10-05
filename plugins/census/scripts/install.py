"""Install / uninstall census: the launcher shim and the status-line block.

Every function plans first and changes files only with ``apply=True``. Reports
name files and census's own lines; they never echo the user's status-line text.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from scripts import statusline as sl

SHIM_MARKER = "# census launcher (managed by `census install`; do not edit)"
_OLD_SHIM_HINT = "census launcher"


def _sh_quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def shim_text(cli: Path) -> str:
    """A POSIX sh launcher for ``cli``. Finds python3, else python (Windows Git
    Bash), at run time; exits 0 silently when the plugin or Python is gone so a
    status line's ``|| true`` guard never prints anything."""
    return (
        "#!/usr/bin/env sh\n"
        f"{SHIM_MARKER}\n"
        f"CLI={_sh_quote(str(cli))}\n"
        '[ -f "$CLI" ] || exit 0\n'
        "for py in python3 python; do\n"
        '  if command -v "$py" >/dev/null 2>&1; then exec "$py" "$CLI" "$@"; fi\n'
        "done\n"
        "exit 0\n"
    )


def _shim_owner(shim: Path) -> str:
    """'none', 'ours' (any census launcher, old or new) or 'foreign'."""
    try:
        text = shim.read_text()
    except FileNotFoundError:
        return "none"
    except OSError:
        return "foreign"
    return "ours" if (SHIM_MARKER in text or _OLD_SHIM_HINT in text) else "foreign"


def install(shim: Path, statusline: Path, cli: Path, apply: bool) -> tuple[int, list[str]]:
    lines: list[str] = []
    verb = "" if apply else "would "
    owner = _shim_owner(shim)
    wanted = shim_text(cli)
    if owner == "foreign":
        return 1, [f"refused: {shim} exists and is not a census launcher — move it, or pass --shim"]
    if owner == "ours" and shim.read_text() == wanted:
        lines.append(f"launcher {shim}: up to date")
    else:
        lines.append(f"launcher {shim}: {verb}{'replace' if owner == 'ours' else 'create'} → {cli}")
        if apply:
            shim.parent.mkdir(parents=True, exist_ok=True)
            shim.write_text(wanted)
            shim.chmod(0o755)
    if not statusline.exists():
        lines.append(f"no status-line script at {statusline} — add this line after `input=$(cat)`:")
        lines.append(f"  {sl.INGEST}")
        return 0, lines
    text = statusline.read_text()
    if sl.is_installed(text):
        lines.append(f"status line {statusline}: census block present")
    else:
        lines.append(f"status line {statusline}: {verb}add the census block after `{sl.DEFAULT_ANCHOR}`")
        if apply:
            statusline.write_text(sl.add_block(text))
    if not apply:
        lines.append("dry run — nothing changed; re-run with --yes")
    return 0, lines


def uninstall(shim: Path, statusline: Path, purge_dir: Path | None, apply: bool) -> tuple[int, list[str]]:
    lines: list[str] = []
    verb = "" if apply else "would "
    owner = _shim_owner(shim)
    if owner == "ours":
        lines.append(f"launcher {shim}: {verb}remove")
        if apply:
            shim.unlink()
    elif owner == "foreign":
        lines.append(f"launcher {shim}: not a census launcher — left alone")
    if statusline.exists() and sl.is_installed(statusline.read_text()):
        lines.append(f"status line {statusline}: {verb}remove the census block")
        if apply:
            statusline.write_text(sl.remove_block(statusline.read_text()))
    if purge_dir is not None and purge_dir.exists():
        lines.append(f"data {purge_dir}: {verb}delete")
        if apply:
            shutil.rmtree(purge_dir)
    if not lines:
        lines.append("nothing to remove")
    if not apply:
        lines.append("dry run — nothing changed; re-run with --yes")
    return 0, lines
