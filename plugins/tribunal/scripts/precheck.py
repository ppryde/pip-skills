#!/usr/bin/env python3
"""Step 0 of tribunal:reckoning: one cheap GraphQL query decides whether a full run is needed.

    precheck.py check [--repo OWNER/REPO] [--pr N] [--full]
    precheck.py save  [--repo OWNER/REPO] [--pr N] [--with-summary]

`check` prints one JSON object with a `verdict`:
  quiet   - no unresolved threads, nothing new since the last run, head unchanged
            (or changed with no check still running): say one line, skip Steps 1-7
  pending - as quiet, but the head moved and checks are still running on it
  cached  - unresolved threads, but nothing new and the head unchanged: show the
            summary stored by the last full run instead of re-triaging
  full    - anything else (no state, new activity, truncated, --full, errors)

It also records what it saw as a pending snapshot. `save` (after a full run) promotes
that snapshot to the state file, re-counting unresolved threads so threads resolved in
Step 9 are reflected, and with --with-summary stores the summary file the session wrote
to `summary_path`. The newest-activity mark stays the one `check` saw, so a comment that
lands mid-run still counts as new next time.

State lives at $RECKONING_STATE_DIR, else $XDG_STATE_HOME/reckoning, else
~/.local/state/reckoning: outside the plugin, which updates replace. The script reads
only timestamps, counts, SHAs and check names, never a comment body.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

QUERY = """
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      headRefOid
      reviewThreads(first: 100) {
        pageInfo { hasNextPage }
        nodes { isResolved comments(last: 1) { nodes { createdAt updatedAt } } }
      }
      reviews(last: 1) { nodes { submittedAt updatedAt } }
      comments(last: 1) { nodes { createdAt updatedAt } }
      commits(last: 1) {
        nodes { commit { statusCheckRollup { contexts(first: 100) { nodes {
          __typename
          ... on CheckRun { name status }
          ... on StatusContext { context state }
        } } } } }
      }
    }
  }
}
"""

SEG = re.compile(r"[A-Za-z0-9._-]+", re.ASCII)
NUM = re.compile(r"[0-9]{1,9}", re.ASCII)
SHA = re.compile(r"[0-9a-f]{40}", re.ASCII)
STAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", re.ASCII)
NAME = re.compile(r"[^\x00-\x1f\x7f]{1,100}")
GH_TIMEOUT = 30


def state_dir() -> Path:
    explicit = os.environ.get("RECKONING_STATE_DIR")
    if explicit:
        return Path(explicit)
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "reckoning"


def valid_seg(v: str) -> bool:
    return bool(SEG.fullmatch(v)) and v not in (".", "..")


def gh(args: list[str]) -> str | None:
    try:
        proc = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=GH_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def detect(repo: str | None, pr: str | None) -> tuple[str, str, str] | None:
    """(owner, repo, number) from the flags, falling back to the current branch's PR."""
    if repo is None or pr is None:
        args = ["pr", "view", *([pr] if pr else []), "--json", "number,url"]
        out = gh(args + (["--repo", repo] if repo else []))
        if out is None:
            return None
        try:
            data = json.loads(out)
            url_parts = str(data["url"]).split("/")
            owner_repo = f"{url_parts[-4]}/{url_parts[-3]}"
            number = str(data["number"])
        except (ValueError, KeyError, IndexError, TypeError):
            return None
        repo, pr = repo or owner_repo, pr or number
    owner, _, name = repo.partition("/")
    if not (valid_seg(owner) and valid_seg(name) and NUM.fullmatch(pr)):
        return None
    return owner, name, pr


def query(owner: str, repo: str, number: str) -> dict[str, Any] | None:
    out = gh(["api", "graphql", "-f", f"owner={owner}", "-f", f"repo={repo}",
              "-F", f"number={number}", "-f", f"query={QUERY}"])  # fmt: skip
    if out is None:
        return None
    try:
        pr = json.loads(out)["data"]["repository"]["pullRequest"]
    except (ValueError, KeyError, TypeError):
        return None
    return pr if isinstance(pr, dict) else None


def _stamps(nodes: Any) -> list[str]:
    out = []
    for node in nodes or []:
        for key in ("createdAt", "submittedAt", "updatedAt"):
            v = (node or {}).get(key)
            if isinstance(v, str) and STAMP.fullmatch(v):
                out.append(v)
    return out


def summarise(pr: dict[str, Any]) -> dict[str, Any]:
    """Counts and marks from the raw query result; malformed parts read as unknown."""
    threads = pr.get("reviewThreads") or {}
    nodes = threads.get("nodes") or []
    stamps: list[str] = []
    unresolved = 0
    for t in nodes:
        if not (t or {}).get("isResolved"):
            unresolved += 1
        stamps += _stamps(((t or {}).get("comments") or {}).get("nodes"))
    stamps += _stamps((pr.get("reviews") or {}).get("nodes"))
    stamps += _stamps((pr.get("comments") or {}).get("nodes"))
    pending: list[str] = []
    for c in (pr.get("commits") or {}).get("nodes") or []:
        rollup = ((c or {}).get("commit") or {}).get("statusCheckRollup") or {}
        for ctx in (rollup.get("contexts") or {}).get("nodes") or []:
            ctx = ctx or {}
            running = ctx.get("status") not in (None, "COMPLETED") or ctx.get(
                "state"
            ) in ("PENDING", "EXPECTED")
            name = ctx.get("name") or ctx.get("context")
            if running and isinstance(name, str) and NAME.fullmatch(name):
                pending.append(name)
    head = pr.get("headRefOid")
    return {
        "head_sha": head if isinstance(head, str) and SHA.fullmatch(head) else None,
        "unresolved": unresolved,
        "truncated": bool((threads.get("pageInfo") or {}).get("hasNextPage")),
        "newest_activity": max(stamps) if stamps else None,
        "pending_checks": sorted(set(pending)),
    }


def decide(
    now: dict[str, Any], prev: dict[str, Any] | None, full: bool
) -> tuple[str, str]:
    if full:
        return "full", "full report asked for"
    if now["head_sha"] is None:
        return "full", "head commit unknown"
    if now["truncated"]:
        return "full", "more than 100 threads"
    if prev is None:
        return "full", "no previous run recorded"
    if now["newest_activity"] and (
        not prev.get("newest_activity")
        or now["newest_activity"] > prev["newest_activity"]
    ):
        return "full", "new comments or reviews since the last run"
    head_moved = now["head_sha"] != prev.get("head_sha")
    if now["unresolved"] == 0:
        if head_moved and now["pending_checks"]:
            return "pending", "new commits; checks still running"
        return "quiet", "nothing unresolved, nothing new"
    if head_moved:
        return "full", "new commits since the last run"
    if now["unresolved"] == prev.get("unresolved") and prev.get("summary"):
        return "cached", "unchanged since the last run"
    return "full", "thread count changed"


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def paths(owner: str, repo: str, number: str) -> tuple[Path, Path, Path]:
    base = state_dir() / f"{owner}-{repo}-{number}"
    return (
        Path(f"{base}.json"),
        Path(f"{base}.pending.json"),
        Path(f"{base}.summary.md"),
    )


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_check(args: argparse.Namespace) -> dict[str, Any]:
    target = detect(args.repo, args.pr)
    if target is None:
        return {"verdict": "full", "reason": "could not detect the PR"}
    owner, repo, number = target
    out: dict[str, Any] = {"repo": f"{owner}/{repo}", "pr": int(number)}
    pr = query(owner, repo, number)
    if pr is None:
        return {**out, "verdict": "full", "reason": "pre-check query failed"}
    now = summarise(pr)
    state, pending, summary = paths(owner, repo, number)
    prev = _read(state)
    verdict, reason = decide(now, prev, args.full)
    if (
        verdict == "quiet"
    ):  # nothing to triage: record the new head now, no save step follows
        quiet = {k: v for k, v in now.items() if k != "pending_checks"}
        _write(state, {**quiet, "checked_at": now_stamp(), "summary": None})
    else:
        _write(pending, {**now, "checked_at": now_stamp()})
    out.update(verdict=verdict, reason=reason, summary_path=str(summary), **now)
    if prev:
        out["last_checked_at"] = prev.get("checked_at")
    if verdict == "cached":
        out["summary"] = prev["summary"] if prev else None
    return out


def cmd_save(args: argparse.Namespace) -> dict[str, Any]:
    target = detect(args.repo, args.pr)
    if target is None:
        return {"saved": False, "reason": "could not detect the PR"}
    state, pending, summary = paths(*target)
    snap = _read(pending)
    if snap is None:
        return {"saved": False, "reason": "no pre-check snapshot; run check first"}
    pr = query(*target)
    if pr is not None:
        fresh = summarise(pr)
        snap["unresolved"] = fresh["unresolved"]
        snap["head_sha"] = fresh["head_sha"] or snap.get("head_sha")
    snap.pop("pending_checks", None)
    snap["summary"] = None
    if args.with_summary:
        try:
            snap["summary"] = summary.read_text(encoding="utf-8")[:20000] or None
        except (OSError, UnicodeError):
            pass
    _write(state, snap)
    for p in (pending, summary):
        p.unlink(missing_ok=True)
    return {
        "saved": True,
        "state": str(state),
        "summary_stored": snap["summary"] is not None,
    }


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="precheck.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("check", "save"):
        p = sub.add_parser(name)
        p.add_argument("--repo")
        p.add_argument("--pr")
    sub.choices["check"].add_argument("--full", action="store_true")
    sub.choices["save"].add_argument("--with-summary", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    result = cmd_check(args) if args.cmd == "check" else cmd_save(args)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
