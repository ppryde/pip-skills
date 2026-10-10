"""The shared finding contract every reviewer subagent returns, plus
verdicts, fingerprints, collation and neutral-voice report rendering."""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, fields, replace

VALID_SEVERITY = ("error", "warning", "info")
_REQUIRED = ("id", "file", "rule", "actual", "severity", "category", "suggestion")
# Tolerant parse defaults a missing category/suggestion instead of rejecting.
_REQUIRED_TOLERANT = ("id", "file", "rule", "actual", "severity")

# The one definition of a rule id ("GEN-001"). A *prefix* match on a finding's
# `id`, so a per-run suffix such as "GEN-001-2" still resolves to "GEN-001".
# Shared by contract, exceptions and doclint; do not redefine it elsewhere.
RULE_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*-\d{3}")

# One step down; `info` is the floor. The only place the step table lives.
_LOWER = {"error": "warning", "warning": "info", "info": "info"}

# Tolerant-parse severity synonyms (reviewers drift from the exact words).
_SEVERITY_SYNONYMS = {
    "critical": "error", "high": "error", "blocker": "error", "major": "error",
    "medium": "warning", "moderate": "warning", "warn": "warning",
    "low": "info", "minor": "info", "nit": "info", "suggestion": "info",
}


class ContractError(Exception):
    """Raised when a reviewer payload violates the finding contract."""


def rule_id_of(text: object) -> str | None:
    """The rule id at the start of `text` ("GEN-001-2" -> "GEN-001"), else None."""
    m = RULE_ID_RE.match(text) if isinstance(text, str) else None
    return m.group(0) if m else None


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
    rule_id: str | None = None
    severity_before: str | None = None
    fingerprint: str | None = None
    # True when the reviewer omitted `category` and "general" was filled in;
    # a made-up category must never be a reason to pair two findings.
    category_defaulted: bool = False


def finding_to_dict(f: Finding) -> dict:
    return asdict(f)


def finding_from_dict(raw: dict) -> Finding:
    """Rebuild a Finding from `finding_to_dict` output (extra keys ignored)."""
    known = {f.name for f in fields(Finding)}
    return Finding(**{k: v for k, v in raw.items() if k in known})


def norm(text: object) -> str:
    """Lowercase, whitespace collapsed: the comparison form of free text."""
    return " ".join(str(text).lower().split())


_norm = norm


def _base_fingerprint(f: Finding) -> str:
    key = "\x1f".join([f.reviewer, f.rule_id or _norm(f.rule), f.file, _norm(f.actual)])
    # Leading "f" so YAML never reads an all-digit key (a decisions.yml
    # override key) as an integer.
    return "f" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:11]


def assign_fingerprints(findings: list[Finding]) -> list[Finding]:
    """Stable, line-free ids for a run's findings (returns copies).

    Findings that already carry a fingerprint keep it. Two findings that hash
    alike (the same `except: pass` twice in one file) get an ordinal suffix
    (`<fp>`, `<fp>-2`, ...) ordered by (line, id), so every downstream map
    (critic verdicts, matcher, decisions.yml) stays one-to-one."""
    used = {f.fingerprint for f in findings if f.fingerprint}
    groups: dict[str, list[int]] = {}
    for i, f in enumerate(findings):
        if not f.fingerprint:
            groups.setdefault(_base_fingerprint(f), []).append(i)
    out = list(findings)
    for base, idxs in groups.items():
        idxs.sort(key=lambda i: (findings[i].line if findings[i].line is not None else -1,
                                 findings[i].id, i))
        n = 1
        for i in idxs:
            cand = base
            while cand in used:
                n += 1
                cand = f"{base}-{n}"
            used.add(cand)
            out[i] = replace(findings[i], fingerprint=cand)
    return out


@dataclass
class VerdictResult:
    kept: list[Finding]
    dropped: list[Finding]
    notes: list[str]


def _label(f: Finding) -> str:
    return f.fingerprint or f.id


def apply_verdicts(findings: list[Finding], *, require: bool = False) -> VerdictResult:
    """Apply critic/arbiter verdicts. Never mutates the input, never silently
    drops: `refuted` goes to `dropped` (the report lists it), `weakened` is
    lowered one step once (idempotent), a missing verdict is kept (and noted
    `unverified` when `require`), an unknown verdict is kept and noted."""
    kept: list[Finding] = []
    dropped: list[Finding] = []
    notes: list[str] = []
    for f in findings:
        v = f.verdict
        if v is None or v == "confirmed":
            if v is None and require:
                notes.append(f"unverified: {_label(f)}")
            kept.append(f)
        elif v == "refuted":
            dropped.append(f)
        elif v == "weakened":
            if f.severity_before is None and _LOWER[f.severity] != f.severity:
                f = replace(f, severity_before=f.severity, severity=_LOWER[f.severity])
            kept.append(f)
        else:
            notes.append(f"unknown verdict {v!r}: {_label(f)}")
            kept.append(f)
    return VerdictResult(kept, dropped, notes)


def _coerce_line(value: object) -> tuple[int | None, bool]:
    """(line, ok). None is fine; a numeric string/float is coerced; junk is not."""
    if value is None:
        return None, True
    if isinstance(value, bool):
        return None, False
    try:
        n = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError, OverflowError):  # OverflowError: Infinity
        return None, False
    return (n, True) if n >= 1 else (None, False)


def _as_list(value: object) -> list:
    """A string becomes a one-item list; None/empty becomes []."""
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return list(value) if isinstance(value, (list, tuple)) else [str(value)]


def _parse_one(reviewer: str, raw: dict, strict: bool, notes: list[str], label: str) -> Finding:
    required = _REQUIRED if strict else _REQUIRED_TOLERANT
    missing = [k for k in required if k not in raw]
    if missing:
        raise ContractError(f"finding missing {missing} in {raw!r}")
    category_defaulted = False
    if not strict:
        for key, default in (("category", "general"), ("suggestion", "")):
            if key not in raw:
                notes.append(f"{key} missing, defaulted: {label} ({raw['file']}:{raw.get('line')})")
                raw = {**raw, key: default}
                category_defaulted = category_defaulted or key == "category"
    severity = raw["severity"]
    if severity not in VALID_SEVERITY:
        mapped = None if strict else _SEVERITY_SYNONYMS.get(str(severity).strip().lower())
        if mapped is None and not strict and str(severity).strip().lower() in VALID_SEVERITY:
            mapped = str(severity).strip().lower()
        if mapped is None:
            raise ContractError(
                f"invalid severity {severity!r}; expected {VALID_SEVERITY}"
            )
        severity = mapped
    line = raw.get("line")
    if not strict:
        line, ok = _coerce_line(line)
        if not ok:
            notes.append(f"line {raw.get('line')!r} invalid (not a number >= 1), "
                         f"treated as no line: {label}")
    rule_id = raw.get("rule_id")
    if not isinstance(rule_id, str) or rule_id_of(rule_id) != rule_id:
        rule_id = None if str(raw["id"]).startswith("CLONE-") else rule_id_of(raw["id"])
    # No findings file is ever trusted. verdict / reason / severity_before /
    # fingerprint / category_defaulted are never read from input: verdicts
    # come only from the verdicts file, fingerprints are recomputed in code.
    return Finding(
        reviewer=reviewer,
        id=raw["id"], file=raw["file"], rule=raw["rule"],
        actual=raw["actual"], severity=severity,
        category=raw["category"], suggestion=raw["suggestion"],
        line=line, citation=raw.get("citation"),
        rule_id=rule_id,
        category_defaulted=category_defaulted,
    )


def parse_reviewer_result(
    payload: dict, strict: bool = False
) -> tuple[list[Finding], list[str], list[str]]:
    """Parse one reviewer payload into (findings, clean_files, notes).

    Tolerant by default: a malformed finding is dropped with a
    `REJECTED <id|index>: <reason>` note and the valid ones are kept (the
    caller re-asks that reviewer once for only the rejected ones). A payload
    with no `reviewer` always raises. `strict=True` raises on the first bad
    finding. Input is never trusted: `verdict`, `reason`, `severity_before`,
    `fingerprint` and `category_defaulted` in it are ignored."""
    reviewer = payload.get("reviewer")
    if not reviewer:
        raise ContractError("payload missing 'reviewer'")
    findings: list[Finding] = []
    notes_out: list[str] = []
    for index, raw in enumerate(payload.get("findings", []) or []):
        label = str(raw.get("id", index)) if isinstance(raw, dict) else str(index)
        if not isinstance(raw, dict):
            if strict:
                raise ContractError(f"finding is not an object: {raw!r}")
            notes_out.append(f"REJECTED {label}: not an object")
            continue
        try:
            findings.append(_parse_one(reviewer, raw, strict, notes_out, label))
        except ContractError as exc:
            if strict:
                raise
            notes_out.append(f"REJECTED {label}: {exc}")
    clean = _as_list(payload.get("clean_files"))
    notes = _as_list(payload.get("notes")) + notes_out
    return findings, clean, notes


def collate(findings: list[Finding]) -> dict:
    grouped: dict[str, dict[str, list[Finding]]] = {}
    for f in findings:
        grouped.setdefault(f.reviewer, {s: [] for s in VALID_SEVERITY})
        grouped[f.reviewer][f.severity].append(f)
    return grouped


def _one_line(text: object) -> str:
    return " ".join(str(text).split())


def _code_span(text: object) -> str:
    """A markdown code span that survives backticks and newlines in text."""
    t = _one_line(text)
    longest = max((len(m) for m in re.findall(r"`+", t)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if t.startswith("`") or t.endswith("`") else ""
    return f"{fence}{pad}{t}{pad}{fence}"


def _counts(findings: list[Finding]) -> str:
    tally = {s: 0 for s in VALID_SEVERITY}
    for f in findings:
        tally[f.severity] += 1
    parts = [f"{tally[s]} {s}" for s in VALID_SEVERITY if tally[s]]
    return ", ".join(parts) if parts else "no findings"


def render_report(
    collated: dict, meta: dict, dropped: list[Finding] | None = None
) -> str:
    """Neutral-voice markdown. `dropped` (critic/arbiter-refuted findings) is
    never shown inline but is listed in a trailing section, so a refutation
    can be audited."""
    dropped = dropped or []
    all_findings = [f for revs in collated.values() for fs in revs.values() for f in fs]
    refuted = f" · {len(dropped)} refuted" if dropped else ""
    lines = [
        "# review-panel",
        "",
        f"Strategy: **{meta.get('strategy','?')}** · Scope: **{meta.get('scope','?')}** · "
        f"{_counts(all_findings)}{refuted}",
        "",
    ]
    for reviewer, by_sev in collated.items():
        rev_findings = [f for fs in by_sev.values() for f in fs]
        lines.append(f"## {reviewer} — {_counts(rev_findings)}")
        for sev in VALID_SEVERITY:
            for f in by_sev[sev]:
                loc = f"{f.file}:{f.line}" if f.line is not None else f.file
                verdict = f" _({f.verdict})_" if f.verdict else ""
                lines.append(f"- **[{f.id}] {sev}**{verdict} — {_one_line(f.rule)} — {_code_span(loc)}")
                lines.append(f"  - found: {_code_span(f.actual)}")
                lines.append(f"  - fix: {_one_line(f.suggestion)}")
                if f.citation:
                    lines.append(f"  - citation: {f.citation}")
                if f.fingerprint:
                    lines.append(f"  - fingerprint: {_code_span(f.fingerprint)}")
        lines.append("")
    notes = [n for n in (meta.get("notes") or [])]
    if notes:
        lines.append("## Notes")
        lines.extend(f"- {_one_line(n)}" for n in notes)
        lines.append("")
    if dropped:
        lines.append("## Refuted (dropped by critic)")
        for f in dropped:
            loc = f"{f.file}:{f.line}" if f.line is not None else f.file
            rule = f.rule_id or _one_line(f.rule)
            reason = _one_line(f.reason) if f.reason else "no reason given"
            lines.append(
                f"- {_code_span(f.fingerprint or f.id)} · {_one_line(rule)} · "
                f"{_code_span(loc)} · {reason}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
