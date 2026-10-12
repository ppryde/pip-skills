import importlib.util
from pathlib import Path

BENCH = Path(__file__).resolve().parent / "bench" / "make_case.py"
spec = importlib.util.spec_from_file_location("make_case", BENCH)
assert spec and spec.loader
make_case = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_case)


def test_plant_reverse_restores_the_bug_but_keeps_the_tests(tmp_path: Path, make_repo) -> None:
    repo = make_repo({"app.py": "def f():\n    return 1\n", "tests/test_app.py": "x = 0\n"})
    repo.write({"app.py": "def f():\n    return 2  # fixed\n",
                "tests/test_app.py": "x = 1  # new test\n"})
    fix = repo.commit("fix")
    case = make_case.build_case(repo.root, tmp_path / "case", plant_reverse=fix)
    assert (case / "app.py").read_text() == "def f():\n    return 1\n"
    assert (case / "tests/test_app.py").read_text() == "x = 1  # new test\n"
    log = make_case._git(case, "log", "--format=%s")
    assert log.split() == ["pr", "base"]


def test_range_case(tmp_path: Path, make_repo) -> None:
    repo = make_repo({"a.py": "a = 1\n"})
    base = repo.git("rev-parse", "HEAD").strip()
    repo.write({"a.py": "a = 2\n"})
    head = repo.commit("change")
    case = make_case.build_case(repo.root, tmp_path / "case", range_=(base, head))
    assert make_case._git(case, "diff", "HEAD~1", "HEAD", "--stat").strip() != ""
    assert (case / "a.py").read_text() == "a = 2\n"


def test_range_case_drops_files_deleted_in_head(tmp_path: Path, make_repo) -> None:
    repo = make_repo({"a.py": "a = 1\n", "gone.py": "g = 1\n"})
    base = repo.git("rev-parse", "HEAD").strip()
    repo.write({"gone.py": None})
    head = repo.commit("delete")
    case = make_case.build_case(repo.root, tmp_path / "case", range_=(base, head))
    assert not (case / "gone.py").exists()
    assert (case / "a.py").exists()


def test_patch_case(tmp_path: Path, make_repo) -> None:
    repo = make_repo({"a.py": "a = 1\n"})
    sha = repo.git("rev-parse", "HEAD").strip()
    patch = tmp_path / "h.patch"
    patch.write_text(
        "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a = 1\n+a = 3\n", encoding="utf-8"
    )
    case = make_case.build_case(repo.root, tmp_path / "case", patch=patch, on=sha)
    assert (case / "a.py").read_text() == "a = 3\n"
    assert make_case._git(case, "log", "--format=%s").split() == ["pr", "base"]


def test_no_mode_exits(tmp_path: Path, make_repo) -> None:
    import pytest

    repo = make_repo({"a.py": "a = 1\n"})
    with pytest.raises(SystemExit):
        make_case.build_case(repo.root, tmp_path / "case")
