#!/usr/bin/env python3
"""Scrape GitHub for a reviewer's PR comments. Writes raw + snapshot + digest to
<persona root>/<alias>/ (see persona_io: ${CLAUDE_CONFIG_DIR:-~/.claude}/review-clone/personas).
Stdout is one JSON line (the snapshot); progress goes to stderr.

    collect.py --alias A --handles h1,h2 --repo owner/name [--months 6] [--paths P] [--extensions E]
               [--since ISO | --incremental] [--workers 3] [--fresh]
    collect.py check   --repo owner/name          # visibility + your permission, writes nothing
    collect.py digest  --alias A [--since ISO]    # rebuild the compact corpus from raw/
    collect.py cleanup --alias A                  # delete raw/, digest and progress (private data)

Everything written is private to the owner (dirs 0700, files 0600). The scrape is
bounded-parallel (3-4 workers), retries 403/429/5xx with Retry-After backoff, and
checkpoints per PR, so a run killed by a timeout resumes where it stopped.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

WINDOW_CAP_MONTHS = 6
SEARCH_LIMIT = 1000
MAX_WORKERS = 4
MAX_ATTEMPTS = 4
MAX_BACKOFF = 120.0

try:  # imported as a package (tests)
    from .persona_io import PERSONA_ROOT, check_alias, ensure_private_dir, write_private
except ImportError:  # run as a script: scripts/ is on sys.path
    from persona_io import PERSONA_ROOT, check_alias, ensure_private_dir, write_private

_sleep = time.sleep  # tests replace this


def _add_collect_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--alias", required=True, help="Persona alias (kebab-case).")
    p.add_argument("--handles", required=True,
                   help="Comma-separated GitHub handles (e.g. 'jane,bob').")
    p.add_argument("--repo", required=True, help="GitHub repo, e.g. 'owner/repo'.")
    p.add_argument("--months", type=int, default=6,
                   help="Lookback in months (default 6, hard cap 6 in v1).")
    p.add_argument("--paths", default="",
                   help="Comma-separated path prefixes to include (empty = all).")
    p.add_argument("--extensions", default="",
                   help="Comma-separated file extensions to include (empty = all).")
    p.add_argument("--since", default=None,
                   help="ISO datetime to scrape since (refresh mode). Overrides --months.")
    p.add_argument("--incremental", action="store_true",
                   help="Scrape only comments newer than the snapshot's watermark "
                        "(merged into raw/, nothing old is lost).")
    p.add_argument("--workers", type=int, default=3,
                   help=f"Parallel fetches, 1-{MAX_WORKERS} (default 3).")
    p.add_argument("--fresh", action="store_true",
                   help="Ignore a checkpoint left by an interrupted run.")


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse collect.py's command-line arguments (the collect form)."""
    p = argparse.ArgumentParser(
        prog="collect.py",
        description="Scrape a reviewer's GitHub comments for review-clone.",
    )
    _add_collect_args(p)
    return p.parse_args(argv)


class GhError(Exception):
    """A `gh` call failed for good (after retries)."""

    def __init__(self, message: str, stderr: str = ""):
        super().__init__(message)
        self.stderr = stderr


_pause_lock = threading.Lock()
_pause_until = 0.0
_truncated: list[str] = []  # handles whose search hit the result limit


def _retry_after(stderr: str) -> float | None:
    m = re.search(r"retry[- ]after:?\s*(\d+)", stderr, re.IGNORECASE)
    return float(m.group(1)) if m else None


def _retryable(stderr: str) -> bool:
    low = stderr.lower()
    if re.search(r"http (429|5\d\d)", low):
        return True
    if "http 403" in low and any(k in low for k in ("rate limit", "secondary", "abuse", "retry")):
        return True
    return any(k in low for k in ("timed out", "timeout", "connection reset", "temporarily"))


def _run_gh(cmd: list[str]) -> subprocess.CompletedProcess:
    """Run a gh command, backing off on rate limits and transient errors.

    Honours a Retry-After value when gh reports one; a pause set by one worker
    holds the others too, so a secondary limit is not hammered in parallel."""
    global _pause_until
    last: subprocess.CalledProcessError | None = None
    for attempt in range(MAX_ATTEMPTS):
        with _pause_lock:
            wait = _pause_until - time.monotonic()
        if wait > 0:
            _sleep(wait)
        try:
            return subprocess.run(cmd, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as exc:
            last = exc
            err = exc.stderr or ""
            if "unknown flag" in err or not _retryable(err) or attempt == MAX_ATTEMPTS - 1:
                raise
            delay = min(_retry_after(err) or (2.0 ** (attempt + 1)) + random.random(), MAX_BACKOFF)
            with _pause_lock:
                _pause_until = max(_pause_until, time.monotonic() + delay)
            print(f"  gh rate-limited or unavailable; backing off {delay:.0f}s", file=sys.stderr)
    raise last  # pragma: no cover - the loop always returns or raises


def check_repo_access(repo: str) -> dict:
    """Visibility and the caller's permission on `repo`; raises GhError when unreadable."""
    cmd = ["gh", "repo", "view", repo, "--json", "visibility,viewerPermission"]
    try:
        result = _run_gh(cmd)
    except subprocess.CalledProcessError as exc:
        raise GhError(f"cannot read {repo} with your gh login: {(exc.stderr or '').strip()[:200]}",
                      exc.stderr or "") from exc
    data = json.loads(result.stdout or "{}")
    vis = str(data.get("visibility") or "UNKNOWN").upper()
    perm = data.get("viewerPermission")
    return {"repo": repo, "visibility": vis.lower(), "private": vis != "PUBLIC",
            "viewer_permission": perm, "can_read": bool(perm)}


def _gh_search(repo: str, handle: str, since: str) -> list[dict]:
    """Call `gh search prs --json number,updatedAt`. Returns list of PR dicts."""
    cmd = [
        "gh", "search", "prs",
        "--repo", repo,
        "--involves", handle,
        "--updated", f">={since}",
        "--limit", str(SEARCH_LIMIT),
        "--json", "number,updatedAt",
    ]
    try:
        result = _run_gh(cmd)
    except subprocess.CalledProcessError as exc:
        raise GhError(f"gh search failed for {handle}: {(exc.stderr or '').strip()[:200]}",
                      exc.stderr or "") from exc
    found = json.loads(result.stdout) if result.stdout.strip() else []
    if len(found) >= SEARCH_LIMIT:
        _truncated.append(handle)
    return found


def discover_prs(repo: str, handles: list[str], since: str) -> list[int]:
    """Return deduplicated list of PR numbers touched by any handle since the given ISO date."""
    seen: set[int] = set()
    for handle in handles:
        for pr in _gh_search(repo, handle, since):
            seen.add(pr["number"])
    return sorted(seen)


_REPO_RE = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")


def _check_repo(repo: str) -> str:
    """Return repo unchanged, or raise ValueError if it is not an owner/name slug."""
    if not _REPO_RE.fullmatch(repo or ""):
        raise ValueError(f"invalid repo {repo!r}: expected owner/name")
    return repo


def _gh_get(api_path: str, paginate: bool = False) -> Any:
    """Call `gh api <path>` and return parsed JSON.

    Paginated calls use `--paginate --slurp` (gh >= 2.48) with per_page=100 and
    return the pages flattened into one list. Transient errors are retried with
    backoff; any other failure raises GhError (the caller records it per PR).
    """
    cmd = ["gh", "api", api_path]
    if paginate:
        sep = "&" if "?" in api_path else "?"
        cmd = ["gh", "api", f"{api_path}{sep}per_page=100", "--paginate", "--slurp"]
    try:
        result = _run_gh(cmd)
    except subprocess.CalledProcessError as exc:
        err = exc.stderr or ""
        if paginate and ("unknown flag" in err or "--slurp" in err):
            print(
                "error: `gh api --paginate --slurp` failed; review-clone needs "
                f"gh >= 2.48 (upgrade gh and retry). gh said: {err or exc}",
                file=sys.stderr,
            )
            raise SystemExit(2) from exc
        raise GhError(f"{api_path}: {err.strip()[:200] or exc}", err) from exc
    if not result.stdout.strip():
        return []
    data = json.loads(result.stdout)
    if paginate:
        return [item for page in data for item in page]
    return data


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
    since: str | None = None,
) -> dict:
    """Fetch one PR's metadata + filtered comments + reply threads.

    When `since` is given, handle-authored comments created before it are dropped.

    Returns a dict with pr_meta, review_comments (with diff_hunk + reply_thread),
    issue_comments, and pr_description (if authored by any handle).
    """
    pr_meta = _gh_get(f"/repos/{repo}/pulls/{number}")
    review_comments = _gh_get(f"/repos/{repo}/pulls/{number}/comments", paginate=True)
    issue_comments = _gh_get(f"/repos/{repo}/issues/{number}/comments", paginate=True)

    handle_set = {h.lower() for h in handles}

    # Replies indexed by parent once (was a scan of every comment per comment).
    replies: dict[Any, list[dict]] = {}
    for r in review_comments:
        parent = r.get("in_reply_to_id")
        if parent is not None:
            replies.setdefault(parent, []).append(
                {"id": r["id"], "user": _login(r), "body": r["body"]})

    # Keep top-level (no in_reply_to_id) comments by our handles, matching
    # path/ext filter. Attach the full reply thread regardless of author.
    kept_reviews = []
    for c in review_comments:
        if c.get("in_reply_to_id") is not None:
            continue
        if (_login(c) or "").lower() not in handle_set:
            continue
        if since and c["created_at"] < since:
            continue
        if not _matches_path_filter(c["path"], paths, extensions):
            continue
        kept_reviews.append({
            "id": c["id"],
            "user": _login(c),
            "path": c["path"],
            "body": c["body"],
            "diff_hunk": c.get("diff_hunk", ""),
            "html_url": c["html_url"],
            "created_at": c["created_at"],
            "reply_thread": replies.get(c["id"], []),
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
        if (_login(c) or "").lower() in handle_set
        and not (since and c["created_at"] < since)
    ]

    # PR description: capture if authored by a handle
    pr_description = None
    if (_login(pr_meta) or "").lower() in handle_set:
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


def _merge_pr(old: dict, new: dict) -> dict:
    """Union an existing raw PR file with a fresher fetch: nothing old is lost.

    Comments are matched by id (the newer copy wins, so a longer reply thread
    replaces a shorter one)."""
    def union(a: list[dict], b: list[dict]) -> list[dict]:
        by_id = {c["id"]: c for c in a}
        by_id.update({c["id"]: c for c in b})
        return sorted(by_id.values(), key=lambda c: (c.get("created_at", ""), c["id"]))

    merged = dict(new)
    merged["review_comments"] = union(old.get("review_comments", []), new["review_comments"])
    merged["issue_comments"] = union(old.get("issue_comments", []), new["issue_comments"])
    merged["pr_description"] = new["pr_description"] or old.get("pr_description")
    return merged


def _run_key(repo, handles, paths, extensions, explicit_since, months) -> str:
    blob = json.dumps([repo, sorted(h.lower() for h in handles), paths, extensions,
                       explicit_since, None if explicit_since else months])
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def _newest(raw_dir: Path) -> str | None:
    newest = None
    for f in raw_dir.glob("pr-*.json"):
        try:
            data = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        for c in data.get("review_comments", []) + data.get("issue_comments", []):
            t = c.get("created_at")
            if t and (newest is None or t > newest):
                newest = t
    return newest


def run_collect(
    *,
    alias: str,
    handles: list[str],
    repo: str,
    months: int,
    paths: list[str],
    extensions: list[str],
    since: str | None,
    visibility: dict | None = None,
    workers: int = 3,
    fresh: bool = False,
    digest: bool = True,
) -> dict:
    """Full scrape pipeline. Writes raw/ + snapshot.json (+ digest). Returns the snapshot.

    One PR failing never aborts the run: it is recorded in `errors` and the
    snapshot is written regardless. Progress is checkpointed after each PR."""
    check_alias(alias, PERSONA_ROOT)
    _check_repo(repo)
    explicit_since = since  # per-comment filter applies only in refresh mode
    since = since or _compute_since(months)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    persona_dir = PERSONA_ROOT / alias
    raw_dir = persona_dir / "raw"
    ensure_private_dir(raw_dir)
    _truncated.clear()

    prs = discover_prs(repo, handles, since)
    print(f"Discovered {len(prs)} PRs touching {','.join(handles)} since {since}", file=sys.stderr)

    key = _run_key(repo, handles, paths, extensions, explicit_since, months)
    progress_file = persona_dir / "progress.json"
    progress: dict = {"key": key, "done": {}, "errors": {}}
    if not fresh and progress_file.exists():
        try:
            saved = json.loads(progress_file.read_text())
            if saved.get("key") == key:
                progress = saved
        except (OSError, ValueError):
            pass
    resumed = len(progress["done"])
    if resumed:
        print(f"  resuming: {resumed} PRs already collected", file=sys.stderr)
    progress["errors"] = {}

    def checkpoint() -> None:
        write_private(progress_file, json.dumps(progress))

    todo = [n for n in prs if str(n) not in progress["done"]]
    workers = max(1, min(int(workers), MAX_WORKERS))

    def work(n: int):
        try:
            return n, fetch_pr(repo, n, handles, paths, extensions, explicit_since), None
        except GhError as exc:
            return n, None, str(exc)
        except Exception as exc:  # noqa: BLE001 - one PR must not end the run
            return n, None, f"{type(exc).__name__}: {exc}"

    def absorb(n: int, data: dict | None, err: str | None, done_n: int) -> None:
        print(f"  [{done_n}/{len(todo)}] PR #{n}" + (f" FAILED: {err}" if err else ""),
              file=sys.stderr)
        if err or data is None:
            progress["errors"][str(n)] = err or "no data"
            return
        empty = (not data["review_comments"] and not data["issue_comments"]
                 and not data["pr_description"])
        delta = [len(data["review_comments"]), len(data["issue_comments"]),
                 1 if data["pr_description"] else 0]  # this fetch only, not the merged file
        if not empty:
            target = raw_dir / f"pr-{n}.json"
            if explicit_since and target.exists():
                try:
                    data = _merge_pr(json.loads(target.read_text()), data)
                except (OSError, ValueError, KeyError):
                    pass
            write_private(target, json.dumps(data, indent=2))
        progress["done"][str(n)] = [0 if empty else 1, *delta, 0 if empty else 1]
        checkpoint()

    if workers == 1 or len(todo) <= 1:
        for i, n in enumerate(todo, 1):
            absorb(*work(n), i)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(work, n) for n in todo]
            for i, fut in enumerate(as_completed(futures), 1):
                absorb(*fut.result(), i)

    if not explicit_since:
        # A full pull replaces the corpus: drop raw files this run did not produce
        # (removed handles, an earlier filter set).
        keep = {f"pr-{n}.json" for n, v in progress["done"].items() if v[4]}
        for f in raw_dir.glob("pr-*.json"):
            if f.name not in keep and not progress["errors"]:
                f.unlink()

    counts = {"prs": 0, "review_comments": 0, "issue_comments": 0, "pr_descriptions": 0}
    for v in progress["done"].values():
        counts["prs"] += v[0]
        counts["review_comments"] += v[1]
        counts["issue_comments"] += v[2]
        counts["pr_descriptions"] += v[3]

    errors = [{"pr": int(n), "error": e} for n, e in sorted(progress["errors"].items(),
                                                            key=lambda kv: int(kv[0]))]
    vis = visibility or {}
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
        "visibility": vis.get("visibility", "unknown"),
        "private_source": bool(vis.get("private", False)),
        "watermark": _newest(raw_dir) or explicit_since or since,
        "errors": errors,
        "search_truncated": sorted(set(_truncated)),
        "resumed_prs": resumed,
    }
    if digest:
        snapshot["digest"] = build_digest(alias, handles, since=explicit_since)
    write_private(persona_dir / "snapshot.json", json.dumps(snapshot, indent=2))
    if errors:
        print(f"warning: {len(errors)} PR(s) failed; re-run the same command to resume "
              "(finished PRs are skipped)", file=sys.stderr)
    else:
        progress_file.unlink(missing_ok=True)  # done: the next run starts clean
    if snapshot["search_truncated"]:
        print(f"warning: gh search returned {SEARCH_LIMIT} results for "
              f"{snapshot['search_truncated']}; older PRs may be missing - narrow the window",
              file=sys.stderr)
    return snapshot


# --------------------------------------------------------------------- digest --

DIGEST_BODY = 600
DIGEST_HUNK_LINES = 3


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + f"... [+{len(text) - limit} chars]"


def build_digest(alias: str, handles: list[str], since: str | None = None) -> dict:
    """Write digest.jsonl: one compact JSON object per handle-authored comment.

    Review comments keep the last few hunk lines, the handles' own replies (a
    withdrawal is theirs) and a count of the other authors' replies; bodies are
    truncated. `since` limits it to comments created on or after that time
    (refresh). The full text stays in raw/pr-<n>.json for on-demand reading."""
    persona_dir = PERSONA_ROOT / alias
    raw_dir = persona_dir / "raw"
    handle_set = {h.lower() for h in handles}
    rows: list[dict] = []
    for f in sorted(raw_dir.glob("pr-*.json"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 0)):
        try:
            data = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        meta = data.get("pr_meta", {})
        pr = meta.get("number")
        title = _clip(meta.get("title", ""), 120)
        for c in data.get("review_comments", []):
            if since and c.get("created_at", "") < since:
                continue
            thread = c.get("reply_thread", [])
            own = [{"user": r.get("user"), "body": _clip(r.get("body", ""), DIGEST_BODY)}
                   for r in thread if (r.get("user") or "").lower() in handle_set]
            hunk = "\n".join((c.get("diff_hunk") or "").splitlines()[-DIGEST_HUNK_LINES:])
            rows.append({"pr": pr, "title": title, "kind": "review", "id": c["id"],
                         "url": c.get("html_url"), "created_at": c.get("created_at"),
                         "path": c.get("path"), "hunk": hunk,
                         "body": _clip(c.get("body", ""), DIGEST_BODY),
                         "own_replies": own, "other_replies": len(thread) - len(own)})
        for c in data.get("issue_comments", []):
            if since and c.get("created_at", "") < since:
                continue
            rows.append({"pr": pr, "title": title, "kind": "issue", "id": c["id"],
                         "url": c.get("html_url"), "created_at": c.get("created_at"),
                         "body": _clip(c.get("body", ""), DIGEST_BODY)})
        if data.get("pr_description"):
            rows.append({"pr": pr, "title": title, "kind": "description",
                         "body": _clip(data["pr_description"], DIGEST_BODY * 2)})
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    out = persona_dir / "digest.jsonl"
    ensure_private_dir(persona_dir)
    write_private(out, text)
    return {"file": str(out), "items": len(rows), "bytes": len(text.encode("utf-8"))}


def cleanup_private_data(alias: str) -> dict:
    """Delete raw/, digest.jsonl and progress.json (the scraped text). PERSONA.md,
    snapshot.json and the slash command are kept."""
    check_alias(alias, PERSONA_ROOT)
    d = PERSONA_ROOT / alias
    removed = []
    if (d / "raw").is_dir():
        shutil.rmtree(d / "raw")
        removed.append(str(d / "raw"))
    for name in ("digest.jsonl", "progress.json"):
        if (d / name).exists():
            (d / name).unlink()
            removed.append(str(d / name))
    return {"removed": removed}


def _fail(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 2


def _split(value: str) -> list[str]:
    return [x.strip() for x in value.split(",") if x.strip()]


def _snapshot_watermark(alias: str) -> str | None:
    try:
        return json.loads((PERSONA_ROOT / alias / "snapshot.json").read_text()).get("watermark")
    except (OSError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: collect a reviewer's comments and write a snapshot."""
    argv = list(argv if argv is not None else sys.argv[1:])
    cmd = argv[0] if argv and argv[0] in ("collect", "check", "digest", "cleanup") else "collect"
    if argv and argv[0] == "collect":
        argv = argv[1:]
    if cmd == "check":
        p = argparse.ArgumentParser(prog="collect.py check")
        p.add_argument("--repo", required=True)
        a = p.parse_args(argv[1:])
        try:
            _check_repo(a.repo)
            info = check_repo_access(a.repo)
        except (ValueError, GhError) as exc:
            return _fail(str(exc))
        print(json.dumps(info))
        return 0 if info["can_read"] else _fail(f"no read access to {a.repo}")
    if cmd in ("digest", "cleanup"):
        p = argparse.ArgumentParser(prog=f"collect.py {cmd}")
        p.add_argument("--alias", required=True)
        if cmd == "digest":
            p.add_argument("--since", default=None)
        a = p.parse_args(argv[1:])
        try:
            check_alias(a.alias, PERSONA_ROOT)
            if cmd == "cleanup":
                print(json.dumps(cleanup_private_data(a.alias)))
                return 0
            snap = json.loads((PERSONA_ROOT / a.alias / "snapshot.json").read_text())
            print(json.dumps(build_digest(a.alias, snap.get("handles", []), since=a.since)))
            return 0
        except (ValueError, OSError) as exc:
            return _fail(str(exc))

    args = parse_args(argv)
    if args.months > WINDOW_CAP_MONTHS and not args.since:
        return _fail(f"--months {args.months} exceeds hard cap of {WINDOW_CAP_MONTHS}")

    try:
        check_alias(args.alias, PERSONA_ROOT)
        _check_repo(args.repo)
    except ValueError as exc:
        return _fail(str(exc))

    since = args.since
    if args.incremental and not since:
        since = _snapshot_watermark(args.alias)
        if not since:
            return _fail("--incremental needs an earlier snapshot with a watermark; "
                         "run a full collect first (or pass --since)")
    try:
        visibility = check_repo_access(args.repo)
        if not visibility["can_read"]:
            return _fail(f"no read access to {args.repo} with your gh login")
        if visibility["private"]:
            print(f"note: {args.repo} is {visibility['visibility']}; collected data is stored "
                  "private (0700/0600) and marked private_source", file=sys.stderr)
        snapshot = run_collect(
            alias=args.alias,
            handles=_split(args.handles),
            repo=args.repo,
            months=args.months,
            paths=_split(args.paths),
            extensions=_split(args.extensions),
            since=since,
            visibility=visibility,
            workers=args.workers,
            fresh=args.fresh,
        )
    except GhError as exc:
        return _fail(str(exc))
    # Print the snapshot to stdout (machine-readable) for the skill to consume
    print(json.dumps(snapshot))
    return 0


if __name__ == "__main__":
    sys.exit(main())
