from __future__ import annotations

import copy
import hashlib
import json
import os

import pytest

from conftest import CONTRACT, EXAMPLES

PERSONA_OF = {"review": "reviewer-scope", "validate": "validator", "locate": "explorer", "run": "gatekeeper"}
VALIDATE_IDS = ["c1", "c2"]


def block(res, fence="```pip-agents-result"):
    return f"headline\n\n{fence}\n{json.dumps(res)}\n```\n"


def example(kind):
    brief = (EXAMPLES / f"{kind}.brief.txt").read_text()
    res = json.loads(next(iter(__import__("re").finditer(r"^```pip-agents-result\n(.*?)^```", (EXAMPLES / f"{kind}.result.md").read_text(), __import__("re").M | __import__("re").S))).group(1))
    return brief, res


def claim_ids_of(res):
    return [v["id"] for v in res["payload"]["verdicts"]] if res["kind"] == "validate" else None


def test_examples_valid(vr):
    for res_file in sorted(EXAMPLES.glob("*.result.md")):
        kind = res_file.name.split(".")[0]
        if kind == "error":
            continue
        brief_file = EXAMPLES / f"{kind}.brief.txt"
        assert not vr.check_brief(vr.parse_brief(brief_file.read_text())), brief_file
        brief = vr.parse_brief(brief_file.read_text())
        if kind not in PERSONA_OF:  # plan, change, test come from adapters, not personas: schema only
            res = vr.extract_block(res_file.read_text())
            assert not vr.validate_schema(res, vr.result_schema()), res_file
            continue
        persona = PERSONA_OF[kind]
        _, res = example(kind)
        _, errs = vr.parse_result(res_file.read_text(), brief, persona, claim_ids_of(res))
        assert errs == [], (res_file, errs)


def test_error_example_valid(vr):
    brief = vr.parse_brief("brief: pip-agents/1\nkind: review\nref: puritan-ddd-2\ntarget: /t/diff.patch\nrules: /r/doc.md L1-10 (R1,R2)\n")
    _, errs = vr.parse_result((EXAMPLES / "error.result.md").read_text(), brief, "reviewer-rules")
    assert errs == []


def test_every_kind_has_examples(vr):
    for kind in vr.result_schema()["properties"]["kind"]["enum"]:
        assert (EXAMPLES / f"{kind}.brief.txt").is_file(), kind
        assert (EXAMPLES / f"{kind}.result.md").is_file(), kind
    assert (EXAMPLES / "error.result.md").is_file()


RULES_BRIEF = "brief: pip-agents/1\nkind: review\nref: b1\ntarget: /t/diff.patch\nrules: /r/doc.md L1-40 (R1,R2,R3)\n"


def rules_res(**payload):
    pay = {"lens": "rules", "findings": [], "medium": [], "rules_checked": "3/3", "n_a": []}
    pay.update(payload)
    return {"result": "pip-agents/1", "kind": "review", "persona": "reviewer-rules", "ref": "b1", "status": "ok",
            "summary": "s", "checked": ["/t/diff.patch"], "unchecked": [], "out_of_lens": [], "injection_attempts": [],
            "payload": pay}


def rfinding(**kw):
    f = {"id": "R1", "rule": "r", "file": "/t/diff.patch", "line": 3, "severity": "minor", "category": "c",
         "claim": "c", "evidence": "e", "fix": "f", "citation": "doc.md"}
    f.update(kw)
    return f


def _mutate(kind, fn):
    brief, res = example(kind)
    res = copy.deepcopy(res)
    fn(res)
    return brief, block(res), PERSONA_OF[kind], claim_ids_of(example(kind)[1])


NEGATIVE = {
    "error_with_status_ok": ("review", lambda r: r.update(error="boom"), "forbidden shape"),
    "missing_payload": ("review", lambda r: r.pop("payload"), "payload"),
    "unknown_finding_field": ("review", lambda r: r["payload"]["findings"][0].update(confidence="high"), "unknown field confidence"),
    "unknown_lens": ("review", lambda r: r["payload"].update(lens="style"), "lens"),
    "lens_general_from_persona": ("review", lambda r: r["payload"].update(lens="general"), "not the persona's lens"),
    "restated_on_confirmed": ("validate", lambda r: r["payload"]["verdicts"][0].update(verdict="confirmed"), "restated present iff weakened"),
    "unverified_on_confirmed": ("validate", lambda r: r["payload"]["verdicts"][1].update(verdict="confirmed"), "only for refuted"),
    "verdict_ids_out_of_order": ("validate", lambda r: r["payload"]["verdicts"].reverse(), "input order"),
    "counts_keys_differ_from_names": ("locate", lambda r: r["payload"]["counts"].update(extra=1), "counts keys"),
    "command_not_verbatim": ("run", lambda r: r["payload"].update(command="python3 other.py"), "command not verbatim"),
    "detail_in_persona_result": ("review", lambda r: r.update(detail="/tmp/x"), "adapters"),
    "outcome_in_persona_payload": ("review", lambda r: r["payload"].update(outcome="approved"), "adapters"),
    "lens_field_on_wrong_lens": ("review", lambda r: r["payload"]["findings"][0].update(trigger="when empty"), "belongs to lens correctness"),
    "ref_not_echoed": ("review", lambda r: r.update(ref="other"), "ref not echoed"),
    "other_persona_name": ("review", lambda r: r.update(persona="reviewer-security"), "persona"),
}


@pytest.mark.parametrize("case", sorted(NEGATIVE))
def test_negative_cases(vr, case):
    kind, fn, want = NEGATIVE[case]
    brief_text, msg, persona, ids = _mutate(kind, fn)
    _, errs = vr.parse_result(msg, vr.parse_brief(brief_text), persona, ids)
    assert any(want in e for e in errs), (case, errs)


def test_negative_validate_unknown_ids_and_dupes(vr):
    brief, res = example("validate")
    res = copy.deepcopy(res)
    _, errs = vr.parse_result(block(res), vr.parse_brief(brief), "validator", ["c1", "zz"])
    assert any("input order" in e for e in errs)
    _, errs = vr.parse_result(block(res), vr.parse_brief(brief), "validator", None)  # claims file absent
    assert any("claims file unreadable" in e for e in errs)


def test_negative_hits_over_limit(vr):
    brief, res = example("locate")
    res = copy.deepcopy(res)
    brief = brief.replace("limit: 200", "limit: 1")
    res["payload"]["hits"] = [{"path": "a.py", "line": 1}, {"path": "b.py", "line": 2}]
    _, errs = vr.parse_result(block(res), vr.parse_brief(brief), "explorer")
    assert any("over limit" in e for e in errs)


def test_negative_commit_id_whitespace(vr):
    res = {"result": "pip-agents/1", "kind": "change", "persona": "x", "status": "ok", "summary": "s", "checked": [],
           "unchecked": [], "out_of_lens": [], "injection_attempts": [],
           "payload": {"outcome": "done", "commits": ["abc def"], "tests_passed": 1, "tests_total": 1}}
    assert any("commits" in e for e in vr.validate_schema(res, vr.result_schema()))


def test_negative_blocks(vr):
    brief, res = example("review")
    b = vr.parse_brief(brief)
    _, errs = vr.parse_result(block(res, "```json"), b, "reviewer-scope")
    assert errs and "E_NO_BLOCK" in errs[0] and "```json" in errs[0]
    _, errs = vr.parse_result("no block at all", b, "reviewer-scope")
    assert "E_NO_BLOCK" in errs[0]
    bad = copy.deepcopy(res)
    bad["status"] = "nope"
    two = block(res) + "\n" + block(bad)
    _, errs = vr.parse_result(two, b, "reviewer-scope")
    assert errs, "the last block wins, and it is invalid"
    reversed_ = block(bad) + "\n" + block(res)
    _, errs = vr.parse_result(reversed_, b, "reviewer-scope")
    assert errs == [], "a quoted invalid example earlier in the message is harmless"
    _, errs = vr.parse_result("```pip-agents-result\n{not json\n```\n", b, "reviewer-scope")
    assert "E_BAD_JSON" in errs[0]
    _, errs = vr.parse_result("```pip-agents-result\n[1]\n```\n", b, "reviewer-scope")
    assert "E_NOT_OBJECT" in errs[0]
    tilde = block(res, "~~~pip-agents-result").replace("\n```\n", "\n~~~\n")
    _, errs = vr.parse_result(tilde, b, "reviewer-scope")
    assert errs == []


def test_negative_briefs(vr):
    with pytest.raises(ValueError):
        vr.parse_brief("brief: pip-agents/1\nkind: review\nplease review the following rule text")
    with pytest.raises(ValueError):
        vr.parse_brief("brief: pip-agents/1\nkind: review\nkind: review\n")
    errs = vr.check_brief(vr.parse_brief("brief: pip-agents/1\nkind: review\ntarget: /t\nrun: ls\n"))
    assert errs, "run: on a review brief"
    assert vr.check_brief(vr.parse_brief("brief: pip-agents/1\nkind: locate\nquestion: q\ntarget: /t\nlimit: many\n"))


def test_rules_lens_checks(vr):
    b = vr.parse_brief(RULES_BRIEF)
    ok = rules_res(findings=[rfinding(id="R1", line=3), rfinding(id="R1", line=9)], rules_checked="3/3", n_a=["R3"])
    assert vr.parse_result(block(ok), b, "reviewer-rules")[1] == []  # a rule id may repeat on different lines
    _, errs = vr.parse_result(block(rules_res(rules_checked="2/4")), b, "reviewer-rules")
    assert any("denominator" in e for e in errs)
    _, errs = vr.parse_result(block(rules_res(findings=[rfinding(id="R9")])), b, "reviewer-rules")
    assert any("not a rule id" in e for e in errs)
    _, errs = vr.parse_result(block(rules_res(n_a=["R7"])), b, "reviewer-rules")
    assert any("n_a" in e for e in errs)
    bad = rules_res()
    del bad["payload"]["rules_checked"]
    _, errs = vr.parse_result(block(bad), b, "reviewer-rules")
    assert any("rules_checked" in e for e in errs)
    _, errs = vr.parse_result(block(rules_res(findings=[rfinding(file="/other.py")])), b, "reviewer-rules")
    assert any("neither checked nor" in e for e in errs)


def test_adapter_shapes_valid(vr):
    base = {"result": "pip-agents/1", "persona": "adapter", "status": "ok", "summary": "s", "checked": [],
            "unchecked": [], "out_of_lens": [], "injection_attempts": []}
    shapes = [
        {"kind": "review", "payload": {"lens": "general", "findings": [], "medium": [], "outcome": "approved",
                                         "counts": {"critical": 0, "important": 1, "minor": 2}}},
        {"kind": "plan", "payload": {"outcome": "done"}},
        {"kind": "change", "payload": {"outcome": "done", "commits": ["abc123"], "tests_passed": 0, "tests_total": 0}},
    ]
    for shape in shapes:
        assert vr.validate_schema({**base, **shape}, vr.result_schema()) == [], shape["kind"]


def test_schema_keyword_subset(vr):
    for name in ("result.schema.json", "brief.schema.json"):
        schema = json.loads((CONTRACT / name).read_text())
        assert vr.unsupported_keywords(schema) == [], name

    def hints(node):
        if isinstance(node, dict):
            if "x-hint" in node:
                assert len(node["x-hint"]) <= 30, node["x-hint"]
            for v in node.values():
                hints(v)
        elif isinstance(node, list):
            for v in node:
                hints(v)

    hints(json.loads((CONTRACT / "result.schema.json").read_text()))
    assert vr.unsupported_keywords({"type": "object", "format": "date"}) == ["/format"]


def test_revision_hash():
    rev, digest = (CONTRACT / "REVISION").read_text().split()
    want = hashlib.sha256((CONTRACT / "brief.schema.json").read_bytes() + (CONTRACT / "result.schema.json").read_bytes()).hexdigest()
    assert digest == want, "a schema edit needs a REVISION bump (and a rebuild)"
    assert rev == "1.0"


def test_persona_kind_must_match_tools_table(vr):
    brief, res = example("review")
    res = json.loads(json.dumps(res))
    res["persona"] = "explorer"
    _, errs = vr.parse_result(block(res), vr.parse_brief(brief), "explorer")
    assert any("kind" in e for e in errs)


# ---- round-1 review fixes (A2, A4, A5, A6, B2) --------------------------------------------------------------

def _fill(skel):
    """Fill a generated skeleton literally: keep placeholders, take the first of `a|b` enums, empty object lists."""
    def go(v, key=""):
        if isinstance(v, dict):
            return {k: go(x, k) for k, x in v.items()}
        if isinstance(v, list):
            if v and isinstance(v[0], dict) and key != "verdicts":
                return []  # findings, hits: a clean run has none (verdicts need one per claim)
            return [go(x, key) for x in v]
        if key == "rules_checked":
            return "1/1"
        if isinstance(v, str) and "|" in v:
            return v.split("|")[0]
        return v
    return go(skel)


@pytest.mark.parametrize("name", ["explorer", "gatekeeper", "reviewer-correctness", "reviewer-rules", "reviewer-scope",
                                  "reviewer-security", "validator"])
def test_skeleton_filled_literally_validates(vr, ba, name):
    pmap = json.loads((CONTRACT / "personas.json").read_text())
    skel = json.loads(ba.skeleton(vr.result_schema(), pmap[name]["kind"], name, pmap[name].get("lens")))
    assert "error" not in skel and "ref" not in skel  # conditional fields are prose, never a literal fill
    res = _fill(skel)
    assert res["status"] == "ok"
    assert vr.validate_schema(res, vr.result_schema()) == []
    brief = vr.parse_brief(f"brief: pip-agents/1\nkind: {pmap[name]['kind']}\n")
    errs = vr.cross_check(brief, res, name, claim_ids=["<claim id>"])
    assert not any("error only with status error" in e or "ref given" in e or "ref not echoed" in e for e in errs), errs


def test_claims_file_read_from_disk(vr, tmp_path):
    brief, res = example("validate")
    res = copy.deepcopy(res)
    ids = [v["id"] for v in res["payload"]["verdicts"]]
    claims = tmp_path / "claims.json"
    b = vr.parse_brief(brief.replace(brief.split("claims: ")[1].split("\n")[0], str(claims)))
    claims.write_text(json.dumps([{"id": i, "claim": "x"} for i in ids]))
    assert vr.parse_result(block(res), b, "validator")[1] == []  # match
    claims.write_text(json.dumps([{"id": i} for i in ids[::-1]]))
    assert any("input order" in e for e in vr.parse_result(block(res), b, "validator")[1])  # mismatch
    claims.write_text(json.dumps({"id": "c1"}))
    assert any("claims file unreadable" in e for e in vr.parse_result(block(res), b, "validator")[1])  # not a list
    claims.write_text("[1, 2")
    assert any("claims file unreadable" in e for e in vr.parse_result(block(res), b, "validator")[1])  # bad JSON


def test_claims_file_size_cap_and_regular_only(vr, tmp_path):
    brief, res = example("validate")
    claims = tmp_path / "claims.json"
    b = vr.parse_brief(brief.replace(brief.split("claims: ")[1].split("\n")[0], str(claims)))
    claims.write_text(json.dumps([{"id": "c1", "pad": "x" * (vr.CLAIMS_MAX_BYTES + 10)}]))
    assert any("claims file unreadable" in e for e in vr.parse_result(block(res), b, "validator")[1])
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)  # opening a FIFO with no writer would hang: it must be refused before any open
    b["claims"] = str(fifo)
    assert any("claims file unreadable" in e for e in vr.parse_result(block(res), b, "validator")[1])
    b["claims"] = "/dev/zero"
    assert any("claims file unreadable" in e for e in vr.parse_result(block(res), b, "validator")[1])


@pytest.mark.parametrize("rules,want", [
    ("/r/doc.md L1-40 (R1,R2,R3)", ["R1", "R2", "R3"]),
    ("/r/doc (v2).md L1-10 (R1,R2)", ["R1", "R2"]),  # trailing group, not the first parenthesis
    ("R1,R2 R3", ["R1", "R2", "R3"]),
    ("rel/doc.md", None), ("doc.md", None), ("C:\\x\\doc.md", None), ("/r/doc.md L1-40", None),
])
def test_id_list(vr, rules, want):
    assert vr._id_list(rules) == want


def test_rules_lens_needs_rules_line(vr):
    b = vr.parse_brief("brief: pip-agents/1\nkind: review\nref: b1\ntarget: /t/diff.patch\n")
    _, errs = vr.parse_result(block(rules_res(rules_checked="1/1")), b, "reviewer-rules")
    assert any("no `rules:` line" in e for e in errs)


def test_rules_with_parenthesised_path_accepts_real_findings(vr):
    b = vr.parse_brief("brief: pip-agents/1\nkind: review\nref: b1\ntarget: /t/diff.patch\nrules: /r/doc (v2).md L1-10 (R1,R2,R3)\n")
    res = rules_res(findings=[rfinding(id="R1")], rules_checked="3/3")
    assert vr.parse_result(block(res), b, "reviewer-rules")[1] == []


def test_unterminated_final_block_is_an_error(vr):
    brief, res = example("review")
    b = vr.parse_brief(brief)
    truncated = block(res) + "\n```pip-agents-result\n" + json.dumps(res)[:40]
    _, errs = vr.parse_result(truncated, b, "reviewer-scope")
    assert errs and "E_NO_BLOCK" in errs[0] and "never closed" in errs[0]
    _, errs = vr.parse_result("```pip-agents-result\n" + json.dumps(res), b, "reviewer-scope")
    assert errs and "never closed" in errs[0]


def test_crlf_message(vr):
    brief, res = example("review")
    b = vr.parse_brief(brief)
    crlf = block(res).replace("\n", "\r\n")
    assert vr.parse_result(crlf, b, "reviewer-scope")[1] == []
    _, errs = vr.parse_result(block(res, "```json").replace("\n", "\r\n"), b, "reviewer-scope")
    assert errs and "E_NO_BLOCK" in errs[0] and "```json" in errs[0]


def test_const_and_enum_are_type_strict(vr):
    assert vr.validate_schema(1, {"const": True})
    assert vr.validate_schema(True, {"const": 1})
    assert vr.validate_schema(True, {"enum": [1, 2]})
    assert vr.validate_schema(1, {"enum": [True]})
    assert vr.validate_schema(1, {"const": 1}) == [] and vr.validate_schema("a", {"enum": ["a", "b"]}) == []
