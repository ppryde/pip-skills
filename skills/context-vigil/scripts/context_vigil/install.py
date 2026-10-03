"""Wire context-vigil into Claude Code: hooks, status-line feed, threshold.

agents.md ships skills as plain folders, so there is no plugin hooks.json —
the skill registers its own hooks in settings.json. Every change is planned
first (``plan_install``), shown as a summary, and applied only on consent
(``apply``). Every added artefact is recorded in install.json so ``uninstall``
removes exactly what was added and nothing the user wrote.

The summary never shows the user's own content. rc files, settings.json and
status-line scripts routinely hold API keys, and the agent runs these commands
through Bash, so anything printed lands in the transcript. A preview therefore
names the file and prints only the lines WE add or remove (or, for settings.json,
the structural paths of our own entries and our own command strings) — never a
text diff, never a context line, never an ``env`` value or another hook's command.
"""
from __future__ import annotations

import copy
import json
import os
import re
import shlex
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

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
_SHELLS = ("bash", "sh", "zsh")
USER_TMP_SUFFIX = ".context-vigil.tmp"


class InstallError(Exception):
    """Install cannot proceed safely; nothing was changed."""


class DamagedMarkers(InstallError):
    """A managed block's markers are damaged; the file was left untouched."""


@dataclass
class Change:
    """One planned file edit. ``summary`` is the ONLY thing ever printed about it:
    built from strings context-vigil itself writes, never from ``before``."""
    path: Path
    before: str
    after: str
    summary: List[str] = field(default_factory=list)
    # MANUAL STEP lines this edit needs from the user (our own strings, paths and
    # line numbers only — never a line of the file)
    notes: List[str] = field(default_factory=list)

    def describe(self) -> str:
        return "\n".join(self.summary) if self.summary else (
            f"{self.path}: will change (contents not shown)")


def _plural(n: int) -> str:
    return f"{n} line{'' if n == 1 else 's'}"


def added_lines(path: Path, after_line: int, lines: List[str]) -> List[str]:
    """Summary of a block of OUR lines inserted after line ``after_line``."""
    return ([f"{path}: adds {_plural(len(lines))} after line {after_line}:"]
            + [f"  + {line}".rstrip() for line in lines])


def removed_block(path: Path, block: List[str], ours: Callable[[str], bool]) -> List[str]:
    """Summary of our block's removal. A line is shown only when it is exactly one
    context-vigil writes; anything else inside the markers is counted, not shown."""
    out = [f"{path}: removes our block ({_plural(len(block))}):"]
    hidden = 0
    for line in block:
        if ours(line):
            out.append(f"  - {line}".rstrip())
        else:
            hidden += 1
    if hidden:
        out.append(f"  ({_plural(hidden)} inside the block not written by context-vigil "
                   "— not shown)")
    return out


def marked_span(text: str, start: str, end: str,
                drop_separator: bool = False) -> Optional[Tuple[int, int]]:
    """0-based (first, last) line indexes of the single intact managed block, the
    separator line included when ``drop_separator``; None when absent or damaged."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if _is_marker(line, start)]
    ends = [i for i, line in enumerate(lines) if _is_marker(line, end)]
    if len(starts) != 1 or len(ends) != 1 or ends[0] < starts[0]:
        return None
    first, last = starts[0], ends[0]
    if drop_separator and first > 0 and lines[first - 1].strip() == "":
        first -= 1
    return first, last


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


def ingest_command(var: str, skill: Optional[str] = None) -> str:
    launcher = paths.launcher_path() if skill is None else Path(skill) / "scripts" / "context-vigil"
    return f"printf '%s' \"${var}\" | \"{launcher}\" ingest 2>/dev/null || true"


def read_user_text(path: Path) -> str:
    """A user file's text; a file that is not UTF-8 is an InstallError naming the path
    only (a decode error would otherwise surface as a byte offset with no file name)."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise InstallError(f"{path} is not UTF-8 text; fix or move it and re-run") from exc


def capture_command() -> str:
    return f'bash "{paths.skill_dir() / "scripts" / "capture.sh"}"'


def _skill_dirs(record: Dict[str, Any]) -> List[str]:
    """The current skill dir plus the one the last install recorded (it may have moved)."""
    dirs = [str(paths.skill_dir())]
    old = record.get("skill_dir")
    if isinstance(old, str) and old and old not in dirs:
        dirs.append(old)
    return dirs


def _our_commands(record: Dict[str, Any]) -> Set[str]:
    """Exactly the hook commands context-vigil writes, for this skill dir and the one
    the last install recorded. Nothing else is ever ours: a user's hook that merely
    mentions context-vigil (a wrapper, extra arguments, another event) is theirs."""
    names = {name for _, _, name in HOOKS}
    return {f'"{Path(d) / "scripts" / "context-vigil"}" hook {name}'
            for d in _skill_dirs(record) for name in names}


def _is_capture(command: str, record: Dict[str, Any]) -> bool:
    return "capture.sh" in command and any(d in command for d in _skill_dirs(record))


class _DuplicateKey(ValueError):
    """settings.json repeats a key inside one object (the key itself is never shown)."""


def _no_duplicate_keys(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise _DuplicateKey("duplicate key")
    return dict(pairs)


def _read_settings() -> Tuple[str, Dict[str, Any]]:
    path = settings_path()
    if not path.exists():
        return "", {}
    text = read_user_text(path)
    try:
        data = json.loads(text, object_pairs_hook=_no_duplicate_keys) if text.strip() else {}
    except _DuplicateKey as exc:
        # rewriting would silently keep only the last of each duplicate: refuse instead
        raise InstallError(f"{path} has duplicate keys in one object; fix it and "
                           "re-run (nothing was changed)") from exc
    except ValueError as exc:
        raise InstallError(f"{path} is not valid JSON ({exc}); fix it and re-run") from exc
    if not isinstance(data, dict):
        raise InstallError(f"{path} is not a JSON object; fix it and re-run")
    hooks = data.get("hooks")
    if hooks is not None and (not isinstance(hooks, dict) or any(
            v is not None and not isinstance(v, list) for v in hooks.values())):
        raise InstallError(f"{path}: unexpected shape for \"hooks\" (want an object of "
                           "lists); fix it and re-run")
    return text, data


def _dump(data: Dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _is_our_hook(hook: Any, ours: Set[str]) -> bool:
    return isinstance(hook, dict) and hook.get("command") in ours


def _is_ours(entry: Any, ours: Set[str]) -> bool:
    hooks = entry.get("hooks") if isinstance(entry, dict) else None
    return isinstance(hooks, list) and any(_is_our_hook(h, ours) for h in hooks)


def _commands(entry: Any) -> List[str]:
    return [str(h.get("command", "")) for h in entry.get("hooks", []) if isinstance(h, dict)]


def _strip_ours(entry: Any, ours: Set[str]) -> Optional[Dict[str, Any]]:
    """The entry minus our commands; None when nothing of the user's remains."""
    if not _is_ours(entry, ours):
        return entry
    rest = [h for h in entry["hooks"] if not _is_our_hook(h, ours)]
    return {**entry, "hooks": rest} if rest else None


def _with_hooks(data: Dict[str, Any], ours: Set[str]) -> Dict[str, Any]:
    hooks = data.get("hooks")
    if hooks is None:
        hooks = data["hooks"] = {}
    for event, matcher, name in HOOKS:
        wanted: Dict[str, Any] = {"hooks": [{"type": "command", "command": hook_command(name)}]}
        if matcher:
            wanted = {"matcher": matcher, **wanted}
        entries = []
        for e in hooks.get(event) or []:
            if (_is_ours(e, ours) and _commands(e) == [hook_command(name)]
                    and e.get("matcher") == matcher):
                entries.append(e)
                continue
            kept = _strip_ours(e, ours)
            if kept is not None:
                entries.append(kept)
        if wanted not in entries:
            entries.append(wanted)
        hooks[event] = entries
    return data


def _without_hooks(data: Dict[str, Any], ours: Set[str]) -> Dict[str, Any]:
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return data
    for event in list(hooks):
        if hooks[event] is None:
            continue
        kept = [k for k in (_strip_ours(e, ours) for e in hooks[event]) if k is not None]
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if not hooks:
        del data["hooks"]
    return data


_OUR_MATCHERS = {m for _, m, _ in HOOKS if m}


def _our_hook_set(data: Dict[str, Any],
                  ours: Set[str]) -> List[Tuple[str, Optional[str], str]]:
    """(event, matcher, command) for every hook of ours in ``data``, in file order."""
    found: List[Tuple[str, Optional[str], str]] = []
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return found
    for event, entries in hooks.items():
        for entry in entries or []:
            if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
                continue
            matcher = entry.get("matcher")
            for hook in entry["hooks"]:
                if _is_our_hook(hook, ours):
                    found.append((str(event), matcher if isinstance(matcher, str) else None,
                                  str(hook.get("command", ""))))
    return found


def _hook_label(event: str, matcher: Optional[str]) -> str:
    """``hooks.<Event>[matcher=…]`` — only our own event names and matchers are shown."""
    name = event if event in {e for e, _, _ in HOOKS} else "<event>"
    return f"hooks.{name}" + (f"[matcher={matcher}]" if matcher in _OUR_MATCHERS else "")


def _our_command_shown(command: str) -> str:
    """Our command verbatim when it is one the CURRENT install writes; otherwise
    (an older install's path, or anything else) it is described, not echoed."""
    known = {hook_command(n) for _, _, n in HOOKS} | {capture_command()}
    return json.dumps(command) if command in known else "an older context-vigil command"


def settings_summary(path: Path, before_text: str, before: Dict[str, Any],
                     after: Dict[str, Any], ours: Set[str],
                     deleting: bool = False) -> List[str]:
    """Structural summary of OUR changes to settings.json — never a user value.

    ``env``, ``apiKeyHelper``, other hooks' commands and every other user key are
    never read into the output: only our hook entries (event, our matcher, our
    command string) and our status-line command are named."""
    if deleting:
        return [f"{path}: deletes the file (context-vigil created it; nothing else is in it)"]
    lines = [f"{path}:" if before_text else f"{path}: creates the file"]
    old, new = _our_hook_set(before, ours), _our_hook_set(after, ours)
    for event, matcher, command in new:
        if (event, matcher, command) not in old:
            lines.append(f"  + {_hook_label(event, matcher)}: {_our_command_shown(command)}")
    for event, matcher, command in old:
        if (event, matcher, command) not in new:
            lines.append(f"  - {_hook_label(event, matcher)}: {_our_command_shown(command)}")

    def status_command(data: Dict[str, Any]) -> Optional[str]:
        status = data.get("statusLine")
        command = status.get("command") if isinstance(status, dict) else None
        return command if isinstance(command, str) else None

    was, now = status_command(before), status_command(after)
    if was != now:
        if now is not None and now == capture_command():
            verb = "+" if was is None else "~"
            lines.append(f"  {verb} statusLine.command: {json.dumps(now)}"
                         + ("" if was is None else " (replaces an older context-vigil one)"))
        elif now is None:
            lines.append("  - statusLine (context-vigil's capture command)")
    return lines


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


def _refresh_block(text: str, skill_dirs: List[str]) -> Optional[str]:
    """Point an intact spliced block's ingest line at the current launcher.

    Only a block that is byte for byte one of ours is touched: exactly one line,
    ``ingest_command(<var>)`` for the variable the script slurps stdin into, and
    the current or a recorded earlier skill dir. Anything else (a hand-edited block,
    another variable) is not ours to rewrite: None, and the caller leaves the file."""
    lines = text.splitlines(keepends=True)
    first = next(i for i, line in enumerate(lines) if _is_marker(line, SL_START))
    last = next(i for i, line in enumerate(lines) if _is_marker(line, SL_END))
    body = "".join(lines[first + 1:last])
    slurped = {m.group(1) for m in (_SLURP.match(line) for line in lines) if m}
    for var in sorted(slurped):
        if body == f"{ingest_command(var)}\n":
            return text
        if any(body == f"{ingest_command(var, d)}\n" for d in skill_dirs):
            return "".join(lines[:first + 1] + [f"{ingest_command(var)}\n"] + lines[last:])
    return None


def foreign_block_note(path: Path, text: str) -> str:
    """Our markers are intact but the block holds something we did not write: name the
    file and the block's line numbers, never its content."""
    span = marked_span(text, SL_START, SL_END)
    where = f"lines {span[0] + 1}-{span[1] + 1}" if span else "a marked block"
    return (f"{path}: {where} (context-vigil's marked block) hold lines context-vigil "
            "did not write — left untouched. Remove the block by hand and re-run install.")


def splice_statusline(text: str, skill_dirs: Optional[List[str]] = None) -> Optional[str]:
    if has_marker(text, SL_START, SL_END):
        if remove_marked_block(text, SL_START, SL_END) is None:
            return None
        return _refresh_block(text, skill_dirs or [str(paths.skill_dir())])
    out: List[str] = []
    done = False
    for line in text.splitlines(keepends=True):
        out.append(line if line.endswith("\n") else line + "\n")
        match = _SLURP.match(line)
        if match and not done:
            out.append(f"{SL_START}\n{ingest_command(match.group(1))}\n{SL_END}\n")
            done = True
    return "".join(out) if done else None


def _is_our_sl_line(line: str) -> bool:
    if line in (SL_START, SL_END):
        return True
    found = _INGEST_VAR.search(line)
    return found is not None and line == ingest_command(found.group(1))


def splice_summary(script: Path, text: str, spliced: str) -> List[str]:
    """What splicing ``script`` does, in our own lines only."""
    if has_marker(text, SL_START, SL_END):
        lines = spliced.splitlines()
        body = next(i for i, line in enumerate(lines) if _is_marker(line, SL_START)) + 1
        return [f"~ statusLine: repoints context-vigil's capture line in {script}",
                f"{script}: rewrites line {body + 1} (inside our block):",
                f"  + {lines[body]}"]
    for index, line in enumerate(text.splitlines()):
        match = _SLURP.match(line)
        if match:
            return ([f"~ statusLine: spliced capture line into {script}"]
                    + added_lines(script, index + 1,
                                  [SL_START, ingest_command(match.group(1)), SL_END]))
    return [f"~ statusLine: spliced capture line into {script}"]


def unsplice_summary(script: Path, text: str) -> List[str]:
    span = marked_span(text, SL_START, SL_END)
    if span is None:
        return [f"~ statusLine: removes the capture line from {script}"]
    block = text.splitlines()[span[0]:span[1] + 1]
    return ([f"~ statusLine: removes the capture line from {script}"]
            + removed_block(script, block, _is_our_sl_line))


def damaged_note(path: Path) -> str:
    return f"context-vigil markers in {path} look damaged — remove the block by hand"


def _manual_line() -> str:
    return (f"Add this line to your status-line script, right after the line that "
            f"reads stdin (e.g. input=$(cat)):\n  {ingest_command('input')}\n"
            "Required: until it is in place, interactive sessions are never nudged "
            "(context-vigil cannot confirm the context window without it). It takes "
            "effect on the next status-line render — no restart.")


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
    ours = _our_commands(prior)
    original = copy.deepcopy(data)
    data = _with_hooks(data, ours)
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
        script_text = read_user_text(script) if script else ""
        spliced = splice_statusline(script_text, _skill_dirs(prior)) if script else None
        if script is not None and has_marker(script_text, SL_START, SL_END) \
                and spliced is None:
            damaged = remove_marked_block(script_text, SL_START, SL_END) is None
            plan.manual.append(damaged_note(script) if damaged
                               else foreign_block_note(script, script_text))
        elif script is not None and spliced is not None:
            plan.changes.append(Change(script, script_text, spliced,
                                       splice_summary(script, script_text, spliced)))
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
            plan.manual.extend(rc.notes)
            record["rc_path"] = str(rc.path)
    # Semantically unchanged settings are left byte for byte: no reformatting churn.
    after = before if data == original else _dump(data)
    plan.changes.insert(0, Change(settings_path(), before, after,
                                  settings_summary(settings_path(), before, original, data,
                                                   ours)))
    plan.record = record
    return plan


def write_atomic(path: Path, text: str) -> None:
    """Atomically rewrite a USER file (rc, settings.json, status-line script).

    The temp file (``.cv-tmp.<name>.<random>.context-vigil.tmp``) is created 0600 by
    ``mkstemp`` (O_EXCL) and stays 0600 until the rename; only then does the target
    get its own mode back. So a key-bearing file is never readable through the temp
    copy, even if a SIGKILL or power loss strands it, and the next write beside it
    sweeps such strays once they are a minute old. Missing parents are made 0700
    whatever the umask. Symlinks are followed so a dotfiles-managed file stays a link."""
    target = path.resolve()
    paths.make_private_dirs(target.parent)
    paths.sweep_stale(target.parent, (f"*{USER_TMP_SUFFIX}",))
    try:
        mode: Optional[int] = stat.S_IMODE(os.stat(str(target)).st_mode)
    except FileNotFoundError:
        mode = None
    fd, name = tempfile.mkstemp(dir=str(target.parent),
                                prefix=f"{paths.TMP_PREFIX}{target.name}.",
                                suffix=USER_TMP_SUFFIX)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(str(tmp), str(target))
        if mode is not None:
            os.chmod(str(target), mode)
    finally:
        if os.path.lexists(str(tmp)):
            tmp.unlink()


def apply(plan: Plan) -> None:
    record_path = paths.install_record_path()
    uninstalling = bool(plan.record.get("uninstall"))
    if plan.record and not uninstalling:
        # Record first: a crash mid-apply must never leave an unrecorded edit.
        paths.write_private(record_path, json.dumps(plan.record, indent=2) + "\n")
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
    ours = _our_commands(record)
    original = copy.deepcopy(data)
    data = _without_hooks(data, ours)
    status = data.get("statusLine")
    if isinstance(status, dict) and _is_capture(str(status.get("command", "")), record):
        del data["statusLine"]
    sl = record.get("statusline")
    if isinstance(sl, dict) and sl.get("kind") == "spliced":
        script = Path(str(sl.get("path", "")))
        if script.is_file():
            text = read_user_text(script)
            stripped = remove_marked_block(text, SL_START, SL_END)
            if stripped is None:
                plan.manual.append(damaged_note(script))
            elif stripped != text:
                plan.changes.append(Change(script, text, stripped,
                                           unsplice_summary(script, text)))
        else:
            plan.manual.append(f"status-line script {script} no longer exists — nothing to remove")
    if data == original:
        after = before            # nothing of ours was there: leave the file byte for byte
    elif data:
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
        text = read_user_text(rc)
        stripped_rc = launch.strip_rc(text)
        if stripped_rc is None:
            plan.manual.append(damaged_note(rc))
        elif stripped_rc != text:
            plan.changes.append(Change(rc, text, stripped_rc, launch.removal_summary(rc, text)))
    plan.changes.insert(0, Change(settings_path(), before, after, settings_summary(
        settings_path(), before, original, data, ours,
        deleting=bool(before) and after == "")))
    return plan


# --- live state, for `status` ------------------------------------------------------
# Read from the real files, never the install record. Every result is a count or one
# of our own words: nothing from settings.json or a status-line script is returned.


class LiveState:
    """What is actually wired right now. ``hooks`` is None when settings.json
    cannot be read; ``statusline`` is capture | spliced | manual | missing | unknown."""

    def __init__(self, hooks: Optional[int], statusline: str) -> None:
        self.hooks = hooks
        self.statusline = statusline


def _hooks_present(data: Dict[str, Any]) -> int:
    """How many of our four hooks are in ``data`` with our matcher, pointing at this
    skill's launcher (a moved skill's stale entries do not count: they never run)."""
    present = 0
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    for event, matcher, name in HOOKS:
        wanted = hook_command(name)
        for entry in hooks.get(event) or []:
            if (isinstance(entry, dict) and entry.get("matcher") == matcher
                    and wanted in _commands(entry)):
                present += 1
                break
    return present


def _feeds_us(text: str) -> bool:
    return str(paths.launcher_path()) in text and " ingest" in text


def _statusline_kind(data: Dict[str, Any]) -> str:
    status = data.get("statusLine")
    command = status.get("command") if isinstance(status, dict) else None
    if not isinstance(command, str) or not command:
        return "missing"
    if _is_capture(command, _read_record()):
        return "capture"
    if _feeds_us(command):
        return "manual"
    script = statusline_script(command)
    if script is None:
        return "missing"
    try:
        text = script.read_text()
    except (OSError, UnicodeError):
        return "unknown"
    if has_marker(text, SL_START, SL_END) and _feeds_us(text):
        return "spliced"
    return "manual" if _feeds_us(text) else "missing"


def live_state() -> LiveState:
    try:
        _text, data = _read_settings()
    except (InstallError, OSError, UnicodeError):
        return LiveState(None, "unknown")
    return LiveState(_hooks_present(data), _statusline_kind(data))
