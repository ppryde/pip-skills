from pathlib import Path

import pytest

from scripts.diff import analyse
from scripts.facts import CallShape, Param
from scripts.index import ensure_view
from scripts.query import (
    Snippets,
    callers,
    check_call,
    guarding_tests,
    literal_hits,
    removed_contract,
    sig_drift,
    untested_changes,
)
from scripts.resolve import ViewIndex
from scripts.store import Store
from scripts.views import base_view, worktree_view

BASE = {
    "app/svc.py": (
        "def refund(loan, amount, *, partial=False):\n"
        "    if amount <= 0:\n"
        "        raise ValueError('amount')\n"
        "    return amount\n\n\n"
        "def old_helper():\n    return 1\n"
    ),
    "app/api.py": (
        "from app.svc import refund, old_helper\n\n\n"
        "def handle(loan):\n    old_helper()\n    return refund(loan, 5, partial=True)\n"
    ),
    "tests/test_svc.py": (
        "import pytest\nfrom app.svc import refund\nfrom app.api import handle\n\n\n"
        "def test_rejects_zero():\n    with pytest.raises(ValueError):\n"
        "        refund(None, 0)\n\n\n"
        "def test_handle():\n    handle(None)\n"
    ),
    "app/sql.py": "Q = 'DELETE FROM scenario_events'\n",
    "app/other.py": "R = 'DELETE FROM scenario_events'\n",
}
HEAD = {
    "app/svc.py": "def refund(loan, amount):\n    return amount\n",
    "app/sql.py": "Q = 'DELETE FROM events'\n",
}


@pytest.fixture
def world(tmp_path: Path, make_repo):
    repo = make_repo(BASE)
    sha = repo.git("rev-parse", "HEAD").strip()
    repo.write(dict(HEAD))
    st = Store(tmp_path / "i.db")
    head, bview = worktree_view(repo.root), base_view(repo.root, sha)
    ensure_view(st, head)
    ensure_view(st, bview)
    vi = ViewIndex(st, head)
    return st, head, vi, analyse(st, bview, head, vi), Snippets(head)


def test_check_call_verdicts() -> None:
    sig = (Param("self", "pos", False), Param("a", "pos", False), Param("b", "kwonly", True))
    assert check_call(CallShape(1, (), False, False), sig, bound=True) is None
    assert check_call(CallShape(2, (), False, False), sig, bound=True)[0] == "error"
    assert "unknown keyword" in check_call(CallShape(1, ("c",), False, False), sig, True)[1]
    assert "missing required" in check_call(CallShape(0, (), False, False), sig, True)[1]
    assert check_call(CallShape(0, (), True, False), sig, True)[0] == "undecided"
    varkw = (Param("a", "pos", False), Param("kw", "varkw", True))
    assert check_call(CallShape(1, ("anything",), False, False), varkw, bound=False) is None


def test_callers_and_guarding_tests(world) -> None:
    _, _, vi, _, snips = world
    hits = callers(vi, "app.svc.refund", snips)
    assert [h.symbol for h in hits][:1] == ["app.api.handle"]  # non-test callers first
    assert "refund(loan, 5, partial=True)" in hits[0].snippet
    tests = {(t.qualname, t.hops) for t in guarding_tests(vi, "app.svc.refund")}
    assert ("tests.test_svc.test_rejects_zero", 1) in tests
    assert ("tests.test_svc.test_handle", 2) in tests


def test_removed_contract_hits(world) -> None:
    _, _, vi, d, snips = world
    groups = removed_contract(vi, d.removed, snips)
    by = {(g.kind, g.qualname): g for g in groups}
    assert [h.symbol for h in by[("symbol", "app.svc.old_helper")].sites] == ["app.api.handle"]
    param = by[("param", "app.svc.refund")]
    assert [h.symbol for h in param.sites] == ["app.api.handle"]
    assert param.sites[0].confidence == "exact" and "partial=True" in param.sites[0].snippet
    guard = by[("guard", "app.svc.refund")]
    assert "tests.test_svc.test_rejects_zero" in {h.symbol for h in guard.sites}


def test_sig_drift_flags_the_stale_call_site(world) -> None:
    _, _, vi, d, snips = world
    drift = sig_drift(vi, d.signatures, snips)
    errors = {(x.hit.symbol, x.verdict) for x in drift}
    assert ("app.api.handle", "error") in errors
    assert any("unknown keyword(s): partial" in x.reason for x in drift)


def test_untested_changes_only_for_behaviour_changes(tmp_path: Path, make_repo) -> None:
    repo = make_repo({"m.py": "def f(x):\n    return x\n\n\ndef g(x):\n    return x\n",
                      "tests/test_m.py": "from m import f\n\n\ndef test_f():\n    f(1)\n"})
    sha = repo.git("rev-parse", "HEAD").strip()
    repo.write({"m.py": "def f(x):\n    return -x\n\n\ndef g(x):\n    return -x\n"})
    st = Store(tmp_path / "i.db")
    head, bview = worktree_view(repo.root), base_view(repo.root, sha)
    ensure_view(st, head)
    ensure_view(st, bview)
    vi = ViewIndex(st, head)
    d = analyse(st, bview, head, vi)
    assert [t.qualname for t in untested_changes(vi, d.touched)] == ["m.g"]


def test_literal_hits_find_other_occurrences(world) -> None:
    st, head, _, d, _ = world
    hits = {(h.change.change, h.change.text): h.elsewhere
            for h in literal_hits(st, head.view_id, d.literals)}
    assert hits[("removed", "DELETE FROM scenario_events")] == [("app/other.py", 1)]
    assert hits[("added", "DELETE FROM events")] == []


def test_check_call_edge_cases() -> None:
    kwonly = (Param("a", "pos", False), Param("k", "kwonly", False))
    assert "keyword-only" in check_call(CallShape(1, (), False, False), kwonly, False)[1]
    assert check_call(CallShape(1, ("k",), False, False), kwonly, False) is None
    posonly = (Param("a", "posonly", False),)
    assert "unknown keyword" in check_call(CallShape(0, ("a",), False, False), posonly, False)[1]
    star = (Param("a", "pos", False), Param("rest", "vararg", True))
    assert check_call(CallShape(5, (), False, False), star, False) is None
    dflt = (Param("a", "pos", False), Param("b", "pos", True))
    assert check_call(CallShape(1, (), False, False), dflt, False) is None
    assert check_call(CallShape(1, (), False, True), dflt, False)[0] == "undecided"
    dup = check_call(CallShape(1, ("a",), False, False), dflt, False)
    assert dup == ("error", "argument `a` given twice")
    unbound = check_call(CallShape(3, (), False, False), dflt, False, binding_known=False)
    assert unbound is not None and unbound[0] == "undecided"
    assert check_call(CallShape(1, ("a",), False, False), dflt, False, False) is None


def _drift(tmp_path: Path, make_repo, base: dict[str, str], head: dict[str, str]):
    repo = make_repo(base)
    sha = repo.git("rev-parse", "HEAD").strip()
    repo.write(head)
    st = Store(tmp_path / "i.db")
    hv, bv = worktree_view(repo.root), base_view(repo.root, sha)
    ensure_view(st, hv)
    ensure_view(st, bv)
    vi = ViewIndex(st, hv)
    return sig_drift(vi, analyse(st, bv, hv, vi).signatures, Snippets(hv))


def test_sig_drift_valid_call_is_silent(tmp_path: Path, make_repo) -> None:
    base = {"m.py": "def f(a, b=1):\n    return a\n",
            "u.py": "from m import f\n\n\ndef go():\n    return f(1)\n"}
    head = {"m.py": "def f(a):\n    return a\n"}
    assert _drift(tmp_path, make_repo, base, head) == []


def test_sig_drift_inferred_target_is_undecided(tmp_path: Path, make_repo) -> None:
    base = {"m.py": "def refund(a, b):\n    return a\n",
            "u.py": "def go(client):\n    return client.refund(1, 2)\n"}
    head = {"m.py": "def refund(a):\n    return a\n"}
    drift = _drift(tmp_path, make_repo, base, head)
    assert drift and {d.verdict for d in drift} == {"undecided"}
    assert any("inferred by name" in d.reason for d in drift)


METHOD_BASE = {
    "m.py": "class C:\n    def go(self, a, b):\n        return a\n",
    "u.py": ("from m import C\n\n\ndef run(c: C):\n    c.go(1, 2)\n"
             "    C.go(c, 1, z=3)\n"),
}
METHOD_HEAD = {"m.py": "class C:\n    def go(self, a):\n        return a\n"}


def test_sig_drift_method_binding_unknown(tmp_path: Path, make_repo) -> None:
    drift = _drift(tmp_path, make_repo, METHOD_BASE, METHOD_HEAD)
    by_line = {d.hit.line: d for d in drift}
    assert 5 in by_line and by_line[5].verdict == "undecided"
    assert "binding unknown" in by_line[5].reason
    assert by_line[6].hit.confidence == "exact"  # explicit Class.method: target is certain
    assert by_line[6].verdict == "error" and "unknown keyword" in by_line[6].reason


def _world(tmp_path: Path, make_repo, base: dict[str, str], head: dict[str, str | None]):
    repo = make_repo(base)
    sha = repo.git("rev-parse", "HEAD").strip()
    repo.write(head)
    st = Store(tmp_path / "w.db")
    hv, bv = worktree_view(repo.root), base_view(repo.root, sha)
    ensure_view(st, hv)
    ensure_view(st, bv)
    vi = ViewIndex(st, hv)
    return vi, analyse(st, bv, hv, vi), Snippets(hv)


def test_removed_guards_group_into_one_row_per_function(tmp_path: Path, make_repo) -> None:
    guarded = (
        "def f(x):\n"
        + "".join(f"    if x == {i}:\n        raise ValueError('bad {i}')\n" for i in range(3))
        + "    return x\n"
    )
    tests = "from app import f\n\n\n" + "".join(
        f"def test_{i}():\n    f({i})\n\n\n" for i in range(4)
    ) + "def test_other():\n    assert ValueError\n"
    vi, d, snips = _world(tmp_path, make_repo,
                          {"app.py": guarded, "tests/test_f.py": tests},
                          {"app.py": "def f(x):\n    return x\n"})
    groups = removed_contract(vi, d.removed, snips)
    guard_groups = [g for g in groups if g.kind == "guard"]
    assert len(guard_groups) == 1  # six removed guards, one row
    g = guard_groups[0]
    assert g.qualname == "app.f" and len(g.removed) == 6
    assert sorted(h.symbol for h in g.sites) == [f"tests.test_f.test_{i}" for i in range(4)]
    # the unrelated test that merely names ValueError is not dragged in repo-wide
    assert not any(h.symbol == "tests.test_f.test_other" for h in g.sites)


def test_ambiguous_same_name_calls_are_not_counted_as_still_referencing(
        tmp_path: Path, make_repo) -> None:
    base = {
        "m.py": ("class A:\n    def save(self):\n        return 1\n\n\n"
                 "class B:\n    def save(self):\n        return 2\n\n\n"
                 "class C:\n    def save(self):\n        return 3\n"),
        "use.py": "def go(o):\n    o.save()\n    o.save()\n",
    }
    head = {"m.py": base["m.py"].replace(
        "class A:\n    def save(self):\n        return 1\n\n\n", "class A:\n    pass\n\n\n")}
    vi, d, snips = _world(tmp_path, make_repo, base, head)
    sym = [g for g in removed_contract(vi, d.removed, snips) if g.kind == "symbol"]
    assert [g.qualname for g in sym] == ["m.A.save"]
    assert sym[0].sites == []  # not a hard claim
    assert sym[0].ambiguous == 2  # named apart as low confidence
