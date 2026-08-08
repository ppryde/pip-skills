# Overseer Central Storage + Git-Trackable Backup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Centralise all overseer state per-repo (sprints/usage/knowledge beside `board.db`, shared by every worktree) and add explicit `backup`/`restore` that dump cards to JSON + copy text state into a committed, diffable `.overseer/backups/`, plus an `init` config flow and opt-in pre-push snapshot gate.

**Architecture:** One central per-repo folder (`$CLAUDE_CONFIG_DIR/overseer/<repo-label>/`) resolved from the canonical repo root is the single source of truth. Git never holds the live `board.db`; it holds `cards.json` (a portable projection) plus the textual sprint/usage/knowledge state, produced only by the explicit `overseer backup`. Restore rebuilds the central folder (cards upsert last-modified-wins; files fill-gaps).

**Tech Stack:** Python 3 (stdlib only — `sqlite3`, `json`, `pathlib`, `shutil`, `argparse`), pytest, bash (pre-push hook). Follows overseer's existing `scripts/*.py` + `tests/test_*.py` layout.

## Global Constraints

- Python: stdlib only for new modules (no new deps); `yaml` already a dep for sprint/knowledge parsing.
- Run tests via the plugin venv: `plugins/overseer/.venv/bin/python -m pytest` (rebuild with `python3 -m venv .venv && .venv/bin/pip install pytest pyyaml` if missing).
- Tests must not touch real `~/.claude*`: the autouse `conftest.py` fixture pins `CLAUDE_CONFIG_DIR` and `OVERSEER_DB` into `tmp_path`. New tests that exercise the central-folder resolver must set/override these via `monkeypatch`, never hardcode a home path.
- The `updated` column already exists and is stamped by every mutator — NO SQLite schema change.
- `board.db` (+ `-wal`/`-shm`) is NEVER committed. Committed artifacts are JSON/text only.
- Backups are scoped to ONE repo (by canonical repo root / label) — never read sibling repos' central folders.
- Loud-failure ethos: corrupt/unreadable backup data raises with the offending path; never silently skip.
- Commit after every task with a `feat(overseer):` / `test(overseer):` message; end messages with the repo's Co-Authored-By / Claude-Session trailers.

---

### Task 1: Central-folder resolver + config loading

Introduce a single resolver for the central state folder and the repo's backup dir, with precedence, and re-point `state_root` at it. This is the foundation every later task consumes.

**Files:**
- Create: `plugins/overseer/scripts/config.py`
- Modify: `plugins/overseer/scripts/store.py` (`state_root`), `plugins/overseer/scripts/db.py:62-72` (`_config_dir`, `board_db_path` — share resolver)
- Test: `plugins/overseer/tests/test_config.py`

**Interfaces:**
- Produces:
  - `config.repo_config_dir(repo_root: Path) -> Path` → `<canonical repo root>/.overseer`
  - `config.load_config(repo_root: Path) -> dict` → merged `config.json` (committed) over `config.local.json` (local wins), `{}` if none
  - `config.central_root(repo_root: Path) -> Path` → precedence: `OVERSEER_CENTRAL` env → `config.local.json:central_dir` → `$CLAUDE_CONFIG_DIR/overseer/<repo-label>/` (default). Uses `derive_repo_label`/`derive_repo_root` from `store.py`.
  - `config.backup_dir(repo_root: Path) -> Path` → `config.json:backup_dir` (repo-relative) → default `<canonical repo root>/.overseer/backups`
- Consumes: `store.derive_repo_root`, `store.derive_repo_label`, `store.slugify`.
- After this task `store.state_root(repo_root)` returns `config.central_root(repo_root)` (the migration importer lands in Task 2).

- [ ] **Step 1: Write the failing test**

```python
# plugins/overseer/tests/test_config.py
import json
from pathlib import Path
import pytest
from scripts import config


def _init_git(root: Path):
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)


def test_central_root_defaults_to_config_dir(tmp_path, monkeypatch):
    repo = tmp_path / "myrepo"; repo.mkdir(); _init_git(repo)
    cfgdir = tmp_path / "cfg"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfgdir))
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    got = config.central_root(repo)
    assert got == cfgdir / "overseer" / "myrepo"


def test_central_root_honours_config_local(tmp_path, monkeypatch):
    repo = tmp_path / "myrepo"; repo.mkdir(); _init_git(repo)
    (repo / ".overseer").mkdir()
    (repo / ".overseer" / "config.local.json").write_text(
        json.dumps({"central_dir": str(tmp_path / "elsewhere")})
    )
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    assert config.central_root(repo) == tmp_path / "elsewhere"


def test_central_root_env_wins(tmp_path, monkeypatch):
    repo = tmp_path / "myrepo"; repo.mkdir(); _init_git(repo)
    (repo / ".overseer").mkdir()
    (repo / ".overseer" / "config.local.json").write_text(
        json.dumps({"central_dir": str(tmp_path / "elsewhere")})
    )
    monkeypatch.setenv("OVERSEER_CENTRAL", str(tmp_path / "envwins"))
    assert config.central_root(repo) == tmp_path / "envwins"


def test_backup_dir_default(tmp_path, monkeypatch):
    repo = tmp_path / "myrepo"; repo.mkdir(); _init_git(repo)
    assert config.backup_dir(repo) == repo / ".overseer" / "backups"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `plugins/overseer/.venv/bin/python -m pytest plugins/overseer/tests/test_config.py -v` (from `plugins/overseer`, so `scripts` is importable via `pythonpath=["."]`)
Expected: FAIL — `ModuleNotFoundError: scripts.config`.

- [ ] **Step 3: Write minimal implementation**

```python
# plugins/overseer/scripts/config.py
"""Resolve overseer's per-repo central state folder and backup dir.

Precedence for the central folder:
  OVERSEER_CENTRAL env  >  config.local.json:central_dir  >  default
    ($CLAUDE_CONFIG_DIR/overseer/<repo-label>/)
The live board.db lives inside this folder; OVERSEER_DB (in db.py) still
overrides the DB *file* path for back-compat.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from scripts.store import derive_repo_label, derive_repo_root, slugify

CENTRAL_ENV = "OVERSEER_CENTRAL"
CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
REPO_CONFIG_DIRNAME = ".overseer"


def _config_dir() -> Path:
    override = os.environ.get(CONFIG_DIR_ENV)
    return Path(override) if override else Path.home() / ".claude"


def repo_config_dir(repo_root: Path) -> Path:
    root = derive_repo_root(repo_root) or repo_root
    return root / REPO_CONFIG_DIRNAME


def load_config(repo_root: Path) -> dict:
    base = repo_config_dir(repo_root)
    merged: dict = {}
    for name in ("config.json", "config.local.json"):  # local wins
        path = base / name
        if path.exists():
            try:
                merged.update(json.loads(path.read_text() or "{}"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}: malformed config JSON: {exc}") from exc
    return merged


def central_root(repo_root: Path) -> Path:
    env = os.environ.get(CENTRAL_ENV)
    if env:
        return Path(env)
    cfg = load_config(repo_root)
    if cfg.get("central_dir"):
        return Path(cfg["central_dir"])
    label = derive_repo_label(repo_root) or slugify(repo_root.resolve().name) or "repo"
    return _config_dir() / "overseer" / label


def backup_dir(repo_root: Path) -> Path:
    cfg = load_config(repo_root)
    if cfg.get("backup_dir"):
        p = Path(cfg["backup_dir"])
        root = derive_repo_root(repo_root) or repo_root
        return p if p.is_absolute() else root / p
    return repo_config_dir(repo_root) / "backups"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `plugins/overseer/.venv/bin/python -m pytest plugins/overseer/tests/test_config.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Re-point `state_root` and share the resolver in `db.py`**

In `store.py`, replace the body of `state_root` (currently `.workflow/` logic at lines 107-115) with central resolution, importing lazily to avoid a circular import (`config` imports from `store`):

```python
def state_root(repo_root: Path) -> Path:
    """Resolve the overseer state root: the central per-repo folder."""
    from scripts.config import central_root
    return central_root(repo_root)
```

In `db.py`, make `board_db_path` sit inside the central folder while keeping `OVERSEER_DB` as the file-level override:

```python
def board_db_path(repo_root: Path) -> Path:
    override = os.environ.get(DB_ENV)
    if override:
        return Path(override)
    from scripts.config import central_root
    return central_root(repo_root) / "board.db"
```

- [ ] **Step 6: Run the full overseer suite to catch fallout, fix fixtures**

Run: `plugins/overseer/.venv/bin/python -m pytest plugins/overseer -q`
Expected: some existing tests referencing the old `.workflow/` `state_root` may fail. Update those fixtures/asserts to the central path (`config.central_root(repo)` or the monkeypatched `CLAUDE_CONFIG_DIR/overseer/<label>`). Do NOT weaken assertions — repoint them. Re-run until green.

- [ ] **Step 7: Commit**

```bash
git add plugins/overseer/scripts/config.py plugins/overseer/scripts/store.py plugins/overseer/scripts/db.py plugins/overseer/tests/test_config.py plugins/overseer/tests/
git commit -m "feat(overseer): central per-repo state resolver; point state_root/board.db at it"
```

---

### Task 2: One-time `.workflow/` → central migration

Move any legacy in-repo `.workflow/` sprint/usage/knowledge/archive state into the central folder exactly once, sourced from the canonical repo root.

**Files:**
- Modify: `plugins/overseer/scripts/store.py` (add `migrate_workflow_to_central`), `plugins/overseer/scripts/db.py` (call from `connect`, guarded by a `meta` flag)
- Test: `plugins/overseer/tests/test_store.py` (extend)

**Interfaces:**
- Produces: `store.migrate_workflow_to_central(repo_root: Path) -> int` — copies files from the canonical repo's `.workflow/` tree into `central_root(repo_root)` (skipping `ledger.md` and the legacy `cards/` markdown, which the DB already imports), returns count of files copied; never overwrites an existing central file.
- Consumes: `config.central_root`, `store.derive_repo_root`.
- Guarded once via `db.get_meta(conn, "workflow_fs_imported")` set to `"1"` after first run, mirroring the existing card `_maybe_import` guard.

- [ ] **Step 1: Write the failing test**

```python
# add to plugins/overseer/tests/test_store.py
import subprocess
from pathlib import Path
from scripts import store, config


def _init_git(root): subprocess.run(["git","init","-q"], cwd=root, check=True)


def test_migrate_workflow_copies_once(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    # seed a legacy .workflow tree
    wf = repo / ".workflow"
    (wf / "sprints").mkdir(parents=True)
    (wf / "sprints" / "sprint-1.md").write_text("---\nid: sprint-1\nstatus: active\n---\n")
    (wf / "usage.jsonl").write_text('{"card":"WF-001","tokens":5}\n')
    n = store.migrate_workflow_to_central(repo)
    central = config.central_root(repo)
    assert (central / "sprints" / "sprint-1.md").exists()
    assert (central / "usage.jsonl").exists()
    assert n == 2
    # second run must not overwrite / re-copy
    (central / "usage.jsonl").write_text("LOCAL\n")
    n2 = store.migrate_workflow_to_central(repo)
    assert n2 == 0
    assert (central / "usage.jsonl").read_text() == "LOCAL\n"


def test_migrate_workflow_empty_is_noop(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    assert store.migrate_workflow_to_central(repo) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `plugins/overseer/.venv/bin/python -m pytest plugins/overseer/tests/test_store.py -k migrate -v`
Expected: FAIL — `AttributeError: module 'scripts.store' has no attribute 'migrate_workflow_to_central'`.

- [ ] **Step 3: Write minimal implementation**

```python
# in store.py
import shutil

_MIGRATE_SKIP_TOP = {"ledger.md", "cards"}  # DB owns cards; ledger.md is a view

def migrate_workflow_to_central(repo_root: Path) -> int:
    """Copy legacy .workflow/ sprint/usage/knowledge/archive state into the
    central folder, once. Never overwrites an existing central file. Sources
    from the canonical repo's .workflow/ (not a worktree's). Returns files copied."""
    from scripts.config import central_root
    source_root = (derive_repo_root(repo_root) or repo_root) / WORKFLOW_DIRNAME
    if not source_root.is_dir():
        return 0
    dest_root = central_root(repo_root)
    copied = 0
    for src in source_root.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(source_root)
        if rel.parts and rel.parts[0] in _MIGRATE_SKIP_TOP:
            continue
        dest = dest_root / rel
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied += 1
    return copied
```

- [ ] **Step 4: Run test to verify it passes**

Run: `plugins/overseer/.venv/bin/python -m pytest plugins/overseer/tests/test_store.py -k migrate -v`
Expected: PASS.

- [ ] **Step 5: Wire the guarded one-time call into `db.connect`**

In `db.py` `connect()`, after the existing card-import block, add the file-state migration behind its own meta guard:

```python
    if migrate and get_meta(conn, "workflow_fs_imported") is None:
        from scripts.store import migrate_workflow_to_central
        migrate_workflow_to_central(repo_root)
        set_meta(conn, "workflow_fs_imported", "1")
        conn.commit()
```

- [ ] **Step 6: Run full suite**

Run: `plugins/overseer/.venv/bin/python -m pytest plugins/overseer -q`
Expected: PASS (fix any connect-related fixtures that now create the extra meta key).

- [ ] **Step 7: Commit**

```bash
git add plugins/overseer/scripts/store.py plugins/overseer/scripts/db.py plugins/overseer/tests/test_store.py
git commit -m "feat(overseer): one-time .workflow/ -> central migration on connect"
```

---

### Task 3: `backup_board()` — dump to a diffable snapshot

**Files:**
- Create: `plugins/overseer/scripts/backup.py`
- Test: `plugins/overseer/tests/test_backup.py`

**Interfaces:**
- Produces:
  - `backup.SCHEMA_TABLES = ("cards", "meta")`
  - `backup.IDENTITY_META_KEYS = {"repo_root", "schema_version", "workflow_fs_imported"}`
  - `backup.backup_board(repo_root: Path, dest: Path | None = None) -> dict` — writes `cards.json`, `meta.json` (excluding `IDENTITY_META_KEYS`), copies `sprints/`, `usage.jsonl`, `knowledge/` from central, writes `manifest.json`; returns a summary dict `{"cards": int, "sprint_files": int, "fact_files": int, "usage_lines": int, "dest": str}`. Atomic (temp dir + swap). `dest` defaults to `config.backup_dir(repo_root)`.
- Consumes: `db.connect`, `db.SCHEMA_VERSION`, `config.central_root`, `config.backup_dir`.

- [ ] **Step 1: Write the failing test**

```python
# plugins/overseer/tests/test_backup.py
import json, subprocess
from pathlib import Path
import pytest
from scripts import backup, db, config


def _init_git(root): subprocess.run(["git","init","-q"], cwd=root, check=True)


def _seed(repo, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(repo.parent / "cfg"))
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    monkeypatch.delenv("OVERSEER_DB", raising=False)
    central = config.central_root(repo)
    central.mkdir(parents=True, exist_ok=True)
    conn = db.connect(repo)
    from scripts.models import Card
    conn_card = Card(id="WF-001", title="First", status="planned",
                     touches=["a.py", "b.py"], updated="2026-08-01T00:00:00")
    db.create_card(conn, conn_card)
    (central / "sprints").mkdir(exist_ok=True)
    (central / "sprints" / "sprint-1.md").write_text("---\nid: sprint-1\nstatus: active\n---\n")
    (central / "usage.jsonl").write_text('{"card":"WF-001","tokens":5}\n')
    return central


def test_backup_writes_json_and_copies_state(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    _seed(repo, monkeypatch)
    summary = backup.backup_board(repo)
    dest = config.backup_dir(repo)
    cards = json.loads((dest / "cards.json").read_text())
    assert [c["id"] for c in cards] == ["WF-001"]
    # lossless JSON column: touches copied verbatim as its stored TEXT
    assert json.loads(cards[0]["touches"]) == ["a.py", "b.py"]
    assert (dest / "sprints" / "sprint-1.md").exists()
    assert (dest / "usage.jsonl").exists()
    manifest = json.loads((dest / "manifest.json").read_text())
    assert manifest["schema_version"] == db.SCHEMA_VERSION
    assert summary["cards"] == 1


def test_backup_excludes_identity_meta(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    _seed(repo, monkeypatch)
    backup.backup_board(repo)
    meta = json.loads((config.backup_dir(repo) / "meta.json").read_text())
    keys = {m["key"] for m in meta}
    assert not (keys & backup.IDENTITY_META_KEYS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `plugins/overseer/.venv/bin/python -m pytest plugins/overseer/tests/test_backup.py -v`
Expected: FAIL — `ModuleNotFoundError: scripts.backup`.

- [ ] **Step 3: Write minimal implementation**

```python
# plugins/overseer/scripts/backup.py
"""Dump this repo's overseer board to a diffable, committed snapshot, and
restore it back. Git never holds board.db; it holds cards.json + text state."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from scripts import config, db

SCHEMA_TABLES = ("cards", "meta")
IDENTITY_META_KEYS = {"repo_root", "schema_version", "workflow_fs_imported"}
_COPY_STATE = ("sprints", "usage.jsonl", "knowledge")


def _dump_table(conn, table: str) -> list[dict]:
    rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    return [dict(r) for r in rows]


def _atomic_replace_dir(staged: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.move(str(staged), str(dest))


def backup_board(repo_root: Path, dest: Path | None = None) -> dict:
    dest = dest or config.backup_dir(repo_root)
    central = config.central_root(repo_root)
    conn = db.connect(repo_root)
    cards = _dump_table(conn, "cards")
    meta = [m for m in _dump_table(conn, "meta")
            if m["key"] not in IDENTITY_META_KEYS]

    parent = dest.parent
    parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=".overseer-bak-", dir=parent))
    (staged / "cards.json").write_text(json.dumps(cards, indent=2, sort_keys=True))
    (staged / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True))

    sprint_files = fact_files = usage_lines = 0
    for name in _COPY_STATE:
        src = central / name
        if src.is_dir():
            shutil.copytree(src, staged / name)
            count = sum(1 for _ in (staged / name).rglob("*") if _.is_file())
            if name == "sprints": sprint_files = count
            if name == "knowledge": fact_files = count
        elif src.is_file():
            shutil.copy2(src, staged / name)
            if name == "usage.jsonl":
                usage_lines = sum(1 for ln in src.read_text().splitlines() if ln.strip())

    manifest = {
        "schema_version": db.SCHEMA_VERSION,
        "repo_label": central.name,
        "cards": len(cards),
        "sprint_files": sprint_files,
        "fact_files": fact_files,
        "usage_lines": usage_lines,
    }
    (staged / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    _atomic_replace_dir(staged, dest)
    return {**{k: manifest[k] for k in ("cards", "sprint_files", "fact_files", "usage_lines")},
            "dest": str(dest)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `plugins/overseer/.venv/bin/python -m pytest plugins/overseer/tests/test_backup.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/scripts/backup.py plugins/overseer/tests/test_backup.py
git commit -m "feat(overseer): backup_board() dumps cards+state to a diffable snapshot"
```

---

### Task 4: `restore_board()` — merge a snapshot back

**Files:**
- Modify: `plugins/overseer/scripts/backup.py` (add `restore_board`)
- Test: `plugins/overseer/tests/test_backup.py` (extend)

**Interfaces:**
- Produces: `backup.restore_board(repo_root: Path, src: Path | None = None) -> dict` — schema-guarded merge. Cards upsert by `id` last-modified-wins via `updated`; meta merged excluding `IDENTITY_META_KEYS`; `sprints/`/`usage.jsonl`/`knowledge/` fill-gaps (write only if absent in central). Calls `rebuild_index`. Returns `{"inserted","updated","skipped_older","files_restored","files_skipped"}`. Raises `ValueError` on schema mismatch, missing/empty `src`, or corrupt `cards.json` (naming the file).
- Consumes: `db.connect`, `db.SCHEMA_VERSION`, `db.card_to_params`/`_upsert` pattern, `config.central_root`, `index.rebuild_index`, `models.Card`.

- [ ] **Step 1: Write the failing test**

```python
# add to plugins/overseer/tests/test_backup.py
def test_restore_roundtrip_and_lmw(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    central = _seed(repo, monkeypatch)
    backup.backup_board(repo)
    # mutate live: bump WF-001 to older-in-backup vs newer-in-db scenarios
    conn = db.connect(repo)
    from scripts.models import Card
    # a newer local edit than the backup -> restore must NOT clobber it
    db.save_card(conn, Card(id="WF-001", title="Edited later", status="in-flight",
                            updated="2026-09-01T00:00:00"))
    res = backup.restore_board(repo)
    conn = db.connect(repo)
    card = db.load_card(conn, "WF-001")
    assert card.title == "Edited later"          # local newer kept
    assert res["skipped_older"] == 1

def test_restore_inserts_missing_and_fills_files(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    central = _seed(repo, monkeypatch)
    backup.backup_board(repo)
    # wipe central entirely (simulate fresh clone / lost board)
    shutil.rmtree(central)
    res = backup.restore_board(repo)
    conn = db.connect(repo)
    assert db.load_card(conn, "WF-001") is not None
    assert (config.central_root(repo) / "sprints" / "sprint-1.md").exists()
    assert res["inserted"] == 1

def test_restore_refuses_schema_mismatch(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    _seed(repo, monkeypatch); backup.backup_board(repo)
    man = config.backup_dir(repo) / "manifest.json"
    m = json.loads(man.read_text()); m["schema_version"] = 999
    man.write_text(json.dumps(m))
    with pytest.raises(ValueError, match="schema"):
        backup.restore_board(repo)

def test_restore_corrupt_cards_is_loud(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    _seed(repo, monkeypatch); backup.backup_board(repo)
    (config.backup_dir(repo) / "cards.json").write_text("{ not json")
    with pytest.raises(ValueError, match="cards.json"):
        backup.restore_board(repo)
```

(add `import shutil` at the top of the test file if not present)

- [ ] **Step 2: Run test to verify it fails**

Run: `plugins/overseer/.venv/bin/python -m pytest plugins/overseer/tests/test_backup.py -k restore -v`
Expected: FAIL — `AttributeError: ... has no attribute 'restore_board'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to backup.py
from scripts.index import rebuild_index
from scripts.models import Card


def _iso_gt(a: str, b: str) -> bool:
    return (a or "") > (b or "")   # ISO-8601 UTC strings sort lexically


def restore_board(repo_root: Path, src: Path | None = None) -> dict:
    src = src or config.backup_dir(repo_root)
    if not src.is_dir() or not (src / "cards.json").exists():
        raise ValueError(f"no backup found at {src}")
    manifest = json.loads((src / "manifest.json").read_text())
    if manifest.get("schema_version") != db.SCHEMA_VERSION:
        raise ValueError(
            f"backup schema {manifest.get('schema_version')} != current "
            f"{db.SCHEMA_VERSION}; refusing to restore")
    try:
        rows = json.loads((src / "cards.json").read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{src / 'cards.json'}: corrupt JSON: {exc}") from exc

    central = config.central_root(repo_root)
    central.mkdir(parents=True, exist_ok=True)
    conn = db.connect(repo_root)
    inserted = updated = skipped = 0
    for row in rows:
        existing = conn.execute(
            "SELECT updated FROM cards WHERE id = ?", (row["id"],)).fetchone()
        if existing is None:
            inserted += 1
        elif _iso_gt(row.get("updated", ""), existing["updated"] or ""):
            updated += 1
        else:
            skipped += 1
            continue
        cols = ", ".join(f'"{c}"' for c in row)
        ph = ", ".join(f":{c}" for c in row)
        upd = ", ".join(f'"{c}" = excluded."{c}"' for c in row if c != "id")
        conn.execute(
            f'INSERT INTO cards ({cols}) VALUES ({ph}) '
            f'ON CONFLICT(id) DO UPDATE SET {upd}', row)
    # meta merge (skip identity keys)
    meta_path = src / "meta.json"
    if meta_path.exists():
        for m in json.loads(meta_path.read_text()):
            if m["key"] in IDENTITY_META_KEYS:
                continue
            db.set_meta(conn, m["key"], m["value"])
    conn.commit()

    files_restored = files_skipped = 0
    for name in _COPY_STATE:
        s = src / name
        if not s.exists():
            continue
        if s.is_dir():
            for f in s.rglob("*"):
                if not f.is_file():
                    continue
                target = central / name / f.relative_to(s)
                if target.exists():
                    files_skipped += 1; continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, target); files_restored += 1
        else:
            target = central / name
            if target.exists():
                files_skipped += 1
            else:
                shutil.copy2(s, target); files_restored += 1

    rebuild_index(repo_root, repo_root.resolve().name, manifest.get("created", ""))
    return {"inserted": inserted, "updated": updated, "skipped_older": skipped,
            "files_restored": files_restored, "files_skipped": files_skipped}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `plugins/overseer/.venv/bin/python -m pytest plugins/overseer/tests/test_backup.py -v`
Expected: PASS (all backup + restore tests).

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/scripts/backup.py plugins/overseer/tests/test_backup.py
git commit -m "feat(overseer): restore_board() merges snapshot (LMW cards, fill-gaps files)"
```

---

### Task 5: CLI wiring — `backup`, `restore`, interactive `init`

**Files:**
- Modify: `plugins/overseer/scripts/cli.py` (add `cmd_backup`, `cmd_restore`, extend `cmd_init`; register parsers near line 1244)
- Test: `plugins/overseer/tests/test_cli.py` (extend)

**Interfaces:**
- Consumes: `backup.backup_board`, `backup.restore_board`, `config.repo_config_dir`.
- Produces: CLI verbs `overseer backup [--dir PATH]`, `overseer restore [--dir PATH]`, and `overseer init [--central PATH] [--backup-dir PATH] [--install-hook] [--yes]` (flags make it scriptable/testable; interactive prompts fill unset values when a TTY).

- [ ] **Step 1: Write the failing test**

```python
# add to plugins/overseer/tests/test_cli.py
import json
from scripts import cli, config

def test_cli_backup_then_restore(tmp_path, monkeypatch, capsys):
    import subprocess
    repo = tmp_path / "r"; repo.mkdir()
    subprocess.run(["git","init","-q"], cwd=repo, check=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    monkeypatch.delenv("OVERSEER_DB", raising=False)
    assert cli.main(["--root", str(repo), "new-card", "--title", "T"]) == 0
    assert cli.main(["--root", str(repo), "backup"]) == 0
    assert (config.backup_dir(repo) / "cards.json").exists()
    assert cli.main(["--root", str(repo), "restore"]) == 0

def test_cli_init_writes_config(tmp_path, monkeypatch):
    import subprocess
    repo = tmp_path / "r"; repo.mkdir()
    subprocess.run(["git","init","-q"], cwd=repo, check=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    cli.main(["--root", str(repo), "init", "--yes",
              "--central", str(tmp_path / "c"), "--backup-dir", ".overseer/backups"])
    cfg = json.loads((repo / ".overseer" / "config.json").read_text())
    local = json.loads((repo / ".overseer" / "config.local.json").read_text())
    assert cfg["backup_dir"] == ".overseer/backups"
    assert local["central_dir"] == str(tmp_path / "c")
    assert ".overseer/config.local.json" in (repo / ".gitignore").read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `plugins/overseer/.venv/bin/python -m pytest plugins/overseer/tests/test_cli.py -k "backup or init_writes" -v`
Expected: FAIL — unknown verb `backup` / `init` lacks `--central`.

- [ ] **Step 3: Write minimal implementation**

Add handlers (near the other `cmd_*` funcs) and parser registration (near line 1244). Use the existing `args.root`/`_repo_root` convention the other commands use (check how `cmd_new_card` obtains `repo_root` — mirror it):

```python
def cmd_backup(args):
    from scripts import backup
    s = backup.backup_board(_root(args), Path(args.dir) if args.dir else None)
    print(f"backed up {s['cards']} cards, {s['sprint_files']} sprints, "
          f"{s['fact_files']} facts, {s['usage_lines']} usage lines -> {s['dest']}")
    return 0

def cmd_restore(args):
    from scripts import backup
    s = backup.restore_board(_root(args), Path(args.dir) if args.dir else None)
    print(f"restored: {s['inserted']} inserted, {s['updated']} updated, "
          f"{s['skipped_older']} skipped-older, {s['files_restored']} files, "
          f"{s['files_skipped']} files-present")
    return 0
```

Extend `cmd_init` to write config + gitignore (and optionally install the Task 6 hook). Use `input()` only when the corresponding flag is unset and `sys.stdin.isatty()`; with `--yes` accept defaults:

```python
def cmd_init(args):
    from scripts import config as cfg
    root = _root(args)
    base = cfg.repo_config_dir(root); base.mkdir(parents=True, exist_ok=True)
    default_central = str(cfg.central_root(root))
    central = args.central or (default_central if args.yes or not sys.stdin.isatty()
                               else input(f"Central folder [{default_central}]: ") or default_central)
    backup_dir = args.backup_dir or ".overseer/backups"
    (base / "config.json").write_text(json.dumps({"backup_dir": backup_dir}, indent=2))
    (base / "config.local.json").write_text(json.dumps({"central_dir": central}, indent=2))
    gi = root / ".gitignore"
    line = ".overseer/config.local.json"
    text = gi.read_text() if gi.exists() else ""
    if line not in text.split("\n"):
        gi.write_text(text + ("" if text.endswith("\n") or not text else "\n") + line + "\n")
    # existing init behaviour (create state dirs) still runs:
    init_workflow(root)
    if getattr(args, "install_hook", False):
        _install_prepush_hook(root)   # from Task 6
    print(f"overseer initialised: central={central} backup_dir={backup_dir}")
    return 0
```

Register parsers (near line 1244), each with `p.set_defaults(func=cmd_...)` following the file's pattern:

```python
p = add_parser("backup"); p.add_argument("--dir"); p.set_defaults(func=cmd_backup)
p = add_parser("restore"); p.add_argument("--dir"); p.set_defaults(func=cmd_restore)
# extend the existing init parser:
init_p.add_argument("--central"); init_p.add_argument("--backup-dir")
init_p.add_argument("--install-hook", action="store_true")
init_p.add_argument("--yes", action="store_true")
```

If `_root(args)` doesn't exist, add a one-line helper mirroring how existing commands resolve `Path(args.root)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `plugins/overseer/.venv/bin/python -m pytest plugins/overseer/tests/test_cli.py -v`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/scripts/cli.py plugins/overseer/tests/test_cli.py
git commit -m "feat(overseer): backup/restore CLI verbs + init config flow"
```

---

### Task 6: Pre-push snapshot hook

**Files:**
- Create: `plugins/overseer/hooks/pre-push.sh`
- Modify: `plugins/overseer/scripts/cli.py` (`_install_prepush_hook`)
- Test: `plugins/overseer/tests/test_hooks.py` (extend) — test the install logic + the re-entrant guard behaviour with a fake `git`.

**Interfaces:**
- Produces: `cli._install_prepush_hook(repo_root: Path) -> Path` — writes/chains `.git/hooks/pre-push` (resolve hooks dir via `git rev-parse --git-path hooks`), makes it executable, returns its path. The installed hook invokes `plugins/overseer/hooks/pre-push.sh`.
- The hook script: if `OVERSEER_PREPUSH_REENTRANT` is set → exit 0. Else run `overseer backup`; if `git status --porcelain .overseer/backups` shows changes → `git add .overseer/backups && git commit -m "chore(overseer): board snapshot"`, then `OVERSEER_PREPUSH_REENTRANT=1 git push "$@"` and exit 1 to abort the original.

- [ ] **Step 1: Write the failing test**

```python
# add to plugins/overseer/tests/test_hooks.py
from pathlib import Path
from scripts import cli

def test_install_prepush_hook_is_executable(tmp_path):
    import subprocess, os, stat
    repo = tmp_path / "r"; repo.mkdir()
    subprocess.run(["git","init","-q"], cwd=repo, check=True)
    path = cli._install_prepush_hook(repo)
    assert path.exists()
    assert os.stat(path).st_mode & stat.S_IXUSR
    assert "OVERSEER_PREPUSH_REENTRANT" in path.read_text() or \
           "pre-push.sh" in path.read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `plugins/overseer/.venv/bin/python -m pytest plugins/overseer/tests/test_hooks.py -k prepush -v`
Expected: FAIL — `AttributeError: _install_prepush_hook`.

- [ ] **Step 3: Write the hook script and installer**

```bash
# plugins/overseer/hooks/pre-push.sh
#!/usr/bin/env bash
set -euo pipefail
# Re-entrant guard: the snapshot re-push sets this so we don't loop.
if [ -n "${OVERSEER_PREPUSH_REENTRANT:-}" ]; then exit 0; fi
repo_root="$(git rev-parse --show-toplevel)"
python "${OVERSEER_CLI:-$repo_root/plugins/overseer/scripts/cli.py}" \
  --root "$repo_root" backup >/dev/null 2>&1 || exit 0
if [ -n "$(git -C "$repo_root" status --porcelain .overseer/backups)" ]; then
  git -C "$repo_root" add .overseer/backups
  git -C "$repo_root" commit -q -m "chore(overseer): board snapshot"
  OVERSEER_PREPUSH_REENTRANT=1 git push "$@"
  exit 1   # abort the original push; the re-push above carried the snapshot
fi
exit 0
```

```python
# in cli.py
import stat as _stat
def _install_prepush_hook(repo_root: Path) -> Path:
    import subprocess
    hooks = subprocess.run(["git","-C",str(repo_root),"rev-parse","--git-path","hooks"],
                           capture_output=True, text=True, check=True).stdout.strip()
    hooks_dir = (repo_root / hooks) if not Path(hooks).is_absolute() else Path(hooks)
    hooks_dir.mkdir(parents=True, exist_ok=True)
    target = hooks_dir / "pre-push"
    script = (Path(__file__).resolve().parent.parent / "hooks" / "pre-push.sh")
    body = f'#!/usr/bin/env bash\nexec "{script}" "$@"\n'
    target.write_text(body)
    target.chmod(target.stat().st_mode | _stat.S_IXUSR | _stat.S_IXGRP)
    return target
```

- [ ] **Step 4: Run test to verify it passes**

Run: `plugins/overseer/.venv/bin/python -m pytest plugins/overseer/tests/test_hooks.py -k prepush -v`
Expected: PASS.

- [ ] **Step 5: Mark the hook script executable in git & commit**

```bash
chmod +x plugins/overseer/hooks/pre-push.sh
git add plugins/overseer/hooks/pre-push.sh plugins/overseer/scripts/cli.py plugins/overseer/tests/test_hooks.py
git update-index --chmod=+x plugins/overseer/hooks/pre-push.sh
git commit -m "feat(overseer): opt-in pre-push board-snapshot hook"
```

---

### Task 7: Docs + version bump

**Files:**
- Modify: `plugins/overseer/README.md`, `plugins/overseer/skills/ledger/SKILL.md`, `plugins/overseer/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`

- [ ] **Step 1: Document the model**

Update `README.md` storage section: central per-repo folder holds board.db + sprints/usage/knowledge; `.workflow/` retired (one-time import); `overseer backup`/`restore` produce/consume `.overseer/backups/` (committed, diffable); `init` config + opt-in pre-push gate. Update `ledger/SKILL.md` to mention `backup`/`restore` verbs.

- [ ] **Step 2: Bump versions**

`plugins/overseer/.claude-plugin/plugin.json`: `0.11.0` → `0.12.0`.
`.claude-plugin/marketplace.json`: current → next minor.

- [ ] **Step 3: Full suite + commit**

```bash
plugins/overseer/.venv/bin/python -m pytest plugins/overseer -q
git add plugins/overseer/README.md plugins/overseer/skills/ledger/SKILL.md plugins/overseer/.claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "docs(overseer): central storage + backup/restore; bump v0.12.0"
```

---

## Self-Review notes

- **Spec coverage:** central storage (T1), migration (T2), backup (T3), restore w/ LMW + fill-gaps + schema guard + loud corrupt (T4), init config + gitignore + precedence (T1/T5), pre-push gate w/ re-entrant guard (T6), version/docs (T7). Dashboard discovery unchanged (T1 keeps default path). All spec sections mapped.
- **Type consistency:** `backup_board`/`restore_board` signatures and summary keys match between T3/T4 and the CLI in T5; `IDENTITY_META_KEYS`/`_COPY_STATE` defined once in T3 and reused in T4.
- **Verify at execution:** `_root(args)` / init parser variable name (`init_p`) must be reconciled with cli.py's actual structure during T5 — the implementer confirms the real handles before wiring.
