"""Census CLI — record and read status-line session state. Pure stdlib."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):  # direct invocation: put plugin root on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import install as ins
from scripts import render as rd
from scripts import statusline as sl
from scripts import store as st


def cmd_ingest(args: argparse.Namespace) -> int:
    st.ingest(_read_stdin())
    try:  # the pointer is best-effort; ingest's exit code must stay 0
        st.publish_location(Path(__file__))
    except Exception:  # noqa: BLE001, S110 - best-effort pointer, never raises
        pass
    return 0


def _read_stdin() -> str:
    """Stdin as UTF-8 text on every platform (Windows defaults to a code page)."""
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is not None:
        return buffer.read().decode("utf-8", "replace")
    return sys.stdin.read()


def _emit(text: str) -> None:
    """Write the line as UTF-8 whatever the console encoding says."""
    data = (text + "\n").encode("utf-8")
    try:
        buffer = getattr(sys.stdout, "buffer", None)
        if buffer is not None:
            buffer.write(data)
            buffer.flush()
        else:
            sys.stdout.write(data.decode("utf-8"))
            sys.stdout.flush()
    except OSError:  # a closed pipe (BrokenPipeError) or a dead console: nobody is reading
        try:  # keep the interpreter's exit-time flush from complaining
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except (OSError, ValueError, AttributeError):
            pass


def cmd_statusline(args: argparse.Namespace) -> int:
    """`_statusline` that can never raise: no traceback ever comes from this command."""
    try:
        return _statusline(args)
    except Exception:  # noqa: BLE001
        try:
            _emit(rd.fallback(None))
        except Exception:  # noqa: BLE001, S110
            pass
        return 0


def _statusline(args: argparse.Namespace) -> int:
    """Ingest the payload on stdin exactly as ``ingest`` does, then draw the line.

    Ingest first, draw second; a failure in either never stops the other and
    nothing here raises."""
    if args.preview:
        try:
            _emit(rd.statusline(rd.preview_payload()))
        except Exception:  # noqa: BLE001 - never a traceback
            _emit(rd.fallback(None))
        return 0
    raw = ""
    try:
        raw = _read_stdin()
    except Exception:  # noqa: BLE001, S110 - an unreadable stdin still gets a line
        pass
    try:
        st.ingest(raw)
        st.publish_location(Path(__file__))
    except Exception:  # noqa: BLE001, S110 - ingest quarantines itself; belt and braces
        pass
    payload: object = None
    try:
        payload = json.loads(raw)
    except ValueError:
        pass
    side_channel = os.environ.get("AGENT_UI_STATUSLINE_CACHE")
    if side_channel:
        try:
            rd.write_side_channel(raw, payload, side_channel)
        except Exception:  # noqa: BLE001, S110 - best-effort
            pass
    try:
        line = rd.statusline(payload) if isinstance(payload, dict) else rd.fallback(None)
    except Exception:  # noqa: BLE001 - never a traceback
        line = rd.fallback(payload if isinstance(payload, dict) else None)
    _emit(line)
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


def cmd_where(args: argparse.Namespace) -> int:
    """Read-only: where census and census-mod are, as one JSON object (no shell variables needed)."""
    from scripts import where as wh

    print(json.dumps(wh.report(), indent=2))
    return 0


def _statusline_path() -> Path:
    return st.config_dir() / "statusline-command.sh"


def cmd_install_statusline(args: argparse.Namespace) -> int:
    path = Path(args.path) if args.path else _statusline_path()
    if not path.exists():
        print(f"no status-line script at {path}", file=sys.stderr)
        return 1
    text = ins._read_text(path)  # byte-preserving: CRLF and undecodable bytes survive
    updated = sl.remove_block(text) if args.uninstall else sl.add_block(text)
    if updated == text:
        print("no change")
        return 0
    ins._write_text(path, updated)
    print(f"{'removed' if args.uninstall else 'installed'} census block in {path}")
    return 0


def _default_shim() -> Path:
    return Path.home() / ".local" / "bin" / "census"


def _this_cli() -> Path:
    return Path(__file__).resolve()


def _settings_path(args: argparse.Namespace) -> Path:
    return Path(args.settings) if args.settings else st.config_dir() / "settings.json"


def _with_account(args: argparse.Namespace, lines: list[str]) -> list[str]:
    """A dry run names the account it would touch on its first line (always, so it is never a guess)."""
    return lines if args.yes else [f"config dir: {st.config_dir()}", *lines]


def cmd_install(args: argparse.Namespace) -> int:
    shim = Path(args.shim) if args.shim else _default_shim()
    if args.statusline:
        code, lines = ins.install_statusline(
            shim,
            _this_cli(),
            _settings_path(args),
            st.census_dir(),
            replace=args.replace,
            segments=args.segments,
            apply=args.yes,
        )
    else:
        code, lines = ins.install(
            shim,
            Path(args.script) if args.script else _statusline_path(),
            _this_cli(),
            apply=args.yes,
        )
    print("\n".join(_with_account(args, lines)))
    return code


def cmd_uninstall(args: argparse.Namespace) -> int:
    code, lines = ins.uninstall(
        Path(args.shim) if args.shim else _default_shim(),
        Path(args.script) if args.script else _statusline_path(),
        st.census_dir() if args.purge else None,
        apply=args.yes,
        settings=_settings_path(args),
        census=st.census_dir(),
    )
    print("\n".join(_with_account(args, lines)))
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="census", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ingest", help="read a status-line payload on stdin and record it").set_defaults(
        func=cmd_ingest
    )

    line = sub.add_parser("statusline", help="ingest the payload on stdin, then draw the status line")
    line.add_argument(
        "--preview", action="store_true", help="draw a canned payload and the live census store; no stdin, no ingest"
    )
    line.set_defaults(func=cmd_statusline)

    where = sub.add_parser(
        "where", help="read-only: the config dir, census dir, plugin installs and whether census-mod is enabled, as JSON"
    )
    where.add_argument("--config-dir", help="use this Claude config dir instead of $CLAUDE_CONFIG_DIR, for this run")
    where.set_defaults(func=cmd_where)

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
    install.add_argument("--path", help="status-line script (default $CLAUDE_CONFIG_DIR/statusline-command.sh, else ~/.claude/)")
    install.add_argument("--uninstall", action="store_true", help="remove the block instead")
    install.set_defaults(func=cmd_install_statusline)

    inst = sub.add_parser("install", help="install the census launcher and status-line block")
    inst.add_argument("--yes", action="store_true", help="apply (default is a dry run)")
    inst.add_argument("--shim", help="launcher path (default ~/.local/bin/census)")
    inst.add_argument("--script", help="status-line script (default $CLAUDE_CONFIG_DIR/statusline-command.sh, else ~/.claude/)")
    inst.add_argument(
        "--statusline",
        action="store_true",
        help="set settings.json statusLine to `census statusline` instead of editing a script",
    )
    inst.add_argument("--replace", action="store_true", help="with --statusline: back up and replace an existing statusLine")
    inst.add_argument("--segments", help="with --statusline: segment list for env.CENSUS_STATUSLINE_SEGMENTS")
    inst.add_argument("--settings", help="settings file (default $CLAUDE_CONFIG_DIR/settings.json)")
    inst.add_argument("--config-dir", help="use this Claude config dir instead of $CLAUDE_CONFIG_DIR, for this run")
    inst.set_defaults(func=cmd_install)

    uninst = sub.add_parser("uninstall", help="remove the launcher and status-line block")
    uninst.add_argument("--purge", action="store_true", help="also delete this account's census data")
    uninst.add_argument("--yes", action="store_true", help="apply (default is a dry run)")
    uninst.add_argument("--shim", help="launcher path (default ~/.local/bin/census)")
    uninst.add_argument("--script", help="status-line script (default $CLAUDE_CONFIG_DIR/statusline-command.sh, else ~/.claude/)")
    uninst.add_argument("--settings", help="settings file (default $CLAUDE_CONFIG_DIR/settings.json)")
    uninst.add_argument("--config-dir", help="use this Claude config dir instead of $CLAUDE_CONFIG_DIR, for this run")
    uninst.set_defaults(func=cmd_uninstall)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if getattr(args, "all", False) and not args.limits:
            parser.error("--all is only valid with --limits")
        if args.command == "install" and not args.statusline and (
            args.replace or args.segments is not None or args.settings
        ):
            parser.error("--replace, --segments and --settings are only valid with --statusline")
    except SystemExit as exc:
        return 0 if not exc.code else 1
    override = getattr(args, "config_dir", None)
    if not override:
        result: int = args.func(args)
        return result
    # --config-dir: the account for THIS run only; the environment is put back afterwards.
    previous = os.environ.get(st.CONFIG_DIR_ENV)
    os.environ[st.CONFIG_DIR_ENV] = override
    try:
        result = args.func(args)
    finally:
        if previous is None:
            os.environ.pop(st.CONFIG_DIR_ENV, None)
        else:
            os.environ[st.CONFIG_DIR_ENV] = previous
    return result


if __name__ == "__main__":
    raise SystemExit(main())
