from pathlib import Path

import pytest

from scripts import extract_ts
from scripts.diff import analyse
from scripts.index import ensure_view
from scripts.query import Snippets, sig_drift
from scripts.resolve import ViewIndex
from scripts.store import Store
from scripts.views import base_view, worktree_view

pytestmark = pytest.mark.skipif(extract_ts.unavailable_reason() is not None,
                                reason=f"TS extractor unavailable: {extract_ts.unavailable_reason()}")

MONEY = (
    "export function refund(amount: number, reason?: string): number {\n"
    "  // keep in sync with ledger\n"
    "  if (amount < 0) {\n"
    "    throw new Error('negative');\n"
    "  }\n"
    "  return amount;\n"
    "}\n"
    "export default refund;\n"
)
USE = (
    "import { refund as r } from '../lib/money';\n"
    "import * as M from '../lib/money';\n"
    "import ts from 'typescript';\n"
    "import { fee } from '@lib/fees';\n\n"
    "export class Svc extends Base {\n"
    "  run(): number {\n"
    "    this.helper();\n"
    "    M.refund(1, 'x', 3);\n"
    "    fee();\n"
    "    return r(2);\n"
    "  }\n"
    "  helper(): void {}\n"
    "}\n"
)
FILES = {
    "src/lib/money.ts": MONEY,
    "src/lib/fees.ts": "export function fee(): number {\n  return 1;\n}\n",
    "src/app/use.ts": USE,
    "src/app/use.test.ts": "import { Svc } from './use';\n\ntest('runs', () => {\n  new Svc().run();\n});\n",
    "tsconfig.json": '{\n  // paths\n  "compilerOptions": {"baseUrl": ".", "paths": {"@lib/*": ["src/lib/*"]},},\n}\n',
    "py/money.py": "def refund(amount):\n    return amount\n",
}


def extract(path: str, text: str):
    return extract_ts.extract_batch([(path, "sha", text.encode())], timeout_s=30)[0]


def test_symbols_signatures_and_default_alias() -> None:
    f = extract("src/lib/money.ts", MONEY)
    by = {s.qualname: s for s in f.symbols}
    refund = by["ts:src/lib/money.refund"]
    assert refund.kind == "function"
    assert [(p.name, p.kind, p.has_default) for p in refund.signature] == [
        ("amount", "pos", False), ("reason", "pos", True)]
    assert by["ts:src/lib/money.default"].alias_of == "ts:src/lib/money.refund"


def test_refs_imports_namespaces_this_and_bare_specifiers() -> None:
    f = extract("src/app/use.ts", USE)
    calls = {(r.src, r.target, r.args.positional if r.args else None)
             for r in f.refs if r.kind == "call"}
    assert ("ts:src/app/use.Svc.run", "ts:src/app/use.Svc.helper", 0) in calls
    assert ("ts:src/app/use.Svc.run", "ts:src/lib/money.refund", 3) in calls
    assert ("ts:src/app/use.Svc.run", "ts:src/lib/money.refund", 1) in calls
    assert ("ts:src/app/use.Svc.run", "ts-bare:@lib/fees|fee", 0) in calls
    aliases = {s.qualname: s.alias_of for s in f.symbols if s.kind == "alias"}
    assert aliases["ts:src/app/use.ts"] == "ts-bare:typescript|default"
    assert not any("Base" in r.target for r in f.refs)


def test_guards_comments_and_test_files() -> None:
    f = extract("src/lib/money.ts", MONEY)
    assert {(g.kind, g.text) for g in f.guards} == {
        ("if", "amount < 0"), ("raise", "new Error('negative')")}
    comment = next(x for x in f.literals if x.kind == "comment")
    assert (comment.text, comment.symbol) == ("keep in sync with ledger", "ts:src/lib/money.refund")
    t = extract("src/app/use.test.ts", FILES["src/app/use.test.ts"])
    assert t.symbols and all(s.is_test for s in t.symbols)


def test_syntax_error_is_recorded() -> None:
    f = extract("bad.ts", "function (:\n")
    assert not f.parsed_ok and f.error is not None and f.error.startswith("SyntaxError: line 1")


def test_end_to_end_callers_tsconfig_paths_and_drift(tmp_path: Path, make_repo) -> None:
    repo = make_repo(FILES)
    sha = repo.git("rev-parse", "HEAD").strip()
    repo.write({"src/lib/money.ts": MONEY.replace(", reason?: string", "")})
    st = Store(tmp_path / "i.db")
    head, base = worktree_view(repo.root), base_view(repo.root, sha)
    assert ensure_view(st, head).skipped == {}
    ensure_view(st, base)
    vi = ViewIndex(st, head)
    srcs = {r.src for _, r, _ in vi.callers("ts:src/lib/money.refund")}
    assert "ts:src/app/use.Svc.run" in srcs
    assert all(s.startswith("ts:") for s in srcs)  # py/money.py's refund never matches
    assert {r.src for _, r, _ in vi.callers("ts:src/lib/fees.fee")} == {"ts:src/app/use.Svc.run"}
    tests = {r.src for _, r, _ in vi.callers_with_class("ts:src/app/use.Svc.run")}
    assert "ts:src/app/use.test" in tests
    d = analyse(st, base, head, vi)
    drift = sig_drift(vi, d.signatures, Snippets(head))
    assert any(x.verdict == "error" and "3 positional" in x.reason for x in drift)


def test_ts_is_indexed_in_chunks_so_a_deadline_keeps_progress(
        tmp_path: Path, make_repo, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import index
    repo = make_repo({"a.ts": "export const a = 1;\n", "b.ts": "export const b = 2;\n"})
    real = extract_ts.extract_batch
    calls: list[int] = []

    def flaky(items: list[tuple[str, str, bytes]], timeout_s: float) -> list:
        calls.append(len(items))
        if len(calls) > 1:
            raise extract_ts.DeadlineExceeded("simulated")
        return real(items, timeout_s)

    monkeypatch.setattr(index, "TS_CHUNK", 1)
    monkeypatch.setattr(extract_ts, "extract_batch", flaky)
    report = ensure_view(Store(tmp_path / "i.db"), worktree_view(repo.root))
    assert calls == [1, 1] and report.parsed == 1
    assert list(report.skipped.values()) == ["deadline"]


def test_anonymous_default_function_has_no_self_alias() -> None:
    f = extract("a.ts", "export default function () {}\n")
    assert not any(s.kind == "alias" and s.alias_of == s.qualname for s in f.symbols)


def test_this_parameter_is_not_a_positional_parameter() -> None:
    f = extract("w.ts", "export function f(this: Window, a: number): number { return a; }\n")
    sig = next(s for s in f.symbols if s.qualname.endswith(".f")).signature
    assert [p.name for p in sig] == ["a"]
