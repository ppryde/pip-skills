import io
import json
import sys

from scripts.cli import main


def run(repo, *argv):
    return main(["--root", str(repo), *argv])


class TestBegin:
    def test_begin_activates_manual_without_tmux(self, repo, capsys, monkeypatch):
        monkeypatch.delenv("TMUX", raising=False)
        assert run(repo, "begin") == 0
        assert "manual" in capsys.readouterr().out
        from scripts import state as st
        assert st.is_active(repo)

    def test_begin_reports_auto_with_tmux(self, repo, capsys, monkeypatch):
        monkeypatch.setenv("TMUX", "/tmp/x,1,0")
        assert run(repo, "begin") == 0
        assert "auto" in capsys.readouterr().out


class TestConfigAndContext:
    def test_config_get_default(self, repo, capsys):
        assert run(repo, "config", "get", "context.threshold") == 0
        assert capsys.readouterr().out.strip() == "35"

    def test_config_set_invalid_returns_1(self, repo, capsys):
        assert run(repo, "config", "set", "context.mode", "bogus") == 1
        assert "context.mode" in capsys.readouterr().err

    def test_context_unknown_without_transcript(self, repo, capsys, monkeypatch):
        monkeypatch.setenv("HOME", str(repo / "empty-home"))
        assert run(repo, "context") == 0
        assert "ctx unknown" in capsys.readouterr().out


class TestPauseResume:
    def test_pause_then_resume(self, repo, capsys):
        run(repo, "begin")
        assert run(repo, "pause") == 0
        from scripts import state as st
        assert st.is_paused(repo)
        assert run(repo, "resume") == 0
        assert not st.is_paused(repo)


class TestHandover:
    def test_notes_only_snapshot_off(self, repo, capsys):
        run(repo, "begin")
        assert run(repo, "handover", "--no-snapshot", "--notes", "keep the auth spike") == 0
        from scripts import state as st
        assert st.clear_flag(repo).exists()
        handoff = st.read_handoff(repo)
        assert "keep the auth spike" in handoff
        assert "Session snapshot" not in handoff  # snapshot suppressed

    def test_snapshot_included_by_default(self, repo):
        run(repo, "begin")
        assert run(repo, "handover", "--notes", "x") == 0
        from scripts import state as st
        assert "Session snapshot" in st.read_handoff(repo)

    def test_content_file_stdin(self, repo, monkeypatch):
        run(repo, "begin")
        monkeypatch.setattr(sys, "stdin", io.StringIO("ROLLUP FROM OVERSEER"))
        assert run(repo, "handover", "--no-snapshot", "--content-file", "-") == 0
        from scripts import state as st
        handoff = st.read_handoff(repo)
        assert "ROLLUP FROM OVERSEER" in handoff
        assert "Session snapshot" not in handoff

    def test_refuses_empty(self, repo, capsys):
        run(repo, "begin")
        assert run(repo, "handover", "--no-snapshot") == 1
        assert "nothing to hand over" in capsys.readouterr().err

    def test_refused_when_not_begun(self, repo, capsys):
        assert run(repo, "handover", "--notes", "x") == 1
        assert "vigil begin" in capsys.readouterr().err

    def test_missing_content_file_refused(self, repo, capsys):
        run(repo, "begin")
        assert run(repo, "handover", "--no-snapshot", "--content-file", "/no/such/file") == 1
        assert "content-file" in capsys.readouterr().err

    def test_armed_announces_auto_under_tmux(self, repo, capsys, monkeypatch):
        monkeypatch.setenv("TMUX", "/tmp/x,1,0")
        run(repo, "begin")
        assert run(repo, "handover", "--notes", "x") == 0
        out = capsys.readouterr().out
        assert "armed — auto" in out
        assert "/clear via tmux" in out

    def test_armed_announces_manual_without_tmux(self, repo, capsys, monkeypatch):
        monkeypatch.delenv("TMUX", raising=False)
        run(repo, "begin")
        assert run(repo, "handover", "--notes", "x") == 0
        out = capsys.readouterr().out
        assert "armed — manual" in out
        assert "type /clear" in out

    def test_inline_embeds_file_content(self, repo, tmp_path):
        run(repo, "begin")
        doc = tmp_path / "notes.md"
        doc.write_text("REMOTE MUST-READ CONTENT")
        assert run(repo, "handover", "--no-snapshot", "--inline", str(doc)) == 0
        from scripts import state as st
        handoff = st.read_handoff(repo)
        assert "REMOTE MUST-READ CONTENT" in handoff
        assert str(doc) in handoff

    def test_inline_repeatable(self, repo, tmp_path):
        run(repo, "begin")
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        a.write_text("FIRST DOC")
        b.write_text("SECOND DOC")
        assert run(repo, "handover", "--no-snapshot",
                   "--inline", str(a), "--inline", str(b)) == 0
        from scripts import state as st
        handoff = st.read_handoff(repo)
        assert "FIRST DOC" in handoff
        assert "SECOND DOC" in handoff

    def test_inline_missing_file_refused(self, repo):
        run(repo, "begin")
        assert run(repo, "handover", "--no-snapshot", "--inline", "/no/such/file") == 1


class TestNudgeHook:
    def _stdin(self, monkeypatch, payload):
        import io
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))

    def _set_census(self, monkeypatch, repo, pct):
        store = repo / "census" / "status.json"
        monkeypatch.setenv("CENSUS_STORE", str(store))
        store.parent.mkdir(parents=True, exist_ok=True)
        import os
        import time
        store.write_text(json.dumps({
            "sessions": {"s1": {
                "worktree_cwd": os.path.realpath(str(repo)),
                "updated_at": time.time(),
                "payload": {"context_window": {"used_percentage": pct}},
            }}
        }))

    def test_nudges_when_all_preconditions_met(self, repo, capsys, monkeypatch):
        from scripts import state as st
        st.begin(repo)
        self._set_census(monkeypatch, repo, 40)
        self._stdin(monkeypatch, {"cwd": str(repo)})
        assert run(repo, "nudge-hook") == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
        assert "40%" in payload["hookSpecificOutput"]["additionalContext"]
        assert "35%" in payload["hookSpecificOutput"]["additionalContext"]
        assert st.gate_active(repo) is True

    def test_writes_gate_exactly_once_per_cycle(self, repo, capsys, monkeypatch):
        from scripts import state as st
        st.begin(repo)
        self._set_census(monkeypatch, repo, 40)
        self._stdin(monkeypatch, {"cwd": str(repo)})
        assert run(repo, "nudge-hook") == 0
        assert capsys.readouterr().out.strip() != ""
        # second turn, still over threshold: gate holds, no re-nudge
        self._stdin(monkeypatch, {"cwd": str(repo)})
        assert run(repo, "nudge-hook") == 0
        assert capsys.readouterr().out.strip() == ""

    def test_silent_under_threshold(self, repo, capsys, monkeypatch):
        from scripts import state as st
        st.begin(repo)
        self._set_census(monkeypatch, repo, 10)
        self._stdin(monkeypatch, {"cwd": str(repo)})
        assert run(repo, "nudge-hook") == 0
        assert capsys.readouterr().out.strip() == ""
        assert st.gate_active(repo) is False

    def test_silent_when_gated(self, repo, capsys, monkeypatch):
        from scripts import state as st
        st.begin(repo)
        st.set_gate(repo)
        self._set_census(monkeypatch, repo, 40)
        self._stdin(monkeypatch, {"cwd": str(repo)})
        assert run(repo, "nudge-hook") == 0
        assert capsys.readouterr().out.strip() == ""
        assert st.gate_active(repo) is True  # unchanged: existing gate held

    def test_silent_when_paused(self, repo, capsys, monkeypatch):
        from scripts import state as st
        st.begin(repo)
        st.pause(repo)
        self._set_census(monkeypatch, repo, 40)
        self._stdin(monkeypatch, {"cwd": str(repo)})
        assert run(repo, "nudge-hook") == 0
        assert capsys.readouterr().out.strip() == ""
        assert st.gate_active(repo) is False  # no gate written when silent

    def test_silent_during_cooldown(self, repo, capsys, monkeypatch):
        from scripts import state as st
        st.begin(repo)
        st.request_clear(repo, "H")
        st.consume_clear_flag(repo)  # sets cooldown
        assert st.cooldown_active(repo) is True
        self._set_census(monkeypatch, repo, 40)
        self._stdin(monkeypatch, {"cwd": str(repo)})
        assert run(repo, "nudge-hook") == 0
        assert capsys.readouterr().out.strip() == ""
        assert st.gate_active(repo) is False  # no gate written when silent

    def test_silent_when_inactive(self, repo, capsys, monkeypatch):
        from scripts import state as st
        self._set_census(monkeypatch, repo, 40)
        self._stdin(monkeypatch, {"cwd": str(repo)})
        assert run(repo, "nudge-hook") == 0
        assert capsys.readouterr().out.strip() == ""
        assert st.gate_active(repo) is False  # no gate written when silent

    def test_silent_when_ctx_unknown(self, repo, capsys, monkeypatch):
        from scripts import state as st
        st.begin(repo)
        monkeypatch.setenv("CENSUS_STORE", str(repo / "absent.json"))
        monkeypatch.setenv("HOME", str(repo / "empty-home"))
        self._stdin(monkeypatch, {"cwd": str(repo)})
        assert run(repo, "nudge-hook") == 0
        assert capsys.readouterr().out.strip() == ""
        assert st.gate_active(repo) is False

    def test_remote_mode_adds_inline_guidance(self, repo, capsys, monkeypatch):
        from scripts import state as st
        st.begin(repo)
        run(repo, "config", "set", "context.mode", "remote")
        capsys.readouterr()
        self._set_census(monkeypatch, repo, 40)
        self._stdin(monkeypatch, {"cwd": str(repo)})
        assert run(repo, "nudge-hook") == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert "--inline" in payload["hookSpecificOutput"]["additionalContext"]

    def test_local_mode_omits_inline_guidance(self, repo, capsys, monkeypatch):
        from scripts import state as st
        st.begin(repo)
        self._set_census(monkeypatch, repo, 40)
        self._stdin(monkeypatch, {"cwd": str(repo)})
        assert run(repo, "nudge-hook") == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert "--inline" not in payload["hookSpecificOutput"]["additionalContext"]

    def test_nudges_from_post_tool_use_payload(self, repo, capsys, monkeypatch):
        # Unattended runs receive no UserPromptSubmit — PostToolUse fires mid-turn
        # inside the agentic loop instead, so the trigger must fire from it too.
        from scripts import state as st
        st.begin(repo)
        self._set_census(monkeypatch, repo, 40)
        self._stdin(monkeypatch, {"cwd": str(repo), "hook_event_name": "PostToolUse"})
        assert run(repo, "nudge-hook") == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
        assert "40%" in payload["hookSpecificOutput"]["additionalContext"]
        assert st.gate_active(repo) is True

    def test_nudges_from_explicit_user_prompt_submit_payload(self, repo, capsys, monkeypatch):
        from scripts import state as st
        st.begin(repo)
        self._set_census(monkeypatch, repo, 40)
        self._stdin(monkeypatch, {"cwd": str(repo), "hook_event_name": "UserPromptSubmit"})
        assert run(repo, "nudge-hook") == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"

    def test_garbage_hook_event_name_defaults_to_user_prompt_submit(
        self, repo, capsys, monkeypatch,
    ):
        # A non-string (or otherwise unparseable) hook_event_name must not crash
        # the hook and must still nudge — defaulting to the original event name.
        from scripts import state as st
        st.begin(repo)
        self._set_census(monkeypatch, repo, 40)
        self._stdin(monkeypatch, {"cwd": str(repo), "hook_event_name": 12345})
        assert run(repo, "nudge-hook") == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
        assert st.gate_active(repo) is True

    def test_missing_hook_event_name_defaults_to_user_prompt_submit(
        self, repo, capsys, monkeypatch,
    ):
        from scripts import state as st
        st.begin(repo)
        self._set_census(monkeypatch, repo, 40)
        self._stdin(monkeypatch, {"cwd": str(repo)})
        assert run(repo, "nudge-hook") == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"

    def test_gate_suppresses_second_nudge_across_mixed_events(
        self, repo, capsys, monkeypatch,
    ):
        # The gate must hold across a mixed sequence: a PostToolUse-triggered
        # nudge must silence a subsequent UserPromptSubmit in the same cycle —
        # this is what keeps PostToolUse registration non-chatty.
        from scripts import state as st
        st.begin(repo)
        self._set_census(monkeypatch, repo, 40)
        self._stdin(monkeypatch, {"cwd": str(repo), "hook_event_name": "PostToolUse"})
        assert run(repo, "nudge-hook") == 0
        assert capsys.readouterr().out.strip() != ""
        self._stdin(monkeypatch, {"cwd": str(repo), "hook_event_name": "UserPromptSubmit"})
        assert run(repo, "nudge-hook") == 0
        assert capsys.readouterr().out.strip() == ""


class TestClearArmedHook:
    def _stdin(self, monkeypatch, payload):
        import io
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))

    def test_prints_armed_when_armed(self, repo, capsys, monkeypatch):
        from scripts import state as st
        st.begin(repo)
        st.request_clear(repo, "H")
        self._stdin(monkeypatch, {"cwd": str(repo)})
        assert run(repo, "clear-armed-hook") == 0
        assert capsys.readouterr().out.strip() == "ARMED"
        assert st.clear_flag(repo).exists()  # not consumed

    def test_silent_when_not_armed(self, repo, capsys, monkeypatch):
        from scripts import state as st
        st.begin(repo)
        self._stdin(monkeypatch, {"cwd": str(repo)})
        assert run(repo, "clear-armed-hook") == 0
        assert capsys.readouterr().out.strip() == ""


class TestHookBackends:
    def _stdin(self, monkeypatch, payload):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))

    def test_stop_hook_dispatches_when_armed(self, repo, capsys, monkeypatch):
        from scripts import state as st
        st.begin(repo)
        st.request_clear(repo, "H")
        self._stdin(monkeypatch, {"cwd": str(repo)})
        assert run(repo, "stop-hook") == 0
        assert "DISPATCH_CLEAR" in capsys.readouterr().out
        assert not st.clear_flag(repo).exists()

    def test_stop_hook_silent_on_bad_stdin(self, repo, capsys, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
        assert run(repo, "stop-hook") == 0
        assert capsys.readouterr().out.strip() == ""

    def test_session_start_injects_and_archives_once(self, repo, capsys, monkeypatch):
        from scripts import state as st
        st.begin(repo)
        st.request_clear(repo, "HANDOFF PAYLOAD")
        st.consume_clear_flag(repo)
        self._stdin(monkeypatch, {"cwd": str(repo), "source": "clear"})
        assert run(repo, "session-start-hook") == 0
        out = capsys.readouterr().out
        assert "HANDOFF PAYLOAD" in out and "additionalContext" in out
        # second launch: handoff archived → silent
        self._stdin(monkeypatch, {"cwd": str(repo), "source": "startup"})
        assert run(repo, "session-start-hook") == 0
        assert capsys.readouterr().out.strip() == ""

    def test_session_start_clears_gate_and_touches_cooldown_after_injection(
        self, repo, capsys, monkeypatch,
    ):
        from scripts import state as st
        st.begin(repo)
        st.request_clear(repo, "HANDOFF PAYLOAD")
        st.consume_clear_flag(repo)
        st.set_gate(repo)
        assert st.gate_active(repo) is True
        self._stdin(monkeypatch, {"cwd": str(repo), "source": "clear"})
        assert run(repo, "session-start-hook") == 0
        assert "HANDOFF PAYLOAD" in capsys.readouterr().out
        assert st.gate_active(repo) is False  # new cycle: gate cleared
        assert st.cooldown_active(repo) is True  # fresh cooldown grace (storm guard)

    def test_session_start_clears_gate_and_touches_cooldown_with_no_handoff(
        self, repo, capsys, monkeypatch,
    ):
        # IMPORTANT 4 + CRITICAL 2: a bare /clear (or plain relaunch) with nothing
        # armed must NOT strand the gate — the new cycle clears it unconditionally
        # and lays down the fresh cooldown that covers census's stale-horizon lag.
        from scripts import state as st
        st.begin(repo)
        st.set_gate(repo)
        self._stdin(monkeypatch, {"cwd": str(repo), "source": "startup"})
        assert run(repo, "session-start-hook") == 0
        assert capsys.readouterr().out.strip() == ""
        assert st.gate_active(repo) is False  # gate cleared: no stranded gate
        assert st.cooldown_active(repo) is True  # fresh cooldown present
