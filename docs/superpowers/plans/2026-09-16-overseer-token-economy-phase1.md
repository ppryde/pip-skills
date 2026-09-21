# Overseer Token Economy — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut overseer orchestrator turns per dispatch from ~19.5 to ≤6 by making agents self-reporting (one-line replies parsed by a `SubagentStop` hook into the ledger), mechanically forbidding the orchestrator from doing work or forking (a `PreToolUse` guard), and collapsing dispatch setup into single CLI verbs.

**Architecture:** Four new focused modules under `plugins/overseer/scripts/` — `dispatch.py` (paths + reply grammar), `transcript_usage.py` (real usage from a transcript), `report_hook.py` (reply → ledger), `guard.py` (orchestrator guard + Read limit) — plus `pending.py` (Learned-fact queue), `bundle.py` (dispatch-prep) and `gitops.py` (base branch + worktree). `cli.py` gets thin `cmd_*` wrappers only. Two shell hooks register in `hooks/hooks.json`. Five plugin agent definitions in `agents/`. Skill prose is rewritten last, once the mechanisms exist.

**Tech Stack:** Python 3.11+ (stdlib only: `sqlite3`, `shlex`, `re`, `json`, `subprocess`), pytest, ruff, mypy; bash hook wrappers; Claude Code 2.1.273 hook payloads.

**Spec:** `docs/superpowers/specs/2026-09-16-overseer-token-economy-design.md` (Phase 1 = §4, §5, §7, §8). Evidence: `docs/superpowers/research/2026-09-16-overseer-token-audit.md`.

## Global Constraints

- Worktree: `/Users/philip.pryde/repos/pip-skills-token-economy`, branch `feat/WF-113-overseer-token-economy`. Never commit to `main`.
- Interpreter: `PY=/Users/philip.pryde/repos/pip-skills/.venv/bin/python` (the worktree has no `.venv`; poetry is not used for this plugin).
- Run tests **from `plugins/overseer`**: `cd /Users/philip.pryde/repos/pip-skills-token-economy/plugins/overseer && $PY -m pytest ../../tests/overseer/<file> -q -p no:cacheprovider`.
- Gates before every commit: `$PY -m ruff check scripts ../../tests/overseer` and `$PY -m mypy scripts` (both from `plugins/overseer`). Baseline suite: 619 passed.
- Test isolation (repo CLAUDE.md): never touch real `~/.claude*`. `tests/overseer/conftest.py` pins `CLAUDE_CONFIG_DIR`, `OVERSEER_DB`, `OVERSEER_CENTRAL` to `tmp_path`; create nothing outside `tmp_path`.
- Hooks are record-only: shell wrappers use `trap 'exit 0' EXIT`; Python backends catch `Exception` and return 0. A `SubagentStop` hook never emits `decision: block`.
- Reply cap: one line, `REPLY_WORD_CAP = 25` words. `--var` values cap: `VAR_CAP = 300` characters.
- Plugin agents are addressed as `overseer:overseer-<role>`; payload `agent_type` carries that prefix.
- Budget: only implementer and fixer spend feeds `budget_actual`, amount `input + cache_creation + output`. Everything goes to `usage.jsonl` with the raw breakdown.
- Commit messages end with: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- Match surrounding style: docstrings explain *why*, `from __future__ import annotations`, type hints on every def (mypy `disallow_untyped_defs`).

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `plugins/overseer/scripts/dispatch.py` (new) | dispatch dir layout, role names, reply grammar parser | 1 |
| `plugins/overseer/scripts/transcript_usage.py` (new) | total usage from an agent transcript | 2 |
| `plugins/overseer/scripts/models.py` (modify) | `Card.record_review`, `Card.set_section` | 3 |
| `plugins/overseer/scripts/db.py` (modify) | `orchestrators` table, `mutate_card` transaction | 3 |
| `plugins/overseer/scripts/pending.py` (new) | pending Learned-fact queue | 4 |
| `plugins/overseer/scripts/report_hook.py` (new) | `SubagentStop` reply → ledger | 5 |
| `plugins/overseer/hooks/report.sh` (new) | shell wrapper | 5 |
| `plugins/overseer/scripts/guard.py` (new) | orchestrator guard, Bash allowlist, Read limit | 7 |
| `plugins/overseer/hooks/pretool.sh` (new) | shell wrapper | 7 |
| `plugins/overseer/scripts/gitops.py` (new) | base-branch detection, diff, worktree add | 8, 9 |
| `plugins/overseer/scripts/bundle.py` (new) | `dispatch-prep` composition | 8 |
| `plugins/overseer/templates/{planner,implementer,reviewer,fixer,verifier}.md` | bundle input sheets | 8 |
| `plugins/overseer/agents/overseer-*.md` (new ×5) | agent definitions: tools, charter, reply line | 10 |
| `plugins/overseer/scripts/cli.py` (modify) | thin verbs: `set-section`, `facts --pending`, `accept-fact`, `reject-fact`, `report-hook`, `release`, `pretool-hook`, `dispatch-prep`, `bootstrap` | 4–9 |
| `plugins/overseer/hooks/hooks.json` (modify) | register `SubagentStop` + `PreToolUse` | 5, 7 |
| `plugins/overseer/skills/**`, `policy.md`, `plugin.json` | prose + version | 11 |
| `tests/overseer/test_*.py` (new) | one test file per new module | 1–10 |

---

### Task 1: Dispatch paths and reply grammar

**Files:**
- Create: `plugins/overseer/scripts/dispatch.py`
- Test: `tests/overseer/test_dispatch.py`

**Interfaces:**
- Consumes: `scripts.store.state_root(repo_root: Path) -> Path`
- Produces:
  - `REPLY_WORD_CAP: int = 25`, `ROLES: tuple[str, ...]`
  - `class ReplyError(ValueError)`
  - `@dataclass(frozen=True) class Reply(role: str, status: str, line: str, path: Path, card: str, stage: str, name: str, round: int | None, slot: str | None, chunk: int | None, counts: dict[str, int], sha: str | None)`
  - `agent_name(agent_type: object) -> str | None`
  - `role_of(agent_type: object) -> str | None` — one of `ROLES` or None
  - `is_hub_agent(agent_type: object) -> bool` — True only for `overseer-foreman`
  - `dispatch_dir(repo_root: Path, card_id: str, stage: str) -> Path`
  - `reply_words(text: str) -> int`
  - `parse_reply(role: str, text: str) -> Reply` — raises `ReplyError`

- [ ] **Step 1: Write the failing tests**

```python
# tests/overseer/test_dispatch.py
from pathlib import Path

import pytest

from scripts.dispatch import (
    REPLY_WORD_CAP,
    ReplyError,
    agent_name,
    dispatch_dir,
    is_hub_agent,
    parse_reply,
    reply_words,
    role_of,
)

D = "/x/state/dispatch/WF-12/impl-review"


class TestRoleOf:
    @pytest.mark.parametrize("agent_type, expected", [
        ("overseer:overseer-reviewer", "reviewer"),
        ("overseer-fixer", "fixer"),
        ("overseer:overseer-implementer", "implementer"),
        ("overseer:overseer-foreman", None),
        ("general-purpose", None),
        ("", None),
        (None, None),
        (42, None),
    ])
    def test_role_of(self, agent_type, expected):
        assert role_of(agent_type) == expected

    def test_agent_name_strips_plugin_prefix(self):
        assert agent_name("overseer:overseer-reviewer") == "overseer-reviewer"

    def test_hub_agent_is_foreman_only(self):
        assert is_hub_agent("overseer:overseer-foreman")
        assert not is_hub_agent("overseer:overseer-reviewer")
        assert not is_hub_agent(None)


class TestParseReply:
    def test_reviewer(self):
        r = parse_reply("reviewer", f"found wanting 2C 1I 0M → {D}/r1-A.md")
        assert (r.status, r.card, r.stage, r.round, r.slot) == (
            "found wanting", "WF-12", "impl-review", 1, "A")
        assert r.counts == {"C": 2, "I": 1, "M": 0}
        assert r.path == Path(f"{D}/r1-A.md")

    def test_ascii_arrow_and_surrounding_whitespace(self):
        r = parse_reply("reviewer", f"  approved 0C 0I 3M -> {D}/r2-B.md\n")
        assert (r.status, r.round, r.slot) == ("approved", 2, "B")

    def test_fixer_with_sha(self):
        r = parse_reply("fixer", f"DISPUTED fixed 2 disputed 1 abc1234 → {D}/r1-fix.md")
        assert r.counts == {"fixed": 2, "disputed": 1}
        assert (r.sha, r.slot, r.round) == ("abc1234", "fix", 1)

    def test_implementer_without_sha(self):
        r = parse_reply("implementer",
                        "BLOCKED tests 3/5 - → /x/state/dispatch/WF-12/implementation/c2.md")
        assert (r.status, r.chunk, r.sha) == ("BLOCKED", 2, None)
        assert r.counts == {"passed": 3, "total": 5}

    def test_planner_and_verifier(self):
        assert parse_reply("planner", "DONE → /s/dispatch/WF-1/planning/plan.md").name == "plan"
        v = parse_reply("verifier", "FAIL → /s/dispatch/WF-1/verification/verification.md")
        assert v.status == "FAIL"

    @pytest.mark.parametrize("role, text, message", [
        ("reviewer", f"approved 0C 0I 0M → {D}/r1-A.md\nextra", "more than one line"),
        ("reviewer", "Looks good to me!", "does not match"),
        ("reviewer", "approved 0C 0I 0M → /tmp/elsewhere/r1-A.md", "not a dispatch file"),
        ("reviewer", f"approved 0C 0I 0M → {D}/c1.md", "does not fit"),
        ("reviewer", f"approved 0C 0I 0M → {D}/r1-fix.md", "does not fit"),
        ("fixer", f"DONE fixed 1 disputed 0 - → {D}/r1-A.md", "does not fit"),
        ("planner", f"DONE → {D}/verification.md", "does not fit"),
        ("foreman", "anything", "no reply grammar"),
    ])
    def test_rejections(self, role, text, message):
        with pytest.raises(ReplyError, match=message):
            parse_reply(role, text)


def test_reply_words_and_cap():
    assert reply_words("approved 0C 0I 0M → /a/b.md") == 6
    assert REPLY_WORD_CAP == 25


def test_dispatch_dir_under_state_root(tmp_path):
    # conftest pins OVERSEER_CENTRAL to tmp_path / "state"
    assert dispatch_dir(tmp_path, "WF-1", "impl-review") == (
        tmp_path / "state" / "dispatch" / "WF-1" / "impl-review")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd plugins/overseer && $PY -m pytest ../../tests/overseer/test_dispatch.py -q -p no:cacheprovider`
Expected: collection error `ModuleNotFoundError: No module named 'scripts.dispatch'`

- [ ] **Step 3: Implement**

```python
# plugins/overseer/scripts/dispatch.py
"""Dispatch directory layout and the one-line agent reply grammar (WF-113 §4).

Every overseer agent writes its detail to a file under
``<state_root>/dispatch/<card>/<stage>/`` and ends with ONE line in a fixed
grammar. The parent reads that line to decide what happens next; the
SubagentStop report hook parses the same line into the ledger. Replies carry a
path, never content — that is what keeps the orchestrator's context small.

The file name encodes round/slot/chunk, so the hook needs nothing but the line.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from scripts.store import state_root

REPLY_WORD_CAP = 25
ROLES = ("planner", "implementer", "reviewer", "fixer", "verifier")

_TO = r"\s*(?:→|->)\s*"
_SHA = r"([0-9a-f]{7,40}|-)"
_GRAMMAR: dict[str, re.Pattern[str]] = {
    "reviewer": re.compile(rf"\A(approved|found wanting) (\d+)C (\d+)I (\d+)M{_TO}(\S+)\Z"),
    "fixer": re.compile(
        rf"\A(DONE|DISPUTED|BLOCKED) fixed (\d+) disputed (\d+) {_SHA}{_TO}(\S+)\Z"
    ),
    "implementer": re.compile(
        rf"\A(DONE|DONE_WITH_CONCERNS|BLOCKED|NEEDS_CONTEXT) tests (\d+)/(\d+) {_SHA}{_TO}(\S+)\Z"
    ),
    "planner": re.compile(rf"\A(DONE|NEEDS_CONTEXT){_TO}(\S+)\Z"),
    "verifier": re.compile(rf"\A(PASS|FAIL){_TO}(\S+)\Z"),
}
_PATH_RE = re.compile(r"/dispatch/(?P<card>[^/]+)/(?P<stage>[^/]+)/(?P<name>[^/]+)\.md\Z")
_NAME_RE = re.compile(
    r"\A(?:r(?P<round>\d+)-(?P<slot>[A-Za-z0-9]+)|c(?P<chunk>\d+)|plan|verification|summary)\Z"
)


class ReplyError(ValueError):
    """An agent's final message that does not follow its role's reply grammar."""


@dataclass(frozen=True)
class Reply:
    role: str
    status: str
    line: str
    path: Path
    card: str
    stage: str
    name: str
    round: int | None = None
    slot: str | None = None
    chunk: int | None = None
    counts: dict[str, int] = field(default_factory=dict)
    sha: str | None = None


def agent_name(agent_type: object) -> str | None:
    """``overseer:overseer-reviewer`` (plugin agents carry the plugin prefix
    in hook payloads) or ``overseer-reviewer`` → ``overseer-reviewer``."""
    if not isinstance(agent_type, str) or not agent_type:
        return None
    return agent_type.split(":")[-1]


def role_of(agent_type: object) -> str | None:
    name = agent_name(agent_type)
    if not name or not name.startswith("overseer-"):
        return None
    role = name[len("overseer-"):]
    return role if role in ROLES else None


def is_hub_agent(agent_type: object) -> bool:
    """A hub dispatches rather than works (Phase 2's foreman); the guard
    holds it to the orchestrator's no-work rule."""
    return agent_name(agent_type) == "overseer-foreman"


def dispatch_dir(repo_root: Path, card_id: str, stage: str) -> Path:
    return state_root(repo_root) / "dispatch" / card_id / stage


def reply_words(text: str) -> int:
    return len(text.split())


def _name_fits(role: str, name: str, parts: re.Match[str]) -> bool:
    if role == "reviewer":
        return parts["round"] is not None and parts["slot"] != "fix"
    if role == "fixer":
        return parts["slot"] == "fix"
    if role == "implementer":
        return parts["chunk"] is not None
    return name == {"planner": "plan", "verifier": "verification"}[role]


def parse_reply(role: str, text: str) -> Reply:
    if role not in _GRAMMAR:
        raise ReplyError(f"no reply grammar for role {role!r}")
    line = text.strip()
    if "\n" in line:
        raise ReplyError("reply is more than one line")
    match = _GRAMMAR[role].match(line)
    if match is None:
        raise ReplyError(f"reply does not match the {role} grammar")
    groups = match.groups()
    where = _PATH_RE.search(groups[-1])
    if where is None:
        raise ReplyError("reply path is not a dispatch file")
    parts = _NAME_RE.match(where["name"])
    if parts is None or not _name_fits(role, where["name"], parts):
        raise ReplyError(f"file name {where['name']!r} does not fit a {role} reply")
    counts: dict[str, int] = {}
    sha: str | None = None
    if role == "reviewer":
        counts = {"C": int(groups[1]), "I": int(groups[2]), "M": int(groups[3])}
    elif role in ("fixer", "implementer"):
        keys = ("fixed", "disputed") if role == "fixer" else ("passed", "total")
        counts = {keys[0]: int(groups[1]), keys[1]: int(groups[2])}
        sha = None if groups[3] == "-" else groups[3]
    return Reply(
        role=role,
        status=groups[0],
        line=line,
        path=Path(groups[-1]),
        card=where["card"],
        stage=where["stage"],
        name=where["name"],
        round=int(parts["round"]) if parts["round"] else None,
        slot=parts["slot"],
        chunk=int(parts["chunk"]) if parts["chunk"] else None,
        counts=counts,
        sha=sha,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PY -m pytest ../../tests/overseer/test_dispatch.py -q -p no:cacheprovider`
Expected: all PASS. Then `$PY -m ruff check scripts ../../tests/overseer && $PY -m mypy scripts` → clean.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/scripts/dispatch.py tests/overseer/test_dispatch.py
git commit -m "feat(overseer): dispatch paths and the one-line agent reply grammar (WF-113)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Real usage from an agent transcript

**Files:**
- Create: `plugins/overseer/scripts/transcript_usage.py`
- Test: `tests/overseer/test_transcript_usage.py`

**Interfaces:**
- Produces:
  - `FIELDS = ("input", "cache_read", "cache_creation", "output")`
  - `sum_usage(path: Path) -> dict[str, int]` — keys exactly `FIELDS`; never raises
  - `zero_usage() -> dict[str, int]`
  - `raw_total(totals: dict[str, int]) -> int`
  - `budget_tokens(totals: dict[str, int]) -> int` — `input + cache_creation + output`

- [ ] **Step 1: Write the failing tests**

```python
# tests/overseer/test_transcript_usage.py
import json

from scripts.transcript_usage import budget_tokens, raw_total, sum_usage, zero_usage


def _assistant(msg_id, inp, read, create, out):
    return {"type": "assistant", "message": {"id": msg_id, "usage": {
        "input_tokens": inp, "cache_read_input_tokens": read,
        "cache_creation_input_tokens": create, "output_tokens": out}}}


def _write(path, entries):
    path.write_text("\n".join(
        e if isinstance(e, str) else json.dumps(e) for e in entries) + "\n")
    return path


def test_counts_each_message_once_across_content_blocks(tmp_path):
    # A message streamed as text + tool_use is written as two lines repeating
    # the same id and identical usage (verified on real 2.1.273 transcripts).
    t = _write(tmp_path / "a.jsonl", [
        {"type": "user", "message": {"content": "go"}},
        _assistant("m1", 2, 1000, 500, 40),
        _assistant("m1", 2, 1000, 500, 40),
        _assistant("m2", 1, 1500, 200, 60),
    ])
    totals = sum_usage(t)
    assert totals == {"input": 3, "cache_read": 2500, "cache_creation": 700, "output": 100}
    assert raw_total(totals) == 3303
    assert budget_tokens(totals) == 803


def test_messages_without_id_are_each_counted(tmp_path):
    t = _write(tmp_path / "a.jsonl", [_assistant(None, 1, 0, 0, 5), _assistant("", 1, 0, 0, 5)])
    assert sum_usage(t)["output"] == 10


def test_malformed_lines_and_missing_file_are_zero(tmp_path):
    t = _write(tmp_path / "a.jsonl", ["{not json", "[]", {"type": "assistant", "message": "x"},
                                      _assistant("m1", 1, 1, 1, 1)])
    assert raw_total(sum_usage(t)) == 4
    assert sum_usage(tmp_path / "missing.jsonl") == zero_usage()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PY -m pytest ../../tests/overseer/test_transcript_usage.py -q -p no:cacheprovider`
Expected: `ModuleNotFoundError: No module named 'scripts.transcript_usage'`

- [ ] **Step 3: Implement**

```python
# plugins/overseer/scripts/transcript_usage.py
"""Real token usage for one agent, totalled from its transcript JSONL.

The SubagentStop payload names the agent's own transcript
(``agent_transcript_path``). Summing it gives the actual spend that the old
``log-usage --tokens`` guesses undercounted ~100×. Telemetry never raises:
an unreadable file or a malformed line counts as zero.
"""
from __future__ import annotations

import json
from pathlib import Path

FIELDS = ("input", "cache_read", "cache_creation", "output")
_KEYS = {
    "input": "input_tokens",
    "cache_read": "cache_read_input_tokens",
    "cache_creation": "cache_creation_input_tokens",
    "output": "output_tokens",
}


def zero_usage() -> dict[str, int]:
    return dict.fromkeys(FIELDS, 0)


def sum_usage(path: Path) -> dict[str, int]:
    """A message streamed as several content blocks is written as several
    lines repeating the same ``message.id`` with identical usage, so usage is
    counted once per id (last line wins); id-less messages count per line."""
    by_id: dict[str, dict[str, object]] = {}
    anonymous: list[dict[str, object]] = []
    try:
        lines = path.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        lines = []
    for raw in lines:
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("type") != "assistant":
            continue
        message = entry.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("usage"), dict):
            continue
        msg_id = message.get("id")
        if isinstance(msg_id, str) and msg_id:
            by_id[msg_id] = message["usage"]
        else:
            anonymous.append(message["usage"])
    totals = zero_usage()
    for usage in [*by_id.values(), *anonymous]:
        for name, key in _KEYS.items():
            value = usage.get(key)
            if isinstance(value, int):
                totals[name] += value
    return totals


def raw_total(totals: dict[str, int]) -> int:
    return sum(totals[f] for f in FIELDS)


def budget_tokens(totals: dict[str, int]) -> int:
    """Tokens newly placed in context. Cache reads are excluded: they are the
    re-read amplification, and counting them would trip every card's budget."""
    return totals["input"] + totals["cache_creation"] + totals["output"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PY -m pytest ../../tests/overseer/test_transcript_usage.py -q -p no:cacheprovider` → PASS; ruff + mypy clean.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/scripts/transcript_usage.py tests/overseer/test_transcript_usage.py
git commit -m "feat(overseer): total an agent's real usage from its transcript (WF-113)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Card review entries, section replace, orchestrator table, atomic card mutation

**Files:**
- Modify: `plugins/overseer/scripts/models.py` (add two methods to `Card`, after `review_rounds`)
- Modify: `plugins/overseer/scripts/db.py` (`_SCHEMA` + three functions + `mutate_card`)
- Test: `tests/overseer/test_card_economy.py`

**Interfaces:**
- Consumes: `models.append_to_section`, `db._upsert`, `db.row_to_card`
- Produces:
  - `Card.record_review(stage: str, round_no: int, slot: str, line: str, now: str) -> None`
  - `Card.set_section(header: str, content: str, now: str) -> None` — `header` includes `"## "`
  - `db.stamp_orchestrator(conn, card_id: str, session_id: str, now: str) -> None`
  - `db.clear_orchestrator(conn, card_id: str) -> None`
  - `db.orchestrated_cards(conn, session_id: str) -> list[Card]` — live, non-archived, status not `parked`
  - `db.mutate_card(conn, card_id: str, mutate: Callable[[Card], None]) -> Card | None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/overseer/test_card_economy.py
import threading

from factories import db_repo, make_card
from scripts import db


class TestRecordReview:
    def test_parallel_reviewers_share_one_round_header(self):
        card = make_card("WF-001")
        card.record_review("impl-review", 1, "A", "found wanting 1C 0I 0M → /d/r1-A.md", "t1")
        card.record_review("impl-review", 1, "B", "approved 0C 0I 1M → /d/r1-B.md", "t2")
        card.record_review("impl-review", 2, "A", "approved 0C 0I 0M → /d/r2-A.md", "t3")
        log = card.sections["## Review log"]
        assert log == (
            "### impl-review — round 1\n"
            "- A: found wanting 1C 0I 0M → /d/r1-A.md\n"
            "- B: approved 0C 0I 1M → /d/r1-B.md\n"
            "### impl-review — round 2\n"
            "- A: approved 0C 0I 0M → /d/r2-A.md"
        )
        assert card.review_rounds("impl-review") == 2
        assert card.updated == "t3"

    def test_round_1_header_does_not_match_round_10(self):
        card = make_card("WF-001")
        card.record_review("impl-review", 10, "A", "approved 0C 0I 0M → /d/r10-A.md", "t")
        card.record_review("impl-review", 1, "A", "approved 0C 0I 0M → /d/r1-A.md", "t")
        assert card.review_rounds("impl-review") == 2

    def test_joins_legacy_header_with_reviewer_count(self):
        card = make_card("WF-001")
        card.log_review("plan-review", 2, "legacy verdict", "t")
        card.record_review("plan-review", 1, "B", "approved 0C 0I 0M → /d/r1-B.md", "t")
        assert card.review_rounds("plan-review") == 1
        assert "- B: approved" in card.sections["## Review log"]


class TestSetSection:
    def test_replaces_existing_and_demotes_headers(self):
        card = make_card("WF-001", body="## Goal\ng\n\n## Plan\n_(pending)_\n\n## Decisions\nd")
        card.set_section("## Plan", "# Title\n## Chunks\n1. do it\n", "t")
        assert card.sections["## Plan"] == "### Title\n### Chunks\n1. do it"
        assert card.sections["## Decisions"] == "d"
        assert list(card.sections) == ["## Goal", "## Plan", "## Decisions"]

    def test_appends_missing_section(self):
        card = make_card("WF-001", body="## Goal\ng")
        card.set_section("## Verification", "all green", "t")
        assert card.sections["## Verification"] == "all green"


class TestOrchestrators:
    def test_stamp_clear_and_filter(self, tmp_path, monkeypatch):
        _, conn = db_repo(tmp_path, monkeypatch)
        for cid, status, archived in [("WF-001", "in-flight", False),
                                      ("WF-002", "parked", False),
                                      ("WF-003", "blocked", False),
                                      ("WF-004", "done", True)]:
            card = make_card(cid, status=status)
            (db.archive_card if archived else db.save_card)(conn, card)
            db.stamp_orchestrator(conn, cid, "sess-1", "t")
        db.stamp_orchestrator(conn, "WF-001", "sess-2", "t2")  # re-stamp moves it
        assert [c.id for c in db.orchestrated_cards(conn, "sess-1")] == ["WF-003"]
        assert [c.id for c in db.orchestrated_cards(conn, "sess-2")] == ["WF-001"]
        db.clear_orchestrator(conn, "WF-003")
        assert db.orchestrated_cards(conn, "sess-1") == []


class TestMutateCard:
    def test_missing_card_returns_none(self, tmp_path, monkeypatch):
        _, conn = db_repo(tmp_path, monkeypatch)
        assert db.mutate_card(conn, "WF-404", lambda c: None) is None

    def test_concurrent_mutations_both_land(self, tmp_path, monkeypatch):
        repo, conn = db_repo(tmp_path, monkeypatch)
        db.save_card(conn, make_card("WF-001"))
        barrier = threading.Barrier(8)

        def worker(slot: str) -> None:
            own = db.connect(repo, migrate=False)
            barrier.wait()
            db.mutate_card(own, "WF-001", lambda c: c.record_review(
                "impl-review", 1, slot, f"approved 0C 0I 0M → /d/r1-{slot}.md", "t"))
            own.close()

        threads = [threading.Thread(target=worker, args=(s,)) for s in "ABCDEFGH"]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        log = db.load_card(conn, "WF-001").sections["## Review log"]
        assert all(f"- {s}: approved" in log for s in "ABCDEFGH")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PY -m pytest ../../tests/overseer/test_card_economy.py -q -p no:cacheprovider`
Expected: FAIL — `AttributeError: 'Card' object has no attribute 'record_review'` (and the db tests on missing functions).

- [ ] **Step 3: Implement — `models.py`**

Add after `review_rounds` in `class Card`:

```python
    def record_review(self, stage: str, round_no: int, slot: str, line: str, now: str) -> None:
        """One reviewer's verdict line under its round's ``### `` header in
        ``## Review log`` (WF-113 report hook). Parallel reviewers share one
        header, so ``review_rounds`` keeps counting rounds, not verdicts. A
        legacy ``log_review`` header ("… round N (k reviewers)") is joined."""
        header = f"### {stage} — round {round_no}"
        entry = f"- {slot}: {line}"
        lines = self.body.split("\n")
        start = next(
            (i for i, text in enumerate(lines)
             if text == header or text.startswith(header + " (")),
            None,
        )
        if start is None:
            self.body = append_to_section(self.body, "## Review log", f"{header}\n{entry}")
        else:
            end = start + 1
            while end < len(lines) and not lines[end].startswith(("### ", "## ")):
                end += 1
            while end > start + 1 and not lines[end - 1].strip():
                end -= 1
            lines.insert(end, entry)
            self.body = "\n".join(lines)
        self.updated = now

    def set_section(self, header: str, content: str, now: str) -> None:
        """Replace a ``## `` section's content (appended if absent). Headers
        inside ``content`` are demoted to ``### `` so a written plan can never
        split the card into new top-level sections."""
        demoted = []
        for text in content.strip().split("\n"):
            if text.startswith("# "):
                text = "### " + text[2:]
            elif text.startswith("## "):
                text = "### " + text[3:]
            demoted.append(text)
        new = "\n".join(demoted)
        lines = self.body.split("\n")
        if header not in lines:
            self.body = f"{self.body.rstrip()}\n\n{header}\n{new}".lstrip("\n")
        else:
            start = lines.index(header)
            end = start + 1
            while end < len(lines) and not lines[end].startswith("## "):
                end += 1
            tail = lines[end:]
            self.body = "\n".join([*lines[: start + 1], new, *([""] if tail else []), *tail])
        self.updated = now
```

- [ ] **Step 4: Implement — `db.py`**

Append to the `_SCHEMA` string (before its closing `"""`):

```sql
CREATE TABLE IF NOT EXISTS orchestrators (
    card_id    TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    stamped    TEXT NOT NULL
);
```

Add `from collections.abc import Callable` to the imports, and these functions after `claim_card`:

```python
def stamp_orchestrator(conn: sqlite3.Connection, card_id: str, session_id: str, now: str) -> None:
    """Record which Claude session orchestrates ``card_id`` (WF-113 §5.1). A
    side table rather than a ``cards`` column: the guard hook is its only
    reader, so the Card model, backups and dashboard stay untouched."""
    conn.execute(
        "INSERT INTO orchestrators(card_id, session_id, stamped) VALUES(?, ?, ?) "
        "ON CONFLICT(card_id) DO UPDATE SET session_id = excluded.session_id, "
        "stamped = excluded.stamped",
        (card_id, session_id, now),
    )
    conn.commit()


def clear_orchestrator(conn: sqlite3.Connection, card_id: str) -> None:
    conn.execute("DELETE FROM orchestrators WHERE card_id = ?", (card_id,))
    conn.commit()


def orchestrated_cards(conn: sqlite3.Connection, session_id: str) -> "list[Card]":
    """Live cards this session orchestrates. Parked cards are shelved, so the
    guard lets go of them; blocked cards keep it (still the session's card)."""
    rows = conn.execute(
        "SELECT c.* FROM cards c JOIN orchestrators o ON o.card_id = c.id "
        "WHERE o.session_id = ? AND c.archived = 0 AND c.status != 'parked' "
        "ORDER BY c.id",
        (session_id,),
    ).fetchall()
    return [row_to_card(r) for r in rows]


def mutate_card(
    conn: sqlite3.Connection, card_id: str, mutate: "Callable[[Card], None]"
) -> "Card | None":
    """Load → change → save one card inside a single ``BEGIN IMMEDIATE``
    transaction. Parallel reviewers' report hooks finish together; the CLI's
    ``_sync`` whole-row upsert is last-write-wins and would drop verdicts."""
    conn.commit()  # close any implicit transaction before taking the write lock
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            conn.rollback()
            return None
        card = row_to_card(row)
        mutate(card)
        _upsert(conn, card, archived=row["archived"], commit=False)
        conn.commit()
        return card
    except BaseException:
        conn.rollback()
        raise
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `$PY -m pytest ../../tests/overseer/test_card_economy.py ../../tests/overseer/test_models.py ../../tests/overseer/test_db.py -q -p no:cacheprovider` → PASS; ruff + mypy clean.

- [ ] **Step 6: Commit**

```bash
git add plugins/overseer/scripts/models.py plugins/overseer/scripts/db.py tests/overseer/test_card_economy.py
git commit -m "feat(overseer): per-reviewer review entries, section replace, orchestrator table, atomic card mutation (WF-113)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Pending Learned facts and `set-section`

**Files:**
- Create: `plugins/overseer/scripts/pending.py`
- Modify: `plugins/overseer/scripts/cli.py` (verbs `set-section`, `accept-fact`, `reject-fact`; `facts --pending --card`)
- Test: `tests/overseer/test_pending.py`

**Interfaces:**
- Consumes: `knowledge.knowledge_root`, `knowledge.ensure_kb`, `knowledge.mint_fact_id`, `knowledge.save_fact`, `knowledge.Fact`, `Card.set_section`
- Produces:
  - `@dataclass class PendingFact(id: str, card: str, statement: str, tags: list[str], source: str, status: str, reason: str)`
  - `parse_learned(text: str) -> list[tuple[str, list[str]]]`
  - `add_pending(repo_root: Path, card: str, statement: str, tags: list[str], source: str) -> PendingFact`
  - `load_pending(repo_root: Path) -> list[PendingFact]`
  - `set_status(repo_root: Path, fact_id: str, status: str, reason: str = "") -> PendingFact`
  - CLI: `set-section <card> --section Plan|Verification|Decisions --file <path>`; `facts --pending [--card ID] [--json]`; `accept-fact <P-id>` (prints the new `KB-` id); `reject-fact <P-id> --reason TEXT`

- [ ] **Step 1: Write the failing tests**

```python
# tests/overseer/test_pending.py
import json

import pytest

from scripts import db
from scripts.cli import main
from scripts.knowledge import knowledge_root, load_facts
from scripts.pending import add_pending, load_pending, parse_learned, set_status


@pytest.fixture
def repo(tmp_path):
    assert main(["--root", str(tmp_path), "init"]) == 0
    return tmp_path


def run(repo, *argv):
    return main(["--root", str(repo), *argv])


class TestParseLearned:
    def test_forms(self):
        text = (
            "findings...\n"
            "Learned: dbt builds need --target ci [tags: dbt, ci]\n"
            "- Learned: the ledger CLI is single-writer\n"
            "Learned: none\n"
            "Learned:   \n"
            "not Learned: inline mention\n"
        )
        assert parse_learned(text) == [
            ("dbt builds need --target ci", ["dbt", "ci"]),
            ("the ledger CLI is single-writer", []),
        ]


class TestQueue:
    def test_add_load_and_status(self, repo):
        f = add_pending(repo, "WF-001", "a fact", ["x"], "/d/r1-A.md")
        assert f.id.startswith("P-") and f.status == "pending"
        assert [p.statement for p in load_pending(repo)] == ["a fact"]
        set_status(repo, f.id, "rejected", "not durable")
        assert load_pending(repo)[0].reason == "not durable"
        with pytest.raises(ValueError, match="already rejected"):
            set_status(repo, f.id, "accepted")
        with pytest.raises(FileNotFoundError):
            set_status(repo, "P-nope", "accepted")

    def test_corrupt_line_is_skipped(self, repo):
        add_pending(repo, "WF-001", "ok", [], "")
        path = knowledge_root(repo) / "pending.jsonl"
        path.write_text(path.read_text() + "{broken\n")
        assert len(load_pending(repo)) == 1


class TestCli:
    def test_facts_pending_accept_reject(self, repo, capsys):
        a = add_pending(repo, "WF-001", "keep me", ["t"], "/d/r1-A.md")
        b = add_pending(repo, "WF-002", "drop me", [], "/d/r1-B.md")
        capsys.readouterr()
        assert run(repo, "facts", "--pending", "--card", "WF-001") == 0
        assert capsys.readouterr().out.strip() == f"{a.id} WF-001 (t): keep me"
        assert run(repo, "accept-fact", a.id) == 0
        kb_id = capsys.readouterr().out.strip()
        facts, _ = load_facts(knowledge_root(repo))
        assert [(x.id, x.statement, x.source) for x in facts] == [
            (kb_id, "keep me", "WF-001 /d/r1-A.md")]
        assert run(repo, "reject-fact", b.id, "--reason", "noise") == 0
        assert run(repo, "facts", "--pending", "--json") == 0
        capsys.readouterr()
        assert run(repo, "facts", "--pending") == 0
        assert capsys.readouterr().out.strip() == "No pending facts."

    def test_set_section(self, repo, tmp_path):
        run(repo, "new-card", "--title", "T")
        plan = tmp_path / "plan.md"
        plan.write_text("## Chunks\n1. x")
        assert run(repo, "set-section", "WF-001", "--section", "Plan", "--file", str(plan)) == 0
        card = db.load_card(db.connect(repo, migrate=False), "WF-001")
        assert card.sections["## Plan"] == "### Chunks\n1. x"

    def test_set_section_rejects_unknown_section(self, repo, tmp_path):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "set-section", "WF-001", "--section", "Goal", "--file", "x") == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PY -m pytest ../../tests/overseer/test_pending.py -q -p no:cacheprovider`
Expected: `ModuleNotFoundError: No module named 'scripts.pending'`

- [ ] **Step 3: Implement `pending.py`**

```python
# plugins/overseer/scripts/pending.py
"""Pending Learned facts (WF-113 §5.5).

Agents write ``Learned: <sentence> [tags: a, b]`` lines into their detail
files; the report hook queues them here; the orchestrator adjudicates at a
stage boundary — accept (becomes a real KB fact) or reject (kept, with a
reason, so the same claim is recognisable if re-proposed). The queue is one
JSONL file beside the knowledge base: appends are the hot path (parallel
hooks), status changes are rare and rewrite the file atomically.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from scripts.knowledge import knowledge_root

PENDING_FILENAME = "pending.jsonl"
_LEARNED_RE = re.compile(r"\A\s*(?:[-*]\s+)?Learned:\s*(?P<text>.*?)\s*\Z")
_TAGS_RE = re.compile(r"\s*\[tags:\s*(?P<tags>[^\]]*)\]\s*\Z")


@dataclass
class PendingFact:
    id: str
    card: str
    statement: str
    tags: list[str] = field(default_factory=list)
    source: str = ""
    status: str = "pending"
    reason: str = ""


def parse_learned(text: str) -> list[tuple[str, list[str]]]:
    found: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        match = _LEARNED_RE.match(line)
        if match is None:
            continue
        statement = match["text"]
        tags: list[str] = []
        tag_match = _TAGS_RE.search(statement)
        if tag_match:
            tags = [t.strip() for t in tag_match["tags"].split(",") if t.strip()]
            statement = statement[: tag_match.start()].strip()
        if not statement or statement.lower().rstrip(".") == "none":
            continue
        found.append((statement, tags))
    return found


def _path(repo_root: Path) -> Path:
    return knowledge_root(repo_root) / PENDING_FILENAME


def add_pending(
    repo_root: Path, card: str, statement: str, tags: list[str], source: str
) -> PendingFact:
    fact = PendingFact(
        id=f"P-{uuid.uuid4().hex[:6]}", card=card, statement=statement, tags=tags, source=source
    )
    path = _path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(asdict(fact)) + "\n")
    return fact


def load_pending(repo_root: Path) -> list[PendingFact]:
    path = _path(repo_root)
    if not path.exists():
        return []
    facts: list[PendingFact] = []
    for raw in path.read_text().splitlines():
        try:
            facts.append(PendingFact(**json.loads(raw)))
        except (ValueError, TypeError):
            continue
    return facts


def set_status(repo_root: Path, fact_id: str, status: str, reason: str = "") -> PendingFact:
    facts = load_pending(repo_root)
    match = next((f for f in facts if f.id == fact_id), None)
    if match is None:
        raise FileNotFoundError(f"no pending fact with id {fact_id}")
    if match.status != "pending":
        raise ValueError(f"{fact_id} is already {match.status}")
    match.status = status
    match.reason = reason
    path = _path(repo_root)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(json.dumps(asdict(f)) + "\n" for f in facts))
    os.replace(tmp, path)
    return match
```

- [ ] **Step 4: Implement the CLI verbs in `cli.py`**

Add import: `from dataclasses import asdict` and `from scripts.pending import load_pending, set_status as set_pending_status`.

In `cmd_facts`, insert at the top of the function body:

```python
    if args.pending:
        rows = [
            f for f in load_pending(args.root)
            if f.status == "pending" and (not args.card or f.card == args.card)
        ]
        if args.json:
            print(json.dumps([asdict(f) for f in rows], indent=2))
            return 0
        if not rows:
            print("No pending facts.")
            return 0
        for f in rows:
            print(f"{f.id} {f.card} ({', '.join(f.tags) or 'no tags'}): {f.statement}")
        return 0
```

Add the verbs after `cmd_facts`:

```python
SECTION_NAMES = ("Plan", "Verification", "Decisions")


def cmd_set_section(args: argparse.Namespace) -> int:
    """Replace one prose section from a file — written by agents (via the
    report hook) so plan and verification text never transit the orchestrator."""
    content = Path(args.file).read_text()
    card = _load(args.root, args.card_id)
    card.set_section(f"## {args.section}", content, _now())
    card.ack_claim()  # work verb — design spec §3 ack list
    _sync(args.root, card)
    print(f"{card.id} ## {args.section} set")
    return 0


def cmd_accept_fact(args: argparse.Namespace) -> int:
    _conn(args.root)  # migration-ordering guard, as cmd_add_fact
    pending = next((f for f in load_pending(args.root) if f.id == args.fact_id), None)
    if pending is None:
        raise FileNotFoundError(f"no pending fact with id {args.fact_id}")
    kb = knowledge_root(args.root)
    ensure_kb(kb)
    fact = Fact(
        id=mint_fact_id(kb),
        statement=pending.statement,
        tags=pending.tags,
        source=f"{pending.card} {pending.source}".strip(),
        created=_today(),
        verified=_today(),
        status="active",
    )
    save_fact(kb, fact)
    set_pending_status(args.root, pending.id, "accepted")
    _report_quarantined(rebuild_knowledge_index(args.root, _today()))
    print(fact.id)
    return 0


def cmd_reject_fact(args: argparse.Namespace) -> int:
    set_pending_status(args.root, args.fact_id, "rejected", args.reason)
    print(f"{args.fact_id} rejected")
    return 0
```

In `build_parser`, extend the `facts` subparser and add the new ones next to it:

```python
    p.add_argument("--pending", action="store_true")
    p.add_argument("--card")
```

```python
    p = sub.add_parser("set-section")
    p.add_argument("card_id")
    p.add_argument("--section", required=True, choices=SECTION_NAMES)
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_set_section)

    p = sub.add_parser("accept-fact")
    p.add_argument("fact_id")
    p.set_defaults(func=cmd_accept_fact)

    p = sub.add_parser("reject-fact")
    p.add_argument("fact_id")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_reject_fact)
```

(`ValueError`/`FileNotFoundError` from `set_status` already become exit 1 in `main`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `$PY -m pytest ../../tests/overseer/test_pending.py ../../tests/overseer/test_knowledge.py -q -p no:cacheprovider` → PASS; ruff + mypy clean.

- [ ] **Step 6: Commit**

```bash
git add plugins/overseer/scripts/pending.py plugins/overseer/scripts/cli.py tests/overseer/test_pending.py
git commit -m "feat(overseer): pending Learned-fact queue and set-section verb (WF-113)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `SubagentStop` report hook

**Files:**
- Create: `plugins/overseer/scripts/report_hook.py`
- Create: `plugins/overseer/hooks/report.sh` (mode 755)
- Modify: `plugins/overseer/hooks/hooks.json`
- Modify: `plugins/overseer/scripts/cli.py` (`report-hook` verb; `usage` warns on unparsed/overrun)
- Test: `tests/overseer/test_report_hook.py`

**Interfaces:**
- Consumes: Task 1 (`parse_reply`, `role_of`, `reply_words`, `REPLY_WORD_CAP`, `ReplyError`, `Reply`), Task 2 (`sum_usage`, `zero_usage`, `raw_total`, `budget_tokens`), Task 3 (`db.mutate_card`, `Card.record_review`, `Card.set_section`), Task 4 (`parse_learned`, `add_pending`), `usage.append_usage`, `store.state_root`
- Produces:
  - `report_hook.handle(payload: dict[str, object], repo_root: Path, now: str) -> dict[str, object] | None` — the usage entry appended, or None for non-overseer agents
  - usage entry keys: `ts, card, role, stage, round, tokens, input, cache_read, cache_creation, output, budget_tokens, reply_words, overrun, agent_id, source` (+ `unparsed`, `error`, `tripwire` when relevant)
  - CLI `report-hook` (always exit 0, no stdout)

- [ ] **Step 1: Write the failing tests**

```python
# tests/overseer/test_report_hook.py
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import db
from scripts.cli import main
from scripts.dispatch import dispatch_dir
from scripts.pending import load_pending
from scripts.usage import load_usage
from scripts.store import state_root

PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "overseer"
BASH = shutil.which("bash") or "/bin/bash"


@pytest.fixture
def repo(tmp_path):
    assert main(["--root", str(tmp_path), "init"]) == 0
    assert main(["--root", str(tmp_path), "new-card", "--title", "T", "--estimate", "1k"]) == 0
    return tmp_path


def _transcript(tmp_path, out=40, create=500, inp=2, read=9000):
    path = tmp_path / "agent.jsonl"
    path.write_text(json.dumps({"type": "assistant", "message": {"id": "m1", "usage": {
        "input_tokens": inp, "cache_read_input_tokens": read,
        "cache_creation_input_tokens": create, "output_tokens": out}}}) + "\n")
    return path


def _hook(repo, monkeypatch, payload):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(repo), **payload})))
    assert main(["--root", str(repo), "report-hook"]) == 0


def _card(repo):
    return db.load_card(db.connect(repo, migrate=False), "WF-001")


def _detail(repo, stage, name, text):
    d = dispatch_dir(repo, "WF-001", stage)
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text)
    return d / name


def test_reviewer_verdict_lands_in_review_log_usage_and_pending(repo, tmp_path, monkeypatch, capsys):
    path = _detail(repo, "impl-review", "r1-A.md",
                   "verdict: found wanting\n...\nLearned: x is y [tags: t]\n")
    _hook(repo, monkeypatch, {
        "agent_type": "overseer:overseer-reviewer", "agent_id": "a1",
        "agent_transcript_path": str(_transcript(tmp_path)),
        "last_assistant_message": f"found wanting 1C 2I 0M → {path}",
    })
    assert capsys.readouterr().out == ""
    card = _card(repo)
    assert f"- A: found wanting 1C 2I 0M → {path}" in card.sections["## Review log"]
    assert card.budget_actual == 0  # reviewer spend is measurement only
    [entry], _ = load_usage(state_root(repo))
    assert entry["card"] == "WF-001" and entry["role"] == "reviewer" and entry["round"] == 1
    assert (entry["tokens"], entry["budget_tokens"]) == (9542, 542)
    assert entry["overrun"] is False and entry["source"] == "hook"
    [fact] = load_pending(repo)
    assert (fact.statement, fact.tags, fact.source) == ("x is y", ["t"], str(path))


def test_implementer_spend_feeds_budget_and_progress(repo, tmp_path, monkeypatch):
    path = _detail(repo, "implementation", "c2.md", "done")
    _hook(repo, monkeypatch, {
        "agent_type": "overseer:overseer-implementer", "agent_id": "a2",
        "agent_transcript_path": str(_transcript(tmp_path)),
        "last_assistant_message": f"DONE tests 5/5 abc1234 → {path}",
    })
    card = _card(repo)
    assert card.budget_actual == 542
    assert "chunk 2 — DONE tests 5/5 abc1234" in card.sections["## Progress log"]


def test_planner_writes_plan_section(repo, tmp_path, monkeypatch):
    path = _detail(repo, "planning", "plan.md", "## Chunks\n1. build it")
    _hook(repo, monkeypatch, {
        "agent_type": "overseer:overseer-planner", "agent_id": "a3",
        "agent_transcript_path": str(_transcript(tmp_path)),
        "last_assistant_message": f"DONE → {path}",
    })
    assert _card(repo).sections["## Plan"] == "### Chunks\n1. build it"


def test_verifier_writes_verification_section(repo, tmp_path, monkeypatch):
    path = _detail(repo, "verification", "verification.md", "pytest: 619 passed")
    _hook(repo, monkeypatch, {
        "agent_type": "overseer:overseer-verifier", "agent_id": "a4",
        "agent_transcript_path": str(_transcript(tmp_path)),
        "last_assistant_message": f"PASS → {path}",
    })
    assert _card(repo).sections["## Verification"] == "pytest: 619 passed"


def test_tripwire_is_recorded(repo, tmp_path, monkeypatch):
    path = _detail(repo, "implementation", "c1.md", "done")
    _hook(repo, monkeypatch, {
        "agent_type": "overseer:overseer-implementer", "agent_id": "a5",
        "agent_transcript_path": str(_transcript(tmp_path, create=5000)),
        "last_assistant_message": f"DONE tests 1/1 - → {path}",
    })
    [entry], _ = load_usage(state_root(repo))
    assert entry["tripwire"] is True  # 5042 ≥ 2 × 1k estimate


@pytest.mark.parametrize("message, error", [
    ("I reviewed everything and it looks great overall.", "does not match"),
    ("approved 0C 0I 0M → /elsewhere/dispatch/WF-001/impl-review/r1-A.md",
     "outside this repo's dispatch directory"),
])
def test_unparsed_reply_is_recorded_not_retried(repo, tmp_path, monkeypatch, capsys, message, error):
    _hook(repo, monkeypatch, {
        "agent_type": "overseer:overseer-reviewer", "agent_id": "a6",
        "agent_transcript_path": str(_transcript(tmp_path)),
        "last_assistant_message": message,
    })
    assert capsys.readouterr().out == ""
    [entry], _ = load_usage(state_root(repo))
    assert entry["card"] is None and error in entry["error"] and entry["unparsed"] == message
    assert "- A:" not in _card(repo).body


def test_missing_detail_file_is_noted_but_verdict_still_recorded(repo, tmp_path, monkeypatch):
    d = dispatch_dir(repo, "WF-001", "impl-review")
    line = "approved 0C 0I 0M → " + str(d / "r1-A.md")
    _hook(repo, monkeypatch, {
        "agent_type": "overseer:overseer-reviewer", "agent_id": "a7",
        "agent_transcript_path": str(_transcript(tmp_path)),
        "last_assistant_message": line,
    })
    [entry], _ = load_usage(state_root(repo))
    assert entry["error"] == "detail file missing" and entry["overrun"] is False
    assert f"- A: {line}" in _card(repo).sections["## Review log"]


def test_non_overseer_agent_is_ignored(repo, monkeypatch):
    _hook(repo, monkeypatch, {"agent_type": "general-purpose", "last_assistant_message": "hi"})
    entries, _ = load_usage(state_root(repo))
    assert entries == []


def test_usage_warns_about_unparsed_and_overruns(repo, tmp_path, monkeypatch, capsys):
    _hook(repo, monkeypatch, {
        "agent_type": "overseer:overseer-fixer", "agent_id": "a8",
        "last_assistant_message": " ".join(["word"] * 30),
    })
    capsys.readouterr()
    assert main(["--root", str(repo), "usage"]) == 0
    assert "1 unparsed agent reply, 1 over the 25-word cap" in capsys.readouterr().err


def test_shell_wrapper_exits_zero_silently_on_garbage(repo):
    result = subprocess.run(
        [BASH, str(PLUGIN_ROOT / "hooks" / "report.sh")], input="not json",
        capture_output=True, text=True,
        env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
             "OVERSEER_PYTHON": sys.executable},
    )
    assert (result.returncode, result.stdout) == (0, "")


def test_hooks_json_registers_subagent_stop():
    hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    commands = [h["command"] for entry in hooks["SubagentStop"] for h in entry["hooks"]]
    assert commands == ["${CLAUDE_PLUGIN_ROOT}/hooks/report.sh"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PY -m pytest ../../tests/overseer/test_report_hook.py -q -p no:cacheprovider`
Expected: FAIL — `report-hook` is not a CLI verb (exit 1 assertion), missing `report.sh`.

- [ ] **Step 3: Implement `report_hook.py`**

```python
# plugins/overseer/scripts/report_hook.py
"""SubagentStop report hook (WF-113 §5.4).

Turns an overseer agent's one-line reply into ledger records without spending
an agent or orchestrator turn: parse the line, total real usage from the
agent's transcript, write the card and usage.jsonl, queue Learned lines.

Record-only by design. A Stop/SubagentStop hook that blocks makes the agent
continue, which costs a turn at the agent's full context and risks a loop —
so a malformed or over-long reply is *recorded* (``unparsed``/``overrun``),
never bounced. The cap is stated in the dispatch instead.
"""
from __future__ import annotations

from pathlib import Path

from scripts import db
from scripts.dispatch import (
    REPLY_WORD_CAP,
    Reply,
    ReplyError,
    parse_reply,
    reply_words,
    role_of,
)
from scripts.models import Card
from scripts.pending import add_pending, parse_learned
from scripts.store import state_root
from scripts.transcript_usage import budget_tokens, raw_total, sum_usage, zero_usage
from scripts.usage import append_usage


def _record(card: Card, reply: Reply, detail: str, spend: int, now: str) -> None:
    """Budget semantics are unchanged from telemetry.md: implementer and fixer
    spend feeds ``budget_actual``; planner/reviewer/verifier spend is
    measurement only (usage.jsonl)."""
    if reply.role == "reviewer":
        card.record_review(reply.stage, reply.round or 0, reply.slot or "?", reply.line, now)
    elif reply.role == "fixer":
        card.log_progress(f"{reply.stage} r{reply.round} fix — {reply.line}", spend, now)
    elif reply.role == "implementer":
        card.log_progress(f"chunk {reply.chunk} — {reply.line}", spend, now)
    elif reply.role == "planner":
        if reply.status == "DONE" and detail.strip():
            card.set_section("## Plan", detail, now)
    elif reply.role == "verifier":
        if detail.strip():
            card.set_section("## Verification", detail, now)


def handle(payload: dict[str, object], repo_root: Path, now: str) -> dict[str, object] | None:
    role = role_of(payload.get("agent_type"))
    if role is None:
        return None
    message = payload.get("last_assistant_message")
    text = message if isinstance(message, str) else ""
    transcript = payload.get("agent_transcript_path")
    totals = sum_usage(Path(transcript)) if isinstance(transcript, str) and transcript else zero_usage()
    words = reply_words(text)
    root = state_root(repo_root)
    entry: dict[str, object] = {
        "ts": now, "card": None, "role": role, "stage": None, "round": None,
        "tokens": raw_total(totals), **totals, "budget_tokens": budget_tokens(totals),
        "reply_words": words, "overrun": words > REPLY_WORD_CAP,
        "agent_id": payload.get("agent_id"), "source": "hook",
    }
    try:
        reply = parse_reply(role, text)
        if not reply.path.resolve().is_relative_to((root / "dispatch").resolve()):
            raise ReplyError("reply path is outside this repo's dispatch directory")
    except ReplyError as exc:
        entry.update(unparsed=text[:500], error=str(exc))
        append_usage(root, entry)
        return entry
    entry.update(card=reply.card, stage=reply.stage, round=reply.round)
    try:
        detail = reply.path.read_text()
    except OSError:
        detail = ""
        entry["error"] = "detail file missing"
    spend = budget_tokens(totals)
    conn = db.connect(repo_root)
    try:
        card = db.mutate_card(conn, reply.card, lambda c: _record(c, reply, detail, spend, now))
    finally:
        conn.close()
    if card is None:
        entry["error"] = f"no card {reply.card}"
    else:
        for statement, tags in parse_learned(detail):
            add_pending(repo_root, reply.card, statement, tags, str(reply.path))
        if card.tripwire_breached:
            entry["tripwire"] = True
    append_usage(root, entry)
    return entry
```

- [ ] **Step 4: Wire the CLI**

Import `from scripts import config, db, liveness, report_hook` (extend the existing line) and `from scripts.dispatch import REPLY_WORD_CAP`. Add:

```python
def cmd_report_hook(args: argparse.Namespace) -> int:
    """SubagentStop backend — scripts/report_hook.py. Always exit 0, no
    output: a failing telemetry hook must never stall or steer an agent."""
    try:
        payload = _read_hook_payload()
        repo_root = _hook_root(payload, args)
        if state_root(repo_root).is_dir():
            report_hook.handle(payload, repo_root, _now())
    except Exception:
        pass
    return 0
```

Parser: `sub.add_parser("report-hook").set_defaults(func=cmd_report_hook)` beside `claim-stop-hook`.

In `cmd_usage`, after the `skipped` warning block:

```python
    scoped = [e for e in entries if not args.card or e.get("card") == args.card]
    unparsed = sum(1 for e in scoped if e.get("unparsed") is not None)
    overruns = sum(1 for e in scoped if e.get("overrun"))
    if unparsed or overruns:
        noun = "reply" if unparsed == 1 else "replies"
        print(
            f"warning: {unparsed} unparsed agent {noun}, "
            f"{overruns} over the {REPLY_WORD_CAP}-word cap",
            file=sys.stderr,
        )
```

- [ ] **Step 5: Shell wrapper and registration**

`plugins/overseer/hooks/report.sh` (then `chmod 755`):

```bash
#!/usr/bin/env bash
# Overseer SubagentStop hook — record an overseer agent's one-line reply and
# real usage into the ledger (WF-113 spec §5.4). Record-only: it never blocks
# (a blocking SubagentStop makes the agent continue — an extra full-context
# turn and a loop risk), so the trap forces exit 0 whatever the CLI does.
trap 'exit 0' EXIT

input="$(cat)"

py="${OVERSEER_PYTHON:-python3}"
if [ -z "${OVERSEER_PYTHON:-}" ] && [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python" ]; then
  py="${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python"
fi

printf '%s' "$input" \
  | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" report-hook >/dev/null 2>&1 || true

exit 0
```

In `hooks/hooks.json`, add a top-level key inside `"hooks"`:

```json
    "SubagentStop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/report.sh"
          }
        ]
      }
    ],
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `$PY -m pytest ../../tests/overseer/test_report_hook.py ../../tests/overseer/test_hooks.py ../../tests/overseer/test_cli.py -q -p no:cacheprovider` → PASS; ruff + mypy clean.

- [ ] **Step 7: Commit**

```bash
git add plugins/overseer/scripts/report_hook.py plugins/overseer/hooks/report.sh plugins/overseer/hooks/hooks.json plugins/overseer/scripts/cli.py tests/overseer/test_report_hook.py
git commit -m "feat(overseer): SubagentStop hook records agent replies and real usage in the ledger (WF-113)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Stamp the orchestrator session; `release`

**Files:**
- Modify: `plugins/overseer/scripts/cli.py`
- Modify: `tests/overseer/conftest.py` (strip ambient session/guard env)
- Test: `tests/overseer/test_orchestrator_stamp.py`

**Interfaces:**
- Consumes: Task 3 (`db.stamp_orchestrator`, `db.clear_orchestrator`, `db.orchestrated_cards`)
- Produces:
  - `SESSION_ENV = "CLAUDE_CODE_SESSION_ID"`
  - `_stamp_orchestrator(repo_root: Path, card_id: str) -> None` (used again by Tasks 8, 9)
  - stamped by: `set-stage`, `log-progress`, `log-review`; cleared by: `done`, `abandon`, `park`, `unclaim`, `release`
  - CLI `release <card>`

- [ ] **Step 1: Update conftest**

Append inside `_no_ambient_task_env` (these are set for real when the suite runs inside Claude Code):

```python
    # WF-113: work verbs stamp the calling Claude session as a card's
    # orchestrator, and the PreToolUse guard reads OVERSEER_GUARD. A suite run
    # from inside Claude Code inherits both — strip them so no test depends
    # on (or records) the developer's live session.
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("OVERSEER_GUARD", raising=False)
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/overseer/test_orchestrator_stamp.py
import pytest

from scripts import db
from scripts.cli import main


@pytest.fixture
def repo(tmp_path):
    assert main(["--root", str(tmp_path), "init"]) == 0
    assert main(["--root", str(tmp_path), "new-card", "--title", "T"]) == 0
    return tmp_path


def run(repo, *argv):
    return main(["--root", str(repo), *argv])


def _orchestrated(repo, session="sess-1"):
    return [c.id for c in db.orchestrated_cards(db.connect(repo, migrate=False), session)]


@pytest.mark.parametrize("argv", [
    ("set-stage", "WF-001", "planning"),
    ("log-progress", "WF-001", "--note", "n", "--tokens", "1k"),
    ("log-review", "WF-001", "--stage", "plan-review", "--reviewers", "1", "--verdict", "ok"),
])
def test_work_verbs_stamp_calling_session(repo, monkeypatch, argv):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-1")
    assert run(repo, *argv) == 0
    assert _orchestrated(repo) == ["WF-001"]


def test_no_session_env_is_a_noop(repo):
    assert run(repo, "set-stage", "WF-001", "planning") == 0
    conn = db.connect(repo, migrate=False)
    assert conn.execute("SELECT COUNT(*) FROM orchestrators").fetchone()[0] == 0


@pytest.mark.parametrize("argv", [
    ("park", "WF-001"), ("unclaim", "WF-001"), ("release", "WF-001"),
    ("done", "WF-001"), ("abandon", "WF-001"),
])
def test_closing_verbs_clear_the_stamp(repo, monkeypatch, argv):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-1")
    run(repo, "set-stage", "WF-001", "planning")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    assert run(repo, *argv) == 0
    conn = db.connect(repo, migrate=False)
    assert conn.execute("SELECT COUNT(*) FROM orchestrators").fetchone()[0] == 0


def test_release_unknown_card_fails(repo):
    assert run(repo, "release", "WF-404") == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `$PY -m pytest ../../tests/overseer/test_orchestrator_stamp.py -q -p no:cacheprovider`
Expected: FAIL — nothing stamped; `release` unknown verb.

- [ ] **Step 4: Implement**

Add near `_load` in `cli.py`:

```python
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"


def _stamp_orchestrator(repo_root: Path, card_id: str) -> None:
    """Record the calling Claude session as ``card_id``'s orchestrator (WF-113
    §5.1) so the PreToolUse guard can tell the hub from its agents. Claude
    Code sets CLAUDE_CODE_SESSION_ID in every Bash call; outside Claude Code
    it is absent and this is a no-op."""
    session_id = os.environ.get(SESSION_ENV)
    if session_id:
        db.stamp_orchestrator(_conn(repo_root), card_id, session_id, _now())


def _release_orchestrator(repo_root: Path, card_id: str) -> None:
    db.clear_orchestrator(_conn(repo_root), card_id)
```

Call `_stamp_orchestrator(args.root, card.id)` after `_sync(...)` in `cmd_set_stage`, `cmd_log_review`, and in `cmd_log_progress` immediately after its `_sync(args.root, card)` (before the tripwire check). Call `_release_orchestrator(args.root, card.id)` after the save in `_close` (after `db.archive_card`), `cmd_park`, and `cmd_unclaim`. Add:

```python
def cmd_release(args: argparse.Namespace) -> int:
    """The guard's per-card escape hatch: forget this card's orchestrator
    until its next work verb re-stamps it."""
    card = _load(args.root, args.card_id)
    _release_orchestrator(args.root, card.id)
    print(f"{card.id} released — guard off until its next work verb")
    return 0
```

Parser, beside `unclaim`:

```python
    p = sub.add_parser("release")
    p.add_argument("card_id")
    p.set_defaults(func=cmd_release)
```

- [ ] **Step 5: Run the full suite** (conftest changed)

Run: `$PY -m pytest -q -p no:cacheprovider` → all PASS (≥ 619 + new); ruff + mypy clean.

- [ ] **Step 6: Commit**

```bash
git add plugins/overseer/scripts/cli.py tests/overseer/conftest.py tests/overseer/test_orchestrator_stamp.py
git commit -m "feat(overseer): work verbs stamp the orchestrator session; release verb (WF-113)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: `PreToolUse` guard and Read limit

**Files:**
- Create: `plugins/overseer/scripts/guard.py`
- Create: `plugins/overseer/hooks/pretool.sh` (mode 755)
- Modify: `plugins/overseer/hooks/hooks.json`
- Modify: `plugins/overseer/scripts/cli.py` (`pretool-hook` verb)
- Test: `tests/overseer/test_guard.py`

**Interfaces:**
- Consumes: Task 1 (`role_of`, `is_hub_agent`), Task 3 (`db.orchestrated_cards`), Task 6 (stamping), `config.load_config`, `config._config_dir`, `models.format_tokens`
- Produces:
  - `READ_LIMIT_DEFAULT = 400`
  - `@dataclass(frozen=True) class Verdict(deny_reason: str | None = None, updated_input: dict[str, object] | None = None)`
  - `bash_allowed(command: str) -> bool`
  - `allowed_roots(state: Path, plugin_root: Path, config_dir: Path) -> list[Path]`
  - `decide(payload: dict[str, object], cards: list[Card], roots: list[Path], *, read_limit: int = READ_LIMIT_DEFAULT) -> Verdict`
  - `hook_output(verdict: Verdict) -> dict[str, object] | None`
  - CLI `pretool-hook` (exit 0 always; prints the hook JSON or nothing)

- [ ] **Step 1: Write the failing tests**

```python
# tests/overseer/test_guard.py
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from factories import make_card
from scripts.cli import main
from scripts.guard import Verdict, allowed_roots, bash_allowed, decide, hook_output

PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "overseer"
BASH = shutil.which("bash") or "/bin/bash"
ROOTS = [Path("/state"), Path("/plugins"), Path("/cfg")]
CARD = make_card("WF-012")


def _p(tool, tool_input=None, **extra):
    return {"tool_name": tool, "tool_input": tool_input or {}, "cwd": "/repo", **extra}


class TestBashAllowed:
    @pytest.mark.parametrize("command", [
        "python plugins/overseer/scripts/cli.py --root . resume",
        "/Users/x/.venv/bin/python ~/.claude/plugins/cache/pip-skills/overseer/0.23.0/scripts/cli.py show WF-1",
        'python "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" set-stage WF-1 planning',
        "python plugins/overseer/scripts/cli.py --root . handoff | python plugins/vigil/scripts/cli.py --root . handover --no-snapshot --content-file -",
        'python plugins/overseer/scripts/cli.py log-progress WF-1 --note "a; b && c" --tokens 0',
        "git status && git log --oneline -3",
        "git -C /tmp/wt push -u origin feat/WF-1-x",
        "cd /repo && gh pr create --title t --body b",
        "OVERSEER_DB=/x python plugins/overseer/scripts/cli.py board",
        "echo 'unbalanced",  # unparseable: fails open
    ])
    def test_allowed(self, command):
        assert bash_allowed(command)

    @pytest.mark.parametrize("command", [
        "pytest -q",
        "cat src/app.py",
        "git status; rm -rf build",
        "cd /repo rm -rf build",
        "git rebase -i HEAD~3",
        "python -m pytest",
        "python scripts/other.py",
        "snowsql -q 'select 1'",
    ])
    def test_denied(self, command):
        assert not bash_allowed(command)


class TestDecideOrchestrator:
    @pytest.mark.parametrize("payload", [
        _p("Edit", {"file_path": "/repo/a.py"}),
        _p("Write", {"file_path": "/state/x.md"}),
        _p("NotebookEdit"),
        _p("mcp__snowflake__query"),
        _p("Read", {"file_path": "/repo/src/app.py"}),
        _p("Read", {"file_path": "src/app.py"}),
        _p("Grep", {"pattern": "x"}),
        _p("Bash", {"command": "pytest"}),
    ])
    def test_work_is_denied(self, payload):
        reason = decide(payload, [CARD], ROOTS).deny_reason
        assert reason and "WF-012 in flight" in reason and "release" in reason

    @pytest.mark.parametrize("payload", [
        _p("Read", {"file_path": "/state/dispatch/WF-012/impl-review/r1-A.md"}),
        _p("Read", {"file_path": "/plugins/overseer/skills/orchestrate/SKILL.md"}),
        _p("Glob", {"pattern": "*.md", "path": "/cfg/skills"}),
        _p("Bash", {"command": "git status"}),
        _p("Agent", {"subagent_type": "overseer:overseer-reviewer", "prompt": "/state/b.md"}),
        _p("TaskCreate", {"subject": "x"}),
        _p("AskUserQuestion"),
    ])
    def test_dispatch_and_ledger_are_allowed(self, payload):
        assert decide(payload, [CARD], ROOTS) == Verdict()

    def test_no_card_means_no_guard(self):
        assert decide(_p("Edit", {"file_path": "/repo/a.py"}), [], ROOTS) == Verdict()

    def test_fork_denied_for_orchestrator_and_agents(self):
        fork = {"subagent_type": "fork", "prompt": "x"}
        assert "forks inherit" in decide(_p("Agent", fork), [CARD], ROOTS).deny_reason
        agent = _p("Agent", fork, agent_id="a1", agent_type="overseer:overseer-implementer")
        assert "forks inherit" in decide(agent, [CARD], ROOTS).deny_reason

    def test_tripwire_denies_dispatch(self):
        hot = make_card("WF-012", budget_estimate=100, budget_actual=250)
        reason = decide(_p("Agent", {"subagent_type": "overseer:overseer-fixer"}), [hot], ROOTS).deny_reason
        assert reason.startswith("TRIPWIRE: WF-012")


class TestDecideAgents:
    def test_agents_may_work(self):
        payload = _p("Edit", {"file_path": "/repo/a.py"}, agent_id="a1",
                     agent_type="overseer:overseer-implementer")
        assert decide(payload, [CARD], ROOTS).deny_reason is None

    def test_foreman_is_held_to_hub_rules(self):
        payload = _p("Edit", {"file_path": "/repo/a.py"}, agent_id="a1",
                     agent_type="overseer:overseer-foreman")
        assert decide(payload, [CARD], ROOTS).deny_reason

    def test_read_limit_applies_to_overseer_agents_only(self):
        read = {"file_path": "/repo/big.py"}
        agent = _p("Read", read, agent_id="a1", agent_type="overseer:overseer-reviewer")
        assert decide(agent, [], ROOTS).updated_input == {"file_path": "/repo/big.py", "limit": 400}
        assert decide(agent, [], ROOTS, read_limit=0).updated_input is None
        other = _p("Read", read, agent_id="a1", agent_type="general-purpose")
        assert decide(other, [], ROOTS).updated_input is None
        explicit = _p("Read", {**read, "offset": 10}, agent_id="a1",
                      agent_type="overseer:overseer-reviewer")
        assert decide(explicit, [], ROOTS).updated_input is None
        image = _p("Read", {"file_path": "/repo/shot.PNG"}, agent_id="a1",
                   agent_type="overseer:overseer-reviewer")
        assert decide(image, [], ROOTS).updated_input is None


def test_hook_output_shapes():
    assert hook_output(Verdict()) is None
    assert hook_output(Verdict(deny_reason="no")) == {"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": "no"}}
    assert hook_output(Verdict(updated_input={"limit": 1})) == {"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "updatedInput": {"limit": 1}}}


def test_allowed_roots_resolve(tmp_path):
    roots = allowed_roots(tmp_path / "s", tmp_path / "plugins" / "overseer", tmp_path / "cfg")
    assert roots == [(tmp_path / "s").resolve(), (tmp_path / "plugins").resolve(),
                     (tmp_path / "cfg").resolve()]


class TestCli:
    @pytest.fixture
    def repo(self, tmp_path, monkeypatch):
        assert main(["--root", str(tmp_path), "init"]) == 0
        assert main(["--root", str(tmp_path), "new-card", "--title", "T"]) == 0
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-1")
        assert main(["--root", str(tmp_path), "set-stage", "WF-001", "implementation"]) == 0
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
        return tmp_path

    def _hook(self, repo, monkeypatch, capsys, **payload):
        body = {"cwd": str(repo), "session_id": "sess-1", "tool_name": "Edit",
                "tool_input": {"file_path": str(repo / "a.py")}, **payload}
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(body)))
        capsys.readouterr()
        assert main(["--root", str(repo), "pretool-hook"]) == 0
        out = capsys.readouterr().out.strip()
        return json.loads(out) if out else None

    def test_orchestrator_edit_denied(self, repo, monkeypatch, capsys):
        out = self._hook(repo, monkeypatch, capsys)
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_other_session_agent_and_escapes_allowed(self, repo, monkeypatch, capsys):
        assert self._hook(repo, monkeypatch, capsys, session_id="sess-2") is None
        assert self._hook(repo, monkeypatch, capsys, agent_id="a1",
                          agent_type="overseer:overseer-implementer") is None
        monkeypatch.setenv("OVERSEER_GUARD", "off")
        assert self._hook(repo, monkeypatch, capsys) is None
        monkeypatch.delenv("OVERSEER_GUARD")
        cfg = repo / ".overseer"
        cfg.mkdir(exist_ok=True)
        (cfg / "config.local.json").write_text('{"guard": false}')
        assert self._hook(repo, monkeypatch, capsys) is None
        (cfg / "config.local.json").write_text("{}")
        assert main(["--root", str(repo), "release", "WF-001"]) == 0
        assert self._hook(repo, monkeypatch, capsys) is None

    def test_config_read_limit(self, repo, monkeypatch, capsys):
        cfg = repo / ".overseer"
        cfg.mkdir(exist_ok=True)
        (cfg / "config.local.json").write_text('{"read_limit": 50}')
        out = self._hook(repo, monkeypatch, capsys, tool_name="Read", agent_id="a1",
                         agent_type="overseer:overseer-reviewer",
                         tool_input={"file_path": str(repo / "x.py")})
        assert out["hookSpecificOutput"]["updatedInput"]["limit"] == 50

    def test_garbage_stdin_is_silent(self, repo, monkeypatch, capsys):
        monkeypatch.setattr(sys, "stdin", io.StringIO("nope"))
        assert main(["--root", str(repo), "pretool-hook"]) == 0
        assert capsys.readouterr().out == ""


def test_shell_wrapper_exits_zero(tmp_path):
    result = subprocess.run(
        [BASH, str(PLUGIN_ROOT / "hooks" / "pretool.sh")], input="{}",
        capture_output=True, text=True,
        env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
             "OVERSEER_PYTHON": sys.executable, "OVERSEER_CENTRAL": str(tmp_path / "s"),
             "OVERSEER_DB": str(tmp_path / "b.db"), "CLAUDE_CONFIG_DIR": str(tmp_path / "c")},
    )
    assert (result.returncode, result.stdout) == (0, "")


def test_hooks_json_registers_pretool_for_all_tools():
    hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    entries = [e for e in hooks["PreToolUse"]
               if any(h["command"].endswith("/hooks/pretool.sh") for h in e["hooks"])]
    assert [e["matcher"] for e in entries] == [".*"]
```

(`.overseer/config.local.json` resolves at the repo root: `repo_config_dir` uses `derive_repo_root(repo) or repo`, and a tmp dir without git falls back to `repo` itself.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PY -m pytest ../../tests/overseer/test_guard.py -q -p no:cacheprovider`
Expected: `ModuleNotFoundError: No module named 'scripts.guard'`

- [ ] **Step 3: Implement `guard.py`**

```python
# plugins/overseer/scripts/guard.py
"""PreToolUse guard and Read limit (WF-113 §5.1, §5.7).

The orchestrator is the most expensive party in an overseer run: every one of
its turns re-reads ~240k of context. This guard stops it doing work itself
(editing, reading source, running queries or tests) and stops anyone forking
(a fork inherits the whole parent context). Agents dispatched by the
orchestrator share its ``session_id`` but carry ``agent_id``, which is how
they are told apart (verified on Claude Code 2.1.273).

This is a cost guard, not a security boundary: command parsing is
best-effort and every doubt fails open.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from scripts.dispatch import is_hub_agent, role_of
from scripts.models import Card, format_tokens

READ_LIMIT_DEFAULT = 400
_UNLIMITED_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".ipynb")
_WRITE_TOOLS = {"Edit", "Write", "NotebookEdit"}
_PATH_TOOLS = {"Read", "Grep", "Glob"}
_OPERATORS = {"&&", "||", ";", "|", "&", ";;", "|&"}
_ASSIGNMENT = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*=")
_LEDGER_CLI = re.compile(
    r"(?:(?:\A|/)(?:overseer|vigil)/(?:[^/\s]+/)?|\$\{?CLAUDE_PLUGIN_ROOT\}?/)scripts/cli\.py\Z"
)
_GIT_SUBCOMMANDS = {
    "add", "branch", "commit", "diff", "fetch", "log", "merge-base", "pull", "push",
    "remote", "rev-parse", "show", "stash", "status", "symbolic-ref", "worktree",
}
_ESCAPES = '`release <card>`, `"guard": false` in .overseer/config.json, or OVERSEER_GUARD=off'


@dataclass(frozen=True)
class Verdict:
    deny_reason: str | None = None
    updated_input: dict[str, object] | None = None


def _segments(command: str) -> list[list[str]] | None:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in _OPERATORS:
            segments.append([])
        else:
            segments[-1].append(token)
    return [s for s in segments if s]


def bash_allowed(command: str) -> bool:
    """Every segment of the command must be ledger/vigil CLI, git plumbing
    the orchestrator needs for branches/PRs, ``gh pr``, or a bare ``cd``."""
    segments = _segments(command)
    if segments is None:
        return True
    for words in segments:
        while words and _ASSIGNMENT.match(words[0]):
            words = words[1:]
        if not words:
            continue
        head = Path(words[0]).name
        if head in {"cd", "pwd"} and len(words) <= 2:
            continue
        if head == "git":
            rest = words[1:]
            while rest and rest[0].startswith("-"):
                rest = rest[2:] if rest[0] in {"-C", "-c"} else rest[1:]
            if rest and rest[0] in _GIT_SUBCOMMANDS:
                continue
            return False
        if head == "gh" and words[1:2] == ["pr"]:
            continue
        if head.startswith("python") and len(words) > 1 and _LEDGER_CLI.search(words[1]):
            continue
        return False
    return True


def allowed_roots(state: Path, plugin_root: Path, config_dir: Path) -> list[Path]:
    """Where the orchestrator may still read: its ledger state (dispatch
    files included), the installed plugins (skills, references, templates),
    and the Claude config dir (memory, other skills)."""
    return [state.resolve(), plugin_root.parent.resolve(), config_dir.resolve()]


def _within(path: Path, roots: list[Path]) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return any(resolved.is_relative_to(root) for root in roots)


def _hub_denial(
    card: Card, tool: str, tool_input: dict[str, object], cwd: object, roots: list[Path]
) -> str | None:
    work = (
        f"{card.id} in flight: the orchestrator dispatches, it does not do the work — "
        f"dispatch an overseer-* agent with a dispatch-prep bundle instead. "
        f"(Escape hatch: {_ESCAPES}.)"
    )
    if tool == "Agent" and card.tripwire_breached:
        return (
            f"TRIPWIRE: {card.id} has spent {format_tokens(card.budget_actual)} against an "
            f"estimate of {format_tokens(card.budget_estimate)} — stop the card and "
            "escalate to the user."
        )
    if tool in _WRITE_TOOLS or tool.startswith("mcp__"):
        return work
    if tool in _PATH_TOOLS:
        raw = tool_input.get("file_path") or tool_input.get("path")
        if not isinstance(raw, str) or not raw:
            return work
        path = Path(raw).expanduser()
        if not path.is_absolute() and isinstance(cwd, str):
            path = Path(cwd) / path
        return None if _within(path, roots) else work
    if tool == "Bash":
        command = tool_input.get("command")
        return None if isinstance(command, str) and bash_allowed(command) else work
    return None


def _limited_read(
    tool: str, tool_input: dict[str, object], payload: dict[str, object], limit: int
) -> dict[str, object] | None:
    if tool != "Read" or limit <= 0 or not payload.get("agent_id"):
        return None
    if role_of(payload.get("agent_type")) is None:
        return None
    if "limit" in tool_input or "offset" in tool_input:
        return None
    path = tool_input.get("file_path")
    if not isinstance(path, str) or path.lower().endswith(_UNLIMITED_SUFFIXES):
        return None
    return {**tool_input, "limit": limit}


def decide(
    payload: dict[str, object],
    cards: list[Card],
    roots: list[Path],
    *,
    read_limit: int = READ_LIMIT_DEFAULT,
) -> Verdict:
    """``cards`` = live cards whose orchestrator is this payload's session
    (empty when the guard is off). Deny beats the Read limit."""
    tool_raw = payload.get("tool_name")
    tool = tool_raw if isinstance(tool_raw, str) else ""
    input_raw = payload.get("tool_input")
    tool_input: dict[str, object] = input_raw if isinstance(input_raw, dict) else {}
    if cards:
        card = cards[0]
        if tool == "Agent" and tool_input.get("subagent_type") == "fork":
            return Verdict(
                f"{card.id} in flight: forks inherit the full parent context — dispatch a "
                "fresh overseer-* agent with a bundle path instead."
            )
        is_hub = not payload.get("agent_id") or is_hub_agent(payload.get("agent_type"))
        if is_hub:
            reason = _hub_denial(card, tool, tool_input, payload.get("cwd"), roots)
            if reason:
                return Verdict(reason)
    return Verdict(updated_input=_limited_read(tool, tool_input, payload, read_limit))


def hook_output(verdict: Verdict) -> dict[str, object] | None:
    """No ``permissionDecision`` with ``updatedInput``: verified on 2.1.273
    that the rewrite applies without one, so user permission rules still run."""
    if verdict.deny_reason:
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": verdict.deny_reason,
        }}
    if verdict.updated_input is not None:
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": verdict.updated_input,
        }}
    return None
```

- [ ] **Step 4: Wire the CLI**

Extend the import: `from scripts import config, db, guard, liveness, report_hook`. Add:

```python
GUARD_ENV = "OVERSEER_GUARD"


def cmd_pretool_hook(args: argparse.Namespace) -> int:
    """PreToolUse backend — scripts/guard.py. Fails open: any error means no
    output, which Claude Code treats as "no opinion"."""
    try:
        payload = _read_hook_payload()
        repo_root = _hook_root(payload, args)
        state = state_root(repo_root)
        if not state.is_dir():
            return 0
        cfg = config.load_config(repo_root)
        cards: list[Card] = []
        session_id = payload.get("session_id")
        guard_on = (
            os.environ.get(GUARD_ENV, "").lower() != "off" and cfg.get("guard", True) is not False
        )
        if guard_on and isinstance(session_id, str) and session_id:
            cards = db.orchestrated_cards(_conn(repo_root), session_id)
        roots = guard.allowed_roots(
            state, Path(__file__).resolve().parent.parent, config._config_dir()
        )
        limit = cfg.get("read_limit", guard.READ_LIMIT_DEFAULT)
        verdict = guard.decide(
            payload, cards, roots,
            read_limit=limit if isinstance(limit, int) else guard.READ_LIMIT_DEFAULT,
        )
        output = guard.hook_output(verdict)
        if output:
            print(json.dumps(output))
    except Exception:
        return 0
    return 0
```

Parser: `sub.add_parser("pretool-hook").set_defaults(func=cmd_pretool_hook)`.

- [ ] **Step 5: Shell wrapper and registration**

`plugins/overseer/hooks/pretool.sh` (`chmod 755`):

```bash
#!/usr/bin/env bash
# Overseer PreToolUse hook — the orchestrator guard (no work, no forks) and
# the Read limit for overseer agents (WF-113 spec §5.1, §5.7). Prints the
# CLI's JSON decision; on any failure prints nothing and exits 0 (fail open).
trap 'exit 0' EXIT

input="$(cat)"

py="${OVERSEER_PYTHON:-python3}"
if [ -z "${OVERSEER_PYTHON:-}" ] && [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python" ]; then
  py="${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python"
fi

printf '%s' "$input" \
  | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" pretool-hook 2>/dev/null || true

exit 0
```

In `hooks/hooks.json`, append to the existing `"PreToolUse"` array (keep the `Bash` prepush entry):

```json
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/pretool.sh"
          }
        ]
      }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `$PY -m pytest ../../tests/overseer/test_guard.py ../../tests/overseer/test_hooks.py -q -p no:cacheprovider` → PASS; ruff + mypy clean.

- [ ] **Step 7: Commit**

```bash
git add plugins/overseer/scripts/guard.py plugins/overseer/hooks/pretool.sh plugins/overseer/hooks/hooks.json plugins/overseer/scripts/cli.py tests/overseer/test_guard.py
git commit -m "feat(overseer): PreToolUse guard — orchestrator dispatches not works, no forks, agent Read limit (WF-113)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: `dispatch-prep` and bundle templates

**Files:**
- Create: `plugins/overseer/scripts/gitops.py`
- Create: `plugins/overseer/scripts/bundle.py`
- Create: `plugins/overseer/templates/verifier.md`
- Modify (full rewrite): `plugins/overseer/templates/{planner,implementer,reviewer,fixer}.md` (leave `sprint-reviewer.md` alone)
- Modify: `plugins/overseer/scripts/cli.py` (`dispatch-prep` verb)
- Test: `tests/overseer/test_bundle.py`

**Interfaces:**
- Consumes: Task 1 (`dispatch_dir`, `ROLES`), Task 6 (`_stamp_orchestrator`), `calibration.calibrate/BANDS`, `knowledge.load_facts/knowledge_root`, `Card.sections`, `models.STAGES`
- Produces:
  - `gitops.GitError(RuntimeError)`, `gitops.base_ref(repo: Path) -> str`, `gitops.diff_against_base(worktree: Path) -> str`
  - `bundle.VAR_CAP = 300`, `bundle.TERSE_CHARTER: str`, `bundle.BundleError(ValueError)`
  - `bundle.parse_vars(pairs: list[str]) -> dict[str, str]`
  - `bundle.reply_name(role: str, *, round_no: int, slot: str | None, chunk: int | None) -> str`
  - `bundle.prepare(repo_root: Path, card: Card, *, stage: str, role: str, round_no: int, slot: str | None, chunk: int | None, lens: str | None, variables: dict[str, str], verbosity: str, archived: list[Card], today: str) -> Path`
  - CLI `dispatch-prep <card> --stage S --role R [--round N] [--slot A] [--chunk N] [--lens L] [--var k=v]...` → prints the bundle's absolute path

- [ ] **Step 1: Write the failing tests**

```python
# tests/overseer/test_bundle.py
import re
import subprocess

import pytest

from factories import git_init, make_card
from scripts import bundle, db
from scripts.cli import main
from scripts.dispatch import dispatch_dir
from scripts.knowledge import Fact, ensure_kb, knowledge_root, save_fact

TEMPLATES = bundle.TEMPLATES_DIR


def _git(path, *argv):
    subprocess.run(["git", *argv], cwd=path, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    git_init(tmp_path)
    (tmp_path / "a.txt").write_text("one\n")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "checkout", "-qb", "feat/x")
    (tmp_path / "a.txt").write_text("one\ntwo\n")
    _git(tmp_path, "commit", "-qam", "change")
    assert main(["--root", str(tmp_path), "init"]) == 0
    assert main(["--root", str(tmp_path), "new-card", "--title", "T", "--goal", "Ship it",
                 "--labels", "dbt"]) == 0
    conn = db.connect(tmp_path, migrate=False)
    card = db.load_card(conn, "WF-001")
    card.worktree = str(tmp_path)
    card.set_section("## Plan", "1. chunk one", "t")
    db.save_card(conn, card)
    kb = knowledge_root(tmp_path)
    ensure_kb(kb)
    save_fact(kb, Fact(id="KB-001", statement="dbt needs --target ci", tags=["dbt"],
                       created="2026-09-01", verified="2026-09-01"))
    save_fact(kb, Fact(id="KB-002", statement="unrelated", tags=["web"],
                       created="2026-09-01", verified="2026-09-01"))
    return tmp_path


def _prep(repo, capsys, *argv):
    capsys.readouterr()
    code = main(["--root", str(repo), "dispatch-prep", "WF-001", *argv])
    out = capsys.readouterr()
    return code, out.out.strip(), out.err


def test_every_template_placeholder_is_supplied():
    known = set(bundle.KNOWN_PLACEHOLDERS)
    for role in ("planner", "implementer", "reviewer", "fixer", "verifier"):
        found = set(re.findall(r"\{\{(\w+)\}\}", (TEMPLATES / f"{role}.md").read_text()))
        assert found <= known, (role, found - known)


def test_reviewer_impl_review_bundle(repo, capsys, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-1")
    code, out, _ = _prep(repo, capsys, "--stage", "impl-review", "--role", "reviewer",
                         "--slot", "A", "--lens", "correctness")
    assert code == 0
    d = dispatch_dir(repo, "WF-001", "impl-review")
    assert out == str(d / "bundle-reviewer-A-r1.md")
    text = (d / "bundle-reviewer-A-r1.md").read_text()
    assert str(d / "r1-A.md") in text and str(d / "diff.patch") in text
    assert "correctness" in text and "Ship it" in text and bundle.TERSE_CHARTER in text
    assert "dbt needs --target ci" in text and "unrelated" not in text
    assert "+two" in (d / "diff.patch").read_text()
    assert "{{" not in text
    assert [c.id for c in db.orchestrated_cards(db.connect(repo, migrate=False), "sess-1")] == ["WF-001"]


def test_round_two_lists_prior_verdicts_and_fix_reports(repo, capsys):
    d = dispatch_dir(repo, "WF-001", "impl-review")
    d.mkdir(parents=True)
    for name in ("r1-A.md", "r1-B.md", "r1-fix.md"):
        (d / name).write_text("x")
    _, out, _ = _prep(repo, capsys, "--stage", "impl-review", "--role", "reviewer",
                      "--slot", "A", "--round", "2")
    text = (d / "bundle-reviewer-A-r2.md").read_text()
    assert all(str(d / n) in text for n in ("r1-A.md", "r1-B.md", "r1-fix.md"))


def test_fixer_gets_this_rounds_verdicts_only(repo, capsys):
    d = dispatch_dir(repo, "WF-001", "impl-review")
    d.mkdir(parents=True)
    for name in ("r1-A.md", "r2-A.md", "r2-B.md"):
        (d / name).write_text("x")
    _prep(repo, capsys, "--stage", "impl-review", "--role", "fixer", "--round", "2",
          "--var", "gate_commands=pytest -q")
    text = (d / "bundle-fixer-r2.md").read_text()
    assert str(d / "r2-A.md") in text and str(d / "r2-B.md") in text
    assert str(d / "r1-A.md") not in text and "pytest -q" in text
    assert str(d / "r2-fix.md") in text


def test_plan_review_snapshots_the_plan(repo, capsys):
    _prep(repo, capsys, "--stage", "plan-review", "--role", "reviewer", "--slot", "A")
    d = dispatch_dir(repo, "WF-001", "plan-review")
    assert (d / "plan.snapshot.md").read_text() == "1. chunk one"


def test_verbosity_normal_drops_charter(repo, capsys):
    (repo / ".overseer").mkdir(exist_ok=True)
    (repo / ".overseer" / "config.local.json").write_text('{"verbosity": "normal"}')
    _, out, _ = _prep(repo, capsys, "--stage", "implementation", "--role", "implementer",
                      "--chunk", "1")
    assert bundle.TERSE_CHARTER not in open(out).read()


@pytest.mark.parametrize("argv, message", [
    (("--stage", "impl-review", "--role", "reviewer"), "--slot is required"),
    (("--stage", "impl-review", "--role", "reviewer", "--slot", "fix"), "reserved"),
    (("--stage", "implementation", "--role", "implementer"), "--chunk is required"),
    (("--stage", "implementation", "--role", "implementer", "--chunk", "1",
      "--var", "constraints=" + "x" * 301), "cap 300"),
    (("--stage", "implementation", "--role", "implementer", "--chunk", "1",
      "--var", "novalue"), "key=value"),
])
def test_errors(repo, capsys, argv, message):
    code, _, err = _prep(repo, capsys, *argv)
    assert code == 1 and message in err


def test_reply_names():
    assert bundle.reply_name("planner", round_no=1, slot=None, chunk=None) == "plan.md"
    assert bundle.reply_name("verifier", round_no=1, slot=None, chunk=None) == "verification.md"
    assert bundle.reply_name("implementer", round_no=1, slot=None, chunk=3) == "c3.md"
    assert bundle.reply_name("fixer", round_no=2, slot=None, chunk=None) == "r2-fix.md"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PY -m pytest ../../tests/overseer/test_bundle.py -q -p no:cacheprovider`
Expected: `ImportError: cannot import name 'bundle' from 'scripts'`

- [ ] **Step 3: Implement `gitops.py`**

```python
# plugins/overseer/scripts/gitops.py
"""Git plumbing for dispatch-prep and bootstrap: detect the repo's real base
branch (never assume ``main``), diff a worktree against it, add a worktree."""
from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    """A git command overseer depends on failed."""


def _git(cwd: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *argv], cwd=cwd, capture_output=True, text=True)


def base_ref(repo: Path) -> str:
    """``origin/HEAD``'s target (e.g. ``origin/main``), else a local
    ``main``/``master``, else ``HEAD``."""
    head = _git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if head.returncode == 0 and head.stdout.strip():
        return head.stdout.strip()
    for candidate in ("main", "master"):
        if _git(repo, "rev-parse", "--verify", "--quiet", candidate).returncode == 0:
            return candidate
    return "HEAD"


def diff_against_base(worktree: Path) -> str:
    base = base_ref(worktree)
    argv = ["diff", "HEAD"] if base == "HEAD" else ["diff", f"{base}...HEAD"]
    result = _git(worktree, *argv)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "git diff failed")
    return result.stdout
```

- [ ] **Step 4: Implement `bundle.py`**

```python
# plugins/overseer/scripts/bundle.py
"""dispatch-prep: compose one agent's bundle file (WF-113 §5.3).

The orchestrator used to spend ~5 full-context turns per dispatch fetching
calibration and facts, writing a diff, gathering prior findings and filling
a template — often pasting the result into the prompt. This does all of it
in one CLI call and prints a path; the agent's whole prompt is that path.

``--var`` values are capped (VAR_CAP): anything longer belongs in a file,
which makes pasting a plan, diff or findings list through here impossible.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from scripts import gitops
from scripts.calibration import BANDS, calibrate
from scripts.dispatch import dispatch_dir
from scripts.knowledge import knowledge_root, load_facts
from scripts.models import Card

VAR_CAP = 300
TERSE_CHARTER = (
    "**Voice:** terse and factual. State results, not process. No preamble, no recap, "
    "no narration of what you are about to do. Expand only when asked."
)
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
CLI_PATH = Path(__file__).resolve().parent / "cli.py"
KNOWN_PLACEHOLDERS = (
    "card_id", "title", "stage", "round_no", "slot", "chunk_no", "goal", "complexity",
    "worktree", "reply_path", "cli", "knowledge", "calibration", "charter", "lens",
    "target_path", "prior_findings", "verdict_paths", "gate_commands", "constraints",
    "repo_context",
)
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
_VAR_KEY = re.compile(r"\A\w+\Z")
_ROUND_FILE = re.compile(r"\Ar(\d+)-[A-Za-z0-9]+\.md\Z")
MAX_FACTS = 15


class BundleError(ValueError):
    """dispatch-prep was asked for a bundle it cannot build."""


def parse_vars(pairs: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not _VAR_KEY.match(key):
            raise BundleError(f"--var {pair!r} must be key=value")
        if len(value) > VAR_CAP:
            raise BundleError(
                f"--var {key} is {len(value)} chars (cap {VAR_CAP}): write it to a file "
                "and pass the path instead"
            )
        values[key] = value
    return values


def reply_name(role: str, *, round_no: int, slot: str | None, chunk: int | None) -> str:
    if role == "reviewer":
        if not slot:
            raise BundleError("--slot is required for a reviewer")
        if slot == "fix":
            raise BundleError("slot 'fix' is reserved for the fixer's report")
        return f"r{round_no}-{slot}.md"
    if role == "fixer":
        return f"r{round_no}-fix.md"
    if role == "implementer":
        if chunk is None:
            raise BundleError("--chunk is required for an implementer")
        return f"c{chunk}.md"
    if role == "planner":
        return "plan.md"
    if role == "verifier":
        return "verification.md"
    raise BundleError(f"unknown role {role!r}")


def _bundle_name(role: str, *, round_no: int, slot: str | None, chunk: int | None) -> str:
    tag = slot if role == "reviewer" else (f"c{chunk}" if role == "implementer" else None)
    return f"bundle-{role}{'-' + tag if tag else ''}-r{round_no}.md"


def _bullets(paths: list[Path]) -> str:
    return "\n".join(f"  - {p}" for p in paths) if paths else "_(none)_"


def _files_for_rounds(directory: Path, rounds: set[int], *, include_fix: bool) -> list[Path]:
    found = []
    for path in sorted(directory.glob("r*-*.md")):
        match = _ROUND_FILE.match(path.name)
        if not match or int(match.group(1)) not in rounds:
            continue
        if path.name.endswith("-fix.md") and not include_fix:
            continue
        found.append(path)
    return found


def _knowledge(repo_root: Path, card: Card, today: str) -> str:
    if not card.labels:
        return "_(none)_"
    facts, _ = load_facts(knowledge_root(repo_root))
    lines = []
    for fact in facts:
        if not set(fact.tags) & set(card.labels):
            continue
        stale = " [STALE — verify first]" if fact.effective_status(today) == "stale" else ""
        lines.append(f"  - {fact.id}{stale}: {fact.statement}")
    return "\n".join(lines[:MAX_FACTS]) or "_(none)_"


def _calibration(archived: list[Card]) -> str:
    report = calibrate(archived)
    parts = []
    for band in BANDS:
        data = report["bands"][band]
        if data["count"]:
            parts.append(f"{band} n={data['count']} median ×{data['median']}")
    return "; ".join(parts) or "_(no samples)_"


def prepare(
    repo_root: Path,
    card: Card,
    *,
    stage: str,
    role: str,
    round_no: int,
    slot: str | None,
    chunk: int | None,
    lens: str | None,
    variables: dict[str, str],
    verbosity: str,
    archived: list[Card],
    today: str,
) -> Path:
    reply = reply_name(role, round_no=round_no, slot=slot, chunk=chunk)
    directory = dispatch_dir(repo_root, card.id, stage)
    directory.mkdir(parents=True, exist_ok=True)
    worktree = Path(card.worktree) if card.worktree else repo_root
    sections = card.sections
    values: dict[str, str] = {
        "card_id": card.id,
        "title": card.title,
        "stage": stage,
        "round_no": str(round_no),
        "slot": slot or "",
        "chunk_no": "" if chunk is None else str(chunk),
        "goal": sections.get("## Goal") or "_(none)_",
        "complexity": card.complexity or "_(ungraded)_",
        "worktree": str(worktree),
        "reply_path": str(directory / reply),
        "cli": f"{sys.executable} {CLI_PATH} --root {repo_root}",
        "knowledge": _knowledge(repo_root, card, today),
        "calibration": _calibration(archived),
        "charter": "" if verbosity == "normal" else TERSE_CHARTER,
        "lens": lens or "general",
        "prior_findings": _bullets(
            _files_for_rounds(directory, set(range(1, round_no)), include_fix=True)
        ),
        "verdict_paths": _bullets(_files_for_rounds(directory, {round_no}, include_fix=False)),
    }
    if role == "reviewer":
        if stage == "plan-review":
            target = directory / "plan.snapshot.md"
            target.write_text(sections.get("## Plan", ""))
        else:
            target = directory / "diff.patch"
            try:
                target.write_text(gitops.diff_against_base(worktree))
            except gitops.GitError as exc:
                raise BundleError(f"could not write the diff: {exc}") from exc
        values["target_path"] = str(target)
    values.update(variables)
    template = (TEMPLATES_DIR / f"{role}.md").read_text()
    text = _PLACEHOLDER.sub(lambda m: values.get(m.group(1), "_(none)_"), template)
    path = directory / _bundle_name(role, round_no=round_no, slot=slot, chunk=chunk)
    path.write_text(text)
    return path
```

- [ ] **Step 5: Rewrite the templates**

`templates/reviewer.md`:

```markdown
# Review bundle — {{card_id}} {{stage}} round {{round_no}}, reviewer {{slot}}

{{charter}}

## Inputs
- Card: {{card_id}} — {{title}}
- Goal: {{goal}}
- Review target: {{target_path}}
- Your lens (priority, not a blinker): {{lens}}
- Binding constraints: {{constraints}}
- Prior rounds' verdicts and fix reports — read them; answer every DISPUTED finding (withdraw, or maintain with new evidence); never re-raise an adjudicated finding verbatim:
{{prior_findings}}
- Knowledge (verify anything marked stale before trusting):
{{knowledge}}
- Worktree (do not modify): {{worktree}}
- Ledger CLI (read-only verbs, e.g. `show {{card_id}} --json`): {{cli}}

## Output
Write your verdict to `{{reply_path}}` in the format your agent definition gives, then reply with the single line it specifies, pointing at that path.
```

`templates/implementer.md`:

```markdown
# Implementation bundle — {{card_id}} chunk {{chunk_no}}

{{charter}}

## Inputs
- Card: {{card_id}} — {{title}}
- Goal: {{goal}}
- Your chunk: chunk {{chunk_no}} of the card's plan. Read it with `{{cli}} show {{card_id}} --json` (field `sections["## Plan"]`). Do that chunk only.
- Worktree (work ONLY here): {{worktree}}
- Gate commands: {{gate_commands}}
- Binding constraints: {{constraints}}
- Knowledge (verify anything marked stale before trusting):
{{knowledge}}

## Output
Write your report to `{{reply_path}}` in the format your agent definition gives, then reply with the single line it specifies.
```

`templates/fixer.md`:

```markdown
# Fix bundle — {{card_id}} {{stage}} round {{round_no}}

{{charter}}

## Inputs
- Card: {{card_id}} — {{title}}
- This round's verdict files — fix ALL Critical and Important findings across all of them:
{{verdict_paths}}
- Worktree: {{worktree}}
- Gate commands: {{gate_commands}}
- Binding constraints: {{constraints}}
- Knowledge (verify anything marked stale before trusting):
{{knowledge}}

## Output
Write your fix report to `{{reply_path}}` in the format your agent definition gives, then reply with the single line it specifies.
```

`templates/planner.md`:

```markdown
# Planning bundle — {{card_id}}: {{title}}

{{charter}}

## Inputs
- Goal: {{goal}}
- Complexity grading so far: {{complexity}} (you may recommend a re-grade)
- Calibration (recent actual ÷ estimate by band): {{calibration}}
- Repo context: {{repo_context}}
- Binding constraints: {{constraints}}
- Knowledge (verify anything marked stale before trusting):
{{knowledge}}
- Worktree (read to plan; do not modify): {{worktree}}

## Output
Write the plan to `{{reply_path}}` in the structure your agent definition gives, then reply with the single line it specifies. The ledger copies the file into the card's Plan section.
```

`templates/verifier.md` (new):

```markdown
# Verification bundle — {{card_id}}

{{charter}}

## Inputs
- Card: {{card_id}} — {{title}}
- Goal: {{goal}}
- Plan: `{{cli}} show {{card_id}} --json` (field `sections["## Plan"]`)
- Worktree: {{worktree}}
- Gate commands: {{gate_commands}}
- Binding constraints: {{constraints}}

## Output
Write your evidence to `{{reply_path}}` in the format your agent definition gives, then reply with the single line it specifies. The ledger copies the file into the card's Verification section.
```

- [ ] **Step 6: Wire the CLI**

Import `from scripts import bundle, config, db, guard, liveness, report_hook` and `from scripts.dispatch import REPLY_WORD_CAP, ROLES` and `from scripts.models import STAGES` (extend existing import). Add:

```python
def cmd_dispatch_prep(args: argparse.Namespace) -> int:
    card = _load(args.root, args.card_id)
    try:
        path = bundle.prepare(
            args.root,
            card,
            stage=args.stage,
            role=args.role,
            round_no=args.round,
            slot=args.slot,
            chunk=args.chunk,
            lens=args.lens,
            variables=bundle.parse_vars(args.var or []),
            verbosity=str(config.load_config(args.root).get("verbosity", "terse")),
            archived=db.load_archived_cards(_conn(args.root)),
            today=_today(),
        )
    except bundle.BundleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _stamp_orchestrator(args.root, card.id)
    print(path)
    return 0
```

Parser:

```python
    p = sub.add_parser("dispatch-prep")
    p.add_argument("card_id")
    p.add_argument("--stage", required=True, choices=STAGES)
    p.add_argument("--role", required=True, choices=ROLES)
    p.add_argument("--round", type=int, default=1)
    p.add_argument("--slot")
    p.add_argument("--chunk", type=int)
    p.add_argument("--lens")
    p.add_argument("--var", action="append", help=f"key=value, value ≤ {bundle.VAR_CAP} chars")
    p.set_defaults(func=cmd_dispatch_prep)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `$PY -m pytest ../../tests/overseer/test_bundle.py -q -p no:cacheprovider` → PASS. Then the full suite (templates changed): `$PY -m pytest -q -p no:cacheprovider` → PASS; ruff + mypy clean.

- [ ] **Step 8: Commit**

```bash
git add plugins/overseer/scripts/gitops.py plugins/overseer/scripts/bundle.py plugins/overseer/templates plugins/overseer/scripts/cli.py tests/overseer/test_bundle.py
git commit -m "feat(overseer): dispatch-prep composes an agent's bundle in one call; path-only templates (WF-113)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: `bootstrap` verb

**Files:**
- Modify: `plugins/overseer/scripts/gitops.py` (add `worktree_add`)
- Modify: `plugins/overseer/scripts/cli.py` (extract `_create_card`; add `bootstrap`)
- Test: `tests/overseer/test_bootstrap.py`

**Interfaces:**
- Consumes: Task 6 (`_stamp_orchestrator`), Task 8 (`gitops.base_ref`, `GitError`), `store.slugify`, `store.derive_repo_root`, `config.load_config`
- Produces:
  - `gitops.worktree_add(repo: Path, path: Path, branch: str, start: str) -> None`
  - `cli._create_card(args: argparse.Namespace) -> Card` (raises `sqlite3.IntegrityError` on id collision; `cmd_new_card` uses it)
  - `cli.worktree_path(main_root: Path, card_id: str, cfg: dict) -> Path`
  - CLI `bootstrap --title T [--complexity] [--labels] [--goal] [--jira|--linear] [--type feat] [--slug S]` or `bootstrap --card WF-N [--type] [--slug]` → one line `WF-N planning · <branch> · <path> (base <ref>)`

- [ ] **Step 1: Write the failing tests**

```python
# tests/overseer/test_bootstrap.py
import json
import subprocess

import pytest

from factories import git_init
from scripts import db
from scripts.cli import main, worktree_path


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    git_init(root)
    (root / "a.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=root, check=True)
    (root / ".overseer").mkdir()
    (root / ".overseer" / "config.local.json").write_text(
        json.dumps({"worktree_dir": str(tmp_path / "wt")}))
    assert main(["--root", str(root), "init"]) == 0
    return root


def test_worktree_path_default_and_config(tmp_path):
    assert worktree_path(tmp_path / "proj", "WF-12", {}) == tmp_path / "proj-wf-12"
    assert worktree_path(tmp_path / "proj", "WF-12", {"worktree_dir": "/w"}).as_posix() == "/w/proj-wf-12"


def test_new_card_bootstrap(repo, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-1")
    capsys.readouterr()
    assert main(["--root", str(repo), "bootstrap", "--title", "Add the Thing!",
                 "--complexity", "S"]) == 0
    path = tmp_path / "wt" / "proj-wf-001"
    assert capsys.readouterr().out.strip() == (
        f"WF-001 planning · feat/WF-001-add-the-thing · {path} (base main)")
    conn = db.connect(repo, migrate=False)
    card = db.load_card(conn, "WF-001")
    assert (card.stage, card.status, card.branch, card.worktree, card.complexity) == (
        "planning", "in-flight", "feat/WF-001-add-the-thing", str(path), "S")
    head = subprocess.run(["git", "branch", "--show-current"], cwd=path,
                          capture_output=True, text=True).stdout.strip()
    assert head == "feat/WF-001-add-the-thing"
    assert [c.id for c in db.orchestrated_cards(conn, "sess-1")] == ["WF-001"]


def test_existing_card_and_custom_type_slug(repo, tmp_path, capsys):
    main(["--root", str(repo), "new-card", "--title", "T"])
    assert main(["--root", str(repo), "bootstrap", "--card", "WF-001",
                 "--type", "fix", "--slug", "short"]) == 0
    assert db.load_card(db.connect(repo, migrate=False), "WF-001").branch == "fix/WF-001-short"


def test_worktree_failure_leaves_card_at_bootstrap(repo, capsys):
    subprocess.run(["git", "branch", "feat/WF-001-t"], cwd=repo, check=True)
    capsys.readouterr()
    assert main(["--root", str(repo), "bootstrap", "--title", "T"]) == 1
    assert "error:" in capsys.readouterr().err
    card = db.load_card(db.connect(repo, migrate=False), "WF-001")
    assert (card.stage, card.branch) == ("bootstrap", None)


def test_title_or_card_required(repo):
    assert main(["--root", str(repo), "bootstrap"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PY -m pytest ../../tests/overseer/test_bootstrap.py -q -p no:cacheprovider`
Expected: `ImportError: cannot import name 'worktree_path'`

- [ ] **Step 3: Implement**

`gitops.py` — append:

```python
def worktree_add(repo: Path, path: Path, branch: str, start: str) -> None:
    """Create ``branch`` at ``start`` checked out in a new worktree at
    ``path``. Fetches first (best effort) so ``origin/<base>`` is current."""
    _git(repo, "fetch", "--quiet", "origin")
    result = _git(repo, "worktree", "add", "-b", branch, str(path), start)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "git worktree add failed")
```

`cli.py` — refactor `cmd_new_card` so creation is shared:

```python
def _create_card(args: argparse.Namespace) -> Card:
    """Mint and insert a card from new-card-style args. Raises
    ``sqlite3.IntegrityError`` on an id collision (insert-only, see below)."""
    conn = _conn(args.root)
    card_id = args.jira or args.linear or db.mint_id(conn)
    card = Card(
        id=card_id,
        title=args.title.strip(),
        status="planned",
        jira=args.jira,
        linear=args.linear,
        complexity=args.complexity,
        sprint=getattr(args, "sprint", None),
        budget_estimate=parse_tokens(getattr(args, "estimate", None)),
        created=_today(),
        updated=_now(),
        repo=args.repo if getattr(args, "repo", None) else derive_repo_label(args.root),
        labels=[lb.strip() for lb in args.labels.split(",") if lb.strip()] if args.labels else [],
        body=CARD_BODY_TEMPLATE.format(goal=args.goal or "_(to be written)_"),
    )
    # Insert-only (not `_sync`'s upsert path): a plain existence check here
    # would leave a TOCTOU window where two concurrent `new-card` calls that
    # mint/target the same id both pass the check and one silently
    # overwrites the other. `create_card` raises on the PK collision instead.
    db.create_card(conn, card)
    _report_quarantined(rebuild_index(args.root, args.root.resolve().name, _now()))
    return card


def cmd_new_card(args: argparse.Namespace) -> int:
    try:
        card = _create_card(args)
    except sqlite3.IntegrityError:
        print(f"error: card {args.jira or args.linear or '(minted id)'} already exists",
              file=sys.stderr)
        return 1
    print(card.id)
    return 0
```

(An explicit `--jira`/`--linear` key is the realistic collision; if `test_cli.py` asserts the old message text for a minted id, keep that test green.)

Add the bootstrap verb:

```python
def worktree_path(main_root: Path, card_id: str, cfg: dict) -> Path:
    parent = Path(cfg["worktree_dir"]) if cfg.get("worktree_dir") else main_root.parent
    return parent / f"{main_root.name}-{card_id.lower()}"


def cmd_bootstrap(args: argparse.Namespace) -> int:
    """new-card + base-branch detection + worktree + branch + set-field +
    set-stage planning, in one orchestrator turn instead of seven."""
    if not args.card and not args.title:
        print("error: bootstrap needs --title (new card) or --card (existing)", file=sys.stderr)
        return 1
    try:
        card = _load(args.root, args.card) if args.card else _create_card(args)
    except sqlite3.IntegrityError:
        print("error: card already exists", file=sys.stderr)
        return 1
    main_root = derive_repo_root(args.root) or args.root
    branch = f"{args.type}/{card.id}-{args.slug or slugify(card.title)}"
    path = worktree_path(main_root, card.id, config.load_config(args.root))
    base = gitops.base_ref(main_root)
    card.set_stage("bootstrap", _now())
    card.ack_claim()
    try:
        gitops.worktree_add(main_root, path, branch, base)
    except gitops.GitError as exc:
        _sync(args.root, card)
        _stamp_orchestrator(args.root, card.id)
        print(f"error: {card.id} left at bootstrap — {exc}", file=sys.stderr)
        return 1
    card.branch = branch
    card.worktree = str(path)
    card.set_stage("planning", _now())
    _sync(args.root, card)
    _stamp_orchestrator(args.root, card.id)
    print(f"{card.id} planning · {branch} · {path} (base {base})")
    return 0
```

Imports: add `gitops` to `from scripts import ...`; `derive_repo_root, slugify` to the `scripts.store` import.

Parser:

```python
    p = sub.add_parser("bootstrap")
    p.add_argument("--card")
    p.add_argument("--title")
    ref = p.add_mutually_exclusive_group()
    ref.add_argument("--jira")
    ref.add_argument("--linear")
    p.add_argument("--complexity", choices=["S", "M", "L", "XL"])
    p.add_argument("--labels")
    p.add_argument("--goal")
    p.add_argument("--type", default="feat")
    p.add_argument("--slug")
    p.set_defaults(func=cmd_bootstrap)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PY -m pytest ../../tests/overseer/test_bootstrap.py ../../tests/overseer/test_cli.py -q -p no:cacheprovider` → PASS; ruff + mypy clean.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/scripts/gitops.py plugins/overseer/scripts/cli.py tests/overseer/test_bootstrap.py
git commit -m "feat(overseer): bootstrap verb — card, worktree, branch and planning stage in one call (WF-113)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Agent definitions

**Files:**
- Create: `plugins/overseer/agents/overseer-planner.md`, `overseer-implementer.md`, `overseer-reviewer.md`, `overseer-fixer.md`, `overseer-verifier.md`
- Test: `tests/overseer/test_agents.py`

**Interfaces:**
- Consumes: Task 1 grammar (each definition's reply example must parse), Task 8 bundle layout
- Produces: agent types `overseer:overseer-{planner,implementer,reviewer,fixer,verifier}`

- [ ] **Step 1: Write the failing test**

```python
# tests/overseer/test_agents.py
import re
from pathlib import Path

import pytest
import yaml

from scripts.dispatch import ROLES, parse_reply

AGENTS = Path(__file__).resolve().parents[2] / "plugins" / "overseer" / "agents"
WRITE_TOOLS = {"Edit", "NotebookEdit"}


def _load(role):
    text = (AGENTS / f"overseer-{role}.md").read_text()
    _, front, body = text.split("---", 2)
    return yaml.safe_load(front), body


@pytest.mark.parametrize("role", ROLES)
def test_definition_shape(role):
    meta, body = _load(role)
    assert meta["name"] == f"overseer-{role}"
    assert meta["model"] == "sonnet"
    tools = {t.strip() for t in meta["tools"].split(",")}
    assert {"Read", "Write"} <= tools
    assert "Agent" not in tools  # workers never dispatch (no forks, no nesting)
    if role in ("reviewer", "planner", "verifier"):
        assert not tools & WRITE_TOOLS
    assert "ONE line" in body and "25 words" in body


@pytest.mark.parametrize("role", ROLES)
def test_reply_examples_parse(role):
    _, body = _load(role)
    examples = re.findall(r"^`(.+ → /.+/dispatch/.+\.md)`$", body, flags=re.M)
    assert examples, role
    for line in examples:
        parse_reply(role, line)
```

- [ ] **Step 2: Run to verify failure**

Run: `$PY -m pytest ../../tests/overseer/test_agents.py -q -p no:cacheprovider` → FAIL (`FileNotFoundError`).

- [ ] **Step 3: Write the five definitions**

`agents/overseer-reviewer.md`:

````markdown
---
name: overseer-reviewer
description: Adversarial reviewer for one overseer card stage (plan or implementation). Dispatched by the overseer orchestrator; its whole prompt is a bundle path.
tools: Read, Grep, Glob, Bash, Write
model: sonnet
---
You are an ADVERSARIAL reviewer. Your charter is to REFUTE the work named in your bundle.

Your prompt is the absolute path of your bundle. Read it first: it holds your inputs, your lens, and the path to write your verdict to.

## Charter
- Hunt the failure case. Distrust the implementer's report; verify every claim against the artifact. Stated rationales are claims, not evidence.
- Default to "found wanting" when uncertain. Approval must be earned against resistance.
- Your lens is a priority, not a blinker: flag any bug you trip over.
- Review independently: never read another reviewer's verdict for the current round.
- For every finding a fixer marked DISPUTED in a prior fix report, state WITHDRAWN or MAINTAINED — maintained only with new evidence.
- Do not modify the worktree. The only file you write is your verdict.
- Evidence: file:line for every finding.

## Verdict file (the reply path in your bundle)
Start with:

```
verdict: approved | found wanting
critical: <n>
important: <n>
minor: <n>
```

Then findings tiered Critical / Important / Minor (file:line, what is wrong, why it matters, the fix if not obvious); then a Disputes section if any; then one line per durable, falsifiable fact worth keeping — `Learned: <one sentence> [tags: a, b]` — or `Learned: none`.

## Reply
Your final message is ONE line, at most 25 words, exactly one of:
`approved 0C 0I 2M → /abs/state/dispatch/WF-12/impl-review/r1-A.md`
`found wanting 1C 2I 0M → /abs/state/dispatch/WF-12/impl-review/r1-A.md`
using your real counts and your bundle's reply path. Nothing else — no summary, no preamble.
````

`agents/overseer-implementer.md`:

````markdown
---
name: overseer-implementer
description: Implements one chunk of an approved overseer card plan in the card's worktree, TDD. Dispatched by the overseer orchestrator; its whole prompt is a bundle path.
tools: Read, Grep, Glob, Bash, Edit, Write, Skill
model: sonnet
---
You implement ONE chunk of an approved plan, in an isolated worktree.

Your prompt is the absolute path of your bundle. Read it first: it names your chunk, worktree, gate commands and report path.

## Charter
- TDD: failing test → minimal implementation → green → gates (lint + types) → commit. Small, focused commits.
- Work ONLY in the worktree. Never touch the overseer state directory except to write your report file.
- Stay inside the chunk. Work you believe is needed beyond it goes in your report, not into the code.
- Blocked or unsure: stop and report BLOCKED or NEEDS_CONTEXT. Bad work is worse than no work.
- No progress messages. Your report file and reply line are the only output.

## Report file (the reply path in your bundle)
Start with:

```
status: DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
commits: <sha subject>, ...
tests: <command> → <passed>/<total>
```

Then concerns or blockers, if any; then `Learned: <one sentence> [tags: a, b]` lines or `Learned: none`.

## Reply
Your final message is ONE line, at most 25 words, exactly:
`DONE tests 41/41 abc1234 → /abs/state/dispatch/WF-12/implementation/c2.md`
with your real status, test counts, latest commit sha (`-` if none) and your bundle's reply path. Nothing else.
````

`agents/overseer-fixer.md`:

````markdown
---
name: overseer-fixer
description: Fixes all Critical and Important review findings for one overseer review round, with covering tests. Dispatched by the overseer orchestrator; its whole prompt is a bundle path.
tools: Read, Grep, Glob, Bash, Edit, Write, Skill
model: sonnet
---
You fix one review round's findings.

Your prompt is the absolute path of your bundle. Read it first, then read every verdict file it lists.

## Charter
- Fix ALL Critical and Important findings across all verdict files in one pass; Minors only where trivial alongside.
- Every fix carries covering-test evidence: name the test, run it, record the result.
- If a finding is wrong, do not "fix" it badly: mark it DISPUTED in your report with evidence. The next round's reviewers withdraw or maintain it.
- Commit as `fix(<scope>): <what>` after the gates pass.

## Report file (the reply path in your bundle)
Start with:

```
status: DONE | DISPUTED | BLOCKED
fixed: <n>
disputed: <n>
commits: <sha subject>, ...
```

Then per finding: `<verdict file>#<finding> — fixed (test: …)` or `— DISPUTED: <evidence>`; then `Learned:` lines or `Learned: none`.

## Reply
Your final message is ONE line, at most 25 words, exactly:
`DONE fixed 3 disputed 0 abc1234 → /abs/state/dispatch/WF-12/impl-review/r1-fix.md`
(`DISPUTED` when any finding is disputed; `-` for sha if no commit). Nothing else.
````

`agents/overseer-planner.md`:

````markdown
---
name: overseer-planner
description: Plans one overseer card — chunks, PR decomposition, estimate, trade-offs. Dispatched by the overseer orchestrator; its whole prompt is a bundle path.
tools: Read, Grep, Glob, Bash, Write
model: sonnet
---
You plan one card of work. Your plan becomes the card's Plan section and is the contract every later agent works from.

Your prompt is the absolute path of your bundle. Read it first.

## Charter
- If the card is L: first try to SPLIT it into independently releasable cards; plan it whole only if splitting fails, and say why.
- YAGNI ruthlessly. Plan the best way to do the work, not the most work.
- Read the code before planning; follow existing patterns; flag (do not plan) refactors beyond scope.
- Anything genuinely ambiguous: reply NEEDS_CONTEXT with the question in the plan file.

## Plan file (the reply path in your bundle), in order
1. **Wider picture** — one paragraph: how this fits the codebase and what done looks like.
2. **Chunks** — numbered, each small enough for one worker (≈15 tool calls), with files touched and exit condition.
3. **PR decomposition** — each PR releasable alone, tests green at every boundary; single PR is fine when honest.
4. **Estimate** — token budget per the policy bands, adjusted by the calibration figures; one line of justification.
5. **Trade-offs** — decisions and rejected alternatives, with why.

Then `Learned:` lines or `Learned: none`.

## Reply
Your final message is ONE line, at most 25 words, exactly:
`DONE → /abs/state/dispatch/WF-12/planning/plan.md`
(or `NEEDS_CONTEXT → …`). Nothing else.
````

`agents/overseer-verifier.md`:

````markdown
---
name: overseer-verifier
description: Verifies an overseer card end-to-end — tests, type-checker, linter, and exercising the change. Dispatched by the overseer orchestrator; its whole prompt is a bundle path.
tools: Read, Grep, Glob, Bash, Write
model: sonnet
---
You verify that a card's change works. Evidence, not assurance.

Your prompt is the absolute path of your bundle. Read it first.

## Charter
- Run every gate command in the bundle and record the exact command and result.
- Exercise the change end-to-end the way a user would (run the CLI, hit the endpoint, open the page) and record what you did and saw.
- Do not fix anything. A failure is a FAIL with evidence.

## Verification file (the reply path in your bundle)
Start with `result: PASS | FAIL`, then one entry per gate (command → result) and per end-to-end check (action → observation), then `Learned:` lines or `Learned: none`.

## Reply
Your final message is ONE line, at most 25 words, exactly:
`PASS → /abs/state/dispatch/WF-12/verification/verification.md`
(or `FAIL → …`). Nothing else.
````

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PY -m pytest ../../tests/overseer/test_agents.py -q -p no:cacheprovider` → PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/agents tests/overseer/test_agents.py
git commit -m "feat(overseer): minimal-preamble agent definitions with fixed reply lines (WF-113)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Skill prose, policy, references, version

**Files:**
- Modify: `plugins/overseer/skills/orchestrate/SKILL.md`
- Modify (rewrite): `plugins/overseer/skills/orchestrate/references/review-loop.md`, `references/telemetry.md`
- Modify: `plugins/overseer/skills/orchestrate/policy.md`, `references/knowledge.md`, `references/context-stewardship.md`, `plugins/overseer/skills/ledger/SKILL.md`
- Modify: `plugins/overseer/.claude-plugin/plugin.json` (`"version": "0.24.0"`)
- Test: `tests/overseer/test_skill_prose.py`

**Interfaces:**
- Consumes: every verb and agent type from Tasks 4–10.

- [ ] **Step 1: Write the failing test** (guards the prose against drifting back)

```python
# tests/overseer/test_skill_prose.py
import json
from pathlib import Path

OVERSEER = Path(__file__).resolve().parents[2] / "plugins" / "overseer"
SKILL = (OVERSEER / "skills" / "orchestrate" / "SKILL.md").read_text()
LOOP = (OVERSEER / "skills" / "orchestrate" / "references" / "review-loop.md").read_text()
IMPL = (OVERSEER / "templates" / "implementer.md").read_text()


def test_orchestrator_rules_present():
    for phrase in ("dispatch-prep", "overseer:overseer-", "never fork", "bootstrap",
                   "facts --pending", "run_in_background", "stage boundary"):
        assert phrase in SKILL, phrase


def test_retired_instructions_gone():
    assert "cadence" not in IMPL
    assert "[peer-cc]" not in SKILL
    assert "log-usage <card> --role" not in SKILL
    assert "log-review <id>" not in LOOP


def test_version_bumped():
    assert json.loads((OVERSEER / ".claude-plugin" / "plugin.json").read_text())["version"] == "0.24.0"
```

- [ ] **Step 2: Run to verify failure**

Run: `$PY -m pytest ../../tests/overseer/test_skill_prose.py -q -p no:cacheprovider` → FAIL.

- [ ] **Step 3: Edit `SKILL.md`**

3a. Replace the role paragraph (from `You are the orchestrator:` through `templates live at\n\`../../templates/\`.`) with:

```markdown
You are the orchestrator: the main session, the single writer of the card in
`board.db` (the per-repo SQLite store shared across worktrees) and of the
*resolved state root* — always via the ledger CLI; the CLI resolves both for
you, you never hard-code them — the dispatcher of every agent, and the user's
single point of contact. Read `policy.md` (this directory) before the first
dispatch.

**You dispatch; you never do the work.** While a card is in flight you do not
Read source, Edit, Write, run tests or queries, or call MCP tools — and you
**never fork** (a fork inherits your whole context). A `PreToolUse` guard
enforces this for the session stamped as the card's orchestrator; if it denies
you, dispatch instead. Genuine exceptions (the user asks you directly for
something off-card): `release <card>` first, and say so. Every turn you take
re-reads your whole context, so every turn you *don't* take is the saving.
```

3b. Replace the **bootstrap**, **planning**, **implementation**, **impl-review** and **verification** bullets of the Stage playbook with:

```markdown
- **bootstrap** — one call: `bootstrap --title "<title>" --complexity <S|M|L>
  [--labels a,b] [--goal "<goal>"] [--jira|--linear KEY] [--type feat|fix|…]`
  (or `bootstrap --card <id>` for an existing card). It detects the real base
  branch, creates worktree + branch, records them, moves the card to
  `planning` and stamps you as orchestrator. Exit 1 leaves the card at
  `bootstrap` with the git error.
- **planning** — `dispatch-prep <id> --stage planning --role planner` →
  dispatch `overseer:overseer-planner` with the printed path as the whole
  prompt. The report hook copies the plan into the card's `## Plan`; you read
  it with `show <id> --json` only when you need it for the gate. L cards:
  attempt split first; if split, create the children **with `set-field <child>
  --parent <this-card>`** and keep this card as the epic. L keeps a second
  planning pass.
```

```markdown
- **implementation** — per chunk: `dispatch-prep <id> --stage implementation
  --role implementer --chunk <n> [--var gate_commands="…"]` → dispatch
  `overseer:overseer-implementer` with the path. Its one-line reply is all you
  read; the report hook logs progress, commits and real usage. A chunk that
  needs MCP tools: dispatch `general-purpose` with the same bundle path.
- **impl-review** — adversarial review loop over the diff; `dispatch-prep`
  writes the diff file for you (`references/review-loop.md`).
- **verification** — `dispatch-prep <id> --stage verification --role verifier
  --var gate_commands="…"` → dispatch `overseer:overseer-verifier`. The hook
  writes the card's `## Verification`. Empty Verification = cannot advance.
```

3c. Insert a new section directly after the Stage playbook:

```markdown
## Dispatch
- **Prompt = bundle path.** Always `dispatch-prep` first; the agent's whole
  prompt is the path it prints. Never paste plans, diffs, findings or files
  into a prompt — `--var` values are capped at 300 characters for that reason.
- **Agent types:** `overseer:overseer-planner|implementer|reviewer|fixer|verifier`.
  Pass `model` per `policy.md` tier on the `Agent` call. Never fork.
- **Replies are one line.** Each agent ends with a fixed one-line reply
  (status, counts, path). Decide from the line; open the named file only when
  the line says you must (a dispute, a BLOCKED, a FAIL).
- **You log nothing after a dispatch.** The `SubagentStop` report hook records
  review verdicts, progress, commits, real usage and Learned facts.
- **Run in the background, don't poll.** Dispatch with `run_in_background: true`
  when you have nothing else to do; the completion notice *is* the report. Never
  sleep, poll or message a running agent to check on it.
- **Batch.** Issue independent tool calls (parallel reviewers, independent CLI
  reads) in one turn.
- **Learned facts:** at each stage boundary, `facts --pending --card <id>`, then
  `accept-fact <P-id>` / `reject-fact <P-id> --reason "…"` per line.
```

3d. Replace the **Budget** and **Unresponsive** watchdog bullets with:

```markdown
- **Unresponsive:** an agent whose transcript has not changed for 2× the
  card's unresponsive window (policy table) → stop it and
  `block <id> --reason "agent: unresponsive"`. Never ping it.
- **Budget:** the guard denies a dispatch once the card's spend reaches 2× its
  estimate (`TRIPWIRE: …`). That is a hard stop: escalate with the overrun
  story, never `release` your way past it.
```

3e. Replace the whole `## Comms` section with:

```markdown
## Comms
- Subagent mode: hub-and-spoke. Agents reply to you with one line; detail lives
  in their dispatch files and the ledger.
- Team mode: peers may talk directly, but nothing they agree is real until it
  is on the card. Do **not** CC peer traffic to yourself — every message you
  receive is a full-context turn. If it isn't in the ledger, it didn't happen.
```

3f. Replace the whole `## Telemetry` section with:

```markdown
## Telemetry
Automatic. The `SubagentStop` report hook totals each overseer agent's real
usage from its transcript and appends it to `usage.jsonl`; implementer and
fixer spend also feeds the card's budget. `usage [--card <id>]` warns when
agents ignored the reply format (unparsed) or the 25-word cap (overrun).
Full rationale: `references/telemetry.md`.
```

3g. In `## Context stewardship`, replace the sentence beginning `hand over by piping your ledger rollup into vigil` through `on command.` with:

```markdown
hand over by piping your ledger rollup into vigil (`python
plugins/overseer/scripts/cli.py --root . handoff | python
plugins/vigil/scripts/cli.py --root . handover --no-snapshot --content-file -`)
**at every stage boundary** once the stage is recorded in the ledger (nothing in
your context is needed after that — the ledger holds it), when a card
completes, when over threshold, or on command.
```

3h. Replace the first sentence of `## Communication with the user` with:

```markdown
Terse and factual: state results, not process; no preamble or recap; expand
only when asked. Lead with card id + stage.
```

- [ ] **Step 4: Rewrite `references/review-loop.md`**

```markdown
# Adversarial review loop (both review stages)

Applies to **plan-review** (over the card's plan) and **impl-review** (over the
diff). `dispatch-prep` snapshots the plan or writes the diff for you; reviewers
read files, never pasted walls.

1. **Round n reviewers.** Panel per `policy.md` (count, tiers, lenses; L round 1
   = 3 then 2 with the strong reviewer retained). For each slot A, B, C:
   `dispatch-prep <id> --stage <stage> --role reviewer --slot <X> --round <n>
   --lens <lens>`, then dispatch every `overseer:overseer-reviewer` **in one
   turn**. Reviewers are independent: none sees another's current-round verdict.
2. **Read the lines.** All `approved` → stage passes. Any `found wanting` with
   C or I > 0 → step 3. Minors never force a round.
3. **One fixer.** `dispatch-prep <id> --stage <stage> --role fixer --round <n>`
   (it lists this round's verdict files) → dispatch `overseer:overseer-fixer`,
   the same implementer lineage. You do not read the findings.
4. **Re-review.** Round n+1 bundles list every earlier verdict and fix report;
   reviewers must WITHDRAW or MAINTAIN (with new evidence) each DISPUTED finding.
   A dispute maintained after that re-review is yours: open only that verdict
   file and fix report, decide, and record the ruling in `## Decisions`.
5. **Round cap per policy.** Cap hit → `block <id> --reason "user: review
   deadlock — <summary>"`.
6. The report hook logs every verdict under the round's header in `## Review
   log` — you never call `log-review` in this loop.
7. Never tell a reviewer what NOT to flag. Never pre-rate severities.
```

- [ ] **Step 5: Rewrite `references/telemetry.md`**

```markdown
# Telemetry (automatic)

The `SubagentStop` report hook (`hooks/report.sh` → `cli.py report-hook`) runs
when any `overseer:overseer-*` agent finishes. It:

1. parses the agent's one-line reply (card, stage, round/slot/chunk come from
   the dispatch file path);
2. totals real usage from the agent's own transcript (`agent_transcript_path`),
   counting each message once;
3. appends to `usage.jsonl`: `tokens` (raw total) plus `input`, `cache_read`,
   `cache_creation`, `output`, `budget_tokens`, `reply_words`, `overrun`,
   `agent_id`, `source: "hook"`;
4. writes the card: reviewer → `## Review log` entry; implementer/fixer →
   `## Progress log` + budget; planner → `## Plan`; verifier → `## Verification`;
5. queues `Learned:` lines as pending facts.

**Budget:** only implementer and fixer spend feeds `budget_actual` (so the S/M/L
bands and the 2× tripwire keep their meaning), counted as
`input + cache_creation + output`. Cache reads are the re-read amplification and
are excluded from the budget; the raw figure stays in `usage.jsonl`.

**Never blocks.** A reply that does not parse is recorded as `unparsed` with the
raw line; one over 25 words as `overrun`. `usage` prints a warning for both.
There is no retry — the cap is stated in the agent definition instead.

`log-usage` remains for manual entries (e.g. an orchestrator overhead figure at
card completion) but is not part of the dispatch loop.
```

- [ ] **Step 6: Smaller edits**

`policy.md`: delete the `Progress cadence` column from the table (header, separator and each row's fifth cell). Change the `Unresponsive after` column header to `Unresponsive after (no transcript change)`.

`references/knowledge.md`: append

```markdown
## Pending facts
Agents propose facts as `Learned:` lines in their dispatch files; the report
hook queues them. At each stage boundary: `facts --pending --card <id>`, then
`accept-fact <P-id>` (creates the KB fact, source = card + dispatch file) or
`reject-fact <P-id> --reason "…"`. Adjudicate before handing over.
```

`references/context-stewardship.md`: in the "Hand over — you decide" bullet, add after its first sentence: `The default trigger is every stage boundary once the stage is recorded in the ledger.`

`skills/ledger/SKILL.md`: in the verb list near the `log-progress` line, add:

```markdown
- **Orchestration verbs (orchestrate skill):** `bootstrap`, `dispatch-prep`,
  `set-section`, `release`, `facts --pending`, `accept-fact`, `reject-fact`.
  Hook backends (not for hand use): `report-hook`, `pretool-hook`.
```

`templates/implementer.md` already has no cadence line (Task 8). `plugin.json`: `"version": "0.24.0"`.

- [ ] **Step 7: Run tests to verify they pass**

Run: `$PY -m pytest -q -p no:cacheprovider` (full suite) → PASS; ruff + mypy clean.

- [ ] **Step 8: Commit**

```bash
git add plugins/overseer/skills plugins/overseer/.claude-plugin/plugin.json tests/overseer/test_skill_prose.py
git commit -m "docs(overseer): orchestrate dispatches, never works — bundle paths, one-line replies, hook telemetry, stage-boundary handover (WF-113)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Live verification and measurement

**Files:**
- Create (scratch only, not committed): `$SCRATCH/e2e/` where `SCRATCH=/private/tmp/claude-502/-Users-philip-pryde-repos-pip-skills/589afcd0-3b56-40e8-b924-5d2ad5cd70f9/scratchpad`
- Modify: `docs/superpowers/specs/2026-09-16-overseer-token-economy-design.md` (§10 results)

This task proves the hooks work inside a real Claude Code session (unit tests cannot) and records the two remaining measurements. All state is pinned into scratch — never the real `~/.claude*` overseer tree.

- [ ] **Step 1: Build a throwaway repo with pinned state**

```bash
E=$SCRATCH/e2e; rm -rf $E; mkdir -p $E/repo && cd $E/repo
git init -q && git config user.email t@t && git config user.name t
printf 'def add(a, b):\n    return a - b\n' > calc.py && git add . && git commit -qm base && git branch -M main
export OVERSEER_CENTRAL=$E/state OVERSEER_DB=$E/state/board.db OVERSEER_PYTHON=$PY
# OVERSEER_PYTHON matters: without it the hook wrappers fall back to system
# python3, which may lack pyyaml — the hooks would then fail open silently and
# this verification would prove nothing.
CLI="$PY /Users/philip.pryde/repos/pip-skills-token-economy/plugins/overseer/scripts/cli.py --root $E/repo"
$CLI init --yes
```

- [ ] **Step 2: Guard — orchestrator denied, agent allowed, fork denied**

```bash
cd $E/repo && OVERSEER_CENTRAL=$E/state OVERSEER_DB=$E/state/board.db OVERSEER_PYTHON=$PY claude -p --model sonnet --effort low \
  --plugin-dir /Users/philip.pryde/repos/pip-skills-token-economy/plugins/overseer \
  --strict-mcp-config --permission-mode bypassPermissions --output-format json \
  "Run exactly these steps and report each tool result verbatim:
   1. Bash: $CLI bootstrap --title 'fix add' --complexity S
   2. Edit $E/repo/calc.py replacing 'a - b' with 'a + b'.
   3. Agent with subagent_type 'fork' and prompt 'say hi'.
   4. Agent with subagent_type 'overseer:overseer-implementer' and prompt 'Edit $E/repo/calc.py replacing a - b with a + b, then reply: DONE tests 0/0 - → $E/state/dispatch/WF-001/implementation/c1.md'" \
  | head -1 > $E/guard.json
$PY -c "import json;print(json.load(open('$E/guard.json'))['result'])"
grep -c 'a + b' $E/repo/../repo-wf-001/calc.py $E/repo/calc.py 2>/dev/null
```

Expected: step 2 denied with `WF-001 in flight: the orchestrator dispatches…`; step 3 denied with `forks inherit`; step 4's agent edit succeeds (the file it names changes). Record the outputs.

- [ ] **Step 3: Report hook — reply lands in the ledger with real usage**

```bash
mkdir -p $E/state/dispatch/WF-001/implementation && echo "status: DONE" > $E/state/dispatch/WF-001/implementation/c1.md
$CLI show WF-001 --json | $PY -c "import json,sys;d=json.load(sys.stdin);print(d['sections'].get('## Progress log'));print(d['budget'])"
$CLI usage --card WF-001
tail -2 $E/state/usage.jsonl
```

Expected (the detail file did not exist when the implementer replied, so the entry also carries `error: detail file missing`): a `chunk 1 — DONE tests 0/0 -` progress line from step 2's implementer, a `usage.jsonl` entry with `source: "hook"` and non-zero `cache_read`/`output`. If the implementer's reply did not parse, the entry shows `unparsed` — record which and why.

- [ ] **Step 4: Read limit — measured**

```bash
seq 1 2000 | sed 's/^/line /' > $E/repo/big.txt
cd $E/repo && OVERSEER_CENTRAL=$E/state OVERSEER_DB=$E/state/board.db OVERSEER_PYTHON=$PY claude -p --model sonnet --effort low \
  --plugin-dir /Users/philip.pryde/repos/pip-skills-token-economy/plugins/overseer \
  --strict-mcp-config --permission-mode bypassPermissions --output-format json \
  "Agent subagent_type 'overseer:overseer-reviewer', prompt: 'Read $E/repo/big.txt with no limit or offset and report only the last line number you saw, as plain text.' Report its answer." \
  | head -1 | $PY -c "import json,sys;print(json.load(sys.stdin)['result'])"
```

Expected: `400`.

- [ ] **Step 5: Turn-1 context of an overseer agent inside this real repo (with CLAUDE.md)**

```bash
cd /Users/philip.pryde/repos/pip-skills-token-economy && OVERSEER_CENTRAL=$E/state2 OVERSEER_DB=$E/state2/board.db OVERSEER_PYTHON=$PY OVERSEER_GUARD=off claude -p --model sonnet --effort low \
  --plugin-dir /Users/philip.pryde/repos/pip-skills-token-economy/plugins/overseer \
  --output-format json \
  "Spawn one agent of subagent_type 'overseer:overseer-reviewer' with prompt 'Reply: ok' and one of subagent_type 'general-purpose' with prompt 'Reply: ok'. Report both answers." > /dev/null
D=$(ls -td ~/.claude-personal/projects/*pip-skills-token-economy*/*/subagents | head -1)
for f in $D/*.jsonl; do $PY - "$f" <<'PYEOF'
import json, sys
meta = json.load(open(sys.argv[1].replace(".jsonl", ".meta.json")))
for line in open(sys.argv[1]):
    d = json.loads(line)
    u = d.get("message", {}).get("usage") if d.get("type") == "assistant" else None
    if u:
        print(meta["agentType"], u["input_tokens"] + u["cache_read_input_tokens"] + u["cache_creation_input_tokens"])
        break
PYEOF
done
```

Record both turn-1 context figures.

- [ ] **Step 6: Full gates**

```bash
cd /Users/philip.pryde/repos/pip-skills-token-economy/plugins/overseer
$PY -m pytest -q -p no:cacheprovider
$PY -m ruff check scripts ../../tests/overseer
$PY -m mypy scripts
bash ../../tests/run.sh 2>&1 | tail -3
```

Expected: all green; the other plugin suites unaffected.

- [ ] **Step 7: Record results in the spec and commit**

Replace spec §10's "Remaining, measured in the plan's final task" paragraph with the measured figures from Steps 2–5 (guard denials observed, hook entry observed, Read limit value, turn-1 context overseer agent vs general-purpose in this repo). Then:

```bash
git add docs/superpowers/specs/2026-09-16-overseer-token-economy-design.md
git commit -m "docs(overseer): record Phase 1 live verification and agent context measurements (WF-113)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Self-review notes

- **Spec coverage:** §4 grammar/paths → T1; §5.1 guard → T3 (table), T6 (stamping/release), T7; §5.2 agent defs → T10; §5.3 dispatch-prep → T8; §5.4 report hook → T2, T3, T5; §5.5 set-section + pending → T4; §5.6 disputes → T10 (reviewer/fixer charters), T8 (prior findings in bundle), T11 (review-loop); §5.7 Read limit → T7; §5.8 bootstrap → T9, no polling / batching / stage-boundary handover → T11; §5.9 terse charter + `verbosity` → T8 (bundle) + T11 (SKILL); §7 error handling → T5/T7 wrappers; §8 tests + measurement → every task + T12. Phase 2 (foreman) intentionally absent except `is_hub_agent`, which the guard needs now so the foreman is covered on arrival.
- **Known trade-off:** `pretool-hook` runs on every tool call in repos with overseer state (one Python start + one SQLite read). It exits at the `state_root(...).is_dir()` check in other repos. Measure in T12 if sessions feel slower.
- **Rejected in planning:** a `cards.orchestrator_session` column (side table instead — no Card/dashboard/backup churn); reviewer spend in the budget (kept telemetry.md's semantics so S/M/L bands stay meaningful).
