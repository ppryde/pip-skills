import json
import os
import subprocess
import sys
from pathlib import Path

from scripts import store as st

CLI = Path(__file__).resolve().parents[2] / "plugins" / "census" / "scripts" / "cli.py"


def _spawn_ingest(store_path, sid):
    """Launch a real subprocess that ingests one payload — exercises lock-free per-session files."""
    env = dict(os.environ, CENSUS_STORE=str(store_path))
    payload = json.dumps({"session_id": sid, "cwd": f"/wt/{sid}"})
    return subprocess.Popen(
        [sys.executable, str(CLI), "ingest"],
        stdin=subprocess.PIPE,
        env=env,
        text=True,
    ), payload


def test_concurrent_writers_do_not_lose_entries(store_file):
    ids = [f"s{i}" for i in range(24)]
    procs = [_spawn_ingest(store_file, sid) for sid in ids]
    for proc, payload in procs:  # feed every child first, so they really overlap...
        proc.stdin.write(payload)
        proc.stdin.close()
    for proc, _ in procs:  # ...then wait for them all
        proc.wait(timeout=30)
    for proc, _ in procs:
        assert proc.returncode == 0

    sessions = st.read_all()["sessions"]
    assert set(sessions) == set(ids), "a concurrent writer lost a session file"
