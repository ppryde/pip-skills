from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cli_client import run_overseer
from app.main import create_app


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
