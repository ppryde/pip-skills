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
from typing import Any

PERSONA_ROOT = Path(
    os.environ.get("REVIEW_CLONE_ROOT", "") or Path.home() / ".claude" / "review-clone"
)

WINDOW_CAP_MONTHS = 6


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse collect.py's command-line arguments."""
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


def _gh_search(repo: str, handle: str, since: str) -> list[dict]:
    """Call `gh search prs --json number,updatedAt`. Returns list of PR dicts."""
    cmd = [
        "gh", "search", "prs",
        "--repo", repo,
        "--involves", handle,
        "--updated", f">={since}",
        "--limit", "1000",
        "--json", "number,updatedAt",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout) if result.stdout.strip() else []


def discover_prs(repo: str, handles: list[str], since: str) -> list[int]:
    """Return deduplicated list of PR numbers touched by any handle since the given ISO date."""
    seen: set[int] = set()
    for handle in handles:
        for pr in _gh_search(repo, handle, since):
            seen.add(pr["number"])
    return sorted(seen)


def _gh_get(api_path: str, paginate: bool = False) -> Any:
    """Call `gh api <path>` and return parsed JSON."""
    cmd = ["gh", "api", api_path]
    if paginate:
        cmd.append("--paginate")
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout) if result.stdout.strip() else []


def _login(obj: dict) -> str | None:
    """Return the `user.login` from a gh API object, or None for ghosted accounts."""
    user = obj.get("user")
    return user["login"] if user else None


def _matches_path_filter(path: str, paths: list[str], extensions: list[str]) -> bool:
    """Return True if path matches any prefix or extension filter (or none set)."""
    if not paths and not extensions:
        return True
    if paths and any(path.startswith(p) for p in paths):
        return True
    if extensions and any(path.endswith(e) for e in extensions):
        return True
    return False


def fetch_pr(
    repo: str,
    number: int,
    handles: list[str],
    paths: list[str],
    extensions: list[str],
) -> dict:
    """Fetch one PR's metadata + filtered comments + reply threads.

    Returns a dict with pr_meta, review_comments (with diff_hunk + reply_thread),
    issue_comments, and pr_description (if authored by any handle).
    """
    pr_meta = _gh_get(f"/repos/{repo}/pulls/{number}")
    review_comments = _gh_get(f"/repos/{repo}/pulls/{number}/comments", paginate=True)
    issue_comments = _gh_get(f"/repos/{repo}/issues/{number}/comments", paginate=True)

    handle_set = set(handles)

    # Index review comments by id for threading
    by_id = {c["id"]: c for c in review_comments}

    # Keep top-level (no in_reply_to_id) comments by our handles, matching
    # path/ext filter. Attach the full reply thread regardless of author.
    kept_reviews = []
    for c in review_comments:
        if c.get("in_reply_to_id") is not None:
            continue
        if _login(c) not in handle_set:
            continue
        if not _matches_path_filter(c["path"], paths, extensions):
            continue
        thread = [
            {
                "id": r["id"],
                "user": _login(r),
                "body": r["body"],
            }
            for r in review_comments
            if r.get("in_reply_to_id") == c["id"]
        ]
        kept_reviews.append({
            "id": c["id"],
            "user": _login(c),
            "path": c["path"],
            "body": c["body"],
            "diff_hunk": c.get("diff_hunk", ""),
            "html_url": c["html_url"],
            "created_at": c["created_at"],
            "reply_thread": thread,
        })

    # Issue comments: no path; just filter by handle
    kept_issues = [
        {
            "id": c["id"],
            "user": _login(c),
            "body": c["body"],
            "html_url": c["html_url"],
            "created_at": c["created_at"],
        }
        for c in issue_comments
        if _login(c) in handle_set
    ]

    # PR description: capture if authored by a handle
    pr_description = None
    if _login(pr_meta) in handle_set:
        pr_description = pr_meta.get("body") or ""

    return {
        "pr_meta": {
            "number": pr_meta["number"],
            "title": pr_meta["title"],
            "author": _login(pr_meta),
            "merged": pr_meta.get("merged", False),
        },
        "review_comments": kept_reviews,
        "issue_comments": kept_issues,
        "pr_description": pr_description,
    }


def _compute_since(months: int) -> str:
    """Return the ISO-8601 UTC cutoff `months` before now."""
    now = datetime.now(timezone.utc)
    delta = timedelta(days=30 * months)
    return (now - delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_collect(
    *,
    alias: str,
    handles: list[str],
    repo: str,
    months: int,
    paths: list[str],
    extensions: list[str],
    since: str | None,
) -> dict:
    """Full scrape pipeline. Writes raw/ + snapshot.json. Returns the snapshot dict."""
    since = since or _compute_since(months)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    persona_dir = PERSONA_ROOT / alias
    raw_dir = persona_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    prs = discover_prs(repo, handles, since)
    print(f"Discovered {len(prs)} PRs touching {','.join(handles)} since {since}", file=sys.stderr)

    counts = {"prs": 0, "review_comments": 0, "issue_comments": 0, "pr_descriptions": 0}

    for i, n in enumerate(prs, 1):
        print(f"  [{i}/{len(prs)}] fetching PR #{n}", file=sys.stderr)
        data = fetch_pr(repo, n, handles, paths, extensions)
        if not data["review_comments"] and not data["issue_comments"] and not data["pr_description"]:
            continue  # PR had nothing matching the filter
        (raw_dir / f"pr-{n}.json").write_text(json.dumps(data, indent=2))
        counts["prs"] += 1
        counts["review_comments"] += len(data["review_comments"])
        counts["issue_comments"] += len(data["issue_comments"])
        if data["pr_description"]:
            counts["pr_descriptions"] += 1

    snapshot = {
        "alias": alias,
        "collected_at": now_iso,
        "since": since,
        "until": now_iso,
        "repo": repo,
        "handles": handles,
        "filters": {"paths": paths, "extensions": extensions},
        "window": {"months": months, "since": since},
        "counts": counts,
    }
    (persona_dir / "snapshot.json").write_text(json.dumps(snapshot, indent=2))
    return snapshot


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: collect a reviewer's comments and write a snapshot."""
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if args.months > WINDOW_CAP_MONTHS and not args.since:
        print(
            f"error: --months {args.months} exceeds hard cap of {WINDOW_CAP_MONTHS}",
            file=sys.stderr,
        )
        return 2

    snapshot = run_collect(
        alias=args.alias,
        handles=[h.strip() for h in args.handles.split(",") if h.strip()],
        repo=args.repo,
        months=args.months,
        paths=[p.strip() for p in args.paths.split(",") if p.strip()],
        extensions=[e.strip() for e in args.extensions.split(",") if e.strip()],
        since=args.since,
    )
    # Print the snapshot to stdout (machine-readable) for the skill to consume
    print(json.dumps(snapshot))
    return 0


if __name__ == "__main__":
    sys.exit(main())
