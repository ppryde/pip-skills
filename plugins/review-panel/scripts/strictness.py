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
        elif level == "pragmatic" and f.id in exceptions.get(f.reviewer, set()):
            out.append(_soften(f))
        else:  # strict, or pragmatic non-exception
            out.append(f)
    return out


def load_decisions(path: Path) -> dict:
    if not Path(path).exists():
        return {}
    data = yaml.safe_load(Path(path).read_text()) or {}
    return data if isinstance(data, dict) else {}


def apply_decisions(findings: list[Finding], decisions: dict) -> list[Finding]:
    overrides = (decisions or {}).get("overrides", {}) or {}
    out: list[Finding] = []
    for f in findings:
        ov = overrides.get(f.id)
        if ov:
            out.append(replace(
                f,
                severity=ov.get("severity", f.severity),
                reason=ov.get("reason", f.reason),
            ))
        else:
            out.append(f)
    return out
