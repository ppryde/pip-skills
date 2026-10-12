"""Run the real concordance CLI for one counterfactual query, as a subprocess, and time it."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

CLI_PATH = Path(__file__).resolve().parent.parent / "cli.py"


@dataclass(frozen=True)
class Answer:
    ok: bool
    doc: dict[str, object] = field(default_factory=dict)
    latency_ms: int = 0
    exit_code: int = 2


def run(args: list[str], cwd: str, timeout: float = 60.0) -> Answer:
    if not cwd or not Path(cwd).is_dir():
        return Answer(False)
    env = {**os.environ, "CONCORDANCE_ORIGIN": "replay"}
    started = time.monotonic()
    try:
        proc = subprocess.run([sys.executable, str(CLI_PATH), *args, "--json"], cwd=cwd,
                              env=env, capture_output=True, text=True, timeout=timeout,
                              check=False)
    except (OSError, subprocess.SubprocessError):
        return Answer(False, latency_ms=int((time.monotonic() - started) * 1000))
    latency = max(1, int((time.monotonic() - started) * 1000))
    # exit 2 prints nothing on stdout under --json: that is a failed run, never parsed.
    try:
        doc = json.loads(proc.stdout)
    except ValueError:
        return Answer(False, latency_ms=latency, exit_code=proc.returncode)
    if not isinstance(doc, dict):
        return Answer(False, latency_ms=latency, exit_code=proc.returncode)
    return Answer(True, doc, latency, proc.returncode)
