"""Thin subprocess client for the overseer and vigil CLIs.

The dashboard backend is a CLIENT of these CLIs — it never imports overseer
or vigil internals and never touches `.workflow/` directly. Every read and
write goes through `subprocess.run([sys.executable, cli_py, "--root", root,
<verb>, <args...>])`, preserving overseer's single-writer invariant.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

# backend/app/cli_client.py -> parents: [0]=app [1]=backend [2]=dashboard [3]=overseer
_OVERSEER_CLI = Path(__file__).resolve().parents[3] / "scripts" / "cli.py"
# parents[4]=plugins
_VIGIL_CLI = Path(__file__).resolve().parents[4] / "vigil" / "scripts" / "cli.py"

_ID_RE = re.compile(r"\A[A-Za-z0-9_-]+\Z")


class CliError(Exception):
    """Raised when a CLI invocation fails, times out, or gets a bad id."""

    def __init__(self, returncode: int, stderr: str) -> None:
        super().__init__(stderr)
        self.returncode = returncode
        self.stderr = stderr


def _check_id(card_id: str) -> None:
    """Reject ids containing glob/path metacharacters before they reach the store's glob."""
    if not _ID_RE.match(card_id):
        raise CliError(2, "invalid card id")


def _run(cli_py: Path, cli_name: str, root: Path, args: tuple[str, ...],
          json_out: bool, timeout: int) -> Any:
    try:
        result = subprocess.run(
            [sys.executable, str(cli_py), "--root", str(root), *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise CliError(504, f"{cli_name} {' '.join(args)} timed out") from None
    if result.returncode != 0:
        raise CliError(result.returncode, result.stderr.strip())
    if json_out:
        return json.loads(result.stdout)
    return result.stdout


def run_overseer(root: Path, *args: str, json_out: bool = False, timeout: int = 15) -> Any:
    return _run(_OVERSEER_CLI, "overseer", root, args, json_out, timeout)


def run_vigil(root: Path, *args: str, json_out: bool = False, timeout: int = 15) -> Any:
    return _run(_VIGIL_CLI, "vigil", root, args, json_out, timeout)
