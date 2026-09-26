"""Rates with history: which list price applied to a model at a moment.

``RateBook`` is a read-only, in-memory view of the store's ``price_history``
table (append-only rows of ``(model, effective_from)`` -> six USD/MTok rates)
plus ``pricing._RATES`` as the seed/fallback. Selection is:

* the model id is matched exactly, else by the longest ``-``-boundary prefix
  (so a dated snapshot resolves to its family and ``claude-fable-5-1`` never
  matches ``claude-fable-5``) — the same semantics ``pricing.rates_for`` has
  always had;
* among that key's rows, the newest with ``effective_from <= ts`` wins;
  ``ts`` of None or 0 means "now" (the newest row); a ``ts`` before the key's
  first row uses the first row (a model first *seen* at T existed before T, so
  its earliest known rate beats leaving those turns unpriced);
* a model the table has no row for at all falls back to the built-in table,
  which is also what an empty or not-yet-migrated store gives, so behaviour
  with no history is exactly what it was before history existed.

Reports price ~100k+ turns, so nothing here is per-turn work: the report
groups token sums by (key, model, *rate period*) in SQL (``period_sql``) and
prices each group once at the period's representative timestamp
(``period_ts``). Only *change points* (a model's second and later rows) are
period boundaries — a model's first row applies backwards, so it splits nothing.
"""
from __future__ import annotations

import sqlite3
from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import pairwise
from typing import Any

from scripts import pricing

TABLE = "price_history"
RATE_FIELDS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")
BUILTIN_SOURCE = "builtin"
# Rows `pricing backfill` reads out of Internet Archive snapshots of the pricing
# page: `archive@<snapshot timestamp>`.
ARCHIVE_PREFIX = "archive@"


@dataclass(frozen=True)
class RateRow:
    """One row of ``price_history``: USD per million tokens from
    ``effective_from`` (epoch seconds; 0 = the beginning of time) until the
    model's next row. The two cache-write rates may be None (the source did not
    state them): ``pricing.turn_cost`` then falls back to the multipliers."""
    model: str
    effective_from: float
    input: float
    output: float
    cache_read: float
    cache_write_5m: float | None
    cache_write_1h: float | None
    source: str
    observed_at: float

    def rates(self) -> dict[str, float]:
        out = {"input": self.input, "output": self.output, "cache_read": self.cache_read}
        if self.cache_write_5m is not None:
            out["cache_write_5m"] = self.cache_write_5m
        if self.cache_write_1h is not None:
            out["cache_write_1h"] = self.cache_write_1h
        return out

    def same_rates(self, other: RateRow) -> bool:
        return all(getattr(self, f) == getattr(other, f) for f in RATE_FIELDS)


def builtin_rows() -> list[RateRow]:
    observed = datetime.strptime(pricing.PRICING_AS_OF, "%Y-%m-%d").replace(
        tzinfo=timezone.utc).timestamp()
    return [
        RateRow(model, 0.0, r["input"], r["output"], r["cache_read"],
                r["input"] * pricing.CACHE_WRITE_5M_MULTIPLIER,
                r["input"] * pricing.CACHE_WRITE_1H_MULTIPLIER, BUILTIN_SOURCE, observed)
        for model, r in pricing._RATES.items()
    ]


class RateBook:
    def __init__(self, rows: Iterable[RateRow] = ()) -> None:
        by_model: dict[str, list[RateRow]] = {}
        for r in sorted(rows, key=lambda r: (r.model, r.effective_from)):
            by_model.setdefault(r.model, []).append(r)
        # The seed row (``effective_from`` 0, today's rate) is a placeholder for
        # "no history known". Once the archive has supplied a model's history it
        # would only shadow it — its rate at 0 would price every turn before the
        # first archived row at today's rate — so it stands aside for that model.
        for model, rs in by_model.items():
            if any(r.source.startswith(ARCHIVE_PREFIX) for r in rs):
                by_model[model] = [r for r in rs if r.source != BUILTIN_SOURCE]
        self._rows = by_model
        self._froms = {m: [r.effective_from for r in rs] for m, rs in by_model.items()}
        self._rates = {m: [r.rates() for r in rs] for m, rs in by_model.items()}
        # A model the table carries wins over the built-in row; one it does
        # not is priced from the built-in table (its single row is at 0).
        for model, rates in pricing._RATES.items():
            if model not in by_model:
                self._froms[model] = [0.0]
                self._rates[model] = [dict(rates)]
        self._keys = list(self._froms)
        self._resolved: dict[str, str | None] = {}
        self._changes = sorted({r.effective_from for rs in by_model.values() for r in rs[1:]})

    # -- selection ---------------------------------------------------------

    def _key_for(self, model: str) -> str | None:
        try:
            return self._resolved[model]
        except KeyError:
            pass
        best: str | None = None
        if model in self._froms:
            best = model
        else:
            for key in self._keys:
                if model.startswith(key + "-") and (best is None or len(key) > len(best)):
                    best = key
        self._resolved[model] = best
        return best

    def rates_for(self, model: str | None, ts: float | None = None) -> dict[str, float] | None:
        """The rates for ``model`` in force at ``ts`` (None/0: the newest), or
        None when the model is unknown."""
        if not model:
            return None
        key = self._key_for(model)
        if key is None:
            return None
        rates = self._rates[key]
        if not ts:
            return rates[-1]
        return rates[max(0, bisect_right(self._froms[key], ts) - 1)]

    # -- periods (see the module docstring) --------------------------------

    @property
    def boundaries(self) -> list[float]:
        """Sorted instants at which some model's rate changed."""
        return list(self._changes)

    def period_sql(self, ts_sql: str) -> str:
        """A SQL expression bucketing ``ts_sql`` by rate period: -1 for a NULL
        timestamp (priced as "now"), else the number of boundaries at or before
        it. Constant ``0`` when nothing ever changed."""
        if not self._changes:
            return "0"
        whens = " ".join(f"WHEN {ts_sql} >= {b!r} THEN {i + 1}"
                         for i, b in reversed(list(enumerate(self._changes))))
        return f"CASE WHEN {ts_sql} IS NULL THEN -1 {whens} ELSE 0 END"

    def period_ts(self, period: int) -> float | None:
        """A timestamp inside ``period`` — what to price its group at."""
        if period < 0:
            return None
        if period == 0:
            return self._changes[0] - 1.0 if self._changes else -1.0
        return self._changes[period - 1]

    # -- report metadata ---------------------------------------------------

    def pricing_as_of(self) -> str:
        """The date the newest rate was observed (the built-in table's own
        date when the store holds none)."""
        seen = [r.observed_at for rs in self._rows.values() for r in rs if r.observed_at]
        if not seen:
            return pricing.PRICING_AS_OF
        return datetime.fromtimestamp(max(seen), tz=timezone.utc).date().isoformat()

    def changes_since(self, since: float | None) -> list[dict[str, Any]]:
        """Rate changes (a model's second and later rows) taking effect at or
        after ``since`` (None: all), oldest first. ``effective_from`` of a
        change found by a refresh is an UPPER bound on when it really changed."""
        out: list[dict[str, Any]] = []
        for model, rs in self._rows.items():
            for prev, cur in pairwise(rs):
                if (since is None or cur.effective_from >= since) and not cur.same_rates(prev):
                    out.append({"model": model, "effective_from": cur.effective_from,
                                "source": cur.source, "previous": prev.rates(),
                                "current": cur.rates()})
        return sorted(out, key=lambda c: (c["effective_from"], c["model"]))

    def models(self) -> list[str]:
        return sorted(self._rows)


# -- storage ---------------------------------------------------------------

_COLUMNS = ("model", "effective_from", *RATE_FIELDS, "source", "observed_at")


def has_table(conn: sqlite3.Connection) -> bool:
    """Whether the store has ``price_history`` yet. The report verbs open the
    store READ-ONLY, which returns before ``_migrate`` runs, so a store upgraded
    but not yet synced may lack it (see ``report._has_table``)."""
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (TABLE,)
    ).fetchone() is not None


def load_rows(conn: sqlite3.Connection) -> list[RateRow]:
    if not has_table(conn):
        return []
    return [
        RateRow(r[0], float(r[1]), r[2], r[3], r[4], r[5], r[6], r[7] or "", float(r[8] or 0))
        for r in conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM {TABLE} ORDER BY model, effective_from")
    ]


def load(conn: sqlite3.Connection) -> RateBook:
    return RateBook(load_rows(conn))


def insert_rows(conn: sqlite3.Connection, rows: Iterable[RateRow]) -> int:
    """Append rows; a ``(model, effective_from)`` already present is left
    exactly as it is (the table is append-only). Returns rows inserted. Does
    not commit."""
    inserted = 0
    for r in rows:
        cur = conn.execute(
            f"INSERT OR IGNORE INTO {TABLE}({', '.join(_COLUMNS)}) VALUES (?,?,?,?,?,?,?,?,?)",
            (r.model, r.effective_from, r.input, r.output, r.cache_read, r.cache_write_5m,
             r.cache_write_1h, r.source, r.observed_at))
        inserted += cur.rowcount
    return inserted


def seed_builtin(conn: sqlite3.Connection) -> int:
    """Insert the built-in table at ``effective_from = 0`` for every model that
    has no history yet. Idempotent. Does not commit."""
    have = {r[0] for r in conn.execute(f"SELECT DISTINCT model FROM {TABLE}")}
    return insert_rows(conn, [r for r in builtin_rows() if r.model not in have])


def newest_by_model(conn: sqlite3.Connection) -> dict[str, RateRow]:
    newest: dict[str, RateRow] = {}
    for r in load_rows(conn):                       # ordered by (model, effective_from)
        newest[r.model] = r
    return newest
