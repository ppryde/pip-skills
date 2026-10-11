"""optimise-orm scripts/triggers.py: one-call trigger scan over the generated INDEX (WF-268)."""
import importlib.util
import re
import subprocess
import sys

import pytest

from lean_common import REPO

SKILL = REPO / "plugins" / "django-inquisition" / "skills" / "optimise-orm"
SCRIPT = SKILL / "scripts" / "triggers.py"
INDEX = SKILL / "checks" / "INDEX.md"
FIXTURES = SKILL / "tests" / "fixtures"

spec = importlib.util.spec_from_file_location("orm_triggers", SCRIPT)
trig = importlib.util.module_from_spec(spec)
sys.modules["orm_triggers"] = trig
spec.loader.exec_module(trig)


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)


def ids(stdout):
    return [ln.split()[0] for ln in stdout.splitlines()[1:]]


def test_every_index_trigger_compiles_and_all_rows_parse():
    rows = trig.load_rows(INDEX)
    n_rows = len(re.findall(r"^\| [A-Z]+-\d+ \|", INDEX.read_text(), re.M))
    assert len(rows) == n_rows == 70


def test_known_fixture_nominates_expected_ids():
    r = run(FIXTURES / "01-basic-n-plus-one" / "target.py", FIXTURES / "01-basic-n-plus-one" / "templates")
    assert r.returncode == 0, r.stderr
    got = ids(r.stdout)
    assert {"FETCH-001", "FETCH-030", "FETCH-010", "IDX-001"} <= set(got)
    line = next(ln for ln in r.stdout.splitlines() if ln.startswith("FETCH-030 "))
    assert "critical fetching.md 372 40 |" in line and "orders.html:1" in line


def test_critical_rows_always_nominated_and_marked():
    r = run(FIXTURES / "09-non-django-target" / "target.py")
    assert r.returncode == 0
    crit = [ln for ln in r.stdout.splitlines() if " critical " in ln]
    assert crit and all("always opened" in ln or ".py:" in ln for ln in crit)
    assert {"FETCH-030", "FETCH-031", "WRITE-001"} <= set(ids(r.stdout))


def test_output_is_deterministic():
    f = FIXTURES / "06-audit-framework-bypass"
    assert run(f).stdout == run(f).stdout


def test_groups_filter_restricts_and_rejects_unknown():
    r = run(FIXTURES / "05-missing-index-postgres" / "target.py", "--groups", "indexes")
    assert r.returncode == 0
    assert all(c.startswith("IDX-") for c in ids(r.stdout))
    bad = run(FIXTURES / "05-missing-index-postgres" / "target.py", "--groups", "nope")
    assert bad.returncode == 2 and "unknown group" in bad.stderr


def test_missing_path_errors_cleanly(tmp_path):
    r = run(tmp_path / "absent.py")
    assert r.returncode == 2 and "no such file" in r.stderr and "Traceback" not in r.stderr


def test_bad_regex_in_index_errors_with_code(tmp_path):
    bad = tmp_path / "INDEX.md"
    bad.write_text("| AGG-001 | high |  | t | `(unclosed` | aggregation.md L1-5 |\n")
    src = tmp_path / "t.py"
    src.write_text("x = 1\n")
    r = run(src, "--index", bad)
    assert r.returncode == 2 and "AGG-001" in r.stderr and "bad trigger regex" in r.stderr


def test_missing_or_empty_index_errors(tmp_path):
    src = tmp_path / "t.py"
    src.write_text("x = 1\n")
    assert run(src, "--index", tmp_path / "nope.md").returncode == 2
    empty = tmp_path / "INDEX.md"
    empty.write_text("# nothing\n")
    r = run(src, "--index", empty)
    assert r.returncode == 2 and "no check rows" in r.stderr
