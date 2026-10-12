"""Validate a pip-agents brief and a persona's result message against the one contract.

Spec: plugins/pip-agents/contract/VALIDATOR.md (normative). Stdlib only; runs under `python3 -I`, so it
reads nothing from the current directory and finds the contract next to itself (`../contract`).

Library:
    parse_brief(text) -> dict                          raises ValueError (not a brief line, duplicate key)
    extract_block(message) -> dict                     raises ResultError (E_NO_BLOCK, E_BAD_JSON, E_NOT_OBJECT)
    parse_result(message, brief, persona) -> (result | None, [errors])
    check_brief(brief) -> [errors]
    unsupported_keywords(schema) -> [paths]            schema keywords outside the supported subset

CLI:
    python3 -I validate_result.py --brief FILE --message FILE --persona NAME
    python3 -I validate_result.py --brief-only FILE
stdout is one JSON object {"ok": bool, "kind": str|null, "errors": [str]}; exit 0 valid, 1 invalid, 2 usage or
unreadable file.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CONTRACT_DIR = Path(__file__).resolve().parent.parent / "contract"

BLOCK_RE = re.compile(r"^(`{3,}|~{3,})pip-agents-result[ \t]*\n(?P<body>.*?)^\1[ \t]*$", re.M | re.S)
OPENER_RE = re.compile(r"^(`{3,}|~{3,})pip-agents-result[ \t]*$", re.M)
CLAIMS_MAX_BYTES = 1_000_000  # a claims file is a short JSON list; refuse anything bigger, or not a regular file
OTHER_FENCE_RE = re.compile(r"^(?:`{3,}|~{3,})([A-Za-z0-9_-]+)", re.M)
LINE_RE = re.compile(r"^([a-z_]+): (.*)$")
INT_KEYS = ("limit", "timeout_ms")

# Keywords the checker implements. Anything else in a schema fails the suite (VALIDATOR.md).
SUPPORTED_KEYWORDS = frozenset({
    "type", "const", "enum", "required", "properties", "additionalProperties", "items", "minItems", "maxItems",
    "maxLength", "minimum", "maximum", "pattern", "$ref", "allOf", "anyOf", "not", "if", "then", "else",
    "dependentRequired",
})
ANNOTATION_KEYWORDS = frozenset({"$schema", "$id", "$defs", "title", "description", "x-hint", "x-lens", "x-persona"})

_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


class ResultError(ValueError):
    """The final message holds no usable result block. `code` is E_NO_BLOCK, E_BAD_JSON or E_NOT_OBJECT."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code


# ---- contract files -------------------------------------------------------------------------------------------

_cache: dict[str, object] = {}


def _load(name: str):
    if name not in _cache:
        _cache[name] = json.loads((CONTRACT_DIR / name).read_text(encoding="utf-8"))
    return _cache[name]


def result_schema() -> dict:
    return _load("result.schema.json")  # type: ignore[return-value]


def brief_schema() -> dict:
    return _load("brief.schema.json")  # type: ignore[return-value]


def personas() -> dict:
    return _load("personas.json")  # type: ignore[return-value]


# ---- the schema subset ----------------------------------------------------------------------------------------

def _is_type(v, t: str) -> bool:
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    return isinstance(v, _TYPES[t])


def _same(a, b) -> bool:
    """JSON equality that keeps booleans apart from numbers (True != 1) at every depth."""
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


def _check(v, s: dict, root: dict, path: str, errs: list[str]) -> None:
    if "$ref" in s:
        s = root["$defs"][s["$ref"].split("/")[-1]]
    if "const" in s and not _same(v, s["const"]):
        errs.append(f"{path}: expected {s['const']!r}")
    if "enum" in s and not any(_same(v, e) for e in s["enum"]):
        errs.append(f"{path}: {v!r} not in {s['enum']}")
    if "type" in s:
        ts = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(_is_type(v, t) for t in ts):
            errs.append(f"{path}: not {s['type']}")
            return
    if isinstance(v, str):
        if len(v) > s.get("maxLength", 10**9):
            errs.append(f"{path}: longer than {s['maxLength']}")
        if "pattern" in s and not re.search(s["pattern"], v):
            errs.append(f"{path}: does not match {s['pattern']}")
    if _is_type(v, "integer"):
        if v < s.get("minimum", -10**18) or v > s.get("maximum", 10**18):
            errs.append(f"{path}: out of range")
    if isinstance(v, list):
        if len(v) < s.get("minItems", 0) or len(v) > s.get("maxItems", 10**9):
            errs.append(f"{path}: item count {len(v)}")
        if "items" in s:
            for i, x in enumerate(v):
                _check(x, s["items"], root, f"{path}[{i}]", errs)
    if isinstance(v, dict):
        for k in s.get("required", []):
            if k not in v:
                errs.append(f"{path}: missing {k}")
        for k, deps in s.get("dependentRequired", {}).items():
            if k in v:
                errs += [f"{path}: {k} needs {d}" for d in deps if d not in v]
        props = s.get("properties", {})
        extra = s.get("additionalProperties", True)
        for k, x in v.items():
            if k in props:
                _check(x, props[k], root, f"{path}.{k}", errs)
            elif extra is False:
                errs.append(f"{path}: unknown field {k}")
            elif isinstance(extra, dict):
                _check(x, extra, root, f"{path}.{k}", errs)
    for sub in s.get("allOf", []):
        _check(v, sub, root, path, errs)
    if "anyOf" in s and not any(not _errs(v, x, root) for x in s["anyOf"]):
        errs.append(f"{path}: matches no anyOf branch")
    if "not" in s and not _errs(v, s["not"], root):
        errs.append(f"{path}: matches a forbidden shape")
    if "if" in s:
        branch = s.get("then") if not _errs(v, s["if"], root) else s.get("else")
        if branch:
            _check(v, branch, root, path, errs)


def _errs(v, s: dict, root: dict) -> list[str]:
    e: list[str] = []
    _check(v, s, root, "$", e)
    return e


def validate_schema(value, schema: dict) -> list[str]:
    """Errors of `value` against `schema` (the supported subset), paths rooted at `$`."""
    return _errs(value, schema, schema)


def unsupported_keywords(schema: dict) -> list[str]:
    """Paths of schema keywords outside SUPPORTED_KEYWORDS + ANNOTATION_KEYWORDS (empty: the checker covers it)."""
    bad: list[str] = []

    def walk(s, path: str) -> None:
        if not isinstance(s, dict):
            return
        for k, sub in s.items():
            here = f"{path}/{k}"
            if k not in SUPPORTED_KEYWORDS and k not in ANNOTATION_KEYWORDS:
                bad.append(here)
            elif k == "$defs":
                for name, d in sub.items():
                    walk(d, f"{here}/{name}")
            elif k == "properties":
                for name, d in sub.items():
                    walk(d, f"{here}/{name}")
            elif k == "additionalProperties":
                walk(sub, here)
            elif k in ("items", "not", "if", "then", "else"):
                walk(sub, here)
            elif k in ("allOf", "anyOf"):
                for i, d in enumerate(sub):
                    walk(d, f"{here}/{i}")

    walk(schema, "")
    return bad


# ---- brief ----------------------------------------------------------------------------------------------------

def parse_brief(text: str) -> dict:
    """One `key: value` line per field; blank lines ignored; a repeated key or any other line is an error."""
    out: dict = {}
    for raw in text.splitlines():
        if not raw.strip():
            continue
        m = LINE_RE.match(raw)
        if not m:
            raise ValueError(f"not a brief line: {raw[:60]!r}")
        key, val = m.groups()
        if key in out:
            raise ValueError(f"duplicate key {key}")
        out[key] = int(val) if key in INT_KEYS and val.isdigit() else val
    return out


def check_brief(brief: dict) -> list[str]:
    return [f"brief {e}" for e in validate_schema(brief, brief_schema())]


# ---- the result block -----------------------------------------------------------------------------------------

def extract_block(message: str) -> dict:
    """Decode the LAST ```pip-agents-result block of the message (the agent's final message only)."""
    message = message.replace("\r\n", "\n").replace("\r", "\n")
    blocks = list(BLOCK_RE.finditer(message))
    openers = list(OPENER_RE.finditer(message))
    if openers and (not blocks or openers[-1].start() > blocks[-1].start()):
        raise ResultError("E_NO_BLOCK", "the last ```pip-agents-result block is never closed (truncated message?)")
    if not blocks:
        found = sorted({m.group(1) for m in OTHER_FENCE_RE.finditer(message)})
        hint = f"found a ```{found[0]} block; " if found else "found no fenced block; "
        raise ResultError("E_NO_BLOCK", hint + "expected ```pip-agents-result")
    try:
        value = json.loads(blocks[-1].group("body"))
    except json.JSONDecodeError as exc:
        raise ResultError("E_BAD_JSON", str(exc)) from exc
    if not isinstance(value, dict):
        raise ResultError("E_NOT_OBJECT", "the block must hold a JSON object")
    return value


# ---- cross checks ---------------------------------------------------------------------------------------------

def _id_list(rules: str) -> list[str] | None:
    """Rule ids named by a brief's `rules:` value: the trailing `(<ids>)` group, else a bare id list.

    None when the value is a path with no id group. A path is anything with a `/` or `\\`, a drive letter, an
    `L<a>-<b>` range or a file extension; a bare id list holds only id-like tokens.
    """
    rules = rules.strip()
    m = re.search(r"\(([^)]*)\)\s*$", rules)
    if m:
        return [x for x in re.split(r"[,\s]+", m.group(1)) if x]
    tokens = [x for x in re.split(r"[,\s]+", rules) if x]
    if tokens and all(re.fullmatch(r"[A-Za-z0-9_.:-]+", x) and not re.search(r"\.[A-Za-z]{1,5}$", x) for x in tokens) \
            and not re.search(r"\bL\d+-\d+\b", rules):
        return tokens
    return None


def _names(value: str) -> set[str]:
    return {x for x in value.split(",") if x}


def _file_in_checked(file: str, checked: list[str]) -> bool:
    for c in checked:
        if c == file or (c.startswith(file) and c[len(file)] in " :#,("):
            return True
    return False


def _x_flags(schema: dict, kind: str) -> tuple[set[str], set[str], dict[str, str], dict[str, str]]:
    """(envelope keys, payload keys) marked x-persona false; payload and finding keys -> their x-lens."""
    env_off = {k for k, v in schema["properties"].items() if v.get("x-persona") is False}
    pay = schema["$defs"].get(kind, {}).get("properties", {})
    pay_off = {k for k, v in pay.items() if v.get("x-persona") is False}
    pay_lens = {k: v["x-lens"] for k, v in pay.items() if "x-lens" in v}
    find = schema["$defs"]["finding"]["properties"]
    find_lens = {k: v["x-lens"] for k, v in find.items() if "x-lens" in v}
    return env_off, pay_off, pay_lens, find_lens


def _review(brief: dict, res: dict, persona: dict, errs: list[str], schema: dict) -> None:
    p = res["payload"]
    lens = persona.get("lens")
    if p.get("lens") != lens:
        errs.append(f"payload.lens {p.get('lens')!r} is not the persona's lens {lens!r}")
    _, _, pay_lens, find_lens = _x_flags(schema, "review")
    for k, want in pay_lens.items():
        if k in p and want != lens:
            errs.append(f"payload.{k} belongs to lens {want}, not {lens}")
    items = [("findings", f) for f in p.get("findings", [])] + [("medium", f) for f in p.get("medium", [])]
    seen: set[str] = set()
    target = str(brief.get("target", "")).split()
    checked = [c for c in res.get("checked", []) if isinstance(c, str)]
    rule_ids = None
    if lens == "rules":
        if "rules" not in brief:
            errs.append("brief has no `rules:` line (lens rules needs it for the id and denominator checks)")
        else:
            rule_ids = _id_list(str(brief["rules"]))
    for where, f in items:
        fid = f.get("id", "?")
        for k, want in find_lens.items():
            if k in f and want != lens:
                errs.append(f"{where} {fid}: field {k} belongs to lens {want}, not {lens}")
        if lens != "rules":
            if fid in seen:
                errs.append(f"finding id {fid} repeated")
            seen.add(fid)
        file = f.get("file")
        if isinstance(file, str) and file not in target and not _file_in_checked(file, checked):
            errs.append(f"{where} {fid}: file {file} is in neither checked nor the brief's target")
        if rule_ids is not None and fid not in rule_ids:
            errs.append(f"{where} {fid}: not a rule id in the brief's rules")
    if lens == "rules" and res["status"] != "error":
        rc = p.get("rules_checked")
        if rc is None:
            errs.append("payload.rules_checked missing (lens rules)")
        elif rule_ids is not None:
            num, den = (int(x) for x in rc.split("/"))
            if den != len(rule_ids):
                errs.append(f"rules_checked denominator {den} is not the batch size {len(rule_ids)}")
            if num > den:
                errs.append(f"rules_checked numerator {num} exceeds {den}")
        for nid in p.get("n_a", []):
            if rule_ids is not None and nid not in rule_ids:
                errs.append(f"n_a id {nid} is not in the brief's rules")


def _claim_ids(brief: dict, claim_ids: list[str] | None, errs: list[str]) -> list[str] | None:
    if claim_ids is not None:
        return claim_ids
    try:
        path = Path(str(brief.get("claims", "")))
        if not path.is_file() or path.stat().st_size > CLAIMS_MAX_BYTES:  # regular files only: no FIFO, /dev/zero
            raise OSError("not a regular file within the size cap")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise TypeError("not a list")
        return [str(c["id"]) for c in data]
    except (OSError, ValueError, KeyError, TypeError):
        errs.append("claims file unreadable or not a JSON list of {id, ...}; verdict ids cannot be checked")
        return None


def _validate(brief: dict, res: dict, claim_ids: list[str] | None, errs: list[str]) -> None:
    verdicts = res["payload"].get("verdicts", [])
    for v in verdicts:
        reason = v.get("reason", "")
        if isinstance(reason, str) and reason.startswith("unverified:") and v.get("verdict") != "refuted":
            errs.append(f"{v.get('id')}: `unverified:` is only for refuted")
        if ("restated" in v) != (v.get("verdict") == "weakened"):
            errs.append(f"{v.get('id')}: restated present iff weakened")
    ids = [v.get("id") for v in verdicts]
    want = _claim_ids(brief, claim_ids, errs)
    if want is not None and ids != want:
        errs.append(f"verdict ids {ids} are not the claim ids {want} in input order, each once")
    if len(ids) != len(set(ids)):
        errs.append("claim id repeated")


def _locate(brief: dict, res: dict, errs: list[str]) -> None:
    p = res["payload"]
    limit = brief.get("limit", 200)
    hits = p.get("hits", [])
    if isinstance(limit, int) and len(hits) > limit:
        errs.append(f"hits {len(hits)} over limit {limit}")
    if isinstance(limit, int) and bool(p.get("truncated")) != (len(hits) == limit):
        errs.append("truncated must be true iff hits equal the limit")
    if set(p.get("counts", {})) != _names(str(brief.get("names", ""))):
        errs.append("counts keys differ from the brief's names")


def _run(brief: dict, res: dict, errs: list[str]) -> None:
    p = res["payload"]
    if p.get("command") != brief.get("run"):
        errs.append("command not verbatim")
    if set(p.get("counts", {})) != _names(str(brief.get("counts", ""))):
        errs.append("counts keys differ from the brief's counts")
    if p.get("out") not in (None, brief.get("out")):
        errs.append("out is neither null nor the brief's out")
    if "stderr_tail" in p and p.get("exit_code") == 0:
        errs.append("stderr_tail only when exit_code is non-zero or null")


def _plan(brief: dict, res: dict, errs: list[str]) -> None:
    p = res["payload"]
    steps = p.get("steps")
    if steps is not None and p.get("chunks") is not None and p["chunks"] != len(steps):
        errs.append(f"chunks {p['chunks']} is not the number of steps {len(steps)}")
    if p.get("outcome") == "done" and res.get("status") == "ok" and not steps:
        errs.append("a done plan from a persona lists its steps")
    if p.get("outcome") == "needs_context" and not p.get("questions"):
        errs.append("needs_context lists its questions")


def _change(brief: dict, res: dict, errs: list[str]) -> None:
    p = res["payload"]
    if p.get("tests_passed", 0) > p.get("tests_total", 0):
        errs.append("tests_passed exceeds tests_total")
    if p.get("outcome") == "done" and not p.get("commits"):
        errs.append("a done change names its commits")


def _test(brief: dict, res: dict, errs: list[str]) -> None:
    p = res["payload"]
    gates = p.get("gates", [])
    failed = bool(p.get("failures")) or any(g.get("exit_code") != 0 for g in gates)
    if p.get("outcome") == "pass" and failed:
        errs.append("outcome pass with a failing gate or listed failures")
    if p.get("outcome") == "fail" and not failed:
        errs.append("outcome fail with every gate at exit 0 and no failures")
    if "tests" in brief and [g.get("command") for g in gates] != [brief["tests"]]:
        errs.append("gates must be the brief's tests command, verbatim")


def _summary(brief: dict, res: dict, errs: list[str]) -> None:
    if res.get("status") == "ok" and not res["payload"].get("points"):
        errs.append("an ok summary has at least one point")


def _research(brief: dict, res: dict, errs: list[str]) -> None:
    p = res["payload"]
    if res.get("status") == "ok" and not p.get("sources"):
        errs.append("an ok research answer cites at least one source")


def cross_check(brief: dict, res: dict, persona: str, claim_ids: list[str] | None = None) -> list[str]:
    errs: list[str] = []
    schema = result_schema()
    meta = personas().get(persona)
    if res.get("persona") != persona:
        errs.append(f"persona {res.get('persona')!r} is not {persona!r}")
    if meta is None:
        errs.append(f"unknown persona {persona!r}")
    kind = res.get("kind")
    if kind != brief.get("kind"):
        errs.append("kind differs from the brief's")
    if meta is not None and kind != meta["kind"]:
        errs.append(f"kind {kind!r} is not {persona}'s kind {meta['kind']!r}")
    env_off, pay_off, _, _ = _x_flags(schema, str(kind))
    for k in sorted(env_off & set(res)):
        errs.append(f"field {k} is for adapters, never a persona result")
    if "ref" in brief:
        if res.get("ref") != brief["ref"]:
            errs.append("ref not echoed")
    elif "ref" in res:
        errs.append("ref given though the brief has none")
    status = res.get("status")
    if status == "error":
        if "error" not in res:
            errs.append("status error needs error")
        if "payload" in res:
            errs.append("status error carries no payload")
        return errs
    if "error" in res:
        errs.append("error only with status error")
    payload = res.get("payload")
    if not isinstance(payload, dict):
        errs.append("payload missing")
        return errs
    for k in sorted(pay_off & set(payload)):
        errs.append(f"payload.{k} is for adapters, never a persona result")
    if kind == "review" and meta is not None:
        _review(brief, res, meta, errs, schema)
    elif kind == "validate":
        _validate(brief, res, claim_ids, errs)
    elif kind == "locate":
        _locate(brief, res, errs)
    elif kind == "run":
        _run(brief, res, errs)
    elif kind in ("plan", "change", "test", "summary", "research"):
        {"plan": _plan, "change": _change, "test": _test, "summary": _summary, "research": _research}[kind](brief, res, errs)
    return errs


def parse_result(message: str, brief: dict, persona: str, claim_ids: list[str] | None = None):
    """(result, errors). result is None when no block could be decoded. All errors are collected.

    Rejects whole; never repairs. `injection_attempts` stays in the returned result for the lead to report.
    """
    try:
        res = extract_block(message)
    except ResultError as exc:
        return None, [str(exc)]
    errs = validate_schema(res, result_schema())
    errs += check_brief(brief)
    if not errs:
        errs += cross_check(brief, res, persona, claim_ids)
    return res, errs


# ---- CLI ------------------------------------------------------------------------------------------------------

def _emit(ok: bool, kind, errors: list[str]) -> None:
    print(json.dumps({"ok": ok, "kind": kind, "errors": errors}, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="validate_result.py", description=__doc__.split("\n")[0])
    ap.add_argument("--brief", help="brief file (with --message and --persona)")
    ap.add_argument("--message", help="the agent's final message file")
    ap.add_argument("--persona", help="agent name, for example reviewer-scope")
    ap.add_argument("--brief-only", metavar="FILE", help="validate one brief file and nothing else")
    ns = ap.parse_args(argv)
    full = (ns.brief, ns.message, ns.persona)
    if ns.brief_only is not None:
        if any(full):
            ap.error("--brief-only takes no other option")
    elif not all(full):
        ap.error("give --brief, --message and --persona, or --brief-only FILE")
    try:
        brief_text = Path(ns.brief_only or ns.brief).read_text(encoding="utf-8")
        message = Path(ns.message).read_text(encoding="utf-8") if ns.message else ""
    except (OSError, UnicodeDecodeError) as exc:
        _emit(False, None, [f"unreadable file: {exc}"])
        return 2
    try:
        brief = parse_brief(brief_text)
    except ValueError as exc:
        _emit(False, None, [str(exc)])
        return 1
    kind = brief.get("kind") if isinstance(brief.get("kind"), str) else None
    if ns.brief_only is not None:
        errors = check_brief(brief)
    else:
        _, errors = parse_result(message, brief, ns.persona)
    _emit(not errors, kind, errors)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
