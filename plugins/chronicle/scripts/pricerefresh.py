"""Keep ``price_history`` current: refresh from the pricing page, on a schedule.

``refresh`` reads the live pricing page (``pricepage``), compares each model's
six rates with the newest stored row (the built-in table stands in for a model
with no row), and APPENDS a row for every change and every new model. It is
append-only and idempotent — an unchanged page writes nothing — and it is
soft: a network error, a layout surprise, or a rate that moved more than 10x
(more likely a mis-parse than a price cut) returns a status and writes
nothing, not even the seed.

A row found by refresh is stamped ``effective_from = <the time it was
observed>``. The page cannot say when a change really took effect, so that is
an UPPER bound: turns between the true change and the observation are priced at
the old rate. ``pricing backfill`` (``pricehistory``) narrows this where the
Internet Archive holds earlier snapshots.

``maybe_refresh`` is what ``chronicle sync`` calls: at most one attempt per 24h
(success or failure is recorded in ``meta`` so a dead network is not retried
every minute), plus one early attempt when newly synced turns use a model no
row covers. ``CHRONICLE_NO_PRICING_REFRESH=1`` turns it off. It never raises.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from scripts import pricepage, ratebook, transcript

DISABLE_ENV = "CHRONICLE_NO_PRICING_REFRESH"
REFRESH_INTERVAL = 86400.0
EARLY_MIN_INTERVAL = 600.0
MAX_RATE_RATIO = 10.0
DEFAULT_TIMEOUT = 5.0

_META_LAST = "pricing_refresh"          # JSON: {status, at, error, changed, added}
_META_LAST_AT = "pricing_refresh_at"    # float, the last attempt
_META_SEEN = "pricing_seen_rowid"       # turns already checked for unpriced models
_META_EARLY = "pricing_early_retried"   # JSON list of models given their one early retry


def _now() -> float:
    return time.time()


def _date(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()


def effective(row: ratebook.RateRow | pricepage.PagePrice) -> tuple[float, ...]:
    """The six numbers a row prices with: cache writes fall back to the
    multipliers, so a source that omits them compares equal to one that states
    the multiplied value."""
    from scripts import pricing
    cw5 = row.cache_write_5m if row.cache_write_5m is not None \
        else row.input * pricing.CACHE_WRITE_5M_MULTIPLIER
    cw1 = row.cache_write_1h if row.cache_write_1h is not None \
        else row.input * pricing.CACHE_WRITE_1H_MULTIPLIER
    return (row.input, row.output, row.cache_read, cw5, cw1)


def same_rates(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return all(math.isclose(x, y, rel_tol=1e-9, abs_tol=1e-12) for x, y in zip(a, b, strict=True))


def implausible(old: tuple[float, ...], new: tuple[float, ...]) -> bool:
    return any(o > 0 and (n / o > MAX_RATE_RATIO or n / o < 1 / MAX_RATE_RATIO)
               for o, n in zip(old, new, strict=True))


def baseline(conn: sqlite3.Connection) -> dict[str, ratebook.RateRow]:
    """Each model's newest known row: the store's, else the built-in seed."""
    known = {r.model: r for r in ratebook.builtin_rows()}
    known.update(ratebook.newest_by_model(conn))
    return known


def refresh(conn: sqlite3.Connection, *, dry_run: bool = False, now: float | None = None,
            url: str = pricepage.PRICING_URL, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Fetch the pricing page and append what changed. Never raises; the
    ``status`` is one of ``changed`` / ``unchanged`` / ``error`` / ``refused``
    and only ``changed`` and the first ``unchanged`` (the seed) write."""
    when = _now() if now is None else now
    out: dict[str, Any] = {"status": "error", "changed": [], "added": [], "seeded": 0,
                           "error": None, "dry_run": dry_run, "details": []}
    try:
        try:
            text = pricepage.fetch_text(url, timeout=timeout)
        except pricepage.FetchError as exc:
            out["error"] = f"fetch failed: {exc}"
            return out
        parsed = pricepage.parse_pricing(text)
        out["skipped"] = parsed.skipped[:20]
        if parsed.error:
            out["error"] = f"page not understood: {parsed.error}"
            return out
        known = baseline(conn)
        new_rows: list[ratebook.RateRow] = []
        refused: list[str] = []
        for model, price in sorted(parsed.prices.items()):
            row = ratebook.RateRow(model, when, price.input, price.output, price.cache_read,
                                   price.cache_write_5m, price.cache_write_1h,
                                   f"pricing-page@{_date(when)}", when)
            prev = known.get(model)
            if prev is None:
                new_rows.append(row)
                out["added"].append(model)
                out["details"].append({"model": model, "previous": None, "current": row.rates()})
                continue
            old_eff, new_eff = effective(prev), effective(price)
            if same_rates(old_eff, new_eff):
                continue
            if implausible(old_eff, new_eff):
                refused.append(model)
                continue
            # Strictly after the row it supersedes, whatever the clock says.
            eff = max(when, prev.effective_from + 0.001)
            new_rows.append(ratebook.RateRow(**{**row.__dict__, "effective_from": eff}))
            out["changed"].append(model)
            out["details"].append({"model": model, "previous": prev.rates(),
                                   "current": row.rates()})
        if refused:
            out.update(status="refused", changed=[], added=[], details=[],
                       error=f"rate moved more than {MAX_RATE_RATIO:g}x, treated as a mis-parse: "
                             + ", ".join(refused))
            return out
        out["status"] = "changed" if new_rows else "unchanged"
        if not dry_run:
            out["seeded"] = ratebook.seed_builtin(conn)
            ratebook.insert_rows(conn, new_rows)
            conn.commit()
        return out
    except Exception as exc:  # noqa: BLE001 - the contract is: refresh never raises
        conn.rollback() if not dry_run else None
        return {**out, "status": "error", "error": f"{type(exc).__name__}: {exc}",
                "changed": [], "added": [], "details": []}


def seed(conn: sqlite3.Connection) -> dict[str, Any]:
    """Write the built-in table into ``price_history`` (models without history)."""
    n = ratebook.seed_builtin(conn)
    conn.commit()
    return {"seeded": n}


# -- meta bookkeeping ------------------------------------------------------

def _meta(conn: sqlite3.Connection, key: str) -> str | None:
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))


def _meta_float(conn: sqlite3.Connection, key: str) -> float | None:
    try:
        return float(_meta(conn, key) or "")
    except ValueError:
        return None


def record_attempt(conn: sqlite3.Connection, result: dict[str, Any], now: float) -> None:
    """Remember the last attempt — success or failure — for ``status`` and for
    ``maybe_refresh``'s cadence. Commits."""
    _set_meta(conn, _META_LAST_AT, str(now))
    _set_meta(conn, _META_LAST, json.dumps({
        "status": result.get("status"), "at": now, "error": result.get("error"),
        "changed": result.get("changed", []), "added": result.get("added", [])}))
    conn.commit()


# -- the automatic path -----------------------------------------------------

def disabled() -> bool:
    return os.environ.get(DISABLE_ENV, "").strip().lower() not in ("", "0", "false", "no")


def _new_unpriced_models(conn: sqlite3.Connection) -> tuple[list[str], int | None]:
    """Models on turns synced since the last check that no row (and no built-in)
    covers, and the newest turn rowid seen."""
    top = conn.execute("SELECT MAX(rowid) FROM turns").fetchone()[0]
    if top is None:
        return [], None
    seen = int(_meta_float(conn, _META_SEEN) or 0)
    if top <= seen:
        return [], top
    book = ratebook.load(conn)
    models = [r[0] for r in conn.execute(
        "SELECT DISTINCT model FROM turns WHERE rowid > ? AND model IS NOT NULL", (seen,))]
    return sorted(m for m in models if m != transcript.SYNTHETIC_MODEL
                  and book.rates_for(m) is None), top


def maybe_refresh(conn: sqlite3.Connection, *, now: float | None = None,
                  interval: float = REFRESH_INTERVAL,
                  timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """`refresh`, at most once per ``interval`` — or early, once per model, when
    newly synced turns use a model nothing prices. Records every attempt in
    ``meta`` (a failure too, so a down network is not retried each sync).
    Returns ``{"status": disabled|skipped|changed|unchanged|error|refused,
    "changed": [...], ...}``; never raises."""
    if disabled():
        return {"status": "disabled", "changed": []}
    when = _now() if now is None else now
    try:
        last = _meta_float(conn, _META_LAST_AT)
        unknown, top = _new_unpriced_models(conn)
        try:
            retried = set(json.loads(_meta(conn, _META_EARLY) or "[]"))
        except ValueError:
            retried = set()
        early = [m for m in unknown if m not in retried]
        due = last is None or when - last >= interval
        early_ok = bool(early) and (last is None or when - last >= EARLY_MIN_INTERVAL)
        if not (due or early_ok):
            if not early and top is not None:               # nothing pending: consume the check
                _set_meta(conn, _META_SEEN, str(top))
                conn.commit()
            return {"status": "skipped", "changed": [],
                    "next_at": None if last is None else last + interval}
        if early_ok:
            _set_meta(conn, _META_EARLY, json.dumps(sorted(retried | set(early))))
        if top is not None:
            _set_meta(conn, _META_SEEN, str(top))
        result = refresh(conn, now=when, timeout=timeout)
        record_attempt(conn, result, when)
        return result
    except Exception as exc:  # noqa: BLE001 - sync must never fail because of pricing
        return {"status": "error", "changed": [], "error": f"{type(exc).__name__}: {exc}"}


# -- reporting ---------------------------------------------------------------

def status(conn: sqlite3.Connection) -> dict[str, Any]:
    """What the store knows about prices: each model's effective ranges, when
    the newest rate was observed, and the last refresh attempt. Read-only and
    safe on a store that predates the table."""
    rows = ratebook.load_rows(conn)
    by_model: dict[str, list[ratebook.RateRow]] = {}
    for r in rows:
        by_model.setdefault(r.model, []).append(r)
    models = []
    for model, rs in by_model.items():
        periods = []
        for i, r in enumerate(rs):
            periods.append({
                "effective_from": r.effective_from,
                "effective_to": rs[i + 1].effective_from if i + 1 < len(rs) else None,
                **{k: getattr(r, k) for k in ratebook.RATE_FIELDS},
                "source": r.source, "observed_at": r.observed_at})
        models.append({"model": model, "periods": periods})
    try:
        last = json.loads(_meta(conn, _META_LAST) or "null")
    except ValueError:
        last = None
    return {"pricing_as_of": ratebook.RateBook(rows).pricing_as_of(), "rows": len(rows),
            "models": models, "last_refresh": last, "using_builtin_only": not rows}
