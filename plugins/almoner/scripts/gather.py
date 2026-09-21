"""Fan out to every configured source, degrade the ones that fail, store the rest.

A source that is unreachable, unauthorised or slow becomes ``ok: false`` with a
named error; it never fails the digest. A silently short digest is worse than a
visible error, because an empty list reads as "nothing needs you" either way.

Each source runs on its own daemon thread rather than a ``ThreadPoolExecutor``:
a pool's worker threads are joined by an atexit hook with no timeout, so one
wedged ``fetch()`` would keep the whole CLI process alive past the dashboard's
subprocess kill. A daemon thread carries no such promise — the process exits
without waiting for it, whether or not it ever returns.
"""
from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from concurrent.futures import Future, wait
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
    # Human-readable, non-fatal problems worth showing next to the source.
    warnings: list[str] = field(default_factory=list)
    # False when the adapter stopped early (a page cap, a rate limit) and
    # in-window content may remain unread — the watermark must not advance.
    complete: bool = True
    # Ids the adapter positively knows no longer have an open conversation —
    # see store.read_digest's "closed" suppression.
    closed: list[str] = field(default_factory=list)


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
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"label": self.label, "type": self.type, "via": self.via,
                               "context": self.context, "ok": self.ok,
                               "watermark": self.watermark}
        if self.error is not None:
            out["error"] = self.error
        if self.warnings:
            out["warnings"] = self.warnings
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


def _report(source: Source, ok: bool, error: str | None, watermark: float | None,
           warnings: list[str] | None = None) -> SourceReport:
    return SourceReport(source.label, source.type, source.via, source.context, ok, error,
                        watermark, warnings or [])


def _fetch_worker(adapter: Adapter, window: Window, future: Future[FetchResult]) -> None:
    # Mirrors concurrent.futures' own worker: catch BaseException so a wedged
    # or misbehaving adapter can never crash the thread without resolving the
    # future the main thread is waiting on.
    if not future.set_running_or_notify_cancel():
        return
    try:
        result = adapter.fetch(window)
    except BaseException as exc:  # noqa: BLE001 — a wedged/broken adapter must still resolve
        future.set_exception(exc)
    else:
        future.set_result(result)


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
        try:
            adapter = factory(source, secret)
        except AdapterError as exc:
            reports[source.label] = _report(source, False, str(exc), previous[source.label])
            continue
        except Exception as exc:  # noqa: BLE001 — a broken factory degrades, never sinks the gather
            reports[source.label] = _report(source, False, f"failed: {type(exc).__name__}",
                                            previous[source.label])
            continue
        window = fetch_window(now, hours, previous[source.label])
        future: Future[FetchResult] = Future()
        pending[future] = source
        threading.Thread(target=_fetch_worker, args=(adapter, window, future), daemon=True,
                         name=f"almoner-fetch-{source.label}").start()
    if pending:
        done, _ = wait(pending, timeout=timeout)

    merged: dict[str, dict[str, Any]] = {}
    suppressed: list[tuple[str, str, str]] = []
    items_in = 0
    ok_results: list[tuple[Source, FetchResult]] = []
    for future, source in pending.items():
        if future not in done:
            reports[source.label] = _report(source, False, "timed out", previous[source.label])
            continue
        raised = future.exception()
        if isinstance(raised, AdapterError):
            reports[source.label] = _report(source, False, str(raised), previous[source.label])
            continue
        if raised is not None:
            reports[source.label] = _report(source, False, f"failed: {type(raised).__name__}",
                                            previous[source.label])
            continue
        result = future.result()
        ok_results.append((source, result))
        items_in += len(result.items)
        suppressed.extend((item_id, source.type, rule) for item_id, rule in result.suppressed)
        suppressed.extend((item_id, source.type, "closed") for item_id in result.closed)
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
        watermark: float | None
        if result.complete:
            store.set_watermark(conn, source.label, now, result.cursor)
            watermark = now
        else:
            # Stopped early: in-window content may remain unread, so the
            # watermark must not advance past it — see FetchResult.complete.
            watermark = previous[source.label]
        reports[source.label] = _report(source, True, None, watermark, list(result.warnings))
    store.record_run(conn, started=now, finished=datetime.now(timezone.utc).timestamp(),
                     sources_ok=[s.label for s, _ in ok_results],
                     sources_failed=[r.label for r in reports.values() if not r.ok],
                     items_in=items_in, items_out=len(merged))
    return GatherOutcome(len(merged), len(suppressed), [reports[s.label] for s in sources])
