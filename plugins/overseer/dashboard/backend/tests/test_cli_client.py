from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.cli_client import CliError, _check_id, run_overseer


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    run_overseer(tmp_path, "init")
    return tmp_path


def test_board_round_trips_new_card(root: Path) -> None:
    out = run_overseer(root, "new-card", "--title", "Widget thing", "--complexity", "S")
    card_id = out.strip()

    board = run_overseer(root, "board", "--json", json_out=True)

    assert isinstance(board, dict)
    ids = [c["id"] for c in board["cards"]]
    assert card_id in ids


def test_bad_verb_raises_cli_error(root: Path) -> None:
    with pytest.raises(CliError) as exc_info:
        run_overseer(root, "not-a-real-verb")
    assert exc_info.value.returncode != 0
    assert exc_info.value.stderr


def test_unknown_id_raises_cli_error_with_stderr(root: Path) -> None:
    with pytest.raises(CliError) as exc_info:
        run_overseer(root, "show", "NOPE-999", "--json", json_out=True)
    assert exc_info.value.returncode == 1
    assert "no card with id" in exc_info.value.stderr


def test_check_id_accepts_safe_ids() -> None:
    _check_id("ABC-123")
    _check_id("abc_123")


@pytest.mark.parametrize(
    "bad_id",
    ["a; rm -rf /", "../etc/passwd", "a/b", "a\\b", "a*b", "a?b", "a[b]", "a b"],
)
def test_check_id_rejects_metacharacters(bad_id: str) -> None:
    with pytest.raises(CliError) as exc_info:
        _check_id(bad_id)
    assert exc_info.value.returncode == 2
    assert exc_info.value.stderr == "invalid card id"
