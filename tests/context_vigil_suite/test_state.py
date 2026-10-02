import os
import time
from pathlib import Path

import pytest
from context_vigil import state as st


@pytest.fixture
def scope(repo):
    from context_vigil import paths
    return paths.scope_dir(repo)


class TestRequestClear:
    def test_arms_and_writes_handoff(self, scope):
        assert st.request_clear(scope, "HANDOFF BODY") == "armed"
        assert st.clear_flag(scope).exists()
        assert st.read_handoff(scope) == "HANDOFF BODY"

    def test_paused_refuses(self, scope):
        st.pause(scope)
        assert st.request_clear(scope, "H") == "paused"
        assert not st.clear_flag(scope).exists()


class TestConsume:
    def test_consume_removes_flag_and_sets_cooldown(self, scope):
        st.request_clear(scope, "H")
        assert st.consume_clear_flag(scope) is True
        assert not st.clear_flag(scope).exists()
        assert st.cooldown_marker(scope).exists()

    def test_consume_noop_without_flag(self, scope):
        assert st.consume_clear_flag(scope) is False

    def test_consume_noop_when_paused(self, scope):
        st.request_clear(scope, "H")
        st.pause(scope)
        assert st.consume_clear_flag(scope) is False
        assert st.clear_flag(scope).exists()


class TestConsumeHandoff:
    def test_returns_text_and_archives(self, scope):
        st.request_clear(scope, "BRIEFING BODY")
        assert st.consume_handoff(scope) == "BRIEFING BODY"
        assert not st.handoff_path(scope).exists()          # live handoff gone
        archived = list(st.handoff_archive_dir(scope).glob("handoff*.md"))
        assert len(archived) == 1
        assert archived[0].read_text() == "BRIEFING BODY"        # archived, not lost

    def test_none_when_no_handoff(self, scope):
        assert st.consume_handoff(scope) is None

    def test_injects_at_most_once(self, scope):
        st.request_clear(scope, "ONE SHOT")
        assert st.consume_handoff(scope) == "ONE SHOT"
        assert st.consume_handoff(scope) is None            # second launch: nothing

    def test_returns_text_when_archive_rename_fails(self, scope, monkeypatch):
        # Archiving may fail (rename raises); the text is already in hand, so the
        # handoff must still be returned and the live file cleared (best-effort).
        st.request_clear(scope, "SURVIVES RENAME")

        def boom(*_a, **_k):
            raise OSError("rename failed")

        monkeypatch.setattr(Path, "rename", boom)
        assert st.consume_handoff(scope) == "SURVIVES RENAME"   # no raise
        assert not st.handoff_path(scope).exists()             # fallback unlink ran

    def test_never_raises_when_rename_and_unlink_both_fail(self, scope, monkeypatch):
        # The residual the never-raise docstring must honour: BOTH the archive
        # rename and the fallback unlink raise a non-FileNotFound OSError.
        st.request_clear(scope, "STILL FINE")

        def boom(*_a, **_k):
            raise OSError("io failed")

        monkeypatch.setattr(Path, "rename", boom)
        monkeypatch.setattr(Path, "unlink", boom)
        assert st.consume_handoff(scope) == "STILL FINE"       # never raises

    def test_never_raises_when_archive_mkdir_fails(self, scope, monkeypatch):
        # mkdir of the archive dir can also fail; text already read → still returned.
        st.request_clear(scope, "MKDIR BOOM")

        def boom(*_a, **_k):
            raise OSError("mkdir failed")

        monkeypatch.setattr(Path, "mkdir", boom)
        assert st.consume_handoff(scope) == "MKDIR BOOM"       # never raises


class TestHandoffWrittenAt:
    def test_handoff_written_at(self, scope):
        assert st.handoff_written_at(scope) is None
        st.request_clear(scope, "x")
        written = st.handoff_written_at(scope)
        assert written is not None and abs(time.time() - written) < 5


class TestCooldown:
    def test_request_clear_refuses_during_cooldown(self, scope):
        st.request_clear(scope, "H")
        st.consume_clear_flag(scope)  # sets cooldown
        assert st.request_clear(scope, "H2") == "cooldown"

    def test_expired_cooldown_allows_rearm(self, scope):
        st.request_clear(scope, "H")
        st.consume_clear_flag(scope)  # sets cooldown
        marker = st.cooldown_marker(scope)
        old = marker.stat().st_mtime - (st.COOLDOWN_TTL_SECONDS + 1)
        os.utime(marker, (old, old))
        assert st.request_clear(scope, "H2") == "armed"
        assert not marker.exists()  # expired cooldown was cleared

    def test_cooldown_active_public_alias_matches_private(self, scope):
        assert st.cooldown_active(scope) is False
        st.request_clear(scope, "H")
        st.consume_clear_flag(scope)  # sets cooldown
        assert st.cooldown_active(scope) is True


class TestBeginCycle:
    def test_begin_cycle_clears_gate_flag_and_touches_cooldown(self, scope):
        st.request_clear(scope, "H")
        st.set_gate(scope)
        st.begin_cycle(scope)
        assert not st.clear_flag(scope).exists()   # queued clear unlinked
        assert st.gate_active(scope) is False       # gate cleared → re-armed
        assert st.cooldown_active(scope) is True    # fresh cooldown grace

    def test_begin_cycle_cooldown_suppresses_immediate_rearm(self, scope):
        # The storm guard: census lag can re-present a high ctx%, but the fresh
        # cooldown makes request_clear refuse during the grace window.
        st.begin_cycle(scope)
        assert st.request_clear(scope, "H2") == "cooldown"

    def test_begin_cycle_touches_cooldown_with_no_gate_or_flag(self, scope):
        st.begin_cycle(scope)
        assert st.cooldown_active(scope) is True
        assert st.gate_active(scope) is False


class TestGate:
    def test_gate_inactive_by_default(self, scope):
        assert st.gate_active(scope) is False

    def test_gate_ttl_is_six_hours(self):
        assert st.GATE_TTL_SECONDS == 6 * 3600

    def test_set_gate_marks_active(self, scope):
        st.set_gate(scope)
        assert st.gate_marker(scope).exists()
        assert st.gate_active(scope) is True

    def test_clear_gate_removes_marker(self, scope):
        st.set_gate(scope)
        st.clear_gate(scope)
        assert not st.gate_marker(scope).exists()
        assert st.gate_active(scope) is False

    def test_clear_gate_noop_when_absent(self, scope):
        st.clear_gate(scope)  # must not raise
        assert st.gate_active(scope) is False

    def test_gate_ttl_expiry_self_heals(self, scope):
        st.set_gate(scope)
        marker = st.gate_marker(scope)
        old = marker.stat().st_mtime - (st.GATE_TTL_SECONDS + 1)
        os.utime(marker, (old, old))
        assert st.gate_active(scope) is False
        assert not marker.exists()  # expired gate was cleared, self-heal

    def test_gate_within_ttl_stays_active(self, scope):
        st.set_gate(scope)
        marker = st.gate_marker(scope)
        recent = marker.stat().st_mtime - (st.GATE_TTL_SECONDS - 1)
        os.utime(marker, (recent, recent))
        assert st.gate_active(scope) is True

    def test_resume_clears_gate(self, scope):
        st.pause(scope)
        st.set_gate(scope)
        st.resume(scope)
        assert st.is_paused(scope) is False
        assert st.gate_active(scope) is False

    def test_resume_clears_gate_even_when_not_paused(self, scope):
        st.set_gate(scope)
        st.resume(scope)
        assert st.gate_active(scope) is False

    def test_resume_keeps_gate_when_clear_armed(self, scope):
        # A handover is queued: clearing the gate would re-nudge over the pending
        # clear. resume unpauses but leaves the gate holding.
        st.pause(scope)
        st.set_gate(scope)
        st.request_clear(scope, "H")  # arms clear-requested... but paused
        # request_clear refuses while paused, so arm the flag directly instead
        st.clear_flag(scope).touch()
        st.resume(scope)
        assert st.is_paused(scope) is False
        assert st.gate_active(scope) is True  # gate held over queued handover


class TestClearRequested:
    def test_false_when_no_flag(self, scope):
        assert st.clear_requested(scope) is False

    def test_true_when_armed(self, scope):
        st.request_clear(scope, "H")
        assert st.clear_requested(scope) is True

    def test_false_when_paused(self, scope):
        st.request_clear(scope, "H")
        st.pause(scope)
        assert st.clear_requested(scope) is False

    def test_does_not_consume_flag(self, scope):
        st.request_clear(scope, "H")
        assert st.clear_requested(scope) is True
        assert st.clear_requested(scope) is True  # non-consuming: repeatable
        assert st.clear_flag(scope).exists()  # still there for the real consumer
