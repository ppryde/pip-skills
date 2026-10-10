"""Golden: which regex rules fire on the planted level-* templates, before vs after the migration.

golden_before.json was captured on origin/main (05e0918d) by capture_golden.py: the OLD
doctrines, structure-normalised by migrate_doctrines.py --stage1-only, scanned line by line by
the SAME rules.py that runs now. One parser on both sides, so the comparison means something.

The after-set must equal the before-set mapped through the alias table and the split below,
modulo the documented changes - exact equality, so any unintended change fails.
"""
import json
from pathlib import Path

import pytest

from conftest import PLUGIN

GOLDEN = json.loads((Path(__file__).parent / "golden_before.json").read_text(encoding="utf-8"))
TEMPLATES = PLUGIN / "tests" / "templates"

# Documented changes (rule id -> why). `lost` = fired before, no longer; `gained` = new hit.
WHY = {
    "GOTCHA-028": "its regex was HTML-003's defect; the preheader recipe is now a contextual check",
    "RENDER-009": "GOTCHA-025's pattern fired on every href=\"{{ url }}\"; only real relative/http: URLs remain",
    "RENDER-004": "GOTCHA-004's pattern fired on comma syntax with spaces (rgba(26, 86, 219, 1)) and was a ReDoS",
    "HTML-006": "new pattern reads the style attribute (not the anchor text) and matches multi-line anchors",
}
DOCUMENTED = {
    "level-1-obvious.liquid": {"lost": {"GOTCHA-028", "HTML-006"}, "gained": set()},
    "level-2-moderate.liquid": {"lost": {"GOTCHA-028", "RENDER-009"}, "gained": set()},
    "level-3-handlebars.hbs": {"lost": {"RENDER-004", "RENDER-009"}, "gained": set()},
    "level-4-advanced.liquid": {"lost": {"RENDER-004", "RENDER-009"}, "gained": set()},
    "level-5-gotchas.hbs": {"lost": {"GOTCHA-028", "RENDER-009"}, "gained": {"HTML-006"}},
    "level-6-mjml.mjml": {"lost": {"HTML-006", "RENDER-009"}, "gained": set()},
    "level-7-content.hbs": {"lost": {"RENDER-009"}, "gained": {"HTML-006"}},
}


def test_golden_covers_every_planted_template():
    assert set(GOLDEN) == {p.name for p in TEMPLATES.glob("level-*")}
    assert set(DOCUMENTED) == set(GOLDEN)


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_regex_hits_match_golden_modulo_documented_changes(name, R, rules):
    alias_to = {r.id: r.alias_of for r in rules if r.is_alias}
    hits = set(R.fire_ids(rules, (TEMPLATES / name).read_text(encoding="utf-8")))

    expected = set()
    for rid in GOLDEN[name]:
        if rid == "HTML-010":
            # split entry: a float hit moved to GOTCHA-012, a position hit stays HTML-010
            expected.add("HTML-010" if "HTML-010" in hits else "GOTCHA-012")
        else:
            expected.add(alias_to.get(rid, rid))

    lost = expected - hits
    gained = hits - expected
    assert lost == DOCUMENTED[name]["lost"], f"lost: {sorted(lost)}"
    assert gained == DOCUMENTED[name]["gained"], f"gained: {sorted(gained)}"
    for rid in lost | gained:
        assert rid in WHY, rid


def test_aliases_never_fire(R, rules):
    alias_ids = {r.id for r in rules if r.is_alias}
    for tpl in TEMPLATES.glob("level-*"):
        assert not set(R.fire_ids(rules, tpl.read_text(encoding="utf-8"))) & alias_ids


def test_float_hits_split_to_gotcha012(R, rules):
    assert R.fire_ids(rules, '<div style="float: left">')["GOTCHA-012"] == 1
    assert "HTML-010" not in R.fire_ids(rules, '<div style="float: left">')
    assert "HTML-010" in R.fire_ids(rules, '<div style="position: absolute">')


def test_scan_is_line_based_and_multiline_is_opt_in(R, rules):
    css = "<style>\n/* note */\n.a { color: red }\n</style>"
    assert "GOTCHA-020" in R.fire_ids(rules, css)           # flagged multiline, spans two lines
    split = '<td style="padding:0;\nbackground:url(x.png)">'
    assert "RENDER-001" not in R.fire_ids(rules, split)     # line based, as the Grep fallback is
    assert "RENDER-001" in R.fire_ids(rules, '<td style="background:url(x.png)">')


def test_absence_rules_fire_once_per_file(R, rules):
    assert "MJML-001" in R.fire_ids(rules, "<mjml><mj-body></mj-body></mjml>")
    assert "MJML-001" not in R.fire_ids(rules, "<mjml><mj-head><mj-preview>x</mj-preview></mj-head></mjml>")
