from pathlib import Path

from scripts.diff import DiffResult, analyse
from scripts.index import ensure_view
from scripts.resolve import ViewIndex
from scripts.store import Store
from scripts.views import base_view, worktree_view


def run(tmp_path: Path, make_repo, base: dict[str, str], edits: dict[str, str | None],
        name: str = "repo") -> DiffResult:
    repo = make_repo(base, name=name)
    sha = repo.git("rev-parse", "HEAD").strip()
    repo.write(edits)  # left uncommitted on purpose: the head view must see dirty edits
    st = Store(tmp_path / f"{name}.db")
    head, bview = worktree_view(repo.root), base_view(repo.root, sha)
    ensure_view(st, head)
    ensure_view(st, bview)
    return analyse(st, bview, head, ViewIndex(st, head))


def removed(d: DiffResult) -> set[tuple[str, str, str]]:
    return {(r.kind, r.qualname, r.name) for r in d.removed}


def test_removed_symbol(tmp_path: Path, make_repo) -> None:
    d = run(tmp_path, make_repo,
            {"m.py": "def keep():\n    gone()\n\n\ndef gone():\n    pass\n"},
            {"m.py": "def keep():\n    gone()\n"})
    assert ("symbol", "m.gone", "gone") in removed(d)
    assert d.changed_files == ["m.py"]


def test_moving_to_another_module_is_a_removal_but_editing_is_not(tmp_path: Path,
                                                                   make_repo) -> None:
    d = run(tmp_path, make_repo,
            {"a.py": "def f():\n    pass\n", "b.py": "x = 1\n"},
            {"a.py": "y = 2\n", "b.py": "x = 1\n\n\ndef f():\n    pass\n"})
    assert ("symbol", "a.f", "f") in removed(d)  # importers of a.f break; b.f is a new qualname
    d2 = run(tmp_path, make_repo,
             {"pkg/a.py": "def f():\n    pass\n"},
             {"pkg/a.py": "def f():\n    return 1\n"}, name="two")
    assert not any(r.kind == "symbol" for r in d2.removed)


def test_removed_param_and_signature_change(tmp_path: Path, make_repo) -> None:
    d = run(tmp_path, make_repo,
            {"m.py": "def f(a, flush=True):\n    return a\n"},
            {"m.py": "def f(a):\n    return a\n"})
    assert ("param", "m.f", "flush") in removed(d)
    assert [s.qualname for s in d.signatures] == ["m.f"]


def test_removed_guard_and_decorator(tmp_path: Path, make_repo) -> None:
    d = run(tmp_path, make_repo,
            {"m.py": "from functools import cache\n\n\n@cache\ndef f(x):\n"
                     "    if x is None:\n        raise ValueError('x')\n    return x\n"},
            {"m.py": "from functools import cache\n\n\ndef f(x):\n    return x\n"})
    kinds = {(r.kind, r.name, r.text) for r in d.removed}
    assert ("guard", "if", "x is None") in kinds
    assert ("guard", "raise", "ValueError('x')") in kinds
    assert ("decorator", "functools.cache", "functools.cache") in kinds


def test_touched_classification(tmp_path: Path, make_repo) -> None:
    d = run(tmp_path, make_repo,
            {"m.py": "def a(x):\n    y = x + 1\n    return y\n\n\ndef b(x):\n    return x\n"},
            {"m.py": "def a(x):\n    z = x + 1\n    return z\n\n\ndef b(x):\n    return -x\n\n\n"
                     "def c():\n    pass\n"})
    by = {t.qualname: t for t in d.touched}
    assert not by["m.a"].behaviour_changed
    assert by["m.b"].behaviour_changed and not by["m.b"].is_new
    assert by["m.c"].is_new


def test_literals_comments_and_reorders(tmp_path: Path, make_repo) -> None:
    d = run(tmp_path, make_repo,
            {"m.py": "SQL = 'DELETE FROM a'\n\n\ndef f():\n    # order matters\n    one()\n    two()\n"},
            {"m.py": "SQL = 'DELETE FROM b'\n\n\ndef f():\n    two()\n    one()\n"})
    assert {(x.change, x.text) for x in d.literals} == {
        ("removed", "DELETE FROM a"), ("added", "DELETE FROM b")}
    assert [(c.text, c.symbol) for c in d.removed_comments] == [("order matters", "m.f")]
    assert [r.qualname for r in d.reorders] == ["m.f"]


def test_duplicate_qualnames_do_not_crash(tmp_path: Path, make_repo) -> None:
    src = ("class C:\n    @property\n    def v(self):\n        return 1\n\n"
           "    @v.setter\n    def v(self, x):\n        pass\n")
    d = run(tmp_path, make_repo, {"m.py": src}, {"m.py": src.replace("pass", "print(x)")},
            name="dup")
    assert d.changed_files == ["m.py"]


def test_decorator_swap_touches_the_method(tmp_path: Path, make_repo) -> None:
    src = ("from functools import cache, lru_cache\n\n\nclass C:\n    @cache\n"
           "    def m(self):\n        return 1\n")
    d = run(tmp_path, make_repo, {"m.py": src}, {"m.py": src.replace("@cache", "@lru_cache")},
            name="deco")
    by = {t.qualname: t for t in d.touched}
    assert by["m.C.m"].behaviour_changed


def test_removed_decorator_touches_the_function(tmp_path: Path, make_repo) -> None:
    src = "import functools\n\n\n@functools.cache\ndef f():\n    return 1\n"
    d = run(tmp_path, make_repo, {"m.py": src}, {"m.py": src.replace("@functools.cache\n", "")},
            name="decorm")
    assert {t.qualname for t in d.touched if t.behaviour_changed} == {"m.f"}
