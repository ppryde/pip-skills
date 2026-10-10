"""Doctrine detect patterns must not fire on compliant markup (WF-145)."""
import re
from pathlib import Path

DOCTRINES = Path(__file__).resolve().parents[2] / "plugins" / "email-absolution" / "doctrines"
SKILLS = DOCTRINES.parent / "skills"


def patterns(rule_id: str) -> list[str]:
    text = next(
        f.read_text() for f in DOCTRINES.glob("*.md") if f"**[{rule_id}]**" in f.read_text()
    )
    block = text.split(f"**[{rule_id}]**", 1)[1].split("\n**[", 1)[0]
    detect = next(line for line in block.splitlines() if "`detect:" in line)
    spans = detect.split("—", 1)[1].split("`")[1::2]  # odd spans are code
    return [s for s in spans if len(s) > 6]


def hits(rule_id: str, sample: str) -> bool:
    return any(re.search(p, sample) for p in patterns(rule_id))


def test_html001_not_picture_pre_param():
    for ok in ("<picture>", "<pre>", "<param name=x>", '<p style="margin: 0;">'):
        assert not hits("HTML-001", ok), ok
    assert hits("HTML-001", "<p>text</p>")
    assert hits("HTML-001", '<p style="color:red">')


def test_html003_order_independent():
    assert not hits("HTML-003", '<div style="mso-hide:all; display:none">')
    assert not hits("HTML-003", '<div style="display:none; mso-hide:all">')
    assert hits("HTML-003", '<div style="display:none">')


def test_html003_is_hybrid():
    text = (DOCTRINES / "html-css.md").read_text()
    block = text.split("**[HTML-003]**", 1)[1].split("\n**[", 1)[0]
    assert "`detect: hybrid`" in block


def test_html005_single_font_only():
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


def test_render006_each_attribute():
    full = '<table border="0" cellpadding="0" cellspacing="0">'
    assert not hits("RENDER-006", full)
    assert hits("RENDER-006", '<table border="0" cellpadding="0">')
    assert hits("RENDER-006", '<table cellpadding="0" cellspacing="0">')
    assert hits("RENDER-006", '<table border="0" cellspacing="0">')
    assert hits("RENDER-006", "border-collapse: collapse")


def test_skills_exclude_underscore_doctrines():
    for skill in ("elder", "scribe", "visitation"):
        assert "starts with `_`" in (SKILLS / skill / "SKILL.md").read_text(), skill
