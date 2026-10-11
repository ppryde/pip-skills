"""Board schema v2 upgrade (WF-265 PR D1): backup, import, evidence backfill and
the mixed-version re-import.

v1 kept sprints (``sprints/<id>.md``), knowledge facts (``knowledge/``) and
pending facts (``knowledge/pending.jsonl``) as files. v2 keeps them in
``board.db`` and regenerates the files as read-only views (``views.py``).

The upgrade is safe by construction:

* ``backup_before_v2`` takes an online ``sqlite3`` backup (WAL-safe) to
  ``<board>.pre-v2.<UTC>.bak`` and verifies it BEFORE any DDL, outside any
  transaction. If it cannot be verified the upgrade aborts with the board
  untouched.
* ``finish_v2`` runs inside the caller's single ``BEGIN IMMEDIATE``: v2 tables,
  the import, the evidence backfill and the version stamp land together or not
  at all.
* The import is idempotent (``INSERT OR IGNORE``) and never moves, renames or
  deletes a source file; files that do not parse are reported, not touched.
* Mixed versions: an older plugin on a v2 board still writes the legacy files.
  ``reimport_newer_files`` (run on every connect) re-imports any file modified
  after the last view export, file-wins-when-newer, so that write is not lost
  to the next export. Upgrade every account that shares a board together.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from scripts.knowledge import Fact
from scripts.models import Card, CardParseError
from scripts.sprints import Sprint
from scripts.store import check_id

BACKUP_KEEP = 3
SCHEMA_V2 = 2
PENDING_FILENAME = "pending.jsonl"


@dataclass
class ImportReport:
    sprints: int = 0
    facts: int = 0
    retired: int = 0
    pending: int = 0
    unparsed: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (f"imported {self.sprints} sprints, {self.facts + self.retired} facts "
                f"({self.retired} retired), {self.pending} pending; "
                f"{len(self.unparsed)} unparsed")


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M")


# --- backup ---------------------------------------------------------------


def backup_before_v2(conn: sqlite3.Connection, path: Path) -> Path:
    """Online-backup the v1 board next to itself and verify the copy
    (``integrity_check`` ok, same card count). Raises ``MigrationError`` and
    removes the partial copy on any failure -- the caller must not touch the
    board then. Keeps the newest ``BACKUP_KEEP`` backups, never the one just
    written being among the pruned."""
    from scripts.db import MigrationError

    conn.commit()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = path.parent / f"{path.name}.pre-v2.{stamp}.bak"
    n = 0
    while dest.exists():
        n += 1
        dest = path.parent / f"{path.name}.pre-v2.{stamp}.{n}.bak"
    try:
        expected = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        out = sqlite3.connect(str(dest))
        try:
            conn.backup(out)
        finally:
            out.close()
        check = sqlite3.connect(str(dest))
        try:
            ok = check.execute("PRAGMA integrity_check").fetchone()[0]
            got = check.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        finally:
            check.close()
        if ok != "ok":
            raise MigrationError(f"backup integrity_check said {ok!r}")
        if got != expected:
            # A writer may have committed between the two counts: re-read once.
            expected = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
            if got != expected:
                raise MigrationError(f"backup holds {got} cards, board has {expected}")
    except (sqlite3.Error, OSError, MigrationError) as exc:
        dest.unlink(missing_ok=True)
        if isinstance(exc, MigrationError):
            raise MigrationError(f"{exc}; board left untouched at {path}") from exc
        raise MigrationError(
            f"could not back up {path} before the schema v2 upgrade ({exc}); "
            "board left untouched"
        ) from exc
    if conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_V2:
        # Lost the first-upgrade race: another process finished while we copied,
        # so this is a copy of a v2 board, not the pre-upgrade state. Drop it.
        dest.unlink(missing_ok=True)
        return dest
    _prune_backups(path, keep_also=dest)
    return dest


def _prune_backups(path: Path, keep_also: Path) -> None:
    found = sorted(path.parent.glob(f"{path.name}.pre-v2.*.bak"), key=lambda p: p.name)
    survivors = set(found[-BACKUP_KEEP:]) | {keep_also}
    for old in found:
        if old not in survivors:
            old.unlink(missing_ok=True)


# --- import ---------------------------------------------------------------


def _newer(path: Path, since: "float | None") -> bool:
    if since is None:
        return True
    try:
        return path.stat().st_mtime > since
    except OSError:
        return False


def _verb(overwrite: bool) -> str:
    return "INSERT OR REPLACE" if overwrite else "INSERT OR IGNORE"


def _import_sprints(conn, state: Path, since, overwrite, report: ImportReport) -> None:
    for path in sorted((state / "sprints").glob("*.md")):
        if not _newer(path, since):
            continue
        try:
            sprint = Sprint.from_text(path.read_text())
            check_id(sprint.id, "sprint id")
        except Exception as exc:  # noqa: BLE001 -- any bad file is reported, never fatal
            report.unparsed.append(f"{path}: {exc}")
            continue
        cur = conn.execute(
            f"{_verb(overwrite)} INTO sprints(id, status, budget_estimate, budget_actual, "
            "started, body, updated) VALUES (?,?,?,?,?,?,?)",
            (sprint.id, sprint.status, sprint.budget_estimate, sprint.budget_actual,
             sprint.started, sprint.body, _now_iso()),
        )
        report.sprints += max(0, cur.rowcount)


def _import_facts(conn, state: Path, since, overwrite, report: ImportReport) -> None:
    kb = state / "knowledge"
    # Retired first: if a crash left the same id in both folders, retired wins.
    for sub, retired in (("retired", 1), ("facts", 0)):
        for path in sorted((kb / sub).glob("*.md")):
            if not _newer(path, since):
                continue
            try:
                fact = Fact.from_text(path.read_text())
                check_id(fact.id, "fact id")
            except Exception as exc:  # noqa: BLE001
                report.unparsed.append(f"{path}: {exc}")
                continue
            if retired:
                fact.status = "retired"
            cur = conn.execute(
                f"{_verb(overwrite)} INTO facts(id, statement, tags, source, status, verified, "
                "created, body, retired, superseded_by) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (fact.id, fact.statement, json.dumps(fact.tags), fact.source, fact.status,
                 fact.verified, fact.created, fact.body, retired or int(fact.status == "retired"),
                 fact.superseded_by),
            )
            if max(0, cur.rowcount):
                if retired:
                    report.retired += 1
                else:
                    report.facts += 1


def _import_pending(conn, state: Path, since, overwrite, report: ImportReport) -> None:
    path = state / "knowledge" / PENDING_FILENAME
    if not path.is_file() or not _newer(path, since):
        return
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        report.unparsed.append(f"{path}: {exc}")
        return
    for number, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
            pid, statement = str(row["id"]), str(row["statement"])
            tags = [str(t) for t in row.get("tags") or []]
            card, source = str(row.get("card", "")), str(row.get("source", ""))
            status, reason = str(row.get("status", "pending")), str(row.get("reason", ""))
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            report.unparsed.append(f"{path}:{number}: {exc}")
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO pending_facts(id, card, statement, tags, source, status, "
            "reason, created) VALUES (?,?,?,?,?,?,?,?)",
            (pid, card, statement, json.dumps(tags), source, status, reason, _now_iso()),
        )
        if max(0, cur.rowcount):
            report.pending += 1
        elif overwrite and status != "pending":
            # A legacy writer adjudicated a fact: that decision wins, never the reverse.
            conn.execute(
                "UPDATE pending_facts SET status=?, reason=? WHERE id=? AND status='pending'",
                (status, reason, pid),
            )


def import_state(
    conn: sqlite3.Connection, state: Path, *, since: "float | None" = None,
    overwrite: bool = False,
) -> ImportReport:
    """Import the legacy file state under ``state`` into the v2 tables. Does
    not commit (the caller owns the transaction). ``overwrite`` is the
    file-wins re-import used for files a legacy writer touched after the last
    export; ``since`` restricts it to files modified after that time."""
    report = ImportReport()
    _import_sprints(conn, state, since, overwrite, report)
    _import_facts(conn, state, since, overwrite, report)
    _import_pending(conn, state, since, overwrite, report)
    return report


# --- evidence backfill ------------------------------------------------------

_ROUND_HEADER = re.compile(r"^### (?P<stage>.+?) — round (?P<n>\d+)(?: \((?P<k>\d+) reviewers?\))?\s*$")
_SLOT_LINE = re.compile(
    r"^- (?P<slot>[^:]+): (?P<status>.+?) (?P<c>\d+)C (?P<i>\d+)I (?P<m>\d+)M(?: → (?P<detail>.*))?$"
)
_VERDICT_LINE = re.compile(r"^Verdict: (?P<verdict>.+)$")
_PASSFAIL = re.compile(r"\b(PASS|FAIL)\b")


def _evidence_rows(card: Card) -> list[dict]:
    rows: list[dict] = []
    sections = card.sections
    stage = None
    round_no = None
    for line in sections.get("## Review log", "").split("\n"):
        header = _ROUND_HEADER.match(line.strip())
        if header:
            stage, round_no = header["stage"], int(header["n"])
            continue
        if stage is None:
            continue
        slot = _SLOT_LINE.match(line.strip())
        if slot:
            rows.append(dict(
                stage=stage, kind="review", round=round_no, slot=slot["slot"].strip(),
                status=slot["status"].strip(), critical=int(slot["c"]),
                important=int(slot["i"]), minor=int(slot["m"]),
            ))
            continue
        verdict = _VERDICT_LINE.match(line.strip())
        if verdict:
            rows.append(dict(
                stage=stage, kind="review", round=round_no, slot="",
                status=verdict["verdict"].strip()[:200], critical=None,
                important=None, minor=None,
            ))
    verification = sections.get("## Verification", "").strip()
    if verification and verification != "_(pending)_":
        # A section that gives two different verdicts ("FAIL ... then PASS") or
        # none is UNKNOWN: D2 reads these rows as gate evidence.
        tokens = {m.group(1) for m in _PASSFAIL.finditer(verification)}
        rows.append(dict(
            stage="verification", kind="verify", round=None, slot="",
            status=tokens.pop() if len(tokens) == 1 else "UNKNOWN",
            critical=None, important=None, minor=None,
        ))
    return rows


def backfill_evidence(conn: sqlite3.Connection) -> tuple[int, int]:
    """Best-effort ``stage_evidence`` rows from each LIVE card's ``## Review log``
    and ``## Verification`` text. A card whose log does not parse yields no rows.
    Skips any card that already has evidence. Returns (rows, cards)."""
    from scripts.db import record_evidence, row_to_card

    rows_total = cards_total = 0
    for row in conn.execute("SELECT * FROM cards WHERE archived = 0").fetchall():
        try:
            card = row_to_card(row)
        except CardParseError:
            continue
        if conn.execute(
            "SELECT 1 FROM stage_evidence WHERE card_id = ? LIMIT 1", (card.id,)
        ).fetchone():
            continue
        rows = _evidence_rows(card)
        for r in rows:
            record_evidence(
                conn, card.id, r["stage"], r["kind"], round_no=r["round"], slot=r["slot"],
                status=r["status"], critical=r["critical"], important=r["important"],
                minor=r["minor"], detail="backfilled", ts=card.updated,
            )
        rows_total += len(rows)
        cards_total += 1 if rows else 0
    return rows_total, cards_total


# --- upgrade orchestration ------------------------------------------------


def finish_v2(conn: sqlite3.Connection, state: "Path | None", *, imported: bool) -> None:
    """Inside the upgrade transaction: import the legacy files, backfill evidence
    (populated boards only) and stamp the markers. ``gates_since`` is the moment
    of the upgrade -- D2's gates are warn-only for cards created before it."""
    from scripts.db import get_meta, set_meta

    report = ImportReport()
    if state is not None and state.is_dir():
        report = import_state(conn, state)
    rows = cards = 0
    if imported:
        rows, cards = backfill_evidence(conn)
    now = _now_iso()
    set_meta(conn, "state_imported_v2", now)
    if get_meta(conn, "gates_since") is None:
        set_meta(conn, "gates_since", now)
    set_meta(conn, "views_exported_at", "0")
    set_meta(conn, "views_reimported_at", now_epoch())
    if imported:
        set_meta(conn, "v2_report", json.dumps({
            "summary": report.summary(), "unparsed": report.unparsed,
            "evidence_rows": rows, "evidence_cards": cards,
        }))


def post_upgrade(conn: sqlite3.Connection, state: Path) -> None:
    """After the upgrade commits: say what happened once, and write the views."""
    from scripts.db import get_meta

    raw = get_meta(conn, "v2_report")
    if raw is None:
        return
    conn.execute("DELETE FROM meta WHERE key = 'v2_report'")
    conn.commit()
    try:
        info = json.loads(raw)
    except ValueError:
        info = {"summary": "imported", "unparsed": []}
    print(f"overseer: board upgraded to schema v2 -- {info['summary']}; "
          f"{info.get('evidence_rows', 0)} evidence rows backfilled. "
          "Upgrade every Claude account that shares this board together.", file=sys.stderr)
    for line in info.get("unparsed", []):
        print(f"overseer: UNPARSED (left in place): {line}", file=sys.stderr)
    export_views(conn, state)


def export_views(conn: sqlite3.Connection, state: Path) -> None:
    from scripts import views
    views.export(conn, state)


def _view_files(state: Path) -> list[Path]:
    kb = state / "knowledge"
    found = list((state / "sprints").glob("*.md"))
    found += list((kb / "facts").glob("*.md")) + list((kb / "retired").glob("*.md"))
    found.append(kb / PENDING_FILENAME)
    return found


def reimport_newer_files(conn: sqlite3.Connection, state: Path, *, export: bool = True) -> None:
    """Mixed-version safety: a plugin of an older version writes the legacy
    files directly. Any file modified after the last view export is a write the
    views would otherwise overwrite, so import it (file wins) and re-export.
    About a hundred ``stat`` calls, no git, no parsing when nothing changed."""
    from scripts import db

    if db.get_meta(conn, "state_imported_v2") is None:
        return
    # A file is "a legacy write" only if it is newer than BOTH the last export
    # and the last re-import: a failed export must not make already-imported
    # (older) file content win over later v2 writes.
    exported = 0.0
    for key in ("views_exported_at", "views_reimported_at"):
        try:
            exported = max(exported, float(db.get_meta(conn, key) or 0))
        except ValueError:
            pass
    scan_started = time.time()
    changed = []
    for path in _view_files(state):
        try:
            if path.stat().st_mtime > exported:
                changed.append(path)
        except OSError:
            continue
    if not changed:
        return
    with db.txn(conn):
        report = import_state(conn, state, since=exported, overwrite=True)
        db.set_meta(conn, "views_reimported_at", repr(scan_started))
    for line in report.unparsed:
        print(f"overseer: UNPARSED (left in place): {line}", file=sys.stderr)
    if export:
        export_views(conn, state)


def now_epoch() -> str:
    return repr(time.time())
