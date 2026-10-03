import json
import subprocess
import sys
import time

from context_vigil import paths

from .conftest import SKILL, cli_env

# Each child imports everything, announces "ready", then spins until the go file
# exists, so all of them hit the read-modify-write in the same instant.
_INGEST = (
    "import os, sys, time; from context_vigil import census as st; "
    "payload = sys.stdin.read(); open(sys.argv[1], 'w').close(); "
    # a 60s lock wait: under CPU load the 0.5s default runs out and ingest drops its entry
    "st._LOCK_ATTEMPTS = 6000; "
    "deadline = time.time() + 90\n"
    "while not os.path.exists(sys.argv[2]) and time.time() < deadline: pass\n"
    "st.ingest(payload)"
)


def _spawn_ingest(sid, ready, go):
    """Launch a real subprocess that ingests one payload once `go` appears."""
    env = cli_env({"PYTHONPATH": str(SKILL / "scripts")})
    payload = json.dumps({"session_id": sid, "cwd": f"/wt/{sid}"})
    proc = subprocess.Popen([sys.executable, "-c", _INGEST, str(ready), str(go)],
                            stdin=subprocess.PIPE, env=env, text=True)
    proc.stdin.write(payload)
    proc.stdin.close()
    return proc


def test_concurrent_writers_do_not_lose_entries(store_file, tmp_path):
    ids = [f"s{i}" for i in range(24)]
    # Claim the data root up front: 24 processes racing to *create* it is a first-use
    # race of its own (it can lose an entry), not the read-modify-write under test.
    paths.ensure_dir(store_file.parent)
    go = tmp_path / "go"
    readies = [tmp_path / f"ready-{sid}" for sid in ids]
    procs = [_spawn_ingest(sid, r, go) for sid, r in zip(ids, readies)]
    try:
        deadline = time.time() + 90
        while not all(r.exists() for r in readies):
            assert time.time() < deadline, "children never became ready"
            time.sleep(0.01)
        go.touch()  # every child is spinning: release them together
        for proc in procs:
            proc.wait(timeout=90)
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
    assert [proc.returncode for proc in procs] == [0] * len(ids)

    sessions = json.loads(store_file.read_text())["sessions"]
    assert set(sessions) == set(ids), "the flock read-modify-write lost concurrent entries"
    assert all(sessions[sid]["worktree_cwd"] == f"/wt/{sid}" for sid in ids)
