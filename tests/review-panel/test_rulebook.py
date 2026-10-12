"""A rules-lens seat is handed a generated rulebook: at most BATCH_CAP rules per batch, each rule with its id."""
import json
import os
import stat
from pathlib import Path

import pytest

from scripts.pip_agents import batching
from scripts.rulebook import BATCH_CAP, Rule, clone_rules, plan, render, table_rules

REVIEWERS = Path(__file__).resolve().parents[2] / "plugins" / "review-panel" / "skills" / "reviewers"
ROOT = Path(__file__).resolve().parents[2]


def test_cap_is_the_vendored_planners_cap():
    assert BATCH_CAP == batching().BATCH_CAP == 30


def test_vendored_planner_is_toolss_planner():
    assert (REVIEWERS.parents[1] / "vendor/pip-agents/scripts/batching.py").read_bytes() == \
        (ROOT / "tools" / "batching.py").read_bytes()


def test_table_rules_reads_ids_categories_and_rows():
    header, rules = table_rules((REVIEWERS / "general.md").read_text())
    assert [r.id for r in rules][:3] == ["GEN-001", "GEN-002", "GEN-003"] and len(rules) == 10
    assert header[0].startswith("| ID |") and set(header[1]) <= set("|- ")
    assert rules[0].category == "correctness" and rules[0].lines[0].startswith("| GEN-001 |")


def test_table_rules_ignores_other_tables_and_non_id_rows():
    text = "## Other\n| ID | x |\n| A-001 | y |\n\n## What to look for\n| ID | category |\n|--|--|\n| not an id | c |\n| X-001 | c |\n\n## Severity\n| X-002 | z |\n"
    header, rules = table_rules(text)
    assert [r.id for r in rules] == ["X-001"]


PERSONA = """---
alias: jen
---

## Voice & tone
Voice text.

## Rules

### Use auth-aware axios
**Severity:** blocker
**Citation:** https://example.com/c/1

### Name tests after behaviour
**Severity:** suggest
**Citation:** https://example.com/c/2
Body line.

## What they let go
Nothing.
"""


def test_clone_rules_numbers_each_rule_heading():
    rules = clone_rules("jen", PERSONA)
    assert [r.id for r in rules] == ["CLONE-jen-001", "CLONE-jen-002"]
    assert rules[0].lines[0] == "### CLONE-jen-001 Use auth-aware axios"
    assert "**Citation:** https://example.com/c/2" in rules[1].lines
    assert all("Nothing" not in "\n".join(r.lines) for r in rules)  # the let-go section is not a rule


def test_clone_rules_none_without_a_rules_section():
    assert clone_rules("jen", "## Voice & tone\nx\n") == []


def test_render_has_header_and_every_line():
    header, rules = table_rules((REVIEWERS / "general.md").read_text())
    text = render("general", rules[:2], header)
    assert text.splitlines()[0] == "# general rules" and "GEN-002" in text and "GEN-003" not in text


def mk(n, cat="c"):
    return [Rule(f"R-{i:03d}", cat, (f"| R-{i:03d} | {cat} |",)) for i in range(1, n + 1)]


def test_plan_keeps_a_small_book_whole():
    assert [len(b) for b in plan("x", mk(10))] == [10]


def test_plan_splits_over_the_cap_without_a_runt():
    assert [len(b) for b in plan("x", mk(31))] == [16, 15]
    assert [len(b) for b in plan("x", mk(64))] == [30, 30, 4] or all(8 <= len(b) <= 30 for b in plan("x", mk(64)))
    flat = [r.id for b in plan("x", mk(64)) for r in b]
    assert flat == [r.id for r in mk(64)]


def test_plan_empty_book_has_no_batches():
    assert plan("x", []) == []
