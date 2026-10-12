"""Puritan adopts pip-agents:reviewer-rules (WF-270 PR B): doctrines/BATCHES.md and the inquisition wiring."""
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PLUGIN = REPO / "plugins/puritan"
DOCTRINES = PLUGIN / "skills/doctrines"
BATCHES = DOCTRINES / "BATCHES.md"
GEN = REPO / "tools/build_index.py"
SKILL = PLUGIN / "skills/inquisition/SKILL.md"
REPORT = PLUGIN / "skills/inquisition/references/report-format.md"

spec = importlib.util.spec_from_file_location("pip_batching", REPO / "tools/batching.py")
batching = importlib.util.module_from_spec(spec)
sys.modules["pip_batching"] = batching
spec.loader.exec_module(batching)

BATCH_LINE = re.compile(r"^- batch: (\d+)/(\d+) ((?:L\d+-\d+,?)+) \(([A-Z0-9,-]+)\)$")


def lines_of(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")


def parse_batches():
    out, name = {}, None
    for ln in lines_of(BATCHES):
        if ln.startswith("## "):
            name = ln[3:].strip()
            out[name] = []
        m = BATCH_LINE.match(ln)
        if m:
            k, n, spans, ids = m.groups()
            out[name].append({"k": int(k), "n": int(n), "ids": ids.split(","),
                              "spans": [tuple(int(x) for x in s[1:].split("-")) for s in spans.split(",")]})
    return out


def catalog_ids(path):
    return re.findall(r"^\|\s*([A-Z]{2,5}-\d+)\s*\|", "\n".join(lines_of(path)), re.M)


def headings(path):
    return {i for i, ln in enumerate(lines_of(path), 1) if re.match(r"#{2,3} ", ln)}


def audit_span(name):
    text = (DOCTRINES / "INDEX.md").read_text()
    section = text.split(f"\n## {name}\n", 1)[1].split("\n## ", 1)[0]
    a, b = re.search(r"^- audit: L(\d+)-(\d+)$", section, re.M).groups()
    return int(a), int(b)


DOCS = sorted(p.stem for p in DOCTRINES.glob("*.md")
              if not p.name.startswith("_") and p.name not in ("INDEX.md", "README.md", "BATCHES.md"))


def test_every_doctrine_has_batches():
    assert sorted(parse_batches()) == DOCS and len(DOCS) == 13


@pytest.mark.parametrize("name", DOCS)
def test_batches_tile_the_catalogue_exactly_and_none_exceeds_the_cap(name):
    bs = parse_batches()[name]
    assert bs and [b["k"] for b in bs] == list(range(1, len(bs) + 1)) and {b["n"] for b in bs} == {len(bs)}
    assert all(0 < len(b["ids"]) <= batching.BATCH_CAP for b in bs)
    assert [i for b in bs for i in b["ids"]] == catalog_ids(DOCTRINES / f"{name}.md")  # tile: exact, in order, once


@pytest.mark.parametrize("name", DOCS)
def test_spans_start_on_a_heading_end_before_one_and_stay_inside_audit(name):
    path = DOCTRINES / f"{name}.md"
    heads, total = headings(path), len(lines_of(path))
    a0, b0 = audit_span(name)
    for b in parse_batches()[name]:
        assert b["spans"][0][0] == a0, "every batch opens with the Applicable Directories preamble"
        assert b["spans"][-1][1] == b0, "every batch closes with the Allowed Exceptions span"
        prev = 0
        for a, e in b["spans"]:
            assert a in heads, f"{name}: span L{a}-{e} does not start on a heading"
            assert e + 1 in heads or e == total, f"{name}: span L{a}-{e} does not end before a heading"
            assert a0 <= a <= e <= b0 and a > prev
            prev = e


@pytest.mark.parametrize("name", DOCS)
def test_each_batch_rule_row_lies_inside_its_spans(name):
    lines = lines_of(DOCTRINES / f"{name}.md")
    for b in parse_batches()[name]:
        for rid in b["ids"]:
            row = next(i for i, ln in enumerate(lines, 1) if re.match(rf"\|\s*{rid}\s*\|", ln))
            assert any(a <= row <= e for a, e in b["spans"]), f"{rid} (line {row}) is outside {b['spans']}"


def test_single_batch_doctrine_is_the_whole_audit_span():
    hexagonal = parse_batches()["hexagonal"]
    assert len(hexagonal) == 1 and hexagonal[0]["spans"] == [audit_span("hexagonal")]


def test_batches_md_is_not_a_doctrine():
    assert "BATCHES.md" in (PLUGIN / "skills/_shared/config.md").read_text()
    covenant = (PLUGIN / "skills/covenant/SKILL.md").read_text()
    assert "BATCHES.md" in covenant or "INDEX.md" in covenant


def run(*args):
    return subprocess.run([sys.executable, str(GEN), *args], capture_output=True, text=True)


def test_generator_writes_and_checks_both_files(tmp_path):
    root = tmp_path
    shutil.copytree(DOCTRINES, root / "plugins/puritan/skills/doctrines")
    assert run("doctrines", "--check", "--root", str(root)).returncode == 0
    target = root / "plugins/puritan/skills/doctrines/BATCHES.md"
    target.write_text(target.read_text().replace("DDD-001", "DDD-9XX", 1))
    r = run("doctrines", "--check", "--root", str(root))
    assert r.returncode == 1 and "BATCHES.md" in r.stdout and "DDD-9XX" in r.stdout
    assert run("doctrines", "--root", str(root)).returncode == 0
    assert run("doctrines", "--check", "--root", str(root)).returncode == 0


def test_generator_splits_an_oversized_doctrine_by_category(tmp_path):
    root = tmp_path
    shutil.copytree(DOCTRINES, root / "plugins/puritan/skills/doctrines")
    d = root / "plugins/puritan/skills/doctrines"
    for p in d.glob("*.md"):
        if p.stem != "strategy" and not p.name.startswith("_") and p.name not in ("README.md",):
            p.unlink()
    assert run("doctrines", "--root", str(root)).returncode == 0
    text = (d / "BATCHES.md").read_text()
    assert "- rules: 41 in 2 batches" in text


# ---- the inquisition skill and its report format -------------------------------------------------------------

def test_plugin_depends_on_pip_agents_and_bumps_its_version():
    plugin = json.loads((PLUGIN / ".claude-plugin/plugin.json").read_text())
    assert plugin["dependencies"] == ["pip-agents"]
    assert plugin["version"].startswith("1.3.")


def test_inquisition_dispatches_reviewer_rules_per_batch():
    text = SKILL.read_text() + REPORT.read_text()
    for needle in ("pip-agents:reviewer-rules", "BATCHES.md", "rules checked", "exceptions: report", "12"):
        assert needle in text, needle
    assert "general-purpose" not in text
    assert "Paste" not in SKILL.read_text() and "span_relocated" not in text


def test_pragmatic_strictness_downgrades_allowed_exceptions():
    text = SKILL.read_text() + REPORT.read_text()
    assert "exception" in text and "pragmatic" in text
    step5 = SKILL.read_text().split("### Step 5", 1)[1].split("### Step 6", 1)[0]
    assert "`exception`" in step5 and "warning" in step5
    assert "strict" in step5 and "aspirational" in step5
