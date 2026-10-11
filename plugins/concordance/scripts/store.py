"""concordance's SQLite store, and its one writer.

Facts are keyed by (path, blob_sha), so every worktree of a repo shares them. A view maps one
worktree (or one base commit) to the file versions it sees; queries join through view_files.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from scripts.facts import (
    FileFacts,
    Guard,
    Literal,
    Ref,
    Symbol,
    shape_from_json,
    shape_to_json,
    signature_from_json,
    signature_to_json,
)

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS file_facts(
  path TEXT NOT NULL, blob_sha TEXT NOT NULL, lang TEXT NOT NULL,
  parsed_ok INTEGER NOT NULL, error TEXT, PRIMARY KEY(path, blob_sha));
CREATE TABLE IF NOT EXISTS symbols(
  path TEXT NOT NULL, blob_sha TEXT NOT NULL, qualname TEXT NOT NULL, kind TEXT NOT NULL,
  line_start INTEGER NOT NULL, line_end INTEGER NOT NULL, is_test INTEGER NOT NULL,
  signature_json TEXT, alias_of TEXT);
CREATE INDEX IF NOT EXISTS symbols_file ON symbols(path, blob_sha);
CREATE TABLE IF NOT EXISTS refs(
  path TEXT NOT NULL, blob_sha TEXT NOT NULL, src TEXT NOT NULL, target TEXT NOT NULL,
  kind TEXT NOT NULL, line INTEGER NOT NULL, args_json TEXT);
CREATE INDEX IF NOT EXISTS refs_file ON refs(path, blob_sha);
CREATE TABLE IF NOT EXISTS literals(
  path TEXT NOT NULL, blob_sha TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL,
  line INTEGER NOT NULL, symbol TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS literals_file ON literals(path, blob_sha);
CREATE INDEX IF NOT EXISTS literals_text ON literals(text);
CREATE TABLE IF NOT EXISTS guards(
  path TEXT NOT NULL, blob_sha TEXT NOT NULL, symbol TEXT NOT NULL, kind TEXT NOT NULL,
  line INTEGER NOT NULL, text TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS guards_file ON guards(path, blob_sha);
CREATE TABLE IF NOT EXISTS views(
  view_id TEXT PRIMARY KEY, kind TEXT NOT NULL, worktree_path TEXT, ref TEXT,
  built_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS view_files(
  view_id TEXT NOT NULL, path TEXT NOT NULL, blob_sha TEXT NOT NULL,
  PRIMARY KEY(view_id, path));
CREATE INDEX IF NOT EXISTS view_files_fact ON view_files(path, blob_sha);
"""

_CHILD_TABLES = ("symbols", "refs", "literals", "guards")


@dataclass(frozen=True)
class Coverage:
    total: int
    failed: list[tuple[str, str]]
    not_indexed: list[str]


@dataclass(frozen=True)
class ViewRow:
    view_id: str
    kind: str
    worktree_path: str | None
    ref: str | None
    built_at: float


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.executescript(_SCHEMA)
        self.conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def _tx(self) -> Iterator[None]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    def meta_get(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return None if row is None else str(row[0])

    def meta_set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def has_facts(self, keys: Iterable[tuple[str, str]]) -> set[tuple[str, str]]:
        wanted = list(keys)
        found: set[tuple[str, str]] = set()
        for i in range(0, len(wanted), 400):
            chunk = wanted[i : i + 400]
            where = " OR ".join("(path=? AND blob_sha=?)" for _ in chunk)
            params = [part for key in chunk for part in key]
            for path, sha in self.conn.execute(
                f"SELECT path, blob_sha FROM file_facts WHERE {where}", params
            ):
                found.add((path, sha))
        return found

    def put_facts(self, ff: FileFacts) -> bool:
        """Store one file's facts. False when another writer already stored this (path, sha)."""
        key = (ff.path, ff.blob_sha)
        with self._tx():
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO file_facts(path, blob_sha, lang, parsed_ok, error) "
                "VALUES (?, ?, ?, ?, ?)",
                (*key, ff.lang, int(ff.parsed_ok), ff.error),
            )
            if cur.rowcount == 0:
                return False
            self.conn.executemany(
                "INSERT INTO symbols VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(*key, s.qualname, s.kind, s.line_start, s.line_end, int(s.is_test),
                  signature_to_json(s.signature), s.alias_of) for s in ff.symbols],
            )
            self.conn.executemany(
                "INSERT INTO refs VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(*key, r.src, r.target, r.kind, r.line, shape_to_json(r.args)) for r in ff.refs],
            )
            self.conn.executemany(
                "INSERT INTO literals VALUES (?, ?, ?, ?, ?, ?)",
                [(*key, x.kind, x.text, x.line, x.symbol) for x in ff.literals],
            )
            self.conn.executemany(
                "INSERT INTO guards VALUES (?, ?, ?, ?, ?, ?)",
                [(*key, g.symbol, g.kind, g.line, g.text) for g in ff.guards],
            )
        return True

    def file_facts(self, path: str, blob_sha: str) -> FileFacts | None:
        key = (path, blob_sha)
        row = self.conn.execute(
            "SELECT lang, parsed_ok, error FROM file_facts WHERE path=? AND blob_sha=?", key
        ).fetchone()
        if row is None:
            return None
        where = "WHERE path=? AND blob_sha=? ORDER BY rowid"
        symbols = [
            Symbol(q, k, a, b, bool(t), signature_from_json(sig), alias)
            for q, k, a, b, t, sig, alias in self.conn.execute(
                "SELECT qualname, kind, line_start, line_end, is_test, signature_json, alias_of "
                f"FROM symbols {where}", key)
        ]
        refs = [
            Ref(src, target, kind, line, shape_from_json(args))
            for src, target, kind, line, args in self.conn.execute(
                f"SELECT src, target, kind, line, args_json FROM refs {where}", key)
        ]
        literals = [
            Literal(kind, text, line, symbol)
            for kind, text, line, symbol in self.conn.execute(
                f"SELECT kind, text, line, symbol FROM literals {where}", key)
        ]
        guards = [
            Guard(symbol, kind, line, text)
            for symbol, kind, line, text in self.conn.execute(
                f"SELECT symbol, kind, line, text FROM guards {where}", key)
        ]
        return FileFacts(path, blob_sha, row[0], bool(row[1]), row[2],
                         symbols, refs, literals, guards)

    def set_view(self, view_id: str, kind: str, worktree_path: str | None, ref: str | None,
                 files: dict[str, str]) -> None:
        with self._tx():
            self.conn.execute(
                "INSERT INTO views(view_id, kind, worktree_path, ref, built_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(view_id) DO UPDATE SET "
                "worktree_path=excluded.worktree_path, ref=excluded.ref, "
                "built_at=excluded.built_at",
                (view_id, kind, worktree_path, ref, time.time()),
            )
            self.conn.execute("DELETE FROM view_files WHERE view_id=?", (view_id,))
            self.conn.executemany(
                "INSERT INTO view_files(view_id, path, blob_sha) VALUES (?, ?, ?)",
                [(view_id, p, s) for p, s in files.items()],
            )

    def get_view(self, view_id: str) -> ViewRow | None:
        row = self.conn.execute(
            "SELECT view_id, kind, worktree_path, ref, built_at FROM views WHERE view_id=?",
            (view_id,),
        ).fetchone()
        return None if row is None else ViewRow(*row)

    def views(self) -> list[ViewRow]:
        return [ViewRow(*row) for row in self.conn.execute(
            "SELECT view_id, kind, worktree_path, ref, built_at FROM views")]

    def view_files(self, view_id: str) -> dict[str, str]:
        return dict(self.conn.execute(
            "SELECT path, blob_sha FROM view_files WHERE view_id=?", (view_id,)))

    def delete_view(self, view_id: str) -> None:
        with self._tx():
            self.conn.execute("DELETE FROM view_files WHERE view_id=?", (view_id,))
            self.conn.execute("DELETE FROM views WHERE view_id=?", (view_id,))

    def delete_orphan_facts(self) -> int:
        with self._tx():
            cur = self.conn.execute(
                "DELETE FROM file_facts WHERE NOT EXISTS (SELECT 1 FROM view_files vf "
                "WHERE vf.path=file_facts.path AND vf.blob_sha=file_facts.blob_sha)"
            )
            removed = cur.rowcount
            for table in _CHILD_TABLES:
                self.conn.execute(
                    f"DELETE FROM {table} WHERE NOT EXISTS (SELECT 1 FROM file_facts ff "
                    f"WHERE ff.path={table}.path AND ff.blob_sha={table}.blob_sha)"
                )
        return removed

    def view_symbols(self, view_id: str) -> list[tuple[str, Symbol]]:
        rows = self.conn.execute(
            "SELECT s.path, s.qualname, s.kind, s.line_start, s.line_end, s.is_test, "
            "s.signature_json, s.alias_of FROM symbols s JOIN view_files vf "
            "ON vf.path=s.path AND vf.blob_sha=s.blob_sha WHERE vf.view_id=? ORDER BY s.rowid",
            (view_id,),
        )
        return [(p, Symbol(q, k, a, b, bool(t), signature_from_json(sig), alias))
                for p, q, k, a, b, t, sig, alias in rows]

    def view_refs(self, view_id: str) -> list[tuple[str, Ref]]:
        rows = self.conn.execute(
            "SELECT r.path, r.src, r.target, r.kind, r.line, r.args_json FROM refs r "
            "JOIN view_files vf ON vf.path=r.path AND vf.blob_sha=r.blob_sha "
            "WHERE vf.view_id=? ORDER BY r.rowid",
            (view_id,),
        )
        return [(p, Ref(src, target, kind, line, shape_from_json(args)))
                for p, src, target, kind, line, args in rows]

    def literal_occurrences(self, view_id: str, texts: list[str]) -> list[tuple[str, str, int]]:
        if not texts:
            return []
        marks = ",".join("?" for _ in texts)
        rows = self.conn.execute(
            "SELECT l.text, l.path, l.line FROM literals l JOIN view_files vf "
            "ON vf.path=l.path AND vf.blob_sha=l.blob_sha "
            f"WHERE vf.view_id=? AND l.kind='string' AND l.text IN ({marks}) "
            "ORDER BY l.path, l.line",
            (view_id, *texts),
        )
        return [(t, p, line) for t, p, line in rows]

    def coverage(self, view_id: str) -> Coverage:
        rows = self.conn.execute(
            "SELECT vf.path, ff.parsed_ok, ff.error FROM view_files vf LEFT JOIN file_facts ff "
            "ON ff.path=vf.path AND ff.blob_sha=vf.blob_sha WHERE vf.view_id=? ORDER BY vf.path",
            (view_id,),
        ).fetchall()
        failed = [(p, err or "parse failed") for p, ok, err in rows if ok == 0]
        missing = [p for p, ok, _ in rows if ok is None]
        return Coverage(len(rows), failed, missing)
