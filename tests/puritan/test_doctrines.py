"""Doctrine lint (WF-268 puritan): prefixes, template order, cross-refs, signal preambles. Stdlib only."""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DOCTRINES = REPO / "plugins/puritan/skills/doctrines"
SECTIONS = ["When to Use", "Why Use It", "Pros and Cons", "Applicable Directories", "Violation Catalog",
            "Allowed Exceptions", "Cross-Reference", "Sources and Authority", "Detection Signatures"]
FILES = sorted(p for p in DOCTRINES.glob("*.md") if not p.name.startswith("_") and p.name not in ("INDEX.md", "README.md"))


def text(p):
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def planned():
    body = text(DOCTRINES / "README.md").split("## Planned", 1)[1]
    return set(re.findall(r"^- `([\w-]+\.md)`", body, re.M))


def test_thirteen_doctrines():
    assert len(FILES) == 13


@pytest.mark.parametrize("path", FILES + [DOCTRINES / "_template.md"], ids=lambda p: p.name)
def test_sections_present_in_template_order(path):
    heads = re.findall(r"^## (.+)$", text(path), re.M)
    idx = [heads.index(s) for s in SECTIONS]
    assert idx == sorted(idx)


def test_prefixes_unique():
    seen = {}
    for p in FILES:
        for pre in set(re.findall(r"^\|\s*([A-Z]{2,5})-\d+\s*\|", text(p), re.M)):
            assert pre not in seen, f"{pre}: {p.name} and {seen[pre]}"
            seen[pre] = p.name


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_cross_refs_resolve_or_are_planned(path):
    section = text(path).split("## Cross-Reference", 1)[1].split("\n## ", 1)[0]
    for ref in re.findall(r"^-\s+\*\*([\w.-]+\.md)\*\*", section, re.M):
        assert (DOCTRINES / ref).exists() or ref in planned(), f"{path.name} -> {ref} neither exists nor planned"


def test_planned_entries_do_not_exist():
    for ref in planned():
        assert not (DOCTRINES / ref).exists(), f"{ref} exists; remove it from Planned"


@pytest.mark.parametrize("path", FILES + [DOCTRINES / "_template.md"], ids=lambda p: p.name)
def test_signal_preambles_carry_no_numeric_threshold(path):
    sig = text(path).split("## Detection Signatures", 1)[1]
    for sub in ("Directory signals", "File signals"):
        lines = sig.split(f"### {sub}\n", 1)[1].split("\n")
        assert not re.search(r"\d", lines[0]), f"{path.name}: {sub} preamble has a number: {lines[0]}"
