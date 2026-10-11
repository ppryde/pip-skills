from pathlib import Path

from scripts.facts import (
    CallShape,
    FileFacts,
    Guard,
    Literal,
    Param,
    Ref,
    Symbol,
    file_facts_from_dict,
)
from scripts.store import Store


def sample(path: str = "a.py", sha: str = "s1") -> FileFacts:
    return FileFacts(
        path, sha, "python", True, None,
        [
            Symbol("a", "module", 1, 3, False),
            Symbol("a.f", "function", 1, 2, False, (Param("x", "pos", False),)),
            Symbol("a.L", "alias", 1, 1, False, None, "b.Loan"),
        ],
        [Ref("a.f", "b.g", "call", 2, CallShape(1, ("k",), False, False))],
        [Literal("string", "hello", 2, "a.f")],
        [Guard("a.f", "if", 2, "x")],
    )


def test_roundtrip_and_idempotent_insert(tmp_path: Path) -> None:
    st = Store(tmp_path / "i.db")
    assert st.put_facts(sample()) is True
    assert st.put_facts(sample()) is False  # another writer already stored it
    assert st.file_facts("a.py", "s1") == sample()
    assert st.has_facts([("a.py", "s1"), ("a.py", "nope")]) == {("a.py", "s1")}


def test_failed_parse_roundtrips(tmp_path: Path) -> None:
    st = Store(tmp_path / "i.db")
    st.put_facts(FileFacts("bad.py", "s", "python", False, "SyntaxError: line 1: x"))
    back = st.file_facts("bad.py", "s")
    assert back is not None and not back.parsed_ok and back.error == "SyntaxError: line 1: x"


def test_views_joins_and_coverage(tmp_path: Path) -> None:
    st = Store(tmp_path / "i.db")
    st.put_facts(sample())
    st.put_facts(FileFacts("c.py", "s3", "python", False, "boom"))
    st.set_view("wt-1", "wt", "/r", None, {"a.py": "s1", "b.py": "s2", "c.py": "s3"})
    assert st.view_files("wt-1") == {"a.py": "s1", "b.py": "s2", "c.py": "s3"}
    assert [s.qualname for _, s in st.view_symbols("wt-1")] == ["a", "a.f", "a.L"]
    assert [(p, r.target) for p, r in st.view_refs("wt-1")] == [("a.py", "b.g")]
    cov = st.coverage("wt-1")
    assert (cov.total, cov.failed, cov.not_indexed) == (3, [("c.py", "boom")], ["b.py"])
    assert st.literal_occurrences("wt-1", ["hello"]) == [("hello", "a.py", 2)]
    st.set_view("wt-1", "wt", "/r", None, {"a.py": "s1"})  # replaces, not appends
    assert st.view_files("wt-1") == {"a.py": "s1"}


def test_orphan_facts_are_deleted_with_their_children(tmp_path: Path) -> None:
    st = Store(tmp_path / "i.db")
    st.put_facts(sample())
    st.set_view("wt-1", "wt", "/r", None, {"a.py": "s1"})
    assert st.delete_orphan_facts() == 0
    st.delete_view("wt-1")
    assert st.delete_orphan_facts() == 1
    assert st.file_facts("a.py", "s1") is None
    for table in ("symbols", "refs", "literals", "guards"):
        assert st.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_meta(tmp_path: Path) -> None:
    st = Store(tmp_path / "i.db")
    assert st.meta_get("schema_version") == "1"
    st.meta_set("last_gc", "5")
    assert st.meta_get("last_gc") == "5"
    assert not hasattr(st, "record_event")


def test_file_facts_from_dict() -> None:
    d = {
        "path": "x.ts", "lang": "typescript", "parsed_ok": True, "error": None,
        "symbols": [{"qualname": "ts:x.f", "kind": "function", "line_start": 1, "line_end": 2,
                     "is_test": False, "signature": [["a", "pos", False]], "alias_of": None}],
        "refs": [{"src": "ts:x.f", "target": "ts:y.g", "kind": "call", "line": 2,
                  "args": {"positional": 2, "keywords": [], "star": False, "dstar": False}}],
        "literals": [{"kind": "comment", "text": "hi", "line": 1, "symbol": "ts:x.f"}],
        "guards": [{"symbol": "ts:x.f", "kind": "raise", "line": 2, "text": "new Error()"}],
    }
    ff = file_facts_from_dict(d, "sha")
    assert ff.blob_sha == "sha" and ff.symbols[0].signature == (Param("a", "pos", False),)
    assert ff.refs[0].args == CallShape(2, (), False, False)
