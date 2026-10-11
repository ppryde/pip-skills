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
    hits = removed_contract(vi, d.removed, snips)
    found = {(h.item.kind, h.item.name, h.hit.symbol) for h in hits}
    assert ("symbol", "old_helper", "app.api.handle") in found
    assert ("param", "partial", "app.api.handle") in found
    assert ("guard", "if", "tests.test_svc.test_rejects_zero") in found
    param_hit = next(h for h in hits if h.item.kind == "param")
    assert param_hit.hit.confidence == "exact" and "partial=True" in param_hit.hit.snippet


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
