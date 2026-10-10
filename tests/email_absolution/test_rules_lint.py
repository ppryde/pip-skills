"""rules.py lint: the structural contract of the doctrine corpus (WF-266)."""
import re
import subprocess
import sys

import pytest

from conftest import DOCTRINES, PLUGIN, SCRIPTS

FRONT = "---\ndoctrine: {name}\nprefix: {prefix}\nkind: core\nscribe: constraints\n---\n\n# T\n\n"


def make_dir(tmp_path, body, name="demo", prefix="DEMO"):
    d = tmp_path / "d"
    d.mkdir()
    (d / f"{name}.md").write_text(FRONT.format(name=name, prefix=prefix) + body, encoding="utf-8")
    return d


def rule(n, tx="mortal", mk="mortal", detect="`detect: contextual` — check it", extra=""):
    return (f"**[DEMO-{n:03d}]** `transactional: {tx} | marketing: {mk}` — Statement {n}.\n"
            f"> Why.\n{extra}> {detect}\n\n")


def problems(R, d):
    _, probs = R.lint(d)
    return [m for _, _, m in probs]


def test_real_corpus_lints_clean(R):
    _, probs = R.lint(DOCTRINES)
    assert not probs, probs


def test_rule_count_is_248(rules):
    assert len(rules) == 248
    assert len({r.id for r in rules}) == 248


def test_cli_lint_exits_zero():
    r = subprocess.run([sys.executable, str(SCRIPTS / "rules.py"), "lint"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "248 rules" in r.stdout


def test_every_header_line_parses(docs):
    for d in docs:
        text = d.path.read_text(encoding="utf-8").split("\n")
        n = sum(1 for ln in text if ln.startswith("**["))
        assert n == len(d.rules), d.name


def test_prefix_and_front_matter_per_doctrine(docs):
    assert len(docs) == 12
    for d in docs:
        assert d.front["doctrine"] == d.name
        assert all(r.prefix == d.front["prefix"] for r in d.rules)
    langs = {d.name: d.front["templating"] for d in docs if d.front["kind"] == "language"}
    assert langs == {"liquid": "liquid", "handlebars": "handlebars", "mjml": "mjml",
                     "react-email": "react-email", "maizzle": "maizzle"}
    assert next(d for d in docs if d.name == "tooling").front["scribe"] == "skip"
    assert next(d for d in docs if d.name == "content-ux").front["scribe"] == "constraints"


def test_transactional_never_weaker_than_marketing(rules, R):
    for r in rules:
        if not r.is_alias:
            assert R.RANK[r.transactional] >= R.RANK[r.marketing], r.id


def test_aliases_resolve_in_one_hop_and_carry_nothing(rules, by_id):
    aliases = [r for r in rules if r.is_alias]
    assert len(aliases) == 9
    for a in aliases:
        assert not by_id[a.alias_of].is_alias, a.id
        assert a.detect is None and not a.applies and not a.flags, a.id
        assert a.transactional == "" and a.marketing == "", a.id


def test_template_vocabulary_mirrors_script(R):
    text = (DOCTRINES / "_template.md").read_text(encoding="utf-8")
    found = {}
    for m in re.finditer(r"^- `(\w+)`: (.+)$", text, re.M):
        found[m.group(1)] = m.group(2).split()
    assert found == R.VOCAB


def test_template_and_index_are_not_doctrines(R):
    names = {p.name for p in R.doctrine_files(DOCTRINES)}
    assert "_template.md" not in names and "INDEX.md" not in names
    assert len(names) == 12


def test_gen_only_no_and_only_audit_neutral_values(rules):
    for r in rules:
        if "gen" in r.applies:
            assert r.applies["gen"] == ["no"], r.id


def test_every_non_alias_has_a_valid_detect(rules):
    for r in rules:
        if r.is_alias:
            continue
        assert r.detect is not None, r.id
        if r.detect.kind != "contextual":
            assert r.detect.patterns or r.detect.absence, r.id


def test_advisory_and_selection_guidance_lines_are_accepted(R):
    d, err = R.parse_detect("> `detect: contextual` — advisory; check project documentation")
    assert not err and d.advisory and d.check == "check project documentation"
    d, err = R.parse_detect("> `detect: contextual` — selection guidance")
    assert not err and d.advisory and d.check == ""
    d, err = R.parse_detect("> `detect: contextual` — check the footer")
    assert not err and not d.advisory


def test_thirty_nine_legacy_advisory_lines_survive(rules):
    adv = [r for r in rules if r.detect and r.detect.advisory]
    assert len(adv) == 39


# ---------------------------------------------------------------- negative cases

def test_missing_front_matter_is_an_error(R, tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    (d / "demo.md").write_text("# T\n\n" + rule(1), encoding="utf-8")
    assert any("front-matter" in m for m in problems(R, d))


def test_duplicate_id_and_bad_prefix(R, tmp_path):
    d = make_dir(tmp_path, rule(1) + rule(1))
    assert any("duplicate id" in m for m in problems(R, d))
    d2 = tmp_path / "e"
    d2.mkdir()
    (d2 / "demo.md").write_text(FRONT.format(name="demo", prefix="OTHER") + rule(1), encoding="utf-8")
    assert any("prefix" in m for m in problems(R, d2))


def test_inverted_tracks_are_rejected(R, tmp_path):
    d = make_dir(tmp_path, rule(1, tx="venial", mk="mortal"))
    assert any("weaker than marketing" in m for m in problems(R, d))


def test_unknown_applies_value_and_gen(R, tmp_path):
    d = make_dir(tmp_path, rule(1, extra="> `applies: esp=braze`\n"))
    assert any("unknown esp" in m for m in problems(R, d))
    t2 = tmp_path / "t2"
    t2.mkdir()
    d = make_dir(t2, rule(1, extra="> `applies: gen=yes`\n"))
    assert any("gen" in m for m in problems(R, d))


def test_bad_detect_grammar(R, tmp_path):
    d = make_dir(tmp_path, rule(1, detect="`detect: regex` — `bare-pattern`"))
    assert any("must start with" in m for m in problems(R, d))
    t2 = tmp_path / "t2"
    t2.mkdir()
    d = make_dir(t2, rule(1, detect="`detect: regex` — pattern: `a` (trailing parenthetical)"))
    assert any("introduced by" in m for m in problems(R, d))


def test_regex_must_compile(R, tmp_path):
    d = make_dir(tmp_path, rule(1, detect="`detect: regex` — pattern: `(unclosed`"))
    assert any("does not compile" in m for m in problems(R, d))


def test_identical_regex_on_two_canonical_rules_is_an_error(R, tmp_path):
    body = (rule(1, detect="`detect: regex` — pattern: `foo=`") +
            rule(2, detect="`detect: regex` — pattern: `foo=`"))
    assert any("identical regex" in m for m in problems(R, make_dir(tmp_path, body)))


def test_alias_to_alias_and_alias_with_detect(R, tmp_path):
    body = (rule(1) +
            "**[DEMO-002]** `alias of DEMO-001` — Dup.\n> Why.\n\n"
            "**[DEMO-003]** `alias of DEMO-002` — Dup of dup.\n> Why.\n\n")
    assert any("itself an alias" in m for m in problems(R, make_dir(tmp_path, body)))
    t2 = tmp_path / "t2"
    t2.mkdir()
    body = rule(1) + "**[DEMO-002]** `alias of DEMO-001` — Dup.\n> Why.\n> `detect: contextual` — x\n\n"
    assert any("carries no detect" in m for m in problems(R, make_dir(t2, body)))


def test_hostile_corpus_budget_catches_catastrophic_backtracking(R, tmp_path):
    # exponential on a long run of spaces; the real corpus must never contain such a pattern
    d = make_dir(tmp_path, rule(1, detect="`detect: regex` — pattern: `(?:\\s+)+x`"))
    if not hasattr(__import__("signal"), "setitimer"):
        pytest.skip("no interval timer on this platform")
    assert any("hostile-corpus budget" in m for m in problems(R, d))


def test_old_gotcha004_pattern_would_have_failed_the_budget(R):
    import re as _re
    if not hasattr(__import__("signal"), "setitimer"):
        pytest.skip("no interval timer on this platform")
    pat = r"(?:rgb|rgba)\([^)]*\s[^),]*(?:/[^)]*)?(?:[^,)])\)"
    assert R._literal_prefix(pat) == "rgb("
    c = _re.compile(pat)
    assert not all(R.regex_within_budget(c, corp) for corp in R.hostile_corpora(pat))


def test_cli_lint_reports_file_and_line(tmp_path):
    d = make_dir(tmp_path, rule(1, tx="venial", mk="mortal"))
    r = subprocess.run([sys.executable, str(SCRIPTS / "rules.py"), "--doctrines-dir", str(d), "lint"],
                       capture_output=True, text=True)
    assert r.returncode == 1
    assert re.search(r"demo\.md:\d+: DEMO-001", r.stderr)


def test_pyproject_wiring():
    text = (PLUGIN / "pyproject.toml").read_text(encoding="utf-8")
    assert "../../tests/email_absolution" in text
    run_sh = (PLUGIN.parents[1] / "tests" / "run.sh").read_text(encoding="utf-8")
    assert re.search(r"^SUITES=\(.*\bemail-absolution\b.*\)", run_sh, re.M)
