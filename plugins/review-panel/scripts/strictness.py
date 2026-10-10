"""Apply per-reviewer strictness and decisions.yml overrides to findings."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import yaml

from scripts.config import DEFAULT_STRICTNESS
from scripts.contract import Finding

_DEFAULT = DEFAULT_STRICTNESS


def _soften(f: Finding) -> Finding:
    """Cap severity at warning: error becomes warning, lower tiers stay."""
    return replace(f, severity="warning") if f.severity == "error" else f


def _excused(f: Finding, listed: set[str]) -> bool:
    # Match on the rule id; the per-run id test keeps old call sites working.
    return (f.rule_id is not None and f.rule_id in listed) or f.id in listed


def apply_strictness(
    findings: list[Finding],
    strictness_by_reviewer: dict[str, str],
    allowed_exceptions: dict[str, set[str]] | None = None,
) -> list[Finding]:
    exceptions = allowed_exceptions or {}
    out: list[Finding] = []
    for f in findings:
        level = strictness_by_reviewer.get(f.reviewer, _DEFAULT)
        if level == "aspirational":
            out.append(_soften(f))
        elif level == "pragmatic" and _excused(f, exceptions.get(f.reviewer, set())):
            out.append(_soften(f))
        else:  # strict, or pragmatic non-exception
            out.append(f)
    return out


def load_decisions(path: Path) -> dict:
    if not Path(path).exists():
        return {}
    data = yaml.safe_load(Path(path).read_text()) or {}
    return data if isinstance(data, dict) else {}


def apply_decisions(
    findings: list[Finding], decisions: dict, notes: list[str] | None = None
) -> list[Finding]:
    """Owner overrides from decisions.yml. A key is a finding fingerprint (the
    current form) or, in old files, a per-run finding id. The fingerprint is
    tried first, and a finding whose fingerprint has a key never consults the
    id key (a reused id cannot hijack it). A legacy id match appends a
    migrate note to `notes` when one is given."""
    raw = (decisions or {}).get("overrides", {}) or {}
    overrides = {str(k): v for k, v in raw.items()}
    out: list[Finding] = []
    for f in findings:
        if f.fingerprint and f.fingerprint in overrides:
            ov = overrides[f.fingerprint]
        else:
            ov = overrides.get(f.id)
            if ov and notes is not None:
                notes.append(f"legacy id-keyed override matched: {f.id}; migrate")
        if ov and not isinstance(ov, dict) and notes is not None:
            notes.append(f"override ignored (not a mapping): {f.fingerprint or f.id}")
        if isinstance(ov, dict) and ov:
            out.append(replace(
                f,
                severity=ov.get("severity", f.severity),
                reason=ov.get("reason", f.reason),
            ))
        else:
            out.append(f)
    return out
