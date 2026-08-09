from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cli_client import run_overseer
from app.main import create_app


# NOTE (test isolation — clean up after yourself): any fixture that runs the
# overseer CLI MUST pin CLAUDE_CONFIG_DIR, OVERSEER_CENTRAL and OVERSEER_DB into
# tmp_path BEFORE invoking it. Otherwise the central board.db + sprint/usage/
# knowledge state land in the developer's REAL ~/.claude*/overseer/ tree —
# named after the pytest tmp dir (i.e. the test function), which is how a run
# once leaked ~45 `test_*` board folders into a real config dir. The plugin's
# own tests/conftest.py already does this via an autouse fixture; this backend
# suite does not yet. Pinning + cleanup is tracked as WF-051 — until then this
# `root` fixture can pollute real state.
@pytest.fixture()
def root(tmp_path: Path) -> Path:
    """A tmp repo root with `.workflow/` initialised.

    overseer `init` calls `git check-ignore`, so the tmp root needs a git
    repo before init runs.
    """
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    run_overseer(tmp_path, "init")
    return tmp_path


@pytest.fixture()
def client(root: Path) -> TestClient:
    return TestClient(create_app(root))
