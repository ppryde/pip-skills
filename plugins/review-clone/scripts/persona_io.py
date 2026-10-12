"""PERSONA.md frontmatter R/W and drift log helpers for review-clone.

Also a small CLI, run by absolute path (no import path needed, CR-10):

    python3 <plugin>/scripts/persona_io.py paths  --alias A
    python3 <plugin>/scripts/persona_io.py list
    python3 <plugin>/scripts/persona_io.py read   --alias A
    python3 <plugin>/scripts/persona_io.py write  --alias A --frontmatter FM.json --body BODY.md
    python3 <plugin>/scripts/persona_io.py update --alias A --set FM_PART.json
    python3 <plugin>/scripts/persona_io.py drift  --alias A --entry ENTRY.json

JSON on stdout. Files hold the data, never argv.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# Stdlib YAML-ish: PERSONA frontmatter is intentionally constrained to types
# we can parse without external deps. See parse_yaml below.

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def config_dir() -> Path:
    """The Claude config dir of this account: CLAUDE_CONFIG_DIR, else ~/.claude."""
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", "") or Path.home() / ".claude")


def commands_dir() -> Path:
    """Where per-persona slash commands live (the account's commands dir)."""
    return config_dir() / "commands"


# New personas live under <config dir>/review-clone/personas/<alias>/. REVIEW_CLONE_ROOT
# overrides it (aliases directly under it, no legacy fallback).
_DEFAULT_ROOT = Path(os.environ.get("REVIEW_CLONE_ROOT", "") or config_dir() / "review-clone" / "personas")
PERSONA_ROOT = _DEFAULT_ROOT


def legacy_roots() -> list[Path]:
    """Pre-RA-8 persona roots (<dir>/review-clone/<alias>), READ-ONLY fallback.

    Only active on the default layout: an overridden PERSONA_ROOT (tests,
    REVIEW_CLONE_ROOT) has no legacy fallback."""
    if PERSONA_ROOT != _DEFAULT_ROOT or os.environ.get("REVIEW_CLONE_ROOT"):
        return []
    out: list[Path] = []
    # This account's config dir only: with CLAUDE_CONFIG_DIR set to another
    # account, the other account's personas are not visible (~/.claude is the
    # fallback only when CLAUDE_CONFIG_DIR is unset, where it is the config dir).
    r = config_dir() / "review-clone"
    if r != PERSONA_ROOT:
        out.append(r)
    return out


_ALIAS_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")


def validate_alias(alias: str) -> str:
    """Return the alias unchanged, or raise ValueError if it is not a safe slug."""
    if not isinstance(alias, str) or not _ALIAS_RE.fullmatch(alias):
        raise ValueError(
            f"invalid alias {alias!r}: use lowercase letters, digits and hyphens "
            "only (max 41 chars, must start with a letter or digit)"
        )
    return alias


def safe_alias(alias: str) -> str:
    """Return the alias unchanged, or raise ValueError if it could escape the persona root.

    Looser than validate_alias: legacy personas (uppercase, underscores, dots,
    long names) keep working; only traversal, separators and absolute paths are refused.
    """
    if (
        not isinstance(alias, str)
        or not alias
        or alias in {".", ".."}
        or any(c in alias for c in ("/", "\\", "\0", "\n", "\r"))
        or Path(alias).is_absolute()
    ):
        raise ValueError(f"unsafe alias {alias!r}")
    return alias


def check_alias(alias: str, root: Path) -> str:
    """Traversal-only check for an existing persona; strict slug rules for a new one."""
    safe_alias(alias)
    if (root / alias).is_dir() or any((r / alias).is_dir() for r in legacy_roots()):
        return alias
    return validate_alias(alias)


def persona_dir(alias: str) -> Path:
    """Return the directory holding a persona's files (existing legacy aliases allowed)."""
    return PERSONA_ROOT / safe_alias(alias)


def persona_write_path(alias: str) -> Path:
    """Where a persona is WRITTEN: always the new root, never a legacy one."""
    return persona_dir(alias) / "PERSONA.md"


def locate_persona(alias: str) -> tuple[Path, str] | None:
    """(PERSONA.md path, "current"|"legacy") for an existing persona, else None."""
    p = persona_write_path(alias)
    if p.exists():
        return p, "current"
    for root in legacy_roots():
        q = root / safe_alias(alias) / "PERSONA.md"
        if q.exists():
            return q, "legacy"
    return None


def persona_path(alias: str) -> Path:
    """The path to read a persona's PERSONA.md from (legacy fallback), else the write path."""
    found = locate_persona(alias)
    return found[0] if found else persona_write_path(alias)


def persona_exists(alias: str) -> bool:
    """Return True if a PERSONA.md exists for the alias."""
    try:
        return locate_persona(alias) is not None
    except ValueError:
        return False


def list_personas() -> list[str]:
    """Return the sorted aliases of every persona on disk."""
    names: set[str] = set()
    for root in [PERSONA_ROOT, *legacy_roots()]:
        if root.is_dir():
            names.update(p.name for p in root.iterdir()
                         if p.is_dir() and (p / "PERSONA.md").exists())
    return sorted(names)


def _normalise(text: str) -> str:
    """Strip a BOM and fold CRLF/CR so the frontmatter regex and parser see LF."""
    return text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")


def read_frontmatter(path: Path) -> dict[str, Any]:
    """Return the frontmatter dict from a PERSONA.md file."""
    text = _normalise(path.read_text(encoding="utf-8"))
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"No YAML frontmatter found in {path}")
    return _parse_yaml(match.group(1))


def _parse_yaml(yaml_text: str) -> dict[str, Any]:
    """Parse the constrained YAML subset we use in PERSONA frontmatter.

    Supports: string scalars, int/float, true/false/null, ISO dates as
    strings, flat lists (- item), nested mappings via 2-space indent.
    Does NOT support: anchors, refs, multi-line strings, flow style.
    """
    # Use stdlib's not-quite-YAML approach: cheat via json after
    # converting safe subset. For v1, accept dependency on tomllib-style
    # constraints and write a small recursive parser.
    return _parse_block(yaml_text.splitlines(), indent=0)[0]


def _parse_block(lines: list[str], indent: int) -> tuple[dict[str, Any], int]:
    """Recursive parser for indented YAML mapping/list. Returns (parsed, next_line_index)."""
    result: dict[str, Any] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        cur_indent = len(line) - len(line.lstrip())
        if cur_indent < indent:
            return result, i
        if cur_indent > indent:
            raise ValueError(f"unexpected indentation in frontmatter: {line.strip()[:60]!r}")
        key, _, val = line.strip().partition(":")
        val = val.strip()
        if val == "":
            # Either a nested mapping or a list follows
            next_line = lines[i + 1] if i + 1 < len(lines) else ""
            next_stripped = next_line.lstrip()
            if next_stripped.startswith("- "):
                items, consumed = _parse_list(lines[i + 1 :], indent + 2)
                result[key] = items
                i += 1 + consumed
            else:
                nested, consumed = _parse_block(lines[i + 1 :], indent + 2)
                result[key] = nested
                i += 1 + consumed
        else:
            result[key] = _coerce_scalar(val)
            i += 1
    return result, i


def _parse_list(lines: list[str], indent: int) -> tuple[list[Any], int]:
    """Parse a YAML block sequence; return (items, lines consumed)."""
    items: list[Any] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        cur_indent = len(line) - len(line.lstrip())
        if cur_indent < indent:
            return items, i
        stripped = line.lstrip()
        if not stripped.startswith("- "):
            return items, i
        val = stripped[2:].strip()
        # If the item looks like "key: value" it's a dict entry — parse as block.
        if ":" in val and not val.startswith('"'):
            first_key, _, first_val = val.partition(":")
            first_val = first_val.strip()
            item: dict[str, Any] = {first_key: _coerce_scalar(first_val)}
            # Collect any continuation lines at indent+2 (the dict's body indent).
            rest, consumed = _parse_block(lines[i + 1 :], indent + 2)
            item.update(rest)
            items.append(item)
            i += 1 + consumed
        else:
            items.append(_coerce_scalar(val))
            i += 1
    return items, i


def _coerce_scalar(val: str) -> Any:
    """Coerce a raw YAML scalar string to its Python type."""
    if len(val) >= 2 and val.startswith('"') and val.endswith('"'):
        try:  # written by json.dumps (RA-9)
            parsed = json.loads(val)
            if isinstance(parsed, str):
                return parsed
        except ValueError:
            pass
        return val[1:-1]  # an older, unescaped file
    if val == "[]":
        return []
    if val == "{}":
        return {}
    if val == "true":
        return True
    if val == "false":
        return False
    if val in ("null", "~", ""):
        return None
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


def ensure_private_dir(path: Path) -> None:
    """Create a directory (and parents) readable by the owner only (0700).

    Refuses a symlinked directory at or below the persona root, and tightens an
    existing directory there to 0700."""
    try:
        within = path.relative_to(PERSONA_ROOT)
        owned = [PERSONA_ROOT / Path(*within.parts[: i + 1]) for i in range(len(within.parts))]
    except ValueError:
        owned = [path]
    for p in owned:
        if p.is_symlink():
            raise ValueError(f"refusing to use a symlinked directory: {p}")
    missing = [p for p in [path, *path.parents] if not p.exists()]
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    for p in dict.fromkeys([*missing, *owned]):
        try:
            os.chmod(p, 0o700)
        except OSError:
            pass


def write_private(path: Path, text: str) -> None:
    """Write text to a file that is 0600 from creation, refusing to follow a symlink."""
    if path.is_symlink():
        raise ValueError(f"refusing to write through a symlink: {path}")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
                     0o600)
    except OSError as exc:
        raise ValueError(f"cannot write {path} privately: {exc}") from exc
    try:
        os.fchmod(fd, 0o600)  # before any text lands in a pre-existing, looser file
    except OSError:
        pass
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)


def write_persona(path: Path, frontmatter: dict[str, Any], body: str) -> None:
    """Atomic write of PERSONA.md (frontmatter + body)."""
    ensure_private_dir(path.parent)
    yaml = _dump_yaml(frontmatter)
    content = f"---\n{yaml}---\n\n{body.rstrip()}\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    write_private(tmp, content)
    tmp.replace(path)


def _dump_yaml(data: dict[str, Any], indent: int = 0) -> str:
    """Dump the constrained YAML subset. Inverse of _parse_yaml."""
    lines: list[str] = []
    pad = " " * indent
    for key, val in data.items():
        if isinstance(val, dict):
            lines.append(f"{pad}{key}:")
            lines.append(_dump_yaml(val, indent + 2))
        elif isinstance(val, list):
            if not val:
                lines.append(f"{pad}{key}: []")
            else:
                lines.append(f"{pad}{key}:")
                for item in val:
                    if isinstance(item, dict):
                        first_key = next(iter(item))
                        lines.append(f"{pad}  - {first_key}: {_format_scalar(item[first_key])}")
                        for k, v in list(item.items())[1:]:
                            lines.append(f"{pad}    {k}: {_format_scalar(v)}")
                    else:
                        lines.append(f"{pad}  - {_format_scalar(item)}")
        else:
            lines.append(f"{pad}{key}: {_format_scalar(val)}")
    return "\n".join(lines) + ("\n" if lines else "")


def _format_scalar(val: Any) -> str:
    """Render a Python scalar as a YAML value. Strings that need quoting are
    written with json.dumps (YAML is a JSON superset), so quotes, backslashes
    and newlines round-trip."""
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    s = str(val)
    if s in ("", "true", "false", "null", "~", "[]", "{}") or s.strip() != s:
        return json.dumps(s, ensure_ascii=False)
    for conv in (int, float):
        try:
            conv(s)
            return json.dumps(s, ensure_ascii=False)
        except ValueError:
            pass
    if s.startswith(('"', "-", "[", "{", "#")) or any(c in s for c in (":", "#", "\n", "\r", "\t")):
        return json.dumps(s, ensure_ascii=False)
    return s


DRIFT_LOG_CAP = 20


def append_drift_entry(persona_path: Path, entry: dict[str, Any]) -> None:
    """Append a drift entry to PERSONA.md frontmatter, capping at DRIFT_LOG_CAP.

    Oldest entries beyond the cap are appended (as JSON lines) to a sidecar
    ``drift.log`` in the same directory, and ``drift_log_archived_count`` is
    incremented.
    """
    text = _normalise(persona_path.read_text(encoding="utf-8"))
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"No frontmatter in {persona_path}")
    fm = _parse_yaml(match.group(1))
    body = text[match.end():]

    log = list(fm.get("drift_log") or [])
    log.append(entry)

    overflow = log[:-DRIFT_LOG_CAP] if len(log) > DRIFT_LOG_CAP else []
    log = log[-DRIFT_LOG_CAP:]

    if overflow:
        fm["drift_log_archived_count"] = int(fm.get("drift_log_archived_count", 0)) + len(overflow)
    fm["drift_log"] = log
    # Persona first, archive second: a crash between the two can lose an
    # archived line but can never duplicate one (RA-9).
    write_persona(persona_path, fm, body.lstrip("\n"))
    if overflow:
        archive_path = persona_path.parent / "drift.log"
        existing = archive_path.read_text(encoding="utf-8") if archive_path.exists() else ""
        write_private(archive_path, existing + "".join(json.dumps(old) + "\n" for old in overflow))


# ----------------------------------------------------------------------- CLI --

def _ensure_current(alias: str) -> Path:
    """The persona's PERSONA.md in the current root, copying a legacy one in first.

    A legacy persona is never written to: its content moves to the new root and
    every later write lands there."""
    new = persona_write_path(alias)
    if new.exists():
        return new
    found = locate_persona(alias)
    if found is None:
        raise ValueError(f"no persona {alias!r}")
    write_persona(new, read_frontmatter(found[0]), _split_body(found[0]))
    return new


def _split_body(path: Path) -> str:
    text = _normalise(path.read_text(encoding="utf-8"))
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"No YAML frontmatter found in {path}")
    return text[match.end():].lstrip("\n")


def _read_json_file(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read JSON file {path}: {exc}") from exc


def _cmd_paths(args) -> dict:
    out: dict[str, Any] = {
        "config_dir": str(config_dir()),
        "persona_root": str(PERSONA_ROOT),
        "commands_dir": str(commands_dir()),
        "legacy_roots": [str(r) for r in legacy_roots()],
    }
    if args.alias:
        safe_alias(args.alias)
        d = persona_dir(args.alias)
        found = locate_persona(args.alias)
        out.update(
            persona_dir=str(d), raw_dir=str(d / "raw"), snapshot=str(d / "snapshot.json"),
            digest=str(d / "digest.jsonl"), persona=str(found[0]) if found else None,
            persona_source=found[1] if found else None,
            command_file=str(commands_dir() / f"review-as-{args.alias}.md"),
        )
    return out


def _cmd_read(args) -> dict:
    found = locate_persona(args.alias)
    if found is None:
        return {"status": "not-found", "alias": args.alias}
    path, source = found
    return {"status": "ok", "alias": args.alias, "path": str(path), "source": source,
            "frontmatter": read_frontmatter(path), "body": _split_body(path)}


def _cmd_write(args) -> dict:
    fm = _read_json_file(args.frontmatter)
    if not isinstance(fm, dict):
        raise ValueError("--frontmatter must hold a JSON object")
    check_alias(args.alias, PERSONA_ROOT)
    body = Path(args.body).read_text(encoding="utf-8")
    path = persona_write_path(args.alias)
    write_persona(path, fm, body)
    return {"status": "ok", "path": str(path)}


def _cmd_update(args) -> dict:
    part = _read_json_file(args.set)
    if not isinstance(part, dict):
        raise ValueError("--set must hold a JSON object")
    path = _ensure_current(args.alias)
    fm = read_frontmatter(path)
    fm.update(part)
    write_persona(path, fm, _split_body(path))
    return {"status": "ok", "path": str(path)}


def _cmd_drift(args) -> dict:
    entry = _read_json_file(args.entry)
    if not isinstance(entry, dict):
        raise ValueError("--entry must hold a JSON object")
    path = _ensure_current(args.alias)
    append_drift_entry(path, entry)
    return {"status": "ok", "path": str(path)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="persona_io.py", description="review-clone persona files")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("paths")
    p.add_argument("--alias")
    p.set_defaults(fn=_cmd_paths)
    sub.add_parser("list").set_defaults(fn=lambda a: {"status": "ok", "personas": list_personas()})
    for name, fn in (("read", _cmd_read), ("write", _cmd_write), ("update", _cmd_update),
                     ("drift", _cmd_drift)):
        q = sub.add_parser(name)
        q.add_argument("--alias", required=True)
        if name == "write":
            q.add_argument("--frontmatter", required=True)
            q.add_argument("--body", required=True)
        if name == "update":
            q.add_argument("--set", required=True)
        if name == "drift":
            q.add_argument("--entry", required=True)
        q.set_defaults(fn=fn)
    args = ap.parse_args(argv)
    try:
        result = args.fn(args)
    except (ValueError, OSError) as exc:
        json.dump({"status": "error", "error": str(exc)}, sys.stdout)
        sys.stdout.write("\n")
        return 2
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
