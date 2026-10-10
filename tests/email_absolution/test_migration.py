"""migrate_doctrines.py: idempotent, id-preserving, severity changes limited to the table (WF-266)."""
import re

import pytest

LEGACY = {  # real legacy detect lines (origin/main 05e0918d) -> what the grammar must make of them
    "LIQ-001": ("> `detect: regex` — pattern: `\\{\\{[\\s]*[a-zA-Z_][a-zA-Z0-9_.]*[\\s]*\\}\\}` (output tag with no filter pipe)",
                ["\\{\\{[\\s]*[a-zA-Z_][a-zA-Z0-9_.]*[\\s]*\\}\\}"]),
    "ACCESS-010": ("> `detect: regex` — patterns: `<p[^>]*>\\s*[•\\*\\-–▸▪►]\\s` (symbol bullet); `<p[^>]*>\\s*\\d+[.)]\\s` (numbered list in paragraph)",
                   ["<p[^>]*>\\s*[•\\*\\-–▸▪►]\\s", "<p[^>]*>\\s*\\d+[.)]\\s"]),
    "HTML-013": ("> `detect: regex` — pattern: `<img(?![^>]*\\bwidth=)[^>]*>` or `<img(?![^>]*\\bheight=)[^>]*>`",
                 ["<img(?![^>]*\\bwidth=)[^>]*>", "<img(?![^>]*\\bheight=)[^>]*>"]),
    "REMAIL-009": ("> `detect: regex` — pattern: `<img\\s` (lowercase `img` element — not the React Email component)",
                   ["<img\\s"]),
    "MJML-007": ("> `detect: regex` — absence check: flag if file contains `<mjml` but not `<mj-breakpoint`", []),
}


def test_legacy_lines_normalise_to_the_same_regex_bytes(migrate, R):
    for rid, (line, pats) in LEGACY.items():
        new = migrate.normalise_detect(rid, line)
        d, err = R.parse_detect(new)
        assert not err, (rid, err)
        if pats:
            assert d.patterns == pats, rid
        else:
            assert d.absence == ("<mjml", "<mj-breakpoint")


def test_normalise_is_idempotent(migrate, R):
    for rid, (line, _) in LEGACY.items():
        once = migrate.normalise_detect(rid, line)
        assert migrate.normalise_detect(rid, once) == once


def test_unknown_irregular_line_is_refused_not_guessed(migrate):
    with pytest.raises(SystemExit):
        migrate.normalise_detect("NEW-001", "> `detect: regex` — part 1: something odd")


def test_running_the_migration_on_the_migrated_tree_changes_nothing(migrate, doctrine_copy, R):
    before = {p.name: p.read_bytes() for p in doctrine_copy.glob("*.md")}
    migrate.run(doctrine_copy, quiet=True)
    after = {p.name: p.read_bytes() for p in doctrine_copy.glob("*.md")}
    assert before == after


def test_main_regenerates_index_and_is_stable(migrate, doctrine_copy, R, capsys):
    (doctrine_copy / "INDEX.md").unlink()
    assert migrate.main(["--doctrines-dir", str(doctrine_copy)]) == 0
    assert (doctrine_copy / "INDEX.md").read_text(encoding="utf-8") == R.build_index(doctrine_copy)
    capsys.readouterr()


def test_id_set_assert_catches_a_dropped_rule(migrate, doctrine_copy):
    p = doctrine_copy / "tooling.md"
    text = p.read_text(encoding="utf-8")
    start = text.index("**[TOOL-015]**")
    p.write_text(text[:start], encoding="utf-8")  # TOOL-015 is the last rule of tooling.md
    with pytest.raises(AssertionError):
        migrate.run(doctrine_copy, quiet=True)


def test_alias_conversion_drops_detect_and_severity(migrate):
    block = ["**[GOTCHA-001]** `transactional: mortal | marketing: mortal` — Do not use `url()`.",
             "> Why.", "> `detect: regex` — pattern: `style=\"[^\"]*url\\(`", ""]
    out = migrate.rewrite_block("GOTCHA-001", block)
    assert out[0] == "**[GOTCHA-001]** `alias of RENDER-001` — Do not use `url()`."
    assert not any(ln.startswith("> `detect:") for ln in out)
    assert migrate.rewrite_block("GOTCHA-001", out) == out  # idempotent


def test_severity_moves_are_exactly_the_documented_ones(migrate):
    assert set(migrate.SEVERITY) == {"RENDER-016", "GOTCHA-002"}
    assert migrate.SEVERITY["RENDER-016"] == ("mortal", "mortal")
    assert migrate.SEVERITY["GOTCHA-002"] == ("venial", "venial")  # not counsel: the 80 KB margin is real


def test_severity_diff_against_the_old_headers(migrate):
    before = {"RENDER-016": ("mortal", "venial"), "GOTCHA-002": ("mortal", "mortal"),
              "HTML-001": ("mortal", "mortal")}
    after = {"RENDER-016": ("mortal", "mortal"), "GOTCHA-002": ("venial", "venial"),
             "HTML-001": ("mortal", "mortal")}
    rows = migrate.severity_diff(before, after)
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [
        ("GOTCHA-002", "transactional", "mortal", "venial"),
        ("GOTCHA-002", "marketing", "mortal", "venial"),
        ("RENDER-016", "marketing", "venial", "mortal"),
    ]


def test_render016_marketing_is_mortal_and_gotcha002_is_venial_with_the_margin_rationale(by_id):
    assert (by_id["RENDER-016"].transactional, by_id["RENDER-016"].marketing) == ("mortal", "mortal")
    g = by_id["GOTCHA-002"]
    assert (g.transactional, g.marketing) == ("venial", "venial")
    text = g.file.read_text(encoding="utf-8")
    block = text[text.index("**[GOTCHA-002]**"):text.index("**[GOTCHA-003]**")]
    assert "as delivered" in block and "link rewriting" in block and "quoted-printable" in block
    assert "counsel" in block  # explains why it is not counsel
    assert by_id["RENDER-010"].transactional == "mortal"      # the 102,400 B limit stays mortal
    assert by_id["DELIV-005"].alias_of == "RENDER-010"


def test_applies_pass_follows_the_targets_guard(rules):
    """A `targets=` rule names only Outlook 2007-2019 as a victim; mixed-client bodies get none."""
    victims = re.compile(r"Gmail|Yahoo|Apple Mail|Samsung|AOL|webmail|Outlook\.com|new Outlook", re.I)
    for r in rules:
        if "targets" in r.applies:
            text = r.file.read_text(encoding="utf-8")
            block = text[text.index(f"**[{r.id}]**"):]
            block = block.split("\n**[", 1)[0]
            assert not victims.search(block.split("applies:", 1)[0].replace("webmail", "")) or r.id in {
                "HTML-003"}, r.id          # HTML-003 names mobile/dark-mode only as *uses* of display:none
            assert r.applies["targets"] == ["outlook-2019"]


def test_known_esp_and_gen_annotations(by_id):
    assert by_id["HBS-003"].applies == {"esp": ["sendgrid"]}
    assert by_id["HBS-004"].applies == {"esp": ["postmark"]}
    assert by_id["LIQ-012"].applies == {"esp": ["klaviyo"]}
    assert by_id["LIQ-019"].applies == {"esp": ["klaviyo"]}
    assert "sendgrid" in by_id["TOOL-008"].applies["esp"]
    for rid in ("DELIV-001", "DELIV-002", "DELIV-003", "DELIV-016"):
        assert by_id[rid].applies == {"gen": ["no"]}


def test_ghost_table_aware_html004_and_retitled_render018(by_id):
    assert "ghost" in by_id["HTML-004"].statement and "ghost" in by_id["HTML-004"].detect.check
    assert (by_id["HTML-004"].transactional, by_id["HTML-004"].marketing) == ("mortal", "mortal")  # PR 3 demotes
    s = by_id["RENDER-018"].statement
    assert "ignored by Outlook" in s and "width" in s


def test_unsubscribe_conditionality_is_untouched(by_id):
    """SC-2 is an owner question: UX-016 stays mortal on both tracks."""
    assert (by_id["UX-016"].transactional, by_id["UX-016"].marketing) == ("mortal", "mortal")
    assert not by_id["UX-016"].applies
