"""The long-term usage log: one SQLite file per Claude account, apart from the per-repo index
caches, so deleting an index never loses history. The CLI appends one event per query; only
`concordance stats` reads it back. Nothing here is printed into an agent's context.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from collections import Counter
from pathlib import Path

from scripts.paths import config_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
  ts REAL NOT NULL, session TEXT, repo TEXT, command TEXT NOT NULL, view_id TEXT,
  latency_ms INTEGER, est_tokens INTEGER, exit_code INTEGER, payload TEXT);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
"""
DAY_S = 86400.0
BUCKETS = ("1-5", "6-20", "21+")


def usage_path() -> Path:
    override = os.environ.get("CONCORDANCE_USAGE_DB")
    return Path(override) if override else config_dir() / "concordance" / "usage.db"


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.executescript(SCHEMA)
    return conn


def record(command: str, repo: str, view_id: str | None, latency_ms: int, est_tokens: int,
           exit_code: int, payload: dict[str, object], session: str = "",
           path: Path | None = None) -> None:
    conn = _connect(path or usage_path())
    try:
        with conn:
            conn.execute(
                "INSERT INTO events(ts, session, repo, command, view_id, latency_ms, "
                "est_tokens, exit_code, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (time.time(), session, repo, command, view_id, latency_ms, est_tokens,
                 exit_code, json.dumps(payload, sort_keys=True)))
    finally:
        conn.close()


def size_bucket(touched: int) -> str:
    if touched <= 0:
        return "0"
    return "1-5" if touched <= 5 else "6-20" if touched <= 20 else "21+"


def _pct(values: list[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)  # nearest rank: the smallest value covering fraction q
    return ordered[min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))]


def report(days: int = 30, repo: str | None = None, now: float | None = None,
           path: Path | None = None) -> dict[str, object]:
    path = path or usage_path()
    since = (now if now is not None else time.time()) - days * DAY_S
    rows: list[tuple[str, str, int, int, int, str]] = []
    if path.exists():
        conn = _connect(path)
        try:
            sql = ("SELECT command, session, latency_ms, est_tokens, exit_code, payload "
                   "FROM events WHERE ts >= ?" + (" AND repo = ?" if repo else "") + " ORDER BY ts")
            rows = conn.execute(sql, (since, repo) if repo else (since,)).fetchall()
        finally:
            conn.close()
    commands: dict[str, dict[str, int]] = {}
    by_size = {b: {"runs": 0, "cut": 0} for b in BUCKETS}
    sections_cut: Counter[str] = Counter()
    budget = {"review_runs": 0, "cut_runs": 0, "omitted_runs": 0}
    verdicts = {"runs": 0, "runs_with_verdicts": 0, "total": 0}
    reviews = {"count": 0, "clean": 0, "findings": 0, "via_index": 0}
    by_step: Counter[str] = Counter()
    grouped: dict[str, list[tuple[str, int, int]]] = {}
    failures: Counter[str] = Counter()
    skipped = 0
    for command, session, latency, tokens, exit_code, raw in rows:
        try:
            p = json.loads(raw or "{}")
        except ValueError:
            skipped += 1
            continue
        if not isinstance(p, dict):
            skipped += 1
            continue
        if exit_code == 2:  # a failed run: counted apart, kept out of cost and effectiveness
            failures[command] += 1
            continue
        if command == "record-review":
            reviews["count"] += 1
            reviews["findings"] += int(p.get("findings", 0))
            reviews["via_index"] += int(p.get("via_index", 0))
            reviews["clean"] += int(p.get("findings", 0)) == 0
            by_step.update({k: int(v) for k, v in p.get("steps", {}).items()})
            continue
        grouped.setdefault(command, []).append((session or "", latency or 0, tokens or 0))
        if "verdicts" in p:
            verdicts["runs"] += 1
            verdicts["runs_with_verdicts"] += int(p["verdicts"]) > 0
            verdicts["total"] += int(p["verdicts"])
        if command == "review-context" and "budget" in p:
            cut, omitted = p.get("cut", {}), p.get("omitted", [])
            budget["review_runs"] += 1
            budget["cut_runs"] += bool(cut or omitted)
            budget["omitted_runs"] += bool(omitted)
            sections_cut.update(set(cut) | set(omitted))
            bucket = size_bucket(int(p.get("touched", 0)))
            if bucket in by_size:
                by_size[bucket]["runs"] += 1
                by_size[bucket]["cut"] += bool(cut or omitted)
    for command in sorted(set(grouped) | set(failures)):
        items = grouped.get(command, [])
        lat = [x[1] for x in items]
        tok = [x[2] for x in items]
        commands[command] = {
            "runs": len(items), "failures": failures[command],
            "sessions": len({x[0] for x in items if x[0]}),
            "tokens_p50": _pct(tok, 0.5), "tokens_p90": _pct(tok, 0.9),
            "latency_p50": _pct(lat, 0.5), "latency_p90": _pct(lat, 0.9)}
    return {"days": days, "repo": repo or "all", "commands": commands,
            "budget": {**budget, "by_size": by_size, "sections_cut": dict(sections_cut)},
            "verdicts": verdicts, "reviews": {**reviews, "by_step": dict(sorted(by_step.items()))},
            "skipped_rows": skipped}


def format_report(rep: dict[str, object]) -> str:
    commands = rep["commands"]
    reviews = rep["reviews"]
    assert isinstance(commands, dict) and isinstance(reviews, dict)
    title = f"# concordance usage, last {rep['days']} days ({rep['repo']})"
    if not commands and not reviews["count"]:
        return f"{title}\n\nno concordance usage recorded in this window"
    out = [title, "", "## Usage", "",
           "| command | runs | failed | sessions | tokens p50/p90 | ms p50/p90 |",
           "|---|---|---|---|---|---|"]
    for name, c in sorted(commands.items()):
        out.append(f"| {name} | {c['runs']} | {c['failures']} | {c['sessions']} | "
                   f"{c['tokens_p50']}/{c['tokens_p90']} | {c['latency_p50']}/{c['latency_p90']} |")
    budget = rep["budget"]
    verdicts = rep["verdicts"]
    assert isinstance(budget, dict) and isinstance(verdicts, dict)
    out += ["", "## Budget pressure", "",
            (f"review-context runs cut: {budget['cut_runs']} of {budget['review_runs']} "
             f"({budget['omitted_runs']} with whole sections omitted)")]
    out += [f"- {b} touched symbols: {v['cut']} of {v['runs']} cut"
            for b, v in budget["by_size"].items() if v["runs"]]
    if budget["sections_cut"]:
        out.append("most cut: " + ", ".join(
            f"{s} ({n})" for s, n in sorted(budget["sections_cut"].items(),
                                            key=lambda kv: (-kv[1], kv[0]))))
    out += ["", "## Effectiveness", "",
            (f"verdicts raised on {verdicts['runs_with_verdicts']} of {verdicts['runs']} runs "
             f"({verdicts['total']} in all)"),
            (f"reviews recorded: {reviews['count']} ({reviews['clean']} clean); "
             f"{reviews['via_index']} of {reviews['findings']} findings via concordance")]
    if reviews["by_step"]:
        out.append("findings by step: " + ", ".join(
            f"step {k}: {v}" for k, v in reviews["by_step"].items()))
    if rep.get("skipped_rows"):
        out += ["", f"{rep['skipped_rows']} unreadable rows skipped"]
    return "\n".join(out)
