import json
import os
import subprocess
import sys

import pytest

from .conftest import SKILL

_INGEST = "import sys; from context_vigil import census as st; st.ingest(sys.stdin.read())"


@pytest.fixture
def store_file(iso):
    from context_vigil import paths
    return paths.census_path()


def _spawn_ingest(sid):
    """Launch a real subprocess that ingests one payload — exercises cross-process flock."""
    env = dict(os.environ, PYTHONPATH=str(SKILL / "scripts"))
    payload = json.dumps({"session_id": sid, "cwd": f"/wt/{sid}"})
    return subprocess.Popen(
        [sys.executable, "-c", _INGEST],
        stdin=subprocess.PIPE,
        env=env,
        text=True,
    ), payload


def test_concurrent_writers_do_not_lose_entries(store_file):
    ids = [f"s{i}" for i in range(24)]
    procs = [_spawn_ingest(sid) for sid in ids]
    for proc, payload in procs:
        proc.communicate(payload, timeout=30)
    for proc, _ in procs:
        assert proc.returncode == 0

    sessions = json.loads(store_file.read_text())["sessions"]
    assert set(sessions) == set(ids), "the flock read-modify-write lost concurrent entries"
