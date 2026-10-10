"""One reconciliation pass: verdicts, then strictness, then decisions.

Order matters. Verdicts first, so a critic's downgrade is never undone;
decisions last, so an owner override always wins."""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from scripts.contract import Finding, apply_verdicts, assign_fingerprints
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
    vr = apply_verdicts(findings, require=require_verdicts)
    notes += vr.notes
    kept = apply_strictness(vr.kept, strictness or {}, exceptions)
    kept = apply_decisions(kept, decisions or {}, notes)
    return ReconcileResult(findings=kept, dropped=vr.dropped, notes=notes)
