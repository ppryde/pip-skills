"""Bridge to the Node TypeScript extractor (extract_ts/extract.mjs).

Missing Node or an uninstalled typescript package is not an error: the files are reported as
not indexed with the reason, and nothing is stored, so they are picked up once it is installed.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.facts import FileFacts, file_facts_from_dict

NODE_DIR = Path(__file__).resolve().parent / "extract_ts"


class DeadlineExceeded(RuntimeError):
    pass


def unavailable_reason() -> str | None:
    if shutil.which("node") is None:
        return "node not found on PATH"
    if not (NODE_DIR / "node_modules" / "typescript" / "package.json").is_file():
        cli = Path(__file__).resolve().parent / "cli.py"
        return f"typescript not installed: run `python {cli} setup-ts`"
    return None


def extract_batch(items: list[tuple[str, str, bytes]], timeout_s: float) -> list[FileFacts]:
    if not items:
        return []
    payload = json.dumps([{"path": p, "content": data.decode("utf-8", errors="replace")}
                          for p, _, data in items])
    try:
        proc = subprocess.run(["node", str(NODE_DIR / "extract.mjs")], input=payload,
                              capture_output=True, text=True, timeout=max(timeout_s, 0.1),
                              cwd=NODE_DIR, check=False)
    except subprocess.TimeoutExpired as exc:
        raise DeadlineExceeded(f"TypeScript extraction exceeded {timeout_s:.0f}s") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"TypeScript extractor failed: {proc.stderr.strip()[:500]}")
    try:
        raw = json.loads(proc.stdout)
    except ValueError as exc:  # garbled output degrades to "not indexed", never a crash
        raise RuntimeError(f"TypeScript extractor returned invalid JSON: {exc}") from exc
    return [file_facts_from_dict(d, sha) for d, (_, sha, _) in zip(raw, items)]


def setup() -> int:
    if shutil.which("npm") is None:
        print("concordance: npm not found on PATH; install Node.js 18+ first", file=sys.stderr)
        return 2
    return subprocess.run(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
                          cwd=NODE_DIR, check=False).returncode
