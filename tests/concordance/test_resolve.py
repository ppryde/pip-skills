from pathlib import Path

import pytest

from scripts.index import ensure_view
from scripts.resolve import Resolved, ViewIndex
from scripts.store import Store
from scripts.views import worktree_view

FILES = {
    "src/pkg/__init__.py": "from .events import DomainEvent\n",
    "src/pkg/events.py": "class DomainEvent:\n    def apply(self):\n        pass\n",
    "src/pkg/svc.py": (
        "from pkg import DomainEvent\n"
        "from pkg.events import DomainEvent as DE\n\n"
        "def _refund_partial(x):\n    return DE()\n\n"
        "def run():\n    DomainEvent().apply()\n    return _refund_partial(1)\n"
    ),
    "services/api/ledger/core.py": "def append_events():\n    pass\n",
    "services/api/ledger/use.py": (
        "from ledger.core import append_events\n\ndef go():\n    append_events()\n"),
    "tests/test_svc.py": "from pkg.svc import run\n\ndef test_run():\n    run()\n",
}


@pytest.fixture
def vi(tmp_path: Path, make_repo) -> ViewIndex:
    repo = make_repo(FILES)
    st = Store(tmp_path / "i.db")
    view = worktree_view(repo.root)
    ensure_view(st, view)
    return ViewIndex(st, view)


def callers_of(vi: ViewIndex, q: str) -> set[tuple[str, str]]:
    return {(ref.src, conf) for _, ref, conf in vi.callers(q)}


def test_reexport_alias_resolves(vi: ViewIndex) -> None:
    assert vi.resolve("pkg.DomainEvent") == Resolved("pkg.events.DomainEvent", "exact")


def test_private_name_and_aliased_import(vi: ViewIndex) -> None:
    assert ("pkg.svc.run", "exact") in callers_of(vi, "pkg.svc._refund_partial")
    assert ("pkg.svc._refund_partial", "exact") in callers_of(vi, "pkg.events.DomainEvent")


def test_package_root_found_by_suffix(vi: ViewIndex) -> None:
    r = vi.resolve("ledger.core.append_events")
    assert r == Resolved("services.api.ledger.core.append_events", "exact")
    assert vi.canonical("ledger.core.gone") == "services.api.ledger.core.gone"


def test_external_and_unresolved(vi: ViewIndex) -> None:
    assert vi.resolve("json.dumps").confidence == "external"
    assert vi.resolve("pkg.svc.nope").confidence == "unresolved"


def test_method_on_unknown_receiver_is_inferred(vi: ViewIndex) -> None:
    assert ("pkg.svc.run", "inferred") in callers_of(vi, "pkg.events.DomainEvent.apply")


def test_test_symbols_are_marked(vi: ViewIndex) -> None:
    assert vi.is_test("tests.test_svc.test_run") and not vi.is_test("pkg.svc.run")
    assert vi.path_of("pkg.svc.run") == "src/pkg/svc.py"


def test_lookup_suffix_and_did_you_mean(vi: ViewIndex) -> None:
    assert vi.lookup("svc.run").target == "pkg.svc.run"
    miss = vi.lookup("_refund_partail")
    assert miss.target is None and "pkg.svc._refund_partial" in miss.candidates


def test_ambiguous_method_name(tmp_path: Path, make_repo) -> None:
    repo = make_repo({
        "a.py": "class A:\n    def save(self):\n        pass\n",
        "b.py": "class B:\n    def save(self):\n        pass\n",
        "c.py": "def go(x):\n    x.save()\n",
    })
    st = Store(tmp_path / "i.db")
    view = worktree_view(repo.root)
    ensure_view(st, view)
    vi = ViewIndex(st, view)
    r = vi.resolve("?.save")
    assert r.confidence == "ambiguous" and set(r.candidates) == {"a.A.save", "b.B.save"}
    assert ("c.go", "ambiguous") in callers_of(vi, "a.A.save")


def test_class_callers_count_for_init(tmp_path: Path, make_repo) -> None:
    repo = make_repo({"m.py": "class K:\n    def __init__(self, a):\n        pass\n\n"
                              "def mk():\n    return K(1)\n"})
    st = Store(tmp_path / "i.db")
    view = worktree_view(repo.root)
    ensure_view(st, view)
    vi = ViewIndex(st, view)
    assert {r.src for _, r, _ in vi.callers_with_class("m.K.__init__")} == {"m.mk"}


def test_duplicate_qualnames_tolerated(tmp_path: Path, make_repo) -> None:
    repo = make_repo({
        "m.py": (
            "import os\nimport os.path\n\n"
            "class C:\n"
            "    @property\n    def v(self):\n        return 1\n\n"
            "    @v.setter\n    def v(self, x):\n        pass\n\n"
            "def go(c):\n    return C.v\n"),
    })
    st = Store(tmp_path / "i.db")
    view = worktree_view(repo.root)
    ensure_view(st, view)
    vi = ViewIndex(st, view)
    r = vi.resolve("m.C.v")
    assert r == Resolved("m.C.v", "exact")
    assert vi.lookup("m.C.v") == Resolved("m.C.v", "exact")
    assert vi.lookup("C.v").confidence == "inferred"
    assert {ref.src for _, ref, _ in vi.callers("m.C.v")} <= {"m.go"}
    assert vi.resolve("m.os").confidence in {"external", "exact"}
