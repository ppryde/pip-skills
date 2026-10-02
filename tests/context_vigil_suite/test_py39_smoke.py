from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from .conftest import LAUNCHER

PY39 = Path("/usr/bin/python3")


@pytest.mark.skipif(not PY39.exists(), reason="no system python3")
def test_full_flow_under_system_python(repo: Path, iso: Path) -> None:
    env = dict(os.environ, CONTEXT_VIGIL_PYTHON=str(PY39))

    def run(*args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
        return subprocess.run(["bash", str(LAUNCHER), *args], input=stdin, cwd=repo,
                              env=env, capture_output=True, text=True, timeout=30)

    payload = {"session_id": "s", "workspace": {"current_dir": str(repo)},
               "context_window": {"used_percentage": 90}}
    assert run("ingest", stdin=json.dumps(payload)).returncode == 0
    nudge = run("hook", "nudge", stdin=json.dumps({"cwd": str(repo), "session_id": "s"}))
    assert "90%" in nudge.stdout, nudge.stderr
    notes = iso / "n.md"
    notes.write_text("## Failed Attempts\nNone\n## Next Step\nGo.\n")
    assert run("handover", "--file", str(notes)).returncode == 0
    start = run("hook", "session-start",
                stdin=json.dumps({"cwd": str(repo), "source": "clear"}))
    assert "Resume from this handover" in start.stdout
    assert run("install", "--yes", "--threshold", "40").returncode == 0
    assert run("status").returncode == 0
