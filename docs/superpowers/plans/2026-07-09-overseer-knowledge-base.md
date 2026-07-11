# Overseer Phase 4 — Living Knowledge Base Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give overseer a durable, per-fact-dated knowledge base — facts minted from agent reports, injected into dispatches, staled by age, and retired when refuted — living under the phase-3 state root.

**Architecture:** A new `scripts/knowledge.py` module owns the KB end-to-end: a `Fact` dataclass (frontmatter parse/serialise, mirroring `Card`), filesystem ops (mint id, load/save, quarantine), staleness computation, and index regeneration. Four CLI commands (`add-fact`, `verify-fact`, `retire-fact`, `facts`) are the single writer. Doctrine edits wire `{{knowledge}}` into the dispatch templates and describe the mint/verify/retire lifecycle. The KB reuses phase-3's `state_root` resolver — it has no resolver of its own.

**Tech Stack:** Python 3.9+, dataclasses, PyYAML, argparse, pytest, ruff, mypy. Run from `plugins/overseer/`. Builds on `feat/overseer-orchestration` at 51e3aec.

## Global Constraints

- Python target: 3.9+ (`from __future__ import annotations` at the top of every module).
- Single writer: only `cli.py` writes under the state root; the `facts` read command may quarantine corrupt files (same as `resume`/`load_live_cards` today) but performs no other writes.
- KB home: `<state-root>/knowledge/`, where `<state-root>` comes from `scripts.store.state_root(repo_root)` (phase 3). No new resolver, no marker file.
- KB layout: `knowledge/facts/KB-nnn-slug.md`, `knowledge/retired/`, `knowledge/corrupt/`, `knowledge/knowledge.md` (regenerated index — a view; facts are truth).
- Fact ids are minted sequentially `KB-nnn` (3-digit zero-pad, like `WF-nnn`).
- Fact statuses: `active | stale | retired` (`FACT_STATUSES`). Staleness threshold: 90 days on the `verified` date, applied at index regeneration; `verify-fact` un-stales.
- Retirement never deletes: retired facts move to `knowledge/retired/`, keeping `superseded_by`.
- Corrupt fact files quarantine to `knowledge/corrupt/` with a loud stderr report — never silently skipped or overwritten (mirror `store.quarantine`).
- TDD throughout: failing test → watch it fail → minimal code → watch it pass → commit. Frequent focused commits.
- Gate command (poetry is unusable here — the plugin pyproject is tool-config only). From `plugins/overseer/`, using the worktree venv at `/Users/philip.pryde/repos/pip-skills/.claude/worktrees/overseer-orchestration/.venv`:
  - Tests: `.venv/bin/python -m pytest -q`
  - Ruff: `.venv/bin/ruff check scripts tests`
  - Mypy: `.venv/bin/mypy scripts` (strict: `disallow_untyped_defs = true` — every def fully annotated)
- Apply the phase-3 lesson: parse defensively — a scalar `tags:` value must not explode into characters (isinstance guard).
- Neutral, technical code and commits. Witchfinder persona is chat-only, never in committed artefacts.
- Baseline before Task 1: 151 tests passing, ruff + mypy clean.

---

## File Structure

**Created:**
- `scripts/knowledge.py` — the whole KB: `Fact` dataclass, `knowledge_root`, paths, `mint_fact_id`, load/save, `load_facts`/`load_retired` (+ quarantine), `is_stale`, `generate_knowledge_index`, `rebuild_knowledge_index`, `retire_fact_file`.
- `tests/test_knowledge.py` — unit tests for the module.

**Modified:**
- `scripts/cli.py` — import KB helpers; add `cmd_add_fact`, `cmd_verify_fact`, `cmd_retire_fact`, `cmd_facts`; register the four sub-parsers.
- `tests/test_cli.py` — CLI-level tests for the four commands.
- `templates/planner.md`, `templates/implementer.md`, `templates/reviewer.md`, `templates/fixer.md`, `templates/sprint-reviewer.md` — add `{{knowledge}}` input + a "Learned" report line.
- `skills/ledger/SKILL.md`, `skills/orchestrate/SKILL.md` — KB lifecycle doctrine.
- `plugins/overseer/README.md`, `plugins/overseer/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` — docs + version bump.

---

### Task 1: Fact dataclass

**Files:**
- Create: `scripts/knowledge.py`
- Test: `tests/test_knowledge.py`

**Interfaces:**
- Consumes: `split_frontmatter`, `CardParseError` from `scripts.models`.
- Produces:
  - `FACT_STATUSES = {"active", "stale", "retired"}`
  - `class FactParseError(ValueError)`
  - `class Fact` with fields `id: str`, `statement: str`, `tags: list[str]`, `source: str | None`, `created: str`, `verified: str`, `status: str = "active"`, `superseded_by: str | None`, `body: str`.
  - `Fact.from_text(text: str) -> Fact`, `Fact.to_text() -> str` (round-trip).
  - `is_stale(verified: str, today: str, max_age_days: int = 90) -> bool`
  - `Fact.effective_status(today: str) -> str` — `"stale"` if `status == "active"` and stale by date, else `status`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_knowledge.py`:

```python
import pytest

from scripts.knowledge import Fact, FactParseError, is_stale


def make_fact(fact_id: str = "KB-001", **overrides: object) -> Fact:
    fields = dict(
        id=fact_id,
        statement="The auth fixtures share a DB schema",
        tags=["testing", "auth"],
        source="WF-012",
        created="2026-07-09",
        verified="2026-07-09",
        status="active",
        body="Fuller story.",
    )
    fields.update(overrides)
    return Fact(**fields)  # type: ignore[arg-type]


class TestFactParse:
    def test_round_trip(self):
        fact = make_fact()
        parsed = Fact.from_text(fact.to_text())
        assert parsed == fact

    def test_missing_statement_raises(self):
        with pytest.raises(FactParseError):
            Fact.from_text("---\nid: KB-001\nstatus: active\n---\nx")

    def test_bad_status_raises(self):
        with pytest.raises(FactParseError):
            Fact.from_text(
                "---\nid: KB-001\nstatement: x\nstatus: bogus\n---\ny"
            )

    def test_scalar_tags_not_exploded(self):
        text = (
            "---\nid: KB-002\nstatement: x\nstatus: active\n"
            "tags: testing\n---\n\nbody\n"
        )
        assert Fact.from_text(text).tags == ["testing"]

    def test_absent_tags_default_empty(self):
        text = "---\nid: KB-003\nstatement: x\nstatus: active\n---\n\nbody\n"
        assert Fact.from_text(text).tags == []


class TestStaleness:
    def test_fresh_is_not_stale(self):
        assert is_stale("2026-07-09", "2026-07-10") is False

    def test_old_is_stale(self):
        assert is_stale("2026-01-01", "2026-07-09") is True

    def test_exactly_90_days_not_stale(self):
        assert is_stale("2026-01-01", "2026-04-01") is False  # 90 days exactly

    def test_unparseable_is_not_stale(self):
        assert is_stale("", "2026-07-09") is False
        assert is_stale("garbage", "2026-07-09") is False

    def test_effective_status_flags_stale_active(self):
        fact = make_fact(status="active", verified="2026-01-01")
        assert fact.effective_status("2026-07-09") == "stale"

    def test_effective_status_leaves_retired(self):
        fact = make_fact(status="retired", verified="2026-01-01")
        assert fact.effective_status("2026-07-09") == "retired"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_knowledge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.knowledge'`.

- [ ] **Step 3: Implement the model**

Create `scripts/knowledge.py`:

```python
"""Knowledge base: Fact parse/serialise, staleness, store ops, index."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import yaml

from scripts.models import split_frontmatter

FACT_STATUSES = {"active", "stale", "retired"}
STALE_DAYS = 90


class FactParseError(ValueError):
    """A fact file that cannot be parsed or fails validation."""


def is_stale(verified: str, today: str, max_age_days: int = STALE_DAYS) -> bool:
    if not verified:
        return False
    try:
        v = datetime.strptime(verified[:10], "%Y-%m-%d")
        t = datetime.strptime(today[:10], "%Y-%m-%d")
    except ValueError:
        return False
    return (t - v).days > max_age_days


@dataclass
class Fact:
    """One falsifiable statement with provenance and a verification date."""

    id: str
    statement: str
    tags: list[str] = field(default_factory=list)
    source: str | None = None
    created: str = ""
    verified: str = ""
    status: str = "active"
    superseded_by: str | None = None
    body: str = ""

    @classmethod
    def from_text(cls, text: str) -> "Fact":
        meta, body = split_frontmatter(text)
        for key in ("id", "statement"):
            if not meta.get(key):
                raise FactParseError(f"missing required field: {key}")
        status = str(meta.get("status", "active"))
        if status not in FACT_STATUSES:
            raise FactParseError(f"unknown status: {status!r}")
        tags_raw = meta.get("tags")
        if isinstance(tags_raw, list):
            tags = [str(t) for t in tags_raw]
        elif tags_raw:
            tags = [str(tags_raw)]
        else:
            tags = []
        return cls(
            id=str(meta["id"]),
            statement=str(meta["statement"]),
            tags=tags,
            source=meta.get("source"),
            created=str(meta.get("created", "")),
            verified=str(meta.get("verified", "")),
            status=status,
            superseded_by=meta.get("superseded_by"),
            body=body.strip(),
        )

    def to_text(self) -> str:
        meta = {
            "id": self.id,
            "statement": self.statement,
            "tags": self.tags or None,
            "source": self.source,
            "created": self.created,
            "verified": self.verified,
            "status": self.status,
            "superseded_by": self.superseded_by,
        }
        front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
        return f"---\n{front}\n---\n\n{self.body.strip()}\n"

    def effective_status(self, today: str) -> str:
        if self.status == "active" and is_stale(self.verified, today):
            return "stale"
        return self.status
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_knowledge.py -v`
Expected: PASS (all `TestFactParse` and `TestStaleness` cases).

- [ ] **Step 5: Gates + commit**

```bash
.venv/bin/python -m pytest && .venv/bin/ruff check scripts tests && .venv/bin/mypy scripts
git add scripts/knowledge.py tests/test_knowledge.py
git commit -m "feat(overseer): Fact model with staleness computation"
```

---

### Task 2: KB store operations

**Files:**
- Modify: `scripts/knowledge.py`
- Test: `tests/test_knowledge.py`

**Interfaces:**
- Consumes: `Fact`, `FactParseError` (Task 1); `state_root`, `slugify`, `_uniquify` from `scripts.store`.
- Produces:
  - `knowledge_root(repo_root: Path) -> Path` → `state_root(repo_root) / "knowledge"`
  - `ensure_kb(kb: Path) -> None` — creates `facts/`, `retired/`, `corrupt/`
  - `mint_fact_id(kb: Path) -> str` — next `KB-nnn` across `facts/` and `retired/`
  - `fact_path(kb: Path, fact: Fact) -> Path`, `find_fact_path(kb: Path, fact_id: str) -> Path`
  - `load_fact(path: Path) -> Fact`, `save_fact(kb: Path, fact: Fact) -> Path`
  - `quarantine_fact(kb: Path, path: Path) -> Path`
  - `load_facts(kb: Path) -> tuple[list[Fact], list[Path]]` (live = `facts/`; quarantines corrupt)
  - `load_retired(kb: Path) -> list[Fact]`
  - `retire_fact_file(kb: Path, fact: Fact) -> Path` — writes to `retired/`, unlinks from `facts/`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_knowledge.py` (add imports at top: `from pathlib import Path` and the new names):

```python
from scripts.knowledge import (
    ensure_kb,
    find_fact_path,
    knowledge_root,
    load_facts,
    load_retired,
    mint_fact_id,
    retire_fact_file,
    save_fact,
)


@pytest.fixture
def kb(tmp_path):
    root = tmp_path / "knowledge"
    ensure_kb(root)
    return root


class TestStoreOps:
    def test_ensure_creates_dirs(self, tmp_path):
        root = tmp_path / "knowledge"
        ensure_kb(root)
        for sub in ("facts", "retired", "corrupt"):
            assert (root / sub).is_dir()

    def test_mint_first_id(self, kb):
        assert mint_fact_id(kb) == "KB-001"

    def test_mint_skips_facts_and_retired(self, kb):
        save_fact(kb, make_fact("KB-004"))
        retire_fact_file(kb, make_fact("KB-007", status="retired"))
        assert mint_fact_id(kb) == "KB-008"

    def test_save_and_find(self, kb):
        save_fact(kb, make_fact("KB-001", statement="Serial tests only"))
        path = find_fact_path(kb, "KB-001")
        assert path.name.startswith("KB-001-")
        assert path.parent == kb / "facts"

    def test_find_missing_raises(self, kb):
        with pytest.raises(FileNotFoundError):
            find_fact_path(kb, "KB-999")

    def test_load_facts_sorted_and_quarantines_corrupt(self, kb):
        save_fact(kb, make_fact("KB-002", statement="B"))
        save_fact(kb, make_fact("KB-001", statement="A"))
        bad = kb / "facts" / "KB-003-broken.md"
        bad.write_text("no frontmatter here")
        facts, quarantined = load_facts(kb)
        assert [f.id for f in facts] == ["KB-001", "KB-002"]
        assert quarantined == [kb / "corrupt" / "KB-003-broken.md"]
        assert not bad.exists()
        assert (kb / "corrupt" / "KB-003-broken.md").read_text() == "no frontmatter here"

    def test_retire_moves_file(self, kb):
        save_fact(kb, make_fact("KB-001"))
        fact = make_fact("KB-001", status="retired", superseded_by="KB-002")
        retire_fact_file(kb, fact)
        assert not list((kb / "facts").glob("KB-001-*"))
        retired = load_retired(kb)
        assert [f.id for f in retired] == ["KB-001"]
        assert retired[0].superseded_by == "KB-002"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_knowledge.py::TestStoreOps -v`
Expected: FAIL — `ImportError: cannot import name 'ensure_kb'`.

- [ ] **Step 3: Implement the store ops**

Add to the imports at the top of `scripts/knowledge.py`:

```python
import re
from pathlib import Path

from scripts.store import _uniquify, slugify, state_root
```

Add the constant near `STALE_DAYS`:

```python
_MINTED_FACT_RE = re.compile(r"\AKB-(\d+)-")
```

Append to `scripts/knowledge.py`:

```python
def knowledge_root(repo_root: Path) -> Path:
    return state_root(repo_root) / "knowledge"


def ensure_kb(kb: Path) -> None:
    for sub in ("facts", "retired", "corrupt"):
        (kb / sub).mkdir(parents=True, exist_ok=True)


def mint_fact_id(kb: Path) -> str:
    highest = 0
    for directory in (kb / "facts", kb / "retired"):
        for path in directory.glob("KB-*.md"):
            match = _MINTED_FACT_RE.match(path.name)
            if match:
                highest = max(highest, int(match.group(1)))
    return f"KB-{highest + 1:03d}"


def fact_path(kb: Path, fact: Fact) -> Path:
    return kb / "facts" / f"{fact.id}-{slugify(fact.statement)}.md"


def find_fact_path(kb: Path, fact_id: str) -> Path:
    matches = sorted((kb / "facts").glob(f"{fact_id}-*.md"))
    if not matches:
        raise FileNotFoundError(f"no live fact with id {fact_id}")
    return matches[0]


def load_fact(path: Path) -> Fact:
    try:
        return Fact.from_text(path.read_text())
    except FactParseError as exc:
        raise FactParseError(f"{path.name}: {exc}") from exc


def save_fact(kb: Path, fact: Fact) -> Path:
    path = fact_path(kb, fact)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fact.to_text())
    return path


def quarantine_fact(kb: Path, path: Path) -> Path:
    target = _uniquify(kb / "corrupt" / path.name)
    target.parent.mkdir(parents=True, exist_ok=True)
    path.rename(target)
    return target


def load_facts(kb: Path) -> tuple[list[Fact], list[Path]]:
    facts: list[Fact] = []
    quarantined: list[Path] = []
    for path in sorted((kb / "facts").glob("*.md")):
        try:
            facts.append(load_fact(path))
        except FactParseError:
            quarantined.append(quarantine_fact(kb, path))
    facts.sort(key=lambda f: f.id)
    return facts, quarantined


def load_retired(kb: Path) -> list[Fact]:
    facts = []
    for path in (kb / "retired").glob("*.md"):
        try:
            facts.append(Fact.from_text(path.read_text()))
        except FactParseError:
            continue
    return sorted(facts, key=lambda f: f.id)


def retire_fact_file(kb: Path, fact: Fact) -> Path:
    target = _uniquify(kb / "retired" / f"{fact.id}-{slugify(fact.statement)}.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(fact.to_text())
    live = fact_path(kb, fact)
    if live.exists():
        live.unlink()
    return target
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_knowledge.py -v`
Expected: PASS.

- [ ] **Step 5: Gates + commit**

```bash
.venv/bin/python -m pytest && .venv/bin/ruff check scripts tests && .venv/bin/mypy scripts
git add scripts/knowledge.py tests/test_knowledge.py
git commit -m "feat(overseer): knowledge store ops (mint, save, load, quarantine, retire)"
```

---

### Task 3: Index generation with staleness persistence

**Files:**
- Modify: `scripts/knowledge.py`
- Test: `tests/test_knowledge.py`

**Interfaces:**
- Consumes: everything from Tasks 1–2.
- Produces:
  - `generate_knowledge_index(facts: list[Fact], retired: list[Fact], now: str) -> str`
  - `rebuild_knowledge_index(repo_root: Path, today: str) -> list[Path]` — loads live facts, persists `active → stale` flips, writes `knowledge.md`, returns quarantined paths.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_knowledge.py`:

```python
from scripts.knowledge import generate_knowledge_index, rebuild_knowledge_index


class TestIndex:
    def test_generate_lists_active_and_stale_and_counts_retired(self):
        active = make_fact("KB-001", statement="Alpha truth", status="active")
        stale = make_fact("KB-002", statement="Beta truth", status="stale")
        retired = make_fact("KB-009", statement="Gamma truth", status="retired")
        out = generate_knowledge_index([active, stale], [retired], "2026-07-09")
        assert "KB-001" in out and "Alpha truth" in out
        assert "## Stale" in out and "KB-002" in out and "Beta truth" in out
        assert "## Retired: 1" in out
        assert "KB-009" not in out  # retired ids/bodies stay out of the index
        assert "Gamma truth" not in out

    def test_rebuild_persists_stale_flip(self, tmp_path):
        kb = knowledge_root(tmp_path)
        ensure_kb(kb)
        save_fact(kb, make_fact("KB-001", status="active", verified="2026-01-01"))
        quarantined = rebuild_knowledge_index(tmp_path, "2026-07-09")
        assert quarantined == []
        reloaded = load_facts(kb)[0][0]
        assert reloaded.status == "stale"
        assert (kb / "knowledge.md").exists()

    def test_rebuild_leaves_fresh_active(self, tmp_path):
        kb = knowledge_root(tmp_path)
        ensure_kb(kb)
        save_fact(kb, make_fact("KB-001", status="active", verified="2026-07-08"))
        rebuild_knowledge_index(tmp_path, "2026-07-09")
        assert load_facts(kb)[0][0].status == "active"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_knowledge.py::TestIndex -v`
Expected: FAIL — `ImportError: cannot import name 'generate_knowledge_index'`.

- [ ] **Step 3: Implement the index**

Append to `scripts/knowledge.py`:

```python
def generate_knowledge_index(
    facts: list[Fact], retired: list[Fact], now: str
) -> str:
    active = [f for f in facts if f.status == "active"]
    stale = [f for f in facts if f.status == "stale"]

    lines = [f"# Knowledge — {len(active)} active", f"Updated: {now}", ""]
    lines.append("## Active")
    if active:
        lines += ["| Fact | Statement | Tags | Verified |", "|---|---|---|---|"]
        for f in active:
            tags = ", ".join(f.tags) or "—"
            lines.append(f"| {f.id} | {f.statement} | {tags} | {f.verified or '?'} |")
    else:
        lines.append("_No active facts._")

    lines += ["", "## Stale — verify before trusting"]
    if stale:
        for f in stale:
            tags = ", ".join(f.tags) or "—"
            lines.append(f"- {f.id} — {f.statement} ({tags}, last verified {f.verified or '?'})")
    else:
        lines.append("_None._")

    lines += ["", f"## Retired: {len(retired)}",
              "See `retired/` for superseded and refuted facts."]
    return "\n".join(lines) + "\n"


def rebuild_knowledge_index(repo_root: Path, today: str) -> list[Path]:
    kb = knowledge_root(repo_root)
    ensure_kb(kb)
    facts, quarantined = load_facts(kb)
    for fact in facts:
        effective = fact.effective_status(today)
        if effective != fact.status:
            fact.status = effective
            save_fact(kb, fact)
    retired = load_retired(kb)
    (kb / "knowledge.md").write_text(generate_knowledge_index(facts, retired, today))
    return quarantined
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_knowledge.py -v`
Expected: PASS.

- [ ] **Step 5: Gates + commit**

```bash
.venv/bin/python -m pytest && .venv/bin/ruff check scripts tests && .venv/bin/mypy scripts
git add scripts/knowledge.py tests/test_knowledge.py
git commit -m "feat(overseer): knowledge index regeneration with staleness persistence"
```

---

### Task 4: `add-fact` CLI

**Files:**
- Modify: `scripts/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `knowledge_root`, `ensure_kb`, `mint_fact_id`, `Fact`, `save_fact`, `rebuild_knowledge_index` (Tasks 1–3); existing `_today`, `_report_quarantined`.
- Produces: `add-fact --statement "<s>" --tags "<csv>" --source <id> [--body <text>]` — mints `KB-nnn`, writes the fact, rebuilds the index, prints the id.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
class TestKnowledgeAddFact:
    def test_add_fact_mints_and_indexes(self, repo, capsys):
        assert run(repo, "add-fact", "--statement", "Serial tests only",
                   "--tags", "testing, ci", "--source", "WF-012") == 0
        out = capsys.readouterr().out
        assert "KB-001" in out
        kb = state_root(repo) / "knowledge"
        fact_file = next((kb / "facts").glob("KB-001-*.md"))
        content = fact_file.read_text()
        assert "statement: Serial tests only" in content
        assert "source: WF-012" in content
        assert "- testing" in content and "- ci" in content
        assert "KB-001" in (kb / "knowledge.md").read_text()

    def test_add_fact_second_id(self, repo, capsys):
        run(repo, "add-fact", "--statement", "A", "--source", "WF-1")
        run(repo, "add-fact", "--statement", "B", "--source", "WF-1")
        assert "KB-002" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli.py::TestKnowledgeAddFact -v`
Expected: FAIL — `invalid choice: 'add-fact'`.

- [ ] **Step 3: Implement the command**

Add the KB import block in `scripts/cli.py` near the other `from scripts.* import` lines. Import ONLY the names this task uses — ruff (`F401`) fails on unused imports, so Tasks 5 and 6 will extend this block when they need more:

```python
from scripts.knowledge import (  # noqa: E402
    Fact,
    ensure_kb,
    knowledge_root,
    mint_fact_id,
    rebuild_knowledge_index,
    save_fact,
)
```

Add the command function (near the other `cmd_*` functions):

```python
def cmd_add_fact(args: argparse.Namespace) -> int:
    kb = knowledge_root(args.root)
    ensure_kb(kb)
    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
    fact = Fact(
        id=mint_fact_id(kb),
        statement=args.statement,
        tags=tags,
        source=args.source,
        created=_today(),
        verified=_today(),
        status="active",
        body=args.body or "",
    )
    save_fact(kb, fact)
    _report_quarantined(rebuild_knowledge_index(args.root, _today()))
    print(fact.id)
    return 0
```

Register in `build_parser` (near the `usage` parser):

```python
    p = sub.add_parser("add-fact")
    p.add_argument("--statement", required=True)
    p.add_argument("--tags")
    p.add_argument("--source")
    p.add_argument("--body")
    p.set_defaults(func=cmd_add_fact)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Gates + commit**

```bash
.venv/bin/python -m pytest && .venv/bin/ruff check scripts tests && .venv/bin/mypy scripts
git add scripts/cli.py tests/test_cli.py
git commit -m "feat(overseer): add-fact CLI mints knowledge facts"
```

---

### Task 5: `verify-fact` and `retire-fact` CLI

**Files:**
- Modify: `scripts/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `knowledge_root`, `find_fact_path`, `load_fact`, `save_fact`, `retire_fact_file`, `rebuild_knowledge_index`.
- Produces:
  - `verify-fact <id>` — sets `verified` to today and `status` to `active`, rebuilds index.
  - `retire-fact <id> [--superseded-by <id>]` — sets `status` retired + `superseded_by`, moves the file to `retired/`, rebuilds index.

First extend the KB import block in `scripts/cli.py` (added in Task 4) with the names this task uses — add `find_fact_path`, `load_fact`, and `retire_fact_file` to it:

```python
from scripts.knowledge import (  # noqa: E402
    Fact,
    ensure_kb,
    find_fact_path,
    knowledge_root,
    load_fact,
    mint_fact_id,
    rebuild_knowledge_index,
    retire_fact_file,
    save_fact,
)
```

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
class TestKnowledgeVerifyRetire:
    def test_verify_sets_active_status(self, repo):
        run(repo, "add-fact", "--statement", "A", "--source", "WF-1")
        assert run(repo, "verify-fact", "KB-001") == 0
        kb = state_root(repo) / "knowledge"
        content = next((kb / "facts").glob("KB-001-*.md")).read_text()
        assert "status: active" in content

    def test_retire_moves_and_records_supersede(self, repo):
        run(repo, "add-fact", "--statement", "Old truth", "--source", "WF-1")
        assert run(repo, "retire-fact", "KB-001", "--superseded-by", "KB-002") == 0
        kb = state_root(repo) / "knowledge"
        assert not list((kb / "facts").glob("KB-001-*"))
        retired_file = next((kb / "retired").glob("KB-001-*.md"))
        content = retired_file.read_text()
        assert "status: retired" in content
        assert "superseded_by: KB-002" in content

    def test_verify_missing_fact_errors(self, repo, capsys):
        assert run(repo, "verify-fact", "KB-404") == 1
        assert "error:" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli.py::TestKnowledgeVerifyRetire -v`
Expected: FAIL — `invalid choice: 'verify-fact'`.

- [ ] **Step 3: Implement the commands**

Add to `scripts/cli.py`:

```python
def cmd_verify_fact(args: argparse.Namespace) -> int:
    kb = knowledge_root(args.root)
    fact = load_fact(find_fact_path(kb, args.fact_id))
    fact.verified = _today()
    fact.status = "active"
    save_fact(kb, fact)
    _report_quarantined(rebuild_knowledge_index(args.root, _today()))
    print(f"{fact.id} verified {fact.verified}")
    return 0


def cmd_retire_fact(args: argparse.Namespace) -> int:
    kb = knowledge_root(args.root)
    fact = load_fact(find_fact_path(kb, args.fact_id))
    fact.status = "retired"
    fact.superseded_by = args.superseded_by
    retire_fact_file(kb, fact)
    _report_quarantined(rebuild_knowledge_index(args.root, _today()))
    print(f"{fact.id} retired")
    return 0
```

Register in `build_parser`:

```python
    p = sub.add_parser("verify-fact")
    p.add_argument("fact_id")
    p.set_defaults(func=cmd_verify_fact)

    p = sub.add_parser("retire-fact")
    p.add_argument("fact_id")
    p.add_argument("--superseded-by", dest="superseded_by")
    p.set_defaults(func=cmd_retire_fact)
```

Note: `find_fact_path` raises `FileNotFoundError` for a missing id; `main`'s existing `except (CardParseError, FileNotFoundError)` handler already turns that into `error:` on stderr and exit 1 (the `test_verify_missing_fact_errors` case relies on this).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Gates + commit**

```bash
.venv/bin/python -m pytest && .venv/bin/ruff check scripts tests && .venv/bin/mypy scripts
git add scripts/cli.py tests/test_cli.py
git commit -m "feat(overseer): verify-fact and retire-fact CLI"
```

---

### Task 6: `facts` CLI (read, filter, staleness display)

**Files:**
- Modify: `scripts/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `knowledge_root`, `load_facts` (imported in Task 4); `Fact.effective_status`.
- Produces: `facts [--tag <t>] [--stale] [--json]` — lists live facts (active + stale) with effective staleness computed for today; `--tag` filters by tag; `--stale` shows only effectively-stale facts; `--json` emits a list of dicts.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
class TestKnowledgeFacts:
    def test_facts_lists_and_filters_by_tag(self, repo, capsys):
        run(repo, "add-fact", "--statement", "A", "--tags", "testing", "--source", "W1")
        run(repo, "add-fact", "--statement", "B", "--tags", "auth", "--source", "W1")
        capsys.readouterr()
        assert run(repo, "facts", "--tag", "testing") == 0
        out = capsys.readouterr().out
        assert "KB-001" in out and "KB-002" not in out

    def test_facts_json(self, repo, capsys):
        run(repo, "add-fact", "--statement", "A", "--tags", "x", "--source", "W1")
        capsys.readouterr()
        assert run(repo, "facts", "--json") == 0
        data = json.loads(capsys.readouterr().out)
        assert data[0]["id"] == "KB-001" and data[0]["status"] == "active"

    def test_facts_stale_filter_shows_effective_staleness(self, repo, capsys):
        run(repo, "add-fact", "--statement", "Old", "--source", "W1")
        # Age the fact on disk so effective_status(today) == stale.
        kb = state_root(repo) / "knowledge"
        fact_file = next((kb / "facts").glob("KB-001-*.md"))
        aged = "\n".join(
            "verified: 2020-01-01" if line.startswith("verified:") else line
            for line in fact_file.read_text().splitlines()
        ) + "\n"
        fact_file.write_text(aged)
        capsys.readouterr()
        assert run(repo, "facts", "--stale", "--json") == 0
        data = json.loads(capsys.readouterr().out)
        assert len(data) == 1 and data[0]["status"] == "stale"

    def test_facts_empty(self, repo, capsys):
        assert run(repo, "facts") == 0
        assert "No facts" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli.py::TestKnowledgeFacts -v`
Expected: FAIL — `invalid choice: 'facts'`.

- [ ] **Step 3: Implement the command**

Add to `scripts/cli.py`:

```python
def cmd_facts(args: argparse.Namespace) -> int:
    kb = knowledge_root(args.root)
    facts, quarantined = load_facts(kb)
    _report_quarantined(quarantined)
    today = _today()
    rows = []
    for f in facts:
        effective = f.effective_status(today)
        if args.tag and args.tag not in f.tags:
            continue
        if args.stale and effective != "stale":
            continue
        rows.append({
            "id": f.id,
            "statement": f.statement,
            "tags": f.tags,
            "verified": f.verified,
            "status": effective,
        })
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("No stale facts." if args.stale else "No facts.")
        return 0
    for r in rows:
        mark = " [STALE]" if r["status"] == "stale" else ""
        tags = ", ".join(r["tags"]) or "no tags"
        print(f"{r['id']} ({tags}){mark}: {r['statement']}")
    return 0
```

Register in `build_parser`:

```python
    p = sub.add_parser("facts")
    p.add_argument("--tag")
    p.add_argument("--stale", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_facts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Gates + commit**

```bash
.venv/bin/python -m pytest && .venv/bin/ruff check scripts tests && .venv/bin/mypy scripts
git add scripts/cli.py tests/test_cli.py
git commit -m "feat(overseer): facts CLI with tag/stale filters and json"
```

---

### Task 7: Template hooks — `{{knowledge}}` + Learned lines

**Files:**
- Modify: `templates/planner.md`, `templates/implementer.md`, `templates/reviewer.md`, `templates/fixer.md`, `templates/sprint-reviewer.md`

**Interfaces:** doctrine only — no code, no test cycle.

- [ ] **Step 1: Add the knowledge input to each template's Inputs**

Add this line to the `## Inputs` block of `planner.md`, `implementer.md`, `reviewer.md`, `fixer.md`, and to the `## Inputs` block of `sprint-reviewer.md`:

```markdown
- Relevant knowledge (verify anything marked stale before trusting): {{knowledge}}
```

Place it as the last bullet in each `## Inputs` section. (In `implementer.md` the relevant heading is `## Inputs`; in `reviewer.md`/`sprint-reviewer.md` it is `## Inputs`; if a template uses a differently named first section for its inputs, add the line there.)

- [ ] **Step 2: Add a "Learned" line to each report contract**

In `implementer.md` and `fixer.md`, in the final report list (the `## Report` block), add a bullet:

```markdown
- Learned: zero or more durable, falsifiable facts worth keeping (one sentence
  each + suggested tags), or "none". The orchestrator adjudicates.
```

In `reviewer.md` and `sprint-reviewer.md`, in the `## Verdict` block, add:

```markdown
- **Learned:** zero or more durable, falsifiable facts (one sentence + tags),
  or "none".
```

In `planner.md`, in the `## Output` block, add a sentence:

```markdown
If planning surfaced a durable, falsifiable fact worth keeping, add a
**Learned** line (one sentence + suggested tags); otherwise omit it.
```

- [ ] **Step 3: Verify the edits**

Re-read all five templates; confirm each has the `{{knowledge}}` input line and the appropriate Learned line, and that markdown structure is intact.

- [ ] **Step 4: Commit**

```bash
git add templates/planner.md templates/implementer.md templates/reviewer.md templates/fixer.md templates/sprint-reviewer.md
git commit -m "docs(overseer): dispatch templates consume {{knowledge}} and report Learned facts"
```

---

### Task 8: KB lifecycle doctrine

**Files:**
- Modify: `skills/ledger/SKILL.md`, `skills/orchestrate/SKILL.md`

**Interfaces:** doctrine only.

- [ ] **Step 1: Add a Knowledge base section to the ledger skill**

Append to `skills/ledger/SKILL.md`, after the `## Sprints` section:

```markdown
## Knowledge base

A living store of durable, falsifiable facts under the state root
(`knowledge/`). The CLI is the only writer; the index (`knowledge.md`) is a
view.

- `add-fact --statement "<falsifiable sentence>" --tags "testing,auth" --source <card-id> [--body "..."]`
  mints the next `KB-nnn`. Only mint facts that are falsifiable — "the auth
  fixtures share a DB schema", not "auth is tricky".
- `verify-fact <id>` when a fact is relied on and still holds — bumps its
  verified date and clears any stale mark.
- `retire-fact <id> [--superseded-by <id>]` when a fact is refuted or
  superseded — moves it to `retired/`, never deletes it.
- `facts [--tag <t>] [--stale] [--json]` lists live facts; facts older than
  90 days show `[STALE]` and must be re-verified before they are trusted.
```

- [ ] **Step 2: Add KB lifecycle to the orchestrate skill**

Append to `skills/orchestrate/SKILL.md`, after the `## Telemetry (self-monitoring)` section:

```markdown
## Knowledge (mint, inject, verify, retire)
The knowledge base is the orchestrator's memory across cards. You are its only
writer; agents propose, you adjudicate.

- **Inject.** At every dispatch, fill the template's `{{knowledge}}` with the
  facts whose tags/paths intersect this card's `touches`, goal, or chunk brief
  — never the whole corpus. An empty selection injects nothing. Facts marked
  `[STALE]` go in with their marker; the agent treats them as claims to
  re-verify.
- **Mint.** Each report may carry a **Learned** line. Adjudicate it: mint only
  falsifiable, non-duplicate facts via `add-fact` (source = the card id).
  Reject the vague and the already-known.
- **Verify.** When an injected fact is relied on and proves true, `verify-fact`
  it — that clears staleness and resets its 90-day clock.
- **Retire.** When a reviewer or worker refutes a fact, `retire-fact` it
  (`--superseded-by` when a newer fact replaces it). Never edit knowledge files
  by hand.
```

- [ ] **Step 3: Verify and commit**

Re-read both files; confirm section structure intact.

```bash
git add skills/ledger/SKILL.md skills/orchestrate/SKILL.md
git commit -m "docs(overseer): knowledge-base lifecycle doctrine (mint/inject/verify/retire)"
```

---

### Task 9: README, version bump, final review

**Files:**
- Modify: `plugins/overseer/README.md`, `plugins/overseer/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`

**Interfaces:** none — housekeeping + final whole-branch review.

- [ ] **Step 1: Update the README**

In `plugins/overseer/README.md`, add the knowledge base to "What it does" and "Skills": durable facts under `knowledge/` with per-fact verification dates, `add-fact`/`verify-fact`/`retire-fact`/`facts` commands, 90-day staleness, retirement (never deleted), and `{{knowledge}}` injection into dispatches. Move the knowledge base out of any "Later phases" framing — it is now delivered.

- [ ] **Step 2: Bump versions**

`plugins/overseer/.claude-plugin/plugin.json`: `"version": "0.3.0"` → `"version": "0.4.0"`. In `.claude-plugin/marketplace.json`, bump the top-level marketplace `version` one minor (`1.6.0` → `1.7.0`; if different, bump whatever is there and note it).

- [ ] **Step 3: Full gates**

```bash
.venv/bin/python -m pytest && .venv/bin/ruff check scripts tests && .venv/bin/mypy scripts
```
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add plugins/overseer/README.md plugins/overseer/.claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "chore(overseer): v0.4.0 — living knowledge base"
```

---

## Self-Review

**Spec coverage:**
- §1 Layout (`<state-root>/knowledge/`, facts/retired/corrupt, index) → Tasks 2 (`knowledge_root`, `ensure_kb`), 3 (index). ✓
- §2 Fact schema (KB-nnn, statement/tags/source/created/verified/status/superseded_by, falsifiable) → Task 1. ✓
- §3 Lifecycle (mint/verify/stale-90d/retire, agents never write) → Tasks 1 (staleness), 3 (persist flip), 4 (add), 5 (verify/retire), 8 (doctrine: adjudication, agents propose). ✓
- §4 Index (active table, loud Stale section, retired count, retired bodies excluded) → Task 3. ✓
- §5 Template hooks (`{{knowledge}}` in five templates, relevance selection, stale marker, Learned lines) → Task 7 (templates) + Task 8 (orchestrator selection/injection doctrine). ✓
- §6 CLI (`add-fact`, `verify-fact`, `retire-fact`, `facts`; corrupt quarantine to `knowledge/corrupt/`) → Tasks 4, 5, 6 (CLI); Task 2 (`quarantine_fact`). ✓
- §7 Testing (round-trips, stale flip, filters, quarantine) → Tasks 1–6 pytest; doctrine end-to-end noted as out of automated scope. ✓
- Out of scope (Obsidian export, cross-repo, auto-extraction, ranking) → not built. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every test step shows complete test code with command + expected result.

**Type consistency:** `Fact` fields and `from_text`/`to_text` (Task 1) are reused verbatim by Tasks 2–6. `knowledge_root(repo_root) -> Path`, `ensure_kb`, `mint_fact_id`, `save_fact`, `load_facts -> tuple[list[Fact], list[Path]]`, `find_fact_path`, `load_fact`, `retire_fact_file` (Task 2) match their uses in Tasks 3–6. `rebuild_knowledge_index(repo_root, today) -> list[Path]` (Task 3) is called identically in Tasks 4–5. `effective_status(today)` (Task 1) is used by Task 3 (persist) and Task 6 (display). The Task 4 import block front-loads every KB name Tasks 4–6 use, so no later task adds imports. ✓

**Note on the Task 5 verify test:** the test asserts `status: active` after `verify-fact` (the load-bearing behaviour). The `verified`-date assertion is left implicit because the fixture runs on the real `_today()`; the round-trip and staleness mechanics are proven in `tests/test_knowledge.py`.

---

## Execution Handoff

Two execution options:

1. **Subagent-Driven (recommended)** — a fresh subagent per task, two-stage review between tasks, fast iteration.
2. **Inline Execution** — batch execution in this session with checkpoints.
