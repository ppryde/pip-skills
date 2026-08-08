"""Census CLI — record and read status-line session state. Pure stdlib."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):  # direct invocation: put plugin root on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import statusline as sl  # noqa: E402
from scripts import store as st  # noqa: E402


def cmd_ingest(args: argparse.Namespace) -> int:
    st.ingest(sys.stdin.read())
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    if args.limits:
        out: object = st.limits()
    elif args.session:
        out = st.for_session(args.session)
    elif args.worktree:
        out = st.latest_for_worktree(args.worktree)
    else:
        out = st.read_all()
    print(json.dumps(out if out is not None else {}))
    return 0


def _statusline_path() -> Path:
    return Path.home() / ".claude" / "statusline-command.sh"


def cmd_install_statusline(args: argparse.Namespace) -> int:
    path = Path(args.path) if args.path else _statusline_path()
    if not path.exists():
        print(f"no status-line script at {path}", file=sys.stderr)
        return 1
    text = path.read_text()
    updated = sl.remove_block(text) if args.uninstall else sl.add_block(text)
    if updated == text:
        print("no change")
        return 0
    path.write_text(updated)
    print(f"{'removed' if args.uninstall else 'installed'} census block in {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="census", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ingest", help="read a status-line payload on stdin and record it").set_defaults(
        func=cmd_ingest
    )

    read = sub.add_parser("read", help="print store contents as JSON")
    group = read.add_mutually_exclusive_group()
    group.add_argument("--worktree", help="freshest session indexed to this worktree cwd")
    group.add_argument("--session", help="the entry for this session id")
    group.add_argument("--limits", action="store_true", help="just the account rate limits")
    read.set_defaults(func=cmd_read)

    install = sub.add_parser(
        "install-statusline", help="add (or --uninstall) the census block in the status-line script"
    )
    install.add_argument("--path", help="status-line script (default ~/.claude/statusline-command.sh)")
    install.add_argument("--uninstall", action="store_true", help="remove the block instead")
    install.set_defaults(func=cmd_install_statusline)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if not exc.code else 1
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
