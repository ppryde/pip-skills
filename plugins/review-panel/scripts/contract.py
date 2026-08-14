"""The shared finding contract every reviewer subagent returns, plus
collation and neutral-voice report rendering."""
from __future__ import annotations

from dataclasses import dataclass

VALID_SEVERITY = ("error", "warning", "info")
_REQUIRED = ("id", "file", "rule", "actual", "severity", "category", "suggestion")


class ContractError(Exception):
    """Raised when a reviewer payload violates the finding contract."""


@dataclass
class Finding:
    reviewer: str
    id: str
    file: str
    rule: str
    actual: str
    severity: str
    category: str
    suggestion: str
    line: int | None = None
    citation: str | None = None
    verdict: str | None = None
    reason: str | None = None


def parse_reviewer_result(payload: dict) -> tuple[list[Finding], list[str], list[str]]:
    reviewer = payload.get("reviewer")
    if not reviewer:
        raise ContractError("payload missing 'reviewer'")
    findings: list[Finding] = []
    for raw in payload.get("findings", []) or []:
        missing = [k for k in _REQUIRED if k not in raw]
        if missing:
            raise ContractError(f"finding missing {missing} in {raw!r}")
        if raw["severity"] not in VALID_SEVERITY:
            raise ContractError(
                f"invalid severity {raw['severity']!r}; expected {VALID_SEVERITY}"
            )
        findings.append(Finding(
            reviewer=reviewer,
            id=raw["id"], file=raw["file"], rule=raw["rule"],
            actual=raw["actual"], severity=raw["severity"],
            category=raw["category"], suggestion=raw["suggestion"],
            line=raw.get("line"), citation=raw.get("citation"),
            verdict=raw.get("verdict"), reason=raw.get("reason"),
        ))
    clean = list(payload.get("clean_files", []) or [])
    notes = list(payload.get("notes", []) or [])
    return findings, clean, notes


def collate(findings: list[Finding]) -> dict:
    grouped: dict[str, dict[str, list[Finding]]] = {}
    for f in findings:
        grouped.setdefault(f.reviewer, {s: [] for s in VALID_SEVERITY})
        grouped[f.reviewer][f.severity].append(f)
    return grouped


def _counts(findings: list[Finding]) -> str:
    tally = {s: 0 for s in VALID_SEVERITY}
    for f in findings:
        tally[f.severity] += 1
    parts = [f"{tally[s]} {s}" for s in VALID_SEVERITY if tally[s]]
    return ", ".join(parts) if parts else "no findings"


def render_report(collated: dict, meta: dict) -> str:
    all_findings = [f for revs in collated.values() for fs in revs.values() for f in fs]
    lines = [
        "# review-panel",
        "",
        f"Strategy: **{meta.get('strategy','?')}** · Scope: **{meta.get('scope','?')}** · "
        f"{_counts(all_findings)}",
        "",
    ]
    for reviewer, by_sev in collated.items():
        rev_findings = [f for fs in by_sev.values() for f in fs]
        lines.append(f"## {reviewer} — {_counts(rev_findings)}")
        for sev in VALID_SEVERITY:
            for f in by_sev[sev]:
                loc = f"{f.file}:{f.line}" if f.line is not None else f.file
                verdict = f" _({f.verdict})_" if f.verdict else ""
                lines.append(f"- **[{f.id}] {sev}**{verdict} — {f.rule} — `{loc}`")
                lines.append(f"  - found: `{f.actual}`")
                lines.append(f"  - fix: {f.suggestion}")
                if f.citation:
                    lines.append(f"  - citation: {f.citation}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
