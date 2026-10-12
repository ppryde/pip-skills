"""optimise-orm adopts pip-agents (WF-270 PR D): triggers.py --batches, the reviewer-rules and explorer wiring, OO-16."""
import importlib.util
import json
import re
import subprocess
import sys

import pytest

from lean_common import REPO

SKILL = REPO / "plugins" / "django-inquisition" / "skills" / "optimise-orm"
SCRIPT = SKILL / "scripts" / "triggers.py"
INDEX = SKILL / "checks" / "INDEX.md"
FIXTURES = SKILL / "tests" / "fixtures"
SKILL_MD = (SKILL / "SKILL.md").read_text(encoding="utf-8")
EXPLAIN = (SKILL / "references" / "explain.md").read_text(encoding="utf-8")
PLUGIN = REPO / "plugins" / "django-inquisition"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


trig = load("orm_triggers_agents", SCRIPT)
batching = load("pip_batching_orm", REPO / "tools" / "batching.py")


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)


def batch_rows(stdout):
    return [ln.split(" | ") for ln in stdout.splitlines() if ln.startswith("batch ")]


def test_constants_are_the_repo_constants():
    assert (trig.BATCH_CAP, trig.BATCH_FLOOR) == (batching.BATCH_CAP, batching.BATCH_FLOOR), "drift: tools/batching.py"


def nominee(i, group):
    return {"id": f"{group[:3].upper()}-{i:03d}", "group": group, "file": f"{group}.md", "a": 10 * i, "b": 10 * i + 5}


def plan(counts):
    nominees = [nominee(i, g) for g, n in counts.items() for i in range(1, n + 1)]
    return nominees, trig.plan_batches(nominees)


@pytest.mark.parametrize("counts", [
    {"fetching": 12, "writes": 14, "iteration": 4},
    {"fetching": 5, "writes": 5, "iteration": 5, "joins": 5, "cardinality": 5, "aggregation": 5, "indexes": 5, "patterns": 5},
    {"fetching": 14, "writes": 14, "indexes": 14, "patterns": 12, "joins": 4, "aggregation": 8, "iteration": 4, "cardinality": 7},
    {"fetching": 3},
    {"fetching": 40},
])
def test_batches_tile_the_nominees_and_respect_cap_and_floor(counts):
    nominees, batches = plan(counts)
    total = sum(counts.values())
    flat = [n["id"] for b in batches for n in b]
    assert all(len(b) <= trig.BATCH_CAP for b in batches)
    if total < trig.BATCH_FLOOR:
        assert batches == []
    else:
        assert sorted(flat) == sorted(n["id"] for n in nominees) and len(set(flat)) == len(flat)
        assert all(len(b) >= trig.BATCH_FLOOR for b in batches), [len(b) for b in batches]


def test_a_group_of_floor_or_more_is_never_packed_with_another():
    _, batches = plan({"fetching": 9, "writes": 3, "iteration": 3, "joins": 3})
    groups = [{n["group"] for n in b} for b in batches]
    assert {"fetching"} in groups and any({"writes", "iteration", "joins"} == g for g in groups)


def test_cli_batches_write_files_a_reviewer_can_open(tmp_path):
    f = FIXTURES / "01-basic-n-plus-one"
    out = tmp_path / "scratch"
    r = run(f / "target.py", f / "templates", "--thorough", "--batches", "--out-dir", out)
    assert r.returncode == 0, r.stderr
    rows = batch_rows(r.stdout)
    assert rows and all(re.fullmatch(r"batch \d+/\d+", row[0]) for row in rows)
    index_rows = trig.load_rows(INDEX)
    seen = []
    for k, row in enumerate(rows, 1):
        _, groups, count, span, ids = row
        path, rng = span.rsplit(" L1-", 1)
        body = (out / f"batch-{k}.md").read_text(encoding="utf-8")
        assert path == str(out / f"batch-{k}.md") and len(body.splitlines()) == int(rng)
        assert body.startswith(f"# Batch {k}: ")
        id_list = ids.split(",")
        assert int(count) == len(id_list) <= trig.BATCH_CAP
        heads = re.findall(r"^### ([A-Z]+-\d+)", body, re.M)
        assert heads == id_list, "one section per id, in order, each opening on its own heading"
        seen += id_list
    assert sorted(seen) == sorted(r["id"] for r in index_rows), "--thorough nominates every check once"


def test_section_text_in_a_batch_file_is_the_group_files_text(tmp_path):
    f = FIXTURES / "01-basic-n-plus-one"
    out = tmp_path / "scratch"
    run(f / "target.py", "--thorough", "--batches", "--out-dir", out)
    rows = {r["id"]: r for r in trig.load_rows(INDEX)}
    body = "".join(p.read_text(encoding="utf-8") for p in sorted(out.glob("batch-*.md")))
    for cid in ("FETCH-001", "WRITE-001"):
        r = rows[cid]
        lines = (SKILL / "checks" / r["file"]).read_text(encoding="utf-8").splitlines()[r["a"] - 1:r["b"]]
        assert "\n".join(lines) in body


def test_default_run_prints_no_batches_and_writes_nothing(tmp_path):
    f = FIXTURES / "01-basic-n-plus-one"
    r = run(f / "target.py")
    assert r.returncode == 0 and not batch_rows(r.stdout)


def test_batches_need_an_out_dir_and_it_must_be_absolute(tmp_path):
    f = FIXTURES / "01-basic-n-plus-one" / "target.py"
    assert run(f, "--batches").returncode == 2
    assert run(f, "--batches", "--out-dir", "relative").returncode == 2


def test_thorough_nominates_every_check_of_the_active_groups():
    f = FIXTURES / "09-non-django-target" / "target.py"
    r = run(f, "--thorough", "--groups", "fetching")
    ids = [ln.split()[0] for ln in r.stdout.splitlines()[1:]]
    want = [x["id"] for x in trig.load_rows(INDEX) if x["file"] == "fetching.md"]
    assert ids == want


# ---- the skill text ---------------------------------------------------------------------------------------------

def test_skill_dispatches_reviewer_rules_and_explorer_and_stays_within_budget():
    fan_out = (SKILL / "references" / "fan-out.md").read_text(encoding="utf-8")
    assert "pip-agents:reviewer-rules" in SKILL_MD and "pip-agents:explorer" in SKILL_MD
    assert "more than 30" in SKILL_MD and "references/fan-out.md" in SKILL_MD and "general-purpose" not in SKILL_MD
    for needle in ("--batches", "pip-agents:reviewer-rules", "pip-agents:explorer", "at most 12 in flight", "rules: <the line's path"):
        assert needle in fan_out, needle
    budgets = json.loads((REPO / "tests/lean/budgets.json").read_text())["budgets"]
    assert len(SKILL_MD.encode()) <= budgets["plugins/django-inquisition/skills/optimise-orm/SKILL.md"]


def test_plugin_depends_on_pip_agents():
    plugin = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    assert plugin["dependencies"] == ["pip-agents"] and plugin["version"].startswith("0.5.")


def test_explain_defaults_to_plain_explain_and_refuses_analyze_unless_asked():
    """OO-16: plain EXPLAIN by default; ANALYZE only with an explicit flag, never on writes or non-local databases."""
    plain = EXPLAIN.split("## ANALYZE", 1)[0]
    assert "EXPLAIN ANALYZE" not in plain and "(ANALYZE" not in plain and "plain `EXPLAIN`" in plain
    assert "--explain-analyze" in SKILL_MD and "--explain-analyze" in EXPLAIN
    analyze = EXPLAIN.split("## ANALYZE", 1)[1]
    for needle in ("localhost", "127.0.0.1", "test", "refuse", "BEGIN", "ROLLBACK", "write"):
        assert needle in analyze, needle
    assert "actual" in analyze and "ratio" in analyze  # the 5x actual/estimated bump needs ANALYZE
    assert "EXPLAIN (ANALYZE" not in SKILL_MD
