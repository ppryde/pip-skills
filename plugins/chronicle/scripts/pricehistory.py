"""``chronicle pricing backfill`` — recover past rates from Internet Archive snapshots.

The pricing page has no history of its own; the Archive holds dated snapshots of
it. This walks them OLDEST -> NEWEST, parses each with the same parser refresh
uses (``pricepage`` — markdown or HTML), diffs consecutive price sets, and
inserts ``price_history`` rows:

* a model's FIRST appearance -> a row at that snapshot's timestamp;
* each later change -> a row at the timestamp of the first snapshot showing it.

Both are UPPER bounds — the true release / change happened at or before the
snapshot that first shows it — and the earliest archived rate also stands in for
turns before the model's first snapshot (see ``ratebook``). Rows are tagged
``archive@<timestamp>``; while a model has any, its seed row stands aside.

Best effort by construction: a snapshot that cannot be fetched is skipped and
reported (and retried next run); one that cannot be parsed, or whose rates jump
more than 10x, is recorded as such and skipped; nothing is ever invented. It is
polite — sequential, at least one second between requests, short timeouts, a
hard ``limit`` on requests per run — and resumable: snapshots already handled
are remembered in ``meta``. It is a manual verb only, never on the sync path.
"""
from __future__ import annotations

import json
import sqlite3
import time
from bisect import bisect_right
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from scripts import pricepage, pricerefresh, ratebook

SOURCE_URLS = (
    "platform.claude.com/docs/en/about-claude/pricing",
    "platform.claude.com/docs/en/about-claude/pricing.md",
    "docs.claude.com/en/docs/about-claude/pricing",
)
DEFAULT_FROM = "2026-05"
DEFAULT_LIMIT = 40
REQUEST_GAP_SECONDS = 1.0
CDX_TIMEOUT = 20.0
SNAPSHOT_TIMEOUT = 15.0
_META_DONE = "pricing_backfill_snapshots"     # JSON {timestamp: "ok" | "unparseable" | "suspect"}


def cdx_url(source: str, frm: str, to: str) -> str:
    return ("https://web.archive.org/cdx/search/cdx?url=" + quote(source, safe="/")
            + f"&from={frm}&to={to}&output=json&collapse=digest&limit=200"
            + "&fl=timestamp,statuscode,digest,length")


def snapshot_url(timestamp: str, source: str) -> str:
    return f"https://web.archive.org/web/{timestamp}id_/https://{source}"


def epoch(timestamp: str) -> float:
    """``20260715123000`` (UTC, as the Archive stamps it) -> epoch seconds."""
    return datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).timestamp()


def parse_cdx(text: str) -> list[str]:
    """Timestamps of the successful (200) captures in a CDX ``output=json`` reply."""
    try:
        rows = json.loads(text)
    except ValueError:
        return []
    if not isinstance(rows, list) or len(rows) < 2 or not isinstance(rows[0], list):
        return []
    head = rows[0]
    try:
        ts_i, code_i = head.index("timestamp"), head.index("statuscode")
    except ValueError:
        return []
    return [str(r[ts_i]) for r in rows[1:]
            if isinstance(r, list) and len(r) > max(ts_i, code_i) and str(r[code_i]) == "200"]


def _done(conn: sqlite3.Connection) -> dict[str, str]:
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (_META_DONE,)).fetchone()
        loaded = json.loads(row[0]) if row else {}
    except (sqlite3.Error, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def backfill(conn: sqlite3.Connection, *, since_month: str | None = None, dry_run: bool = False,
             limit: int = DEFAULT_LIMIT, now: float | None = None,
             sleep: Callable[[float], None] = time.sleep,
             sources: tuple[str, ...] = SOURCE_URLS) -> dict[str, Any]:
    """Walk archived snapshots oldest -> newest and record rate history.
    ``limit`` caps ALL requests this run makes (the CDX listings included).
    Never raises; the result says what was found, added, skipped and why."""
    when = time.time() if now is None else now
    frm = (since_month or DEFAULT_FROM).replace("-", "") + "01"
    to = datetime.fromtimestamp(when, tz=timezone.utc).strftime("%Y%m%d")
    out: dict[str, Any] = {"status": "ok", "dry_run": dry_run, "requests": 0, "found": 0,
                           "already_done": 0, "processed": 0, "rows": [], "failed": [],
                           "unparseable": [], "limit_reached": False, "remaining": 0}

    def get(url: str, timeout: float) -> str | None:
        if out["requests"] >= limit:
            out["limit_reached"] = True
            return None
        if out["requests"]:
            sleep(REQUEST_GAP_SECONDS)
        out["requests"] += 1
        return pricepage.fetch_text(url, timeout=timeout)

    try:
        # -- 1. list the captures (each listing is a request, counted) --------
        captures: dict[str, str] = {}                       # timestamp -> source it was seen under
        for source in sources:
            try:
                text = get(cdx_url(source, frm, to), CDX_TIMEOUT)
            except pricepage.FetchError as exc:
                out["failed"].append({"listing": source, "error": str(exc)})
                continue
            for ts in parse_cdx(text or ""):
                captures.setdefault(ts, source)
        out["found"] = len(captures)
        if not captures and out["failed"]:
            out["status"] = "error"
            return out
        done = _done(conn)
        todo = sorted(ts for ts in captures if ts not in done)
        out["already_done"] = len(captures) - len(todo)

        # -- 2. the known archive history, as-of lookups by timestamp ----------
        history: dict[str, list[ratebook.RateRow]] = {}
        for r in ratebook.load_rows(conn):
            if r.source.startswith(ratebook.ARCHIVE_PREFIX):
                history.setdefault(r.model, []).append(r)

        def prior(model: str, at: float) -> ratebook.RateRow | None:
            rs = history.get(model, [])
            i = bisect_right([r.effective_from for r in rs], at)
            return rs[i - 1] if i else None

        # -- 3. walk oldest -> newest ----------------------------------------
        new_rows: list[ratebook.RateRow] = []
        outcomes: dict[str, str] = {}
        for index, ts in enumerate(todo):
            try:
                text = get(snapshot_url(ts, captures[ts]), SNAPSHOT_TIMEOUT)
            except pricepage.FetchError as exc:
                out["failed"].append({"timestamp": ts, "error": str(exc)})
                continue
            if text is None:                                # the request budget is spent
                out["remaining"] = len(todo) - index
                break
            parsed = pricepage.parse_pricing(text)
            if parsed.error:
                out["unparseable"].append({"timestamp": ts, "error": parsed.error})
                outcomes[ts] = "unparseable"
                continue
            at = epoch(ts)
            added = _diff(parsed.prices, ts, at, prior)
            if added is None:
                out["unparseable"].append({"timestamp": ts, "error": "rate moved more than 10x"})
                outcomes[ts] = "suspect"
                continue
            for row in added:
                history.setdefault(row.model, []).append(row)
                history[row.model].sort(key=lambda r: r.effective_from)
                new_rows.append(row)
                out["rows"].append({"model": row.model, "effective_from": row.effective_from,
                                    "timestamp": ts, "kind": "first" if _is_first(history, row) else "change",
                                    "rates": row.rates()})
            outcomes[ts] = "ok"
            out["processed"] += 1

        # -- 4. write (resume state and rows together) -------------------------
        if not dry_run and (new_rows or outcomes):
            ratebook.insert_rows(conn, new_rows)
            done.update(outcomes)
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                         (_META_DONE, json.dumps(done, sort_keys=True)))
            conn.commit()
        return out
    except Exception as exc:  # noqa: BLE001 - a best-effort verb reports, it does not crash
        return {**out, "status": "error", "error": f"{type(exc).__name__}: {exc}"}


def _is_first(history: dict[str, list[ratebook.RateRow]], row: ratebook.RateRow) -> bool:
    return history[row.model][0] is row


def _diff(prices: dict[str, pricepage.PagePrice], ts: str, at: float,
          prior: Callable[[str, float], ratebook.RateRow | None]) -> list[ratebook.RateRow] | None:
    """Rows this snapshot adds over the history before it; None when a rate moved
    more than 10x (a mis-parse, not a price change — the snapshot is skipped)."""
    rows: list[ratebook.RateRow] = []
    for model, price in sorted(prices.items()):
        before = prior(model, at)
        if before is not None:
            old, new = pricerefresh.effective(before), pricerefresh.effective(price)
            if pricerefresh.same_rates(old, new):
                continue
            if pricerefresh.implausible(old, new):
                return None
        rows.append(ratebook.RateRow(
            model, at, price.input, price.output, price.cache_read, price.cache_write_5m,
            price.cache_write_1h, f"{ratebook.ARCHIVE_PREFIX}{ts}", at))
    return rows
