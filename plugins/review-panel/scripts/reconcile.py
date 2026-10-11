"""One reconciliation pass: verdicts, then strictness, then decisions.

Order matters. Verdicts first, so a critic's downgrade is never undone;
decisions last, so an owner override always wins."""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from scripts.contract import Finding, apply_verdicts, assign_fingerprints, norm
from scripts.strictness import apply_decisions, apply_strictness


@dataclass
class ReconcileResult:
    findings: list[Finding]
    dropped: list[Finding]
    notes: list[str] = field(default_factory=list)


def merge_verdicts(
    findings: list[Finding], verdicts: dict | None
) -> tuple[list[Finding], list[str]]:
    """Stamp `{"<fingerprint>": {"verdict": ..., "reason": ...}}` onto findings.

    A verdict for a fingerprint that matches no finding is noted, not fatal; a
    malformed entry is noted and ignored."""
    verdicts = verdicts or {}
    notes: list[str] = []
    by_fp = {f.fingerprint for f in findings if f.fingerprint}
    for fp in verdicts:
        if fp not in by_fp:
            notes.append(f"verdict for unknown fingerprint: {fp}")
    out: list[Finding] = []
    for f in findings:
        entry = verdicts.get(f.fingerprint) if f.fingerprint else None
        if entry is None:
            out.append(f)
        elif isinstance(entry, dict) and isinstance(entry.get("verdict"), str):
            out.append(replace(
                f, verdict=entry["verdict"], reason=entry.get("reason", f.reason),
            ))
        else:
            notes.append(f"malformed verdict entry: {f.fingerprint}")
            out.append(f)
    return out, notes


_TWIN_WINDOW = 3


def _rule_key(f: Finding) -> str:
    return f.rule_id or norm(f.rule)


def _is_twin(a: Finding, b: Finding) -> bool:
    # `actual` must match too: an inherited `refuted` must never hide a
    # different problem that merely shares a rule and a neighbourhood.
    if (a.reviewer, a.file, _rule_key(a), norm(a.actual)) != (
            b.reviewer, b.file, _rule_key(b), norm(b.actual)):
        return False
    if a.line is None or b.line is None:
        return a.line is None and b.line is None
    return abs(a.line - b.line) <= _TWIN_WINDOW


def propagate_twin_verdicts(
    findings: list[Finding], verdict_fps: set[str]
) -> tuple[list[Finding], list[str]]:
    """Give a verdict-less finding the verdict of its twin (same reviewer,
    file and rule, lines within 3). Adversarial Stage 2 sends only one of a
    set of duplicates to the critic; the others inherit its verdict here, and
    each inheritance is recorded in the notes. Only a verdict from the
    verdicts file (`verdict_fps`) is inherited, never a code-set one."""
    sources = [f for f in findings if f.verdict is not None and f.fingerprint in verdict_fps]
    notes: list[str] = []
    out: list[Finding] = []
    for f in findings:
        if f.verdict is None:
            twins = [s for s in sources if _is_twin(f, s)]
            if twins:
                src = min(twins, key=lambda s: abs((f.line or 0) - (s.line or 0)))
                f = replace(f, verdict=src.verdict, reason=src.reason)
                notes.append(f"verdict propagated: {f.fingerprint or f.id} "
                             f"from {src.fingerprint or src.id}")
        out.append(f)
    return out, notes


def reconcile(
    findings: list[Finding],
    *,
    require_verdicts: bool = False,
    strictness: dict[str, str] | None = None,
    exceptions: dict[str, set[str]] | None = None,
    decisions: dict | None = None,
    verdicts: dict | None = None,
) -> ReconcileResult:
    notes: list[str] = []
    findings = assign_fingerprints(list(findings))
    findings, merge_notes = merge_verdicts(findings, verdicts)
    notes += merge_notes
    findings, twin_notes = propagate_twin_verdicts(findings, set(verdicts or {}))
    notes += twin_notes
    vr = apply_verdicts(findings, require=require_verdicts)
    notes += vr.notes
    kept = apply_strictness(vr.kept, strictness or {}, exceptions)
    kept = apply_decisions(kept, decisions or {}, notes)
    return ReconcileResult(findings=kept, dropped=vr.dropped, notes=notes)
