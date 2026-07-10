from pathlib import Path

from scripts import state as st
from scripts.store import ensure_root


class TestPromotion:
    def test_inactive_by_default(self, tmp_path):
        ensure_root(tmp_path)
        assert st.is_active(tmp_path) is False

    def test_promote_sets_active(self, tmp_path):
        ensure_root(tmp_path)
        st.begin(tmp_path)
        assert st.is_active(tmp_path) is True


class TestRequestClear:
    def test_inactive_refuses(self, tmp_path):
        ensure_root(tmp_path)
        assert st.request_clear(tmp_path, "HANDOFF") == "inactive"
        assert st.read_handoff(tmp_path) is None

    def test_active_arms_and_writes_handoff(self, tmp_path):
        ensure_root(tmp_path)
        st.begin(tmp_path)
        assert st.request_clear(tmp_path, "HANDOFF BODY") == "armed"
        assert st.clear_flag(tmp_path).exists()
        assert st.read_handoff(tmp_path) == "HANDOFF BODY"

    def test_paused_refuses(self, tmp_path):
        ensure_root(tmp_path)
        st.begin(tmp_path)
        st.pause(tmp_path)
        assert st.request_clear(tmp_path, "H") == "paused"
        assert not st.clear_flag(tmp_path).exists()


class TestConsume:
    def test_consume_removes_flag_and_sets_cooldown(self, tmp_path):
        ensure_root(tmp_path)
        st.begin(tmp_path)
        st.request_clear(tmp_path, "H")
        assert st.consume_clear_flag(tmp_path) is True
        assert not st.clear_flag(tmp_path).exists()
        assert st.cooldown_marker(tmp_path).exists()

    def test_consume_noop_without_flag(self, tmp_path):
        ensure_root(tmp_path)
        st.begin(tmp_path)
        assert st.consume_clear_flag(tmp_path) is False

    def test_consume_noop_when_inactive(self, tmp_path):
        ensure_root(tmp_path)
        st.clear_flag(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        st.clear_flag(tmp_path).touch()
        assert st.consume_clear_flag(tmp_path) is False

    def test_consume_noop_when_paused(self, tmp_path):
        ensure_root(tmp_path)
        st.begin(tmp_path)
        st.request_clear(tmp_path, "H")
        st.pause(tmp_path)
        assert st.consume_clear_flag(tmp_path) is False
        assert st.clear_flag(tmp_path).exists()


class TestConsumeHandoff:
    def test_returns_text_and_archives(self, tmp_path):
        ensure_root(tmp_path)
        st.begin(tmp_path)
        st.request_clear(tmp_path, "BRIEFING BODY")
        assert st.consume_handoff(tmp_path) == "BRIEFING BODY"
        assert not st.handoff_path(tmp_path).exists()          # live handoff gone
        archived = list(st.handoff_archive_dir(tmp_path).glob("handoff*.md"))
        assert len(archived) == 1
        assert archived[0].read_text() == "BRIEFING BODY"        # archived, not lost

    def test_none_when_no_handoff(self, tmp_path):
        ensure_root(tmp_path)
        st.begin(tmp_path)
        assert st.consume_handoff(tmp_path) is None

    def test_injects_at_most_once(self, tmp_path):
        ensure_root(tmp_path)
        st.begin(tmp_path)
        st.request_clear(tmp_path, "ONE SHOT")
        assert st.consume_handoff(tmp_path) == "ONE SHOT"
        assert st.consume_handoff(tmp_path) is None            # second launch: nothing

    def test_returns_text_when_archive_rename_fails(self, tmp_path, monkeypatch):
        # Archiving may fail (rename raises); the text is already in hand, so the
        # handoff must still be returned and the live file cleared (best-effort).
        ensure_root(tmp_path)
        st.begin(tmp_path)
        st.request_clear(tmp_path, "SURVIVES RENAME")

        def boom(*_a, **_k):
            raise OSError("rename failed")

        monkeypatch.setattr(Path, "rename", boom)
        assert st.consume_handoff(tmp_path) == "SURVIVES RENAME"   # no raise
        assert not st.handoff_path(tmp_path).exists()             # fallback unlink ran

    def test_never_raises_when_rename_and_unlink_both_fail(self, tmp_path, monkeypatch):
        # The residual the never-raise docstring must honour: BOTH the archive
        # rename and the fallback unlink raise a non-FileNotFound OSError.
        ensure_root(tmp_path)
        st.begin(tmp_path)
        st.request_clear(tmp_path, "STILL FINE")

        def boom(*_a, **_k):
            raise OSError("io failed")

        monkeypatch.setattr(Path, "rename", boom)
        monkeypatch.setattr(Path, "unlink", boom)
        assert st.consume_handoff(tmp_path) == "STILL FINE"       # never raises

    def test_never_raises_when_archive_mkdir_fails(self, tmp_path, monkeypatch):
        # mkdir of the archive dir can also fail; text already read → still returned.
        ensure_root(tmp_path)
        st.begin(tmp_path)
        st.request_clear(tmp_path, "MKDIR BOOM")

        def boom(*_a, **_k):
            raise OSError("mkdir failed")

        monkeypatch.setattr(Path, "mkdir", boom)
        assert st.consume_handoff(tmp_path) == "MKDIR BOOM"       # never raises


class TestCooldown:
    def test_request_clear_refuses_during_cooldown(self, tmp_path):
        ensure_root(tmp_path)
        st.begin(tmp_path)
        st.request_clear(tmp_path, "H")
        st.consume_clear_flag(tmp_path)  # sets cooldown
        assert st.request_clear(tmp_path, "H2") == "cooldown"

    def test_arm_ready_clears_cooldown_and_flag(self, tmp_path):
        ensure_root(tmp_path)
        st.begin(tmp_path)
        st.request_clear(tmp_path, "H")
        st.consume_clear_flag(tmp_path)
        st.arm_ready(tmp_path)
        assert not st.cooldown_marker(tmp_path).exists()
        assert st.request_clear(tmp_path, "H3") == "armed"

    def test_expired_cooldown_allows_rearm(self, tmp_path):
        import os
        ensure_root(tmp_path)
        st.begin(tmp_path)
        st.request_clear(tmp_path, "H")
        st.consume_clear_flag(tmp_path)  # sets cooldown
        marker = st.cooldown_marker(tmp_path)
        old = marker.stat().st_mtime - (st.COOLDOWN_TTL_SECONDS + 1)
        os.utime(marker, (old, old))
        assert st.request_clear(tmp_path, "H2") == "armed"
        assert not marker.exists()  # expired cooldown was cleared
