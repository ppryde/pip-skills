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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from context_vigil import config, paths

HOOKS: List[Tuple[str, Optional[str], str]] = [
    ("SessionStart", "startup|clear", "session-start"),
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


def settings_path() -> Path:
    return paths.config_dir() / "settings.json"


def hook_command(name: str) -> str:
    return f'"{paths.launcher_path()}" hook {name}'


def ingest_command(var: str) -> str:
    return f"printf '%s' \"${var}\" | \"{paths.launcher_path()}\" ingest 2>/dev/null || true"


def capture_command() -> str:
    return f'bash "{paths.skill_dir() / "scripts" / "capture.sh"}"'


def _read_settings() -> Tuple[str, Dict[str, Any]]:
    path = settings_path()
    if not path.exists():
        return "", {}
    text = path.read_text()
    try:
        data = json.loads(text) if text.strip() else {}
    except ValueError as exc:
        raise InstallError(f"{path} is not valid JSON ({exc}); fix it and re-run") from exc
    if not isinstance(data, dict):
        raise InstallError(f"{path} is not a JSON object; fix it and re-run")
    return text, data


def _dump(data: Dict[str, Any]) -> str:
    return json.dumps(data, indent=2) + "\n"


def _is_ours(entry: Any) -> bool:
    hooks = entry.get("hooks") if isinstance(entry, dict) else None
    return isinstance(hooks, list) and any(
        isinstance(h, dict) and _OUR_HOOK.search(str(h.get("command", ""))) for h in hooks)


def _commands(entry: Any) -> List[str]:
    return [str(h.get("command", "")) for h in entry.get("hooks", []) if isinstance(h, dict)]


def _with_hooks(data: Dict[str, Any]) -> Dict[str, Any]:
    hooks = data.setdefault("hooks", {})
    for event, matcher, name in HOOKS:
        entries = [e for e in hooks.get(event, []) if not _is_ours(e)
                   or _commands(e) == [hook_command(name)]]
        wanted: Dict[str, Any] = {"hooks": [{"type": "command", "command": hook_command(name)}]}
        if matcher:
            wanted = {"matcher": matcher, **wanted}
        if wanted not in entries:
            entries.append(wanted)
        hooks[event] = entries
    return data


def _without_hooks(data: Dict[str, Any]) -> Dict[str, Any]:
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return data
    for event in list(hooks):
        kept = [e for e in hooks[event] if not _is_ours(e)]
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


def splice_statusline(text: str) -> Optional[str]:
    if SL_START in text:
        return text
    out: List[str] = []
    done = False
    for line in text.splitlines(keepends=True):
        out.append(line if line.endswith("\n") else line + "\n")
        match = _SLURP.match(line)
        if match and not done:
            out.append(f"{SL_START}\n{ingest_command(match.group(1))}\n{SL_END}\n")
            done = True
    return "".join(out) if done else None


def unsplice_statusline(text: str) -> str:
    out: List[str] = []
    skipping = False
    for line in text.splitlines(keepends=True):
        if SL_START in line:
            skipping = True
            continue
        if skipping:
            skipping = SL_END not in line
            continue
        out.append(line)
    return "".join(out)


def _manual_line() -> str:
    return (f"Add this line to your status-line script, right after the line that "
            f"reads stdin (e.g. input=$(cat)):\n  {ingest_command('input')}")


def plan_install(threshold: Optional[int], launcher: Optional[str] = None) -> Plan:
    if threshold is not None:
        config.coerce("context.threshold", threshold)
    before, data = _read_settings()
    plan = Plan(threshold=threshold)
    record: Dict[str, Any] = {"skill_dir": str(paths.skill_dir()), "statusline": None,
                              "launcher": launcher}
    data = _with_hooks(data)
    status = data.get("statusLine")
    command = status.get("command") if isinstance(status, dict) else None
    if not isinstance(command, str) or not command:
        data["statusLine"] = {"type": "command", "command": capture_command(),
                              "refreshInterval": 60}
        record["statusline"] = {"kind": "capture"}
    elif "capture.sh" in command and str(paths.skill_dir()) in command:
        record["statusline"] = {"kind": "capture"}
    else:
        script = statusline_script(command)
        spliced = splice_statusline(script.read_text()) if script else None
        if script is not None and spliced is not None:
            plan.changes.append(Change(script, script.read_text(), spliced))
            record["statusline"] = {"kind": "spliced", "path": str(script)}
        else:
            plan.manual.append(_manual_line())
    plan.changes.insert(0, Change(settings_path(), before, _dump(data)))
    plan.record = record
    return plan


def apply(plan: Plan) -> None:
    for change in plan.changes:
        if change.before == change.after:
            continue
        if change.after == "" and change.path == settings_path():
            change.path.unlink(missing_ok=True)
            continue
        change.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = change.path.with_name(change.path.name + ".context-vigil.tmp")
        tmp.write_text(change.after)
        os.replace(tmp, change.path)
    record_path = paths.install_record_path()
    if plan.record.get("uninstall"):
        record_path.unlink(missing_ok=True)
        return
    if plan.threshold is not None:
        config.set_value(Path.cwd(), "context.threshold", str(plan.threshold))
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(plan.record, indent=2) + "\n")


def plan_uninstall() -> Plan:
    before, data = _read_settings()
    try:
        record = json.loads(paths.install_record_path().read_text())
    except (OSError, ValueError):
        record = {}
    plan = Plan(record={"uninstall": True})
    data = _without_hooks(data)
    status = data.get("statusLine")
    if isinstance(status, dict) and "capture.sh" in str(status.get("command", "")) \
            and str(paths.skill_dir()) in str(status.get("command", "")):
        del data["statusLine"]
    sl = record.get("statusline") if isinstance(record, dict) else None
    if isinstance(sl, dict) and sl.get("kind") == "spliced":
        script = Path(sl["path"])
        if script.exists():
            text = script.read_text()
            plan.changes.append(Change(script, text, unsplice_statusline(text)))
        else:
            plan.manual.append(f"status-line script {script} no longer exists — nothing to remove")
    after = _dump(data) if data else ""
    if before and not data and before.strip() == "{}":
        after = before
    plan.changes.insert(0, Change(settings_path(), before, after))
    return plan
