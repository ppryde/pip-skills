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


def test_empty_groups_is_an_error_not_no_filter():
    for arg in ("--groups=", "--groups=,"):
        r = run(FIXTURES / "05-missing-index-postgres" / "target.py", arg)
        assert r.returncode == 2 and "--groups is empty" in r.stderr


def test_write_005_needs_the_listener_file_fixture_06_layout():
    f = FIXTURES / "06-audit-framework-bypass"
    assert "@receiver" in (f / "signals.py").read_text()
    without = run(f / "target.py", f / "settings.py")
    assert "PAT-070" in ids(without.stdout) and "WRITE-005" not in ids(without.stdout)
    with_listeners = run(f / "target.py", f / "settings.py", f / "signals.py")
    assert "WRITE-005" in ids(with_listeners.stdout)


# ---- round 2: long lines, skipped files, pruning -------------------------------


def test_one_big_line_file_scans_fast(tmp_path):
    import time

    f = tmp_path / "blob.txt"
    f.write_text("a" * 1_900_000)
    t = time.monotonic()
    r = run(f)
    assert r.returncode == 0, r.stderr
    assert time.monotonic() - t < 1.5  # interpreter start-up included
    assert "truncated:" in r.stdout and "blob.txt" in r.stdout


def test_every_trigger_survives_a_100kb_adversarial_line():
    import time

    rows = trig.load_rows(INDEX)
    shapes = ["a" * 100_000, "a.b " * 25_000, "x.y or " * 15_000, "(" * 100_000, " " * 100_000, "a_1." * 25_000]
    for r in rows:
        for line in shapes:
            t = time.monotonic()
            r["rx"].search(line[: trig.MAX_LINE])  # what scan() feeds a trigger
            assert time.monotonic() - t < 0.2, (r["id"], line[:10])
    agg = next(r for r in rows if r["id"] == "AGG-011")
    t = time.monotonic()
    agg["rx"].search("a" * 100_000)  # even the untruncated pattern is linear now
    assert time.monotonic() - t < 0.5


def test_skipped_files_are_listed_and_not_counted(tmp_path):
    (tmp_path / "ok.py").write_text("x = 1\n")
    (tmp_path / "bin.py").write_bytes(b"\0\1\2 data")
    big = tmp_path / "big.py"
    big.write_bytes(b"#" * (trig.MAX_BYTES + 1))
    r = run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert f"skipped: {big} (over 2 MB)" in r.stdout
    assert f"skipped: {tmp_path / 'bin.py'} (binary)" in r.stdout
    assert "over 1 file(s)" in r.stdout


def test_directory_scan_prunes_vendor_and_migration_dirs(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "views.py").write_text("x = 1\n")
    for d in (".venv", "node_modules", "migrations", ".git", "__pycache__"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "junk.py").write_text("x = 1\n")
    r = run(tmp_path)
    assert "over 1 file(s)" in r.stdout


def test_explicit_file_in_pruned_dir_is_still_scanned(tmp_path):
    (tmp_path / "migrations").mkdir()
    f = tmp_path / "migrations" / "0001.py"
    f.write_text("x = 1\n")
    assert "over 1 file(s)" in run(f).stdout
