import json
import os
import subprocess
import sys
import time

import pytest

from .conftest import SKILL

# Each child imports everything, announces "ready", then spins until the go file
# exists, so all of them hit the read-modify-write in the same instant.
_INGEST = (
    "import os, sys, time; from context_vigil import census as st; "
    "payload = sys.stdin.read(); open(sys.argv[1], 'w').close(); "
    "deadline = time.time() + 20\n"
    "while not os.path.exists(sys.argv[2]) and time.time() < deadline: pass\n"
    "st.ingest(payload)"
)


@pytest.fixture
def store_file(iso):
    from context_vigil import paths
    return paths.census_path()


def _spawn_ingest(sid, ready, go):
    """Launch a real subprocess that ingests one payload once `go` appears."""
    env = dict(os.environ, PYTHONPATH=str(SKILL / "scripts"))
    payload = json.dumps({"session_id": sid, "cwd": f"/wt/{sid}"})
    proc = subprocess.Popen([sys.executable, "-c", _INGEST, str(ready), str(go)],
                            stdin=subprocess.PIPE, env=env, text=True)
    proc.stdin.write(payload)
    proc.stdin.close()
    return proc


def test_concurrent_writers_do_not_lose_entries(store_file, tmp_path):
    ids = [f"s{i}" for i in range(24)]
    go = tmp_path / "go"
    readies = [tmp_path / f"ready-{sid}" for sid in ids]
    procs = [_spawn_ingest(sid, r, go) for sid, r in zip(ids, readies)]
    try:
        deadline = time.time() + 30
        while not all(r.exists() for r in readies):
            assert time.time() < deadline, "children never became ready"
            time.sleep(0.01)
        go.touch()  # every child is spinning: release them together
        for proc in procs:
            proc.wait(timeout=30)
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
    assert [proc.returncode for proc in procs] == [0] * len(ids)

    sessions = json.loads(store_file.read_text())["sessions"]
    assert set(sessions) == set(ids), "the flock read-modify-write lost concurrent entries"
    assert all(sessions[sid]["worktree_cwd"] == f"/wt/{sid}" for sid in ids)
