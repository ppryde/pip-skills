#!/usr/bin/env python3
"""Scrape GitHub for a reviewer's PR comments. Writes raw + snapshot to
~/.claude/review-clone/<alias>/. Stdout is human-readable progress.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PERSONA_ROOT = Path(
    os.environ.get("REVIEW_CLONE_ROOT", "") or Path.home() / ".claude" / "review-clone"
)

WINDOW_CAP_MONTHS = 6


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="collect.py",
        description="Scrape a reviewer's GitHub comments for review-clone.",
    )
    p.add_argument("--alias", required=True, help="Persona alias (kebab-case).")
    p.add_argument(
        "--handles",
        required=True,
        help="Comma-separated GitHub handles (e.g. 'jane,bob').",
    )
    p.add_argument("--repo", required=True, help="GitHub repo, e.g. 'owner/repo'.")
    p.add_argument(
        "--months",
        type=int,
        default=6,
        help="Lookback in months (default 6, hard cap 6 in v1).",
    )
    p.add_argument(
        "--paths",
        default="",
        help="Comma-separated path prefixes to include (empty = all).",
    )
    p.add_argument(
        "--extensions",
        default="",
        help="Comma-separated file extensions to include (empty = all).",
    )
    p.add_argument(
        "--since",
        default=None,
        help="ISO datetime to scrape since (refresh mode). Overrides --months.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if args.months > WINDOW_CAP_MONTHS and not args.since:
        print(
            f"error: --months {args.months} exceeds hard cap of {WINDOW_CAP_MONTHS}",
            file=sys.stderr,
        )
        return 2
    # TODO: implement scrape in Task 7+
    return 0


if __name__ == "__main__":
    sys.exit(main())
