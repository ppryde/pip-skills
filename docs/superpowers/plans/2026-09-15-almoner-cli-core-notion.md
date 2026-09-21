# Almoner CLI — Core + Notion Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `almoner` plugin's CLI — config, SQLite store, adapter seam, gather/digest/dismiss/ack/log/status verbs — with Notion (`via: api`) as the first real source, so the existing dashboard Almoner page shows real rows.

**Architecture:** A stdlib-only sibling plugin at `plugins/almoner/`, shaped like `plugins/chronicle/` and found by the dashboard's existing `find_plugin("almoner")`. `digest` fans out to every configured source in parallel through one adapter contract (`fetch(window) -> FetchResult`), persists what came back (the store caches content and never deletes), then reads the digest back through a `--days` window applied as a SQL bound. The `awaiting` last-speaker rule and conversation collapse live in one shared `model.py` so every transport computes them identically.

**Tech Stack:** Python >= 3.11 stdlib only (`argparse`, `sqlite3`, `urllib.request`, `concurrent.futures`); pytest; ruff; mypy.

**Spec:** `docs/superpowers/specs/2026-09-13-almoner-design.md` — read it before any task. This plan argues from it.

## Global Constraints

- **Stdlib only.** The dashboard runs the CLI as `[sys.executable, cli.py, ...]`; there is no install step. No `requests`, no `httpx`.
- **Read-only against every remote system.** Only `GET` requests plus Notion's `POST /v1/search` (a read). Nothing is sent, marked read, resolved or edited.
- **Output contract** is the frontend's `AlmonerDigest` / `AlmonerStatus` / `AlmonerItem` in `plugins/overseer/dashboard/frontend/src/api/types.ts` (lines ~876-1030). Every verb prints ONE JSON object to stdout. The page's icon/label maps key on `source: "notion"`.
- **`awaiting` is strictly mechanical:** `true` iff the newest message is not the reader's; **absent** (key omitted) when the adapter cannot tell who the reader is. Absence must never manufacture urgency.
- **The store keeps everything. Nothing rolls.** `--days` (7|14|30, default 14) is a `WHERE` bound in SQL, never a post-filter in Python.
- **`--hours` (default 48) bounds what is FETCHED; `--days` bounds what is READ.** Never conflate them.
- **A failing source degrades to `ok: false` with a named `error`; it never fails the digest.** Error strings must never contain a credential.
- **Public repo:** no real person, workspace, customer, employer or account may be nameable from anything committed — tests and fixtures use invented names (e.g. "Rhona Baird", "Tomas Ek") and `example.com` / `example.invalid` addresses.
- **Config is per-machine (per Claude account):** rooted at `$CLAUDE_CONFIG_DIR/almoner/` (default `~/.claude/almoner/`), overridable with `ALMONER_HOME`. The published plugin ships no config and no sources.
- **Credentials:** one file per source label at `<home>/secrets/<label>`, mode `0600`; a missing file means "not configured" and never raises.
- **Label and context** must match `^[A-Za-z0-9][A-Za-z0-9_-]*$` (context reaches the dashboard's argv check; label becomes a filename).
- **Test isolation (repo CLAUDE.md):** every test pins `CLAUDE_CONFIG_DIR`, `ALMONER_HOME`, `ALMONER_DB` into `tmp_path` via an autouse fixture. No test touches the network or `~`.
- **Interpreter:** the worktree has no `.venv`; use `PY=/Users/philip.pryde/repos/pip-skills/.venv/bin/python`. Poetry is unusable here.
- **Gates (run from `plugins/almoner/`):** `$PY -m pytest`, `$PY -m ruff check scripts ../../tests/almoner`, `$PY -m mypy scripts`.
- Commit messages end with the attribution lines the controller gives you.

## File Structure

```
plugins/almoner/
  .claude-plugin/plugin.json      plugin manifest
  pyproject.toml                  pytest/ruff/mypy config (testpaths -> ../../tests/almoner)
  README.md                       setup: config file, Notion integration, secret file
  scripts/__init__.py
  scripts/paths.py                where config, db and secrets live (env overrides)
  scripts/config.py               Source dataclass, load_sources, read_secret
  scripts/model.py                InMessage, conversation() collapse + awaiting rule, digest_hash
  scripts/store.py                schema, connect, upsert/read_digest/state/log/watermark/run
  scripts/gather.py               Window/FetchResult/Adapter contract, parallel gather, persist
  scripts/adapters/__init__.py    registry(): (type, via) -> factory
  scripts/adapters/notion.py      Notion via:api adapter with injectable transport
  scripts/cli.py                  argparse verbs, JSON out
tests/almoner/
  __init__.py
  conftest.py                     autouse isolation fixture
  test_config.py
  test_model.py
  test_store.py
  test_gather.py
  test_notion.py
  test_cli.py
tests/run.sh                      add "almoner" to SUITES
tests/README.md                   add almoner/ to the relocated list
.claude-plugin/marketplace.json   add almoner entry, bump marketplace version
docs/superpowers/specs/2026-09-13-almoner-design.md   State of play + open question 3 settled
```

No dashboard *app* changes (one backend test file changes in Task 1 Step 6): `find_plugin("almoner")` (`plugins/overseer/dashboard/backend/app/cli_client.py`) already resolves `plugins/almoner/scripts/cli.py`, and `/api/almoner/status` + `/api/almoner/digest` already call `status` and `digest --json [--hours N] [--context C] [--new]`.

---

### Task 1: Plugin skeleton, paths, and an empty `status`

**Files:**
- Create: `plugins/almoner/.claude-plugin/plugin.json`
- Create: `plugins/almoner/pyproject.toml`
- Create: `plugins/almoner/scripts/__init__.py` (empty)
- Create: `plugins/almoner/scripts/paths.py`
- Create: `plugins/almoner/scripts/cli.py`
- Create: `tests/almoner/__init__.py` (empty), `tests/almoner/conftest.py`, `tests/almoner/test_cli.py`
- Modify: `tests/run.sh` (SUITES line), `tests/README.md` ("Currently relocated" line)

**Interfaces:**
- Produces: `paths.config_dir() -> Path`, `paths.home() -> Path`, `paths.config_path() -> Path`, `paths.db_path() -> Path`, `paths.secret_path(label: str) -> Path`; `cli.build_parser() -> argparse.ArgumentParser`; `cli.main(argv: list[str] | None = None) -> int`. Each subcommand sets `fn=<callable(args) -> int>`.

- [ ] **Step 1: Write the isolation fixture and failing tests**

`tests/almoner/conftest.py`:
```python
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_almoner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin every path almoner resolves into this test's ``tmp_path``.

    ``CLAUDE_CONFIG_DIR`` is what ``paths.home()`` derives from; ``ALMONER_HOME``
    and ``ALMONER_DB`` are pinned too so no test can read a developer's real
    source config, secrets or cached work content.
    """
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ALMONER_HOME", str(tmp_path / "config" / "almoner"))
    monkeypatch.setenv("ALMONER_DB", str(tmp_path / "config" / "almoner" / "almoner.db"))
```

`tests/almoner/test_cli.py`:
```python
import json
import os
import subprocess
import sys
from pathlib import Path

from scripts import paths
from scripts.cli import build_parser, main

PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "almoner"


class TestPaths:
    def test_home_defaults_under_the_claude_config_dir(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ALMONER_HOME")
        assert paths.home() == tmp_path / "config" / "almoner"

    def test_db_and_secrets_live_under_home(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ALMONER_DB")
        home = tmp_path / "config" / "almoner"
        assert paths.db_path() == home / "almoner.db"
        assert paths.config_path() == home / "config.json"
        assert paths.secret_path("notion") == home / "secrets" / "notion"


class TestSurface:
    def test_ships_no_hooks_and_the_spec_verbs(self):
        assert not (PLUGIN_ROOT / "hooks").exists()
        verbs = set(build_parser()._subparsers._group_actions[0].choices)  # type: ignore[union-attr]
        assert {"status", "digest", "dismiss", "ack", "log"} <= verbs


class TestStatusUnconfigured:
    def test_status_with_no_config_reports_no_sources(self, capsys):
        assert main(["status"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["sources"] == []

    def test_runs_as_a_script_the_way_the_dashboard_calls_it(self, tmp_path):
        # The dashboard runs `[sys.executable, cli.py, "status"]` from an
        # arbitrary cwd — the script must bootstrap its own import path.
        result = subprocess.run(
            [sys.executable, str(PLUGIN_ROOT / "scripts" / "cli.py"), "status"],
            capture_output=True, text=True, cwd=tmp_path, env={**os.environ}, check=False,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["sources"] == []
```

- [ ] **Step 2: Create the plugin config files**

`plugins/almoner/pyproject.toml`:
```toml
[tool.pytest.ini_options]
testpaths = ["../../tests/almoner"]
python_files = ["test_*.py"]
addopts = "-v --tb=short"
pythonpath = ["."]

[tool.ruff]
line-length = 100

[tool.mypy]
python_version = "3.11"
disallow_untyped_defs = true
warn_unused_ignores = true
ignore_missing_imports = true
```

`plugins/almoner/.claude-plugin/plugin.json`:
```json
{
  "name": "almoner",
  "version": "0.1.0",
  "description": "One triaged view of what is asking for your attention. Gathers configured sources (Notion first) read-only, collapses each conversation into one row, marks what is awaiting you by the last-speaker rule, and caches the result in a local SQLite store read through a 7/14/30-day window. The overseer dashboard grows an Almoner page when it is present.",
  "author": {
    "name": "Pip",
    "url": "https://github.com/ppryde/pip-skills"
  },
  "keywords": ["triage", "inbox", "notion", "digest", "sqlite", "dashboard"]
}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd plugins/almoner && $PY -m pytest`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.paths'` (or `scripts.cli`).

- [ ] **Step 4: Implement `paths.py` and a minimal `cli.py`**

`plugins/almoner/scripts/paths.py`:
```python
"""Where almoner keeps its config, store and credentials.

Rooted under the Claude config dir because ``CLAUDE_CONFIG_DIR`` is the account
isolation boundary on this machine (two accounts never share work content).
The source list is per-machine, not per-repo: every board shows the same digest.
"""
from __future__ import annotations

import os
from pathlib import Path

CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
HOME_ENV = "ALMONER_HOME"
DB_ENV = "ALMONER_DB"


def config_dir() -> Path:
    override = os.environ.get(CONFIG_DIR_ENV)
    return Path(override) if override else Path.home() / ".claude"


def home() -> Path:
    override = os.environ.get(HOME_ENV)
    return Path(override) if override else config_dir() / "almoner"


def config_path() -> Path:
    return home() / "config.json"


def db_path() -> Path:
    override = os.environ.get(DB_ENV)
    return Path(override) if override else home() / "almoner.db"


def secret_path(label: str) -> Path:
    return home() / "secrets" / label
```

`plugins/almoner/scripts/cli.py`:
```python
"""almoner CLI — gather configured sources into one digest, read-only.

Every verb prints one JSON object to stdout for the overseer dashboard. Pull
only: no hooks, no schedule — refresh is a person pressing Gather.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Allow `python plugins/almoner/scripts/cli.py` from anywhere.
_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from scripts import paths  # noqa: E402


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload))


def cmd_status(_: argparse.Namespace) -> int:
    _emit({"config": str(paths.config_path()), "db": str(paths.db_path()), "sources": []})
    return 0


def _not_yet(_: argparse.Namespace) -> int:
    print("almoner: not implemented yet", file=sys.stderr)
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="almoner")
    sub = parser.add_subparsers(dest="verb", required=True)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    for verb in ("digest", "dismiss", "ack", "log"):
        sub.add_parser(verb).set_defaults(fn=_not_yet)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Wire the suite into the repo runner**

In `tests/run.sh` change `SUITES=(overseer census vigil review-clone chronicle)` to `SUITES=(overseer census vigil review-clone chronicle almoner)`.
In `tests/README.md` change the "Currently relocated" line so it ends `` `chronicle/`, `almoner/`. ``

- [ ] **Step 6: Stop the dashboard's "absent" tests depending on the plugin being absent**

`plugins/overseer/dashboard/backend/tests/test_almoner.py` has two tests —
`test_status_reports_not_installed_when_the_plugin_is_absent` and
`test_digest_is_empty_rather_than_erroring_when_absent` — that relied on the plugin
genuinely not existing in the tree. Creating `plugins/almoner/scripts/cli.py` makes
`find_plugin("almoner")` resolve it, so both would now fail. Give each a
`monkeypatch: pytest.MonkeyPatch` parameter and, as its first line:
```python
    monkeypatch.setattr(main, "almoner_installed", lambda: False)
```
and replace the module docstring's second paragraph with:
```
The plugin now lives in the tree, so the "not installed" paths are simulated
by monkeypatching `almoner_installed`, the same way the installed paths are.
```

- [ ] **Step 7: Run tests, ruff, mypy**

```bash
cd plugins/almoner && $PY -m pytest && $PY -m ruff check scripts ../../tests/almoner && $PY -m mypy scripts
cd ../overseer/dashboard/backend && $PY -m pytest -q tests/test_almoner.py tests/test_plugin_discovery.py
```
Expected: 5 passed; ruff clean; mypy `Success`; backend almoner + discovery tests pass.

- [ ] **Step 8: Commit**

```bash
git add plugins/almoner tests/almoner tests/run.sh tests/README.md plugins/overseer/dashboard/backend/tests/test_almoner.py
git commit -m "feat(almoner): the plugin exists, knows where it lives, and reports no sources"
```

---

### Task 2: Source config and credentials

**Files:**
- Create: `plugins/almoner/scripts/config.py`
- Create: `tests/almoner/test_config.py`

**Interfaces:**
- Consumes: `paths.config_path()`, `paths.secret_path(label)`.
- Produces:
  - `@dataclass(frozen=True) class Source: type: str; via: str; label: str; context: str; options: dict[str, Any]` (options = every other key in the config entry, e.g. `"me"`; default empty dict).
  - `class ConfigError(Exception)` — message is safe to print.
  - `load_sources(path: Path | None = None) -> list[Source]` — missing file -> `[]`; unreadable/malformed JSON, non-list `sources`, missing `type`/`via`/`label`/`context`, bad identifier, duplicate label -> `ConfigError`.
  - `read_secret(label: str) -> str | None` — stripped file contents, `None` if missing/empty/unreadable; never raises.
  - `secret_is_private(label: str) -> bool` — `True` iff the file exists and `mode & 0o077 == 0`.
  - `IDENT_RE: re.Pattern[str]`.

- [ ] **Step 1: Write the failing tests**

`tests/almoner/test_config.py`:
```python
import json
import os

import pytest

from scripts import config, paths


def _write_config(payload) -> None:
    path = paths.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


class TestLoadSources:
    def test_missing_file_is_no_sources_not_an_error(self):
        assert config.load_sources() == []

    def test_parses_known_keys_and_keeps_the_rest_as_options(self):
        _write_config({"sources": [
            {"type": "notion", "via": "api", "label": "notion", "context": "work",
             "me": "rhona@example.com"},
        ]})
        [src] = config.load_sources()
        assert (src.type, src.via, src.label, src.context) == ("notion", "api", "notion", "work")
        assert src.options == {"me": "rhona@example.com"}

    @pytest.mark.parametrize("entry, needle", [
        ({"via": "api", "label": "n", "context": "work"}, "type"),
        ({"type": "notion", "via": "api", "label": "../etc", "context": "work"}, "label"),
        ({"type": "notion", "via": "api", "label": "n", "context": "wo rk"}, "context"),
    ])
    def test_rejects_bad_entries_by_naming_the_field(self, entry, needle):
        _write_config({"sources": [entry]})
        with pytest.raises(config.ConfigError, match=needle):
            config.load_sources()

    def test_rejects_duplicate_labels(self):
        entry = {"type": "notion", "via": "api", "label": "n", "context": "work"}
        _write_config({"sources": [entry, entry]})
        with pytest.raises(config.ConfigError, match="duplicate"):
            config.load_sources()

    def test_malformed_json_is_a_config_error(self):
        path = paths.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{nope")
        with pytest.raises(config.ConfigError, match="config"):
            config.load_sources()


class TestSecrets:
    def test_missing_secret_is_none(self):
        assert config.read_secret("notion") is None
        assert config.secret_is_private("notion") is False

    def test_reads_and_strips_a_private_secret(self):
        path = paths.secret_path("notion")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ntn_invented_token\n")
        os.chmod(path, 0o600)
        assert config.read_secret("notion") == "ntn_invented_token"
        assert config.secret_is_private("notion") is True

    def test_world_readable_secret_is_flagged(self):
        path = paths.secret_path("notion")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ntn_invented_token")
        os.chmod(path, 0o644)
        assert config.secret_is_private("notion") is False
```

- [ ] **Step 2: Run to verify failure**

Run: `cd plugins/almoner && $PY -m pytest ../../tests/almoner/test_config.py`
Expected: FAIL — `ImportError: cannot import name 'config'`.

- [ ] **Step 3: Implement `config.py`**

```python
"""The source list and its credentials.

``<home>/config.json`` holds ``{"sources": [...]}``. The published plugin ships
no file at all, so a fresh install has no sources and the page says "not
configured" rather than "nothing needs you". Swapping transport is a config
edit (``"via": "agent"`` -> ``"via": "api"``), never a refactor.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts import paths

IDENT_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]*\Z")
_REQUIRED = ("type", "via", "label", "context")


class ConfigError(Exception):
    """The config file is unusable. The message names the problem, never a secret."""


@dataclass(frozen=True)
class Source:
    type: str
    via: str
    label: str
    context: str
    options: dict[str, Any] = field(default_factory=dict)


def load_sources(path: Path | None = None) -> list[Source]:
    target = path if path is not None else paths.config_path()
    if not target.exists():
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"config {target} is not readable JSON: {exc}") from None
    entries = data.get("sources", []) if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ConfigError(f"config {target}: 'sources' must be a list")
    sources: list[Source] = []
    seen: set[str] = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ConfigError(f"config source #{i} must be an object")
        for key in _REQUIRED:
            if not isinstance(entry.get(key), str) or not entry[key]:
                raise ConfigError(f"config source #{i} is missing '{key}'")
        for key in ("label", "context"):
            if not IDENT_RE.match(entry[key]):
                raise ConfigError(f"config source #{i}: '{key}' must be a plain identifier")
        if entry["label"] in seen:
            raise ConfigError(f"config source #{i}: duplicate label '{entry['label']}'")
        seen.add(entry["label"])
        options = {k: v for k, v in entry.items() if k not in _REQUIRED}
        sources.append(Source(entry["type"], entry["via"], entry["label"], entry["context"],
                              options))
    return sources


def read_secret(label: str) -> str | None:
    try:
        value = paths.secret_path(label).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return value or None


def secret_is_private(label: str) -> bool:
    try:
        mode = paths.secret_path(label).stat().st_mode
    except OSError:
        return False
    return mode & 0o077 == 0
```

- [ ] **Step 4: Run tests, ruff, mypy** (Task 1 Step 6 command). Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add plugins/almoner/scripts/config.py tests/almoner/test_config.py
git commit -m "feat(almoner): sources come from one per-account config, secrets from 0600 files"
```

---

### Task 3: The conversation collapse and the last-speaker rule

**Files:**
- Create: `plugins/almoner/scripts/model.py`
- Create: `tests/almoner/test_model.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class InMessage: text: str; at: datetime; who: str | None = None; url: str | None = None; mine: bool | None = None` — `at` is timezone-aware; `mine=None` means "cannot tell".
  - `conversation(*, id: str, source: str, context: str, title: str, messages: list[InMessage], url: str | None = None) -> dict[str, Any]` — raises `ValueError` on an empty `messages` list.
  - `digest_hash(item: dict[str, Any]) -> str` — 16 hex chars.
  - `iso(dt: datetime) -> str`.

Rules `conversation()` implements (spec: "The item grain is a conversation", "the last-speaker rule"):
- messages sorted oldest-first by `at`; `count = len(messages)`.
- **`awaiting`**: from the newest message. `mine is None` -> omit the key. `mine is False` -> `True`. `mine is True` -> `False`.
- **`excerpt` / `who` / `arrived`**: from the newest message whose `mine is not True` (newest inbound); if every message is mine, from the newest message. Omit `who` when `None`.
- `messages` serialised oldest-first as `{"text", "at", "who"?, "url"?}` — omit `who`/`url` when `None`; never serialise `mine`.
- Always set `bundled: False`, `asks: None`, `rank: None`, `because: None`, `seen_in: [source]`; set `url` only when given.

- [ ] **Step 1: Write the failing tests**

`tests/almoner/test_model.py`:
```python
from datetime import datetime, timedelta, timezone

import pytest

from scripts.model import InMessage, conversation, digest_hash

T0 = datetime(2026, 9, 11, 18, 0, tzinfo=timezone.utc)


def _msg(minutes: int, *, mine, who="Rhona Baird", text=None):
    return InMessage(text=text or f"m{minutes}", at=T0 + timedelta(minutes=minutes),
                     who=who, mine=mine)


def _conv(messages):
    return conversation(id="notion:p1", source="notion", context="work",
                        title="Launch plan", messages=messages, url="https://example.invalid/p1")


class TestLastSpeaker:
    def test_last_message_from_someone_else_is_awaiting(self):
        assert _conv([_msg(0, mine=True), _msg(5, mine=False)])["awaiting"] is True

    def test_last_message_mine_is_not_awaiting(self):
        assert _conv([_msg(0, mine=False), _msg(5, mine=True, who="Me")])["awaiting"] is False

    def test_unknown_reader_leaves_awaiting_absent(self):
        # Absence must never manufacture urgency — the key is omitted, not False.
        assert "awaiting" not in _conv([_msg(0, mine=None)])

    def test_order_is_by_time_not_by_input(self):
        item = _conv([_msg(5, mine=True, who="Me"), _msg(0, mine=False)])
        assert item["awaiting"] is False
        assert [m["text"] for m in item["messages"]] == ["m0", "m5"]


class TestCollapse:
    def test_excerpt_who_and_arrived_come_from_newest_inbound(self):
        item = _conv([_msg(0, mine=False, text="first ask"),
                      _msg(3, mine=False, who="Tomas Ek", text="second ask"),
                      _msg(9, mine=True, who="Me", text="my answer")])
        assert item["excerpt"] == "second ask"
        assert item["who"] == "Tomas Ek"
        assert item["arrived"] == "2026-09-11T18:03:00+00:00"
        assert item["count"] == 3

    def test_all_mine_falls_back_to_newest(self):
        item = _conv([_msg(0, mine=True, who="Me", text="note to self")])
        assert item["excerpt"] == "note to self"

    def test_serialised_messages_never_carry_mine(self):
        item = _conv([_msg(0, mine=False)])
        assert item["messages"] == [{"text": "m0", "at": "2026-09-11T18:00:00+00:00",
                                     "who": "Rhona Baird"}]

    def test_unjudged_fields_are_null_and_seen_in_names_the_source(self):
        item = _conv([_msg(0, mine=False)])
        assert (item["asks"], item["rank"], item["because"], item["bundled"]) == (
            None, None, None, False)
        assert item["seen_in"] == ["notion"]
        assert item["id"] == "notion:p1" and item["url"] == "https://example.invalid/p1"

    def test_empty_conversation_is_refused(self):
        with pytest.raises(ValueError):
            _conv([])


class TestDigestHash:
    def test_stable_for_the_same_item(self):
        assert digest_hash(_conv([_msg(0, mine=False)])) == digest_hash(
            _conv([_msg(0, mine=False)]))

    def test_moves_when_a_new_message_arrives(self):
        before = digest_hash(_conv([_msg(0, mine=False)]))
        after = digest_hash(_conv([_msg(0, mine=False), _msg(4, mine=False)]))
        assert before != after and len(before) == 16
```

- [ ] **Step 2: Run to verify failure** — `$PY -m pytest ../../tests/almoner/test_model.py`. Expected: `ImportError`.

- [ ] **Step 3: Implement `model.py`**

```python
"""One row per conversation, and the rule that says whether it waits on you.

Both halves live here, shared by every adapter, so two transports for one
source (``via: agent`` and ``via: api``) cannot drift apart in behaviour.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class InMessage:
    text: str
    at: datetime
    who: str | None = None
    url: str | None = None
    # True: the reader wrote it. False: someone else did. None: cannot tell.
    mine: bool | None = None


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def conversation(*, id: str, source: str, context: str, title: str,
                 messages: list[InMessage], url: str | None = None) -> dict[str, Any]:
    if not messages:
        raise ValueError("a conversation needs at least one message")
    ordered = sorted(messages, key=lambda m: m.at)
    newest = ordered[-1]
    inbound = [m for m in ordered if m.mine is not True]
    headline = inbound[-1] if inbound else newest

    item: dict[str, Any] = {
        "id": id,
        "source": source,
        "context": context,
        "title": title,
        "excerpt": headline.text,
        "count": len(ordered),
        "messages": [_serialise(m) for m in ordered],
        "arrived": iso(headline.at),
        "bundled": False,
        "asks": None,
        "seen_in": [source],
        "rank": None,
        "because": None,
    }
    if headline.who is not None:
        item["who"] = headline.who
    if url is not None:
        item["url"] = url
    # The last-speaker rule. Unknown stays ABSENT: absence must not read as urgency.
    if newest.mine is not None:
        item["awaiting"] = newest.mine is False
    return item


def _serialise(m: InMessage) -> dict[str, Any]:
    out: dict[str, Any] = {"text": m.text, "at": iso(m.at)}
    if m.who is not None:
        out["who"] = m.who
    if m.url is not None:
        out["url"] = m.url
    return out


def digest_hash(item: dict[str, Any]) -> str:
    """Hash of what would change your mind about a dismissal.

    Dismissing means "not as it currently stands": when this moves, the row
    comes back as new.
    """
    last = (item.get("messages") or [{}])[-1]
    basis = {
        "title": item.get("title"),
        "count": item.get("count"),
        "awaiting": item.get("awaiting"),
        "last_at": last.get("at"),
        "last_text": last.get("text"),
    }
    return hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()[:16]
```

- [ ] **Step 4: Run tests, ruff, mypy.** Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add plugins/almoner/scripts/model.py tests/almoner/test_model.py
git commit -m "feat(almoner): a row is a conversation, and awaiting is the last-speaker rule"
```

---

### Task 4: The store — cache everything, read through a window

**Files:**
- Create: `plugins/almoner/scripts/store.py`
- Create: `tests/almoner/test_store.py`

**Interfaces:**
- Consumes: `paths.db_path()`, `model.digest_hash(item)`.
- Produces (all take an open `sqlite3.Connection` first; `now` is epoch seconds `float`):
  - `connect(path: Path | None = None) -> sqlite3.Connection` — creates dirs + schema, WAL, `row_factory = sqlite3.Row`.
  - `upsert_items(conn, items: list[dict[str, Any]], now: float) -> None`
  - `read_digest(conn, *, days: int, now: float, context: str | None = None, source: str | None = None, new_only: bool = False, mark_shown: bool = True) -> list[dict[str, Any]]` — marks returned rows shown only when `mark_shown` is true (a later `judge --pending` reads through the same window without side effects).
  - `set_state(conn, item_id: str, state: str, now: float) -> bool` — state in `("dismissed", "acted")`, else `ValueError`; `False` for an unknown id.
  - `record_suppressed(conn, rows: list[tuple[str, str, str]], now: float) -> None` — `(id, source, rule)`.
  - `get_watermark(conn, source: str) -> float | None`; `set_watermark(conn, source: str, fetched_at: float, cursor: str | None = None) -> None`.
  - `record_run(conn, *, started: float, finished: float, sources_ok: list[str], sources_failed: list[str], items_in: int, items_out: int) -> int`.
  - `log_runs(conn, limit: int = 20) -> dict[str, Any]` -> `{"runs": [...], "store_bytes": int}`.
  - `log_suppressed(conn, limit: int = 200) -> dict[str, Any]` -> `{"suppressed": [...]}`.
  - `STATES = ("new", "shown", "dismissed", "acted")`.

Semantics:
- `item.payload` holds the full item JSON; `read_digest` returns `json.loads(payload)`.
- `arrived_ts` = epoch of `item["arrived"]` or `NULL`. The window bound is SQL: `COALESCE(item.arrived_ts, item.gathered_at) >= ?` with `now - days*86400`; newest first by the same expression.
- `upsert_items`: for an existing `seen` row whose state is `dismissed`/`acted` and whose `digest_hash` changed -> reset `state='new'`, `state_at=now`. Always update `last_seen`, `digest_hash`; the item row is replaced (latest gather wins). New ids insert `seen(state='new', shown_count=0, first_seen=now)`.
- `read_digest` excludes `dismissed`/`acted`; `new_only` keeps `shown_count = 0`; after selecting, and only when `mark_shown` is true, increments `shown_count` and sets `state='shown'` where it was `new`.
- **Ratified 2026-09-15 (architecture):** judgements (`asks`, `rank`, `because`, …) will live in their own `judgement` table keyed `(id, digest_hash)` (Task 9, not in this plan's scope), because `upsert_items` replaces the `item` row on every gather and would wipe them. So the `item` table has **no** `asks`/`rank`/`because` columns; those fields stay only inside `payload` (as `null`) for the page contract.
- `suppressed` primary key `(id, rule)`; re-suppression updates `at`. Nothing is ever deleted from any table.

- [ ] **Step 1: Write the failing tests**

`tests/almoner/test_store.py`:
```python
from datetime import datetime, timedelta, timezone

from scripts import store
from scripts.model import InMessage, conversation

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


def _item(pid: str, *, days_ago: float, text: str = "hello", context: str = "work",
          source: str = "notion"):
    at = NOW - timedelta(days=days_ago)
    return conversation(id=f"{source}:{pid}", source=source, context=context, title=pid,
                        messages=[InMessage(text=text, at=at, who="Rhona Baird", mine=False)])


def _ids(rows):
    return [r["id"] for r in rows]


class TestWindow:
    def test_days_bound_what_is_read_and_orders_newest_first(self):
        conn = store.connect()
        store.upsert_items(conn, [_item("old", days_ago=20), _item("mid", days_ago=3),
                                  _item("new", days_ago=1)], NOW.timestamp())
        assert _ids(store.read_digest(conn, days=14, now=NOW.timestamp())) == [
            "notion:new", "notion:mid"]
        assert len(store.read_digest(conn, days=30, now=NOW.timestamp())) == 3

    def test_nothing_is_deleted_by_reading_a_narrow_window(self):
        conn = store.connect()
        store.upsert_items(conn, [_item("old", days_ago=20)], NOW.timestamp())
        store.read_digest(conn, days=7, now=NOW.timestamp())
        assert conn.execute("SELECT COUNT(*) FROM item").fetchone()[0] == 1

    def test_filters_by_context_and_source(self):
        conn = store.connect()
        store.upsert_items(conn, [_item("a", days_ago=1, context="work"),
                                  _item("b", days_ago=1, context="home")], NOW.timestamp())
        assert _ids(store.read_digest(conn, days=14, now=NOW.timestamp(), context="home")) == [
            "notion:b"]
        assert store.read_digest(conn, days=14, now=NOW.timestamp(), source="slack") == []


class TestSeen:
    def test_new_only_returns_each_row_once(self):
        conn = store.connect()
        store.upsert_items(conn, [_item("a", days_ago=1)], NOW.timestamp())
        assert len(store.read_digest(conn, days=14, now=NOW.timestamp(), new_only=True)) == 1
        assert store.read_digest(conn, days=14, now=NOW.timestamp(), new_only=True) == []
        assert len(store.read_digest(conn, days=14, now=NOW.timestamp())) == 1

    def test_reading_without_marking_leaves_rows_new(self):
        conn = store.connect()
        store.upsert_items(conn, [_item("a", days_ago=1)], NOW.timestamp())
        assert len(store.read_digest(conn, days=14, now=NOW.timestamp(), mark_shown=False)) == 1
        assert len(store.read_digest(conn, days=14, now=NOW.timestamp(), new_only=True)) == 1

    def test_dismissal_hides_until_the_item_changes(self):
        conn = store.connect()
        t = NOW.timestamp()
        store.upsert_items(conn, [_item("a", days_ago=1)], t)
        assert store.set_state(conn, "notion:a", "dismissed", t) is True
        store.upsert_items(conn, [_item("a", days_ago=1)], t + 60)  # unchanged re-fetch
        assert store.read_digest(conn, days=14, now=t) == []
        store.upsert_items(conn, [_item("a", days_ago=0.5, text="a new reply")], t + 120)
        assert _ids(store.read_digest(conn, days=14, now=t)) == ["notion:a"]

    def test_unknown_id_is_reported(self):
        conn = store.connect()
        assert store.set_state(conn, "notion:nope", "acted", NOW.timestamp()) is False


class TestBookkeeping:
    def test_watermark_round_trip(self):
        conn = store.connect()
        assert store.get_watermark(conn, "notion") is None
        store.set_watermark(conn, "notion", 123.0, cursor="c1")
        assert store.get_watermark(conn, "notion") == 123.0

    def test_runs_and_suppressed_are_logged(self):
        conn = store.connect()
        t = NOW.timestamp()
        store.record_suppressed(conn, [("notion:x", "notion", "notion:no-open-comments")], t)
        store.record_suppressed(conn, [("notion:x", "notion", "notion:no-open-comments")], t + 1)
        run_id = store.record_run(conn, started=t, finished=t + 2, sources_ok=["notion"],
                                  sources_failed=[], items_in=3, items_out=2)
        runs = store.log_runs(conn)
        assert runs["runs"][0]["id"] == run_id and runs["runs"][0]["sources_ok"] == ["notion"]
        assert runs["store_bytes"] > 0
        [row] = store.log_suppressed(conn)["suppressed"]
        assert row["rule"] == "notion:no-open-comments" and row["at"] == t + 1
```

- [ ] **Step 2: Run to verify failure** — Expected: `ImportError: cannot import name 'store'`.

- [ ] **Step 3: Implement `store.py`**

```python
"""Almoner store: one SQLite file that caches every gather and forgets nothing.

The store caches remote content (a deliberate reversal of the original
no-cache non-goal) so the page renders from the last gather and yesterday's
rows stay browsable. Retention is a VIEW: ``read_digest``'s ``days`` is a SQL
bound, and no table here is ever pruned. Growth is watched via ``log_runs``.

Judgements (asks, rank, because, topic) are deliberately NOT columns on
``item``: every gather replaces the item row, which would wipe them. They get
their own table keyed by (id, digest_hash) when the judging stage lands.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts import paths
from scripts.model import digest_hash

STATES = ("new", "shown", "dismissed", "acted")
_HIDDEN = ("dismissed", "acted")
BUSY_TIMEOUT_S = 5.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS watermark (
    source     TEXT PRIMARY KEY,
    cursor     TEXT,
    fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS seen (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    first_seen  REAL NOT NULL,
    last_seen   REAL NOT NULL,
    shown_count INTEGER NOT NULL DEFAULT 0,
    digest_hash TEXT NOT NULL,
    state       TEXT NOT NULL DEFAULT 'new',
    state_at    REAL
);
CREATE TABLE IF NOT EXISTS item (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    context     TEXT NOT NULL,
    title       TEXT,
    excerpt     TEXT,
    messages    TEXT,
    url         TEXT,
    who         TEXT,
    arrived     TEXT,
    arrived_ts  REAL,
    awaiting    INTEGER,
    gathered_at REAL NOT NULL,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS item_when ON item (COALESCE(arrived_ts, gathered_at));
CREATE TABLE IF NOT EXISTS suppressed (
    id     TEXT NOT NULL,
    source TEXT NOT NULL,
    rule   TEXT NOT NULL,
    at     REAL NOT NULL,
    PRIMARY KEY (id, rule)
);
CREATE TABLE IF NOT EXISTS run (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    started        REAL NOT NULL,
    finished       REAL NOT NULL,
    sources_ok     TEXT NOT NULL,
    sources_failed TEXT NOT NULL,
    items_in       INTEGER NOT NULL,
    items_out      INTEGER NOT NULL
);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path if path is not None else paths.db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=BUSY_TIMEOUT_S)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    return conn


def _epoch(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def upsert_items(conn: sqlite3.Connection, items: list[dict[str, Any]], now: float) -> None:
    with conn:
        for item in items:
            h = digest_hash(item)
            row = conn.execute("SELECT digest_hash, state FROM seen WHERE id = ?",
                               (item["id"],)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO seen (id, source, first_seen, last_seen, digest_hash, state)"
                    " VALUES (?, ?, ?, ?, ?, 'new')",
                    (item["id"], item["source"], now, now, h))
            elif row["state"] in _HIDDEN and row["digest_hash"] != h:
                conn.execute(
                    "UPDATE seen SET last_seen = ?, digest_hash = ?, state = 'new', state_at = ?"
                    " WHERE id = ?", (now, h, now, item["id"]))
            else:
                conn.execute("UPDATE seen SET last_seen = ?, digest_hash = ? WHERE id = ?",
                             (now, h, item["id"]))
            awaiting = item.get("awaiting")
            conn.execute(
                "INSERT OR REPLACE INTO item (id, source, context, title, excerpt, messages, url,"
                " who, arrived, arrived_ts, awaiting, gathered_at, payload)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (item["id"], item["source"], item["context"], item.get("title"),
                 item.get("excerpt"), json.dumps(item.get("messages")), item.get("url"),
                 item.get("who"), item.get("arrived"), _epoch(item.get("arrived")),
                 None if awaiting is None else int(bool(awaiting)), now, json.dumps(item)))


def read_digest(conn: sqlite3.Connection, *, days: int, now: float, context: str | None = None,
                source: str | None = None, new_only: bool = False,
                mark_shown: bool = True) -> list[dict[str, Any]]:
    # The window is a query bound, never a post-filter: see module docstring.
    sql = ("SELECT item.id, item.payload FROM item JOIN seen ON seen.id = item.id"
           " WHERE COALESCE(item.arrived_ts, item.gathered_at) >= ?"
           " AND seen.state NOT IN ('dismissed', 'acted')")
    params: list[Any] = [now - days * 86400]
    if context is not None:
        sql += " AND item.context = ?"
        params.append(context)
    if source is not None:
        sql += " AND item.source = ?"
        params.append(source)
    if new_only:
        sql += " AND seen.shown_count = 0"
    sql += " ORDER BY COALESCE(item.arrived_ts, item.gathered_at) DESC, item.id"
    rows = conn.execute(sql, params).fetchall()
    if mark_shown:
        with conn:
            conn.executemany(
                "UPDATE seen SET shown_count = shown_count + 1,"
                " state = CASE WHEN state = 'new' THEN 'shown' ELSE state END WHERE id = ?",
                [(r["id"],) for r in rows])
    return [json.loads(r["payload"]) for r in rows]


def set_state(conn: sqlite3.Connection, item_id: str, state: str, now: float) -> bool:
    if state not in _HIDDEN:
        raise ValueError(f"state must be one of {_HIDDEN}")
    with conn:
        cur = conn.execute("UPDATE seen SET state = ?, state_at = ? WHERE id = ?",
                           (state, now, item_id))
    return cur.rowcount > 0


def record_suppressed(conn: sqlite3.Connection, rows: list[tuple[str, str, str]],
                      now: float) -> None:
    with conn:
        conn.executemany(
            "INSERT INTO suppressed (id, source, rule, at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT (id, rule) DO UPDATE SET at = excluded.at",
            [(i, s, r, now) for i, s, r in rows])


def get_watermark(conn: sqlite3.Connection, source: str) -> float | None:
    row = conn.execute("SELECT fetched_at FROM watermark WHERE source = ?",
                       (source,)).fetchone()
    return None if row is None else float(row["fetched_at"])


def set_watermark(conn: sqlite3.Connection, source: str, fetched_at: float,
                  cursor: str | None = None) -> None:
    with conn:
        conn.execute(
            "INSERT INTO watermark (source, cursor, fetched_at) VALUES (?, ?, ?)"
            " ON CONFLICT (source) DO UPDATE SET cursor = excluded.cursor,"
            " fetched_at = excluded.fetched_at", (source, cursor, fetched_at))


def record_run(conn: sqlite3.Connection, *, started: float, finished: float,
               sources_ok: list[str], sources_failed: list[str], items_in: int,
               items_out: int) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO run (started, finished, sources_ok, sources_failed, items_in, items_out)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (started, finished, json.dumps(sources_ok), json.dumps(sources_failed),
             items_in, items_out))
    return int(cur.lastrowid or 0)


def log_runs(conn: sqlite3.Connection, limit: int = 20) -> dict[str, Any]:
    rows = conn.execute("SELECT * FROM run ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    page_count = conn.execute("PRAGMA page_count").fetchone()[0]
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    return {
        "runs": [{**dict(r), "sources_ok": json.loads(r["sources_ok"]),
                  "sources_failed": json.loads(r["sources_failed"])} for r in rows],
        "store_bytes": int(page_count * page_size),
    }


def log_suppressed(conn: sqlite3.Connection, limit: int = 200) -> dict[str, Any]:
    rows = conn.execute("SELECT id, source, rule, at FROM suppressed ORDER BY at DESC LIMIT ?",
                        (limit,)).fetchall()
    return {"suppressed": [dict(r) for r in rows]}
```

- [ ] **Step 4: Run tests, ruff, mypy.** Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add plugins/almoner/scripts/store.py tests/almoner/test_store.py
git commit -m "feat(almoner): a store that caches every gather and reads it through a window"
```

---

### Task 5: The adapter seam and the parallel gather

**Files:**
- Create: `plugins/almoner/scripts/gather.py`
- Create: `plugins/almoner/scripts/adapters/__init__.py`
- Create: `tests/almoner/test_gather.py`

**Interfaces:**
- Consumes: `config.Source`, `config.read_secret`, `store.*` (Task 4).
- Produces (in `gather.py`):
  - `@dataclass(frozen=True) class Window: since: datetime; until: datetime`
  - `@dataclass class FetchResult: items: list[dict[str, Any]]; suppressed: list[tuple[str, str]] = []; cursor: str | None = None` — `suppressed` entries are `(item_id, rule)`.
  - `class Adapter(Protocol): def fetch(self, window: Window) -> FetchResult: ...`
  - `class AdapterError(Exception)` — message shown in the UI; never contains a secret.
  - `AdapterFactory = Callable[[Source, str], Adapter]` — `(source, secret)`.
  - `OVERLAP_S = 3600.0`, `SOURCE_TIMEOUT_S = 40.0`
  - `fetch_window(now: float, hours: int, watermark: float | None) -> Window` — `since = now - hours*3600`, raised to `watermark - OVERLAP_S` when that is later.
  - `@dataclass class SourceReport: label, type, via, context: str; ok: bool; error: str | None = None; watermark: float | None = None; def to_json(self) -> dict[str, Any]` (omits `error` when `None`).
  - `@dataclass class GatherOutcome: items_out: int; suppressed: int; reports: list[SourceReport]`
  - `gather_and_store(conn, sources: list[Source], *, hours: int, now: float, registry: dict[tuple[str, str], AdapterFactory] | None = None, timeout: float = SOURCE_TIMEOUT_S) -> GatherOutcome`
- Produces (in `adapters/__init__.py`): `registry() -> dict[tuple[str, str], AdapterFactory]` — imports lazily. EMPTY in this task; Task 7 adds Notion.

Behaviour of `gather_and_store`:
1. Per source: no factory for `(type, via)` -> `ok=False, error="unsupported source: <type> via <via>"`. `read_secret(label)` is `None` -> `ok=False, error="no credentials"`. Otherwise build the adapter and submit `fetch(window)` to a `ThreadPoolExecutor`.
2. Wait for all futures up to `timeout` total. Unfinished -> `error="timed out"`. `AdapterError` -> `error=str(exc)`. Any other exception -> `error=f"failed: {type(exc).__name__}"` (never `str(exc)`, which could echo a URL or token). Shut the pool down with `wait=False, cancel_futures=True` so a wedged source cannot hold the digest.
3. Merge items across ok sources by `id`, unioning `seen_in` (order kept).
4. Persist on the calling thread only: `upsert_items`, `record_suppressed` (rows `(id, source.type, rule)`), `set_watermark(source.label, now, cursor)` per ok source, `record_run(...)` with `items_in = sum of result items`, `items_out = len(merged)`.
5. `SourceReport.watermark` = `now` for ok sources, else the previous watermark. Reports come back in config order.

- [ ] **Step 1: Write the failing tests**

`tests/almoner/test_gather.py`:
```python
import os
import threading
from datetime import datetime, timedelta, timezone

from scripts import gather, paths, store
from scripts.config import Source
from scripts.gather import AdapterError, FetchResult, Window
from scripts.model import InMessage, conversation

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc).timestamp()
NOTION = Source("notion", "api", "notion", "work")


def _secret(label: str) -> None:
    path = paths.secret_path(label)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("invented-token")
    os.chmod(path, 0o600)


def _item(pid: str, source: str = "notion"):
    at = datetime.fromtimestamp(NOW, timezone.utc) - timedelta(hours=1)
    return conversation(id=f"shared:{pid}", source=source, context="work", title=pid,
                        messages=[InMessage(text="hi", at=at, who="Rhona Baird", mine=False)])


class Fake:
    def __init__(self, result=None, exc=None, block: threading.Event | None = None):
        self.result, self.exc, self.block, self.windows = result, exc, block, []

    def fetch(self, window: Window) -> FetchResult:
        self.windows.append(window)
        if self.block is not None:
            self.block.wait(5)
        if self.exc is not None:
            raise self.exc
        return self.result


def _registry(fake):
    return {("notion", "api"): lambda source, secret: fake}


class TestWindow:
    def test_hours_bound_the_first_fetch(self):
        w = gather.fetch_window(NOW, 48, None)
        assert w.until.timestamp() == NOW and w.since.timestamp() == NOW - 48 * 3600

    def test_watermark_narrows_but_keeps_an_overlap(self):
        w = gather.fetch_window(NOW, 48, NOW - 600)
        assert w.since.timestamp() == NOW - 600 - gather.OVERLAP_S


class TestDegrade:
    def test_missing_credentials_names_the_source_and_fetches_nothing(self):
        conn = store.connect()
        fake = Fake(result=FetchResult(items=[]))
        out = gather.gather_and_store(conn, [NOTION], hours=48, now=NOW, registry=_registry(fake))
        [report] = out.reports
        assert (report.ok, report.error) == (False, "no credentials") and fake.windows == []

    def test_unsupported_transport_is_reported(self):
        conn = store.connect()
        src = Source("slack", "agent", "slack", "work")
        _secret("slack")
        [report] = gather.gather_and_store(conn, [src], hours=48, now=NOW, registry={}).reports
        assert report.error == "unsupported source: slack via agent"

    def test_adapter_error_is_shown_but_unexpected_errors_are_not_echoed(self):
        conn = store.connect()
        _secret("notion")
        [r1] = gather.gather_and_store(
            conn, [NOTION], hours=48, now=NOW,
            registry=_registry(Fake(exc=AdapterError("notion 401")))).reports
        [r2] = gather.gather_and_store(
            conn, [NOTION], hours=48, now=NOW,
            registry=_registry(Fake(exc=RuntimeError("token=secret")))).reports
        assert r1.error == "notion 401"
        assert r2.error == "failed: RuntimeError" and "secret" not in (r2.error or "")

    def test_a_wedged_source_times_out_without_holding_the_digest(self):
        conn = store.connect()
        _secret("notion")
        release = threading.Event()
        fake = Fake(result=FetchResult(items=[]), block=release)
        try:
            [report] = gather.gather_and_store(conn, [NOTION], hours=48, now=NOW,
                                               registry=_registry(fake), timeout=0.2).reports
        finally:
            release.set()
        assert (report.ok, report.error) == (False, "timed out")


class TestPersist:
    def test_items_suppressions_watermark_and_run_are_stored(self):
        conn = store.connect()
        _secret("notion")
        fake = Fake(result=FetchResult(items=[_item("p1")],
                                       suppressed=[("notion:p2", "notion:no-open-comments")],
                                       cursor="c"))
        out = gather.gather_and_store(conn, [NOTION], hours=48, now=NOW, registry=_registry(fake))
        assert out.items_out == 1 and out.suppressed == 1
        assert out.reports[0].ok and out.reports[0].watermark == NOW
        assert store.get_watermark(conn, "notion") == NOW
        assert [r["id"] for r in store.read_digest(conn, days=14, now=NOW)] == ["shared:p1"]
        assert store.log_runs(conn)["runs"][0]["items_out"] == 1

    def test_the_same_event_from_two_sources_is_one_row_seen_in_both(self):
        conn = store.connect()
        _secret("notion")
        _secret("notion2")
        second = Source("notion", "api", "notion2", "home")
        fakes = iter([Fake(result=FetchResult(items=[_item("p1", source="notion")])),
                      Fake(result=FetchResult(items=[_item("p1", source="mail")]))])
        registry = {("notion", "api"): lambda source, secret: next(fakes)}
        out = gather.gather_and_store(conn, [NOTION, second], hours=48, now=NOW,
                                      registry=registry)
        [row] = store.read_digest(conn, days=14, now=NOW)
        assert out.items_out == 1 and row["seen_in"] == ["notion", "mail"]
```

- [ ] **Step 2: Run to verify failure** — Expected: `ImportError: cannot import name 'gather'`.

- [ ] **Step 3: Implement `adapters/__init__.py`**

```python
"""The transport seam: (type, via) -> adapter factory.

Swapping how a source is reached is a config edit that selects a different
entry here — never a refactor of anything above this module.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scripts.gather import AdapterFactory


def registry() -> dict[tuple[str, str], "AdapterFactory"]:
    return {}
```

- [ ] **Step 4: Implement `gather.py`**

```python
"""Fan out to every configured source, degrade the ones that fail, store the rest.

A source that is unreachable, unauthorised or slow becomes ``ok: false`` with a
named error; it never fails the digest. A silently short digest is worse than a
visible error, because an empty list reads as "nothing needs you" either way.
"""
from __future__ import annotations

import sqlite3
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from scripts import store
from scripts.config import Source, read_secret

OVERLAP_S = 3600.0
SOURCE_TIMEOUT_S = 40.0


@dataclass(frozen=True)
class Window:
    since: datetime
    until: datetime


@dataclass
class FetchResult:
    items: list[dict[str, Any]]
    suppressed: list[tuple[str, str]] = field(default_factory=list)
    cursor: str | None = None


class Adapter(Protocol):
    def fetch(self, window: Window) -> FetchResult: ...


class AdapterError(Exception):
    """A source failure whose message is safe to show — never a credential."""


AdapterFactory = Callable[[Source, str], Adapter]


@dataclass
class SourceReport:
    label: str
    type: str
    via: str
    context: str
    ok: bool
    error: str | None = None
    watermark: float | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"label": self.label, "type": self.type, "via": self.via,
                               "context": self.context, "ok": self.ok,
                               "watermark": self.watermark}
        if self.error is not None:
            out["error"] = self.error
        return out


@dataclass
class GatherOutcome:
    items_out: int
    suppressed: int
    reports: list[SourceReport]


def fetch_window(now: float, hours: int, watermark: float | None) -> Window:
    # The watermark only avoids re-paging old history; the overlap catches late
    # arrivals, and `seen` dedup by id makes re-fetching them safe.
    since = now - hours * 3600
    if watermark is not None:
        since = max(since, watermark - OVERLAP_S)
    return Window(datetime.fromtimestamp(since, timezone.utc),
                  datetime.fromtimestamp(now, timezone.utc))


def _report(source: Source, ok: bool, error: str | None,
            watermark: float | None) -> SourceReport:
    return SourceReport(source.label, source.type, source.via, source.context, ok, error,
                        watermark)


def gather_and_store(conn: sqlite3.Connection, sources: list[Source], *, hours: int, now: float,
                     registry: dict[tuple[str, str], AdapterFactory] | None = None,
                     timeout: float = SOURCE_TIMEOUT_S) -> GatherOutcome:
    if registry is None:
        from scripts.adapters import registry as default_registry
        registry = default_registry()

    previous = {s.label: store.get_watermark(conn, s.label) for s in sources}
    reports: dict[str, SourceReport] = {}
    pending: dict[Future[FetchResult], Source] = {}
    done: set[Future[FetchResult]] = set()
    pool = ThreadPoolExecutor(max_workers=max(1, len(sources)))
    try:
        for source in sources:
            factory = registry.get((source.type, source.via))
            if factory is None:
                reports[source.label] = _report(
                    source, False, f"unsupported source: {source.type} via {source.via}",
                    previous[source.label])
                continue
            secret = read_secret(source.label)
            if secret is None:
                reports[source.label] = _report(source, False, "no credentials",
                                                previous[source.label])
                continue
            adapter = factory(source, secret)
            window = fetch_window(now, hours, previous[source.label])
            pending[pool.submit(adapter.fetch, window)] = source
        if pending:
            done, _ = wait(pending, timeout=timeout)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    merged: dict[str, dict[str, Any]] = {}
    suppressed: list[tuple[str, str, str]] = []
    items_in = 0
    ok_results: list[tuple[Source, FetchResult]] = []
    for future, source in pending.items():
        if future not in done:
            reports[source.label] = _report(source, False, "timed out", previous[source.label])
            continue
        exc = future.exception()
        if isinstance(exc, AdapterError):
            reports[source.label] = _report(source, False, str(exc), previous[source.label])
            continue
        if exc is not None:
            reports[source.label] = _report(source, False, f"failed: {type(exc).__name__}",
                                            previous[source.label])
            continue
        result = future.result()
        ok_results.append((source, result))
        items_in += len(result.items)
        suppressed.extend((item_id, source.type, rule) for item_id, rule in result.suppressed)
        for item in result.items:
            existing = merged.get(item["id"])
            if existing is None:
                merged[item["id"]] = item
                continue
            for name in item.get("seen_in") or []:
                if name not in existing["seen_in"]:
                    existing["seen_in"].append(name)

    store.upsert_items(conn, list(merged.values()), now)
    store.record_suppressed(conn, suppressed, now)
    for source, result in ok_results:
        store.set_watermark(conn, source.label, now, result.cursor)
        reports[source.label] = _report(source, True, None, now)
    store.record_run(conn, started=now, finished=datetime.now(timezone.utc).timestamp(),
                     sources_ok=[s.label for s, _ in ok_results],
                     sources_failed=[r.label for r in reports.values() if not r.ok],
                     items_in=items_in, items_out=len(merged))
    return GatherOutcome(len(merged), len(suppressed), [reports[s.label] for s in sources])
```

- [ ] **Step 5: Run tests, ruff, mypy.** Expected: all pass. The timeout test must return promptly after 0.2s — if it hangs ~5s, the pool is being shut down with `wait=True`.

- [ ] **Step 6: Commit**

```bash
git add plugins/almoner/scripts/gather.py plugins/almoner/scripts/adapters tests/almoner/test_gather.py
git commit -m "feat(almoner): one adapter contract, gathered in parallel, failures named not fatal"
```

---

### Task 6: The verbs — `status`, `digest`, `dismiss`, `ack`, `log`

**Files:**
- Modify: `plugins/almoner/scripts/cli.py` (full replacement below)
- Modify: `tests/almoner/test_cli.py` (append the classes below; merge imports at the top)

**Interfaces:**
- Consumes: `config.load_sources`, `config.read_secret`, `config.secret_is_private`, `config.ConfigError`, `config.IDENT_RE`, `store.*`, `gather.gather_and_store`, `gather.SourceReport`, `gather.AdapterFactory`.
- Produces the CLI surface (spec "Surface"):
  - `status` -> `{"config", "db", "sources": [{label, type, via, context, ok, watermark, error?, warnings?}]}` — **no network**. `ok` = credentials present; `error="no credentials"` when missing; `warnings=["secret file is readable by others"]` when not private. Config error -> stderr, exit 2.
  - `digest [--json] [--source LABEL] [--context C] [--hours 1..720 (48)] [--days {7,14,30} (14)] [--new]` -> `{"items", "sources", "fetched_at", "ranked": false, "suppressed", "days"}`. `--source` restricts the fetch (by label) and the read (by that source's `type`). Unknown `--source` label or config error -> stderr, exit 2 (the dashboard shows its `error` state).
  - `dismiss ID` / `ack ID` -> `{"id", "state"}` exit 0; unknown id -> `{"id", "error": "unknown id"}` exit 1.
  - `log (--runs | --suppressed) [--limit N]` -> `store.log_runs` / `store.log_suppressed` payload.
- Test seams: module-level `_REGISTRY: dict[tuple[str, str], gather.AdapterFactory] | None = None` passed to `gather_and_store`; module function `_now() -> float`. Tests monkeypatch both.

- [ ] **Step 1: Append failing tests to `tests/almoner/test_cli.py`**

Add to the imports at the top: `from datetime import datetime, timedelta, timezone`, `import pytest`, `from scripts import cli`, `from scripts.gather import FetchResult`, `from scripts.model import InMessage, conversation`. Then append:

```python
NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc).timestamp()
NOTION = {"type": "notion", "via": "api", "label": "notion", "context": "work"}


def _configure(*entries):
    path = paths.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sources": list(entries)}))


def _secret(label, mode=0o600):
    p = paths.secret_path(label)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("invented-token")
    os.chmod(p, mode)


class _Fake:
    def __init__(self, items):
        self.items = items

    def fetch(self, window):
        return FetchResult(items=self.items,
                           suppressed=[("notion:quiet", "notion:no-open-comments")])


@pytest.fixture
def fake_notion(monkeypatch):
    at = datetime.fromtimestamp(NOW, timezone.utc) - timedelta(hours=2)
    items = [conversation(id="notion:p1", source="notion", context="work", title="Launch plan",
                          messages=[InMessage(text="can you look?", at=at, who="Rhona Baird",
                                              mine=False)])]
    monkeypatch.setattr(cli, "_REGISTRY", {("notion", "api"): lambda s, secret: _Fake(items)})
    monkeypatch.setattr(cli, "_now", lambda: NOW)


def _run(capsys, *argv):
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, (json.loads(captured.out) if captured.out.strip() else None), captured.err


class TestStatus:
    def test_reports_credentials_without_fetching(self, capsys):
        _configure(NOTION)
        code, out, _ = _run(capsys, "status")
        assert code == 0
        assert out["sources"] == [{"label": "notion", "type": "notion", "via": "api",
                                   "context": "work", "ok": False, "watermark": None,
                                   "error": "no credentials"}]

    def test_warns_on_a_world_readable_secret(self, capsys):
        _configure(NOTION)
        _secret("notion", mode=0o644)
        _, out, _ = _run(capsys, "status")
        assert out["sources"][0]["ok"] is True
        assert out["sources"][0]["warnings"] == ["secret file is readable by others"]

    def test_broken_config_exits_non_zero(self, capsys):
        paths.config_path().parent.mkdir(parents=True, exist_ok=True)
        paths.config_path().write_text("{nope")
        code, out, err = _run(capsys, "status")
        assert code == 2 and out is None and "config" in err


class TestDigest:
    def test_gathers_stores_and_reads_back(self, capsys, fake_notion):
        _configure(NOTION)
        _secret("notion")
        code, out, _ = _run(capsys, "digest", "--json")
        assert code == 0
        assert [i["id"] for i in out["items"]] == ["notion:p1"]
        assert out["items"][0]["awaiting"] is True
        assert out["sources"][0]["ok"] is True
        assert (out["ranked"], out["suppressed"], out["days"], out["fetched_at"]) == (
            False, 1, 14, NOW)

    def test_new_only_shows_a_row_once(self, capsys, fake_notion):
        _configure(NOTION)
        _secret("notion")
        _, first, _ = _run(capsys, "digest", "--json", "--new")
        _, second, _ = _run(capsys, "digest", "--json", "--new")
        assert len(first["items"]) == 1 and second["items"] == []

    def test_no_sources_is_an_empty_digest_not_an_error(self, capsys, fake_notion):
        code, out, _ = _run(capsys, "digest", "--json")
        assert code == 0 and out["items"] == [] and out["sources"] == []

    def test_unknown_source_label_is_refused(self, capsys, fake_notion):
        _configure(NOTION)
        code, _, err = _run(capsys, "digest", "--json", "--source", "slack")
        assert code == 2 and "slack" in err

    @pytest.mark.parametrize("argv", [["--days", "9"], ["--hours", "0"], ["--hours", "721"]])
    def test_rejects_out_of_range_windows(self, argv):
        with pytest.raises(SystemExit):
            main(["digest", "--json", *argv])


class TestDismissAckLog:
    def test_dismiss_hides_a_row_and_ack_reports_unknown(self, capsys, fake_notion):
        _configure(NOTION)
        _secret("notion")
        _run(capsys, "digest", "--json")
        code, out, _ = _run(capsys, "dismiss", "notion:p1")
        assert (code, out) == (0, {"id": "notion:p1", "state": "dismissed"})
        code, out, _ = _run(capsys, "ack", "notion:missing")
        assert code == 1 and out["error"] == "unknown id"

    def test_log_runs_and_suppressed(self, capsys, fake_notion):
        _configure(NOTION)
        _secret("notion")
        _run(capsys, "digest", "--json")
        _, runs, _ = _run(capsys, "log", "--runs")
        _, supp, _ = _run(capsys, "log", "--suppressed")
        assert runs["runs"][0]["sources_ok"] == ["notion"] and runs["store_bytes"] > 0
        assert supp["suppressed"][0]["rule"] == "notion:no-open-comments"
```

- [ ] **Step 2: Run to verify failure** — Expected: `AttributeError` on `_REGISTRY`/`_now` and verbs exiting 2.

- [ ] **Step 3: Replace `cli.py`**

```python
"""almoner CLI — gather configured sources into one digest, read-only.

Every verb prints one JSON object to stdout for the overseer dashboard. Pull
only: no hooks, no schedule — refresh is a person pressing Gather. The CLI
fetches and pre-filters; ranking is a separate judging skill, so with no skill
behind it the digest is unranked newest-first but still usable.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

# Allow `python plugins/almoner/scripts/cli.py` from anywhere.
_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from scripts import config, gather, paths, store  # noqa: E402

# Tests swap these; production uses the adapter registry and the wall clock.
_REGISTRY: dict[tuple[str, str], gather.AdapterFactory] | None = None


def _now() -> float:
    return time.time()


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload))


def _fail(message: str) -> int:
    print(f"almoner: {message}", file=sys.stderr)
    return 2


def _sources() -> list[config.Source] | None:
    try:
        return config.load_sources()
    except config.ConfigError as exc:
        _fail(str(exc))
        return None


def cmd_status(_: argparse.Namespace) -> int:
    sources = _sources()
    if sources is None:
        return 2
    conn = store.connect()
    try:
        rows = []
        for s in sources:
            has_secret = config.read_secret(s.label) is not None
            row = gather.SourceReport(s.label, s.type, s.via, s.context, has_secret,
                                      None if has_secret else "no credentials",
                                      store.get_watermark(conn, s.label)).to_json()
            if has_secret and not config.secret_is_private(s.label):
                row["warnings"] = ["secret file is readable by others"]
            rows.append(row)
    finally:
        conn.close()
    _emit({"config": str(paths.config_path()), "db": str(paths.db_path()), "sources": rows})
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    sources = _sources()
    if sources is None:
        return 2
    read_source: str | None = None
    if args.source is not None:
        chosen = [s for s in sources if s.label == args.source]
        if not chosen:
            return _fail(f"no configured source labelled '{args.source}'")
        sources, read_source = chosen, chosen[0].type
    if args.context is not None:
        sources = [s for s in sources if s.context == args.context]
    now = _now()
    conn = store.connect()
    try:
        outcome = gather.gather_and_store(conn, sources, hours=args.hours, now=now,
                                          registry=_REGISTRY)
        items = store.read_digest(conn, days=args.days, now=now, context=args.context,
                                  source=read_source, new_only=args.new)
    finally:
        conn.close()
    _emit({"items": items, "sources": [r.to_json() for r in outcome.reports],
           "fetched_at": now, "ranked": False, "suppressed": outcome.suppressed,
           "days": args.days})
    return 0


def _set_state(item_id: str, state: str) -> int:
    conn = store.connect()
    try:
        known = store.set_state(conn, item_id, state, _now())
    finally:
        conn.close()
    if not known:
        _emit({"id": item_id, "error": "unknown id"})
        return 1
    _emit({"id": item_id, "state": state})
    return 0


def cmd_dismiss(args: argparse.Namespace) -> int:
    return _set_state(args.id, "dismissed")


def cmd_ack(args: argparse.Namespace) -> int:
    return _set_state(args.id, "acted")


def cmd_log(args: argparse.Namespace) -> int:
    conn = store.connect()
    try:
        payload = (store.log_runs(conn, args.limit) if args.runs
                   else store.log_suppressed(conn, args.limit))
    finally:
        conn.close()
    _emit(payload)
    return 0


def _hours(value: str) -> int:
    hours = int(value)
    if not 1 <= hours <= 24 * 30:
        raise argparse.ArgumentTypeError("hours must be between 1 and 720")
    return hours


def _ident(value: str) -> str:
    if not config.IDENT_RE.match(value):
        raise argparse.ArgumentTypeError("must be a plain identifier")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="almoner")
    sub = parser.add_subparsers(dest="verb", required=True)

    sub.add_parser("status", help="sources, credentials, last fetch").set_defaults(fn=cmd_status)

    digest = sub.add_parser("digest", help="gather every source, then read the digest back")
    digest.add_argument("--json", action="store_true",
                        help="accepted for the spec; output is always JSON")
    digest.add_argument("--source", type=_ident, help="one source, by label")
    digest.add_argument("--context", type=_ident, help="one context")
    digest.add_argument("--hours", type=_hours, default=48,
                        help="how far back to FETCH (default 48)")
    digest.add_argument("--days", type=int, choices=(7, 14, 30), default=14,
                        help="how far back to READ from the store (default 14)")
    digest.add_argument("--new", action="store_true", help="only rows not shown before")
    digest.set_defaults(fn=cmd_digest)

    for verb, fn, what in (("dismiss", cmd_dismiss, "hide until it changes — local only"),
                           ("ack", cmd_ack, "mark actioned — local only")):
        p = sub.add_parser(verb, help=what)
        p.add_argument("id")
        p.set_defaults(fn=fn)

    log = sub.add_parser("log", help="refresh history, or what was filtered")
    which = log.add_mutually_exclusive_group(required=True)
    which.add_argument("--runs", action="store_true")
    which.add_argument("--suppressed", action="store_true")
    log.add_argument("--limit", type=int, default=50)
    log.set_defaults(fn=cmd_log)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the whole suite, ruff, mypy.** Expected: all pass (Task 1's status tests still pass: no config means `sources: []`).

- [ ] **Step 5: Check the dashboard contract**

```bash
(cd plugins/overseer/dashboard/backend && $PY -m pytest tests/test_almoner.py tests/test_plugin_discovery.py -q)
ALMONER_HOME=$(mktemp -d) $PY plugins/almoner/scripts/cli.py digest --json
```
Expected: backend tests pass; the CLI prints `{"items": [], "sources": [], "fetched_at": ..., "ranked": false, "suppressed": 0, "days": 14}`.

- [ ] **Step 6: Commit**

```bash
git add plugins/almoner/scripts/cli.py tests/almoner/test_cli.py
git commit -m "feat(almoner): status, digest, dismiss, ack and log, all speaking the page's JSON"
```

---

### Task 7: The Notion adapter (`via: api`)

**Files:**
- Create: `plugins/almoner/scripts/adapters/notion.py`
- Modify: `plugins/almoner/scripts/adapters/__init__.py` (register it)
- Create: `tests/almoner/test_notion.py`

**Interfaces:**
- Consumes: `gather.Window`, `gather.FetchResult`, `gather.AdapterError`, `model.InMessage`, `model.conversation`, `config.Source`.
- Produces:
  - `Transport = Callable[[str, str, dict[str, Any] | None], dict[str, Any]]` — `(method, path_with_query, json_body)` -> parsed JSON; raises `AdapterError`.
  - `urllib_transport(token: str, *, timeout: float = 15.0) -> Transport`
  - `class NotionAdapter: __init__(self, source: Source, transport: Transport)`; `from_source(cls, source: Source, secret: str) -> NotionAdapter` (classmethod); `fetch(self, window: Window) -> FetchResult`.
  - Constants: `API = "https://api.notion.com/v1"`, `NOTION_VERSION = "2026-03-11"`, `MAX_PAGES = 50`.

Notion facts this adapter relies on (two are verified live in Task 8):
- `POST /v1/search` body `{"filter": {"property": "object", "value": "page"}, "sort": {"direction": "descending", "timestamp": "last_edited_time"}, "page_size": 100, "start_cursor"?}` -> `{"results": [page...], "has_more", "next_cursor"}`. A page has `id`, `url`, `last_edited_time` (ISO with `Z`), and `properties` in which one property has `"type": "title"` and `"title": [{"plain_text"}]`.
- `GET /v1/comments?block_id=<page_id>&page_size=100[&start_cursor=]` -> **unresolved** comments only: `id`, `discussion_id`, `created_time`, `created_by: {"object": "user", "id"}`, `rich_text: [{"plain_text"}]`. Needs the *read comments* capability. **Unverified:** whether inline block comments are included.
- `GET /v1/users/<id>` -> `{"name", "type", "person": {"email"}}`; `GET /v1/users` paginates all users. Needs *read user information*.
- Discussion deep link: `<page url>?d=<discussion_id>`. **Unverified live.**
- 401 bad token; 403 missing capability or page access; 429 rate limited.

Adapter behaviour:
1. **Reader identity** from `source.options["me"]`: a Notion user id, or an email (contains `@`) resolved by paging `GET /v1/users` and matching `person.email` case-insensitively. No `me`, a failed lookup, or no match -> `mine=None` on every message (so `awaiting` is absent).
2. **Pages:** page through search newest-edited first; stop at the first page with `last_edited_time < window.since`, when `has_more` is false, or once `MAX_PAGES` are collected.
3. **Per page:** list all open comments (follow `next_cursor`). None -> suppress `(f"notion:{id}", "notion:no-open-comments")`. None created at/after `window.since` -> suppress `"notion:no-new-comments"`. Otherwise emit ONE item for the page: `id=f"notion:{id}"`, `source="notion"`, `context=source.context`, `title` (or `"Untitled"`), `url=page["url"]`, messages = every open comment: `text` = joined `plain_text`, `at` = `created_time`, `who` = user name (cached per adapter; lookup failure -> `None`), `url = f"{page_url}?d={discussion_id}"`, `mine = author == me_id` or `None` when `me_id` is unknown.
4. **Errors:** 401/403/429 map to the fixed messages in `_HTTP_ERRORS`; other HTTP -> `f"notion: HTTP {code}"`; network failure -> `"notion: unreachable"`. User lookups swallow `AdapterError`; everything else propagates.
5. `FetchResult.cursor` = the first (newest) collected page's `last_edited_time`, or `None`.

- [ ] **Step 1: Write the failing tests**

`tests/almoner/test_notion.py`:
```python
from datetime import datetime, timezone

import pytest

from scripts.adapters import registry
from scripts.adapters.notion import NotionAdapter
from scripts.config import Source
from scripts.gather import AdapterError, Window

WINDOW = Window(datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc),
                datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc))
ME = "user-me"
RHONA = "user-rhona"
USERS = {ME: {"id": ME, "name": "Me", "type": "person", "person": {"email": "me@example.com"}},
         RHONA: {"id": RHONA, "name": "Rhona Baird", "type": "person",
                 "person": {"email": "rhona@example.com"}}}


def _page(pid, edited, title="Launch plan"):
    return {"object": "page", "id": pid, "url": f"https://www.notion.so/{pid}",
            "last_edited_time": edited,
            "properties": {"Name": {"type": "title", "title": [{"plain_text": title}]},
                           "Status": {"type": "select"}}}


def _comment(cid, author, created, text, discussion="d1"):
    return {"object": "comment", "id": cid, "discussion_id": discussion,
            "created_time": created, "created_by": {"object": "user", "id": author},
            "rich_text": [{"plain_text": text}]}


class FakeNotion:
    def __init__(self, pages, comments, users=None, fail=None):
        self.pages, self.comments, self.users, self.fail = pages, comments, users or {}, fail
        self.calls = []

    def __call__(self, method, path, body):
        self.calls.append((method, path, body))
        if self.fail and path.startswith(self.fail[0]):
            raise self.fail[1]
        if path == "/search":
            return {"results": self.pages, "has_more": False, "next_cursor": None}
        if path.startswith("/comments?"):
            pid = path.split("block_id=")[1].split("&")[0]
            return {"results": self.comments.get(pid, []), "has_more": False,
                    "next_cursor": None}
        if path.startswith("/users?"):
            return {"results": list(self.users.values()), "has_more": False,
                    "next_cursor": None}
        if path.startswith("/users/"):
            uid = path.split("/users/")[1]
            if uid not in self.users:
                raise AdapterError("notion: HTTP 404")
            return self.users[uid]
        raise AssertionError(f"unexpected call {method} {path}")


def _adapter(fake, **options):
    return NotionAdapter(Source("notion", "api", "notion", "work", options), fake)


class TestCollapse:
    def test_one_row_per_page_with_every_open_comment(self):
        fake = FakeNotion([_page("p1", "2026-09-15T09:00:00.000Z")], {"p1": [
            _comment("c1", RHONA, "2026-09-15T08:00:00.000Z", "can you review?"),
            _comment("c2", RHONA, "2026-09-15T08:01:00.000Z", "esp. section 2",
                     discussion="d2"),
        ]}, USERS)
        result = _adapter(fake, me=ME).fetch(WINDOW)
        [item] = result.items
        assert item["id"] == "notion:p1" and item["title"] == "Launch plan"
        assert item["count"] == 2 and item["awaiting"] is True and item["who"] == "Rhona Baird"
        assert item["messages"][1]["url"] == "https://www.notion.so/p1?d=d2"
        assert result.cursor == "2026-09-15T09:00:00.000Z"

    def test_my_reply_last_means_not_awaiting(self):
        fake = FakeNotion([_page("p1", "2026-09-15T09:00:00.000Z")], {"p1": [
            _comment("c1", RHONA, "2026-09-15T08:00:00.000Z", "can you review?"),
            _comment("c2", ME, "2026-09-15T08:30:00.000Z", "done"),
        ]}, USERS)
        assert _adapter(fake, me=ME).fetch(WINDOW).items[0]["awaiting"] is False

    def test_reader_given_as_email_is_resolved(self):
        fake = FakeNotion([_page("p1", "2026-09-15T09:00:00.000Z")], {"p1": [
            _comment("c1", ME, "2026-09-15T08:30:00.000Z", "note"),
        ]}, USERS)
        assert _adapter(fake, me="ME@example.com").fetch(WINDOW).items[0]["awaiting"] is False

    def test_without_a_reader_awaiting_is_absent(self):
        fake = FakeNotion([_page("p1", "2026-09-15T09:00:00.000Z")], {"p1": [
            _comment("c1", RHONA, "2026-09-15T08:00:00.000Z", "hello"),
        ]}, USERS)
        assert "awaiting" not in _adapter(fake).fetch(WINDOW).items[0]

    def test_unknown_author_name_degrades_to_no_who(self):
        fake = FakeNotion([_page("p1", "2026-09-15T09:00:00.000Z")], {"p1": [
            _comment("c1", "user-gone", "2026-09-15T08:00:00.000Z", "hello"),
        ]}, {})
        item = _adapter(fake).fetch(WINDOW).items[0]
        assert "who" not in item and "who" not in item["messages"][0]


class TestFilter:
    def test_pages_without_open_or_new_comments_are_suppressed_not_dropped(self):
        fake = FakeNotion([_page("p1", "2026-09-15T09:00:00.000Z"),
                           _page("p2", "2026-09-14T09:00:00.000Z")],
                          {"p2": [_comment("c1", RHONA, "2026-09-01T08:00:00.000Z", "old")]},
                          USERS)
        result = _adapter(fake, me=ME).fetch(WINDOW)
        assert result.items == []
        assert result.suppressed == [("notion:p1", "notion:no-open-comments"),
                                     ("notion:p2", "notion:no-new-comments")]

    def test_stops_paging_at_the_window_edge(self):
        fake = FakeNotion([_page("p1", "2026-09-15T09:00:00.000Z"),
                           _page("old", "2026-09-10T09:00:00.000Z")], {}, USERS)
        _adapter(fake).fetch(WINDOW)
        assert not any("block_id=old" in path for _, path, _ in fake.calls)

    def test_is_read_only(self):
        fake = FakeNotion([_page("p1", "2026-09-15T09:00:00.000Z")], {}, USERS)
        _adapter(fake, me="me@example.com").fetch(WINDOW)
        assert {(m, p) for m, p, _ in fake.calls if m != "GET"} == {("POST", "/search")}


class TestErrors:
    def test_search_failure_propagates_as_an_adapter_error(self):
        fake = FakeNotion([], {}, fail=("/search", AdapterError("notion: token rejected (401)")))
        with pytest.raises(AdapterError, match="401"):
            _adapter(fake).fetch(WINDOW)


def test_registered_under_notion_via_api():
    factory = registry()[("notion", "api")]
    adapter = factory(Source("notion", "api", "notion", "work"), "invented-token")
    assert isinstance(adapter, NotionAdapter)
```

- [ ] **Step 2: Run to verify failure** — Expected: `ModuleNotFoundError: No module named 'scripts.adapters.notion'`.

- [ ] **Step 3: Implement `adapters/notion.py`**

```python
"""Notion, reached directly with an internal integration token (``via: api``).

Notion's API has no inbox and no mentions feed, so "what is asking for you" is
rebuilt: recently edited pages the integration can see, and their open comment
threads. The grain is the PAGE — every open thread on one document is one thing
to deal with. Only pages shared with the integration are visible; anything else
is indistinguishable from quiet, which the README says plainly.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Callable

from scripts.config import Source
from scripts.gather import AdapterError, FetchResult, Window
from scripts.model import InMessage, conversation

API = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"
MAX_PAGES = 50

Transport = Callable[[str, str, "dict[str, Any] | None"], "dict[str, Any]"]

_HTTP_ERRORS = {
    401: "notion: token rejected (401)",
    403: "notion: integration lacks a capability or page access (403)",
    429: "notion: rate limited (429)",
}


def urllib_transport(token: str, *, timeout: float = 15.0) -> Transport:
    def call(method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(f"{API}{path}", data=data, method=method, headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return dict(json.loads(response.read().decode()))
        except urllib.error.HTTPError as exc:
            raise AdapterError(_HTTP_ERRORS.get(exc.code, f"notion: HTTP {exc.code}")) from None
        except (urllib.error.URLError, TimeoutError):
            raise AdapterError("notion: unreachable") from None
    return call


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _title(page: dict[str, Any]) -> str:
    for prop in (page.get("properties") or {}).values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            text = "".join(part.get("plain_text", "") for part in prop.get("title") or [])
            if text:
                return text
    return "Untitled"


class NotionAdapter:
    def __init__(self, source: Source, transport: Transport) -> None:
        self.source = source
        self.call = transport
        self._names: dict[str, str | None] = {}

    @classmethod
    def from_source(cls, source: Source, secret: str) -> "NotionAdapter":
        return cls(source, urllib_transport(secret))

    def fetch(self, window: Window) -> FetchResult:
        me = self._reader_id()
        items: list[dict[str, Any]] = []
        suppressed: list[tuple[str, str]] = []
        pages = self._recent_pages(window)
        for page in pages:
            item_id = f"notion:{page['id']}"
            comments = self._open_comments(page["id"])
            if not comments:
                suppressed.append((item_id, "notion:no-open-comments"))
                continue
            if all(_parse(c["created_time"]) < window.since for c in comments):
                suppressed.append((item_id, "notion:no-new-comments"))
                continue
            items.append(conversation(
                id=item_id, source="notion", context=self.source.context, title=_title(page),
                url=page["url"], messages=[self._message(page, c, me) for c in comments]))
        cursor = pages[0]["last_edited_time"] if pages else None
        return FetchResult(items=items, suppressed=suppressed, cursor=cursor)

    def _recent_pages(self, window: Window) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {
                "filter": {"property": "object", "value": "page"},
                "sort": {"direction": "descending", "timestamp": "last_edited_time"},
                "page_size": 100,
            }
            if cursor:
                body["start_cursor"] = cursor
            response = self.call("POST", "/search", body)
            for page in response.get("results") or []:
                if _parse(page["last_edited_time"]) < window.since:
                    return pages
                pages.append(page)
                if len(pages) >= MAX_PAGES:
                    return pages
            if not response.get("has_more"):
                return pages
            cursor = response.get("next_cursor")

    def _open_comments(self, page_id: str) -> list[dict[str, Any]]:
        comments: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            query = {"block_id": page_id, "page_size": "100"}
            if cursor:
                query["start_cursor"] = cursor
            response = self.call("GET", f"/comments?{urllib.parse.urlencode(query)}", None)
            comments.extend(response.get("results") or [])
            if not response.get("has_more"):
                return comments
            cursor = response.get("next_cursor")

    def _reader_id(self) -> str | None:
        me = self.source.options.get("me")
        if not isinstance(me, str) or not me:
            return None
        if "@" not in me:
            return me
        cursor: str | None = None
        while True:
            query = {"page_size": "100"}
            if cursor:
                query["start_cursor"] = cursor
            try:
                response = self.call("GET", f"/users?{urllib.parse.urlencode(query)}", None)
            except AdapterError:
                return None
            for user in response.get("results") or []:
                email = ((user.get("person") or {}).get("email") or "").lower()
                if email == me.lower():
                    return str(user["id"])
            if not response.get("has_more"):
                return None
            cursor = response.get("next_cursor")

    def _name(self, user_id: str) -> str | None:
        if user_id not in self._names:
            try:
                self._names[user_id] = self.call("GET", f"/users/{user_id}", None).get("name")
            except AdapterError:
                self._names[user_id] = None
        return self._names[user_id]

    def _message(self, page: dict[str, Any], comment: dict[str, Any],
                 me: str | None) -> InMessage:
        author = (comment.get("created_by") or {}).get("id", "")
        return InMessage(
            text="".join(part.get("plain_text", "") for part in comment.get("rich_text") or []),
            at=_parse(comment["created_time"]),
            who=self._name(author) if author else None,
            url=f"{page['url']}?d={comment['discussion_id']}",
            mine=None if me is None else author == me,
        )
```

- [ ] **Step 4: Register it**

Replace `registry()` in `plugins/almoner/scripts/adapters/__init__.py`:
```python
def registry() -> dict[tuple[str, str], "AdapterFactory"]:
    from scripts.adapters.notion import NotionAdapter

    return {("notion", "api"): NotionAdapter.from_source}
```

- [ ] **Step 5: Run the whole suite, ruff, mypy.** Expected: all pass (`test_cli.py` monkeypatches `_REGISTRY`, so it never reaches the network).

- [ ] **Step 6: Commit**

```bash
git add plugins/almoner/scripts/adapters tests/almoner/test_notion.py
git commit -m "feat(almoner): Notion as the first source — pages with open threads, read-only"
```

---

### Task 8: Ship it — README, marketplace, spec

**Files:**
- Create: `plugins/almoner/README.md`
- Modify: `.claude-plugin/marketplace.json` (add entry after `chronicle`; bump the top-level `"version"` minor — read the current value first, e.g. `1.30.0` -> `1.31.0`)
- Modify: `docs/superpowers/specs/2026-09-13-almoner-design.md`

**Interfaces:** none new.

- [ ] **Step 1: Write `plugins/almoner/README.md`** with exactly these sections (invented names only):

~~~markdown
# almoner

One triaged view of what is asking for your attention, on the overseer
dashboard's Almoner page. Read-only against every source: nothing is sent,
marked read, resolved or edited.

## Verbs

    almoner status                     sources, credentials, last fetch (no network)
    almoner digest --json              gather every source, then read the digest back
    almoner digest --source notion     one source, by label
    almoner digest --context work      one context
    almoner digest --hours 72          how far back to FETCH (default 48)
    almoner digest --days 30           how far back to READ (7|14|30, default 14)
    almoner digest --new               only rows not shown before
    almoner dismiss <id>               hide until it changes — local only
    almoner ack <id>                   mark actioned — local only
    almoner log --runs | --suppressed  refresh history, or what was filtered and why

## Configure (per machine, per Claude account)

Everything lives in `$CLAUDE_CONFIG_DIR/almoner/` (default `~/.claude/almoner/`):

    config.json         {"sources": [...]}
    secrets/<label>     one credential per source, chmod 600
    almoner.db          the store — caches every gather, never pruned

The plugin ships no sources: until you add one the page says "not configured".

## Notion (`type: notion`, `via: api`)

1. Create an **internal integration** at https://www.notion.so/profile/integrations
   with *Read content*, *Read comments* and *Read user information including email
   addresses*. A work workspace's admin may need to allow this.
2. Save its secret to `$CLAUDE_CONFIG_DIR/almoner/secrets/notion` and `chmod 600` it.
3. Share the pages or teamspaces you care about with the integration (page ⋯ → Connections).
   **Pages not shared with it are invisible, and invisible looks the same as quiet.**
4. Add the source, with `me` set to your Notion email (or user id) so `awaiting` can be computed:

       {"sources": [{"type": "notion", "via": "api", "label": "notion",
                     "context": "work", "me": "you@example.com"}]}

5. `almoner status` should show the source `ok: true`.

What it reads: recently edited pages and their **open** comment threads — one row per
page. Notion's API has no inbox or mentions feed, so a resolved thread is gone and an
@-mention outside a comment is not seen.
~~~

- [ ] **Step 2: Add the marketplace entry** after the `chronicle` object, matching neighbours' formatting:

```json
{
  "name": "almoner",
  "source": "./plugins/almoner",
  "description": "One triaged view of what is asking for your attention. Gathers configured sources (Notion first) read-only, collapses each conversation into one row, marks what awaits you by the last-speaker rule, and caches every gather in a local SQLite store read through a 7/14/30-day window. The overseer dashboard grows an Almoner page when it is present.",
  "category": "engineering",
  "tags": ["triage", "inbox", "notion", "digest", "sqlite", "dashboard"]
}
```
Validate: `$PY -c "import json; json.load(open('.claude-plugin/marketplace.json'))"`.

- [ ] **Step 3: Update the spec**

- The `**Status:**` line -> `**Status:** CLI core + Notion source built (plan 2026-09-15-almoner-cli-core-notion); Slack, Linear and mail adapters, the judging skill and POST /dismiss unbuilt.`
- "State of play": move the CLI, store, dismiss/ack and the history read out of **Unbuilt** into a new **Built (2026-09-15)** paragraph; leave in Unbuilt: Slack/Linear/mail adapters, the judging skill, `POST /api/almoner/dismiss`, a `days` passthrough on `GET /api/almoner/digest`.
- Open question 3 -> `3. ~~**Is the source list per-machine or per-repo?**~~ **Settled 2026-09-15: per machine, rooted per Claude account at `$CLAUDE_CONFIG_DIR/almoner/`.**`
- Under "The transport seam", note Notion is reachable directly by internal integration token, needing no connector.
- Add a **"Judging (ratified 2026-09-15)"** section after "CLI and skill", recording, as design not yet built:
  - Two stages: gather (CLI, deterministic) then judge (the `almoner:judge` skill), which processes only items whose `digest_hash` differs from the hash they were last judged at.
  - Boundary: the agent never touches SQLite. `almoner judge --pending [--limit N]` is a pure read (never marks rows shown) returning unjudged/changed items plus a feedback block of the reader's recent dismissals and acks (capped at 20; title, source, asks — no bodies). `almoner judge --apply FILE|-` validates per item against a fixed schema; each judgement echoes `digest_hash`, and a stale one is rejected.
  - Store: `judgement` table keyed `(id, digest_hash)`, history kept, latest `judged_at` wins; `rollup(key, title, excerpt, judged_at)`. Judgements are not columns on `item`, because each gather replaces the item row.
  - Judgement fields: `asks`, `rank`, `because`, `topic` (free-text label for v1), `for_reader`, `fold_into`, `attributed`.
  - `for_reader` **demotes only**: row state is `bundled` > (`awaiting === true` && `for_reader !== false`) > reconcile > fyi. Mechanical `awaiting` is never overwritten.
  - **The agent cannot hide rows.** Its only tools for noise are `fold_into` (a disclosed rollup) and `for_reader: false`.
  - Safety gate in code: a keyword list (sign-in, password, login/verification code, reset, bank, payment, invoice, card, credential, currency marks); a keyword-hit item without an explicit `attributed: true` has its `fold_into` rejected per item.
  - Rollup validation: every member is an accepted item in the same batch; `excerpt` non-empty and not equal to `title`; the read shows the rollup as one `bundled: true` row, members not repeated at top level.
  - **v1 is interactive-only** (run the skill in a session). Connector lookups during judging are allowed, read-only, only for rows otherwise ambiguous. A dashboard Judge button (headless `claude -p`, inheriting `CLAUDE_CONFIG_DIR`) is a later task.
- Add `almoner judge --pending | --apply FILE` and `almoner digest --cached` to the Surface block, marked *(unbuilt)*.

- [ ] **Step 4: Full gates**

```bash
(cd plugins/almoner && $PY -m pytest -q && $PY -m ruff check scripts ../../tests/almoner && $PY -m mypy scripts)
(cd plugins/overseer/dashboard/backend && $PY -m pytest -q tests/test_almoner.py tests/test_plugin_discovery.py)
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add plugins/almoner/README.md .claude-plugin/marketplace.json docs/superpowers/specs/2026-09-13-almoner-design.md docs/superpowers/plans/2026-09-15-almoner-cli-core-notion.md
git commit -m "docs(almoner): how to point it at Notion, and the spec's state of play"
```

---

### After the tasks: live smoke test (controller with the owner — not a subagent)

Needs the owner's real integration token; nothing produced here is committed.

1. Owner completes the README "Notion" steps under their real `$CLAUDE_CONFIG_DIR`.
2. `$PY plugins/almoner/scripts/cli.py status` -> source `ok: true`, no warnings.
3. `$PY plugins/almoner/scripts/cli.py digest --json --hours 168` -> `sources[0].ok` is `true`; rows for shared pages with open comments; `log --suppressed` accounts for the rest.
4. Verify the two unconfirmed API facts: (a) an *inline* comment on a block inside a shared page appears in that page's row — if not, record it in the spec as a known gap (inline threads need a per-block walk, deferred); (b) a message link with `?d=<discussion_id>` opens that thread.
5. Restart the dashboard; the Almoner coin appears and the page renders the rows.

---

## Next plan (not in this one)

The ratified judging stage (spec "Judging") is planned separately once Task 8 lands:
Task 9 `judgement`/`rollup` tables + `judge --pending` / `judge --apply` + `digest --cached` + safety gate;
Task 10 the `almoner:judge` skill (interactive-only);
Task 11 backend `cached=1` and `days` passthrough on `GET /api/almoner/digest`, and page rendering of `topic`, `asks` chips, rollups and the judged-at stamp.
