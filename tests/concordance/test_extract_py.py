from scripts.extract_py import extract_python, module_name

SRC = '''\
"""Module doc."""
from .models import Loan as L
from pkg.events import DomainEvent
import json

TABLE = "scenario_events"


class Repo(Base):
    def save(self, loan, *, flush=True):
        # FK order matters here
        if loan is None:
            raise ValueError("no loan")
        self.validate(loan)
        L.check(loan, strict=True)
        return json.dumps(DomainEvent)


def helper(a, b=1):
    return Repo().save(a, flush=False)
'''


def facts():
    return extract_python("src/pkg/repo.py", "sha1", SRC.encode())


def test_module_name_strips_src_and_init() -> None:
    assert module_name("src/pkg/repo.py") == "pkg.repo"
    assert module_name("pkg/__init__.py") == "pkg"
    assert module_name("__init__.py") == "__root__"


def test_symbols_signature_and_aliases() -> None:
    by = {s.qualname: s for s in facts().symbols}
    assert by["pkg.repo"].kind == "module"
    assert by["pkg.repo.Repo"].kind == "class"
    save = by["pkg.repo.Repo.save"]
    assert save.kind == "method" and (save.line_start, save.line_end) == (10, 16)
    assert [(p.name, p.kind, p.has_default) for p in save.signature] == [
        ("self", "pos", False), ("loan", "pos", False), ("flush", "kwonly", True)]
    assert by["pkg.repo.L"].kind == "alias" and by["pkg.repo.L"].alias_of == "pkg.models.Loan"
    assert by["pkg.repo.json"].alias_of == "json"


def test_refs_resolve_imports_self_and_unknown_receivers() -> None:
    refs = facts().refs
    calls = {(r.src, r.target) for r in refs if r.kind == "call"}
    assert ("pkg.repo.Repo.save", "pkg.repo.Repo.validate") in calls
    assert ("pkg.repo.Repo.save", "pkg.models.Loan.check") in calls
    assert ("pkg.repo.Repo.save", "json.dumps") in calls
    assert ("pkg.repo.helper", "?.save") in calls
    assert ("pkg.repo.helper", "pkg.repo.Repo") in calls
    names = {(r.src, r.target) for r in refs if r.kind == "name"}
    assert ("pkg.repo.Repo.save", "pkg.events.DomainEvent") in names
    assert not any("Base" in r.target or "ValueError" in r.target for r in refs)


def test_call_shapes() -> None:
    refs = facts().refs
    check = next(r for r in refs if r.target == "pkg.models.Loan.check")
    assert check.args is not None
    assert (check.args.positional, check.args.keywords) == (1, ("strict",))
    save = next(r for r in refs if r.target == "?.save")
    assert save.args is not None and save.args.keywords == ("flush",)


def test_decorators_and_bases() -> None:
    src = (
        "from functools import cache\nimport abc\n\n"
        "class A(abc.ABC):\n    @cache\n    def f(self):\n        pass\n"
    )
    refs = extract_python("m.py", "s", src.encode()).refs
    assert ("m.A.f", "functools.cache", "decorator") in {(r.src, r.target, r.kind) for r in refs}
    assert ("m.A", "abc.ABC", "inherit") in {(r.src, r.target, r.kind) for r in refs}


def test_guards_literals_comments() -> None:
    f = facts()
    assert {(g.kind, g.text) for g in f.guards} >= {
        ("if", "loan is None"), ("raise", "ValueError('no loan')")}
    strings = {x.text for x in f.literals if x.kind == "string"}
    assert "scenario_events" in strings and "Module doc." not in strings
    comment = next(x for x in f.literals if x.kind == "comment")
    assert (comment.text, comment.symbol) == ("FK order matters here", "pkg.repo.Repo.save")


def test_relative_import_from_package_init() -> None:
    f = extract_python("src/pkg/__init__.py", "s", b"from .events import DomainEvent\n")
    alias = next(s for s in f.symbols if s.kind == "alias")
    assert (alias.qualname, alias.alias_of) == ("pkg.DomainEvent", "pkg.events.DomainEvent")


def test_test_files_mark_every_symbol_as_test() -> None:
    f = extract_python("tests/test_repo.py", "s", b"def test_x():\n    helper()\n")
    assert f.symbols and all(s.is_test for s in f.symbols)


def test_bad_input_is_a_recorded_failure_not_a_crash() -> None:  # Review Focus 2
    bad = extract_python("a.py", "s", b"\xff\xfe def")
    assert not bad.parsed_ok and bad.error is not None and "UTF-8" in bad.error
    nul = extract_python("b.py", "s", b"x = 1\x00\n")
    assert not nul.parsed_ok
    syn = extract_python("c.py", "s", b"def (:\n")
    assert not syn.parsed_ok and syn.error is not None
    assert syn.error.startswith("SyntaxError: line 1")
