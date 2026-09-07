import json

from scripts.transcript import TASK_CHARS, fold, parse_ts

from .conftest import _assistant, _user

T0 = "2026-09-01T10:00:00.000Z"
T1 = "2026-09-01T10:00:30.000Z"


def _lines(*records):
    return [json.dumps(r) for r in records]


class TestParseTs:
    def test_iso_z(self):
        assert parse_ts("2026-09-01T10:00:00.000Z") == 1788256800.0

    def test_epoch_passthrough(self):
        assert parse_ts(12.5) == 12.5

    def test_garbage(self):
        assert parse_ts("yesterday") is None
        assert parse_ts(None) is None
        assert parse_ts(True) is None


class TestFold:
    def test_split_blocks_count_as_one_turn(self):
        blocks = [
            {"type": "thinking", "thinking": "..."},
            {"type": "text", "text": "hi"},
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {}},
        ]
        lines = _lines(*[_assistant("m1", ts=T0, blocks=[b]) for b in blocks])
        facts = fold(lines)
        assert len(facts.turns) == 1
        turn = facts.turns[("", "m1")]
        assert turn.input_tokens == 3
        assert turn.cache_read_tokens == 1000
        assert turn.cache_creation_tokens == 200
        assert turn.output_tokens == 40
        assert turn.thinking_tokens == 10
        assert turn.context_tokens == 1203
        assert turn.tool_uses == [("t1", "Bash", None)]
        assert turn.model == "claude-opus-5"
        assert turn.request_id == "req-m1"

    def test_cache_ttl_split_and_cold_flag(self):
        warm = _assistant("w", ts=T0, usage={
            "input_tokens": 1, "cache_read_input_tokens": 900, "cache_creation_input_tokens": 100,
            "output_tokens": 5, "cache_creation": {"ephemeral_5m_input_tokens": 40, "ephemeral_1h_input_tokens": 60},
        })
        cold = _assistant("c", ts=T1, usage={
            "input_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 5000,
            "output_tokens": 5,
        })
        facts = fold(_lines(warm, cold))
        w, c = facts.turns[("", "w")], facts.turns[("", "c")]
        assert (w.cache_5m_tokens, w.cache_1h_tokens, w.cold) == (40, 60, False)
        assert (c.cache_5m_tokens, c.cache_1h_tokens, c.cold) == (0, 0, True)

    def test_prompts_vs_tool_results(self):
        lines = _lines(
            _user("u1", ts=T0, content="hello"),
            _user("u2", ts=T0, content=[{"type": "tool_result", "tool_use_id": "t", "content": "x"}],
                  toolUseResult={}),
            _user("u3", ts=T0, content=[{"type": "text", "text": "typed"}]),
            _user("u4", ts=T0, content="meta", isMeta=True),
            _user("u5", ts=T0, content="   "),
        )
        facts = fold(lines)
        prompts = [e.uuid for e in facts.events if e.kind == "prompt"]
        assert prompts == ["u1", "u3"]

    def test_compaction_markers(self):
        lines = _lines(
            _user("c1", ts=T0, content="summary...", isCompactSummary=True),
            {"type": "system", "subtype": "compact_boundary", "uuid": "c2", "timestamp": T1,
             "sessionId": "s1"},
        )
        kinds = [(e.uuid, e.kind) for e in fold(lines).events]
        assert kinds == [("c1", "compaction"), ("c2", "compaction")]

    def test_turn_duration_event(self):
        lines = _lines({"type": "system", "subtype": "turn_duration", "durationMs": 7300,
                        "uuid": "d1", "timestamp": T0, "sessionId": "s1"})
        event = fold(lines).events[0]
        assert (event.kind, event.value) == ("turn_duration", 7300)

    def test_synthetic_messages_are_not_turns(self):
        lines = _lines(_assistant("syn", ts=T0, model="<synthetic>"))
        assert fold(lines).turns == {}

    def test_identity_fields_and_timestamps(self):
        lines = _lines(
            _user("u1", ts=T0),
            _assistant("m1", ts=T1),
            {"type": "ai-title", "aiTitle": "  Fix the widget ", "sessionId": "s1"},
        )
        facts = fold(lines)
        assert facts.session_id == "s1"
        assert facts.cwd == "/repo"
        assert facts.git_branch == "main"
        assert facts.version == "2.1.258"
        assert facts.entrypoint == "cli"
        assert facts.title == "Fix the widget"
        assert facts.first_ts == parse_ts(T0)
        assert facts.last_ts == parse_ts(T1)

    def test_branch_follows_latest_record(self):
        lines = _lines(_user("u1", ts=T0, gitBranch="main"), _user("u2", ts=T1, gitBranch="feat"))
        assert fold(lines).git_branch == "feat"

    def test_subagent_records_do_not_move_main_timestamps(self):
        lines = _lines(_assistant("a1", ts="2026-09-01T09:00:00Z", agent_id="agent-x"))
        facts = fold(lines)
        assert facts.first_ts is None
        assert ("agent-x", "a1") in facts.turns

    def test_garbage_lines_are_skipped(self):
        facts = fold(["not json", "", "[]", json.dumps({"type": "user"})])
        assert facts.turns == {}
        assert facts.events == []


class TestToolResultsAndArtifacts:
    def test_result_size_and_time_are_captured(self):
        lines = _lines(
            _assistant("m1", ts=T0, blocks=[{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]),
            _user("r1", ts=T1, content=[{"type": "tool_result", "tool_use_id": "t1", "content": "x" * 500}],
                  toolUseResult={}),
        )
        facts = fold(lines)
        assert facts.results["t1"].chars == 500
        assert facts.results["t1"].ts == parse_ts(T1)
        assert facts.results["t1"].artifact_url is None

    def test_artifact_publish_pairs_with_its_url(self):
        url = "https://claude.ai/code/artifact/f7ec8e3d-b032-4432-94a1-c81758132da3"
        lines = _lines(
            _assistant("m1", ts=T0, blocks=[{"type": "tool_use", "id": "a1", "name": "Artifact",
                                            "input": {"file_path": "/x.html", "title": "Walkthrough",
                                                      "description": "A tour", "favicon": "🔔"}}]),
            _user("r1", ts=T1, content=[{"type": "tool_result", "tool_use_id": "a1",
                                         "content": f"Published /x.html at {url}\n\nLive subscription: arming"}],
                  toolUseResult={}),
        )
        facts = fold(lines)
        artifact = facts.turns[("", "m1")].artifacts["a1"]
        assert (artifact.title, artifact.description, artifact.favicon) == ("Walkthrough", "A tour", "🔔")
        assert artifact.url == url
        assert artifact.redeploy is False
        assert facts.results["a1"].artifact_url == url

    def test_title_falls_back_to_the_file_stem(self):
        lines = _lines(_assistant("m1", ts=T0, blocks=[
            {"type": "tool_use", "id": "a1", "name": "Artifact",
             "input": {"file_path": "/scratch/notifications-internals.html", "favicon": "🔔"}}]))
        assert fold(lines).turns[("", "m1")].artifacts["a1"].title == "notifications-internals"

    def test_redeploy_and_non_publish_actions(self):
        lines = _lines(_assistant("m1", ts=T0, blocks=[
            {"type": "tool_use", "id": "a1", "name": "Artifact",
             "input": {"file_path": "/x.html", "url": "https://claude.ai/code/artifact/abc"}},
            {"type": "tool_use", "id": "a2", "name": "Artifact", "input": {"action": "list"}},
            {"type": "tool_use", "id": "a3", "name": "Artifact",
             "input": {"action": "read", "url": "https://claude.ai/code/artifact/abc"}},
        ]))
        turn = fold(lines).turns[("", "m1")]
        assert set(turn.artifacts) == {"a1"}
        assert turn.artifacts["a1"].redeploy is True
        assert len(turn.tool_uses) == 3  # still counted as tool calls


class TestQualifier:
    def test_skill_call_keeps_its_skill_name(self):
        facts = fold(_lines(_assistant("m1", ts=T0, blocks=[
            {"type": "tool_use", "id": "t1", "name": "Skill",
             "input": {"skill": "tribunal:reckoning", "args": "355"}},
        ])))
        assert facts.turns[("", "m1")].tool_uses == [("t1", "Skill", "tribunal:reckoning")]

    def test_agent_call_keeps_its_subagent_type_not_its_prompt(self):
        facts = fold(_lines(_assistant("m1", ts=T0, blocks=[
            {"type": "tool_use", "id": "t1", "name": "Agent",
             "input": {"subagent_type": "Explore", "prompt": "a very long prompt"}},
        ])))
        assert facts.turns[("", "m1")].tool_uses == [("t1", "Agent", "Explore")]

    def test_ordinary_tool_keeps_no_qualifier(self):
        facts = fold(_lines(_assistant("m1", ts=T0, blocks=[
            {"type": "tool_use", "id": "t1", "name": "Bash",
             "input": {"command": "ls -la /secret"}},
        ])))
        assert facts.turns[("", "m1")].tool_uses == [("t1", "Bash", None)]


class TestFileEdits:
    """Claude Code writes a real unified diff on every edit result
    (`toolUseResult.structuredPatch`). The fold kept only its length."""

    def _result(self, tool_id, patch, *, file_path="/repo/a.py", kind=None):
        tur = {"filePath": file_path, "structuredPatch": patch}
        if kind:
            tur["type"] = kind
        return {
            "type": "user", "uuid": f"u-{tool_id}", "sessionId": "s1",
            "timestamp": T0,
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tool_id, "content": "ok"}]},
            "toolUseResult": tur,
        }

    def test_counts_added_and_removed_lines_from_the_patch(self):
        facts = fold(_lines(self._result("t1", [
            {"oldStart": 1, "oldLines": 3, "newStart": 1, "newLines": 4,
             "lines": [" keep", "-gone", "+new", "+also new"]},
            {"oldStart": 20, "oldLines": 1, "newStart": 21, "newLines": 1,
             "lines": ["-old", "+fresh"]},
        ])))
        edit = facts.file_edits["t1"]
        assert edit.file_path == "/repo/a.py"
        assert (edit.lines_added, edit.lines_removed) == (3, 2)
        assert edit.operation == "edit"

    def test_a_diff_marker_line_is_not_counted_as_a_change(self):
        # `---`/`+++` headers and the `\ No newline` marker must not inflate
        # the count; only real +/- content lines are changes.
        facts = fold(_lines(self._result("t1", [
            {"lines": ["--- a/x", "+++ b/x", "+real", "-gone",
                       "\\ No newline at end of file"]},
        ])))
        edit = facts.file_edits["t1"]
        assert (edit.lines_added, edit.lines_removed) == (1, 1)

    def test_a_write_records_its_operation(self):
        facts = fold(_lines(self._result("t1", [
            {"lines": ["+one", "+two"]}], file_path="/repo/new.py", kind="create")))
        assert facts.file_edits["t1"].operation == "create"

    def test_a_result_without_a_patch_records_no_file_edit(self):
        facts = fold(_lines({
            "type": "user", "uuid": "u1", "sessionId": "s1", "timestamp": T0,
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
            "toolUseResult": {"stdout": "hi", "stderr": ""},
        }))
        assert facts.file_edits == {}
        assert facts.results["t1"].chars == 2   # still measured as before


class TestAttribution:
    """Claude Code stamps what was in scope onto the ASSISTANT record — so
    attribution lands on turns, which carry usage, and therefore accounts for
    tokens rather than merely counting invocations."""

    def _turn(self, **attrs):
        return _assistant("m1", ts=T0, **attrs)

    def test_a_plugin_skill_attributes_both(self):
        facts = fold(_lines(self._turn(attributionSkill="tribunal:reckoning",
                                       attributionPlugin="tribunal")))
        turn = facts.turns[("", "m1")]
        assert turn.skill == "tribunal:reckoning"
        assert turn.plugin == "tribunal"

    def test_a_builtin_skill_has_no_plugin(self):
        # Claude Code sends attributionPlugin: null for a built-in. That is
        # the system stating "not from a plugin", not a gap to be inferred.
        facts = fold(_lines(self._turn(attributionSkill="code-review",
                                       attributionPlugin=None)))
        turn = facts.turns[("", "m1")]
        assert turn.skill == "code-review"
        assert turn.plugin is None

    def test_a_subagent_turn_attributes_its_type(self):
        facts = fold(_lines(self._turn(attributionAgent="Explore")))
        assert facts.turns[("", "m1")].agent_type == "Explore"

    def test_a_skill_running_inside_a_subagent_attributes_both(self):
        facts = fold(_lines(self._turn(attributionAgent="general-purpose",
                                       attributionSkill="superpowers:test-driven-development",
                                       attributionPlugin="superpowers")))
        turn = facts.turns[("", "m1")]
        assert turn.agent_type == "general-purpose"
        assert turn.plugin == "superpowers"

    def test_mcp_scope_is_attributed(self):
        facts = fold(_lines(self._turn(attributionMcpServer="claude.ai Snowflake",
                                       attributionMcpTool="sql_exec_tool")))
        assert facts.turns[("", "m1")].mcp_server == "claude.ai Snowflake"

    def test_an_unattributed_turn_carries_nothing(self):
        facts = fold(_lines(self._turn()))
        turn = facts.turns[("", "m1")]
        assert (turn.skill, turn.plugin, turn.agent_type, turn.mcp_server) == (None,) * 4


class TestSubagentTask:
    """A subagent's transcript opens with the task it was handed. That text
    is the only human-legible name a subagent has — its id is a hash — so it
    is lifted verbatim and truncated, never summarised. No model is involved:
    this is `json.loads` and a slice, like every other fact here."""

    def _task(self, content, agent_id="a1"):
        return fold(_lines(_user("u1", ts=T0, content=content, agentId=agent_id,
                                 isSidechain=True)),
                    default_agent=agent_id).task

    def test_the_first_prompt_of_a_subagent_file_is_its_task(self):
        assert self._task("Find the auth flow in this repo") == "Find the auth flow in this repo"

    def test_whitespace_is_normalised_so_a_rail_row_stays_one_line(self):
        assert self._task("Find the auth flow\n\n  and report back") == \
            "Find the auth flow and report back"

    def test_a_long_task_is_truncated_with_an_ellipsis(self):
        task = self._task("x" * 500)
        assert len(task) <= TASK_CHARS + 1
        assert task.endswith("…")

    def test_a_teammate_message_prefers_its_own_summary(self):
        # Agent-team prompts arrive wrapped in `<teammate-message>`, whose
        # summary attribute is already the short label a rail wants. The raw
        # text would otherwise read as markup.
        assert self._task(
            '<teammate-message teammate_id="team-lead" summary="Verify code ground-truth claims">'
            " You are in a worktree...</teammate-message>"
        ) == "Verify code ground-truth claims"

    def test_block_content_is_read_as_well_as_a_bare_string(self):
        assert self._task([{"type": "text", "text": "Audit the ORM"}]) == "Audit the ORM"

    def test_only_the_first_prompt_counts(self):
        facts = fold(_lines(
            _user("u1", ts=T0, content="First task", agentId="a1", isSidechain=True),
            _user("u2", ts=T0, content="A later message", agentId="a1", isSidechain=True),
        ), default_agent="a1")
        assert facts.task == "First task"

    def test_a_main_transcript_records_no_task(self):
        # The main agent was handed nothing; its first prompt is the user
        # talking, which the session title already covers.
        assert fold(_lines(_user("u1", ts=T0, content="hello"))).task is None

    def test_a_tool_result_is_not_mistaken_for_a_task(self):
        facts = fold(_lines(_user("u1", ts=T0, agentId="a1", isSidechain=True,
                                  content=[{"type": "tool_result", "tool_use_id": "t1",
                                            "content": "output"}],
                                  toolUseResult={"stdout": "output"})),
                     default_agent="a1")
        assert facts.task is None
