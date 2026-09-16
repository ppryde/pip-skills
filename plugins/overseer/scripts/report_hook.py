"""SubagentStop report hook (WF-113 rework — typed JSON report contract).

Turns an overseer agent's ``overseer-report`` JSON block into ledger records
without spending an agent or orchestrator turn: parse the block, total real
usage from the agent's transcript, write the card and usage.jsonl, queue
Learned facts.

Bounded retry, not silent record-only: a Stop/SubagentStop hook that blocks
makes the agent continue, which costs a turn at the agent's full context and
risks a loop if it can repeat forever — so a missing or malformed report
gets exactly ONE bounce (``decision: block`` naming every problem found and
the expected shape), guarded by ``stop_hook_active`` so Claude Code's own
retry-once semantics bound it. A report that is still missing or invalid on
the retry is recorded as ``unparsed`` (with the error list) and the hook
falls silent — never a second block, never a loop.
"""
from __future__ import annotations

from pathlib import Path

from scripts import db
from scripts.dispatch import role_of
from scripts.models import Card
from scripts.pending import add_pending
from scripts.schemas import (
    FixerReport,
    ImplementerReport,
    PlannerReport,
    Report,
    ReportError,
    ReviewerReport,
    VerifierReport,
    parse_report_message,
)
from scripts.store import state_root
from scripts.transcript_usage import budget_tokens, raw_total, sum_usage, zero_usage
from scripts.usage import append_usage

EXPECTED_SHAPE = {
    "reviewer": (
        '{"schema": "overseer.reviewer/1", "card": "...", "stage": "...", '
        '"round": 1, "slot": "A", "status": "approved|found wanting", '
        '"counts": {"critical": 0, "important": 0, "minor": 0}, '
        '"detail": "/abs/path", "learned": [{"statement": "...", "tags": []}]}'
    ),
    "implementer": (
        '{"schema": "overseer.implementer/1", "card": "...", "stage": "...", '
        '"chunk": 1, "status": "DONE|DONE_WITH_CONCERNS|BLOCKED|NEEDS_CONTEXT", '
        '"tests": {"passed": 0, "total": 0}, "commits": ["sha"], '
        '"detail": "/abs/path", "learned": []}'
    ),
    "fixer": (
        '{"schema": "overseer.fixer/1", "card": "...", "stage": "...", '
        '"round": 1, "status": "DONE|DISPUTED|BLOCKED", '
        '"counts": {"fixed": 0, "disputed": 0}, "commits": ["sha"], '
        '"detail": "/abs/path", "learned": []}'
    ),
    "planner": (
        '{"schema": "overseer.planner/1", "card": "...", "stage": "planning", '
        '"status": "DONE|NEEDS_CONTEXT", "detail": "/abs/path", "learned": []}'
    ),
    "verifier": (
        '{"schema": "overseer.verifier/1", "card": "...", "stage": "verification", '
        '"status": "PASS|FAIL", "detail": "/abs/path", "learned": []}'
    ),
}


def _reviewer_line(r: ReviewerReport) -> str:
    return f"{r.status} {r.critical}C {r.important}I {r.minor}M → {r.detail}"


def _fixer_line(r: FixerReport) -> str:
    sha = r.commits[-1] if r.commits else "-"
    return f"{r.status} fixed {r.fixed} disputed {r.disputed} {sha} → {r.detail}"


def _implementer_line(r: ImplementerReport) -> str:
    sha = r.commits[-1] if r.commits else "-"
    return f"{r.status} tests {r.tests_passed}/{r.tests_total} {sha} → {r.detail}"


def _detail_text(report: Report) -> tuple[str, str | None]:
    try:
        return report.detail.read_text(), None
    except OSError:
        return "", "detail file missing"


def _record(card: Card, role: str, report: Report, detail: str, spend: int, now: str) -> None:
    """Budget semantics are unchanged from telemetry.md: implementer and
    fixer spend feeds ``budget_actual``; planner/reviewer/verifier spend is
    measurement only (usage.jsonl)."""
    if isinstance(report, ReviewerReport):
        card.record_review(report.stage, report.round, report.slot, _reviewer_line(report), now)
    elif isinstance(report, FixerReport):
        card.log_progress(f"{report.stage} r{report.round} fix — {_fixer_line(report)}", spend, now)
    elif isinstance(report, ImplementerReport):
        card.log_progress(f"chunk {report.chunk} — {_implementer_line(report)}", spend, now)
    elif isinstance(report, PlannerReport):
        if report.status == "DONE" and detail.strip():
            card.set_section("## Plan", detail, now)
    elif isinstance(report, VerifierReport) and detail.strip():
        card.set_section("## Verification", detail, now)


def handle(payload: dict[str, object], repo_root: Path, now: str) -> dict[str, object] | None:
    """Returns a hook-output dict (``{"decision": "block", ...}``) when the
    reply should be bounced once, else None — the caller (``cli.py``'s
    ``report-hook`` verb) prints whatever this returns and nothing else."""
    role = role_of(payload.get("agent_type"))
    if role is None:
        return None
    message = payload.get("last_assistant_message")
    text = message if isinstance(message, str) else ""
    transcript = payload.get("agent_transcript_path")
    totals = sum_usage(Path(transcript)) if isinstance(transcript, str) and transcript else zero_usage()
    root = state_root(repo_root)
    entry: dict[str, object] = {
        "ts": now, "card": None, "role": role, "stage": None, "round": None,
        "tokens": raw_total(totals), **totals, "budget_tokens": budget_tokens(totals),
        "agent_id": payload.get("agent_id"), "source": "hook",
    }
    try:
        report = parse_report_message(role, text)
    except ReportError as exc:
        stop_hook_active = bool(payload.get("stop_hook_active"))
        if not stop_hook_active:
            reason = (
                f"overseer {role} report invalid: " + "; ".join(exc.errors) +
                f". Expected a final message containing exactly one "
                f"```overseer-report block shaped like: {EXPECTED_SHAPE[role]}"
            )
            return {"decision": "block", "reason": reason}
        entry.update(unparsed=text[:500], errors=exc.errors)
        append_usage(root, entry)
        return None
    entry.update(card=report.card, stage=report.stage, round=getattr(report, "round", None))
    detail, detail_error = _detail_text(report)
    if detail_error:
        entry["error"] = detail_error
    spend = budget_tokens(totals)
    conn = db.connect(repo_root)
    try:
        card = db.mutate_card(conn, report.card, lambda c: _record(c, role, report, detail, spend, now))
    finally:
        conn.close()
    if card is None:
        entry["error"] = f"no card {report.card}"
    else:
        for fact in report.learned:
            add_pending(repo_root, report.card, fact.statement, list(fact.tags), str(report.detail))
        if card.tripwire_breached:
            entry["tripwire"] = True
    append_usage(root, entry)
    return None
