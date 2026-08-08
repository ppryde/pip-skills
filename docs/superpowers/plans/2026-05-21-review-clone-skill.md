# review-clone Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a portable Claude Code plugin (`review-clone`) that derives "review-as-X" personas from any GitHub reviewer's public comment history, then runs branch reviews, refreshes, and chats grounded in cited rules.

**Architecture:** Plugin under `plugins/review-clone/`. Two skills (`clone-reviewer` for setup, `review-as` for run-time use) plus two thin Python scripts (`collect.py` for the `gh` scrape, `persona_io.py` for PERSONA.md frontmatter R/W and drift-log management). Personas live per-user at `~/.claude/review-clone/<alias>/PERSONA.md` so they travel across repos. A user-level slash command `~/.claude/commands/review-as-<alias>.md` is written at clone time per persona for tab-completion discoverability.

**Tech Stack:** Python 3.11+ stdlib only (no external deps), `gh` CLI (authenticated), Markdown + YAML frontmatter for PERSONA.md, JSON for raw scrape + snapshot, pytest for unit tests.

**Source material (read once before starting):**
- `scratch/reviewer-sim/DESIGN.md` — the doctrine (now named review-clone; supersedes any reviewer-sim references)
- `scratch/jenbot/SKILL.md` — proof-of-concept skill being generalised
- `scratch/jenbot/collect.py` — existing scraper to port + extend
- `scratch/jenbot/analysis.md` — validation target (re-create the `jen` persona, compare rules)
- `scratch/jenbot/raw/*.json` — cached scrape used for validation without re-hitting GitHub

**Locked design decisions (do NOT re-litigate):**
- Personas portable, personal-only: `~/.claude/review-clone/<alias>/PERSONA.md`
- Cross-repo missing-symbol rules silently skipped (debug-log only)
- Hard cap 6-month window; wider needs `--chunked` flag (out of v1 scope)
- Pre-extract gate: prompt user if `prs > 100 OR comments > 200`, showing both counts
- Drift log in PERSONA frontmatter, capped at 20 entries, oldest auto-archived to sidecar `drift.log` with `drift_log_archived_count` counter
- Multi-handle conflicts: most-cited rule wins; losers preserved as `also_seen:` notes
- `chat` mode must cite a real comment URL or answer "no signal in the corpus on this"
- Clone-time privacy notice (non-blocking) + auto-disclaimer line in PERSONA.md
- Re-clone of existing alias → 3-way prompt: **refresh** / **modify handles & re-extract** / **fork to new alias**

---

## File Structure

```
plugins/review-clone/
├── .claude-plugin/
│   └── plugin.json                          # Plugin manifest
├── README.md                                # User-facing docs
├── commands/
│   └── clone-reviewer.md                    # /clone-reviewer slash command
├── skills/
│   ├── clone-reviewer/
│   │   └── SKILL.md                         # Conversational setup procedure
│   └── review-as/
│       └── SKILL.md                         # Per-persona review/refresh/chat procedure
├── scripts/
│   ├── collect.py                           # gh CLI scraper (ports + extends jenbot/collect.py)
│   └── persona_io.py                        # PERSONA.md frontmatter R/W + drift log helpers
├── templates/
│   └── review-as-command.md.tmpl            # Template for per-persona slash command
├── tests/
│   ├── test_persona_io.py
│   ├── test_collect.py
│   └── fixtures/
│       ├── sample_pr.json                   # Minimal PR response for collect tests
│       └── sample_persona.md                # Minimal PERSONA.md for io tests
└── pyproject.toml                           # pytest config; no runtime deps
```

**Storage outside the plugin (created at clone time):**
```
~/.claude/review-clone/<alias>/
├── PERSONA.md                               # Persona definition (frontmatter + body)
├── raw/
│   └── pr-<n>.json                          # Per-PR scrape (pr_meta + review_comments[] + issue_comments[])
├── snapshot.json                            # Provenance: window, counts, collected_at
└── drift.log                                # Archived drift entries beyond cap of 20

~/.claude/commands/
└── review-as-<alias>.md                     # Per-persona slash command (written by clone-reviewer)
```

---

## Phase 1 — Scaffold the plugin

### Task 1: Create plugin directory structure and manifest

**Files:**
- Create: `plugins/review-clone/.claude-plugin/plugin.json`
- Create: `plugins/review-clone/README.md`
- Create: `plugins/review-clone/pyproject.toml`

- [ ] **Step 1: Create the plugin directories**

```bash
mkdir -p plugins/review-clone/.claude-plugin
mkdir -p plugins/review-clone/commands
mkdir -p plugins/review-clone/skills/clone-reviewer
mkdir -p plugins/review-clone/skills/review-as
mkdir -p plugins/review-clone/scripts
mkdir -p plugins/review-clone/templates
mkdir -p plugins/review-clone/tests/fixtures
```

- [ ] **Step 2: Write `plugins/review-clone/.claude-plugin/plugin.json`**

```json
{
  "name": "review-clone",
  "version": "0.1.0",
  "description": "Clone a reviewer's voice and rules from their public GitHub review history. Run branch reviews, refresh from new comments, or chat as the persona — every finding grounded in a cited real comment.",
  "author": {
    "name": "Pip",
    "url": "https://github.com/ppryde/pip-skills"
  },
  "keywords": ["code-review", "pr-review", "github", "persona", "voice", "review-bot"]
}
```

- [ ] **Step 3: Write `plugins/review-clone/pyproject.toml`**

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
addopts = "-v --tb=short"
```

- [ ] **Step 4: Write a placeholder `plugins/review-clone/README.md`** (replaced in final task)

```markdown
# review-clone

Clone a reviewer's voice and rules from their public GitHub review history.

Status: under construction. See `docs/superpowers/plans/2026-05-21-review-clone-skill.md`.
```

- [ ] **Step 5: Commit**

```bash
git add plugins/review-clone/
git commit -m "feat(review-clone): scaffold plugin directory structure and manifest"
```

---

## Phase 2 — Persona I/O module (TDD)

This module is the lowest-level dependency: it owns reading + writing PERSONA.md (frontmatter YAML + Markdown body), capping the drift log, and archiving old entries. Build it first so other components can use it.

### Task 2: Implement `read_frontmatter`

**Files:**
- Create: `plugins/review-clone/scripts/persona_io.py`
- Create: `plugins/review-clone/tests/test_persona_io.py`
- Create: `plugins/review-clone/tests/fixtures/sample_persona.md`

- [ ] **Step 1: Write the failing test**

Create `tests/fixtures/sample_persona.md`:

```markdown
---
alias: jen
handles:
  - jenniferjensen
repo: wayflyer/wayflyer
window:
  months: 6
  since: "2025-11-22"
last_scanned_at: "2026-05-21T14:00:00Z"
drift_log: []
drift_log_archived_count: 0
---

## Voice & tone
She uses "Can we" instead of "please".

## Rules

### Use auth-aware axios
**Severity:** blocker
**Citation:** https://example.com/c/1
```

Create `tests/test_persona_io.py`:

```python
from pathlib import Path
from scripts.persona_io import read_frontmatter


def test_read_frontmatter_parses_yaml_header():
    fm = read_frontmatter(Path("tests/fixtures/sample_persona.md"))
    assert fm["alias"] == "jen"
    assert fm["handles"] == ["jenniferjensen"]
    assert fm["repo"] == "wayflyer/wayflyer"
    assert fm["window"]["months"] == 6
    assert fm["drift_log"] == []
    assert fm["drift_log_archived_count"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd plugins/review-clone && python -m pytest tests/test_persona_io.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.persona_io'`.

- [ ] **Step 3: Write minimal implementation**

Create `scripts/persona_io.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd plugins/review-clone && python -m pytest tests/test_persona_io.py::test_read_frontmatter_parses_yaml_header -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/review-clone/scripts/persona_io.py plugins/review-clone/tests/
git commit -m "feat(review-clone): persona_io.read_frontmatter parses YAML header"
```

### Task 3: Implement `write_persona`

**Files:**
- Modify: `plugins/review-clone/scripts/persona_io.py`
- Modify: `plugins/review-clone/tests/test_persona_io.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_persona_io.py`:

```python
def test_write_persona_roundtrips(tmp_path):
    from scripts.persona_io import write_persona, read_frontmatter

    path = tmp_path / "PERSONA.md"
    frontmatter = {
        "alias": "test",
        "handles": ["a", "b"],
        "repo": "x/y",
        "window": {"months": 6, "since": "2025-11-22"},
        "drift_log": [],
        "drift_log_archived_count": 0,
    }
    body = "## Voice\nTest voice."
    write_persona(path, frontmatter, body)

    assert path.exists()
    fm = read_frontmatter(path)
    assert fm["alias"] == "test"
    assert fm["handles"] == ["a", "b"]
    assert fm["window"]["months"] == 6
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd plugins/review-clone && python -m pytest tests/test_persona_io.py::test_write_persona_roundtrips -v
```

Expected: FAIL — `ImportError: cannot import name 'write_persona'`.

- [ ] **Step 3: Add `write_persona` and `_dump_yaml` to `scripts/persona_io.py`**

```python
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
                        # Inline dict as nested under "-"
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
    # Quote if contains characters that would confuse the parser
    if any(c in s for c in (":", "#", "\n")) or s.strip() != s:
        return f'"{s}"'
    return s
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd plugins/review-clone && python -m pytest tests/test_persona_io.py -v
```

Expected: BOTH tests PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/review-clone/scripts/persona_io.py plugins/review-clone/tests/test_persona_io.py
git commit -m "feat(review-clone): persona_io.write_persona with round-trip safety"
```

### Task 4: Implement drift log cap + archive

**Files:**
- Modify: `plugins/review-clone/scripts/persona_io.py`
- Modify: `plugins/review-clone/tests/test_persona_io.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_persona_io.py`:

```python
def test_append_drift_entry_within_cap(tmp_path):
    from scripts.persona_io import append_drift_entry, read_frontmatter, write_persona

    path = tmp_path / "PERSONA.md"
    write_persona(
        path,
        {"alias": "t", "drift_log": [], "drift_log_archived_count": 0},
        "## Voice\nx",
    )

    for i in range(5):
        append_drift_entry(path, {"date": f"2026-05-0{i+1}", "summary": f"entry {i}"})

    fm = read_frontmatter(path)
    assert len(fm["drift_log"]) == 5
    assert fm["drift_log_archived_count"] == 0


def test_append_drift_entry_archives_beyond_cap(tmp_path):
    from scripts.persona_io import append_drift_entry, read_frontmatter, write_persona

    path = tmp_path / "PERSONA.md"
    write_persona(
        path,
        {"alias": "t", "drift_log": [], "drift_log_archived_count": 0},
        "## Voice\nx",
    )

    for i in range(25):
        append_drift_entry(
            path, {"date": f"2026-05-{i+1:02d}", "summary": f"entry {i}"}
        )

    fm = read_frontmatter(path)
    assert len(fm["drift_log"]) == 20, "frontmatter capped at 20"
    assert fm["drift_log_archived_count"] == 5, "5 oldest archived"

    archive = path.parent / "drift.log"
    assert archive.exists()
    archived_lines = archive.read_text().strip().split("\n")
    assert len(archived_lines) == 5
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd plugins/review-clone && python -m pytest tests/test_persona_io.py -v
```

Expected: FAIL — `ImportError: cannot import name 'append_drift_entry'`.

- [ ] **Step 3: Add `append_drift_entry` to `scripts/persona_io.py`**

```python
import json

DRIFT_LOG_CAP = 20


def append_drift_entry(persona_path: Path, entry: dict[str, Any]) -> None:
    """Append a drift entry to PERSONA.md frontmatter, capping at DRIFT_LOG_CAP.

    Oldest entries beyond the cap are appended (as JSON lines) to a sidecar
    ``drift.log`` in the same directory, and ``drift_log_archived_count`` is
    incremented.
    """
    text = persona_path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"No frontmatter in {persona_path}")
    fm = _parse_yaml(match.group(1))
    body = text[match.end() :]

    log = list(fm.get("drift_log") or [])
    log.append(entry)

    overflow = log[:-DRIFT_LOG_CAP] if len(log) > DRIFT_LOG_CAP else []
    log = log[-DRIFT_LOG_CAP:]

    if overflow:
        archive_path = persona_path.parent / "drift.log"
        with archive_path.open("a", encoding="utf-8") as f:
            for old in overflow:
                f.write(json.dumps(old) + "\n")
        fm["drift_log_archived_count"] = int(fm.get("drift_log_archived_count", 0)) + len(overflow)

    fm["drift_log"] = log
    write_persona(persona_path, fm, body.lstrip("\n"))
```

- [ ] **Step 4: Run tests**

```bash
cd plugins/review-clone && python -m pytest tests/test_persona_io.py -v
```

Expected: ALL four tests PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/review-clone/scripts/persona_io.py plugins/review-clone/tests/test_persona_io.py
git commit -m "feat(review-clone): drift log cap (20) with sidecar archive"
```

### Task 5: Add persona helpers (`persona_exists`, `persona_dir`, `list_personas`)

**Files:**
- Modify: `plugins/review-clone/scripts/persona_io.py`
- Modify: `plugins/review-clone/tests/test_persona_io.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_persona_io.py`:

```python
def test_persona_helpers(tmp_path, monkeypatch):
    from scripts import persona_io

    monkeypatch.setattr(persona_io, "PERSONA_ROOT", tmp_path)

    assert persona_io.list_personas() == []
    assert not persona_io.persona_exists("jen")

    persona_io.write_persona(
        persona_io.persona_path("jen"),
        {"alias": "jen", "drift_log": [], "drift_log_archived_count": 0},
        "## Voice\nx",
    )

    assert persona_io.persona_exists("jen")
    assert persona_io.list_personas() == ["jen"]
    assert persona_io.persona_dir("jen") == tmp_path / "jen"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd plugins/review-clone && python -m pytest tests/test_persona_io.py::test_persona_helpers -v
```

Expected: FAIL — `AttributeError: PERSONA_ROOT` (or similar).

- [ ] **Step 3: Add helpers to `scripts/persona_io.py`**

```python
import os

PERSONA_ROOT = Path(os.environ.get("REVIEW_CLONE_ROOT", Path.home() / ".claude" / "review-clone"))


def persona_dir(alias: str) -> Path:
    return PERSONA_ROOT / alias


def persona_path(alias: str) -> Path:
    return persona_dir(alias) / "PERSONA.md"


def persona_exists(alias: str) -> bool:
    return persona_path(alias).exists()


def list_personas() -> list[str]:
    if not PERSONA_ROOT.exists():
        return []
    return sorted(
        p.name for p in PERSONA_ROOT.iterdir()
        if p.is_dir() and (p / "PERSONA.md").exists()
    )
```

- [ ] **Step 4: Run all persona_io tests**

```bash
cd plugins/review-clone && python -m pytest tests/test_persona_io.py -v
```

Expected: ALL tests PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/review-clone/scripts/persona_io.py plugins/review-clone/tests/test_persona_io.py
git commit -m "feat(review-clone): persona path/exists/list helpers"
```

---

## Phase 3 — Collector script (TDD)

`collect.py` is a CLI tool that the clone-reviewer skill invokes. It scrapes `gh` for PRs touched by the persona's handles within a window, fetches review/issue comments with diff hunks and reply threads, filters by the persona's path/extension filters, and writes `raw/pr-<n>.json` + `snapshot.json` to the persona's storage dir.

It does NOT prompt; it just scrapes and reports counts. The skill reads `snapshot.json` and decides whether to prompt the user.

### Task 6: Stub `collect.py` CLI + argument parsing

**Files:**
- Create: `plugins/review-clone/scripts/collect.py`
- Create: `plugins/review-clone/tests/test_collect.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_collect.py`:

```python
import subprocess
import sys


def test_collect_cli_help():
    """`python scripts/collect.py --help` exits 0 and shows known args."""
    result = subprocess.run(
        [sys.executable, "scripts/collect.py", "--help"],
        capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "--alias" in result.stdout
    assert "--handles" in result.stdout
    assert "--repo" in result.stdout
    assert "--months" in result.stdout
    assert "--paths" in result.stdout
    assert "--extensions" in result.stdout
    assert "--since" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd plugins/review-clone && python -m pytest tests/test_collect.py -v
```

Expected: FAIL — file doesn't exist.

- [ ] **Step 3: Write minimal `scripts/collect.py`**

```python
#!/usr/bin/env python3
"""Scrape GitHub for a reviewer's PR comments. Writes raw + snapshot to
~/.claude/review-clone/<alias>/. Stdout is human-readable progress.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PERSONA_ROOT = Path(
    os.environ.get("REVIEW_CLONE_ROOT", Path.home() / ".claude" / "review-clone")
)

WINDOW_CAP_MONTHS = 6


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="collect.py",
        description="Scrape a reviewer's GitHub comments for review-clone.",
    )
    p.add_argument("--alias", required=True, help="Persona alias (kebab-case).")
    p.add_argument(
        "--handles",
        required=True,
        help="Comma-separated GitHub handles (e.g. 'jane,bob').",
    )
    p.add_argument("--repo", required=True, help="GitHub repo, e.g. 'owner/repo'.")
    p.add_argument(
        "--months",
        type=int,
        default=6,
        help="Lookback in months (default 6, hard cap 6 in v1).",
    )
    p.add_argument(
        "--paths",
        default="",
        help="Comma-separated path prefixes to include (empty = all).",
    )
    p.add_argument(
        "--extensions",
        default="",
        help="Comma-separated file extensions to include (empty = all).",
    )
    p.add_argument(
        "--since",
        default=None,
        help="ISO datetime to scrape since (refresh mode). Overrides --months.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if args.months > WINDOW_CAP_MONTHS and not args.since:
        print(
            f"error: --months {args.months} exceeds hard cap of {WINDOW_CAP_MONTHS}",
            file=sys.stderr,
        )
        return 2
    # TODO: implement scrape in Task 7+
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test**

```bash
cd plugins/review-clone && python -m pytest tests/test_collect.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/review-clone/scripts/collect.py plugins/review-clone/tests/test_collect.py
git commit -m "feat(review-clone): collect.py CLI scaffolding with arg validation"
```

### Task 7: Implement `discover_prs` (gh search wrapper)

**Files:**
- Modify: `plugins/review-clone/scripts/collect.py`
- Modify: `plugins/review-clone/tests/test_collect.py`
- Create: `plugins/review-clone/tests/fixtures/sample_search.json`

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/sample_search.json`:

```json
[
  {"number": 100, "updatedAt": "2026-05-01T10:00:00Z"},
  {"number": 200, "updatedAt": "2026-04-15T10:00:00Z"},
  {"number": 300, "updatedAt": "2026-03-01T10:00:00Z"}
]
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_collect.py`:

```python
from pathlib import Path
from unittest.mock import patch, MagicMock


def test_discover_prs_dedupes_across_handles():
    from scripts.collect import discover_prs

    fixture = Path("tests/fixtures/sample_search.json").read_text()

    with patch("scripts.collect._gh_search") as mock_search:
        mock_search.return_value = [
            {"number": 100, "updatedAt": "2026-05-01T10:00:00Z"},
            {"number": 200, "updatedAt": "2026-04-15T10:00:00Z"},
        ]
        prs = discover_prs("owner/repo", ["a", "b"], since="2026-01-01")

    # Each handle queried once, results deduped
    assert mock_search.call_count == 2
    assert sorted(prs) == [100, 200]
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd plugins/review-clone && python -m pytest tests/test_collect.py::test_discover_prs_dedupes_across_handles -v
```

Expected: FAIL — `ImportError: cannot import name 'discover_prs'`.

- [ ] **Step 4: Implement `discover_prs` and `_gh_search` in `scripts/collect.py`**

Add after `parse_args`:

```python
def _gh_search(repo: str, handle: str, since: str) -> list[dict]:
    """Call `gh search prs --json number,updatedAt`. Returns list of PR dicts."""
    cmd = [
        "gh", "search", "prs",
        "--repo", repo,
        "--involves", handle,
        "--updated", f">={since}",
        "--limit", "1000",
        "--json", "number,updatedAt",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout) if result.stdout.strip() else []


def discover_prs(repo: str, handles: list[str], since: str) -> list[int]:
    """Return deduplicated list of PR numbers touched by any handle since the given ISO date."""
    seen: set[int] = set()
    for handle in handles:
        for pr in _gh_search(repo, handle, since):
            seen.add(pr["number"])
    return sorted(seen)
```

- [ ] **Step 5: Run tests**

```bash
cd plugins/review-clone && python -m pytest tests/test_collect.py -v
```

Expected: ALL tests PASS.

- [ ] **Step 6: Commit**

```bash
git add plugins/review-clone/scripts/collect.py plugins/review-clone/tests/
git commit -m "feat(review-clone): discover_prs dedupes across handles"
```

### Task 8: Implement `fetch_pr` with diff hunks and reply threads

**Files:**
- Modify: `plugins/review-clone/scripts/collect.py`
- Modify: `plugins/review-clone/tests/test_collect.py`
- Create: `plugins/review-clone/tests/fixtures/sample_pr.json`

This is the substantive extension over jenbot/collect.py: capture `diff_hunk` (already in the GitHub API response, no extra call) and `in_reply_to_id` (lets us thread comments later).

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/sample_pr.json` (simplified GitHub API response):

```json
{
  "pr": {
    "number": 100,
    "title": "Add widget",
    "user": {"login": "jane"},
    "merged": true,
    "body": "FUNDE-123 — adds a new widget."
  },
  "review_comments": [
    {
      "id": 1001,
      "user": {"login": "jen"},
      "path": "frontend/widget.tsx",
      "body": "Use Card.Header here.",
      "diff_hunk": "@@ -10,3 +10,3 @@\n-old\n+new",
      "html_url": "https://github.com/o/r/pull/100#discussion_r1001",
      "in_reply_to_id": null,
      "created_at": "2026-05-01T10:00:00Z"
    },
    {
      "id": 1002,
      "user": {"login": "jane"},
      "path": "frontend/widget.tsx",
      "body": "Good catch, fixed.",
      "diff_hunk": "@@ -10,3 +10,3 @@\n-old\n+new",
      "html_url": "https://github.com/o/r/pull/100#discussion_r1002",
      "in_reply_to_id": 1001,
      "created_at": "2026-05-01T10:05:00Z"
    },
    {
      "id": 1003,
      "user": {"login": "jen"},
      "path": "backend/api.py",
      "body": "Outside FE scope.",
      "diff_hunk": "@@ -5,1 +5,1 @@\n-x\n+y",
      "html_url": "https://github.com/o/r/pull/100#discussion_r1003",
      "in_reply_to_id": null,
      "created_at": "2026-05-01T11:00:00Z"
    }
  ],
  "issue_comments": [
    {
      "id": 2001,
      "user": {"login": "jen"},
      "body": "@cubic-dev-ai re-review please",
      "html_url": "https://github.com/o/r/pull/100#issuecomment-2001",
      "created_at": "2026-05-01T12:00:00Z"
    }
  ]
}
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_collect.py`:

```python
def test_fetch_pr_filters_by_handle_and_path():
    from scripts.collect import fetch_pr

    fixture = json.loads(Path("tests/fixtures/sample_pr.json").read_text())

    with patch("scripts.collect._gh_get") as mock_get:
        mock_get.side_effect = [
            fixture["pr"],
            fixture["review_comments"],
            fixture["issue_comments"],
        ]
        result = fetch_pr(
            repo="o/r",
            number=100,
            handles=["jen"],
            paths=["frontend/"],
            extensions=[".tsx"],
        )

    # Filter to jen's comments on frontend .tsx files only
    assert len(result["review_comments"]) == 1
    assert result["review_comments"][0]["id"] == 1001
    assert result["review_comments"][0]["diff_hunk"].startswith("@@")
    # Reply chains: jane's reply 1002 is kept under 1001's thread
    assert result["review_comments"][0]["reply_thread"] == [
        {"id": 1002, "user": "jane", "body": "Good catch, fixed."}
    ]
    # Issue comments NOT path-filtered (no path); jen's comment kept
    assert len(result["issue_comments"]) == 1
    # PR description authored by jane (not in handles) → not captured
    assert result.get("pr_description") is None


def test_fetch_pr_captures_pr_description_if_authored_by_handle():
    from scripts.collect import fetch_pr

    fixture = json.loads(Path("tests/fixtures/sample_pr.json").read_text())

    with patch("scripts.collect._gh_get") as mock_get:
        mock_get.side_effect = [
            fixture["pr"],
            fixture["review_comments"],
            fixture["issue_comments"],
        ]
        result = fetch_pr(
            repo="o/r",
            number=100,
            handles=["jane"],
            paths=[],
            extensions=[],
        )

    assert result["pr_description"] == "FUNDE-123 — adds a new widget."
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd plugins/review-clone && python -m pytest tests/test_collect.py -v -k fetch_pr
```

Expected: FAIL — `ImportError: cannot import name 'fetch_pr'`.

- [ ] **Step 4: Implement `fetch_pr` and `_gh_get` in `scripts/collect.py`**

```python
def _gh_get(api_path: str, paginate: bool = False) -> Any:
    """Call `gh api <path>` and return parsed JSON."""
    cmd = ["gh", "api", api_path]
    if paginate:
        cmd.append("--paginate")
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout) if result.stdout.strip() else []


def _matches_path_filter(path: str, paths: list[str], extensions: list[str]) -> bool:
    if not paths and not extensions:
        return True
    if paths and any(path.startswith(p) for p in paths):
        return True
    if extensions and any(path.endswith(e) for e in extensions):
        return True
    return False


def fetch_pr(
    repo: str,
    number: int,
    handles: list[str],
    paths: list[str],
    extensions: list[str],
) -> dict:
    """Fetch one PR's metadata + filtered comments + reply threads.

    Returns a dict with pr_meta, review_comments (with diff_hunk + reply_thread),
    issue_comments, and pr_description (if authored by any handle).
    """
    pr_meta = _gh_get(f"/repos/{repo}/pulls/{number}")
    review_comments = _gh_get(f"/repos/{repo}/pulls/{number}/comments", paginate=True)
    issue_comments = _gh_get(f"/repos/{repo}/issues/{number}/comments", paginate=True)

    handle_set = set(handles)

    # Index review comments by id for threading
    by_id = {c["id"]: c for c in review_comments}

    # Keep top-level (no in_reply_to_id) comments by our handles, matching
    # path/ext filter. Attach the full reply thread regardless of author.
    kept_reviews = []
    for c in review_comments:
        if c.get("in_reply_to_id") is not None:
            continue
        if c["user"]["login"] not in handle_set:
            continue
        if not _matches_path_filter(c["path"], paths, extensions):
            continue
        thread = [
            {
                "id": r["id"],
                "user": r["user"]["login"],
                "body": r["body"],
            }
            for r in review_comments
            if r.get("in_reply_to_id") == c["id"]
        ]
        kept_reviews.append({
            "id": c["id"],
            "user": c["user"]["login"],
            "path": c["path"],
            "body": c["body"],
            "diff_hunk": c.get("diff_hunk", ""),
            "html_url": c["html_url"],
            "created_at": c["created_at"],
            "reply_thread": thread,
        })

    # Issue comments: no path; just filter by handle
    kept_issues = [
        {
            "id": c["id"],
            "user": c["user"]["login"],
            "body": c["body"],
            "html_url": c["html_url"],
            "created_at": c["created_at"],
        }
        for c in issue_comments
        if c["user"]["login"] in handle_set
    ]

    # PR description: capture if authored by a handle
    pr_description = None
    if pr_meta["user"]["login"] in handle_set:
        pr_description = pr_meta.get("body") or ""

    return {
        "pr_meta": {
            "number": pr_meta["number"],
            "title": pr_meta["title"],
            "author": pr_meta["user"]["login"],
            "merged": pr_meta.get("merged", False),
        },
        "review_comments": kept_reviews,
        "issue_comments": kept_issues,
        "pr_description": pr_description,
    }
```

- [ ] **Step 5: Run all collect tests**

```bash
cd plugins/review-clone && python -m pytest tests/test_collect.py -v
```

Expected: ALL tests PASS.

- [ ] **Step 6: Commit**

```bash
git add plugins/review-clone/scripts/collect.py plugins/review-clone/tests/
git commit -m "feat(review-clone): fetch_pr captures diff hunks + reply threads + PR descriptions"
```

### Task 9: Implement `run_collect` (full pipeline + snapshot.json)

**Files:**
- Modify: `plugins/review-clone/scripts/collect.py`
- Modify: `plugins/review-clone/tests/test_collect.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_collect.py`:

```python
def test_run_collect_writes_raw_and_snapshot(tmp_path, monkeypatch):
    import scripts.collect as collect_mod

    monkeypatch.setattr(collect_mod, "PERSONA_ROOT", tmp_path)

    fixture = json.loads(Path("tests/fixtures/sample_pr.json").read_text())

    with patch.object(collect_mod, "discover_prs", return_value=[100]), \
         patch.object(collect_mod, "fetch_pr", return_value={
             "pr_meta": {"number": 100, "title": "x", "author": "jane", "merged": True},
             "review_comments": [{"id": 1, "user": "jen", "path": "f.tsx",
                                  "body": "x", "diff_hunk": "@@", "reply_thread": [],
                                  "html_url": "u", "created_at": "2026-05-01T10:00:00Z"}],
             "issue_comments": [],
             "pr_description": None,
         }):
        snapshot = collect_mod.run_collect(
            alias="jen",
            handles=["jen"],
            repo="o/r",
            months=6,
            paths=["frontend/"],
            extensions=[".tsx"],
            since=None,
        )

    persona_dir = tmp_path / "jen"
    raw_dir = persona_dir / "raw"
    assert raw_dir.exists()
    assert (raw_dir / "pr-100.json").exists()
    assert (persona_dir / "snapshot.json").exists()

    saved = json.loads((persona_dir / "snapshot.json").read_text())
    assert saved["counts"]["prs"] == 1
    assert saved["counts"]["review_comments"] == 1
    assert saved["counts"]["issue_comments"] == 0
    assert saved["counts"]["pr_descriptions"] == 0
    assert saved["window"]["months"] == 6
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd plugins/review-clone && python -m pytest tests/test_collect.py::test_run_collect_writes_raw_and_snapshot -v
```

Expected: FAIL — `AttributeError: module 'scripts.collect' has no attribute 'run_collect'`.

- [ ] **Step 3: Implement `run_collect` and wire to `main()`**

Add to `scripts/collect.py`:

```python
def _compute_since(months: int) -> str:
    now = datetime.now(timezone.utc)
    delta = timedelta(days=30 * months)
    return (now - delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_collect(
    *,
    alias: str,
    handles: list[str],
    repo: str,
    months: int,
    paths: list[str],
    extensions: list[str],
    since: str | None,
) -> dict:
    """Full scrape pipeline. Writes raw/ + snapshot.json. Returns the snapshot dict."""
    since = since or _compute_since(months)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    persona_dir = PERSONA_ROOT / alias
    raw_dir = persona_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    prs = discover_prs(repo, handles, since)
    print(f"Discovered {len(prs)} PRs touching {','.join(handles)} since {since}", file=sys.stderr)

    counts = {"prs": 0, "review_comments": 0, "issue_comments": 0, "pr_descriptions": 0}

    for i, n in enumerate(prs, 1):
        print(f"  [{i}/{len(prs)}] fetching PR #{n}", file=sys.stderr)
        data = fetch_pr(repo, n, handles, paths, extensions)
        if not data["review_comments"] and not data["issue_comments"] and not data["pr_description"]:
            continue  # PR had nothing matching the filter
        (raw_dir / f"pr-{n}.json").write_text(json.dumps(data, indent=2))
        counts["prs"] += 1
        counts["review_comments"] += len(data["review_comments"])
        counts["issue_comments"] += len(data["issue_comments"])
        if data["pr_description"]:
            counts["pr_descriptions"] += 1

    snapshot = {
        "alias": alias,
        "collected_at": now_iso,
        "since": since,
        "until": now_iso,
        "repo": repo,
        "handles": handles,
        "filters": {"paths": paths, "extensions": extensions},
        "window": {"months": months, "since": since},
        "counts": counts,
    }
    (persona_dir / "snapshot.json").write_text(json.dumps(snapshot, indent=2))
    return snapshot
```

Update `main()` to call `run_collect`:

```python
def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if args.months > WINDOW_CAP_MONTHS and not args.since:
        print(
            f"error: --months {args.months} exceeds hard cap of {WINDOW_CAP_MONTHS}",
            file=sys.stderr,
        )
        return 2

    snapshot = run_collect(
        alias=args.alias,
        handles=[h.strip() for h in args.handles.split(",") if h.strip()],
        repo=args.repo,
        months=args.months,
        paths=[p.strip() for p in args.paths.split(",") if p.strip()],
        extensions=[e.strip() for e in args.extensions.split(",") if e.strip()],
        since=args.since,
    )
    # Print the snapshot to stdout (machine-readable) for the skill to consume
    print(json.dumps(snapshot))
    return 0
```

- [ ] **Step 4: Run all collect tests**

```bash
cd plugins/review-clone && python -m pytest tests/test_collect.py -v
```

Expected: ALL tests PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/review-clone/scripts/collect.py plugins/review-clone/tests/test_collect.py
git commit -m "feat(review-clone): run_collect writes raw/ and snapshot.json"
```

### Task 10: Incremental refresh via `--since` (no behavioural change, integration check)

**Files:**
- Modify: `plugins/review-clone/tests/test_collect.py`

- [ ] **Step 1: Write the integration test**

Append to `tests/test_collect.py`:

```python
def test_run_collect_skips_unchanged_prs_in_refresh_mode(tmp_path, monkeypatch):
    """When --since is set, discover_prs is called with that date directly,
    NOT a recomputed months-based date."""
    import scripts.collect as collect_mod

    monkeypatch.setattr(collect_mod, "PERSONA_ROOT", tmp_path)

    captured_since = []

    def fake_discover(repo, handles, since):
        captured_since.append(since)
        return []

    with patch.object(collect_mod, "discover_prs", side_effect=fake_discover):
        collect_mod.run_collect(
            alias="jen",
            handles=["jen"],
            repo="o/r",
            months=6,
            paths=[],
            extensions=[],
            since="2026-05-01T00:00:00Z",
        )

    assert captured_since == ["2026-05-01T00:00:00Z"]
```

- [ ] **Step 2: Run test**

```bash
cd plugins/review-clone && python -m pytest tests/test_collect.py -v
```

Expected: PASS (the implementation already supports `--since` from Task 9).

- [ ] **Step 3: Commit**

```bash
git add plugins/review-clone/tests/test_collect.py
git commit -m "test(review-clone): integration test for --since refresh mode"
```

---

## Phase 4 — clone-reviewer skill

### Task 11: Write `skills/clone-reviewer/SKILL.md`

**Files:**
- Create: `plugins/review-clone/skills/clone-reviewer/SKILL.md`

- [ ] **Step 1: Write SKILL.md**

```markdown
---
name: clone-reviewer
description: Use when the user wants to create a new "review-as-X" persona by cloning a reviewer's public GitHub comment history. Triggers on "clone reviewer", "create review persona", "make a reviewer bot for X", "review-clone setup", or the slash command /clone-reviewer.
---

# Clone Reviewer — derive a persona from real review history

You are setting up a new `review-clone` persona. The user wants you to derive a "review-as-X" voice + ruleset from one or more GitHub reviewers' public comment history, and register a slash command `/review-as-<alias>` for future use.

## Storage (locked)

- Persona files: `~/.claude/review-clone/<alias>/PERSONA.md`
- Raw scrape: `~/.claude/review-clone/<alias>/raw/pr-<n>.json`
- Snapshot: `~/.claude/review-clone/<alias>/snapshot.json`
- Per-persona slash command: `~/.claude/commands/review-as-<alias>.md`
- Drift log overflow: `~/.claude/review-clone/<alias>/drift.log`

## Procedure

### Step 0 — Re-clone check

Run `python <plugin>/scripts/persona_io.py --list` (or use the helper inline) to check if any personas already exist. If the user's intended alias is taken, present this 3-way prompt:

> A persona `<alias>` already exists (last scanned <last_scanned_at>).
> 1. **Refresh** — pull comments since last scan, fold into existing rules
> 2. **Modify handles & re-extract** — add/remove handles, full re-pull for added handles
> 3. **Fork to new alias** — create a separate persona under a different name

Only proceed to Step 1 after the user picks. If they pick **Refresh**, hand off to the `review-as` skill's refresh flow.

### Step 1 — Conversational setup (one question at a time)

Ask each of these in turn, accepting defaults shown in brackets:

1. **Alias** — kebab-case, unique. Becomes the slash command name (`jen` → `/review-as-jen`).
2. **GitHub handle(s)** — one or more, comma-separated. Multi-handle personas aggregate across all listed handles.
3. **Repo scope** [defaults to the current repo's `origin` if any] — e.g. `wayflyer/wayflyer`.
4. **Path filters** [empty = all] — comma-separated path prefixes (`frontend/, packages/`).
5. **Extension filters** [empty = all] — comma-separated extensions (`.ts, .tsx, .css, .scss`).
6. **Time window** [6 months] — hard cap at 6 in v1.
7. **Tone** [`copy`] — `copy` (mimic voice) or `neutral` (rules in plain prose).
8. **Authoring voice** [yes if tone=copy, else no] — include their PR descriptions as input for an "author-as-X" sub-mode.
9. **Lets-go calibration** [skippable] — "Anything you've seen <handle> explicitly NOT care about?" Free text, used as anti-rules.

### Step 2 — Privacy notice (non-blocking)

After answers, before scraping, print:

> 🔔 This will derive a persona from <handle>'s **public** GitHub review comments. They will not be notified. A disclaimer line stating the derived nature will be written into PERSONA.md.

Continue without confirmation — non-blocking by design.

### Step 3 — Run the collector

Invoke the scraper:

```bash
python <plugin>/scripts/collect.py \
  --alias <alias> \
  --handles <handles> \
  --repo <repo> \
  --months <months> \
  --paths <paths> \
  --extensions <extensions>
```

Capture stdout (the JSON snapshot). Stream stderr to the user so they see progress.

### Step 4 — Pre-extract gate

Read `snapshot.json.counts`. Display:

> Scraped **<prs> PRs**, **<review_comments + issue_comments> comments**, **<pr_descriptions> PR descriptions** for `<alias>`.

If `prs > 100 OR (review_comments + issue_comments) > 200`, prompt:

> This is a large corpus. Theme extraction will use significant context tokens. Proceed? [y/N]

If user declines, leave the raw data in place (they can re-run later) and stop.

### Step 5 — Theme extraction (LLM-driven, you do this)

Read every `~/.claude/review-clone/<alias>/raw/pr-*.json`. For each comment:

- **Honor withdrawals.** If a comment's `reply_thread` shows the author conceding (e.g. "good point, ignore my last", "Ha, I conflicted myself!"), mark that comment as withdrawn — do NOT derive a rule from it.
- **Multi-handle conflict resolution.** When two handles' comments contradict, pick the rule with the most citations across the corpus. Preserve losers under an `also_seen:` field on the rule.

Derive:

1. **Rules.** Cluster comments by topic. For each cluster, write a rule with: title, topic tags, severity (use the reviewer's actual phrasings to calibrate), citation URL (the strongest-anchor comment), one positive + one negative example pulled directly from the corpus.
2. **Voice patterns.** Openers, severity ladder (block/strong/suggest/question/non-blocking), quirks (e.g. "Needs reverted" without "to be"), what they NEVER say.
3. **Lets-go.** From the corpus + the user's Step 1.9 input.

### Step 6 — Write PERSONA.md

Use the persona_io helpers (`from scripts.persona_io import write_persona, persona_path`). Frontmatter shape:

```yaml
alias: <alias>
handles:
  - <handle1>
repo: <repo>
filters:
  paths: [...]
  extensions: [...]
window:
  months: <n>
  since: "<iso>"
tone: <copy|neutral>
authoring_voice: <true|false>
last_scanned_at: "<iso>"
snapshot:
  prs: <n>
  review_comments: <n>
  issue_comments: <n>
  pr_descriptions: <n>
output_default: null
drift_log: []
drift_log_archived_count: 0
disclaimer: "Derived from public GitHub review history of <handles>. Not endorsed by them."
```

Body sections: `## Voice & tone`, `## Rules` (one ### per rule, with severity/citation/examples), `## What they let go`, `## Drift log`.

### Step 7 — Write the per-persona slash command

Render `<plugin>/templates/review-as-command.md.tmpl` substituting `<alias>` and `<last_scanned_at>`. Write to `~/.claude/commands/review-as-<alias>.md`. Create the `~/.claude/commands/` dir if missing.

### Step 8 — Final summary

Print:

> ✅ Persona `<alias>` cloned.
> - <N> rules derived from <M> comments across <P> PRs
> - Slash command `/review-as-<alias>` ready
> - Window: <months> months · last scanned <last_scanned_at>
>
> Try it: `/review-as-<alias>` to review the current branch, or `/review-as-<alias> chat "would they like X?"`.

## Constraints

- Do NOT scrape outside the user's stated window. Hard cap 6 months in v1.
- Do NOT skip the withdrawal pass — false rules from softened comments are the #1 quality problem.
- Do NOT invent rules without a citation URL. Every rule must point at a real comment.
- Do NOT fabricate symbols/APIs in examples. Quote the comment's body verbatim where it names anything.
```

- [ ] **Step 2: Commit**

```bash
git add plugins/review-clone/skills/clone-reviewer/SKILL.md
git commit -m "feat(review-clone): clone-reviewer skill procedure"
```

### Task 12: Write the slash command wrapper for clone-reviewer

**Files:**
- Create: `plugins/review-clone/commands/clone-reviewer.md`

- [ ] **Step 1: Write the command file**

```markdown
---
description: Clone a reviewer's voice and rules from their public GitHub review history. Walks you through setup; creates /review-as-<alias>.
---

Invoke the `clone-reviewer` skill. Follow its procedure step-by-step, asking the user one question at a time.

$ARGUMENTS
```

- [ ] **Step 2: Commit**

```bash
git add plugins/review-clone/commands/clone-reviewer.md
git commit -m "feat(review-clone): /clone-reviewer slash command"
```

### Task 13: Write the per-persona command template

**Files:**
- Create: `plugins/review-clone/templates/review-as-command.md.tmpl`

- [ ] **Step 1: Write the template**

```markdown
---
description: Review the current branch as {{ALIAS}} (last calibrated {{LAST_SCANNED_AT}}). Modes: review (default), refresh, chat.
---

Invoke the `review-as` skill for persona `{{ALIAS}}`.

Parsing rule:
- No args → `review` mode
- First arg `refresh` → `refresh` mode
- First arg `chat` → `chat` mode; the rest of the args are the prompt
- Anything else → `chat` mode; full args are the prompt

$ARGUMENTS
```

- [ ] **Step 2: Commit**

```bash
git add plugins/review-clone/templates/review-as-command.md.tmpl
git commit -m "feat(review-clone): per-persona slash command template"
```

---

## Phase 5 — review-as skill

This is the run-time skill that handles all three modes (`review`, `refresh`, `chat`) for any persona.

### Task 14: Write `skills/review-as/SKILL.md`

**Files:**
- Create: `plugins/review-clone/skills/review-as/SKILL.md`

- [ ] **Step 1: Write SKILL.md**

```markdown
---
name: review-as
description: Use when the user invokes /review-as-<alias>, says "review as <alias>", asks "would <alias> like X", or runs refresh/chat on an existing review-clone persona. Loads PERSONA.md, dispatches to review/refresh/chat mode.
---

# review-as — run a cloned reviewer persona

You are running an existing `review-clone` persona. The PERSONA.md frontmatter is your single source of truth; the rules + voice live in the body.

## Modes

Dispatch from `$ARGUMENTS`:
- empty → **review**
- `refresh` → **refresh**
- `chat <prompt>` → **chat**
- anything else → **chat** with the full arg string as the prompt

## Step 0 — Load the persona

Read `~/.claude/review-clone/<alias>/PERSONA.md`. Use `scripts/persona_io.read_frontmatter` for the YAML; read the body raw for rules + voice.

**Opening line, every invocation:**

> Running `/review-as-<alias>` against snapshot from `<last_scanned_at>`.

If `last_scanned_at` is more than 30 days old, suggest (don't force) a refresh:

> Snapshot is <N> days old. Consider `/review-as-<alias> refresh` before relying on this review.

---

## Mode: review

### 1 — Compute the diff

```bash
git fetch origin main --quiet
git diff origin/main...HEAD --name-only
```

Filter to files matching the persona's `filters.paths` OR `filters.extensions`. If empty:

> Nothing to review — no files matching <alias>'s scope have changed.

### 2 — For each in-scope changed file

```bash
git diff origin/main...HEAD -- <path>
```

Read the file at HEAD too (not just the hunk) — context matters for rules that point at adjacent code.

### 3 — Walk the rule list

For each rule in the PERSONA body, decide if it applies to any changed file. If yes, draft a finding.

### 4 — Verification gate (run BEFORE emitting each finding)

**6a — API reality check.** If the rule names a function/helper/flag/component:
- Use `Grep` (via the Grep tool) to confirm the symbol currently exists (or doesn't, if the rule says so) in the target repo.
- **If the symbol is absent from the target repo:** silently skip this rule. Do NOT emit; do NOT explain to the user. (Locked decision B.)

**6b — Trace-the-fix.** Mentally apply the proposed fix to the diff. If it doesn't compile, doesn't change behaviour, or needs additional unstated changes — downgrade severity to Question, or drop entirely.

**6c — Lets-go check.** If the finding matches anything in the persona's `## What they let go` section, drop it.

### 5 — Output mode selector

Read `output_default` from frontmatter:
- If set → use it silently
- If null → present three options:
  1. **Summary in chat, details in file** (`summary-chat-details-file`)
  2. **All in chat** (`all-chat`)
  3. **All in file** (`all-file`)

  Plus a toggle: "Make this the default for /review-as-<alias>?" If yes, write `output_default` back to PERSONA frontmatter using `persona_io.write_persona`.

  File path when used: `.review-clone/last-review-<alias>.md` in repo root.

### 6 — Emit

Format:

```
# /review-as-<alias> — <branch> vs origin/main

Snapshot: <last_scanned_at> · <N> files in scope

## <file path>
- **<severity>** — <comment in their voice>
  Citation: <comment URL>

(... more findings ...)

---

<verdict line in their voice>
```

If no findings: emit the persona's "nothing to say" line (from voice section), or default to "Nothing from me. Good to push."

---

## Mode: refresh

### 1 — Pull since last scan

```bash
python <plugin>/scripts/collect.py \
  --alias <alias> \
  --handles <handles from frontmatter> \
  --repo <repo> \
  --months <months> \
  --paths <paths> \
  --extensions <extensions> \
  --since <last_scanned_at>
```

### 2 — Pre-extract gate

Read the new snapshot.json. Display delta counts. If `new_prs > 100 OR new_comments > 200`, prompt to confirm before extracting.

### 3 — Drift detection (LLM-judged)

For each newly-derived rule:
- Compare against existing rules in PERSONA body. Look for direct contradictions ("use X" vs "use Y" on the same surface area).
- On contradiction: newer wins. Mark old rule with `superseded_by: <new rule id>`. Append drift entry via `persona_io.append_drift_entry`:

  ```python
  {"date": "<iso>", "summary": "Rule X superseded by Y", "url": "<new citation>"}
  ```

- Honor withdrawals from new comment reply threads. Don't derive from withdrawn comments.

### 4 — Update PERSONA.md

- Bump `last_scanned_at`
- Update `snapshot:` counts
- Append/modify rules
- Refresh voice patterns if new openers/quirks emerge
- Drift log auto-caps via `persona_io.append_drift_entry`

### 5 — Print delta

> Refreshed `<alias>` from `<old_scanned>` → `<new_scanned>`.
> +<N> rules · <M> superseded · <K> voice refinements

---

## Mode: chat

The user asks "would `<alias>` like <something>?" or asks for the persona's opinion on a pattern.

**Cite-or-refuse (locked decision G):**

- If you can ground the answer in a real cited rule from PERSONA body → answer in voice + cite the comment URL.
- If you cannot → answer plainly:

  > No signal in the corpus on this. `<alias>` hasn't commented on <topic> in the scanned window.

Do NOT invent opinions. The persona's silence is data.

---

## Constraints

- Never invent symbols. Pull them from the cited comment body.
- Never link a URL that isn't in PERSONA.md or the repo's existing docs.
- Never sandwich criticism with compliments unless the persona's voice section explicitly does that.
- Match the persona's severity-ladder phrasings verbatim.
```

- [ ] **Step 2: Commit**

```bash
git add plugins/review-clone/skills/review-as/SKILL.md
git commit -m "feat(review-clone): review-as skill with verification gate, refresh, chat modes"
```

---

## Phase 6 — Validation against jenbot corpus

The build prompt mandates re-creating the `jen` persona from cached `scratch/jenbot/raw/` data, comparing the result against `scratch/jenbot/analysis.md`.

### Task 15: Seed the jen persona from cached data

**Files:**
- (No new files in the plugin; this exercises the existing scripts.)

- [ ] **Step 1: Copy cached scrape to the persona dir**

```bash
mkdir -p ~/.claude/review-clone/jen/raw
cp /Users/philip.pryde/repos/pip-skills/scratch/jenbot/raw/*.json ~/.claude/review-clone/jen/raw/
cp /Users/philip.pryde/repos/pip-skills/scratch/jenbot/snapshot.json ~/.claude/review-clone/jen/snapshot.json
```

- [ ] **Step 2: Verify the persona dir is populated**

```bash
ls ~/.claude/review-clone/jen/raw/ | wc -l   # Should be >100
cat ~/.claude/review-clone/jen/snapshot.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('counts'))"
```

Expected: non-empty counts.

- [ ] **Step 3: No commit (this is local cache setup, not repo content)**

### Task 16: Manually invoke clone-reviewer skill to extract themes

This task is **interactive** — execute it yourself (the engineer) in a fresh Claude Code session.

- [ ] **Step 1: Trigger the skill**

In a fresh session at the repo root:

> /clone-reviewer
> alias: jen
> handles: jenniferjensen
> repo: wayflyer/wayflyer
> paths: frontend/, packages/
> extensions: .ts, .tsx, .css, .scss
> months: 6
> tone: copy
> authoring voice: yes
> lets-go: (paste from scratch/jenbot/analysis.md "What she lets go" section)

The skill should detect the existing `raw/` cache and **skip the collector phase**, going straight to Step 4 (pre-extract gate).

- [ ] **Step 2: Verify PERSONA.md is written**

```bash
ls -la ~/.claude/review-clone/jen/PERSONA.md
ls -la ~/.claude/commands/review-as-jen.md
```

Both should exist.

- [ ] **Step 3: Compare against analysis.md**

Manually compare the derived rules in `~/.claude/review-clone/jen/PERSONA.md` against `scratch/jenbot/analysis.md`. They should be **substantially similar** — the same major themes (YAGNI, FlyUI primitives, React Query patterns, etc.) should appear. The new framework should additionally have:

- Rules with `diff_hunk` citations in their examples (jenbot lacks these)
- Comments from reply threads marked as withdrawn where appropriate
- A `disclaimer:` line in frontmatter

If themes are missing or incorrect, refine the `clone-reviewer/SKILL.md` extraction instructions and retry.

- [ ] **Step 4: Document the validation result**

Append to the PR description (when raised in Phase 7) a section "Validation against jenbot corpus" with: number of rules derived, themes matched/missed, any notable extraction differences.

### Task 17: Smoke-test the three modes

- [ ] **Step 1: Test `review` mode**

Check out a known frontend PR locally (or a sample branch) and run:

> /review-as-jen

Expected: findings cite real comment URLs; no `Card.SuperHeader`-style fabrications; output mode selector appears once.

- [ ] **Step 2: Test `chat` mode**

> /review-as-jen chat would she like a useEffect with no deps?

Expected: either a cited answer grounded in real comments, or "No signal in the corpus on this."

- [ ] **Step 3: Test `refresh` mode (near-no-op)**

> /review-as-jen refresh

Since the cache is current (was just used), the collector should pull 0 new PRs, and the skill should report a near-empty delta. Verify `last_scanned_at` gets bumped in PERSONA.md.

- [ ] **Step 4: No commit (this is validation only)**

---

## Phase 7 — Ship

### Task 18: Add icons and finalise README

**Files:**
- Create: `plugins/review-clone/README.md` (replace placeholder)
- (Optional) Create: `plugins/review-clone/review-clone-100.png`, `review-clone-250.png` — match the pattern from `puritan-100.png`. If artwork isn't ready, ship without and add in a follow-up PR.

- [ ] **Step 1: Write the README**

```markdown
# review-clone

Clone a reviewer's voice and rules from their public GitHub review history. Every finding cites a real comment. The persona never invents APIs.

## What it does

`/clone-reviewer` → walks you through creating a persona from any GitHub reviewer's public comments.

`/review-as-<alias>` → review the current branch, refresh from new comments, or chat as the persona:
- no args → review the current branch
- `refresh` → pull comments since last scan, fold into rules
- `chat <question>` → ask the persona's opinion (cited or "no signal")

## Storage

Personas are personal and portable across repos:

```
~/.claude/review-clone/<alias>/PERSONA.md         # rules + voice
~/.claude/review-clone/<alias>/raw/               # cached scrape
~/.claude/review-clone/<alias>/snapshot.json      # provenance
~/.claude/commands/review-as-<alias>.md           # auto-registered command
```

## Requirements

- `gh` CLI authenticated (`gh auth status`)
- Python 3.11+
- Repo with `origin` set (for default repo detection at clone time)

## Limits (v1)

- Window capped at 6 months
- Pre-extract gate prompts above 100 PRs or 200 comments
- Drift log capped at 20 entries; older entries archived to `drift.log`

## Privacy

`review-clone` derives personas from **public** GitHub review comments. The cloned person is not notified. A disclaimer line is written into every PERSONA.md.
```

- [ ] **Step 2: Commit**

```bash
git add plugins/review-clone/README.md
git commit -m "docs(review-clone): finalise README"
```

### Task 19: Register the plugin in the marketplace

**Files:**
- Modify: `.claude-plugin/marketplace.json`

- [ ] **Step 1: Add the entry**

In `.claude-plugin/marketplace.json`, append to the `plugins` array (before the closing `]`):

```json
,
    {
      "name": "review-clone",
      "source": "./plugins/review-clone",
      "description": "Clone a reviewer's voice and rules from their public GitHub review history. Every finding cites a real comment; the persona never invents APIs.",
      "category": "engineering",
      "tags": ["code-review", "pr-review", "github", "persona", "voice", "review-bot"]
    }
```

Also bump the top-level `"version"` field by one minor (e.g. `1.1.1` → `1.2.0`).

- [ ] **Step 2: Verify JSON is valid**

```bash
python3 -m json.tool < .claude-plugin/marketplace.json > /dev/null
```

Expected: exit 0, no output.

- [ ] **Step 3: Commit**

```bash
git add .claude-plugin/marketplace.json
git commit -m "feat(marketplace): register review-clone plugin, bump to v1.2.0"
```

### Task 20: Run the full test suite

- [ ] **Step 1: Run all plugin tests**

```bash
cd /Users/philip.pryde/repos/pip-skills/plugins/review-clone
python -m pytest tests/ -v
```

Expected: ALL tests PASS.

- [ ] **Step 2: Manually verify the skill discovery**

Check that both skills are loadable:

```bash
ls plugins/review-clone/skills/clone-reviewer/SKILL.md
ls plugins/review-clone/skills/review-as/SKILL.md
ls plugins/review-clone/commands/clone-reviewer.md
ls plugins/review-clone/templates/review-as-command.md.tmpl
```

All exist.

### Task 21: Open the PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin review-clone
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --base main --head review-clone --title "feat(review-clone): clone a reviewer's voice from their GitHub history" --body "$(cat <<'EOF'
## Summary

Adds the `review-clone` plugin — a framework for deriving "review-as-X" personas from any GitHub reviewer's public comment history. Generalises and supersedes `scratch/jenbot/`.

- Two skills: `clone-reviewer` (conversational setup) and `review-as` (review/refresh/chat at runtime)
- Two scripts: `collect.py` (gh-scraper with diff hunks + reply threads) and `persona_io.py` (PERSONA.md frontmatter + drift log)
- Per-user storage at `~/.claude/review-clone/<alias>/` — personas portable across repos
- Per-persona slash command auto-written to `~/.claude/commands/review-as-<alias>.md`

## Locked design decisions

- Personas portable & personal-only
- Cross-repo missing-symbol rules silently skipped
- Hard cap 6-month window
- Pre-extract gate above 100 PRs or 200 comments
- Drift log capped at 20 with auto-archive
- Multi-handle conflicts: most-cited wins, losers as `also_seen`
- `chat` mode: cite or refuse
- Privacy notice non-blocking + disclaimer in PERSONA.md
- Re-clone: refresh / modify-handles / fork prompt

## Validation

Re-created the `jen` persona from cached `scratch/jenbot/raw/` data. Themes substantially match `scratch/jenbot/analysis.md`. Verification gate cleanly skips rules referencing absent symbols.

## Test plan

- [x] All pytest tests pass (`plugins/review-clone/tests/`)
- [x] `/clone-reviewer` flow walks through Q&A and writes PERSONA.md
- [x] `/review-as-jen` produces findings citing real comment URLs
- [x] `/review-as-jen chat` returns either a cited answer or "no signal in the corpus"
- [x] `/review-as-jen refresh` is a near-no-op on a current cache

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Print the PR URL in the response**

(Per user preference — always surface the PR URL in chat after creating it.)

### Task 22: Clean up scratch

**Files:**
- Delete: `scratch/jenbot/`, `scratch/reviewer-sim/`

- [ ] **Step 1: Ask the user before deleting**

Before this task, ask: "The scratch/ directories (jenbot/, reviewer-sim/) are now superseded by the merged plugin. Delete them, archive them, or keep them as historical reference?"

Default to **keeping them** — scratch/ is gitignored and harmless. Only delete on explicit user instruction.

- [ ] **Step 2 (conditional): Delete on user OK**

```bash
rm -rf scratch/jenbot scratch/reviewer-sim
```

No commit needed (scratch/ is gitignored).

---

## Self-Review Notes

This plan covers:

- ✅ Plugin scaffold (Task 1)
- ✅ PERSONA.md I/O with drift log cap + archive (Tasks 2–5)
- ✅ Collector with diff hunks + reply threads + since-mode (Tasks 6–10)
- ✅ clone-reviewer skill incl. re-clone 3-way prompt, privacy notice, pre-extract gate (Tasks 11–13)
- ✅ review-as skill with verification gate 6a/6b/6c, output-mode selector, refresh, chat (Task 14)
- ✅ Validation against jenbot corpus (Tasks 15–17)
- ✅ README + marketplace + PR (Tasks 18–21)

Locked decisions traceability:
- A (portable personas) → Task 5 `PERSONA_ROOT`
- B (silent skip cross-repo) → Task 14 Step 4 (verification gate 6a)
- C (6-month cap) → Task 6 `WINDOW_CAP_MONTHS`
- D (pre-extract gate) → Task 11 Step 4
- E (drift log cap+archive) → Task 4
- F (most-cited wins) → Task 11 Step 5
- G (chat cite-or-refuse) → Task 14 Mode: chat
- H (privacy notice + disclaimer) → Task 11 Step 2 + Step 6 (`disclaimer:` frontmatter)
- I (re-clone 3-way prompt) → Task 11 Step 0

No placeholders. No TBDs. Every code step shows the actual code; every command shows the expected output where checkable.

---

## Execution Handoff

Plan saved. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration with checkpoints.
2. **Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batched with checkpoints.

Which approach?
