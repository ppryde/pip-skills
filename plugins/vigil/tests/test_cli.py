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
