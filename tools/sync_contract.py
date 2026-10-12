#!/usr/bin/env python3
"""Vendor the pip-agents validator, contract and batch planner into the plugins that consume them (WF-270 PR E).

Stdlib only, deterministic. A consumer skill cannot reach a dependency plugin's files (its `${CLAUDE_PLUGIN_ROOT}` is
its own root, and no variable names the dependency's versioned cache path; probe recorded in PR A), so each consumer
carries a byte-identical copy, the census-mod bundle precedent. The source is plugins/pip-agents; the copy goes to
plugins/<consumer>/vendor/pip-agents/ with a VENDORED.json recording the contract revision and a sha256 per file.

    python3 tools/sync_contract.py                    # write every consumer's copy
    python3 tools/sync_contract.py --check            # write nothing; list drift, exit 1
    python3 tools/sync_contract.py review-clone       # one consumer
    python3 tools/sync_contract.py --root DIR         # act on another repo layout (tests use a temp tree)

Exit codes: 0 clean; 1 drift (--check); 2 usage error or a missing source file.
tests/agents/test_sync_contract.py fails when a committed copy drifts, and this tool is the fix.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = Path("plugins") / "pip-agents"
# Path under vendor/pip-agents/ -> its source, relative to the repo root. The batch planner lives in tools/ (it is
# repo tooling, not part of the pip-agents plugin), and consumers that split a rulebook import the vendored copy so
# BATCH_CAP has one definition.
SOURCES = {
    "scripts/validate_result.py": SOURCE / "scripts" / "validate_result.py",
    "scripts/batching.py": Path("tools") / "batching.py",
    "contract/result.schema.json": SOURCE / "contract" / "result.schema.json",
    "contract/brief.schema.json": SOURCE / "contract" / "brief.schema.json",
    "contract/personas.json": SOURCE / "contract" / "personas.json",
    "contract/REVISION": SOURCE / "contract" / "REVISION",
}
FILES = tuple(SOURCES)
CONSUMERS = ("review-panel", "review-clone")
VENDOR_DIR = Path("vendor") / "pip-agents"
MANIFEST = "VENDORED.json"


class SyncError(Exception):
    """A source file is missing or the consumer is unknown (exit 2)."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def expected(root: Path) -> dict[str, bytes]:
    """Vendored relative path -> exact bytes, for one consumer. Includes the manifest."""
    out: dict[str, bytes] = {}
    for rel, source in SOURCES.items():
        p = root / source
        if not p.is_file():
            raise SyncError(f"missing source file {p}")
        out[rel] = p.read_bytes()
    revision = out["contract/REVISION"].decode("utf-8").strip()
    manifest = {
        "sources": {rel: source.as_posix() for rel, source in sorted(SOURCES.items())},
        "revision": revision,
        "files": {rel: sha256(out[rel]) for rel in sorted(out)},
    }
    out[MANIFEST] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return out


def drift(root: Path, consumer: str) -> list[str]:
    """Human-readable differences between the committed copy and the source; empty when clean."""
    dest = root / "plugins" / consumer / VENDOR_DIR
    want = expected(root)
    problems: list[str] = []
    for rel, data in sorted(want.items()):
        p = dest / rel
        if not p.is_file():
            problems.append(f"{consumer}: {rel} is missing")
        elif p.read_bytes() != data:
            problems.append(f"{consumer}: {rel} differs from the source")
    if dest.is_dir():
        for p in sorted(dest.rglob("*")):
            rel = p.relative_to(dest).as_posix()
            if p.is_file() and rel not in want and "__pycache__" not in p.parts:
                problems.append(f"{consumer}: {rel} is not part of the bundle")
    return problems


def sync(root: Path, consumer: str) -> None:
    dest = root / "plugins" / consumer / VENDOR_DIR
    if not (root / "plugins" / consumer).is_dir():
        raise SyncError(f"no plugin {consumer} under {root / 'plugins'}")
    want = expected(root)
    for rel, data in want.items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    if dest.is_dir():  # nothing else may linger from an earlier bundle
        for p in sorted(dest.rglob("*")):
            rel = p.relative_to(dest).as_posix()
            if p.is_file() and rel not in want and "__pycache__" not in p.parts:
                p.unlink()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sync_contract.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("consumers", nargs="*", help=f"default: {' '.join(CONSUMERS)}")
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 on drift")
    ap.add_argument("--root", default=str(ROOT), help="repo root (default: this repo)")
    args = ap.parse_args(argv)
    root = Path(args.root)
    consumers = args.consumers or list(CONSUMERS)
    try:
        if args.check:
            problems = [p for c in consumers for p in drift(root, c)]
            for p in problems:
                print(p)
            if problems:
                print("run: python3 tools/sync_contract.py", file=sys.stderr)
            return 1 if problems else 0
        for c in consumers:
            sync(root, c)
            print(f"synced plugins/{c}/{VENDOR_DIR.as_posix()}")
    except SyncError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
