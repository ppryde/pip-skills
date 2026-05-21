"""PERSONA.md frontmatter R/W and drift log helpers for review-clone."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Stdlib YAML-ish: PERSONA frontmatter is intentionally constrained to types
# we can parse without external deps. See parse_yaml below.

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def read_frontmatter(path: Path) -> dict[str, Any]:
    """Return the frontmatter dict from a PERSONA.md file."""
    text = path.read_text(encoding="utf-8")
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
            i += 1
            continue
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
        items.append(_coerce_scalar(val))
        i += 1
    return items, i


def _coerce_scalar(val: str) -> Any:
    if val.startswith('"') and val.endswith('"'):
        return val[1:-1]
    if val == "[]":
        return []
    if val == "{}":
        return {}
    if val.lower() == "true":
        return True
    if val.lower() == "false":
        return False
    if val.lower() in ("null", "~", ""):
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


def write_persona(path: Path, frontmatter: dict[str, Any], body: str) -> None:
    """Atomic write of PERSONA.md (frontmatter + body)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    yaml = _dump_yaml(frontmatter)
    content = f"---\n{yaml}---\n\n{body.rstrip()}\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
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
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    s = str(val)
    if any(c in s for c in (":", "#", "\n")) or s.strip() != s:
        return f'"{s}"'
    return s
