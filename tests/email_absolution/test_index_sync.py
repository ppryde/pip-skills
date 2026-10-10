"""doctrines/INDEX.md is generated; it must never drift from the doctrines (WF-266)."""
import re
import subprocess
import sys

from conftest import DOCTRINES, SCRIPTS


def test_build_check_passes(R):
    assert (DOCTRINES / "INDEX.md").read_text(encoding="utf-8") == R.build_index(DOCTRINES)
    r = subprocess.run([sys.executable, str(SCRIPTS / "rules.py"), "build", "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_row_count_equals_lint_rule_count(rules):
    text = (DOCTRINES / "INDEX.md").read_text(encoding="utf-8")
    canonical_rows = re.findall(r"^\| ([A-Z]+-\d{3}) \| [MVC] \| [MVC] \|", text, re.M)
    alias_rows = re.findall(r"^\| ([A-Z]+-\d{3}) \| ([A-Z]+-\d{3}) \| \S+\.md:\d+ \|$", text, re.M)
    assert len(canonical_rows) + len(alias_rows) == len(rules) == 248
    assert sorted(canonical_rows + [a for a, _ in alias_rows]) == sorted(r.id for r in rules)
    assert f"rules: {len(rules)} " in text


def test_index_is_small_enough_to_read_whole():
    assert (DOCTRINES / "INDEX.md").stat().st_size < 60_000


def test_index_carries_no_regexes_and_a_set_hash(R):
    text = (DOCTRINES / "INDEX.md").read_text(encoding="utf-8")
    assert R.sha_of_set(DOCTRINES) in text
    assert "GENERATED" in text
    assert "mso-hide)[^" not in text  # patterns live in the doctrines, not here


def test_aliases_listed_with_canonical(rules):
    text = (DOCTRINES / "INDEX.md").read_text(encoding="utf-8")
    for r in rules:
        if r.is_alias:
            assert f"| {r.id} | {r.alias_of} |" in text


def test_drift_is_detected(R, doctrine_copy):
    (doctrine_copy / "INDEX.md").write_text(R.build_index(doctrine_copy), encoding="utf-8")
    assert R.main(["--doctrines-dir", str(doctrine_copy), "build", "--check"]) == 0
    target = doctrine_copy / "liquid.md"
    target.write_text(target.read_text(encoding="utf-8").replace("Without a default", "Without any default", 1),
                      encoding="utf-8")
    assert R.main(["--doctrines-dir", str(doctrine_copy), "build", "--check"]) == 1
    assert R.main(["--doctrines-dir", str(doctrine_copy), "build"]) == 0
    assert R.main(["--doctrines-dir", str(doctrine_copy), "build", "--check"]) == 0


def test_build_refuses_to_index_unparseable_doctrines(R, doctrine_copy):
    p = doctrine_copy / "liquid.md"
    p.write_text(p.read_text(encoding="utf-8").replace("---\n", "", 1), encoding="utf-8")
    try:
        R.build_index(doctrine_copy)
    except SystemExit as e:
        assert "cannot build" in str(e)
    else:
        raise AssertionError("expected SystemExit")
