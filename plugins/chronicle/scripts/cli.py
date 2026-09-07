"""chronicle CLI — ingest and read/report verbs.

Pull only: nothing here runs inside a Claude Code session. ``sync`` (and
``ingest`` for one transcript) is how rows get in, driven by a person or by
the dashboard, which syncs on open and every minute while the Chronicle page
shows. There are deliberately no hooks — a Stop hook that runs code after
every turn is a feedback loop waiting to happen, and the per-file cursors make
polling cheap enough that a live feed buys nothing.

Report verbs print JSON to stdout for the dashboard / other tools.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Allow `python plugins/chronicle/scripts/cli.py` from anywhere.
_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from scripts import ingest, report, store


def cmd_ingest(args: argparse.Namespace) -> int:
    path = Path(args.transcript)
    if not path.is_file():
        print(f"chronicle: no transcript at {path}", file=sys.stderr)
        return 1
    conn = store.connect()
    try:
        result = ingest.ingest_session(conn, path, args.session_id)
    finally:
        conn.close()
    print(json.dumps(result))
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    """Reconcile the store with the transcripts on disk (see ``ingest.sync``).
    Defaults to every watched config dir's ``projects/``; ``--projects`` (one
    or more) replaces that set."""
    projects = [Path(p) for p in args.projects] if args.projects else store.projects_dirs()
    conn = store.connect()
    try:
        result = ingest.sync(conn, projects, full=bool(getattr(args, "full", False)))
    finally:
        conn.close()
    out: dict[str, Any] = {
        **result,
        "projects_dirs": [str(p) for p in projects],
        "db": str(store.db_path()),
    }
    print(json.dumps(out))
    return 0


def _open_readonly() -> Any:
    try:
        return store.connect(readonly=True)
    except FileNotFoundError:
        return None


def cmd_status(_: argparse.Namespace) -> int:
    path = store.db_path()
    conn = _open_readonly()
    if conn is None:
        print(json.dumps({"db": str(path), "exists": False}))
        return 0
    try:
        out = {"db": str(path), "exists": True, **report.status(conn)}
    finally:
        conn.close()
    print(json.dumps(out))
    return 0


def _since(days: int | None) -> float | None:
    return time.time() - days * 86400 if days else None


def cmd_summary(args: argparse.Namespace) -> int:
    conn = _open_readonly()
    if conn is None:
        print(json.dumps({"totals": None}))
        return 0
    try:
        out = report.summary(conn, repo_root=args.root, since=_since(args.days), branch=args.branch)
    finally:
        conn.close()
    print(json.dumps(out))
    return 0


def cmd_sessions(args: argparse.Namespace) -> int:
    conn = _open_readonly()
    if conn is None:
        print(json.dumps({"sessions": []}))
        return 0
    try:
        rows = report.sessions(conn, repo_root=args.root, since=_since(args.days), limit=args.limit,
                               branch=args.branch)
    finally:
        conn.close()
    print(json.dumps({"sessions": rows}))
    return 0


def cmd_session(args: argparse.Namespace) -> int:
    conn = _open_readonly()
    if conn is None:
        print(f"chronicle: no store at {store.db_path()}", file=sys.stderr)
        return 1
    try:
        detail = report.session_detail(conn, args.session_id)
    finally:
        conn.close()
    if detail is None:
        print(f"chronicle: no session {args.session_id}", file=sys.stderr)
        return 1
    print(json.dumps(detail))
    return 0


# A docker volume name, and the path within it. Validated rather than trusted:
# both are interpolated into a `docker run` argv, and a value starting with "-"
# would be read by docker as an option rather than as a name.
_VOLUME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
# Leading dot allowed — the default source is `.config/claude/projects`. A `..`
# segment is not: the helper mounts the volume read-only, but a traversal would
# still let the copy read the helper image's own filesystem.
_SOURCE_RE = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9_./-]*$")
# The helper image, validated for the same reason and more urgently: it sits at
# the one argv position where docker is still parsing its OWN options, so an
# unvalidated value is the easiest of the three to turn into a flag. Registry
# host, port, path segments, a `:tag` and an `@sha256:` digest all pass; a
# space or a leading dash does not.
_IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-/:@]*$")
_PULL_TIMEOUT_SECONDS = 900


def cmd_pull_volume(args: argparse.Namespace) -> int:
    """`chronicle pull-volume` — copy transcripts out of a docker named volume
    onto this filesystem, so a containerised account can be watched like any
    other config dir.

    A named volume lives inside the Docker VM; on macOS its Mountpoint is not a
    host path at all, so it cannot simply be listed in `claude_dirs`. A helper
    container is the only reader that can see it. The copy is incremental
    (`cp -au` — archive, and only what is newer), so the first pull is the
    expensive one and later pulls move just the transcripts that grew.

    Pull only, like every other verb here: nothing watches, nothing daemonises.
    """
    if not _VOLUME_RE.match(args.volume):
        print(json.dumps({"error": f"invalid volume name: {args.volume!r}"}), file=sys.stderr)
        return 2
    source = args.source.strip("/")
    if not _SOURCE_RE.match(source) or ".." in Path(source).parts:
        print(json.dumps({"error": f"invalid source path: {args.source!r}"}), file=sys.stderr)
        return 2
    if not _IMAGE_RE.match(args.image):
        print(json.dumps({"error": f"invalid image: {args.image!r}"}), file=sys.stderr)
        return 2
    dest = Path(args.dest).expanduser()
    if not dest.is_absolute():
        print(json.dumps({"error": "dest must be an absolute path (docker requires one)"}),
              file=sys.stderr)
        return 2
    # Created HERE, not by the container: the container needs no shell to
    # mkdir, so nothing is interpolated into one.
    #
    # Ownership caveat — this is a Docker DESKTOP recipe. On macOS and Windows
    # the bind mount remaps uids, so what the root helper writes lands owned by
    # the invoking user. On a Linux host there is no remapping: `cp -a`
    # preserves the source uid and mode, so a 0600 root-owned transcript stays
    # unreadable to whoever later runs `chronicle sync` — and `_read_new_lines`
    # catches that OSError and returns [], making the ingest a SILENT no-op
    # rather than an error. Verified only on Docker Desktop; a Linux user
    # wanting this should add `--user "$(id -u):$(id -g)"` below, having first
    # checked that uid can read the volume's contents.
    projects = dest / "projects"
    try:
        projects.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(json.dumps({"error": f"cannot create {projects}: {exc}"}), file=sys.stderr)
        return 1
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{args.volume}:/v:ro",
        "-v", f"{dest}:/out",
        args.image,
        "cp", "-au", f"/v/{source}/.", "/out/projects/",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=_PULL_TIMEOUT_SECONDS, check=False)
    except FileNotFoundError:
        print(json.dumps({"error": "docker not found on PATH"}), file=sys.stderr)
        return 1
    except subprocess.SubprocessError as exc:
        print(json.dumps({"error": f"docker run failed: {exc}"}), file=sys.stderr)
        return 1
    if result.returncode != 0:
        print(json.dumps({"error": (result.stderr or result.stdout).strip()[:500],
                          "returncode": result.returncode}), file=sys.stderr)
        return 1
    pulled = list(projects.rglob("*.jsonl"))
    # A pulled transcript this user cannot read is the failure mode of the
    # ownership caveat above (see the comment on `projects.mkdir`): `sync`
    # would skip it inside `_read_new_lines`'s OSError guard and ingest
    # nothing, reporting success. Counted here so the pull says so plainly
    # rather than leaving a silent hole in the history.
    unreadable = sum(1 for f in pulled if not os.access(f, os.R_OK))
    out: dict[str, Any] = {
        "volume": args.volume,
        "dest": str(dest),
        "transcripts": len(pulled),
        "bytes": sum(f.stat().st_size for f in pulled),
        "hint": f"watch it with: overseer claude-dirs add {dest}",
    }
    if unreadable:
        out["unreadable"] = unreadable
        out["warning"] = (
            f"{unreadable} pulled transcript(s) are not readable by this user and would be "
            f"skipped silently by sync — re-run with `--user \"$(id -u):$(id -g)\"` on the "
            f"docker helper, or chown {projects}"
        )
    print(json.dumps(out))
    return 0


def cmd_agent(args: argparse.Namespace) -> int:
    conn = _open_readonly()
    if conn is None:
        print(f"chronicle: no store at {store.db_path()}", file=sys.stderr)
        return 1
    try:
        detail = report.agent_detail(conn, args.session_id, args.agent_id)
    finally:
        conn.close()
    if detail is None:
        print(f"chronicle: no agent {args.agent_id} in session {args.session_id}",
              file=sys.stderr)
        return 1
    print(json.dumps(detail))
    return 0


def cmd_repos(_: argparse.Namespace) -> int:
    conn = _open_readonly()
    if conn is None:
        print(json.dumps({"repos": []}))
        return 0
    try:
        rows = report.repos(conn)
    finally:
        conn.close()
    print(json.dumps({"repos": rows}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chronicle", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest", help="ingest one transcript (and its subagents) now")
    p.add_argument("--transcript", required=True)
    p.add_argument("--session-id", default=None)
    p.set_defaults(fn=cmd_ingest)

    for verb, help_text in (
        ("sync", "pull-on-demand: ingest every transcript whose file moved since last seen"),
        ("backfill", "alias of sync (a first run over an empty store)"),
    ):
        p = sub.add_parser(verb, help=help_text)
        p.add_argument("--projects", action="append", default=None,
                       help="a projects/ dir to scan (repeatable); default: every watched "
                            "config dir's — see `overseer claude-dirs`")
        p.add_argument("--full", action="store_true",
                       help="forget every cursor and re-read all transcripts (after a schema change)")
        p.set_defaults(fn=cmd_sync)

    sub.add_parser("status", help="store location and row counts (JSON)").set_defaults(fn=cmd_status)

    p = sub.add_parser("summary", help="aggregate metrics (JSON)")
    p.add_argument("--root", default=None, help="scope to one main repo root")
    p.add_argument("--days", type=int, default=None, help="only sessions active in the last N days")
    p.add_argument("--branch", default=None,
                   help="only sessions whose last-seen git branch matches (session-level)")
    p.set_defaults(fn=cmd_summary)

    p = sub.add_parser("sessions", help="session rows, most recent first (JSON)")
    p.add_argument("--root", default=None)
    p.add_argument("--days", type=int, default=None)
    p.add_argument("--branch", default=None)
    p.add_argument("--limit", type=int, default=200)
    p.set_defaults(fn=cmd_sessions)

    p = sub.add_parser("session", help="one session in detail, with its turn series (JSON)")
    p.add_argument("session_id")
    p.set_defaults(fn=cmd_session)

    p = sub.add_parser("agent", help="one subagent of a session in detail (JSON)")
    p.add_argument("session_id")
    p.add_argument("agent_id")
    p.set_defaults(fn=cmd_agent)

    sub.add_parser("repos", help="repo roots seen, with session counts (JSON)").set_defaults(fn=cmd_repos)

    p = sub.add_parser("pull-volume",
                       help="copy transcripts out of a docker named volume onto this filesystem")
    p.add_argument("--volume", required=True, help="docker named volume, e.g. wf-state")
    p.add_argument("--dest", required=True,
                   help="absolute host dir to copy into; watch it with `overseer claude-dirs add`")
    p.add_argument("--source", default=".config/claude/projects",
                   help="path to projects/ within the volume (default: %(default)s)")
    p.add_argument("--image", default="alpine",
                   help="helper image used to read the volume (default: %(default)s)")
    p.set_defaults(fn=cmd_pull_volume)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
