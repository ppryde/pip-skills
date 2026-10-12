"""Degradation paths of the TypeScript bridge; none of these need node installed."""
import json
import subprocess
from typing import Any

import pytest

from scripts import extract_ts

ITEMS = [("a.ts", "sha", b"export const a = 1;\n")]


def fake_run(stdout: str = "", returncode: int = 0):
    def run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, returncode, stdout, "")
    return run


def test_unavailable_without_node(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extract_ts.shutil, "which", lambda _name: None)
    reason = extract_ts.unavailable_reason()
    assert reason is not None and "node" in reason


@pytest.mark.parametrize("stdout", [
    "not json",
    "[]",  # short result list
    "{}",
    json.dumps([{"path": "a.ts"}]),  # valid JSON, missing fields
])
def test_unusable_output_is_a_runtime_error(
        monkeypatch: pytest.MonkeyPatch, stdout: str) -> None:
    monkeypatch.setattr(subprocess, "run", fake_run(stdout))
    with pytest.raises(RuntimeError):
        extract_ts.extract_batch(ITEMS, timeout_s=5)


def test_nonzero_exit_is_a_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", fake_run("", returncode=1))
    with pytest.raises(RuntimeError):
        extract_ts.extract_batch(ITEMS, timeout_s=5)


def test_missing_node_binary_is_a_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise FileNotFoundError("node")
    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(RuntimeError, match="could not run"):
        extract_ts.extract_batch(ITEMS, timeout_s=5)


def test_timeout_is_a_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(*args: Any, **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired("node", 1)
    monkeypatch.setattr(subprocess, "run", slow)
    with pytest.raises(extract_ts.DeadlineExceeded):
        extract_ts.extract_batch(ITEMS, timeout_s=5)
