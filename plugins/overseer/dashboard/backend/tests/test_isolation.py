"""Test isolation guard (WF-051).

The `root`/`client` fixtures run overseer `init` (and every test that drives
the API runs more overseer verbs). Overseer resolves its central board.db from
OVERSEER_DB -> OVERSEER_CENTRAL -> $CLAUDE_CONFIG_DIR/overseer/... — so unless
these are pinned into the environment the subprocess inherits, a test board
lands in the developer's REAL config dir instead of the tmp root it thinks it
is using. This test fails if that isolation is ever removed.
"""
from __future__ import annotations

from pathlib import Path

from app.cli_client import run_overseer


def test_overseer_state_stays_under_tmp(root: Path, tmp_path: Path) -> None:
    # Force a board write through the CLI (init already ran in the fixture; a
    # board read connects and materialises the db if it is not there yet).
    run_overseer(root, "board", "--json")

    dbs = list(tmp_path.rglob("board.db"))
    assert dbs, (
        f"no board.db found under {tmp_path}: overseer state leaked outside the "
        f"tmp root (OVERSEER_DB / OVERSEER_CENTRAL / CLAUDE_CONFIG_DIR not pinned)"
    )
