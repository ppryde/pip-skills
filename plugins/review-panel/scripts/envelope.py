"""Adopt the pip-agents result envelope (MAPPING.md sections 1.1 and 1.2).

A seat's final message ends with one ```pip-agents-result block. `ingest` validates it with the vendored validator
(schema, persona, brief cross-checks; the result is rejected whole, never repaired) and adapts a valid envelope to the
shapes the rest of this plugin already reads: a reviewer payload for `parse_reviewer_result`, or a verdict map keyed
by claim id (= finding fingerprint) for `reconcile`. `Finding`, `collate` and `render_report` do not change."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from scripts.contract import RULE_ID_RE
from scripts.pip_agents import validator

# The only value translation: impact words to the severity words decisions.yml and strictness speak.
SEVERITY = {"critical": "error", "important": "warning", "minor": "info"}
_PATHLIKE = re.compile(r"^[\w@+.\-]+(?:/[\w@+.\-]+)*$")


@dataclass
class Ingested:
    ok: bool
    kind: str | None = None
    errors: list[str] = field(default_factory=list)
    payload: dict | None = None  # kind review: the reviewer payload
    verdicts: dict | None = None  # kind validate: {claim id: {verdict, reason}}
    seat: str | None = None
    status: str | None = None  # the envelope's own status: ok | partial | error
    seat_error: str | None = None
    injection_attempts: list[str] = field(default_factory=list)
    summary: str = ""


def _finding(f: dict, tier: str | None = None) -> dict:
    out = {
        "id": f["id"],
        "file": f["file"],
        "rule": f.get("rule") or f["claim"],  # rules lens states the rule; other lenses state what goes wrong
        "actual": f["evidence"],
        "severity": SEVERITY[f["severity"]],
        "category": f["category"],
        "suggestion": f["fix"],
    }
    if isinstance(f.get("line"), int) and f["line"] >= 1:  # 0 means the whole file
        out["line"] = f["line"]
    if f.get("citation"):
        out["citation"] = f["citation"]
    if tier:
        out["tier"] = tier
    return out


def _is_path(entry: str) -> bool:
    return bool(_PATHLIKE.match(entry)) and not RULE_ID_RE.match(entry) and not re.match(r"^L\d", entry)


def reviewer_payload(env: dict, seat: str) -> dict:
    """The legacy reviewer payload for one valid `review` envelope (the envelope is not modified)."""
    notes: list[str] = []
    notes += [f"unchecked: {x}" for x in env.get("unchecked", [])]
    notes += [f"out of lens: {x}" for x in env.get("out_of_lens", [])]
    notes += [f"injection: {x}" for x in env.get("injection_attempts", [])]
    if env["status"] == "error":
        return {"reviewer": seat, "findings": [], "clean_files": [], "notes": [f"seat error: {env['error']}"] + notes}
    p = env["payload"]
    findings = [_finding(f) for f in p["findings"]] + [_finding(f, "medium") for f in p["medium"]]
    flagged = {f["file"] for f in findings}
    clean = [c for c in env.get("checked", []) if isinstance(c, str) and _is_path(c) and c not in flagged]
    if p.get("rules_checked"):
        notes.insert(0, f"rules checked: {p['rules_checked']}")
    return {"reviewer": seat, "findings": findings, "clean_files": clean, "notes": notes}


def verdict_map(env: dict) -> dict:
    """`{claim id: {verdict, reason}}` from a valid `validate` envelope; a weakened claim's restatement joins the reason."""
    out: dict = {}
    for v in env["payload"]["verdicts"]:
        reason = v["reason"]
        if v.get("restated"):
            reason = f"{reason} (restated: {v['restated']})"
        out[v["id"]] = {"verdict": v["verdict"], "reason": reason}
    return out


def ingest(message: str, brief_text: str, persona: str) -> Ingested:
    """Validate `message` (a seat's final message) against its brief and adapt it. `persona` is the bare agent name
    (`reviewer-scope`, `validator`)."""
    vr = validator()
    try:
        brief = vr.parse_brief(brief_text)
    except ValueError as exc:
        return Ingested(False, errors=[f"brief: {exc}"])
    if brief.get("kind") == "review" and not brief.get("ref"):
        return Ingested(False, errors=["brief: a review brief needs `ref:` (the seat's bare name)"])
    env, errors = vr.parse_result(message, brief, persona)
    if errors or env is None:
        return Ingested(False, errors=errors or ["no result"])
    out = Ingested(True, kind=env["kind"], seat=env.get("ref"), status=env["status"],
                   injection_attempts=list(env.get("injection_attempts", [])), summary=env.get("summary", ""))
    if env["kind"] == "review":
        out.payload = reviewer_payload(env, brief["ref"])
        if env["status"] == "error":
            out.seat_error = env["error"]
    elif env["kind"] == "validate":
        out.verdicts = verdict_map(env)
    else:
        return Ingested(False, errors=[f"kind {env['kind']!r} is not a review-panel seat"])
    return out
