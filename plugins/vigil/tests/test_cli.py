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
