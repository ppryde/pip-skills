"""almoner CLI — gather configured sources into one digest, read-only.

Every verb prints one JSON object to stdout for the overseer dashboard. Pull
only: no hooks, no schedule — refresh is a person pressing Gather.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Allow `python plugins/almoner/scripts/cli.py` from anywhere.
_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from scripts import paths


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload))


def cmd_status(_: argparse.Namespace) -> int:
    _emit({"config": str(paths.config_path()), "db": str(paths.db_path()), "sources": []})
    return 0


def _not_yet(_: argparse.Namespace) -> int:
    print("almoner: not implemented yet", file=sys.stderr)
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="almoner")
    sub = parser.add_subparsers(dest="verb", required=True)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    for verb in ("digest", "dismiss", "ack", "log"):
        sub.add_parser(verb).set_defaults(fn=_not_yet)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
