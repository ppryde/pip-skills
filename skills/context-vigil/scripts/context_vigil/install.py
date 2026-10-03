"""Wire context-vigil into Claude Code: hooks, status-line feed, threshold.

agents.md ships skills as plain folders, so there is no plugin hooks.json —
the skill registers its own hooks in settings.json. Every change is planned
first (``plan_install``), shown as a diff, and applied only on consent
(``apply``). Every added artefact is recorded in install.json so ``uninstall``
removes exactly what was added and nothing the user wrote.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import shlex
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from context_vigil import config, paths

HOOKS: List[Tuple[str, Optional[str], str]] = [
    ("SessionStart", "startup|clear|resume", "session-start"),
    ("Stop", None, "stop"),
    ("UserPromptSubmit", None, "nudge"),
    ("PostToolUse", "TaskCreate|TaskUpdate", "nudge"),
]
SL_START = "# --- context-vigil: record status-line payload (managed; do not edit) ---"
SL_END = "# --- end context-vigil ---"
_SLURP = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=\$\(cat\)\s*$")
_OUR_HOOK = re.compile(r"context-vigil\"?\s+hook\s+")
_SHELLS = ("bash", "sh", "zsh")


class InstallError(Exception):
    """Install cannot proceed safely; nothing was changed."""


class DamagedMarkers(InstallError):
    """A managed block's markers are damaged; the file was left untouched."""


@dataclass
class Change:
    path: Path
    before: str
    after: str

    def diff(self) -> str:
        return "".join(difflib.unified_diff(
            self.before.splitlines(keepends=True), self.after.splitlines(keepends=True),
            fromfile=f"{self.path} (current)", tofile=f"{self.path} (after)"))


@dataclass
class Plan:
    changes: List[Change] = field(default_factory=list)
    manual: List[str] = field(default_factory=list)
    record: Dict[str, Any] = field(default_factory=dict)
    threshold: Optional[int] = None
    notes: List[str] = field(default_factory=list)


def settings_path() -> Path:
    return paths.config_dir() / "settings.json"


def hook_command(name: str) -> str:
    return f'"{paths.launcher_path()}" hook {name}'


def ingest_command(var: str) -> str:
    return f"printf '%s' \"${var}\" | \"{paths.launcher_path()}\" ingest 2>/dev/null || true"


def capture_command() -> str:
    return f'bash "{paths.skill_dir() / "scripts" / "capture.sh"}"'


def _skill_dirs(record: Dict[str, Any]) -> List[str]:
    """The current skill dir plus the one the last install recorded (it may have moved)."""
    dirs = [str(paths.skill_dir())]
    old = record.get("skill_dir")
    if isinstance(old, str) and old and old not in dirs:
        dirs.append(old)
    return dirs


def _is_capture(command: str, record: Dict[str, Any]) -> bool:
    return "capture.sh" in command and any(d in command for d in _skill_dirs(record))


def _read_settings() -> Tuple[str, Dict[str, Any]]:
    path = settings_path()
    if not path.exists():
        return "", {}
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text) if text.strip() else {}
    except ValueError as exc:
        raise InstallError(f"{path} is not valid JSON ({exc}); fix it and re-run") from exc
    if not isinstance(data, dict):
        raise InstallError(f"{path} is not a JSON object; fix it and re-run")
    hooks = data.get("hooks")
    if hooks is not None and (not isinstance(hooks, dict) or any(
            not isinstance(v, list) for v in hooks.values())):
        raise InstallError(f"{path}: unexpected shape for \"hooks\" (want an object of "
                           "lists); fix it and re-run")
    return text, data


def _dump(data: Dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _is_our_hook(hook: Any) -> bool:
    return isinstance(hook, dict) and bool(_OUR_HOOK.search(str(hook.get("command", ""))))


def _is_ours(entry: Any) -> bool:
    hooks = entry.get("hooks") if isinstance(entry, dict) else None
    return isinstance(hooks, list) and any(_is_our_hook(h) for h in hooks)


def _commands(entry: Any) -> List[str]:
    return [str(h.get("command", "")) for h in entry.get("hooks", []) if isinstance(h, dict)]


def _strip_ours(entry: Any) -> Optional[Dict[str, Any]]:
    """The entry minus our commands; None when nothing of the user's remains."""
    if not _is_ours(entry):
        return entry
    rest = [h for h in entry["hooks"] if not _is_our_hook(h)]
    return {**entry, "hooks": rest} if rest else None


def _with_hooks(data: Dict[str, Any]) -> Dict[str, Any]:
    hooks = data.get("hooks")
    if hooks is None:
        hooks = data["hooks"] = {}
    for event, matcher, name in HOOKS:
        wanted: Dict[str, Any] = {"hooks": [{"type": "command", "command": hook_command(name)}]}
        if matcher:
            wanted = {"matcher": matcher, **wanted}
        entries = []
        for e in hooks.get(event, []):
            if _is_ours(e) and _commands(e) == [hook_command(name)]:
                entries.append(e)
                continue
            kept = _strip_ours(e)
            if kept is not None:
                entries.append(kept)
        if wanted not in entries:
            entries.append(wanted)
        hooks[event] = entries
    return data


def _without_hooks(data: Dict[str, Any]) -> Dict[str, Any]:
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return data
    for event in list(hooks):
        kept = [k for k in (_strip_ours(e) for e in hooks[event]) if k is not None]
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if not hooks:
        del data["hooks"]
    return data


def statusline_script(command: str) -> Optional[Path]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if not tokens:
        return None
    candidate = tokens[1] if tokens[0] in _SHELLS and len(tokens) == 2 else (
        tokens[0] if len(tokens) == 1 else None)
    if candidate is None:
        return None
    path = Path(os.path.expandvars(os.path.expanduser(candidate)))
    return path if path.is_file() else None


def _is_marker(line: str, marker: str) -> bool:
    return line.rstrip("\r\n") == marker


def has_marker(text: str, start: str, end: str) -> bool:
    """True if any line is exactly a START or END marker."""
    return any(_is_marker(line, start) or _is_marker(line, end)
               for line in text.splitlines())


def remove_marked_block(text: str, start: str, end: str,
                        drop_separator: bool = False) -> Optional[str]:
    """Remove the single managed block delimited by whole-line START/END markers.

    Returns the text unchanged when there are no markers, and None when they
    are damaged (START without END, END without START, END before START, or
    more than one block): the caller must then leave the file alone. Markers
    match whole lines only, so a user line that merely quotes one is safe.
    ``drop_separator`` also drops the one blank line we insert before a block.
    A block that ends the file without a newline takes the newline of the line
    before it too, so add/remove round-trips a file that lacked one.
    """
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if _is_marker(line, start)]
    ends = [i for i, line in enumerate(lines) if _is_marker(line, end)]
    if not starts and not ends:
        return text
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        return None
    first, last = starts[0], ends[0]
    if drop_separator and first > 0 and lines[first - 1].strip() == "":
        first -= 1
    kept = "".join(lines[:first] + lines[last + 1:])
    if not lines[last].endswith("\n") and kept.endswith("\n"):
        kept = kept[:-1]
    return kept


_INGEST_VAR = re.compile(r"\"\$([A-Za-z_][A-Za-z0-9_]*)\"")


def _refresh_block(text: str) -> str:
    """Point an intact spliced block's ingest line at the current launcher."""
    lines = text.splitlines(keepends=True)
    first = next(i for i, line in enumerate(lines) if _is_marker(line, SL_START))
    last = next(i for i, line in enumerate(lines) if _is_marker(line, SL_END))
    found = _INGEST_VAR.search("".join(lines[first + 1:last]))
    if found is None:
        return text
    body = f"{ingest_command(found.group(1))}\n"
    if "".join(lines[first + 1:last]) == body:
        return text
    return "".join(lines[:first + 1] + [body] + lines[last:])


def splice_statusline(text: str) -> Optional[str]:
    if has_marker(text, SL_START, SL_END):
        if remove_marked_block(text, SL_START, SL_END) is None:
            return None
        return _refresh_block(text)
    out: List[str] = []
    done = False
    for line in text.splitlines(keepends=True):
        out.append(line if line.endswith("\n") else line + "\n")
        match = _SLURP.match(line)
        if match and not done:
            out.append(f"{SL_START}\n{ingest_command(match.group(1))}\n{SL_END}\n")
            done = True
    return "".join(out) if done else None


def damaged_note(path: Path) -> str:
    return f"context-vigil markers in {path} look damaged — remove the block by hand"


def _manual_line() -> str:
    return (f"Add this line to your status-line script, right after the line that "
            f"reads stdin (e.g. input=$(cat)):\n  {ingest_command('input')}")


def _read_record() -> Dict[str, Any]:
    try:
        record = json.loads(paths.install_record_path().read_text())
    except (OSError, ValueError):
        return {}
    return record if isinstance(record, dict) else {}


def _settings_existed_before() -> bool:
    """True if settings.json predates our first install (kept across reinstalls)."""
    prior = _read_record().get("settings_existed")
    return prior if isinstance(prior, bool) else settings_path().exists()


def plan_install(threshold: Optional[int], launcher: Optional[str] = None) -> Plan:
    if threshold is not None:
        config.coerce("context.threshold", threshold)
    before, data = _read_settings()
    plan = Plan(threshold=threshold)
    prior = _read_record()
    record: Dict[str, Any] = {"skill_dir": str(paths.skill_dir()), "statusline": None,
                              "launcher": launcher,
                              "settings_existed": _settings_existed_before()}
    if launcher is None:
        # A reinstall that does not touch the launcher must not forget the rc
        # block an earlier one added, or uninstall would leave it behind.
        for key in ("launcher", "rc_path"):
            if prior.get(key) is not None:
                record[key] = prior[key]
    if threshold is not None:
        plan.notes.append(f"will set context.threshold = {threshold} "
                          f"(global config: {paths.global_config_path()})")
    data = _with_hooks(data)
    status = data.get("statusLine")
    command = status.get("command") if isinstance(status, dict) else None
    if not isinstance(command, str) or not command:
        data["statusLine"] = {"type": "command", "command": capture_command(),
                              "refreshInterval": 60}
        record["statusline"] = {"kind": "capture"}
    elif _is_capture(command, prior):
        record["statusline"] = {"kind": "capture"}
        if str(paths.skill_dir()) not in command and isinstance(status, dict):
            data["statusLine"] = {**status, "command": capture_command()}
    else:
        script = statusline_script(command)
        script_text = script.read_text() if script else ""
        spliced = splice_statusline(script_text) if script else None
        if script is not None and has_marker(script_text, SL_START, SL_END) \
                and spliced is None:
            plan.manual.append(damaged_note(script))
        elif script is not None and spliced is not None:
            plan.changes.append(Change(script, script_text, spliced))
            record["statusline"] = {"kind": "spliced", "path": str(script)}
        else:
            plan.manual.append(_manual_line())
    if launcher is not None:
        from context_vigil import launcher as launch
        try:
            rc = launch.plan_rc(launcher)
        except DamagedMarkers as exc:
            plan.manual.append(str(exc))
            rc = None
        else:
            if rc is None and launcher in ("on-demand", "always"):
                plan.manual.append(f"Add to your shell rc: {launch.alias_line(launcher)}")
        if rc is not None:
            plan.changes.append(rc)
            record["rc_path"] = str(rc.path)
    plan.changes.insert(0, Change(settings_path(), before, _dump(data)))
    plan.record = record
    return plan


def write_atomic(path: Path, text: str) -> None:
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".context-vigil.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        if target.exists():
            shutil.copymode(target, tmp)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()


def apply(plan: Plan) -> None:
    record_path = paths.install_record_path()
    uninstalling = bool(plan.record.get("uninstall"))
    if plan.record and not uninstalling:
        # Record first: a crash mid-apply must never leave an unrecorded edit.
        write_atomic(record_path, json.dumps(plan.record, indent=2) + "\n")
    for change in plan.changes:
        if change.before == change.after:
            continue
        if change.after == "" and change.path == settings_path():
            change.path.unlink(missing_ok=True)
            continue
        write_atomic(change.path, change.after)
    if uninstalling:
        record_path.unlink(missing_ok=True)
        return
    if plan.threshold is not None:
        config.set_value(Path.cwd(), "context.threshold", str(plan.threshold))


def plan_uninstall() -> Plan:
    before, data = _read_settings()
    record = _read_record()
    plan = Plan(record={"uninstall": True})
    if not record:
        plan.manual.append("no install record found; removing only entries recognisably "
                           "ours (hooks and capture status line)")
    data = _without_hooks(data)
    status = data.get("statusLine")
    if isinstance(status, dict) and _is_capture(str(status.get("command", "")), record):
        del data["statusLine"]
    sl = record.get("statusline")
    if isinstance(sl, dict) and sl.get("kind") == "spliced":
        script = Path(str(sl.get("path", "")))
        if script.is_file():
            text = script.read_text()
            stripped = remove_marked_block(text, SL_START, SL_END)
            if stripped is None:
                plan.manual.append(damaged_note(script))
            elif stripped != text:
                plan.changes.append(Change(script, text, stripped))
        else:
            plan.manual.append(f"status-line script {script} no longer exists — nothing to remove")
    if data:
        after = _dump(data)
    elif record.get("settings_existed") is False:
        after = ""
    else:
        after = "{}\n" if before else ""
    from context_vigil import launcher as launch
    # No rc_path on record (older install, or a reinstall that dropped it):
    # still strip an intact block from the shell's rc, notes if damaged.
    rc = Path(str(record["rc_path"])) if record.get("rc_path") else launch.rc_path()
    if rc is not None and rc.is_file():
        text = rc.read_text()
        stripped_rc = launch.strip_rc(text)
        if stripped_rc is None:
            plan.manual.append(damaged_note(rc))
        else:
            plan.changes.append(Change(rc, text, stripped_rc))
    plan.changes.insert(0, Change(settings_path(), before, after))
    return plan
