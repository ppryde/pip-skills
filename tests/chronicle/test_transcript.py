import json

from scripts.transcript import (
    MAIN_AGENT,
    SYNTHETIC_MODEL,
    TASK_CHARS,
    fold,
    parse_reset_time,
    parse_ts,
)

from .conftest import _assistant, _limit_hit, _user

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

    def test_an_error_result_unpublishes_its_artifact_and_ignores_its_url(self):
        """A refused or invalid publish published nothing, even when its
        error text echoes an artifact url."""
        url = "https://claude.ai/code/artifact/f7ec8e3d-b032-4432-94a1-c81758132da3"
        other_url = "https://claude.ai/code/artifact/0000aaaa-b032-4432-94a1-c81758132da3"
        publishes = [
            {"type": "tool_use", "id": tid, "name": "Artifact", "input": {"file_path": f"/{tid}.html"}}
            for tid in ("ok", "bad", "odd")
        ]
        error_text = f"Refused: {other_url} belongs to someone else"
        lines = _lines(
            _assistant("m1", ts=T0, blocks=publishes),
            _user("r1", ts=T1, content=[
                {"type": "tool_result", "tool_use_id": "ok", "content": f"Published at {url}"},
                {"type": "tool_result", "tool_use_id": "bad", "content": error_text, "is_error": True},
                # A truthy but non-boolean is_error is NOT an error — only `is True` counts.
                {"type": "tool_result", "tool_use_id": "odd", "content": f"Published at {other_url}",
                 "is_error": "yes"},
            ], toolUseResult={}),
        )
        facts = fold(lines)
        assert facts.turns[("", "m1")].artifacts.keys() == {"ok", "odd"}
        assert facts.turns[("", "m1")].artifacts["ok"].url == url
        assert facts.turns[("", "m1")].artifacts["odd"].url == other_url
        assert (facts.results["ok"].is_error, facts.results["ok"].artifact_url) == (False, url)
        assert (facts.results["bad"].is_error, facts.results["bad"].artifact_url) == (True, None)
        assert (facts.results["odd"].is_error, facts.results["odd"].artifact_url) == (False, other_url)

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

    def test_the_no_newline_marker_is_not_counted_as_a_change(self):
        # git's `\ No newline at end of file` is the ONE non-change line that
        # actually appears in a `structuredPatch` hunk.
        facts = fold(_lines(self._result("t1", [
            {"lines": ["+real", "-gone", "\\ No newline at end of file"]},
        ])))
        edit = facts.file_edits["t1"]
        assert (edit.lines_added, edit.lines_removed) == (1, 1)

    def test_a_removed_line_that_looks_like_a_diff_header_still_counts(self):
        """This test used to assert the opposite, on a false premise.

        `structuredPatch` hunks carry only +/-/space-prefixed CONTENT — they
        never contain the `---`/`+++` file headers a full unified diff opens
        with, so the guard that skipped them caught nothing it was aimed at.
        What it DID catch was real work: a removed SQL comment arrives as
        `-` + `-- text` = `--- text`. A scan of 40,645 hunk lines from real
        transcripts found zero `+++` lines and 129 beginning `---`, every one
        of them a removed SQL comment — silently dropped from the churn
        feeding the Rework tile and the Files ranking."""
        facts = fold(_lines(self._result("t1", [
            {"lines": ["--- Import app events into EVENTS.", "-ordinary",
                       "+++i;", "+ordinary"]},
        ])))
        edit = facts.file_edits["t1"]
        assert (edit.lines_added, edit.lines_removed) == (2, 2)

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


class TestFileEditOwnership:
    """A file edit belongs to whoever made it. `tool_calls`, `artifacts` and
    `events` all record the real agent; `file_edits` used to write the main
    agent for every row, so no subagent could ever own one."""

    def _result(self, tool_use_id: str, *, added: int, removed: int, agent_id=None):
        record = {
            "type": "user", "uuid": f"r-{tool_use_id}", "sessionId": "s1",
            "timestamp": "2026-09-01T10:00:00.000Z", "cwd": "/repo",
            "gitBranch": "main", "version": "2.1.258", "entrypoint": "cli",
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tool_use_id, "content": "ok"}]},
            "toolUseResult": {
                "filePath": "/repo/x.py",
                "structuredPatch": [{"lines": ["+a"] * added + ["-b"] * removed}],
            },
        }
        if agent_id:
            record["agentId"] = agent_id
            record["isSidechain"] = True
        return record

    def test_an_edit_carries_the_agent_that_made_it(self):
        facts = fold([json.dumps(self._result("t1", added=3, removed=1, agent_id="a1"))],
                     default_agent="a1")
        assert facts.file_edits["t1"].agent_id == "a1"

    def test_a_main_loop_edit_carries_the_main_agent(self):
        facts = fold([json.dumps(self._result("t1", added=3, removed=1))])
        assert facts.file_edits["t1"].agent_id == MAIN_AGENT


class TestDiffLineCounting:
    """The hunk lines are already +/-/space-prefixed CONTENT — they are never
    the `---`/`+++` file headers a unified diff opens with, which
    `structuredPatch` does not carry at all."""

    def _patch(self, lines):
        return {
            "type": "user", "uuid": "r1", "sessionId": "s1",
            "timestamp": "2026-09-01T10:00:00.000Z", "cwd": "/repo",
            "gitBranch": "main", "version": "2.1.258", "entrypoint": "cli",
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
            "toolUseResult": {"filePath": "/repo/run.sh",
                              "structuredPatch": [{"lines": lines}]},
        }

    def test_counts_a_line_whose_own_text_starts_with_dashes(self):
        # Removing `--flag` from a shell script produces the hunk line
        # `-` + `--flag` = `---flag`, which the old header guard skipped.
        facts = fold([json.dumps(self._patch(["---flag", "-ordinary"]))])
        assert facts.file_edits["t1"].lines_removed == 2

    def test_counts_a_line_whose_own_text_starts_with_pluses(self):
        facts = fold([json.dumps(self._patch(["+++i;", "+ordinary"]))])
        assert facts.file_edits["t1"].lines_added == 2

    def test_still_ignores_gits_no_trailing_newline_marker(self):
        facts = fold([json.dumps(self._patch(["+a", "\\ No newline at end of file"]))])
        assert facts.file_edits["t1"].lines_added == 1


class TestStreamedUsage:
    """Claude Code writes one JSONL line per content block as a response
    streams, all sharing a message id — and the usage on the EARLY lines is a
    partial snapshot. Only the last line carries the finished totals."""

    def _line(self, out: int, block: str, thinking: int = 0):
        return json.dumps(_assistant(
            "m1", ts=T0, blocks=[{"type": block, "text": "x"}],
            usage={"input_tokens": 3, "cache_read_input_tokens": 1000,
                   "cache_creation_input_tokens": 200, "output_tokens": out,
                   "output_tokens_details": {"thinking_tokens": thinking}},
        ))

    def test_keeps_the_finished_output_count_not_the_first_snapshot(self):
        # Observed verbatim in a real subagent transcript: a message whose
        # lines read [3, 1337]. Taking the first under-counted that agent's
        # whole output by 21x (222 recorded against 4,702 actual).
        facts = fold([self._line(3, "thinking"), self._line(1337, "text")])
        turn = next(iter(facts.turns.values()))
        assert turn.output_tokens == 1337

    def test_keeps_the_finished_thinking_count_too(self):
        facts = fold([self._line(3, "thinking", thinking=2),
                      self._line(1337, "text", thinking=900)])
        assert next(iter(facts.turns.values())).thinking_tokens == 900

    def test_a_later_line_never_lowers_the_count(self):
        # Order is not guaranteed and a partial must never overwrite a total.
        facts = fold([self._line(1337, "text"), self._line(3, "thinking")])
        assert next(iter(facts.turns.values())).output_tokens == 1337

    def test_a_single_line_message_is_unchanged(self):
        facts = fold([self._line(40, "text", thinking=10)])
        turn = next(iter(facts.turns.values()))
        assert (turn.output_tokens, turn.thinking_tokens) == (40, 10)


class TestLimitHits:
    """A usage-limit banner is a SYNTHETIC assistant record — no API call
    happened — so it must be captured independently of ``turns``, which skips
    synthetic records outright (see ``_fold_assistant``)."""

    def test_session_limit_with_bare_time_reset(self):
        rec = _limit_hit("h1", ts=T0, text="You've hit your session limit · resets 11:50am (Europe/London)")
        facts = fold([json.dumps(rec)])
        assert len(facts.limit_hits) == 1
        hit = facts.limit_hits[0]
        assert hit.kind == "session"
        assert hit.model is None
        assert hit.reset_raw == "11:50am (Europe/London)"
        assert hit.raw_text == "You've hit your session limit · resets 11:50am (Europe/London)"
        # T0 is 10:00 UTC = 11:00 BST; "11:50am" that same day is still ahead
        # of the hit, so no day rollover.
        assert hit.resets_at == parse_ts("2026-09-01T11:50:00+01:00")

    def test_session_limit_never_becomes_a_turn(self):
        rec = _limit_hit("h1", ts=T0, text="You've hit your session limit · resets 11:50am (Europe/London)")
        facts = fold([json.dumps(rec)])
        assert facts.turns == {}

    def test_weekly_limit_with_dated_reset(self):
        rec = _limit_hit("h2", ts="2026-08-10T10:00:00.000Z",
                         text="You've hit your weekly limit · resets Aug 16 at 8pm (Europe/London)")
        hit = fold([json.dumps(rec)]).limit_hits[0]
        assert hit.kind == "weekly"
        assert hit.reset_raw == "Aug 16 at 8pm (Europe/London)"
        assert hit.resets_at == parse_ts("2026-08-16T20:00:00+01:00")

    def test_dated_reset_rolls_the_year_forward_when_the_date_has_passed(self):
        # A weekly reset stated in early January for a hit made in late
        # December names a date already behind the hit in the current year.
        rec = _limit_hit("h2b", ts="2026-12-30T10:00:00.000Z",
                         text="You've hit your weekly limit · resets Jan 2 at 8pm (Europe/London)")
        hit = fold([json.dumps(rec)]).limit_hits[0]
        assert hit.resets_at == parse_ts("2027-01-02T20:00:00+00:00")

    def test_monthly_spend_limit_has_no_reset_time(self):
        rec = _limit_hit("h3", ts=T0,
                         text="You've hit your monthly spend limit · raise it at claude.ai/settings/usage")
        hit = fold([json.dumps(rec)]).limit_hits[0]
        assert hit.kind == "monthly_spend"
        assert hit.reset_raw is None
        assert hit.resets_at is None

    def test_model_limit_captures_the_model_name(self):
        rec = _limit_hit("h4", ts=T0,
                         text="You've reached your Fable 5 limit. Run /usage-credits to continue or switch models with /model.")
        hit = fold([json.dumps(rec)]).limit_hits[0]
        assert hit.kind == "model"
        assert hit.model == "Fable 5"
        assert hit.resets_at is None

    def test_unrecognised_wording_is_kept_as_other_not_dropped(self):
        rec = _limit_hit("h5", ts=T0, text="You've hit some new kind of limit we've never seen")
        hit = fold([json.dumps(rec)]).limit_hits[0]
        assert hit.kind == "other"
        assert hit.model is None
        assert hit.raw_text == "You've hit some new kind of limit we've never seen"

    def test_other_api_errors_are_not_limit_hits(self):
        connection_drop = _assistant("m1", ts=T0, model=SYNTHETIC_MODEL,
                                     blocks=[{"type": "text",
                                              "text": "API Error: Connection closed mid-response."}],
                                     isApiErrorMessage=True, error="server_error", uuid="not-a-hit")
        login_expired = _assistant("m2", ts=T0, model=SYNTHETIC_MODEL,
                                   blocks=[{"type": "text", "text": "Login expired · Please run /login"}],
                                   isApiErrorMessage=True, error="authentication_failed", uuid="also-not")
        facts = fold([json.dumps(connection_drop), json.dumps(login_expired)])
        assert facts.limit_hits == []

    def test_ordinary_rate_limited_text_without_the_error_marker_is_ignored(self):
        # The banner is only recognised via Claude Code's own error markers —
        # a turn that merely MENTIONS a limit in its own text is not a hit.
        rec = _assistant("m1", ts=T0, blocks=[{"type": "text", "text": "You've hit your session limit"}])
        assert fold([json.dumps(rec)]).limit_hits == []

    def test_quota_limits_resets_at_is_preferred_over_text_parsing(self):
        rec = _limit_hit("h6", ts=T0, text="You've hit your session limit · resets 11:50am (Europe/London)",
                         quotaLimits={"resetsAt": 1234567890, "rateLimitType": "five_hour"})
        hit = fold([json.dumps(rec)]).limit_hits[0]
        assert hit.resets_at == 1234567890.0

    def test_subagent_hit_carries_its_agent_id(self):
        rec = _limit_hit("h7", ts=T0, text="You've hit your session limit · resets 11:50am (Europe/London)",
                         agent_id="worker-1")
        hit = fold([json.dumps(rec)]).limit_hits[0]
        assert hit.agent_id == "worker-1"

    def test_bare_hour_with_no_minutes(self):
        rec = _limit_hit("h8", ts=T0, text="You've hit your session limit · resets 11pm (Europe/London)")
        hit = fold([json.dumps(rec)]).limit_hits[0]
        assert hit.resets_at == parse_ts("2026-09-01T23:00:00+01:00")

    def test_bare_time_already_passed_today_rolls_to_tomorrow(self):
        # Hit at 10:00 UTC (11:00 BST); "resets 9am" has already happened
        # today, so the next occurrence is tomorrow morning.
        rec = _limit_hit("h9", ts=T0, text="You've hit your session limit · resets 9am (Europe/London)")
        hit = fold([json.dumps(rec)]).limit_hits[0]
        assert hit.resets_at == parse_ts("2026-09-02T09:00:00+01:00")


class TestParseResetTime:
    def test_no_timezone_is_unparseable(self):
        assert parse_reset_time("11:50am", parse_ts(T0)) is None

    def test_unknown_timezone_is_unparseable(self):
        assert parse_reset_time("11:50am (Nowhere/Fake)", parse_ts(T0)) is None

    def test_garbage_body_is_unparseable(self):
        assert parse_reset_time("sometime soon (Europe/London)", parse_ts(T0)) is None

    def test_none_is_unparseable(self):
        assert parse_reset_time(None, parse_ts(T0)) is None
