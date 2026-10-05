"""Install / uninstall census: the launcher shim and the status-line block.

Every function plans first and changes files only with ``apply=True``. Reports
name files and census's own lines; they never echo the user's status-line text.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from scripts import statusline as sl

SHIM_MARKER = "# census launcher (managed by `census install`; do not edit)"


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
        lines.append(f"data {purge_dir}: {verb}delete")
        if apply:
            shutil.rmtree(purge_dir)
    if not lines:
        lines.append("nothing to remove")
    if not apply:
        lines.append("dry run — nothing changed; re-run with --yes")
    return 0, lines
