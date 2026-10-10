from pathlib import Path

import pytest

from scripts.contract import Finding, RULE_ID_RE, rule_id_of
from scripts.discovery import discover_builtin_reviewers
from scripts.doclint import lint_doc
from scripts.exceptions import (
    ExceptionsError, load_allowed_exceptions, parse_allowed_exceptions,
)
from scripts.strictness import apply_strictness

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "review-panel"
REVIEWERS = PLUGIN / "skills" / "reviewers"


def _doc(body: str) -> str:
    return f"## Allowed exceptions\nSentence.\n\n```allowed-exceptions\n{body}```\n"


def test_parse_ids_and_reasons():
    got = parse_allowed_exceptions(_doc("GEN-009   # tests are in another repo\nGEN-003\n"))
    assert got == {"GEN-009": "tests are in another repo", "GEN-003": ""}


def test_blank_and_comment_only_lines_are_not_entries():
    assert parse_allowed_exceptions(_doc("\n# GEN-009  # example\n   \n")) == {}


def test_empty_block_is_none():
    assert parse_allowed_exceptions("```allowed-exceptions\n```\n") == {}


def test_bad_id_rejected():
    for bad in ("gen-001\n", "GEN-1\n", "GEN-001 GEN-002\n", "GEN-0012\n"):
        with pytest.raises(ExceptionsError, match="not a rule id"):
            parse_allowed_exceptions(_doc(bad))


def test_prefix_digit_ids_accepted():
    assert "A1-001" in parse_allowed_exceptions(_doc("A1-001\n"))


def test_no_block_rejected():
    with pytest.raises(ExceptionsError, match="no ```allowed-exceptions"):
        parse_allowed_exceptions("## Allowed exceptions\nprose only\n")


def test_two_blocks_rejected():
    two = _doc("GEN-001\n") + _doc("GEN-002\n")
    with pytest.raises(ExceptionsError, match="2 allowed-exceptions blocks"):
        parse_allowed_exceptions(two)


def test_unterminated_block_rejected():
    with pytest.raises(ExceptionsError, match="not closed"):
        parse_allowed_exceptions("```allowed-exceptions\nGEN-001\n")


def test_other_fences_are_ignored():
    text = "```python\nGEN-999\n```\n" + _doc("GEN-001\n")
    assert list(parse_allowed_exceptions(text)) == ["GEN-001"]


def test_rule_id_regex_is_one_shared_constant():
    assert rule_id_of("GEN-001-2") == "GEN-001"
    assert rule_id_of("A1-001") == "A1-001"
    assert rule_id_of("gen-001") is None and rule_id_of(None) is None
    assert RULE_ID_RE.pattern == r"^[A-Z][A-Z0-9]*-\d{3}"


def test_load_keys_by_bare_name_clones_empty(tmp_path):
    (tmp_path / "mine.md").write_text(_doc("MIN-001\n"))
    got = load_allowed_exceptions(tmp_path, ["mine", "danvk"])
    assert got == {"mine": {"MIN-001"}, "danvk": set()}


def test_load_custom_file_without_block_warns_and_runs_as_none(tmp_path):
    (tmp_path / "old.md").write_text("## Allowed exceptions\nprose\n")
    warnings: list[str] = []
    got = load_allowed_exceptions(tmp_path, ["old"], warnings)
    assert got == {"old": set()}
    assert warnings and "old.md" in warnings[0]


def test_load_refuses_traversal_names(tmp_path):
    (tmp_path.parent / "evil.md").write_text(_doc("EVL-001\n"))
    assert load_allowed_exceptions(tmp_path, ["../evil"]) == {"../evil": set()}


def _finding(id_, rule_id, severity="error"):
    return Finding(reviewer="general", id=id_, file="a.py", rule="r", actual="x",
                   severity=severity, category="c", suggestion="s", rule_id=rule_id)


def test_strictness_matches_on_rule_id_not_per_run_id():
    out = apply_strictness(
        [_finding("GEN-009-2", "GEN-009"), _finding("GEN-001", "GEN-001")],
        {"general": "pragmatic"}, {"general": {"GEN-009"}},
    )
    assert [f.severity for f in out] == ["warning", "error"]


def test_strictness_only_caps_error_never_raises():
    out = apply_strictness(
        [_finding("GEN-009", "GEN-009", "info"), _finding("GEN-003", "GEN-003", "warning")],
        {"general": "pragmatic"}, {"general": {"GEN-009", "GEN-003"}},
    )
    assert [f.severity for f in out] == ["info", "warning"]


def test_strict_ignores_exceptions():
    out = apply_strictness([_finding("GEN-009", "GEN-009")], {"general": "strict"},
                           {"general": {"GEN-009"}})
    assert out[0].severity == "error"


def test_every_reviewer_file_and_the_template_lint_clean():
    files = [REVIEWERS / f"{n}.md" for n in discover_builtin_reviewers(REVIEWERS)]
    files.append(REVIEWERS / "_template.md")
    assert len(files) >= 2
    for path in files:
        assert lint_doc(path, "reviewer") == [], path.name


def test_shipped_general_excuses_nothing():
    assert parse_allowed_exceptions((REVIEWERS / "general.md").read_text()) == {}
    assert parse_allowed_exceptions((REVIEWERS / "_template.md").read_text()) == {}


def test_doclint_flags_id_not_in_table(tmp_path):
    src = (REVIEWERS / "general.md").read_text().replace(
        "```allowed-exceptions\n```", "```allowed-exceptions\nGEN-099\n```")
    doc = tmp_path / "x.md"
    doc.write_text(src)
    problems = lint_doc(doc, "reviewer")
    assert any("GEN-099" in p for p in problems)


def test_doclint_flags_missing_block(tmp_path):
    src = (REVIEWERS / "general.md").read_text().split("```allowed-exceptions")[0]
    doc = tmp_path / "x.md"
    doc.write_text(src)
    assert any("allowed-exceptions" in p for p in lint_doc(doc, "reviewer"))


def test_doclint_heading_match_is_exact(tmp_path):
    src = (REVIEWERS / "general.md").read_text().replace(
        "## Severity", "## Severity levels")
    doc = tmp_path / "x.md"
    doc.write_text(src)
    assert any("'## Severity'" in p for p in lint_doc(doc, "reviewer"))


def test_doclint_accepts_str_path():
    assert lint_doc(str(REVIEWERS / "general.md"), "reviewer") == []
