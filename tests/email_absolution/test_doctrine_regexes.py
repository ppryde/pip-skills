"""Doctrine detect patterns must not fire on compliant markup (WF-145), now on the shared parser,
plus the pattern-merge rulings of WF-266 (each named exception has its test here)."""
import re
import signal
import time

import pytest

from conftest import PLUGIN

PLANTED = PLUGIN / "tests" / "templates"


@pytest.fixture()
def hits(by_id, R):
    def _hits(rule_id: str, sample: str) -> bool:
        r = by_id[rule_id]
        assert r.detect is not None and r.detect.patterns, rule_id
        return any(re.search(p, sample) for p in r.detect.patterns)
    return _hits


# ---- the WF-145 assertions, unchanged in substance ------------------------------

def test_html001_not_picture_pre_param(hits):
    for ok in ("<picture>", "<pre>", "<param name=x>", '<p style="margin: 0;">'):
        assert not hits("HTML-001", ok), ok
    assert hits("HTML-001", "<p>text</p>")
    assert hits("HTML-001", '<p style="color:red">')


def test_html003_order_independent(hits):
    assert not hits("HTML-003", '<div style="mso-hide:all; display:none">')
    assert not hits("HTML-003", '<div style="display:none; mso-hide:all">')
    assert hits("HTML-003", '<div style="display:none">')


def test_html003_is_hybrid(by_id):
    assert by_id["HTML-003"].detect.kind == "hybrid"
    assert "verify" in by_id["HTML-003"].flags


def test_html005_single_font_only(hits):
    for ok in (
        'style="font-family: Arial, Helvetica, sans-serif;"',
        "font-family: 'Open Sans', Arial, sans-serif;",
        "font-family: 'Open Sans', sans-serif }",
        'font-family: "Open Sans", Arial, sans-serif;',
        "font-family: inherit;",
        "font-family: Arial, sans-serif !important;",
    ):
        assert not hits("HTML-005", ok), ok
    for bad in (
        "font-family: 'MyFont';",
        'style="font-family: MyFont"',
        'font-family: "MyFont";',
        "font-family: Arial !important;",
    ):
        assert hits("HTML-005", bad), bad


def test_render006_each_attribute(hits):
    full = '<table border="0" cellpadding="0" cellspacing="0">'
    assert not hits("RENDER-006", full)
    assert hits("RENDER-006", '<table border="0" cellpadding="0">')
    assert hits("RENDER-006", '<table cellpadding="0" cellspacing="0">')
    assert hits("RENDER-006", '<table border="0" cellspacing="0">')
    assert hits("RENDER-006", "border-collapse: collapse")


def test_verify_flag_on_the_ef1_rules(by_id):
    for rid in ("HTML-001", "HTML-003", "HTML-005", "RENDER-006"):
        assert "verify" in by_id[rid].flags, rid
    assert "verify" not in by_id["HTML-006"].flags


def test_html001_003_005_render006_patterns_are_byte_identical_to_146(by_id):
    # WF-146 shipped these exact patterns; WF-266 must not touch their bytes.
    assert by_id["HTML-001"].detect.patterns == [r'<p\b(?![^>]*style="[^"]*margin:\s*0)[^>]*>']
    assert by_id["HTML-003"].detect.patterns == [r'style="(?![^"]*mso-hide)[^"]*display:\s*none']
    assert by_id["HTML-005"].detect.patterns == [
        r"""font-family\s*:\s*(?:'[^',;"]*'|"[^",;]*"|(?!(?:inherit|initial|unset)\b)[A-Za-z][^,;"'}]*)\s*[;"}]"""]
    assert by_id["RENDER-006"].detect.patterns == [
        r"<table(?![^>]*\bcellpadding=)[^>]*>", r"<table(?![^>]*\bcellspacing=)[^>]*>",
        r"<table(?![^>]*\bborder=)[^>]*>", r"border-collapse\s*:\s*collapse"]


# ---- pattern-merge rulings (verdict change 2) -----------------------------------

def test_render009_absolute_urls(hits, R, by_id):
    for bad in ('<img src="/images/logo.png">', '<a href="/login">', '<img src="//cdn.example.com/a.png">',
                '<a href="http://example.com">', "<a href='http://example.com'>", '<a HREF="HTTP://x.com">',
                '<img src="logo.png">', '<a href="images/a.png">', '<a href="./a">', '<a href="../a">',
                '<a href="www.x.com">', '<img src="data:image/png;base64,AAA">'):
        assert hits("RENDER-009", bad), bad
    for ok in ('<a href="{{ url }}">', '<a href="{{cta_url}}">', '<a href="{% url x %}">',
               '<a href="*|UNSUB|*">', '<a href="%%unsub%%">', '<a href="<%= url %>">',
               '<a href="https://example.com/a">', '<a href="HTTPS://example.com/a">',
               '<a href="mailto:a@b.co">', '<a href="tel:+4412345">', '<a href="#top">',
               '<img src="cid:logo">', '<img src="{{ logo }}">'):
        assert not hits("RENDER-009", ok), ok


@pytest.mark.parametrize("ok", [
    '<a href="sms:+4412345">', '<a href="geo:51.5,-0.1">', '<a href="webcal://x.com/cal.ics">',
    '<a href="viber://chat?number=1">', '<a href="%unsubscribe_url%">', '<a href="%UNSUBSCRIBELINK%">',
    '<a href="$url">', '<a href="${url}">', '<a href="[unsubscribe]">', '<a href="<unsubscribe>">',
    '<a href="@Model.Url">', '<a href="<?= $url ?>">', '<a href="<%= url %>">',
])
def test_render009_allows_legit_schemes_and_esp_placeholders(hits, ok):
    assert not hits("RENDER-009", ok), ok


@pytest.mark.parametrize("bad", [
    '<a href="javascript:void(0)">', '<a href="ftp://x.com/f">', '<a href="JAVASCRIPT:x">',
])
def test_render009_still_fires_on_javascript_and_ftp(hits, bad):
    assert hits("RENDER-009", bad), bad


def test_html006_is_case_insensitive(hits):
    assert hits("HTML-006", '<A HREF="x">x</A>')
    assert not hits("HTML-006", '<A HREF="x" STYLE="color:red">x</A>')
    assert not hits("HTML-006", '<a href="x" STYLE="color:red">x</a>')
    assert hits("HTML-006", '<A HREF="x" DATA-STYLE="a">x</A>')


def test_planted_plain_relative_src_is_caught(by_id):
    line = next(ln for ln in (PLANTED / "level-1-obvious.liquid").read_text().splitlines()
                if "images/footer-logo.png" in ln)
    assert any(re.search(p, line) for p in by_id["RENDER-009"].detect.patterns)
    assert not re.search(r'src=["\']/', line)  # it is the no-leading-slash form


def test_render008_keeps_both_min_height_patterns(by_id):
    pats = by_id["RENDER-008"].detect.patterns
    assert len(pats) == 2
    assert any(re.search(p, '<td style="min-height: 80px">') for p in pats)
    assert not re.search(pats[0], "td { min-height: 80px }")
    assert re.search(pats[1], "td { min-height: 80px }")  # <style> blocks are covered


def test_html006_both_attribute_orders(hits):
    assert hits("HTML-006", '<a href="x">link</a>')
    assert hits("HTML-006", '<a class="c" href="x">link</a>')
    assert not hits("HTML-006", '<a href="x" style="color:#fff;text-decoration:none">link</a>')
    assert not hits("HTML-006", '<a style="color:#fff" href="x">link</a>')
    assert not hits("HTML-006", '<a class="c" style="color:#fff" target="_blank" href="x">link</a>')
    # the style attribute is read, not the anchor text
    assert hits("HTML-006", '<a href="x">my style=guide</a>')
    assert not hits("HTML-006", '<a href="x" style="color:red">x</a>')


def test_html006_wrapped_anchors_data_style_and_title(hits, by_id):
    assert "multiline" in by_id["HTML-006"].flags
    wrapped = '<a href="{{ url }}"\n   target="_blank"\n   style="color:#fff; text-decoration:none">x</a>'
    assert not hits("HTML-006", wrapped)
    assert hits("HTML-006", '<a href="{{ url }}"\n   target="_blank">x</a>')
    # data-style / x-style are not the style attribute
    assert hits("HTML-006", '<a href="x" data-style="a">x</a>')
    assert hits("HTML-006", '<a data-style="a" href="x">x</a>')
    # a title that merely contains "style=" is not a style attribute
    assert hits("HTML-006", '<a href="x" title="style=1">x</a>')
    assert not hits("HTML-006", '<a href="x" style = "color:red">x</a>')
    assert not hits("HTML-006", '<a style="color:red" href="x">x</a>')


def test_html006_wrapped_anchor_through_fire(R, rules):
    wrapped = '<a href="{{ u }}"\n   style="color:#fff">x</a>\n'
    assert "HTML-006" not in R.fire_ids(rules, wrapped)
    assert "HTML-006" in R.fire_ids(rules, '<a href="{{ u }}"\n   target="_blank">x</a>\n')


def test_render004_whitespace_colour_syntax(hits):
    for bad in ("rgb(51 51 51)", "rgba(0 0 0 / 0.5)", "rgb( 10% 20% 30% )", "color: rgb(0 128 0)"):
        assert hits("RENDER-004", bad), bad
    for ok in ("rgb(51, 51, 51)", "rgba(0, 0, 0, 0.5)", "rgba(26, 86, 219, 1)", "rgb(0,128,0)"):
        assert not hits("RENDER-004", ok), ok


def test_render001_covers_url_with_space(hits):
    assert hits("RENDER-001", '<td style="background-image: url(hero.jpg)">')
    assert hits("RENDER-001", '<td style="background-image: url (hero.jpg)">')
    assert not hits("RENDER-001", '<td style="padding:0">')


def test_access003_role_presentation(hits):
    assert hits("ACCESS-003", '<table border="0">')
    assert not hits("ACCESS-003", '<table role="presentation" border="0">')
    assert not hits("ACCESS-003", '<table border="0" role="presentation">')


def test_html008_td_padding_shorthand(hits):
    assert hits("HTML-008", '<td style="padding: 30px">')
    assert not hits("HTML-008", '<td style="padding-top: 30px">')


# ---- float / position split (verdict change 3) ----------------------------------

def test_float_is_gotcha012_and_not_target_filtered(by_id, hits):
    r = by_id["GOTCHA-012"]
    assert "targets" not in r.applies
    assert (r.transactional, r.marketing) == ("mortal", "mortal")
    assert hits("GOTCHA-012", "float: left") and hits("GOTCHA-012", 'style="float:right"')
    assert "other clients collapse it" in r.statement
    h = by_id["HTML-010"]
    assert (h.transactional, h.marketing) == ("mortal", "venial")
    assert not hits("HTML-010", '<div style="float: left">')
    for bad in ('<div style="position: absolute">', '<div style="top:0; position:relative">',
                '<div style="position: fixed">'):
        assert hits("HTML-010", bad), bad
    assert not hits("HTML-010", '<td style="padding:0">')


def test_float_survives_a_gmail_only_config(R, docs):
    cfg = R.Config(email_type="marketing", targets=("gmail",))
    active, _, _ = R.select_rules(docs, cfg)
    assert "GOTCHA-012" in {r.id for r in active}


# ---- GOTCHA-028 has its own detect (verdict change 6) ---------------------------

def test_gotcha028_is_the_preheader_recipe_not_html003(by_id):
    r = by_id["GOTCHA-028"]
    assert r.detect.kind == "contextual"
    assert "mso-hide:all" in r.detect.check and "opacity:0" in r.detect.check
    assert not r.is_alias


# ---- the other linearised / disambiguated patterns ------------------------------

def test_hbs_patterns_keep_their_meaning(hits):
    assert hits("HBS-002", "{{{rawHtml}}}") and not hits("HBS-002", "{{name}}")
    assert hits("HBS-008", "{{ order.date }}")
    assert hits("HBS-008", "{{ created_date }}")
    assert not hits("HBS-008", "{{ name }}")
    assert hits("HBS-010", '{{#if user.tier === "vip"}}') and hits("HBS-010", "{{#if a >= 3}}")
    assert not hits("HBS-010", "{{#if user.isVip}}")
    assert not hits("HBS-010", "{{#if a")  # unterminated tag


def test_render022_meta_tags_vs_html017_css(hits, by_id):
    assert by_id["RENDER-022"].detect.patterns != by_id["HTML-017"].detect.patterns
    assert hits("RENDER-022", '<meta name="color-scheme" content="light dark">')
    assert hits("RENDER-022", '<meta name="supported-color-schemes" content="light dark">')
    assert not hits("RENDER-022", ":root { color-scheme: light dark; }")
    assert hits("HTML-017", ":root { color-scheme: light dark; }")


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="no interval timer")
def test_every_pattern_is_linear_on_a_hostile_line(rules, R):
    # The lint budget, asserted directly with a larger margin than lint uses on its own.
    worst = 0.0
    for r in rules:
        if r.is_alias or r.detect is None:
            continue
        for pat in list(r.detect.patterns) + list(r.detect.absence):
            c = re.compile(pat)
            for corpus in R.hostile_corpora(pat):
                t0 = time.perf_counter()
                assert R.regex_within_budget(c, corpus), (r.id, pat)
                worst = max(worst, time.perf_counter() - t0)
    assert worst < R.REGEX_BUDGET_S * 1.5


def test_skills_exclude_underscore_and_index_doctrines(R):
    """Behavioural replacement for the old `starts with _` string assertion."""
    names = {p.name for p in R.doctrine_files(R.DEFAULT_DOCTRINES)}
    assert "_template.md" not in names and "INDEX.md" not in names


def test_template_rules_never_selected(R, docs):
    assert not any(r.id.startswith("PREFIX-") for r in R.all_rules(docs))
    text = R.render_select(docs, R.Config(email_type="marketing"))
    assert "PREFIX-" not in text
