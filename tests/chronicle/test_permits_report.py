"""`chronicle permits` (permits PR 2): the report over a fixture store."""
from __future__ import annotations

import json
import time

import pytest

from scripts import ingest, permits_report, store
from scripts.cli import main

from .conftest import _assistant, _user

T0 = "2026-10-09T10:00:00.000Z"
V = "2.1.296"
SECRET = "SECRETARG-acme-4242"


def _agent(builder, agent_id, *, meta, calls, skill=None, version=V):
    """A subagent transcript: ``calls`` are (tool, input, text, is_error, permissionDecision)."""
    folder = builder.dir / builder.session_id / "subagents"
    folder.mkdir(parents=True, exist_ok=True)
    records = []
    extra = {"attributionSkill": skill} if skill else {}
    for i, (tool, inp, text, err, pd) in enumerate(calls):
        tid = f"{agent_id}-t{i}"
        records.append(_assistant(f"m-{tid}", ts=T0, session_id=builder.session_id, agent_id=agent_id,
                                  version=version, blocks=[
                                      {"type": "tool_use", "id": tid, "name": tool, "input": inp}],
                                  **extra))
        result = {"type": "tool_result", "tool_use_id": tid, "content": text}
        if err:
            result["is_error"] = True
        more = {"permissionDecision": pd} if pd else {}
        records.append(_user(f"u-{tid}", ts=T0, session_id=builder.session_id, version=version,
                             agentId=agent_id, isSidechain=True, content=[result], **more))
    path = folder / f"agent-{agent_id}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    path.with_suffix(".meta.json").write_text(json.dumps(meta))


CLASSIFIER_PD = {"decision": "reject", "source": "classifier", "reasonType": "classifier"}
USER_PD = {"decision": "accept", "source": "user_temporary"}


@pytest.fixture
def conn(builder):
    builder.turn("m0", T0, version=V).write()
    _agent(builder, "rev1", skill="overseer:orchestrate",
           meta={"agentType": "overseer:overseer-reviewer", "requestNonInteractive": True},
           calls=[
               ("Bash", {"command": "git status"}, "ok", False, {"decision": "accept", "source": "mode"}),
               ("Bash", {"command": f"cd x && git log | head --token {SECRET}"},
                "is isolated in the worktree: too complex to verify", True, None),
               ("Bash", {"command": "curl https://x.example"},
                ("denied by the Claude Code auto mode classifier. "
                 "Reason: [Modify Shared Resources]"), True, CLASSIFIER_PD),
               ("Read", {"file_path": "/a"}, "text", False, {"decision": "accept", "source": "mode"}),
           ])
    _agent(builder, "rev2", skill="overseer:orchestrate",
           meta={"agentType": "overseer:overseer-reviewer", "requestNonInteractive": False},
           calls=[("Bash", {"command": "pytest -q"}, "1 passed", False, USER_PD),
                  ("Bash", {"command": "pytest -q"}, "1 passed", False, USER_PD),
                  ("Bash", {"command": "false"}, "weird new wording", True, None)])
    _agent(builder, "adhoc", meta={"agentType": "wf-087-gate1b", "requestNonInteractive": True},
           calls=[("Bash", {"command": "ls"}, "ok", False, None)])
    # an old CLI: no permissionDecision, and its missing decision is not drift
    older = type(builder)(builder.projects, session_id="s-old")
    older.turn("mo", T0, version="2.1.200").write()
    _agent(older, "old", meta={"agentType": "Explore"}, version="2.1.200",
           calls=[("Read", {"file_path": "/a"}, "text", False, None)])
    c = store.connect()
    ingest.sync(c, [builder.projects])
    yield c
    c.close()


def _group(out, skill, agent_type):
    return next(g for g in out["groups"] if (g["skill"], g["agent_type"]) == (skill, agent_type))


class TestReport:
    def test_groups_count_outcomes_per_skill_and_type(self, conn):
        out = permits_report.report(conn)
        g = _group(out, "overseer:orchestrate", "overseer:overseer-reviewer")
        assert (g["agents"], g["calls"], g["ok"], g["errors"], g["denied"]) == (2, 7, 4, 1, 2)
        assert g["denied_by_cause"] == {"classifier": 1, "worktree-guard": 1}
        assert (g["prompts_total"], g["prompts_approved"]) == (2, 2)

    def test_prompts_and_denials_split_by_non_interactive(self, conn):
        g = _group(permits_report.report(conn), "overseer:orchestrate", "overseer:overseer-reviewer")
        assert g["by_mode"]["non-interactive"]["denied"] == 2
        assert g["by_mode"]["non-interactive"]["prompts_total"] == 0
        assert g["by_mode"]["interactive"]["prompts_total"] == 2
        assert g["non_interactive_agents"] == 1

    def test_adhoc_names_always_print_folded(self, conn):
        out = permits_report.report(conn)
        types = {g["agent_type"] for g in out["groups"]}
        assert "wf-087-gate1b" not in types and "(ad-hoc)" in types
        assert "wf-087-gate1b" not in json.dumps(out)
        only = permits_report.report(conn, agent_type="(ad-hoc)")
        assert [g["agent_type"] for g in only["groups"]] == ["(ad-hoc)"]

    def test_flagged_shapes_are_only_denied_or_prompted_and_carry_no_arguments(self, conn):
        out = permits_report.report(conn)
        bash = next(t for t in out["tools"] if t["tool"] == "Bash"
                    and t["agent_type"] == "overseer:overseer-reviewer")
        shapes = {f["shape"]: f for f in bash["flagged_shapes"]}
        assert set(shapes) == {"git log +compound", "curl", "pytest"}
        assert shapes["pytest"]["outcomes"] == {"prompted:approved": 2}
        assert shapes["pytest"]["approved_temporary"] == 2
        assert shapes["git log +compound"]["reasons"] == {"wt:too-complex": 1}
        assert shapes["curl"]["reasons"] == {"modify-shared-resources": 1}
        assert shapes["git log +compound"]["outcomes"] == {"denied:worktree-guard": 1}
        assert SECRET not in json.dumps(out)

    def test_tool_and_group_rows_carry_the_outcome_breakdown(self, conn):
        out = permits_report.report(conn)
        g = _group(out, "overseer:orchestrate", "overseer:overseer-reviewer")
        assert g["outcomes"]["denied:classifier"] == 1 and g["outcomes"]["error:other"] == 1
        bash = next(t for t in out["tools"] if t["tool"] == "Bash"
                    and t["agent_type"] == "overseer:overseer-reviewer")
        assert bash["outcomes"]["prompted:approved"] == 2

    def test_tool_totals_list_what_each_type_used(self, conn):
        out = permits_report.report(conn)
        used = {t["tool"] for t in out["tools"] if t["agent_type"] == "overseer:overseer-reviewer"}
        assert used == {"Bash", "Read"}

    def test_drift_counts_error_other_and_decisions_only_from_the_new_cli(self, conn):
        d = permits_report.report(conn)["drift"]
        assert d["error_other"] == 1 and d["calls"] == 9
        assert d["decision_since_cli"] == "2.1.295"
        # 8 calls on 2.1.296; the "old" CLI's call is not eligible. no_decision: the
        # worktree guard, the weird error, and the ad-hoc ls carry none.
        assert (d["decision_eligible"], d["no_decision"]) == (8, 3)

    def test_filters(self, conn):
        assert permits_report.report(conn, skill="nope")["groups"] == []
        out = permits_report.report(conn, skill="overseer:orchestrate")
        assert {g["skill"] for g in out["groups"]} == {"overseer:orchestrate"}
        assert permits_report.report(conn, since=time.time() + 10)["groups"] == []

    def test_main_agent_calls_are_not_counted(self, conn):
        out = permits_report.report(conn)
        assert sum(g["calls"] for g in out["groups"]) == 9      # nothing from the main loop

    def test_a_store_without_the_columns_says_so(self):
        import sqlite3
        c = sqlite3.connect(":memory:")
        c.execute("CREATE TABLE tool_calls (tool_name TEXT)")
        c.execute("CREATE TABLE agents (agent_id TEXT)")
        out = permits_report.report(c)
        assert out["supported"] is False and "sync" in out["note"]

    def test_text_rendering_has_the_three_sections(self, conn):
        text = permits_report.render_text(permits_report.report(conn))
        assert "PER SKILL / AGENT TYPE" in text and "FLAGGED SHAPES" in text and "DRIFT" in text
        assert "overseer:overseer-reviewer" in text and SECRET not in text


class TestCli:
    def test_json_flag_and_filters(self, conn, capsys):
        conn.close()
        assert main(["permits", "--json", "--skill", "overseer:orchestrate"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["supported"] is True and len(out["groups"]) == 1

    def test_default_output_is_text(self, conn, capsys):
        conn.close()
        assert main(["permits", "--since", "30d"]) == 0
        text = capsys.readouterr().out
        assert text.startswith("PER SKILL") or "PER SKILL" in text

    def test_days_and_since_are_exclusive_and_since_is_validated(self, conn, capsys):
        conn.close()
        with pytest.raises(SystemExit):
            main(["permits", "--days", "3", "--since", "30d"])
        with pytest.raises(SystemExit):
            main(["permits", "--since", "yesterdayish"])

    def test_no_store_is_reported_plainly(self, capsys):
        assert main(["permits", "--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["supported"] is False and "no store" in out["note"]
