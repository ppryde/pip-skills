# Overseer Card Relationships Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add emergent epics (`parent`), structured dependencies (`depends_on`) with computed readiness gating, and a `parked` soft-shelf status to overseer's card model, surfaced in the index/resume and governed by doctrine.

**Architecture:** Two new `Card` fields + one status, kept as pure data; a new pure-function `relations.py` for derived helpers (children/epic-rollup/readiness/cycle-checks); CLI verbs that validate edges before writing through the existing single-writer path; light text rendering in `index.py`/`resume.py`; doctrine in the `ledger`/`orchestrate` skills. Rich visuals are out of scope (dashboard is Spec 3).

**Tech Stack:** Python 3.11 (stdlib + PyYAML), argparse CLI, pytest.

## Global Constraints

- **Python 3.11**; `mypy` strict (`disallow_untyped_defs = true`) — annotate every `def`. `ruff` line-length 100.
- **Run gates from `plugins/overseer/`** via the worktree venv: `../../.venv/bin/python -m pytest -q`, `../../.venv/bin/ruff check scripts tests`, `../../.venv/bin/mypy scripts`.
- **Follow house patterns:** `from __future__ import annotations`; `Card` stays a pure data holder (edge validation lives in the CLI, like `touches`/`conflicts`); single-writer via `_sync` (card first, then index); quarantine-safe derived reads (unknown ids surfaced, never raised).
- **Model facts (verbatim from the spec):** statuses become `{planned, in-flight, blocked, parked, done, abandoned}`. `blocked_on` is retained for human/agent blocks only; card→card ordering is `depends_on`. Cycles rejected for both `parent` (tree) and `depends_on` (DAG). `unpark` → `in-flight` if `stage` set else `planned`. Rollup is display-only over **direct** children.
- **No `__pycache__`/`.pyc` committed** (globally gitignored).
- **Commit after each task** with a `feat(overseer):`/`docs(overseer):` prefix ending with the two trailer lines this session requires.
- **Do NOT touch `vigil`** — this branch forked from the vigil work; overseer is post-extraction. All work is under `plugins/overseer/`.

---

## File Structure

- **Modify `scripts/models.py`** — add `parent`, `depends_on`, `parked` status + `park`/`unpark` (Task 1).
- **Create `scripts/relations.py`** — pure derived helpers (Task 2).
- **Modify `scripts/cli.py`** — `set-field --parent`, `depends`, `park`/`unpark` (Task 3).
- **Modify `scripts/index.py`** — Epics + Parked sections, readiness, standalone filtering (Task 4).
- **Modify `scripts/resume.py`** — readiness/epic/parked in entries + handoff (Task 5).
- **Modify `skills/ledger/SKILL.md` + `skills/orchestrate/` doctrine** (Task 6).
- **Tests:** `tests/test_models.py`, new `tests/test_relations.py`, `tests/test_cli.py`, `tests/test_index.py`, `tests/test_resume.py`.

---

## Task 1: Model — `parent`, `depends_on`, `parked`

**Files:**
- Modify: `plugins/overseer/scripts/models.py`
- Test: `plugins/overseer/tests/test_models.py`

**Interfaces:**
- Produces: `Card.parent: str | None`, `Card.depends_on: list[str]`; `"parked"` in `STATUSES`; `Card.park(now: str) -> None`, `Card.unpark(now: str) -> None`.

- [ ] **Step 1: Write the failing tests**

Add to `plugins/overseer/tests/test_models.py`:

```python
class TestRelationsFields:
    def _card_text(self, extra=""):
        return (
            "---\n"
            "id: WF-001\n"
            "title: T\n"
            "status: planned\n"
            f"{extra}"
            "---\n\n## Goal\nx\n"
        )

    def test_parent_and_depends_parsed(self):
        from scripts.models import Card
        c = Card.from_text(self._card_text("parent: WF-010\ndepends_on:\n- WF-002\n- WF-003\n"))
        assert c.parent == "WF-010"
        assert c.depends_on == ["WF-002", "WF-003"]

    def test_depends_scalar_coerced_to_list(self):
        from scripts.models import Card
        c = Card.from_text(self._card_text("depends_on: WF-002\n"))
        assert c.depends_on == ["WF-002"]

    def test_defaults_when_absent(self):
        from scripts.models import Card
        c = Card.from_text(self._card_text())
        assert c.parent is None and c.depends_on == []

    def test_round_trip_preserves_relations(self):
        from scripts.models import Card
        c = Card.from_text(self._card_text("parent: WF-010\ndepends_on:\n- WF-002\n"))
        c2 = Card.from_text(c.to_text())
        assert c2.parent == "WF-010" and c2.depends_on == ["WF-002"]

    def test_parked_status_accepted(self):
        from scripts.models import Card
        c = Card.from_text(self._card_text().replace("status: planned", "status: parked"))
        assert c.status == "parked"


class TestParkUnpark:
    def _card(self, **kw):
        from scripts.models import Card
        base = dict(id="WF-001", title="T", status="in-flight", stage="implementation")
        base.update(kw)
        return Card(**base)  # type: ignore[arg-type]

    def test_park_sets_status_preserves_stage(self):
        c = self._card(branch="feat/x", worktree="wt/WF-001")
        c.park("2026-07-11T10:00")
        assert c.status == "parked"
        assert c.stage == "implementation" and c.branch == "feat/x" and c.worktree == "wt/WF-001"
        assert c.updated == "2026-07-11T10:00"

    def test_unpark_with_stage_returns_in_flight(self):
        c = self._card(status="parked")
        c.unpark("2026-07-11T11:00")
        assert c.status == "in-flight"

    def test_unpark_without_stage_returns_planned(self):
        c = self._card(status="parked", stage=None)
        c.unpark("2026-07-11T11:00")
        assert c.status == "planned"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_models.py::TestRelationsFields tests/test_models.py::TestParkUnpark -q`
Expected: FAIL — `parent`/`depends_on` unknown, `parked` rejected as unknown status.

- [ ] **Step 3: Implement the model changes**

In `plugins/overseer/scripts/models.py`:

1. Add `parked` to statuses:
```python
STATUSES = {"planned", "in-flight", "blocked", "parked", "done", "abandoned"}
```

2. Add two fields to the `Card` dataclass — insert `parent` after the `sprint` line and `depends_on` after the `touches` line:
```python
    sprint: str | None = None
    parent: str | None = None
```
and
```python
    touches: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
```

3. In `from_text`, after the `touches` parsing block, add depends_on parsing (mirror `touches`):
```python
        depends_raw = meta.get("depends_on")
        if isinstance(depends_raw, list):
            depends_on = [str(d) for d in depends_raw]
        elif depends_raw:
            depends_on = [str(depends_raw)]
        else:
            depends_on = []
```
and add to the `cls(...)` constructor call, alongside the existing kwargs:
```python
            sprint=meta.get("sprint"),
            parent=meta.get("parent"),
```
and
```python
            touches=touches,
            depends_on=depends_on,
```

4. In `to_text`, add to the `meta` dict — `parent` after `sprint`, `depends_on` after `touches`:
```python
            "sprint": self.sprint,
            "parent": self.parent,
```
and
```python
            "touches": self.touches or None,
            "depends_on": self.depends_on or None,
```

5. Add the two methods to `Card` (after `unblock`):
```python
    def park(self, now: str) -> None:
        self.status = "parked"
        self.updated = now

    def unpark(self, now: str) -> None:
        self.status = "in-flight" if self.stage else "planned"
        self.updated = now
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_models.py -q`
Expected: PASS (new classes + all existing model tests — the added fields default, so existing tests are unaffected).

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd plugins/overseer
../../.venv/bin/ruff check scripts/models.py tests/test_models.py
../../.venv/bin/mypy scripts
git add scripts/models.py tests/test_models.py
git commit -m "feat(overseer): card parent/depends_on fields + parked status"
```

---

## Task 2: `relations.py` — derived helpers

**Files:**
- Create: `plugins/overseer/scripts/relations.py`
- Test: `plugins/overseer/tests/test_relations.py`

**Interfaces:**
- Consumes: `Card` (Task 1's `parent`/`depends_on`/`status`).
- Produces: `children(cards, parent_id) -> list[Card]`, `is_epic(cards, card_id) -> bool`, `epic_rollup(cards, card_id) -> dict` (`{"done","total","estimate","actual"}`), `unmet_deps(card, cards) -> list[str]`, `is_ready(card, cards) -> bool`, `would_cycle_parent(cards, card_id, new_parent) -> bool`, `would_cycle_depends(cards, card_id, new_dep) -> bool`.

- [ ] **Step 1: Write the failing tests**

Create `plugins/overseer/tests/test_relations.py`:

```python
from scripts.models import Card
from scripts import relations as rel


def card(cid, **kw):
    base = dict(id=cid, title=f"T {cid}", status="planned")
    base.update(kw)
    return Card(**base)  # type: ignore[arg-type]


class TestHierarchy:
    def test_children_and_is_epic(self):
        cards = [card("WF-010"), card("WF-011", parent="WF-010"),
                 card("WF-012", parent="WF-010"), card("WF-020")]
        assert [c.id for c in rel.children(cards, "WF-010")] == ["WF-011", "WF-012"]
        assert rel.is_epic(cards, "WF-010") is True
        assert rel.is_epic(cards, "WF-020") is False

    def test_epic_rollup_counts_and_budgets(self):
        cards = [
            card("WF-010"),
            card("WF-011", parent="WF-010", status="done",
                 budget_estimate=100_000, budget_actual=90_000),
            card("WF-012", parent="WF-010", status="in-flight",
                 budget_estimate=300_000, budget_actual=120_000),
        ]
        r = rel.epic_rollup(cards, "WF-010")
        assert r == {"done": 1, "total": 2, "estimate": 400_000, "actual": 210_000}


class TestReadiness:
    def test_unmet_deps_flags_unfinished_and_unknown(self):
        cards = [card("WF-001", depends_on=["WF-002", "WF-999"]),
                 card("WF-002", status="in-flight")]
        assert rel.unmet_deps(cards[0], cards) == ["WF-002", "WF-999"]  # unknown counts as unmet

    def test_ready_when_all_deps_done(self):
        cards = [card("WF-001", depends_on=["WF-002"]),
                 card("WF-002", status="done")]
        assert rel.is_ready(cards[0], cards) is True

    def test_ready_when_no_deps(self):
        assert rel.is_ready(card("WF-001"), [card("WF-001")]) is True


class TestCycles:
    def test_parent_self_and_transitive(self):
        cards = [card("WF-010"), card("WF-011", parent="WF-010"),
                 card("WF-012", parent="WF-011")]
        assert rel.would_cycle_parent(cards, "WF-010", "WF-010") is True   # self
        assert rel.would_cycle_parent(cards, "WF-010", "WF-012") is True   # WF-012→WF-011→WF-010
        assert rel.would_cycle_parent(cards, "WF-020", "WF-010") is False  # new card, no cycle

    def test_depends_self_and_transitive(self):
        cards = [card("WF-001", depends_on=["WF-002"]),
                 card("WF-002", depends_on=["WF-003"]),
                 card("WF-003")]
        assert rel.would_cycle_depends(cards, "WF-001", "WF-001") is True   # self
        assert rel.would_cycle_depends(cards, "WF-003", "WF-001") is True   # WF-001→WF-002→WF-003
        assert rel.would_cycle_depends(cards, "WF-001", "WF-003") is False  # already reachable, but no back-edge
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_relations.py -q`
Expected: FAIL — `No module named 'scripts.relations'`.

- [ ] **Step 3: Create `relations.py`**

```python
"""Derived card relationships: epics (parent), dependencies, readiness, cycles.

Pure functions over a card list — no I/O, no mutation. Unknown/missing referenced
ids are surfaced (treated as unmet/absent), never raised.
"""
from __future__ import annotations

from scripts.models import Card


def _by_id(cards: list[Card]) -> dict[str, Card]:
    return {c.id: c for c in cards}


def children(cards: list[Card], parent_id: str) -> list[Card]:
    return [c for c in cards if c.parent == parent_id]


def is_epic(cards: list[Card], card_id: str) -> bool:
    return any(c.parent == card_id for c in cards)


def epic_rollup(cards: list[Card], card_id: str) -> dict:
    kids = children(cards, card_id)
    return {
        "done": sum(1 for c in kids if c.status == "done"),
        "total": len(kids),
        "estimate": sum(c.budget_estimate or 0 for c in kids),
        "actual": sum(c.budget_actual for c in kids),
    }


def unmet_deps(card: Card, cards: list[Card]) -> list[str]:
    index = _by_id(cards)
    unmet: list[str] = []
    for dep in card.depends_on:
        target = index.get(dep)
        if target is None or target.status != "done":
            unmet.append(dep)
    return unmet


def is_ready(card: Card, cards: list[Card]) -> bool:
    return not unmet_deps(card, cards)


def would_cycle_parent(cards: list[Card], card_id: str, new_parent: str) -> bool:
    """True if setting card_id.parent = new_parent would create a cycle."""
    if new_parent == card_id:
        return True
    index = _by_id(cards)
    cur = index.get(new_parent)
    seen: set[str] = set()
    while cur is not None and cur.id not in seen:
        if cur.id == card_id:
            return True
        seen.add(cur.id)
        cur = index.get(cur.parent) if cur.parent else None
    return False


def would_cycle_depends(cards: list[Card], card_id: str, new_dep: str) -> bool:
    """True if adding card_id -> depends_on new_dep would create a cycle."""
    if new_dep == card_id:
        return True
    index = _by_id(cards)
    stack = [new_dep]
    seen: set[str] = set()
    while stack:
        cur_id = stack.pop()
        if cur_id == card_id:
            return True
        if cur_id in seen:
            continue
        seen.add(cur_id)
        cur = index.get(cur_id)
        if cur is not None:
            stack.extend(cur.depends_on)
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_relations.py -q`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd plugins/overseer
../../.venv/bin/ruff check scripts/relations.py tests/test_relations.py
../../.venv/bin/mypy scripts
git add scripts/relations.py tests/test_relations.py
git commit -m "feat(overseer): relations helpers — epics, readiness, cycle checks"
```

---

## Task 3: CLI — `set-field --parent`, `depends`, `park`/`unpark`

**Files:**
- Modify: `plugins/overseer/scripts/cli.py`
- Test: `plugins/overseer/tests/test_cli.py`

**Interfaces:**
- Consumes: `Card.park`/`unpark` (Task 1); `would_cycle_parent`, `would_cycle_depends` (Task 2); existing `_load`, `_sync`, `_now`, `load_live_cards`, `state_root`.
- Produces CLI: `set-field --parent <id|"">`; `depends <card> [--on <id>] [--off <id>]`; `park <id>`; `unpark <id>`.

- [ ] **Step 1: Write the failing tests**

Add to `plugins/overseer/tests/test_cli.py` (the file already has a `repo` fixture and `run(repo, *argv)` helper; `make_card`/`git_init` come from `tests.factories`):

```python
class TestRelationsCommands:
    def _two_cards(self, repo):
        run(repo, "new-card", "--title", "Parent")   # WF-001
        run(repo, "new-card", "--title", "Child")     # WF-002

    def test_set_parent_and_clear(self, repo, capsys):
        self._two_cards(repo)
        assert run(repo, "set-field", "WF-002", "--parent", "WF-001") == 0
        from scripts.store import find_card_path, state_root
        from scripts.models import Card
        c = Card.from_text(find_card_path(state_root(repo), "WF-002").read_text())
        assert c.parent == "WF-001"
        assert run(repo, "set-field", "WF-002", "--parent", "") == 0
        c = Card.from_text(find_card_path(state_root(repo), "WF-002").read_text())
        assert c.parent is None

    def test_set_parent_unknown_rejected(self, repo, capsys):
        run(repo, "new-card", "--title", "Only")
        assert run(repo, "set-field", "WF-001", "--parent", "WF-999") == 1
        assert "WF-999" in capsys.readouterr().err

    def test_set_parent_cycle_rejected(self, repo, capsys):
        self._two_cards(repo)
        run(repo, "set-field", "WF-002", "--parent", "WF-001")
        capsys.readouterr()
        assert run(repo, "set-field", "WF-001", "--parent", "WF-002") == 1
        assert "cycle" in capsys.readouterr().err

    def test_depends_on_and_off(self, repo, capsys):
        self._two_cards(repo)
        assert run(repo, "depends", "WF-002", "--on", "WF-001") == 0
        from scripts.store import find_card_path, state_root
        from scripts.models import Card
        c = Card.from_text(find_card_path(state_root(repo), "WF-002").read_text())
        assert c.depends_on == ["WF-001"]
        assert run(repo, "depends", "WF-002", "--off", "WF-001") == 0
        c = Card.from_text(find_card_path(state_root(repo), "WF-002").read_text())
        assert c.depends_on == []

    def test_depends_self_and_cycle_rejected(self, repo, capsys):
        self._two_cards(repo)
        assert run(repo, "depends", "WF-001", "--on", "WF-001") == 1
        capsys.readouterr()
        run(repo, "depends", "WF-002", "--on", "WF-001")
        capsys.readouterr()
        assert run(repo, "depends", "WF-001", "--on", "WF-002") == 1
        assert "cycle" in capsys.readouterr().err

    def test_park_unpark(self, repo, capsys):
        run(repo, "new-card", "--title", "Shelve me")
        assert run(repo, "park", "WF-001") == 0
        from scripts.store import find_card_path, state_root
        from scripts.models import Card
        c = Card.from_text(find_card_path(state_root(repo), "WF-001").read_text())
        assert c.status == "parked"
        assert run(repo, "unpark", "WF-001") == 0
        c = Card.from_text(find_card_path(state_root(repo), "WF-001").read_text())
        assert c.status == "planned"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_cli.py::TestRelationsCommands -q`
Expected: FAIL — `set-field` has no `--parent`; `depends`/`park`/`unpark` are invalid choices.

- [ ] **Step 3: Implement the CLI changes**

In `plugins/overseer/scripts/cli.py`:

1. Add the relations import near the other `scripts.*` imports:
```python
from scripts.relations import would_cycle_depends, would_cycle_parent  # noqa: E402
```

2. In `cmd_set_field`, add parent handling. Insert before the `card.updated = _now()` line:
```python
    if args.parent is not None:
        if args.parent == "":
            card.parent = None
        else:
            cards, _ = load_live_cards(state_root(args.root))
            if args.parent not in {c.id for c in cards}:
                print(f"error: no live card {args.parent}", file=sys.stderr)
                return 1
            if would_cycle_parent(cards, args.card_id, args.parent):
                print(f"error: parent {args.parent} would create a cycle",
                      file=sys.stderr)
                return 1
            card.parent = args.parent
```

3. Add three command functions (place after `cmd_set_field`):
```python
def cmd_depends(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    cards, _ = load_live_cards(state_root(args.root))
    ids = {c.id for c in cards}
    if args.on:
        if args.on == args.card_id:
            print("error: a card cannot depend on itself", file=sys.stderr)
            return 1
        if args.on not in ids:
            print(f"error: no live card {args.on}", file=sys.stderr)
            return 1
        if would_cycle_depends(cards, args.card_id, args.on):
            print(f"error: depending on {args.on} would create a cycle",
                  file=sys.stderr)
            return 1
        if args.on not in card.depends_on:
            card.depends_on.append(args.on)
    if args.off and args.off in card.depends_on:
        card.depends_on.remove(args.off)
    card.updated = _now()
    _sync(args.root, card)
    print(f"{card.id} depends_on: {', '.join(card.depends_on) or '(none)'}")
    return 0


def cmd_park(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    card.park(_now())
    _sync(args.root, card)
    print(f"{card.id} parked")
    return 0


def cmd_unpark(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    card.unpark(_now())
    _sync(args.root, card)
    print(f"{card.id} → {card.status}")
    return 0
```

4. Register the parser entries. Add `--parent` to the existing `set-field` parser (find the `p = sub.add_parser("set-field")` block and add):
```python
    p.add_argument("--parent")
```
Then add the new commands (near the other `sub.add_parser` calls):
```python
    p = sub.add_parser("depends")
    p.add_argument("card_id")
    p.add_argument("--on")
    p.add_argument("--off")
    p.set_defaults(func=cmd_depends)

    p = sub.add_parser("park")
    p.add_argument("card_id")
    p.set_defaults(func=cmd_park)

    p = sub.add_parser("unpark")
    p.add_argument("card_id")
    p.set_defaults(func=cmd_unpark)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_cli.py -q`
Expected: PASS (new class + existing CLI tests).

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd plugins/overseer
../../.venv/bin/ruff check scripts/cli.py tests/test_cli.py
../../.venv/bin/mypy scripts
git add scripts/cli.py tests/test_cli.py
git commit -m "feat(overseer): set-field --parent, depends, park/unpark CLI"
```

---

## Task 4: Index rendering — Epics + Parked + readiness

**Files:**
- Modify: `plugins/overseer/scripts/index.py`
- Test: `plugins/overseer/tests/test_index.py`

**Interfaces:**
- Consumes: `children`, `is_epic`, `epic_rollup`, `unmet_deps` (Task 2); existing `format_tokens`, `_budget_cell`.
- Produces: a `generate_index` that renders `## Epics` (rollup + nested children + readiness), filters `## In flight`/`## Planned` to standalone cards (no parent, no children), and adds `## Parked`.

- [ ] **Step 1: Write the failing tests**

Add to `plugins/overseer/tests/test_index.py` (uses `make_card`/`git_init` from `tests.factories` and the existing patterns):

```python
class TestEpicsAndParked:
    def _gen(self, cards):
        from scripts.index import generate_index
        return generate_index("proj", cards, [], "2026-07-11T10:00")

    def test_epic_section_with_rollup_and_children(self):
        from tests.factories import make_card
        cards = [
            make_card("WF-010", status="in-flight", title="Auth"),
            make_card("WF-011", parent="WF-010", status="done",
                      budget_estimate=100_000, budget_actual=90_000),
            make_card("WF-012", parent="WF-010", status="in-flight", stage="implementation",
                      budget_estimate=300_000, budget_actual=120_000),
        ]
        out = self._gen(cards)
        assert "## Epics" in out
        assert "WF-010" in out and "1/2 done" in out          # rollup
        assert "WF-011" in out and "WF-012" in out            # nested children

    def test_children_not_in_status_sections(self):
        from tests.factories import make_card
        cards = [make_card("WF-010"), make_card("WF-011", parent="WF-010", status="in-flight")]
        out = self._gen(cards)
        # WF-011 appears under the epic, not as a standalone In-flight row
        infl = out.split("## In flight")[1].split("##")[0]
        assert "WF-011" not in infl

    def test_readiness_shown(self):
        from tests.factories import make_card
        cards = [
            make_card("WF-001", status="planned", depends_on=["WF-002"]),
            make_card("WF-002", status="in-flight"),
        ]
        out = self._gen(cards)
        assert "waiting on WF-002" in out

    def test_parked_section(self):
        from tests.factories import make_card
        cards = [make_card("WF-005", status="parked", title="Legacy", updated="2026-07-09T10:00")]
        out = self._gen(cards)
        assert "## Parked" in out and "WF-005" in out and "shelved" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_index.py::TestEpicsAndParked -q`
Expected: FAIL — no Epics/Parked sections; children currently appear in In flight.

- [ ] **Step 3: Implement the rendering**

In `plugins/overseer/scripts/index.py`, add the import and rewrite `_in_flight_row` + `generate_index`:

```python
from scripts.relations import children, epic_rollup, is_epic, unmet_deps
```

Add a readiness helper and a child-line helper near the top (after `_budget_cell`):
```python
def _readiness(card: Card, cards: list[Card]) -> str:
    if not card.depends_on:
        return ""
    unmet = unmet_deps(card, cards)
    return "ready" if not unmet else f"waiting on {', '.join(unmet)}"


def _epic_child_line(card: Card, cards: list[Card]) -> str:
    if card.status in ("done", "parked", "blocked"):
        state = card.status
    else:
        state = card.stage or "planned"
    parts = [state, _budget_cell(card)]
    ready = _readiness(card, cards)
    if ready:
        parts.append(ready)
    return f"    - {card.id}  {card.title}  " + " · ".join(parts)
```

Change `_in_flight_row` to take `cards` and surface readiness in the note:
```python
def _in_flight_row(card: Card, cards: list[Card]) -> str:
    if card.status == "blocked":
        stage = "BLOCKED"
        note = card.blocked_on or "blocked"
    else:
        stage = card.stage or "—"
        if card.stage and card.stage.endswith("review"):
            rounds = card.review_rounds(card.stage)
            if rounds:
                stage = f"{stage} (r{rounds})"
        ready = _readiness(card, cards)
        note = ready if ready else ("2× BUDGET" if card.tripwire_breached else "—")
    return (
        f"| {card.id} | {card.title} | {stage} | {card.complexity or '?'} "
        f"| {_budget_cell(card)} | {note} |"
    )
```

Replace `generate_index` with:
```python
def generate_index(
    project: str, cards: list[Card], recently_done: list[Card], now: str
) -> str:
    epics = sorted((c for c in cards if is_epic(cards, c.id)), key=lambda c: c.id)
    standalone = [c for c in cards if c.parent is None and not is_epic(cards, c.id)]
    in_flight = [c for c in standalone if c.status in ("in-flight", "blocked")]
    planned = [c for c in standalone if c.status == "planned"]
    parked = [c for c in standalone if c.status == "parked"]

    lines = [f"# Ledger — {project}", f"Updated: {now}", ""]

    if epics:
        lines.append("## Epics")
        for e in epics:
            r = epic_rollup(cards, e.id)
            est = format_tokens(r["estimate"]) or "0"
            act = format_tokens(r["actual"]) or "0"
            lines.append(
                f"- {e.id} — {e.title}  ({r['done']}/{r['total']} done · {act}/{est})"
            )
            for kid in sorted(children(cards, e.id), key=lambda c: c.id):
                lines.append(_epic_child_line(kid, cards))
        lines.append("")

    lines.append("## In flight")
    if in_flight:
        lines += [
            "| Card | Title | Stage | Complexity | Budget (act/est) | Note |",
            "|---|---|---|---|---|---|",
        ]
        lines += [_in_flight_row(c, cards) for c in in_flight]
    else:
        lines.append("_Nothing in flight._")

    lines += ["", "## Planned"]
    if planned:
        for c in planned:
            estimate = format_tokens(c.budget_estimate) or "?"
            sprint = f", sprint {c.sprint}" if c.sprint else ""
            ready = _readiness(c, cards)
            suffix = f" · {ready}" if ready else ""
            lines.append(
                f"- {c.id} — {c.title} ({c.complexity or '?'}, ~{estimate}{sprint}){suffix}"
            )
    else:
        lines.append("_Backlog empty._")

    if parked:
        lines += ["", "## Parked"]
        for c in parked:
            day = c.updated[:10] if c.updated else "?"
            lines.append(f"- {c.id} — {c.title} (shelved {day})")

    lines += ["", "## Recently done"]
    if recently_done:
        for c in recently_done:
            day = c.updated[:10] if c.updated else "?"
            lines.append(f"- {c.id} — {c.status} {day}, {_budget_cell(c)}")
    else:
        lines.append("_Nothing yet._")

    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_index.py -q`
Expected: PASS. If a pre-existing index test asserted a child card appears in In-flight or asserted the exact section order, update it to the new standalone-filtered layout (the index is a regenerated view; adjust the assertion, don't weaken it).

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd plugins/overseer
../../.venv/bin/ruff check scripts/index.py tests/test_index.py
../../.venv/bin/mypy scripts
git add scripts/index.py tests/test_index.py
git commit -m "feat(overseer): index renders epics, parked, and readiness"
```

---

## Task 5: Resume/handoff rendering — readiness, epics, parked

**Files:**
- Modify: `plugins/overseer/scripts/resume.py`
- Test: `plugins/overseer/tests/test_resume.py`

**Interfaces:**
- Consumes: `is_ready`, `unmet_deps`, `is_epic`, `children`, `epic_rollup` (Task 2).
- Produces: `_entry` dicts gain `"parent"`, `"depends_on"`, `"ready"`; `format_report` appends readiness; `handoff_data` gains `"parked"` and `"epics"`; `handoff_report` renders `## Parked` and epic readiness.

- [ ] **Step 1: Write the failing tests**

Add to `plugins/overseer/tests/test_resume.py` (uses `make_card`/`git_init` from `tests.factories`):

```python
class TestResumeRelations:
    def test_entry_carries_relations_and_readiness(self, tmp_path):
        from scripts.store import init_workflow, save_card
        from scripts.resume import resume_entries
        from tests.factories import make_card
        root = init_workflow(tmp_path)
        save_card(root, make_card("WF-002", status="in-flight"))
        save_card(root, make_card("WF-001", status="in-flight",
                                  parent="WF-000", depends_on=["WF-002"]))
        entry = next(e for e in resume_entries(tmp_path) if e["id"] == "WF-001")
        assert entry["parent"] == "WF-000"
        assert entry["depends_on"] == ["WF-002"]
        assert entry["ready"] is False  # WF-002 not done

    def test_report_shows_waiting(self, tmp_path):
        from scripts.store import init_workflow, save_card
        from scripts.resume import resume_entries, format_report
        from tests.factories import make_card
        root = init_workflow(tmp_path)
        save_card(root, make_card("WF-002", status="in-flight"))
        save_card(root, make_card("WF-001", status="in-flight", depends_on=["WF-002"]))
        assert "waiting on WF-002" in format_report(resume_entries(tmp_path))

    def test_handoff_has_parked_section(self, tmp_path):
        from scripts.store import init_workflow, save_card
        from scripts.resume import handoff_report
        from tests.factories import make_card
        root = init_workflow(tmp_path)
        save_card(root, make_card("WF-005", status="parked", title="Legacy"))
        assert "## Parked" in handoff_report(tmp_path) and "WF-005" in handoff_report(tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_resume.py::TestResumeRelations -q`
Expected: FAIL — entries lack `parent`/`depends_on`/`ready`; no Parked section.

- [ ] **Step 3: Implement the resume changes**

In `plugins/overseer/scripts/resume.py`:

1. Add the import:
```python
from scripts.relations import is_ready
```

2. `_entry` currently takes `(repo_root, card)`. Change it to also take the full card list for readiness, and add the three fields. Update its signature and the two call sites (in `resume_entries` and `handoff_data`) to pass the loaded `cards`:
```python
def _entry(repo_root: Path, card: Card, cards: list[Card]) -> dict:
    ...  # existing body unchanged, then add to the returned dict:
        "parent": card.parent,
        "depends_on": card.depends_on,
        "ready": is_ready(card, cards),
```
In `resume_entries`: it already does `cards, _ = load_live_cards(...)`; pass `cards` into `_entry(repo_root, c, cards)`.
In `handoff_data`: it already loads `cards`; pass `cards` into each `_entry(repo_root, c, cards)`.

3. In `format_report`, append readiness to each line. After the existing line-building (before `lines.append(line)`), add:
```python
        if e.get("depends_on"):
            line += " | ready" if e.get("ready") else " | waiting on " + ", ".join(
                d for d in e["depends_on"]
            )
```
(Keep it simple: show `ready`/`waiting on …` when the entry has deps. Unmet-specific filtering isn't needed here — `resume`'s job is to flag not-ready; the precise unmet list is in the index.)

4. In `handoff_data`, add a `parked` list alongside the existing keys:
```python
        "parked": [{"id": c.id, "title": c.title} for c in cards if c.status == "parked"],
```

5. In `handoff_report`, render a `## Parked` section after `## Planned`:
```python
    if data.get("parked"):
        lines += ["", "## Parked"]
        lines += [f"- {p['id']} — {p['title']} (shelved)" for p in data["parked"]]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_resume.py -q`
Expected: PASS (new class + existing resume/handoff tests — the added dict keys are additive).

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd plugins/overseer
../../.venv/bin/ruff check scripts/resume.py tests/test_resume.py
../../.venv/bin/mypy scripts
git add scripts/resume.py tests/test_resume.py
git commit -m "feat(overseer): resume/handoff carry relations, readiness, parked"
```

---

## Task 6: Doctrine — ledger + orchestrate

**Files:**
- Modify: `plugins/overseer/skills/ledger/SKILL.md`
- Modify: `plugins/overseer/skills/orchestrate/SKILL.md` (stage playbook) and `skills/orchestrate/references/` if a sub-playbook fits

**Interfaces:**
- Consumes: every command from Tasks 3 (`set-field --parent`, `depends`, `park`/`unpark`) and the readiness/epics behaviour from Tasks 4–5. Doctrine only — no code, no tests.

- [ ] **Step 1: Add relationship doctrine to the ledger skill**

In `plugins/overseer/skills/ledger/SKILL.md`, add a `## Relationships` section after the `## During work` section:

```markdown
## Relationships (epics, dependencies, parking)
- **Epics are emergent.** Set a card's `parent` with `set-field <id> --parent
  <epic-id>` (`--parent ""` clears). A card with children *is* an epic — the
  index shows it with a rollup (`2/4 done · 260k/900k`) and its children nested.
  Keep trees shallow; deep nesting is discouraged.
- **Dependencies gate readiness.** Record card→card ordering with
  `depends <id> --on <dep>` (`--off` to remove). A card is **ready** only when
  every `depends_on` card is `done`; the index/resume show `ready` or
  `waiting on <id>`. Use `depends`, not `blocked_on`, for card ordering —
  `blocked_on` is for human/agent blocks only (`user:`/`agent:`). Cycles are
  refused.
- **Park to shelve.** `park <id>` sets a card aside without a blocker (distinct
  from `block`, which needs a reason, and `abandon`, which is terminal). It
  preserves stage/branch/worktree; `unpark <id>` resumes it (→ in-flight if it
  had a stage, else planned).
```

- [ ] **Step 2: Add the readiness gate + park semantics to orchestrate**

In `plugins/overseer/skills/orchestrate/SKILL.md`:

1. In the `## Stage playbook` **planning** bullet, change the L-split sentence from creating children and abandoning the parent to keeping the parent as an epic. Replace the existing L-card sentence with:
```markdown
  L cards: attempt split first; if split, create the child cards **with
  `set-field <child> --parent <this-card>`** and keep this card as the epic
  (do not abandon it) — its rollup tracks the children. L keeps a second
  planning pass.
```

2. Add a readiness rule to the `## Watchdogs` section (or as a new short bullet in the stage playbook's bootstrap entry):
```markdown
- **Readiness:** never bootstrap or plan a card that is not `ready` — if the
  ledger shows `waiting on <id>`, work the dependency first or pick a ready card.
  Record ordering with `depends`, not a `block` reason.
```

3. Add a one-line note where blocking/parking is relevant (e.g. near the watchdogs or the on-invocation park handling): 
```markdown
- **Park vs block vs abandon:** `park` to shelve without a blocker (resumable),
  `block` for a real blocker with a reason, `abandon` for terminal.
```

- [ ] **Step 3: Verify doctrine references only real commands + suite green**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest -q`
Expected: PASS (docs-only change; full suite unchanged in count from Task 5).
Manually confirm every command named in the new doctrine exists in `build_parser`: `set-field --parent`, `depends`, `park`, `unpark`.

- [ ] **Step 4: Commit**

```bash
cd plugins/overseer
git add skills/ledger/SKILL.md skills/orchestrate/SKILL.md
git commit -m "docs(overseer): relationships doctrine — epics, readiness gate, park"
```

---

## Final verification

From `plugins/overseer/`:
```bash
../../.venv/bin/python -m pytest -q
../../.venv/bin/ruff check scripts tests
../../.venv/bin/mypy scripts
```
Expected: all green; ruff + mypy clean. Then eyeball a real `ledger.md`: create an epic + children + a dependency + a parked card via the CLI and confirm the rendered sections match the spec's §4 shape.

## Spec coverage map

| Spec section | Task(s) |
|---|---|
| §1 model (`parent`, `depends_on`, `parked` + park/unpark) | 1 |
| §2 derived (`relations.py`) | 2 |
| §3 CLI (`set-field --parent`, `depends`, `park`/`unpark`) | 3 |
| §4 rendering (Epics/Parked/readiness, standalone filtering) | 4 (index), 5 (resume/handoff) |
| §5 doctrine (ledger + orchestrate, L-split-sets-parent, readiness gate) | 6 |
| §6 testing | every task's tests |
| §7 migration/non-goals | respected — additive fields, display-only rollup, no auto-migration |
| §8 verify-at-impl (status vocabulary, resume JSON consumers, base branch) | 1 (STATUSES), 5 (resume JSON), branch chosen at execution |
