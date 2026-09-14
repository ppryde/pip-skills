"""Fan out to every configured source, degrade the ones that fail, store the rest.

A source that is unreachable, unauthorised or slow becomes ``ok: false`` with a
named error; it never fails the digest. A silently short digest is worse than a
visible error, because an empty list reads as "nothing needs you" either way.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from scripts import store
from scripts.config import Source, read_secret

OVERLAP_S = 3600.0
SOURCE_TIMEOUT_S = 40.0


@dataclass(frozen=True)
class Window:
    since: datetime
    until: datetime


@dataclass
class FetchResult:
    items: list[dict[str, Any]]
    suppressed: list[tuple[str, str]] = field(default_factory=list)
    cursor: str | None = None


class Adapter(Protocol):
    def fetch(self, window: Window) -> FetchResult: ...


class AdapterError(Exception):
    """A source failure whose message is safe to show — never a credential."""


AdapterFactory = Callable[[Source, str], Adapter]


@dataclass
class SourceReport:
    label: str
    type: str
    via: str
    context: str
    ok: bool
    error: str | None = None
    watermark: float | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"label": self.label, "type": self.type, "via": self.via,
                               "context": self.context, "ok": self.ok,
                               "watermark": self.watermark}
        if self.error is not None:
            out["error"] = self.error
        return out


@dataclass
class GatherOutcome:
    items_out: int
    suppressed: int
    reports: list[SourceReport]


def fetch_window(now: float, hours: int, watermark: float | None) -> Window:
    # The watermark only avoids re-paging old history; the overlap catches late
    # arrivals, and `seen` dedup by id makes re-fetching them safe.
    since = now - hours * 3600
    if watermark is not None:
        since = max(since, watermark - OVERLAP_S)
    return Window(datetime.fromtimestamp(since, timezone.utc),
                  datetime.fromtimestamp(now, timezone.utc))


def _report(source: Source, ok: bool, error: str | None,
           watermark: float | None) -> SourceReport:
    return SourceReport(source.label, source.type, source.via, source.context, ok, error,
                        watermark)


def gather_and_store(conn: sqlite3.Connection, sources: list[Source], *, hours: int, now: float,
                     registry: dict[tuple[str, str], AdapterFactory] | None = None,
                     timeout: float = SOURCE_TIMEOUT_S) -> GatherOutcome:
    if registry is None:
        from scripts.adapters import registry as default_registry
        registry = default_registry()

    previous = {s.label: store.get_watermark(conn, s.label) for s in sources}
    reports: dict[str, SourceReport] = {}
    pending: dict[Future[FetchResult], Source] = {}
    done: set[Future[FetchResult]] = set()
    pool = ThreadPoolExecutor(max_workers=max(1, len(sources)))
    try:
        for source in sources:
            factory = registry.get((source.type, source.via))
            if factory is None:
                reports[source.label] = _report(
                    source, False, f"unsupported source: {source.type} via {source.via}",
                    previous[source.label])
                continue
            secret = read_secret(source.label)
            if secret is None:
                reports[source.label] = _report(source, False, "no credentials",
                                                previous[source.label])
                continue
            adapter = factory(source, secret)
            window = fetch_window(now, hours, previous[source.label])
            pending[pool.submit(adapter.fetch, window)] = source
        if pending:
            done, _ = wait(pending, timeout=timeout)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    merged: dict[str, dict[str, Any]] = {}
    suppressed: list[tuple[str, str, str]] = []
    items_in = 0
    ok_results: list[tuple[Source, FetchResult]] = []
    for future, source in pending.items():
        if future not in done:
            reports[source.label] = _report(source, False, "timed out", previous[source.label])
            continue
        exc = future.exception()
        if isinstance(exc, AdapterError):
            reports[source.label] = _report(source, False, str(exc), previous[source.label])
            continue
        if exc is not None:
            reports[source.label] = _report(source, False, f"failed: {type(exc).__name__}",
                                            previous[source.label])
            continue
        result = future.result()
        ok_results.append((source, result))
        items_in += len(result.items)
        suppressed.extend((item_id, source.type, rule) for item_id, rule in result.suppressed)
        for item in result.items:
            existing = merged.get(item["id"])
            if existing is None:
                merged[item["id"]] = item
                continue
            for name in item.get("seen_in") or []:
                if name not in existing["seen_in"]:
                    existing["seen_in"].append(name)

    store.upsert_items(conn, list(merged.values()), now)
    store.record_suppressed(conn, suppressed, now)
    for source, result in ok_results:
        store.set_watermark(conn, source.label, now, result.cursor)
        reports[source.label] = _report(source, True, None, now)
    store.record_run(conn, started=now, finished=datetime.now(timezone.utc).timestamp(),
                     sources_ok=[s.label for s, _ in ok_results],
                     sources_failed=[r.label for r in reports.values() if not r.ok],
                     items_in=items_in, items_out=len(merged))
    return GatherOutcome(len(merged), len(suppressed), [reports[s.label] for s in sources])
