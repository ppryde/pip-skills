"""Build a view's facts: hash-gated (only unseen (path, blob) pairs are parsed), lazy, deadline
capped, and safe to run from several worktrees at once. GC runs lazily, at most hourly.
"""
from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from scripts import extract_ts, gitio
from scripts.extract_py import extract_python
from scripts.store import Store
from scripts.views import View, lang_of

TS_CHUNK = 200  # TypeScript files per Node run

BATCH = 200
BASE_VIEW_TTL_S = 7 * 86400


class LockTimeout(RuntimeError):
    pass


@contextmanager
def view_lock(store_path: Path, view_id: str, wait_s: float,
              stale_s: float = 300.0) -> Iterator[None]:
    lock = store_path.parent / "locks" / f"{view_id}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    end = time.monotonic() + wait_s
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > stale_s:
                    lock.unlink(missing_ok=True)  # a crashed indexer left it
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= end:
                raise LockTimeout(
                    f"index busy: {view_id} is being built by another process "
                    f"(waited {wait_s:.0f}s)") from None
            time.sleep(0.05)
            continue
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        break
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


@dataclass
class BuildReport:
    view_id: str
    files: int
    reused: int
    parsed: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)


def ensure_view(store: Store, view: View, deadline_s: float = 60.0) -> BuildReport:
    start = time.monotonic()
    with view_lock(store.path, view.view_id, wait_s=max(deadline_s, 1.0)):
        store.set_view(view.view_id, view.kind,
                       str(view.root) if view.kind == "wt" else None, view.ref, view.files)
        have = store.has_facts(view.files.items())
        missing = [(p, s) for p, s in view.files.items() if (p, s) not in have]
        report = BuildReport(view.view_id, len(view.files), len(have))
        py = [k for k in missing if lang_of(k[0]) == "python"]
        ts = [k for k in missing if lang_of(k[0]) == "typescript"]
        _index_python(store, view, py, report, start, deadline_s)
        _index_typescript(store, view, ts, report, start, deadline_s)
    if view.kind == "wt":
        maybe_gc(store, view.root)
    return report


def _index_python(store: Store, view: View, items: list[tuple[str, str]], report: BuildReport,
                  start: float, deadline_s: float) -> None:
    for i in range(0, len(items), BATCH):
        if time.monotonic() - start > deadline_s:
            report.skipped.update({p: "deadline" for p, _ in items[i:]})
            return
        batch = items[i : i + BATCH]
        data = view.read([p for p, _ in batch])
        for p, s in batch:
            if p not in data:
                report.skipped[p] = "unreadable"
                continue
            ff = extract_python(p, s, data[p])
            store.put_facts(ff)
            report.parsed += 1
            if not ff.parsed_ok:
                report.failed.append((p, ff.error or "parse failed"))


def _index_typescript(store: Store, view: View, items: list[tuple[str, str]],
                      report: BuildReport, start: float, deadline_s: float) -> None:
    if not items:
        return
    reason = extract_ts.unavailable_reason()
    remaining = deadline_s - (time.monotonic() - start)
    if reason is None and remaining <= 0:
        reason = "deadline"
    if reason is not None:
        report.skipped.update({p: reason for p, _ in items})
        return
    for i in range(0, len(items), TS_CHUNK):  # chunked: a deadline keeps the chunks done
        chunk = items[i:i + TS_CHUNK]
        remaining = deadline_s - (time.monotonic() - start)
        if remaining <= 0:
            report.skipped.update({p: "deadline" for p, _ in items[i:]})
            return
        data = view.read([p for p, _ in chunk])
        batch = [(p, s, data[p]) for p, s in chunk if p in data]
        try:
            facts = extract_ts.extract_batch(batch, timeout_s=remaining)
        except extract_ts.DeadlineExceeded:
            report.skipped.update({p: "deadline" for p, _ in items[i:]})
            return
        except RuntimeError as exc:
            report.skipped.update({p: str(exc) for p, _ in items[i:]})
            return
        for ff in facts:
            store.put_facts(ff)
            report.parsed += 1
            if not ff.parsed_ok:
                report.failed.append((ff.path, ff.error or "parse failed"))


@dataclass(frozen=True)
class GcReport:
    views_removed: int
    facts_removed: int


def maybe_gc(store: Store, root: Path, now: float | None = None,
             interval_s: float = 3600.0) -> GcReport | None:
    """Drop dead-worktree views, expired base views and orphaned facts, at most once per interval.

    Runs outside the view lock, so facts a concurrent indexer has written but not yet attached
    to a view may be swept; the next run's hash gate re-extracts them.
    """
    now = time.time() if now is None else now
    if now - float(store.meta_get("last_gc") or 0) < interval_s:
        return None
    try:
        live = gitio.live_worktrees(root)
    except gitio.GitError:
        return None
    removed = 0
    for v in store.views():
        gone = v.kind == "wt" and v.worktree_path not in live
        expired = v.kind == "base" and now - v.built_at > BASE_VIEW_TTL_S
        if gone or expired:
            store.delete_view(v.view_id)
            removed += 1
    facts = store.delete_orphan_facts()
    store.meta_set("last_gc", str(now))
    return GcReport(removed, facts)
