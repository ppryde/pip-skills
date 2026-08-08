import json
import os
import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).resolve().parent.parent / "scripts" / "cli.py"


def _spawn_ingest(store_path, sid):
    """Launch a real subprocess that ingests one payload — exercises cross-process flock."""
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
    for proc, payload in procs:
        proc.communicate(payload, timeout=30)
    for proc, _ in procs:
        assert proc.returncode == 0

    sessions = json.loads(store_file.read_text())["sessions"]
    assert set(sessions) == set(ids), "the flock read-modify-write lost concurrent entries"
