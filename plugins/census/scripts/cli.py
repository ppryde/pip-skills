"""Census CLI — record and read status-line session state. Pure stdlib."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):  # direct invocation: put plugin root on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import install as ins
from scripts import statusline as sl
from scripts import store as st


def cmd_ingest(args: argparse.Namespace) -> int:
    st.ingest(sys.stdin.read())
    try:  # the pointer is best-effort; ingest's exit code must stay 0
        st.publish_location(Path(__file__))
    except Exception:  # noqa: BLE001, S110 - best-effort pointer, never raises
        pass
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    if args.limits:
        out: object = st.all_limits() if args.all else st.limits()
    elif args.session:
        out = st.for_session(args.session)
    elif args.worktree:
        out = st.latest_for_worktree(args.worktree)
    else:
        out = st.read_all()
    print(json.dumps(out if out is not None else {}))
    return 0


def _statusline_path() -> Path:
    return st.config_dir() / "statusline-command.sh"


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


def _default_shim() -> Path:
    return Path.home() / ".local" / "bin" / "census"


def _this_cli() -> Path:
    return Path(__file__).resolve()


def cmd_install(args: argparse.Namespace) -> int:
    code, lines = ins.install(
        Path(args.shim) if args.shim else _default_shim(),
        Path(args.statusline) if args.statusline else _statusline_path(),
        _this_cli(),
        apply=args.yes,
    )
    print("\n".join(lines))
    return code


def cmd_uninstall(args: argparse.Namespace) -> int:
    code, lines = ins.uninstall(
        Path(args.shim) if args.shim else _default_shim(),
        Path(args.statusline) if args.statusline else _statusline_path(),
        st.census_dir() if args.purge else None,
        apply=args.yes,
    )
    print("\n".join(lines))
    return code


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
    read.add_argument("--all", action="store_true", help="with --limits: every account in this folder")
    read.set_defaults(func=cmd_read)

    install = sub.add_parser(
        "install-statusline",
        help="(deprecated alias) add or --uninstall only the status-line block",
    )
    install.add_argument("--path", help="status-line script (default ~/.claude/statusline-command.sh)")
    install.add_argument("--uninstall", action="store_true", help="remove the block instead")
    install.set_defaults(func=cmd_install_statusline)

    inst = sub.add_parser("install", help="install the census launcher and status-line block")
    inst.add_argument("--yes", action="store_true", help="apply (default is a dry run)")
    inst.add_argument("--shim", help="launcher path (default ~/.local/bin/census)")
    inst.add_argument("--statusline", help="status-line script (default ~/.claude/statusline-command.sh)")
    inst.set_defaults(func=cmd_install)

    uninst = sub.add_parser("uninstall", help="remove the launcher and status-line block")
    uninst.add_argument("--purge", action="store_true", help="also delete this account's census data")
    uninst.add_argument("--yes", action="store_true", help="apply (default is a dry run)")
    uninst.add_argument("--shim", help="launcher path (default ~/.local/bin/census)")
    uninst.add_argument("--statusline", help="status-line script (default ~/.claude/statusline-command.sh)")
    uninst.set_defaults(func=cmd_uninstall)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if getattr(args, "all", False) and not args.limits:
            parser.error("--all is only valid with --limits")
    except SystemExit as exc:
        return 0 if not exc.code else 1
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
