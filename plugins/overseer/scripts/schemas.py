"""Typed JSON report contract for overseer agents (replaces the one-line
reply grammar formerly in ``dispatch.py``).

Every overseer agent still writes its detail to a file under
``<state_root>/dispatch/<card>/<stage>/`` (``scripts.dispatch.dispatch_dir``),
but its final message now carries exactly one fenced code block, info string
``overseer-report``, holding a JSON object shaped by one of the dataclasses
below. The ``SubagentStop`` report hook (``scripts/report_hook.py``) reads
only that block: findings, plans and evidence stay in the detail file body.

Stdlib only — hooks run under a plain ``python3`` with no pydantic. Kept
small and boring on purpose: one frozen dataclass per role, one parse
function per role, one function that turns a role's shape into a JSON
Schema document (``schemas/<role>.json``, checked for drift by
``tests/overseer/test_schemas.py``).
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 1
ROLES = ("planner", "implementer", "reviewer", "fixer", "verifier")
SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"

_STATUS: dict[str, tuple[str, ...]] = {
    "reviewer": ("approved", "found wanting"),
    "implementer": ("DONE", "DONE_WITH_CONCERNS", "BLOCKED", "NEEDS_CONTEXT"),
    "fixer": ("DONE", "DISPUTED", "BLOCKED"),
    "planner": ("DONE", "NEEDS_CONTEXT"),
    "verifier": ("PASS", "FAIL"),
}

# A block fence's info string may carry trailing attributes/whitespace; only
# the leading word is checked. Extracting the LAST match is what makes a
# report block that appears mid-message (a quoted example, say) harmless —
# only the agent's actual, final block is ever parsed.
_BLOCK_RE = re.compile(
    r"```overseer-report\b[^\n]*\n(?P<body>.*?)```", re.DOTALL,
)
_DISPATCH_RE = re.compile(r"/dispatch/(?P<card>[^/]+)/(?P<stage>[^/]+)/")


class ReportError(ValueError):
    """An agent's report block that does not fit its role's schema.

    ``errors`` is the full list of problems found — every field is checked,
    not just the first failure — so a block that is wrong in three ways is
    reported that way once, not bounced three times.
    """

    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors) or "invalid report")


@dataclass(frozen=True)
class LearnedFact:
    statement: str
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewerReport:
    schema: str
    card: str
    stage: str
    round: int
    slot: str
    status: str  # "approved" | "found wanting"
    critical: int
    important: int
    minor: int
    detail: Path
    learned: tuple[LearnedFact, ...] = ()
    role: str = "reviewer"


@dataclass(frozen=True)
class ImplementerReport:
    schema: str
    card: str
    stage: str
    chunk: int
    status: str  # DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
    tests_passed: int
    tests_total: int
    commits: tuple[str, ...]
    detail: Path
    learned: tuple[LearnedFact, ...] = ()
    role: str = "implementer"


@dataclass(frozen=True)
class FixerReport:
    schema: str
    card: str
    stage: str
    round: int
    status: str  # DONE | DISPUTED | BLOCKED
    fixed: int
    disputed: int
    commits: tuple[str, ...]
    detail: Path
    learned: tuple[LearnedFact, ...] = ()
    role: str = "fixer"


@dataclass(frozen=True)
class PlannerReport:
    schema: str
    card: str
    stage: str
    status: str  # DONE | NEEDS_CONTEXT
    detail: Path
    learned: tuple[LearnedFact, ...] = ()
    role: str = "planner"


@dataclass(frozen=True)
class VerifierReport:
    schema: str
    card: str
    stage: str
    status: str  # PASS | FAIL
    detail: Path
    learned: tuple[LearnedFact, ...] = ()
    role: str = "verifier"


Report = (
    ReviewerReport | ImplementerReport | FixerReport | PlannerReport | VerifierReport
)


# --- field-level checks — each appends to ``errors`` and returns None on
# failure, so callers can keep going and collect every problem at once. -----


def _check_str(obj: dict, key: str, errors: list[str]) -> str | None:
    if key not in obj:
        errors.append(f"missing field {key!r}")
        return None
    value = obj[key]
    if not isinstance(value, str) or not value:
        errors.append(f"field {key!r} must be a non-empty string, got {value!r}")
        return None
    return value


def _check_int(obj: dict, key: str, errors: list[str]) -> int | None:
    if key not in obj:
        errors.append(f"missing field {key!r}")
        return None
    value = obj[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        errors.append(f"field {key!r} must be a non-negative integer, got {value!r}")
        return None
    return value


def _check_enum(value: str | None, key: str, allowed: tuple[str, ...], errors: list[str]) -> None:
    if value is not None and value not in allowed:
        errors.append(f"field {key!r} must be one of {list(allowed)!r}, got {value!r}")


def _check_schema(obj: dict, role: str, errors: list[str]) -> None:
    schema = _check_str(obj, "schema", errors)
    expected = f"overseer.{role}/{SCHEMA_VERSION}"
    if schema is not None and schema != expected:
        errors.append(f"field 'schema' must be {expected!r}, got {schema!r}")


def _check_unknown(obj: dict, allowed: set[str], errors: list[str], *, where: str = "top level") -> None:
    extra = set(obj) - allowed
    if extra:
        errors.append(f"{where} has unknown field(s): {', '.join(sorted(extra))}")


def _check_detail(obj: dict, card: str | None, stage: str | None, errors: list[str]) -> Path | None:
    value = _check_str(obj, "detail", errors)
    if value is None:
        return None
    if not value.startswith("/"):
        errors.append("field 'detail' must be an absolute path")
        return None
    match = _DISPATCH_RE.search(value)
    if match is None or (card is not None and match["card"] != card) or (
        stage is not None and match["stage"] != stage
    ):
        errors.append(
            f"field 'detail' ({value!r}) is outside the dispatch directory for {card}/{stage}"
        )
        return None
    return Path(value)


def _check_commits(obj: dict, errors: list[str]) -> tuple[str, ...]:
    if "commits" not in obj:
        errors.append("missing field 'commits'")
        return ()
    value = obj["commits"]
    if not isinstance(value, list) or not all(isinstance(c, str) and c for c in value):
        errors.append("field 'commits' must be a list of non-empty strings")
        return ()
    return tuple(value)


def _check_counts(obj: dict, keys: tuple[str, str, str] | tuple[str, str], errors: list[str]) -> dict[str, int]:
    if "counts" not in obj:
        errors.append("missing field 'counts'")
        return {}
    counts = obj["counts"]
    if not isinstance(counts, dict):
        errors.append("field 'counts' must be an object")
        return {}
    _check_unknown(counts, set(keys), errors, where="counts")
    return {k: v for k in keys if (v := _check_int(counts, k, errors)) is not None}


def _check_tests(obj: dict, errors: list[str]) -> tuple[int | None, int | None]:
    if "tests" not in obj:
        errors.append("missing field 'tests'")
        return None, None
    tests = obj["tests"]
    if not isinstance(tests, dict):
        errors.append("field 'tests' must be an object")
        return None, None
    _check_unknown(tests, {"passed", "total"}, errors, where="tests")
    return _check_int(tests, "passed", errors), _check_int(tests, "total", errors)


def _check_learned(obj: dict, errors: list[str]) -> tuple[LearnedFact, ...]:
    if "learned" not in obj:
        errors.append("missing field 'learned'")
        return ()
    value = obj["learned"]
    if not isinstance(value, list):
        errors.append("field 'learned' must be a list")
        return ()
    facts: list[LearnedFact] = []
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"learned[{i}] must be an object")
            continue
        _check_unknown(item, {"statement", "tags"}, errors, where=f"learned[{i}]")
        statement = item.get("statement")
        if not isinstance(statement, str) or not statement:
            errors.append(f"learned[{i}].statement must be a non-empty string")
            continue
        tags = item.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            errors.append(f"learned[{i}].tags must be a list of strings")
            tags = []
        facts.append(LearnedFact(statement=statement, tags=tuple(tags)))
    return tuple(facts)


# --- one parse function per role --------------------------------------------


def _parse_reviewer(obj: dict) -> ReviewerReport:
    errors: list[str] = []
    allowed = {"schema", "card", "stage", "round", "slot", "status", "counts", "detail", "learned"}
    _check_unknown(obj, allowed, errors)
    _check_schema(obj, "reviewer", errors)
    card = _check_str(obj, "card", errors)
    stage = _check_str(obj, "stage", errors)
    round_no = _check_int(obj, "round", errors)
    slot = _check_str(obj, "slot", errors)
    status = _check_str(obj, "status", errors)
    _check_enum(status, "status", _STATUS["reviewer"], errors)
    counts = _check_counts(obj, ("critical", "important", "minor"), errors)
    detail = _check_detail(obj, card, stage, errors)
    learned = _check_learned(obj, errors)
    if errors:
        raise ReportError(errors)
    assert card and stage and slot and status and round_no is not None and detail is not None
    return ReviewerReport(
        schema=obj["schema"], card=card, stage=stage, round=round_no, slot=slot,
        status=status, critical=counts["critical"], important=counts["important"],
        minor=counts["minor"], detail=detail, learned=learned,
    )


def _parse_implementer(obj: dict) -> ImplementerReport:
    errors: list[str] = []
    allowed = {"schema", "card", "stage", "chunk", "status", "tests", "commits", "detail", "learned"}
    _check_unknown(obj, allowed, errors)
    _check_schema(obj, "implementer", errors)
    card = _check_str(obj, "card", errors)
    stage = _check_str(obj, "stage", errors)
    chunk = _check_int(obj, "chunk", errors)
    status = _check_str(obj, "status", errors)
    _check_enum(status, "status", _STATUS["implementer"], errors)
    passed, total = _check_tests(obj, errors)
    commits = _check_commits(obj, errors)
    detail = _check_detail(obj, card, stage, errors)
    learned = _check_learned(obj, errors)
    if errors:
        raise ReportError(errors)
    assert (
        card and stage and status and chunk is not None and passed is not None
        and total is not None and detail is not None
    )
    return ImplementerReport(
        schema=obj["schema"], card=card, stage=stage, chunk=chunk, status=status,
        tests_passed=passed, tests_total=total, commits=commits, detail=detail,
        learned=learned,
    )


def _parse_fixer(obj: dict) -> FixerReport:
    errors: list[str] = []
    allowed = {"schema", "card", "stage", "round", "status", "counts", "commits", "detail", "learned"}
    _check_unknown(obj, allowed, errors)
    _check_schema(obj, "fixer", errors)
    card = _check_str(obj, "card", errors)
    stage = _check_str(obj, "stage", errors)
    round_no = _check_int(obj, "round", errors)
    status = _check_str(obj, "status", errors)
    _check_enum(status, "status", _STATUS["fixer"], errors)
    counts = _check_counts(obj, ("fixed", "disputed"), errors)
    commits = _check_commits(obj, errors)
    detail = _check_detail(obj, card, stage, errors)
    learned = _check_learned(obj, errors)
    if errors:
        raise ReportError(errors)
    assert card and stage and status and round_no is not None and detail is not None
    return FixerReport(
        schema=obj["schema"], card=card, stage=stage, round=round_no, status=status,
        fixed=counts["fixed"], disputed=counts["disputed"], commits=commits,
        detail=detail, learned=learned,
    )


def _parse_planner(obj: dict) -> PlannerReport:
    errors: list[str] = []
    allowed = {"schema", "card", "stage", "status", "detail", "learned"}
    _check_unknown(obj, allowed, errors)
    _check_schema(obj, "planner", errors)
    card = _check_str(obj, "card", errors)
    stage = _check_str(obj, "stage", errors)
    status = _check_str(obj, "status", errors)
    _check_enum(status, "status", _STATUS["planner"], errors)
    detail = _check_detail(obj, card, stage, errors)
    learned = _check_learned(obj, errors)
    if errors:
        raise ReportError(errors)
    assert card and stage and status and detail is not None
    return PlannerReport(
        schema=obj["schema"], card=card, stage=stage, status=status, detail=detail,
        learned=learned,
    )


def _parse_verifier(obj: dict) -> VerifierReport:
    errors: list[str] = []
    allowed = {"schema", "card", "stage", "status", "detail", "learned"}
    _check_unknown(obj, allowed, errors)
    _check_schema(obj, "verifier", errors)
    card = _check_str(obj, "card", errors)
    stage = _check_str(obj, "stage", errors)
    status = _check_str(obj, "status", errors)
    _check_enum(status, "status", _STATUS["verifier"], errors)
    detail = _check_detail(obj, card, stage, errors)
    learned = _check_learned(obj, errors)
    if errors:
        raise ReportError(errors)
    assert card and stage and status and detail is not None
    return VerifierReport(
        schema=obj["schema"], card=card, stage=stage, status=status, detail=detail,
        learned=learned,
    )


_PARSERS: dict[str, Callable[[dict], Report]] = {
    "reviewer": _parse_reviewer,
    "implementer": _parse_implementer,
    "fixer": _parse_fixer,
    "planner": _parse_planner,
    "verifier": _parse_verifier,
}


def parse_report(role: str, obj: object) -> Report:
    """Parse a decoded JSON object into the role's Report dataclass.

    Raises ``ReportError`` carrying every problem found — unknown/missing
    fields, wrong types, bad enum values, or a ``detail`` path outside the
    dispatch directory named by ``card``/``stage``.
    """
    if role not in _PARSERS:
        raise ReportError([f"no report schema for role {role!r}"])
    if not isinstance(obj, dict):
        raise ReportError(["report must be a JSON object"])
    return _PARSERS[role](obj)


def extract_report_block(text: str) -> str | None:
    """The raw (unparsed) body of the LAST ```overseer-report fenced block in
    ``text``, or None if there isn't one. Nothing else in the message is
    inspected — findings, plans and evidence live in the detail file."""
    blocks = _BLOCK_RE.findall(text)
    return blocks[-1] if blocks else None


def parse_report_message(role: str, text: str) -> Report:
    """Extract the last ``overseer-report`` block from an agent's final
    message and parse it. Raises ``ReportError`` for a missing block, invalid
    JSON, or a block that fails the role's schema."""
    block = extract_report_block(text)
    if block is None:
        raise ReportError(["no ```overseer-report``` block found in the reply"])
    try:
        obj = json.loads(block)
    except json.JSONDecodeError as exc:
        raise ReportError([f"report block is not valid JSON: {exc}"]) from exc
    return parse_report(role, obj)


# --- JSON Schema generation (plugins/overseer/schemas/<role>.json) ---------


def _learned_schema() -> dict:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "statement": {"type": "string", "minLength": 1},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["statement"],
            "additionalProperties": False,
        },
    }


def _base(role: str) -> dict:
    return {
        "schema": {"const": f"overseer.{role}/{SCHEMA_VERSION}"},
        "card": {"type": "string", "minLength": 1},
        "stage": {"type": "string", "minLength": 1},
        "detail": {"type": "string", "minLength": 1, "description": "absolute path inside the card's dispatch directory"},
        "learned": _learned_schema(),
    }


def _counts_schema(*keys: str) -> dict:
    return {
        "type": "object",
        "properties": {k: {"type": "integer", "minimum": 0} for k in keys},
        "required": list(keys),
        "additionalProperties": False,
    }


def _object_schema(role: str, properties: dict, required: list[str]) -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"overseer.{role}/{SCHEMA_VERSION}",
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _reviewer_schema() -> dict:
    props = {
        **_base("reviewer"),
        "round": {"type": "integer", "minimum": 1},
        "slot": {"type": "string", "minLength": 1},
        "status": {"enum": list(_STATUS["reviewer"])},
        "counts": _counts_schema("critical", "important", "minor"),
    }
    required = ["schema", "card", "stage", "round", "slot", "status", "counts", "detail", "learned"]
    return _object_schema("reviewer", props, required)


def _implementer_schema() -> dict:
    props = {
        **_base("implementer"),
        "chunk": {"type": "integer", "minimum": 1},
        "status": {"enum": list(_STATUS["implementer"])},
        "tests": _counts_schema("passed", "total"),
        "commits": {"type": "array", "items": {"type": "string", "minLength": 1}},
    }
    required = ["schema", "card", "stage", "chunk", "status", "tests", "commits", "detail", "learned"]
    return _object_schema("implementer", props, required)


def _fixer_schema() -> dict:
    props = {
        **_base("fixer"),
        "round": {"type": "integer", "minimum": 1},
        "status": {"enum": list(_STATUS["fixer"])},
        "counts": _counts_schema("fixed", "disputed"),
        "commits": {"type": "array", "items": {"type": "string", "minLength": 1}},
    }
    required = ["schema", "card", "stage", "round", "status", "counts", "commits", "detail", "learned"]
    return _object_schema("fixer", props, required)


def _planner_schema() -> dict:
    props = {**_base("planner"), "status": {"enum": list(_STATUS["planner"])}}
    required = ["schema", "card", "stage", "status", "detail", "learned"]
    return _object_schema("planner", props, required)


def _verifier_schema() -> dict:
    props = {**_base("verifier"), "status": {"enum": list(_STATUS["verifier"])}}
    required = ["schema", "card", "stage", "status", "detail", "learned"]
    return _object_schema("verifier", props, required)


_SCHEMA_BUILDERS = {
    "reviewer": _reviewer_schema,
    "implementer": _implementer_schema,
    "fixer": _fixer_schema,
    "planner": _planner_schema,
    "verifier": _verifier_schema,
}


def json_schema(role: str) -> dict:
    if role not in _SCHEMA_BUILDERS:
        raise ValueError(f"no JSON Schema for role {role!r}")
    return _SCHEMA_BUILDERS[role]()


def schema_text(role: str) -> str:
    return json.dumps(json_schema(role), indent=2, sort_keys=True) + "\n"


def write_schemas(target: Path = SCHEMA_DIR) -> None:
    """Regenerate the committed ``schemas/<role>.json`` files. Run by hand
    after changing a role's shape; ``test_schemas.py`` fails on drift."""
    target.mkdir(parents=True, exist_ok=True)
    for role in ROLES:
        (target / f"{role}.json").write_text(schema_text(role))


if __name__ == "__main__":  # pragma: no cover — `python -m scripts.schemas`
    write_schemas()
