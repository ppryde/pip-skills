"""WF-013: the auto-resume 'kick' after a `/clear` handover.

Injected `additionalContext` never starts a turn on its own — the fresh
session sits idle until a human types something. When a handover was just
consumed on a `source == "clear"` SessionStart, vigil types a short resume
prompt into the session's own tmux pane so unattended runs restart
hands-free. See `cmd_session_start_hook` / `_maybe_kick_resume` in
`scripts/cli.py`.

Unit tests here fake `tmux` with a PATH shim that records argv to a marker
file. The one E2E test at the bottom drives a REAL tmux server, but always on
a private `-L vigil-test-<pid>` socket — it must never touch the developer's
own running tmux server.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from scripts.cli import main
from scripts import state as st

KICK_PROMPT = (
    "vigil: handover received — resume the work described in the injected handover now."
)


def run(repo, *argv):
    return main(["--root", str(repo), *argv])


def _stdin(monkeypatch, payload):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))


def _arm_and_consume(repo):
    """Active root, handover armed then consumed by the Stop hook — the state
    a real `source=clear` SessionStart always finds: a pending, uninjected
    handoff."""
    st.begin(repo)
    st.request_clear(repo, "KICK TEST HANDOFF")
    st.consume_clear_flag(repo)


def _make_tmux_shim(bindir: Path, marker: Path, has_session_rc: int = 0) -> Path:
    """A fake `tmux` on PATH: `has-session` exits `has_session_rc` silently;
    any other invocation (i.e. `send-keys`) appends its argv to `marker` — so
    the marker's mere existence proves a send-keys call happened, and its
    absence proves tmux was never asked to do anything beyond (at most) the
    liveness probe."""
    bindir.mkdir(parents=True, exist_ok=True)
    fake = bindir / "tmux"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        f'if [ "$1" = "has-session" ]; then exit {has_session_rc}; fi\n'
        f'echo "$@" >> "{marker}"\n'
    )
    fake.chmod(0o755)
    return fake


def _kick_recorded(marker: Path) -> bool:
    """True once the shim has recorded the COMPLETE kick: both the literal
    prompt send AND the separate Enter send. The kick is two distinct shim
    invocations, so polling for the marker's mere existence returns after the
    first append — a subsequent read (or unlink) then races the second
    invocation under load."""
    if not marker.exists():
        return False
    lines = marker.read_text().splitlines()
    prompt_sent = any(
        line.startswith("send-keys") and "-l" in line and KICK_PROMPT in line
        for line in lines
    )
    enter_sent = any(
        line.startswith("send-keys") and line.rstrip().endswith("Enter")
        for line in lines
    )
    return prompt_sent and enter_sent


def _wait_for_kick(marker: Path, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _kick_recorded(marker):
            return True
        time.sleep(0.05)
    return False


class TestResumeKickUnit:
    def test_clear_source_dispatches_send_keys_and_enter(self, repo, capsys, monkeypatch):
        _arm_and_consume(repo)
        bindir = repo / "bin"
        marker = repo / "tmux-called"
        _make_tmux_shim(bindir, marker)
        monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
        monkeypatch.setenv("TMUX", "/tmp/x,1,0")
        monkeypatch.setenv("TMUX_PANE", "%9")
        monkeypatch.setenv("VIGIL_KICK_DELAY", "0")
        _stdin(monkeypatch, {"cwd": str(repo), "source": "clear"})

        assert run(repo, "session-start-hook") == 0
        out = capsys.readouterr().out
        assert "KICK TEST HANDOFF" in out
        assert "additionalContext" in out

        assert _wait_for_kick(marker)  # predicate poll: BOTH sends recorded
        lines = marker.read_text().splitlines()
        assert any(
            line.startswith("send-keys -t %9 -l") and KICK_PROMPT in line for line in lines
        )
        assert any(line == "send-keys -t %9 Enter" for line in lines)

    def test_non_clear_source_never_invokes_tmux(self, repo, capsys, monkeypatch):
        _arm_and_consume(repo)
        bindir = repo / "bin"
        marker = repo / "tmux-called"
        _make_tmux_shim(bindir, marker)
        monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
        monkeypatch.setenv("TMUX", "/tmp/x,1,0")
        monkeypatch.setenv("TMUX_PANE", "%9")
        monkeypatch.setenv("VIGIL_KICK_DELAY", "0")
        _stdin(monkeypatch, {"cwd": str(repo), "source": "startup"})

        assert run(repo, "session-start-hook") == 0
        out = capsys.readouterr().out
        assert "KICK TEST HANDOFF" in out
        assert "additionalContext" in out

        time.sleep(0.3)  # give a wrongly-dispatched kick a chance to land
        assert not marker.exists()  # source check gates BEFORE any tmux probe

    def test_no_pending_handoff_no_json_no_kick(self, repo, capsys, monkeypatch):
        st.begin(repo)  # active, but nothing armed/consumed
        bindir = repo / "bin"
        marker = repo / "tmux-called"
        _make_tmux_shim(bindir, marker)
        monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
        monkeypatch.setenv("TMUX", "/tmp/x,1,0")
        monkeypatch.setenv("TMUX_PANE", "%9")
        monkeypatch.setenv("VIGIL_KICK_DELAY", "0")
        _stdin(monkeypatch, {"cwd": str(repo), "source": "clear"})

        assert run(repo, "session-start-hook") == 0
        assert capsys.readouterr().out.strip() == ""
        time.sleep(0.3)
        assert not marker.exists()

    def test_tmux_env_unset_no_kick(self, repo, capsys, monkeypatch):
        _arm_and_consume(repo)
        bindir = repo / "bin"
        marker = repo / "tmux-called"
        _make_tmux_shim(bindir, marker)
        monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
        monkeypatch.delenv("TMUX", raising=False)
        monkeypatch.setenv("TMUX_PANE", "%9")
        monkeypatch.setenv("VIGIL_KICK_DELAY", "0")
        _stdin(monkeypatch, {"cwd": str(repo), "source": "clear"})

        assert run(repo, "session-start-hook") == 0
        out = capsys.readouterr().out
        assert "KICK TEST HANDOFF" in out
        time.sleep(0.3)
        assert not marker.exists()

    def test_dead_tmux_server_no_kick(self, repo, capsys, monkeypatch):
        _arm_and_consume(repo)
        bindir = repo / "bin"
        marker = repo / "tmux-called"
        _make_tmux_shim(bindir, marker, has_session_rc=1)
        monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
        monkeypatch.setenv("TMUX", "/tmp/x,1,0")
        monkeypatch.setenv("TMUX_PANE", "%9")
        monkeypatch.setenv("VIGIL_KICK_DELAY", "0")
        _stdin(monkeypatch, {"cwd": str(repo), "source": "clear"})

        assert run(repo, "session-start-hook") == 0
        out = capsys.readouterr().out
        assert "KICK TEST HANDOFF" in out
        time.sleep(0.3)
        assert not marker.exists()  # has-session failed → send-keys never runs

    def test_tmux_binary_entirely_missing_never_raises(self, repo, capsys, monkeypatch):
        _arm_and_consume(repo)
        empty_path = repo / "no-such-bin"
        empty_path.mkdir()
        monkeypatch.setenv("PATH", str(empty_path))
        monkeypatch.setenv("TMUX", "/tmp/x,1,0")
        monkeypatch.setenv("TMUX_PANE", "%9")
        monkeypatch.setenv("VIGIL_KICK_DELAY", "0")
        _stdin(monkeypatch, {"cwd": str(repo), "source": "clear"})

        assert run(repo, "session-start-hook") == 0  # never raises
        out = capsys.readouterr().out
        assert "KICK TEST HANDOFF" in out

    def test_second_session_start_after_kick_is_silent(self, repo, capsys, monkeypatch):
        _arm_and_consume(repo)
        bindir = repo / "bin"
        marker = repo / "tmux-called"
        _make_tmux_shim(bindir, marker)
        monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
        monkeypatch.setenv("TMUX", "/tmp/x,1,0")
        monkeypatch.setenv("TMUX_PANE", "%9")
        monkeypatch.setenv("VIGIL_KICK_DELAY", "0")
        _stdin(monkeypatch, {"cwd": str(repo), "source": "clear"})
        assert run(repo, "session-start-hook") == 0
        assert "KICK TEST HANDOFF" in capsys.readouterr().out
        # Predicate poll matters doubly here: waiting on mere marker existence
        # would let the unlink below race the shim's second (Enter) invocation,
        # which would re-create the marker and false-fail the final assertion.
        assert _wait_for_kick(marker)  # first launch kicks — BOTH sends done

        marker.unlink()  # reset the recorder for the second launch
        _stdin(monkeypatch, {"cwd": str(repo), "source": "clear"})
        assert run(repo, "session-start-hook") == 0
        assert capsys.readouterr().out.strip() == ""  # handoff already archived
        time.sleep(0.3)
        assert not marker.exists()  # at most once per handover

    def test_malformed_stdin_exits_0_no_kick(self, repo, capsys, monkeypatch):
        bindir = repo / "bin"
        marker = repo / "tmux-called"
        _make_tmux_shim(bindir, marker)
        monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
        monkeypatch.setenv("TMUX", "/tmp/x,1,0")
        monkeypatch.setenv("TMUX_PANE", "%9")
        monkeypatch.setenv("VIGIL_KICK_DELAY", "0")
        monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))

        assert run(repo, "session-start-hook") == 0
        assert capsys.readouterr().out.strip() == ""
        time.sleep(0.3)
        assert not marker.exists()


TMUX_BIN = shutil.which("tmux")


def _start_private_session(socket_name: str, session_name: str) -> bool:
    result = subprocess.run(
        [TMUX_BIN, "-L", socket_name, "new-session", "-d", "-s", session_name, "cat"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


@pytest.mark.skipif(TMUX_BIN is None, reason="tmux not installed on this machine")
class TestResumeKickE2E:
    def test_real_tmux_pane_receives_resume_prompt(self, repo, monkeypatch, request):
        socket_name = f"vigil-test-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        session_name = "vigil-e2e"

        if not _start_private_session(socket_name, session_name):
            pytest.skip("could not start a private tmux server on this machine")

        def _kill_private_server():
            subprocess.run(
                [TMUX_BIN, "-L", socket_name, "kill-server"],
                capture_output=True,
            )

        request.addfinalizer(_kill_private_server)

        pane = subprocess.run(
            [TMUX_BIN, "-L", socket_name, "list-panes", "-t", session_name, "-F", "#{pane_id}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert pane

        wrapper = repo / "tmux-wrapper.sh"
        wrapper.write_text(
            "#!/usr/bin/env bash\n"
            f'exec {TMUX_BIN} -L {socket_name} "$@"\n'
        )
        wrapper.chmod(0o755)

        _arm_and_consume(repo)
        monkeypatch.setenv("VIGIL_TMUX_BIN", str(wrapper))
        monkeypatch.setenv("VIGIL_KICK_DELAY", "0")
        monkeypatch.setenv("TMUX", "e2e-fake,1,0")  # only gates "is TMUX set"
        monkeypatch.setenv("TMUX_PANE", pane)
        _stdin(monkeypatch, {"cwd": str(repo), "source": "clear"})

        assert run(repo, "session-start-hook") == 0

        deadline = time.time() + 5
        captured = ""
        while time.time() < deadline:
            captured = subprocess.run(
                [TMUX_BIN, "-L", socket_name, "capture-pane", "-p", "-t", pane],
                capture_output=True, text=True,
            ).stdout
            if "vigil: handover received" in captured:
                break
            time.sleep(0.1)

        assert "vigil: handover received" in captured, (
            f"resume prompt never appeared in pane; last capture:\n{captured}"
        )
