# Overseer Ledger & State — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `overseer` plugin's phase-1 foundation: a file-based work ledger (`.workflow/`) with card lifecycle, index regeneration, sprint rollups, budget tripwire, resume detection, and a CLI that a SKILL.md drives.

**Architecture:** Pure file-in/file-out Python package under `plugins/overseer/scripts/`, mirroring review-clone's layout (flat modules, pytest with `pythonpath=["."]`). Card/sprint files are markdown + YAML frontmatter; `ledger.md` is a regenerated view, card files are the source of truth; a single writer (the orchestrating session) calls the CLI. No agent orchestration in this phase.

**Tech Stack:** Python 3.11, PyYAML (only runtime dep), pytest, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-07-08-workflow-ledger-design.md` — schemas and lifecycle defined there are authoritative.

## Global Constraints

- Plugin name is `overseer`; everything lives under `plugins/overseer/`.
- Statuses: `planned | in-flight | blocked | done | abandoned`. Stages (only while in-flight): `bootstrap | planning | plan-review | implementation | impl-review | verification | awaiting-merge`.
- Token budgets are stored in frontmatter as strings (`400k`, `2.1M`), held in memory as ints. Tripwire fires when `actual >= 2 * estimate`.
- Timestamps are strings, format `%Y-%m-%dT%H:%M` (dates alone `%Y-%m-%d` for `created`). Core functions take `now: str` parameters — never call `datetime.now()` outside `cli.py`.
- Card body section headers are exact: `## Goal`, `## Plan`, `## Decisions`, `## Review log`, `## Progress log`, `## Verification`.
- Every mutating CLI command writes the card file first, then regenerates `ledger.md` (write ordering per spec).
- Unparseable cards are quarantined to `archive/corrupt/`, never skipped or overwritten.
- All commands below run from `plugins/overseer/` unless stated. Lint/type gates per task: `poetry run ruff check scripts tests` and `poetry run mypy scripts` must pass before each commit.
- Execution happens on a fresh branch `feat/overseer-ledger` off `origin/main` in an isolated worktree (superpowers:using-git-worktrees).

## File Structure

```
plugins/overseer/
  .claude-plugin/plugin.json      # plugin manifest
  pyproject.toml                  # pytest/ruff/mypy config
  README.md                       # plugin readme (Task 9)
  scripts/
    __init__.py
    models.py                     # Card model, frontmatter, tokens, mutations (Tasks 1–3)
    store.py                      # .workflow/ filesystem ops (Task 4)
    index.py                      # ledger.md generation (Task 5)
    sprints.py                    # Sprint model + rollup (Task 6)
    resume.py                     # session-start in-flight report (Task 7)
    cli.py                        # argparse entry point (Task 8)
  skills/ledger/SKILL.md          # the overseer:ledger skill (Task 9)
  tests/
    test_models.py
    test_store.py
    test_index.py
    test_sprints.py
    test_resume.py
    test_cli.py
```

Root-repo changes (Task 9): register the plugin in `.claude-plugin/marketplace.json`.

---

### Task 1: Scaffold + token helpers + frontmatter split

**Files:**
- Create: `plugins/overseer/.claude-plugin/plugin.json`
- Create: `plugins/overseer/pyproject.toml`
- Create: `plugins/overseer/scripts/__init__.py` (empty)
- Create: `plugins/overseer/scripts/models.py`
- Test: `plugins/overseer/tests/test_models.py`

**Interfaces:**
- Produces: `parse_tokens(value: str | int | float | None) -> int | None`, `format_tokens(n: int | None) -> str | None`, `split_frontmatter(text: str) -> tuple[dict, str]`, exception `CardParseError(ValueError)`, constants `STATUSES: set[str]`, `STAGES: list[str]` — all in `scripts.models`.

- [ ] **Step 1: Create scaffold files**

`plugins/overseer/.claude-plugin/plugin.json`:

```json
{
  "name": "overseer",
  "version": "0.1.0",
  "description": "Workflow orchestration foundation: a persistent per-repo ledger of cards, sprints and token budgets. Phase 1 of the overseer plugin — state only.",
  "author": {
    "name": "Pip",
    "url": "https://github.com/ppryde/pip-skills"
  },
  "keywords": ["workflow", "ledger", "sprints", "orchestration", "task-tracking", "budgets"]
}
```

`plugins/overseer/pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
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

`plugins/overseer/scripts/__init__.py`: empty file.

- [ ] **Step 2: Write the failing tests**

`plugins/overseer/tests/test_models.py`:

```python
import pytest

from scripts.models import (
    CardParseError,
    format_tokens,
    parse_tokens,
    split_frontmatter,
)


class TestTokens:
    def test_parse_plain_int(self):
        assert parse_tokens(400000) == 400000

    def test_parse_k_suffix(self):
        assert parse_tokens("400k") == 400_000

    def test_parse_decimal_m_suffix(self):
        assert parse_tokens("2.1M") == 2_100_000

    def test_parse_none(self):
        assert parse_tokens(None) is None

    def test_parse_garbage_raises(self):
        with pytest.raises(CardParseError):
            parse_tokens("lots")

    def test_format_k(self):
        assert format_tokens(310_000) == "310k"

    def test_format_m(self):
        assert format_tokens(2_100_000) == "2.1M"

    def test_format_small(self):
        assert format_tokens(950) == "950"

    def test_format_none(self):
        assert format_tokens(None) is None

    def test_round_trip(self):
        for raw in ("150k", "2.1M", "999"):
            assert format_tokens(parse_tokens(raw)) == raw


class TestSplitFrontmatter:
    def test_splits_meta_and_body(self):
        meta, body = split_frontmatter("---\nid: WF-001\n---\n\n## Goal\nHi\n")
        assert meta == {"id": "WF-001"}
        assert body.strip() == "## Goal\nHi"

    def test_missing_frontmatter_raises(self):
        with pytest.raises(CardParseError):
            split_frontmatter("## Goal\nno frontmatter here\n")

    def test_invalid_yaml_raises(self):
        with pytest.raises(CardParseError):
            split_frontmatter("---\n{ not: valid: yaml\n---\nbody\n")

    def test_non_mapping_frontmatter_raises(self):
        with pytest.raises(CardParseError):
            split_frontmatter("---\n- just\n- a list\n---\nbody\n")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd plugins/overseer && poetry run pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError` / `ImportError` (models.py has no such names yet).

- [ ] **Step 4: Write the implementation**

`plugins/overseer/scripts/models.py`:

```python
"""Card data model: frontmatter parse/serialise, token arithmetic, mutations."""
from __future__ import annotations

import re

import yaml

STATUSES = {"planned", "in-flight", "blocked", "done", "abandoned"}
STAGES = [
    "bootstrap",
    "planning",
    "plan-review",
    "implementation",
    "impl-review",
    "verification",
    "awaiting-merge",
]

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
_TOKENS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([kM])?")


class CardParseError(ValueError):
    """A card file that cannot be parsed or fails validation."""


def parse_tokens(value: str | int | float | None) -> int | None:
    """'400k' -> 400_000, '2.1M' -> 2_100_000, 999 -> 999. None passes through."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = _TOKENS_RE.fullmatch(str(value).strip())
    if match is None:
        raise CardParseError(f"unparseable token count: {value!r}")
    multiplier = {"k": 1_000, "M": 1_000_000}.get(match.group(2) or "", 1)
    return int(float(match.group(1)) * multiplier)


def format_tokens(n: int | None) -> str | None:
    """400_000 -> '400k', 2_100_000 -> '2.1M', 999 -> '999'. None passes through."""
    if n is None:
        return None
    if n >= 1_000_000:
        return f"{n / 1_000_000:g}M"
    if n >= 1_000:
        return f"{n / 1_000:g}k"
    return str(n)


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Split a markdown document into (frontmatter mapping, body)."""
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise CardParseError("no frontmatter block found")
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise CardParseError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(meta, dict):
        raise CardParseError("frontmatter is not a mapping")
    return meta, match.group(2)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd plugins/overseer && poetry run pytest tests/test_models.py -v`
Expected: PASS (14 tests). If `yaml` is missing from the poetry env: `poetry add pyyaml` at repo root first.

- [ ] **Step 6: Lint, type-check, commit**

Run: `cd plugins/overseer && poetry run ruff check scripts tests && poetry run mypy scripts`
Expected: no findings.

```bash
git add plugins/overseer
git commit -m "feat(overseer): scaffold plugin with token + frontmatter helpers"
```

---

### Task 2: Card parse/serialise round-trip

**Files:**
- Modify: `plugins/overseer/scripts/models.py` (append)
- Test: `plugins/overseer/tests/test_models.py` (append)

**Interfaces:**
- Consumes: `split_frontmatter`, `parse_tokens`, `format_tokens`, `STATUSES`, `STAGES`, `CardParseError` (Task 1).
- Produces: `@dataclass Card` with fields `id: str, title: str, status: str, stage: str | None, complexity: str | None, jira: str | None, sprint: str | None, branch: str | None, worktree: str | None, budget_estimate: int | None, budget_actual: int, created: str, updated: str, blocked_on: str | None, body: str`; `Card.from_text(text: str) -> Card`; `Card.to_text() -> str`. Round-trip is lossless for all frontmatter fields and the stripped body.

- [ ] **Step 1: Write the failing tests**

Append to `plugins/overseer/tests/test_models.py`:

```python
from scripts.models import Card

SAMPLE_CARD = """---
id: WF-012
jira: PROJ-142
title: Fix auth redirect loop on SSO logout
status: in-flight
stage: impl-review
complexity: M
sprint: 2026-07-S1
branch: fix/PROJ-142-auth-redirect-loop
worktree: ../pip-skills-wt/PROJ-142
budget:
  estimate: 400k
  actual: 310k
created: 2026-07-08
updated: 2026-07-08T14:32
blocked_on: null
---

## Goal
Stop the redirect loop.

## Plan
1. Reproduce.

## Decisions

## Review log

## Progress log

## Verification
"""


class TestCardParse:
    def test_parses_all_fields(self):
        card = Card.from_text(SAMPLE_CARD)
        assert card.id == "WF-012"
        assert card.jira == "PROJ-142"
        assert card.title == "Fix auth redirect loop on SSO logout"
        assert card.status == "in-flight"
        assert card.stage == "impl-review"
        assert card.complexity == "M"
        assert card.sprint == "2026-07-S1"
        assert card.branch == "fix/PROJ-142-auth-redirect-loop"
        assert card.worktree == "../pip-skills-wt/PROJ-142"
        assert card.budget_estimate == 400_000
        assert card.budget_actual == 310_000
        assert card.created == "2026-07-08"
        assert card.updated == "2026-07-08T14:32"
        assert card.blocked_on is None
        assert card.body.startswith("## Goal")

    def test_minimal_card(self):
        card = Card.from_text("---\nid: WF-001\ntitle: T\nstatus: planned\n---\nbody\n")
        assert card.stage is None
        assert card.budget_estimate is None
        assert card.budget_actual == 0

    def test_missing_required_field_raises(self):
        with pytest.raises(CardParseError, match="title"):
            Card.from_text("---\nid: WF-001\nstatus: planned\n---\nbody\n")

    def test_bad_status_raises(self):
        with pytest.raises(CardParseError, match="status"):
            Card.from_text("---\nid: WF-001\ntitle: T\nstatus: doing\n---\nbody\n")

    def test_bad_stage_raises(self):
        with pytest.raises(CardParseError, match="stage"):
            Card.from_text(
                "---\nid: WF-001\ntitle: T\nstatus: in-flight\nstage: coding\n---\nbody\n"
            )

    def test_round_trip_is_lossless(self):
        card = Card.from_text(SAMPLE_CARD)
        again = Card.from_text(card.to_text())
        assert again == card

    def test_to_text_formats_budget_as_strings(self):
        card = Card.from_text(SAMPLE_CARD)
        assert "estimate: 400k" in card.to_text()
        assert "actual: 310k" in card.to_text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd plugins/overseer && poetry run pytest tests/test_models.py -v -k Card`
Expected: FAIL — `ImportError: cannot import name 'Card'`.

- [ ] **Step 3: Write the implementation**

Append to `plugins/overseer/scripts/models.py` (add `from dataclasses import dataclass, field` to the imports):

```python
@dataclass
class Card:
    """One unit of work. The card file is the source of truth; the index is a view."""

    id: str
    title: str
    status: str = "planned"
    stage: str | None = None
    complexity: str | None = None
    jira: str | None = None
    sprint: str | None = None
    branch: str | None = None
    worktree: str | None = None
    budget_estimate: int | None = None
    budget_actual: int = 0
    created: str = ""
    updated: str = ""
    blocked_on: str | None = None
    body: str = ""

    @classmethod
    def from_text(cls, text: str) -> "Card":
        meta, body = split_frontmatter(text)
        for key in ("id", "title", "status"):
            if not meta.get(key):
                raise CardParseError(f"missing required field: {key}")
        status = str(meta["status"])
        if status not in STATUSES:
            raise CardParseError(f"unknown status: {status!r}")
        stage = meta.get("stage")
        if stage is not None and stage not in STAGES:
            raise CardParseError(f"unknown stage: {stage!r}")
        budget = meta.get("budget") or {}
        return cls(
            id=str(meta["id"]),
            title=str(meta["title"]),
            status=status,
            stage=stage,
            complexity=meta.get("complexity"),
            jira=meta.get("jira"),
            sprint=meta.get("sprint"),
            branch=meta.get("branch"),
            worktree=meta.get("worktree"),
            budget_estimate=parse_tokens(budget.get("estimate")),
            budget_actual=parse_tokens(budget.get("actual")) or 0,
            created=str(meta.get("created", "")),
            updated=str(meta.get("updated", "")),
            blocked_on=meta.get("blocked_on"),
            body=body.strip(),
        )

    def to_text(self) -> str:
        meta = {
            "id": self.id,
            "jira": self.jira,
            "title": self.title,
            "status": self.status,
            "stage": self.stage,
            "complexity": self.complexity,
            "sprint": self.sprint,
            "branch": self.branch,
            "worktree": self.worktree,
            "budget": {
                "estimate": format_tokens(self.budget_estimate),
                "actual": format_tokens(self.budget_actual),
            },
            "created": self.created,
            "updated": self.updated,
            "blocked_on": self.blocked_on,
        }
        front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
        return f"---\n{front}\n---\n\n{self.body.strip()}\n"
```

Note: `yaml.safe_dump` renders `None` as `null` and keeps insertion order with `sort_keys=False` — matching the spec's frontmatter exactly. `created: 2026-07-08` parses from YAML as a `datetime.date`; `str(...)` normalises it back to ISO text, and `updated: 2026-07-08T14:32` stays a string because bare `T`-times without seconds are not YAML timestamps. The round-trip test guards this.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/overseer && poetry run pytest tests/test_models.py -v`
Expected: PASS (21 tests).

- [ ] **Step 5: Lint, type-check, commit**

Run: `cd plugins/overseer && poetry run ruff check scripts tests && poetry run mypy scripts`

```bash
git add plugins/overseer
git commit -m "feat(overseer): Card model with lossless frontmatter round-trip"
```

---

### Task 3: Card mutations — stages, blocking, progress, reviews, tripwire

**Files:**
- Modify: `plugins/overseer/scripts/models.py` (append)
- Test: `plugins/overseer/tests/test_models.py` (append)

**Interfaces:**
- Consumes: `Card` (Task 2).
- Produces (all on `Card`, all set `self.updated = now`):
  - `set_stage(stage: str, now: str) -> None` — validates stage, sets `status="in-flight"`.
  - `block(reason: str, now: str) -> None` — `status="blocked"`, `blocked_on=reason` (stage preserved).
  - `unblock(now: str) -> None` — status back to `"in-flight"` if a stage is set else `"planned"`; clears `blocked_on`.
  - `complete(now: str) -> None` / `abandon(now: str) -> None` — status `done`/`abandoned`, stage cleared.
  - `log_progress(note: str, tokens: int, now: str) -> None` — adds tokens to `budget_actual`, appends `- {now} — {note} (~{format_tokens(tokens)} tokens)` to `## Progress log`.
  - `log_review(stage: str, reviewers: int, verdict: str, now: str) -> None` — appends a `### {stage} — round {n} ({reviewers} reviewers)\nVerdict: {verdict}` block to `## Review log`; round auto-increments.
  - `review_rounds(stage: str) -> int` — count of logged rounds for a stage.
  - property `tripwire_breached: bool` — `estimate is not None and actual >= 2 * estimate`.
- Also produces module function `append_to_section(body: str, header: str, content: str) -> str` (used by sprints in Task 6).

- [ ] **Step 1: Write the failing tests**

Append to `plugins/overseer/tests/test_models.py`:

```python
from scripts.models import append_to_section

NOW = "2026-07-08T15:00"


def make_card() -> Card:
    return Card.from_text(SAMPLE_CARD)


class TestAppendToSection:
    def test_appends_inside_section(self):
        body = "## Progress log\n- old line\n\n## Verification\nevidence"
        out = append_to_section(body, "## Progress log", "- new line")
        assert out.index("- new line") < out.index("## Verification")
        assert out.index("- old line") < out.index("- new line")

    def test_appends_to_last_section(self):
        out = append_to_section("## Progress log\n- old", "## Progress log", "- new")
        assert out.endswith("- new")

    def test_missing_section_is_created(self):
        out = append_to_section("## Goal\nhi", "## Progress log", "- new")
        assert "## Progress log\n- new" in out


class TestMutations:
    def test_set_stage(self):
        card = make_card()
        card.set_stage("verification", NOW)
        assert (card.status, card.stage, card.updated) == ("in-flight", "verification", NOW)

    def test_set_bad_stage_raises(self):
        with pytest.raises(CardParseError):
            make_card().set_stage("coding", NOW)

    def test_block_preserves_stage(self):
        card = make_card()
        card.block("user: scope question", NOW)
        assert card.status == "blocked"
        assert card.blocked_on == "user: scope question"
        assert card.stage == "impl-review"

    def test_unblock_returns_to_in_flight(self):
        card = make_card()
        card.block("user: q", NOW)
        card.unblock(NOW)
        assert card.status == "in-flight"
        assert card.blocked_on is None

    def test_unblock_without_stage_returns_to_planned(self):
        card = Card.from_text("---\nid: W-1\ntitle: T\nstatus: planned\n---\nx")
        card.block("card: WF-011", NOW)
        card.unblock(NOW)
        assert card.status == "planned"

    def test_complete_clears_stage(self):
        card = make_card()
        card.complete(NOW)
        assert (card.status, card.stage) == ("done", None)

    def test_abandon(self):
        card = make_card()
        card.abandon(NOW)
        assert card.status == "abandoned"

    def test_log_progress_adds_tokens_and_line(self):
        card = make_card()
        card.log_progress("impl agent: steps 1-3 done", 120_000, NOW)
        assert card.budget_actual == 430_000
        assert f"- {NOW} — impl agent: steps 1-3 done (~120k tokens)" in card.body

    def test_log_review_rounds_auto_increment(self):
        card = make_card()
        card.log_review("impl-review", 2, "found wanting — 2 findings", NOW)
        card.log_review("impl-review", 2, "approved", NOW)
        assert card.review_rounds("impl-review") == 2
        assert "### impl-review — round 2 (2 reviewers)\nVerdict: approved" in card.body

    def test_tripwire(self):
        card = make_card()
        assert card.tripwire_breached is False
        card.log_progress("big burn", 490_000, NOW)  # 310k + 490k = 800k >= 2*400k
        assert card.tripwire_breached is True

    def test_tripwire_without_estimate_never_fires(self):
        card = Card.from_text("---\nid: W-1\ntitle: T\nstatus: planned\n---\nx")
        card.log_progress("work", 10_000_000, NOW)
        assert card.tripwire_breached is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd plugins/overseer && poetry run pytest tests/test_models.py -v -k "Mutations or AppendToSection"`
Expected: FAIL — `ImportError: cannot import name 'append_to_section'`.

- [ ] **Step 3: Write the implementation**

Append to `plugins/overseer/scripts/models.py` — module function first:

```python
def append_to_section(body: str, header: str, content: str) -> str:
    """Insert content at the end of the named `## ` section, creating it if absent."""
    lines = body.split("\n")
    if header not in lines:
        return f"{body.rstrip()}\n\n{header}\n{content}"
    start = lines.index(header)
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    while end - 1 > start and lines[end - 1].strip() == "":
        end -= 1
    lines.insert(end, content)
    return "\n".join(lines)
```

Then these methods inside `class Card`:

```python
    def set_stage(self, stage: str, now: str) -> None:
        if stage not in STAGES:
            raise CardParseError(f"unknown stage: {stage!r}")
        self.stage = stage
        self.status = "in-flight"
        self.updated = now

    def block(self, reason: str, now: str) -> None:
        self.status = "blocked"
        self.blocked_on = reason
        self.updated = now

    def unblock(self, now: str) -> None:
        self.status = "in-flight" if self.stage else "planned"
        self.blocked_on = None
        self.updated = now

    def complete(self, now: str) -> None:
        self.status = "done"
        self.stage = None
        self.updated = now

    def abandon(self, now: str) -> None:
        self.status = "abandoned"
        self.stage = None
        self.updated = now

    def log_progress(self, note: str, tokens: int, now: str) -> None:
        self.budget_actual += tokens
        line = f"- {now} — {note} (~{format_tokens(tokens)} tokens)"
        self.body = append_to_section(self.body, "## Progress log", line)
        self.updated = now

    def log_review(self, stage: str, reviewers: int, verdict: str, now: str) -> None:
        round_no = self.review_rounds(stage) + 1
        block = f"### {stage} — round {round_no} ({reviewers} reviewers)\nVerdict: {verdict}"
        self.body = append_to_section(self.body, "## Review log", block)
        self.updated = now

    def review_rounds(self, stage: str) -> int:
        return self.body.count(f"### {stage} — round ")

    @property
    def tripwire_breached(self) -> bool:
        if self.budget_estimate is None:
            return False
        return self.budget_actual >= 2 * self.budget_estimate
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/overseer && poetry run pytest tests/test_models.py -v`
Expected: PASS (35 tests).

- [ ] **Step 5: Lint, type-check, commit**

Run: `cd plugins/overseer && poetry run ruff check scripts tests && poetry run mypy scripts`

```bash
git add plugins/overseer
git commit -m "feat(overseer): card lifecycle mutations, review log, budget tripwire"
```

---

### Task 4: Store — `.workflow/` filesystem operations

**Files:**
- Create: `plugins/overseer/scripts/store.py`
- Test: `plugins/overseer/tests/test_store.py`

**Interfaces:**
- Consumes: `Card`, `CardParseError` (Tasks 2–3).
- Produces (`scripts.store`, all paths `pathlib.Path`):
  - `workflow_root(repo_root: Path) -> Path` — `repo_root / ".workflow"`.
  - `init_workflow(repo_root: Path) -> Path` — creates `cards/`, `sprints/`, `archive/cards/`, `archive/corrupt/`; appends `.workflow/` to the repo `.gitignore` if absent; idempotent; returns the root.
  - `slugify(title: str) -> str` — lowercase, alnum runs joined by `-`, max 40 chars.
  - `mint_id(root: Path) -> str` — next `WF-nnn` (3-digit, zero-padded) scanning `cards/` and `archive/cards/`.
  - `card_path(root: Path, card: Card) -> Path` — `cards/{id}-{slug}.md`.
  - `find_card_path(root: Path, card_id: str) -> Path` — glob `cards/{card_id}-*.md`; raises `FileNotFoundError` if no match.
  - `load_card(path: Path) -> Card` — raises `CardParseError` on bad content.
  - `save_card(root: Path, card: Card) -> Path` — writes `card.to_text()` to `card_path`.
  - `load_live_cards(root: Path) -> tuple[list[Card], list[Path]]` — loads every card in `cards/`; unparseable files are quarantined and returned in the second element (post-quarantine paths).
  - `quarantine(root: Path, path: Path) -> Path` — moves the file to `archive/corrupt/`.
  - `archive_card(root: Path, card: Card) -> Path` — writes card to `archive/cards/`, removes it from `cards/`.
  - `load_archived_cards(root: Path) -> list[Card]` — parseable cards from `archive/cards/`, newest `updated` first.

- [ ] **Step 1: Write the failing tests**

`plugins/overseer/tests/test_store.py`:

```python
import pytest

from scripts.models import Card
from scripts.store import (
    archive_card,
    find_card_path,
    init_workflow,
    load_archived_cards,
    load_live_cards,
    mint_id,
    save_card,
    slugify,
)


def make_card(card_id: str = "WF-001", **overrides: object) -> Card:
    fields = dict(
        id=card_id, title="Fix the thing", status="planned",
        created="2026-07-08", updated="2026-07-08T10:00",
        body="## Goal\nfix it",
    )
    fields.update(overrides)
    return Card(**fields)  # type: ignore[arg-type]


@pytest.fixture
def root(tmp_path):
    return init_workflow(tmp_path)


class TestInit:
    def test_creates_directories(self, tmp_path):
        root = init_workflow(tmp_path)
        for sub in ("cards", "sprints", "archive/cards", "archive/corrupt"):
            assert (root / sub).is_dir()

    def test_gitignore_entry_added_once(self, tmp_path):
        init_workflow(tmp_path)
        init_workflow(tmp_path)
        assert (tmp_path / ".gitignore").read_text().count(".workflow/") == 1

    def test_existing_gitignore_preserved(self, tmp_path):
        (tmp_path / ".gitignore").write_text("*.pyc\n")
        init_workflow(tmp_path)
        content = (tmp_path / ".gitignore").read_text()
        assert "*.pyc" in content and ".workflow/" in content


class TestSlugAndMint:
    def test_slugify(self):
        assert slugify("Fix auth redirect loop on SSO logout!") == (
            "fix-auth-redirect-loop-on-sso-logout"
        )

    def test_mint_first_id(self, root):
        assert mint_id(root) == "WF-001"

    def test_mint_skips_used_and_archived(self, root):
        save_card(root, make_card("WF-004"))
        archive_card(root, make_card("WF-007", status="done"))
        assert mint_id(root) == "WF-008"

    def test_mint_ignores_jira_ids(self, root):
        save_card(root, make_card("PROJ-142"))
        assert mint_id(root) == "WF-001"


class TestSaveLoad:
    def test_save_and_find(self, root):
        save_card(root, make_card())
        path = find_card_path(root, "WF-001")
        assert path.name == "WF-001-fix-the-thing.md"

    def test_find_missing_raises(self, root):
        with pytest.raises(FileNotFoundError):
            find_card_path(root, "WF-999")

    def test_load_live_cards_sorted(self, root):
        save_card(root, make_card("WF-002", title="B"))
        save_card(root, make_card("WF-001", title="A"))
        cards, quarantined = load_live_cards(root)
        assert [c.id for c in cards] == ["WF-001", "WF-002"]
        assert quarantined == []

    def test_corrupt_card_quarantined_not_skipped(self, root):
        save_card(root, make_card())
        bad = root / "cards" / "WF-002-broken.md"
        bad.write_text("no frontmatter at all")
        cards, quarantined = load_live_cards(root)
        assert [c.id for c in cards] == ["WF-001"]
        assert quarantined == [root / "archive" / "corrupt" / "WF-002-broken.md"]
        assert not bad.exists()
        assert quarantined[0].read_text() == "no frontmatter at all"


class TestArchive:
    def test_archive_moves_card(self, root):
        card = make_card()
        save_card(root, card)
        card.complete("2026-07-09T09:00")
        archive_card(root, card)
        assert not (root / "cards" / "WF-001-fix-the-thing.md").exists()
        assert (root / "archive" / "cards" / "WF-001-fix-the-thing.md").exists()

    def test_load_archived_newest_first(self, root):
        older = make_card("WF-001", status="done", updated="2026-07-01T09:00")
        newer = make_card("WF-002", status="done", updated="2026-07-05T09:00")
        archive_card(root, older)
        archive_card(root, newer)
        assert [c.id for c in load_archived_cards(root)] == ["WF-002", "WF-001"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd plugins/overseer && poetry run pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.store'`.

- [ ] **Step 3: Write the implementation**

`plugins/overseer/scripts/store.py`:

```python
"""Filesystem operations for the .workflow/ tree. Single-writer by convention."""
from __future__ import annotations

import re
from pathlib import Path

from scripts.models import Card, CardParseError

WORKFLOW_DIRNAME = ".workflow"
_MINTED_ID_RE = re.compile(r"\AWF-(\d+)-")


def workflow_root(repo_root: Path) -> Path:
    return repo_root / WORKFLOW_DIRNAME


def init_workflow(repo_root: Path) -> Path:
    root = workflow_root(repo_root)
    for sub in ("cards", "sprints", "archive/cards", "archive/corrupt"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    gitignore = repo_root / ".gitignore"
    existing = gitignore.read_text() if gitignore.exists() else ""
    if f"{WORKFLOW_DIRNAME}/" not in existing.split("\n"):
        suffix = "" if existing in ("", "\n") or existing.endswith("\n") else "\n"
        gitignore.write_text(f"{existing}{suffix}{WORKFLOW_DIRNAME}/\n")
    return root


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:40].rstrip("-")


def mint_id(root: Path) -> str:
    highest = 0
    for directory in (root / "cards", root / "archive" / "cards"):
        for path in directory.glob("WF-*.md"):
            match = _MINTED_ID_RE.match(path.name)
            if match:
                highest = max(highest, int(match.group(1)))
    return f"WF-{highest + 1:03d}"


def card_path(root: Path, card: Card) -> Path:
    return root / "cards" / f"{card.id}-{slugify(card.title)}.md"


def find_card_path(root: Path, card_id: str) -> Path:
    matches = sorted((root / "cards").glob(f"{card_id}-*.md"))
    if not matches:
        raise FileNotFoundError(f"no live card with id {card_id}")
    return matches[0]


def load_card(path: Path) -> Card:
    try:
        return Card.from_text(path.read_text())
    except CardParseError as exc:
        raise CardParseError(f"{path.name}: {exc}") from exc


def save_card(root: Path, card: Card) -> Path:
    path = card_path(root, card)
    path.write_text(card.to_text())
    return path


def quarantine(root: Path, path: Path) -> Path:
    target = root / "archive" / "corrupt" / path.name
    path.rename(target)
    return target


def load_live_cards(root: Path) -> tuple[list[Card], list[Path]]:
    cards: list[Card] = []
    quarantined: list[Path] = []
    for path in sorted((root / "cards").glob("*.md")):
        try:
            cards.append(load_card(path))
        except CardParseError:
            quarantined.append(quarantine(root, path))
    cards.sort(key=lambda c: c.id)
    return cards, quarantined


def archive_card(root: Path, card: Card) -> Path:
    target = root / "archive" / "cards" / f"{card.id}-{slugify(card.title)}.md"
    target.write_text(card.to_text())
    live = card_path(root, card)
    if live.exists():
        live.unlink()
    return target


def load_archived_cards(root: Path) -> list[Card]:
    cards = []
    for path in (root / "archive" / "cards").glob("*.md"):
        try:
            cards.append(Card.from_text(path.read_text()))
        except CardParseError:
            continue
    return sorted(cards, key=lambda c: c.updated, reverse=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/overseer && poetry run pytest tests/test_store.py -v`
Expected: PASS (13 tests).

- [ ] **Step 5: Lint, type-check, commit**

Run: `cd plugins/overseer && poetry run ruff check scripts tests && poetry run mypy scripts`

```bash
git add plugins/overseer
git commit -m "feat(overseer): .workflow/ store with quarantine and archive"
```

---

### Task 5: Index — `ledger.md` generation

**Files:**
- Create: `plugins/overseer/scripts/index.py`
- Test: `plugins/overseer/tests/test_index.py`

**Interfaces:**
- Consumes: `Card`, `format_tokens` (Tasks 2–3); `load_live_cards`, `load_archived_cards`, `workflow_root` (Task 4).
- Produces:
  - `generate_index(project: str, cards: list[Card], recently_done: list[Card], now: str) -> str` — pure.
  - `rebuild_index(repo_root: Path, project: str, now: str) -> list[Path]` — loads cards (quarantining corrupt ones), takes the 5 newest archived cards, writes `ledger.md` under the workflow root, returns quarantined paths.

- [ ] **Step 1: Write the failing tests**

`plugins/overseer/tests/test_index.py`:

```python
from scripts.index import generate_index, rebuild_index
from scripts.models import Card
from scripts.store import init_workflow, save_card

NOW = "2026-07-08T14:32"


def card(card_id: str, **overrides: object) -> Card:
    fields = dict(
        id=card_id, title=f"Title {card_id}", status="planned",
        created="2026-07-08", updated="2026-07-08T10:00", body="## Goal\nx",
    )
    fields.update(overrides)
    return Card(**fields)  # type: ignore[arg-type]


class TestGenerateIndex:
    def test_in_flight_row(self):
        c = card("WF-012", status="in-flight", stage="implementation",
                 complexity="M", budget_estimate=400_000, budget_actual=310_000)
        out = generate_index("pip-skills", [c], [], NOW)
        assert "# Ledger — pip-skills" in out
        assert f"Updated: {NOW}" in out
        assert "| WF-012 | Title WF-012 | implementation | M | 310k/400k | — |" in out

    def test_review_stage_shows_round(self):
        c = card("WF-012", status="in-flight", stage="impl-review")
        c.log_review("impl-review", 2, "found wanting", NOW)
        c.log_review("impl-review", 2, "found wanting again", NOW)
        out = generate_index("p", [c], [], NOW)
        assert "impl-review (r2)" in out

    def test_blocked_card_shouts(self):
        c = card("WF-014", status="blocked", stage="planning",
                 blocked_on="user: scope Q")
        out = generate_index("p", [c], [], NOW)
        assert "| BLOCKED |" in out
        assert "user: scope Q" in out

    def test_tripwire_noted(self):
        c = card("WF-013", status="in-flight", stage="implementation",
                 budget_estimate=100_000, budget_actual=250_000)
        out = generate_index("p", [c], [], NOW)
        assert "2× BUDGET" in out

    def test_planned_and_done_sections(self):
        planned = card("WF-015", complexity="S", budget_estimate=150_000,
                       sprint="2026-07-S1")
        done = card("WF-011", status="done", updated="2026-07-07T18:00",
                    budget_estimate=250_000, budget_actual=210_000)
        out = generate_index("p", [planned], [done], NOW)
        assert "- WF-015 — Title WF-015 (S, ~150k, sprint 2026-07-S1)" in out
        assert "- WF-011 — done 2026-07-07, 210k/250k" in out

    def test_empty_ledger(self):
        out = generate_index("p", [], [], NOW)
        assert "_Nothing in flight._" in out


class TestRebuildIndex:
    def test_writes_ledger_and_self_heals(self, tmp_path):
        root = init_workflow(tmp_path)
        save_card(root, card("WF-001", status="in-flight", stage="planning"))
        (root / "cards" / "WF-002-bad.md").write_text("garbage")
        (root / "ledger.md").write_text("stale nonsense")
        quarantined = rebuild_index(tmp_path, "proj", NOW)
        content = (root / "ledger.md").read_text()
        assert "WF-001" in content and "stale nonsense" not in content
        assert len(quarantined) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd plugins/overseer && poetry run pytest tests/test_index.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.index'`.

- [ ] **Step 3: Write the implementation**

`plugins/overseer/scripts/index.py`:

```python
"""ledger.md generation. The index is a view; card files are the truth."""
from __future__ import annotations

from pathlib import Path

from scripts.models import Card, format_tokens
from scripts.store import load_archived_cards, load_live_cards, workflow_root

RECENTLY_DONE_LIMIT = 5


def _budget_cell(card: Card) -> str:
    actual = format_tokens(card.budget_actual) or "0"
    estimate = format_tokens(card.budget_estimate) or "?"
    return f"{actual}/{estimate}"


def _in_flight_row(card: Card) -> str:
    if card.status == "blocked":
        stage = "BLOCKED"
        note = card.blocked_on or "blocked"
    else:
        stage = card.stage or "—"
        if card.stage and card.stage.endswith("review"):
            rounds = card.review_rounds(card.stage)
            if rounds:
                stage = f"{stage} (r{rounds})"
        note = "2× BUDGET" if card.tripwire_breached else "—"
    return (
        f"| {card.id} | {card.title} | {stage} | {card.complexity or '?'} "
        f"| {_budget_cell(card)} | {note} |"
    )


def generate_index(
    project: str, cards: list[Card], recently_done: list[Card], now: str
) -> str:
    in_flight = [c for c in cards if c.status in ("in-flight", "blocked")]
    planned = [c for c in cards if c.status == "planned"]

    lines = [f"# Ledger — {project}", f"Updated: {now}", "", "## In flight"]
    if in_flight:
        lines += [
            "| Card | Title | Stage | Complexity | Budget (act/est) | Note |",
            "|---|---|---|---|---|---|",
        ]
        lines += [_in_flight_row(c) for c in in_flight]
    else:
        lines.append("_Nothing in flight._")

    lines += ["", "## Planned"]
    if planned:
        for c in planned:
            estimate = format_tokens(c.budget_estimate) or "?"
            sprint = f", sprint {c.sprint}" if c.sprint else ""
            lines.append(f"- {c.id} — {c.title} ({c.complexity or '?'}, ~{estimate}{sprint})")
    else:
        lines.append("_Backlog empty._")

    lines += ["", "## Recently done"]
    if recently_done:
        for c in recently_done:
            day = c.updated[:10] if c.updated else "?"
            lines.append(f"- {c.id} — {c.status} {day}, {_budget_cell(c)}")
    else:
        lines.append("_Nothing yet._")

    return "\n".join(lines) + "\n"


def rebuild_index(repo_root: Path, project: str, now: str) -> list[Path]:
    root = workflow_root(repo_root)
    cards, quarantined = load_live_cards(root)
    recently_done = load_archived_cards(root)[:RECENTLY_DONE_LIMIT]
    (root / "ledger.md").write_text(generate_index(project, cards, recently_done, now))
    return quarantined
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/overseer && poetry run pytest tests/test_index.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Lint, type-check, commit**

Run: `cd plugins/overseer && poetry run ruff check scripts tests && poetry run mypy scripts`

```bash
git add plugins/overseer
git commit -m "feat(overseer): ledger.md index generation with self-healing rebuild"
```

---

### Task 6: Sprints — model and rollup

**Files:**
- Create: `plugins/overseer/scripts/sprints.py`
- Test: `plugins/overseer/tests/test_sprints.py`

**Interfaces:**
- Consumes: `split_frontmatter`, `parse_tokens`, `format_tokens`, `CardParseError`, `Card` (Tasks 1–3).
- Produces:
  - `@dataclass Sprint` — fields `id: str, status: str ("planned"|"active"|"closed"), budget_estimate: int | None, budget_actual: int, started: str, body: str`; `Sprint.from_text` / `to_text` mirroring `Card`.
  - `replace_section(body: str, header: str, content: str) -> str` — replaces the content of a `## ` section (creating it if absent).
  - `rollup(sprint: Sprint, cards: list[Card]) -> Sprint` — filters cards where `card.sprint == sprint.id`, rebuilds the `## Cards` table, sets `budget_actual` to the sum of card actuals and `budget_estimate` to the sum of card estimates (None if no card has one). Returns a new Sprint.
  - `sprint_path(root: Path, sprint_id: str) -> Path` — `sprints/{id}.md`; `load_sprint(path) -> Sprint`; `save_sprint(root: Path, sprint: Sprint) -> Path`.

- [ ] **Step 1: Write the failing tests**

`plugins/overseer/tests/test_sprints.py`:

```python
import pytest

from scripts.models import Card, CardParseError
from scripts.sprints import Sprint, replace_section, rollup, save_sprint
from scripts.store import init_workflow

SAMPLE_SPRINT = """---
id: 2026-07-S1
status: active
budget:
  estimate: 2.1M
  actual: 840k
started: 2026-07-07
---

## Goal
Ship the thing.

## Cards
| Card | Complexity | Est | Actual | Status |
|---|---|---|---|---|
| WF-001 | S | 100k | 0 | planned |

## Conflicts

## Retro
"""


def card(card_id: str, **overrides: object) -> Card:
    fields = dict(
        id=card_id, title=f"T {card_id}", status="in-flight", stage="implementation",
        sprint="2026-07-S1", created="2026-07-08", updated="2026-07-08T10:00", body="x",
    )
    fields.update(overrides)
    return Card(**fields)  # type: ignore[arg-type]


class TestSprintParse:
    def test_round_trip(self):
        sprint = Sprint.from_text(SAMPLE_SPRINT)
        assert sprint.id == "2026-07-S1"
        assert sprint.status == "active"
        assert sprint.budget_estimate == 2_100_000
        assert sprint.budget_actual == 840_000
        assert Sprint.from_text(sprint.to_text()) == sprint

    def test_bad_status_raises(self):
        with pytest.raises(CardParseError):
            Sprint.from_text("---\nid: S1\nstatus: running\n---\nx")


class TestReplaceSection:
    def test_replaces_content(self):
        body = "## Goal\nold goal\n\n## Cards\nold table\n\n## Retro\nkeep"
        out = replace_section(body, "## Cards", "new table")
        assert "new table" in out and "old table" not in out
        assert "old goal" in out and "keep" in out

    def test_creates_missing_section(self):
        out = replace_section("## Goal\nhi", "## Cards", "table")
        assert "## Cards\ntable" in out


class TestRollup:
    def test_rebuilds_table_and_budget(self):
        sprint = Sprint.from_text(SAMPLE_SPRINT)
        cards = [
            card("WF-001", complexity="M", budget_estimate=400_000,
                 budget_actual=310_000),
            card("WF-002", complexity="L", status="blocked",
                 budget_estimate=900_000, budget_actual=80_000),
            card("WF-099", sprint="other-sprint", budget_actual=999_999),
        ]
        rolled = rollup(sprint, cards)
        assert "| WF-001 | M | 400k | 310k | in-flight |" in rolled.body
        assert "| WF-002 | L | 900k | 80k | blocked |" in rolled.body
        assert "WF-099" not in rolled.body
        assert rolled.budget_actual == 390_000
        assert rolled.budget_estimate == 1_300_000

    def test_save(self, tmp_path):
        root = init_workflow(tmp_path)
        path = save_sprint(root, Sprint.from_text(SAMPLE_SPRINT))
        assert path == root / "sprints" / "2026-07-S1.md"
        assert path.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd plugins/overseer && poetry run pytest tests/test_sprints.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.sprints'`.

- [ ] **Step 3: Write the implementation**

`plugins/overseer/scripts/sprints.py`:

```python
"""Sprint files: parse/serialise and card-table rollup."""
from __future__ import annotations

from dataclasses import dataclass, replace as dc_replace
from pathlib import Path

import yaml

from scripts.models import (
    Card,
    CardParseError,
    format_tokens,
    parse_tokens,
    split_frontmatter,
)

SPRINT_STATUSES = {"planned", "active", "closed"}


@dataclass
class Sprint:
    id: str
    status: str = "planned"
    budget_estimate: int | None = None
    budget_actual: int = 0
    started: str = ""
    body: str = ""

    @classmethod
    def from_text(cls, text: str) -> "Sprint":
        meta, body = split_frontmatter(text)
        for key in ("id", "status"):
            if not meta.get(key):
                raise CardParseError(f"missing required field: {key}")
        status = str(meta["status"])
        if status not in SPRINT_STATUSES:
            raise CardParseError(f"unknown sprint status: {status!r}")
        budget = meta.get("budget") or {}
        return cls(
            id=str(meta["id"]),
            status=status,
            budget_estimate=parse_tokens(budget.get("estimate")),
            budget_actual=parse_tokens(budget.get("actual")) or 0,
            started=str(meta.get("started", "")),
            body=body.strip(),
        )

    def to_text(self) -> str:
        meta = {
            "id": self.id,
            "status": self.status,
            "budget": {
                "estimate": format_tokens(self.budget_estimate),
                "actual": format_tokens(self.budget_actual),
            },
            "started": self.started,
        }
        front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
        return f"---\n{front}\n---\n\n{self.body.strip()}\n"


def replace_section(body: str, header: str, content: str) -> str:
    """Replace the content of the named `## ` section, creating it if absent."""
    lines = body.split("\n")
    if header not in lines:
        return f"{body.rstrip()}\n\n{header}\n{content}"
    start = lines.index(header)
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    return "\n".join(lines[: start + 1] + [content, ""] + lines[end:]).rstrip()


def rollup(sprint: Sprint, cards: list[Card]) -> Sprint:
    mine = sorted((c for c in cards if c.sprint == sprint.id), key=lambda c: c.id)
    rows = [
        "| Card | Complexity | Est | Actual | Status |",
        "|---|---|---|---|---|",
    ]
    for c in mine:
        est = format_tokens(c.budget_estimate) or "?"
        act = format_tokens(c.budget_actual) or "0"
        rows.append(f"| {c.id} | {c.complexity or '?'} | {est} | {act} | {c.status} |")
    estimates = [c.budget_estimate for c in mine if c.budget_estimate is not None]
    return dc_replace(
        sprint,
        body=replace_section(sprint.body, "## Cards", "\n".join(rows)),
        budget_actual=sum(c.budget_actual for c in mine),
        budget_estimate=sum(estimates) if estimates else None,
    )


def sprint_path(root: Path, sprint_id: str) -> Path:
    return root / "sprints" / f"{sprint_id}.md"


def load_sprint(path: Path) -> Sprint:
    return Sprint.from_text(path.read_text())


def save_sprint(root: Path, sprint: Sprint) -> Path:
    path = sprint_path(root, sprint.id)
    path.write_text(sprint.to_text())
    return path
```

Note on `replace_section`: section splicing is easy to get wrong — the tests are the arbiter. If the implementation above produces doubled blank lines, `re.sub(r"\n{3,}", "\n\n", ...)` the result — behaviour over cleverness; the tests define correctness.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/overseer && poetry run pytest tests/test_sprints.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Lint, type-check, commit**

Run: `cd plugins/overseer && poetry run ruff check scripts tests && poetry run mypy scripts`

```bash
git add plugins/overseer
git commit -m "feat(overseer): sprint model with card-table rollup"
```

---

### Task 7: Resume — session-start report

**Files:**
- Create: `plugins/overseer/scripts/resume.py`
- Test: `plugins/overseer/tests/test_resume.py`

**Interfaces:**
- Consumes: `Card` (Tasks 2–3); `load_live_cards`, `workflow_root` (Task 4); `format_tokens` (Task 1).
- Produces:
  - `resume_entries(repo_root: Path) -> list[dict]` — one dict per in-flight/blocked card: `{"id", "title", "status", "stage", "round", "branch", "worktree", "worktree_exists", "blocked_on", "budget"}`. `round` is the review round for the current stage (0 if not a review stage); `worktree_exists` checks the recorded path relative to `repo_root`; `budget` is `"310k/400k"`.
  - `format_report(entries: list[dict]) -> str` — human-readable lines; `"Nothing in flight — clean slate."` when empty.

- [ ] **Step 1: Write the failing tests**

`plugins/overseer/tests/test_resume.py`:

```python
from scripts.models import Card
from scripts.resume import format_report, resume_entries
from scripts.store import init_workflow, save_card

NOW = "2026-07-08T15:00"


def card(card_id: str, **overrides: object) -> Card:
    fields = dict(
        id=card_id, title=f"T {card_id}", status="in-flight", stage="implementation",
        created="2026-07-08", updated=NOW, body="## Review log\n\n## Progress log",
    )
    fields.update(overrides)
    return Card(**fields)  # type: ignore[arg-type]


class TestResumeEntries:
    def test_reports_in_flight_and_blocked_only(self, tmp_path):
        root = init_workflow(tmp_path)
        save_card(root, card("WF-001"))
        save_card(root, card("WF-002", status="blocked", blocked_on="user: q"))
        save_card(root, card("WF-003", status="planned", stage=None))
        entries = resume_entries(tmp_path)
        assert [e["id"] for e in entries] == ["WF-001", "WF-002"]
        assert entries[1]["blocked_on"] == "user: q"

    def test_review_round_and_worktree_check(self, tmp_path):
        root = init_workflow(tmp_path)
        c = card("WF-001", stage="impl-review", worktree="wt/WF-001",
                 budget_estimate=400_000, budget_actual=310_000)
        c.log_review("impl-review", 2, "found wanting", NOW)
        c.log_review("impl-review", 2, "found wanting", NOW)
        save_card(root, c)
        (tmp_path / "wt" / "WF-001").mkdir(parents=True)
        entry = resume_entries(tmp_path)[0]
        assert entry["round"] == 2
        assert entry["worktree_exists"] is True
        assert entry["budget"] == "310k/400k"

    def test_missing_worktree_flagged(self, tmp_path):
        root = init_workflow(tmp_path)
        save_card(root, card("WF-001", worktree="gone/away"))
        assert resume_entries(tmp_path)[0]["worktree_exists"] is False


class TestFormatReport:
    def test_empty(self):
        assert "clean slate" in format_report([])

    def test_lines(self, tmp_path):
        root = init_workflow(tmp_path)
        save_card(root, card("WF-001", stage="verification"))
        report = format_report(resume_entries(tmp_path))
        assert "WF-001" in report and "verification" in report
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd plugins/overseer && poetry run pytest tests/test_resume.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.resume'`.

- [ ] **Step 3: Write the implementation**

`plugins/overseer/scripts/resume.py`:

```python
"""Session-start resume detection: what was in flight, and at what stage."""
from __future__ import annotations

from pathlib import Path

from scripts.models import Card, format_tokens
from scripts.store import load_live_cards, workflow_root


def _entry(repo_root: Path, card: Card) -> dict:
    worktree_exists = bool(card.worktree) and (repo_root / card.worktree).is_dir()
    round_no = (
        card.review_rounds(card.stage)
        if card.stage and card.stage.endswith("review")
        else 0
    )
    actual = format_tokens(card.budget_actual) or "0"
    estimate = format_tokens(card.budget_estimate) or "?"
    return {
        "id": card.id,
        "title": card.title,
        "status": card.status,
        "stage": card.stage,
        "round": round_no,
        "branch": card.branch,
        "worktree": card.worktree,
        "worktree_exists": worktree_exists,
        "blocked_on": card.blocked_on,
        "budget": f"{actual}/{estimate}",
    }


def resume_entries(repo_root: Path) -> list[dict]:
    cards, _ = load_live_cards(workflow_root(repo_root))
    return [
        _entry(repo_root, c) for c in cards if c.status in ("in-flight", "blocked")
    ]


def format_report(entries: list[dict]) -> str:
    if not entries:
        return "Nothing in flight — clean slate."
    lines = []
    for e in entries:
        stage = f"BLOCKED ({e['blocked_on']})" if e["status"] == "blocked" else e["stage"]
        if e["round"]:
            stage = f"{stage}, round {e['round']}"
        worktree = e["worktree"] or "no worktree"
        if e["worktree"] and not e["worktree_exists"]:
            worktree += " (MISSING)"
        lines.append(f"- {e['id']} — {e['title']}: {stage} | {worktree} | {e['budget']}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/overseer && poetry run pytest tests/test_resume.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Lint, type-check, commit**

Run: `cd plugins/overseer && poetry run ruff check scripts tests && poetry run mypy scripts`

```bash
git add plugins/overseer
git commit -m "feat(overseer): resume report for session-start recovery"
```

---

### Task 8: CLI — the skill's interface

**Files:**
- Create: `plugins/overseer/scripts/cli.py`
- Test: `plugins/overseer/tests/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `main(argv: list[str] | None = None) -> int` and subcommands, all taking `--root <repo-root>` (default `.`):
  - `init` — create tree + gitignore + empty index.
  - `new-card --title T [--jira KEY] [--complexity S|M|L] [--sprint ID] [--estimate 400k] [--goal TEXT]` — id = jira key if given else minted; prints the id.
  - `set-stage CARD_ID STAGE`, `block CARD_ID --reason R`, `unblock CARD_ID`, `done CARD_ID`, `abandon CARD_ID` — `done`/`abandon` archive the card.
  - `set-field CARD_ID --branch B --worktree W` (either or both).
  - `log-progress CARD_ID --note N --tokens 120k` — exit code 2 + warning on tripwire breach.
  - `log-review CARD_ID --stage S --reviewers 2 --verdict V`.
  - `new-sprint SPRINT_ID [--estimate 2.1M] [--goal TEXT]`, `rollup-sprint SPRINT_ID`.
  - `rebuild-index`, `resume [--json]`.
  - Every card mutation: save card → rebuild index (in that order). Project name for the index = `repo_root.resolve().name`.
  - Errors (`CardParseError`, `FileNotFoundError`) print `error: ...` to stderr, exit 1.

- [ ] **Step 1: Write the failing tests**

`plugins/overseer/tests/test_cli.py`:

```python
import json

import pytest

from scripts.cli import main
from scripts.store import find_card_path, workflow_root


@pytest.fixture
def repo(tmp_path):
    assert main(["--root", str(tmp_path), "init"]) == 0
    return tmp_path


def run(repo, *argv: str) -> int:
    return main(["--root", str(repo), *argv])


class TestInitAndNewCard:
    def test_init_creates_tree_and_index(self, repo):
        root = workflow_root(repo)
        assert (root / "ledger.md").exists()
        assert (root / "cards").is_dir()

    def test_new_card_minted_id(self, repo, capsys):
        assert run(repo, "new-card", "--title", "Fix the thing",
                   "--complexity", "M", "--estimate", "400k") == 0
        assert "WF-001" in capsys.readouterr().out
        card_file = find_card_path(workflow_root(repo), "WF-001")
        content = card_file.read_text()
        assert "estimate: 400k" in content and "## Goal" in content

    def test_new_card_jira_id(self, repo, capsys):
        run(repo, "new-card", "--title", "Webhooks", "--jira", "PROJ-142")
        assert "PROJ-142" in capsys.readouterr().out

    def test_new_card_updates_index(self, repo):
        run(repo, "new-card", "--title", "Fix the thing")
        assert "WF-001" in (workflow_root(repo) / "ledger.md").read_text()


class TestLifecycle:
    def test_stage_and_block_flow(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "set-stage", "WF-001", "planning") == 0
        assert run(repo, "block", "WF-001", "--reason", "user: q") == 0
        ledger = (workflow_root(repo) / "ledger.md").read_text()
        assert "BLOCKED" in ledger
        assert run(repo, "unblock", "WF-001") == 0

    def test_done_archives(self, repo):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "done", "WF-001") == 0
        root = workflow_root(repo)
        assert not list((root / "cards").glob("WF-001-*"))
        assert list((root / "archive" / "cards").glob("WF-001-*"))
        assert "Recently done" in (root / "ledger.md").read_text()

    def test_unknown_card_errors(self, repo, capsys):
        assert run(repo, "set-stage", "WF-999", "planning") == 1
        assert "error:" in capsys.readouterr().err


class TestProgressAndReview:
    def test_log_progress(self, repo):
        run(repo, "new-card", "--title", "T", "--estimate", "400k")
        assert run(repo, "log-progress", "WF-001", "--note", "step 1",
                   "--tokens", "120k") == 0
        content = find_card_path(workflow_root(repo), "WF-001").read_text()
        assert "step 1 (~120k tokens)" in content and "actual: 120k" in content

    def test_tripwire_exit_code(self, repo, capsys):
        run(repo, "new-card", "--title", "T", "--estimate", "100k")
        assert run(repo, "log-progress", "WF-001", "--note", "burn",
                   "--tokens", "250k") == 2
        assert "TRIPWIRE" in capsys.readouterr().err

    def test_log_review(self, repo):
        run(repo, "new-card", "--title", "T")
        run(repo, "set-stage", "WF-001", "plan-review")
        assert run(repo, "log-review", "WF-001", "--stage", "plan-review",
                   "--reviewers", "2", "--verdict", "approved") == 0
        content = find_card_path(workflow_root(repo), "WF-001").read_text()
        assert "### plan-review — round 1 (2 reviewers)" in content


class TestSprintsAndResume:
    def test_sprint_rollup(self, repo):
        run(repo, "new-sprint", "2026-07-S1", "--estimate", "2.1M")
        run(repo, "new-card", "--title", "T", "--sprint", "2026-07-S1",
            "--estimate", "400k")
        assert run(repo, "rollup-sprint", "2026-07-S1") == 0
        sprint = (workflow_root(repo) / "sprints" / "2026-07-S1.md").read_text()
        assert "| WF-001 |" in sprint

    def test_resume_json(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        run(repo, "set-stage", "WF-001", "implementation")
        capsys.readouterr()
        assert run(repo, "resume", "--json") == 0
        entries = json.loads(capsys.readouterr().out)
        assert entries[0]["id"] == "WF-001"

    def test_resume_empty(self, repo, capsys):
        assert run(repo, "resume") == 0
        assert "clean slate" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd plugins/overseer && poetry run pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.cli'`.

- [ ] **Step 3: Write the implementation**

`plugins/overseer/scripts/cli.py`:

```python
"""Overseer ledger CLI — the interface the ledger skill drives.

Single-writer by convention: only the orchestrating session calls this.
Every mutation writes the card file first, then regenerates the index.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from scripts.index import rebuild_index
from scripts.models import Card, CardParseError, format_tokens, parse_tokens
from scripts.resume import format_report, resume_entries
from scripts.sprints import Sprint, load_sprint, rollup, save_sprint, sprint_path
from scripts.store import (
    archive_card,
    find_card_path,
    init_workflow,
    load_card,
    load_live_cards,
    mint_id,
    save_card,
    workflow_root,
)

CARD_BODY_TEMPLATE = """## Goal
{goal}

## Plan
_(pending)_

## Decisions

## Review log

## Progress log

## Verification
"""

SPRINT_BODY_TEMPLATE = """## Goal
{goal}

## Cards
| Card | Complexity | Est | Actual | Status |
|---|---|---|---|---|

## Conflicts

## Retro
"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _sync(repo_root: Path, card: Card) -> None:
    """Write ordering per spec: card first, then the index view."""
    root = workflow_root(repo_root)
    save_card(root, card)
    rebuild_index(repo_root, repo_root.resolve().name, _now())


def _load(repo_root: Path, card_id: str) -> Card:
    return load_card(find_card_path(workflow_root(repo_root), card_id))


def cmd_init(args: argparse.Namespace) -> int:
    init_workflow(args.root)
    rebuild_index(args.root, args.root.resolve().name, _now())
    print(f"initialised {workflow_root(args.root)}")
    return 0


def cmd_new_card(args: argparse.Namespace) -> int:
    root = workflow_root(args.root)
    card = Card(
        id=args.jira or mint_id(root),
        title=args.title,
        status="planned",
        jira=args.jira,
        complexity=args.complexity,
        sprint=args.sprint,
        budget_estimate=parse_tokens(args.estimate),
        created=_today(),
        updated=_now(),
        body=CARD_BODY_TEMPLATE.format(goal=args.goal or "_(to be written)_"),
    )
    _sync(args.root, card)
    print(card.id)
    return 0


def cmd_set_stage(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    card.set_stage(args.stage, _now())
    _sync(args.root, card)
    print(f"{card.id} → {args.stage}")
    return 0


def cmd_block(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    card.block(args.reason, _now())
    _sync(args.root, card)
    print(f"{card.id} blocked: {args.reason}")
    return 0


def cmd_unblock(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    card.unblock(_now())
    _sync(args.root, card)
    print(f"{card.id} → {card.status}")
    return 0


def _close(args: argparse.Namespace, verb: str) -> int:
    card = _load(args.root, args.card_id)
    card.complete(_now()) if verb == "done" else card.abandon(_now())
    root = workflow_root(args.root)
    archive_card(root, card)
    rebuild_index(args.root, args.root.resolve().name, _now())
    print(f"{card.id} {card.status}, archived")
    return 0


def cmd_done(args: argparse.Namespace) -> int:
    return _close(args, "done")


def cmd_abandon(args: argparse.Namespace) -> int:
    return _close(args, "abandon")


def cmd_set_field(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    if args.branch:
        card.branch = args.branch
    if args.worktree:
        card.worktree = args.worktree
    card.updated = _now()
    _sync(args.root, card)
    print(f"{card.id} updated")
    return 0


def cmd_log_progress(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    tokens = parse_tokens(args.tokens) or 0
    card.log_progress(args.note, tokens, _now())
    _sync(args.root, card)
    if card.tripwire_breached:
        actual = format_tokens(card.budget_actual)
        estimate = format_tokens(card.budget_estimate)
        print(
            f"TRIPWIRE: {card.id} at {actual} vs estimate {estimate} — "
            "stop this card and escalate to the user",
            file=sys.stderr,
        )
        return 2
    return 0


def cmd_log_review(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    card.log_review(args.stage, args.reviewers, args.verdict, _now())
    _sync(args.root, card)
    print(f"{card.id} {args.stage} round {card.review_rounds(args.stage)} logged")
    return 0


def cmd_new_sprint(args: argparse.Namespace) -> int:
    sprint = Sprint(
        id=args.sprint_id,
        status="planned",
        budget_estimate=parse_tokens(args.estimate),
        started=_today(),
        body=SPRINT_BODY_TEMPLATE.format(goal=args.goal or "_(to be written)_"),
    )
    save_sprint(workflow_root(args.root), sprint)
    print(sprint.id)
    return 0


def cmd_rollup_sprint(args: argparse.Namespace) -> int:
    root = workflow_root(args.root)
    sprint = load_sprint(sprint_path(root, args.sprint_id))
    cards, _ = load_live_cards(root)
    save_sprint(root, rollup(sprint, cards))
    print(f"{args.sprint_id} rolled up")
    return 0


def cmd_rebuild_index(args: argparse.Namespace) -> int:
    quarantined = rebuild_index(args.root, args.root.resolve().name, _now())
    for path in quarantined:
        print(f"QUARANTINED: {path}", file=sys.stderr)
    print("index rebuilt")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    entries = resume_entries(args.root)
    print(json.dumps(entries, indent=2) if args.json else format_report(entries))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="overseer", description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init").set_defaults(func=cmd_init)

    p = sub.add_parser("new-card")
    p.add_argument("--title", required=True)
    p.add_argument("--jira")
    p.add_argument("--complexity", choices=["S", "M", "L"])
    p.add_argument("--sprint")
    p.add_argument("--estimate")
    p.add_argument("--goal")
    p.set_defaults(func=cmd_new_card)

    p = sub.add_parser("set-stage")
    p.add_argument("card_id")
    p.add_argument("stage")
    p.set_defaults(func=cmd_set_stage)

    p = sub.add_parser("block")
    p.add_argument("card_id")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_block)

    p = sub.add_parser("unblock")
    p.add_argument("card_id")
    p.set_defaults(func=cmd_unblock)

    for name, func in (("done", cmd_done), ("abandon", cmd_abandon)):
        p = sub.add_parser(name)
        p.add_argument("card_id")
        p.set_defaults(func=func)

    p = sub.add_parser("set-field")
    p.add_argument("card_id")
    p.add_argument("--branch")
    p.add_argument("--worktree")
    p.set_defaults(func=cmd_set_field)

    p = sub.add_parser("log-progress")
    p.add_argument("card_id")
    p.add_argument("--note", required=True)
    p.add_argument("--tokens", required=True)
    p.set_defaults(func=cmd_log_progress)

    p = sub.add_parser("log-review")
    p.add_argument("card_id")
    p.add_argument("--stage", required=True)
    p.add_argument("--reviewers", type=int, required=True)
    p.add_argument("--verdict", required=True)
    p.set_defaults(func=cmd_log_review)

    p = sub.add_parser("new-sprint")
    p.add_argument("sprint_id")
    p.add_argument("--estimate")
    p.add_argument("--goal")
    p.set_defaults(func=cmd_new_sprint)

    p = sub.add_parser("rollup-sprint")
    p.add_argument("sprint_id")
    p.set_defaults(func=cmd_rollup_sprint)

    sub.add_parser("rebuild-index").set_defaults(func=cmd_rebuild_index)

    p = sub.add_parser("resume")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_resume)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result: int = args.func(args)
        return result
    except (CardParseError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the full suite**

Run: `cd plugins/overseer && poetry run pytest -v`
Expected: PASS — all tests across all six test files.

- [ ] **Step 5: Lint, type-check, commit**

Run: `cd plugins/overseer && poetry run ruff check scripts tests && poetry run mypy scripts`

```bash
git add plugins/overseer
git commit -m "feat(overseer): ledger CLI with tripwire exit codes"
```

---

### Task 9: SKILL.md, README, marketplace registration

**Files:**
- Create: `plugins/overseer/skills/ledger/SKILL.md`
- Create: `plugins/overseer/README.md`
- Modify: `.claude-plugin/marketplace.json` (repo root — add overseer entry, bump version to 1.4.0)

**Interfaces:**
- Consumes: the CLI (Task 8) — the SKILL.md drives it exclusively; no direct file edits to `.workflow/` by the skill.

- [ ] **Step 1: Write the SKILL.md**

`plugins/overseer/skills/ledger/SKILL.md`:

````markdown
---
name: ledger
description: >
  Persistent per-repo work ledger: cards, stages, sprints, token budgets and
  session resume. Use when starting a piece of tracked work, when the user asks
  "what's in flight", "resume where we left off", "start a new card/task",
  "log progress", or at the start of any session in a repo with a .workflow/
  directory. Phase 1 of overseer — state only; orchestration arrives later.
---

# Overseer Ledger

Manage `.workflow/` — the single source of truth for planned, in-flight and
completed work in this repo. **Never edit `.workflow/` files directly**; drive
everything through the CLI so write-ordering (card first, index second) holds:

```bash
python plugins/overseer/scripts/cli.py --root <repo-root> <command> ...
```

(When overseer is installed as a plugin, the scripts live under the plugin
root instead — locate `cli.py` relative to this SKILL.md.)

## On invocation — always check for in-flight work first

```bash
python .../cli.py --root . resume
```

- If cards are in flight, report them to the user and offer per card:
  **resume / park as blocked / abandon**. Never silently start fresh.
- Resuming a card: read its file under `.workflow/cards/`, re-enter at the
  recorded stage — never earlier, never assume later. If the report shows
  `(MISSING)` next to the worktree, recreate it from the recorded branch
  before continuing.
- If `.workflow/` does not exist and the user wants tracked work: run `init`.

## Starting a new piece of work

1. `new-card --title "..." [--jira PROJ-142] [--complexity S|M|L] [--estimate 300k] [--goal "..."]`
   - Use the Jira key as the id when one exists; otherwise an id is minted.
   - Complexity bands for estimates: S ≈ 100–200k, M ≈ 300–500k, L ≈ 700k+.
2. `set-stage <id> bootstrap`, then: pull latest main, create a worktree and
   branch (branch name: `<type>/<id>-<slug>`), record them with
   `set-field <id> --branch ... --worktree ...`.
3. Advance stages as work proceeds:
   `bootstrap → planning → plan-review → implementation → impl-review →
   verification → awaiting-merge`.

## During work

- **Progress:** `log-progress <id> --note "what happened" --tokens 120k`
  after each meaningful unit of work. Exit code 2 means the 2× budget
  tripwire fired: **stop the card, tell the user why it overran.**
- **Reviews:** after each review round:
  `log-review <id> --stage plan-review --reviewers 2 --verdict "approved"`.
  Verdicts are short and factual ("found wanting — 2 findings, 1 mortal").
- **Blocked:** `block <id> --reason "user: <question>"` or
  `--reason "card: WF-011"`. `unblock <id>` when cleared.
- **Decisions:** significant decisions and trade-offs go in the card's
  `## Decisions` section — append via Edit on the card file is the one
  exception to the no-direct-edits rule, since prose is not state.

## Finishing

- `done <id>` when merged (archives the card); `abandon <id>` otherwise.
- The verification stage requires evidence in the card's `## Verification`
  section: test output, mypy/ruff results, end-to-end observation. A card
  with an empty Verification section does not pass `awaiting-merge`.

## Sprints

- `new-sprint 2026-07-S1 --estimate 2.1M --goal "..."`, assign cards with
  `--sprint` at creation, and `rollup-sprint <id>` after any card change to
  refresh the sprint's card table and budget actuals.

## Reporting style

Concise and factual, with the odd dry aside. Lead with card id and stage;
budgets as `actual/estimate`. The user reads the index, not your transcript —
keep `ledger.md` the place where truth lives.
````

- [ ] **Step 2: Write the README**

`plugins/overseer/README.md`:

```markdown
# overseer

Workflow orchestration for serious engineering work. Phase 1: the ledger — a
persistent, per-repo record of cards, stages, sprints and token budgets that
survives session crashes and context loss.

## What it does

- `.workflow/` directory (gitignored) holding one markdown card per unit of
  work, a regenerated `ledger.md` index, and sprint files with budget rollups.
- Card lifecycle: `planned → in-flight → done`, with `blocked`/`abandoned`
  exits and seven in-flight stages from `bootstrap` to `awaiting-merge`.
- Token budgets with a 2× tripwire: overruns stop the card and escalate.
- Session resume: `resume` reports everything in flight and at what stage.
- Corrupt cards are quarantined to `archive/corrupt/`, never silently lost.

## Skills

- **ledger** — drive the `.workflow/` state through the CLI.

Later phases add orchestration (agent teams, adversarial review loops) and
sprint planning on top of these schemas.

## Development

```bash
cd plugins/overseer
poetry run pytest
poetry run ruff check scripts tests
poetry run mypy scripts
```

Design spec: `docs/superpowers/specs/2026-07-08-workflow-ledger-design.md`.
```

- [ ] **Step 3: Register in the marketplace**

In `.claude-plugin/marketplace.json`: bump `"version"` to `"1.4.0"` and append to `"plugins"`:

```json
{
  "name": "overseer",
  "source": "./plugins/overseer",
  "description": "Persistent work ledger: cards, stages, sprints and token budgets that survive session loss. Phase 1 of workflow orchestration.",
  "category": "engineering",
  "tags": ["workflow", "ledger", "sprints", "orchestration", "task-tracking", "budgets", "resume"]
}
```

- [ ] **Step 4: Smoke-test the skill's happy path end-to-end**

```bash
cd $(mktemp -d) && git init -q .
python <path-to>/plugins/overseer/scripts/cli.py init
python <path-to>/plugins/overseer/scripts/cli.py new-card --title "Smoke test" --complexity S --estimate 100k
python <path-to>/plugins/overseer/scripts/cli.py set-stage WF-001 planning
python <path-to>/plugins/overseer/scripts/cli.py log-progress WF-001 --note "planned" --tokens 20k
python <path-to>/plugins/overseer/scripts/cli.py resume
cat .workflow/ledger.md
```

Expected: resume shows `WF-001 — Smoke test: planning | no worktree | 20k/100k`; ledger shows the in-flight table; exit codes all 0.

- [ ] **Step 5: Full suite, lint, type-check, commit**

Run: `cd plugins/overseer && poetry run pytest && poetry run ruff check scripts tests && poetry run mypy scripts`

```bash
git add plugins/overseer .claude-plugin/marketplace.json
git commit -m "feat(overseer): ledger skill, README and marketplace registration"
```

---

## Self-Review Notes

- **Spec coverage:** directory layout (T4 init), lifecycle + stages (T2–T3), card schema (T2), index as regenerated view + self-heal (T5), sprint + rollup + budget rules (T6), 2× tripwire (T3 model, T8 exit code), resume semantics (T7, SKILL.md), corruption quarantine (T4), write ordering (T8 `_sync`), gitignore (T4). Conflicts-section *detection* is later-phase (sprint planning); the section exists in the template (T8).
- **Out of scope confirmed:** no agent spawning, no Jira API sync (the `--jira` flag only records the key), no worktree creation in code (the SKILL.md instructs the session to do it and record it).
- **Type consistency check done:** `parse_tokens`/`format_tokens` signatures match across T1/T6/T8; `load_live_cards` returns `(cards, quarantined)` everywhere; `Card` field names identical in T2 dataclass, T4 fixtures, T8 CLI.
