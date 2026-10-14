"""``bootstrap`` and ``dispatch-prep`` under ``--remote`` (WF-300).

Both verbs run git in a worktree, and the host refuses to (a tree the container can
write may hold hooks and filters). So the CLIENT does the git and writes every file an
agent reads, in the container, and the host only reads and writes the board through
the git-free verbs ``bootstrap-begin`` / ``bootstrap-finish`` / ``dispatch-record``.

Each forwarded argv is built from the PARSED arguments, never replayed from the raw
one: a replayed ``--brief-file`` would be a host path and a 403.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

from scripts import bundle, config, gitops
from scripts.store import derive_repo_root

RECORD_VERSION = 1
Call = Callable[[list[str], "str | None"], "RemoteResultLike"]


class RemoteResultLike:  # structural stand-in for scripts.remote.RemoteResult
    stdout: str
    stderr: str
    returncode: int


class _Stop(Exception):
    """Abort the flow with this exit code (the message is already printed)."""

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


def _fail(message: str, code: int = 1) -> _Stop:
    print(message, file=sys.stderr)
    return _Stop(code)


def _skew(verb: str) -> str:
    return (f"error: the overseer host does not speak this container's {verb} protocol; "
            f"update overseer on the host/in this container ({verb} v{RECORD_VERSION} expected)")


def _is_skew(text: str) -> bool:
    return "invalid choice" in text or "not permitted" in text


def _call(call: Call, argv: list[str], stdin: str | None, verb: str) -> RemoteResultLike:
    """One host call. Transport errors surface as RemoteError to the caller; an older
    host (no such verb) becomes the skew message."""
    from scripts.remote import RemoteError
    try:
        res = call(argv, stdin)
    except RemoteError as exc:
        if _is_skew(str(exc)):
            raise _fail(_skew(verb)) from exc
        raise
    if res.returncode != 0 and _is_skew(res.stderr):
        raise _fail(_skew(verb))
    return res


def _relay(res: RemoteResultLike) -> None:
    if res.stderr:
        sys.stderr.write(res.stderr)


def _record(res: RemoteResultLike, verb: str) -> dict:
    try:
        data = json.loads(res.stdout)
    except ValueError:
        data = None
    if not isinstance(data, dict) or data.get("v") != RECORD_VERSION:
        raise _fail(_skew(verb))
    return data


def _read_brief(args: argparse.Namespace) -> str | None:
    if getattr(args, "brief_file", None) and args.brief is not None:
        raise _fail("error: pass --brief or --brief-file, not both")
    if getattr(args, "brief_file", None):
        try:
            return Path(args.brief_file).read_text().rstrip("\n")
        except OSError as exc:
            raise _fail(f"error: cannot read {exc.filename or 'the file'}: {exc.strerror or exc}") from exc
    if args.brief == "-":
        return sys.stdin.read().rstrip("\n")
    return args.brief


# --- bootstrap ------------------------------------------------------------------------

def _worktrees(main_root: Path) -> dict[Path, str | None]:
    """path -> branch (None when detached) for every worktree of the repo."""
    res = gitops._git(main_root, "worktree", "list", "--porcelain")
    out: dict[Path, str | None] = {}
    current: Path | None = None
    for line in res.stdout.splitlines():
        if line.startswith("worktree "):
            current = Path(line[len("worktree "):]).resolve()
            out[current] = None
        elif line.startswith("branch ") and current is not None:
            out[current] = line[len("branch "):].removeprefix("refs/heads/")
    return out


def _add_or_adopt(main_root: Path, path: Path, branch: str, base: str, card_id: str) -> None:
    existing = _worktrees(main_root)
    here = existing.get(path.resolve(), ...)
    if here is not ...:
        if here == branch:
            print(f"{card_id}: adopting existing worktree {path}", file=sys.stderr)
            return
        raise _fail(f"error: {card_id} left at bootstrap - {path} is already a worktree on "
                    f"{here or 'a detached HEAD'}, not {branch}")
    elsewhere = next((p for p, b in existing.items() if b == branch), None)
    if elsewhere is not None:
        raise _fail(f"error: {card_id} left at bootstrap - {branch} is already checked out at "
                    f"{elsewhere}, not {path}")
    try:
        gitops.worktree_add(main_root, path, branch, base)
    except gitops.GitError as exc:
        raise _fail(f"error: {card_id} left at bootstrap - {exc}") from exc


def _begin_argv(args: argparse.Namespace, brief: str | None) -> list[str]:
    argv = ["bootstrap-begin", "--type", args.type]
    for flag, value in (("--card", args.card), ("--title", args.title), ("--jira", args.jira),
                        ("--linear", args.linear), ("--complexity", args.complexity),
                        ("--labels", args.labels), ("--goal", args.goal), ("--slug", args.slug),
                        ("--force-gate", args.force_gate)):
        if value is not None:
            argv += [flag, value]
    if brief:
        argv += ["--brief", "-"]
    return argv


def bootstrap(call: Call, args: argparse.Namespace, root: Path) -> int:
    try:
        return _bootstrap(call, args, root)
    except _Stop as stop:
        return stop.code


def _bootstrap(call: Call, args: argparse.Namespace, root: Path) -> int:
    main_root = derive_repo_root(root)
    if main_root is None:
        raise _fail("error: bootstrap under --remote needs a git checkout in this container; "
                    "run from inside the repo (or pass --root)")
    brief = _read_brief(args)
    res = _call(call, _begin_argv(args, brief), brief if brief else None, "bootstrap-begin")
    _relay(res)
    if res.returncode != 0:
        return res.returncode
    begun = _record(res, "bootstrap-begin")
    card_id, branch = begun["id"], begun["branch"]
    path = gitops_path(main_root, card_id, root)
    if not path.resolve().is_relative_to(main_root.resolve()):
        print(f"warning: worktree {path} is outside the mounted repo and will not survive this "
              "container; set worktree_dir in .overseer/config.json", file=sys.stderr)
    base = gitops.base_ref(main_root)
    _add_or_adopt(main_root, path, branch, base, card_id)
    finish = ["bootstrap-finish", card_id, "--branch", branch, "--worktree", str(path),
              "--base", base]
    if brief:
        finish += ["--brief", "-"]
    if args.force_gate is not None:
        finish += ["--force-gate", args.force_gate]
    from scripts.remote import RemoteError
    retry = (f"card {card_id} is at bootstrap on the host; rerun bootstrap --card {card_id} "
             "(the existing worktree is adopted)")
    try:
        res = _call(call, finish, brief if brief else None, "bootstrap-finish")
    except RemoteError as exc:
        raise _fail(f"error: {exc}\n{retry}") from exc
    if res.stdout:
        sys.stdout.write(res.stdout)
    _relay(res)
    if res.returncode != 0:
        print(retry, file=sys.stderr)
    return res.returncode


def gitops_path(main_root: Path, card_id: str, root: Path) -> Path:
    from scripts.cli import worktree_path
    return worktree_path(main_root, card_id, config.load_config(root))


# --- dispatch-prep --------------------------------------------------------------------

def _record_argv(args: argparse.Namespace) -> list[str]:
    argv = ["dispatch-record", args.card_id, "--stage", args.stage, "--role", args.role,
            "--round", str(args.round)]
    for flag, value in (("--slot", args.slot), ("--chunk", args.chunk), ("--lens", args.lens),
                        ("--force-gate", args.force_gate)):
        if value is not None:
            argv += [flag, str(value)]
    if args.advance:
        argv.append("--advance")
    if args.panel:
        argv.append("--panel")
    return argv


def dispatch_prep(call: Call, args: argparse.Namespace, root: Path) -> int:
    try:
        return _dispatch_prep(call, args, root)
    except _Stop as stop:
        return stop.code


def _dispatch_prep(call: Call, args: argparse.Namespace, root: Path) -> int:
    from scripts import cli
    from scripts.dispatch import dispatch_dir
    from scripts.nextstep import AGENT_PREFIX
    try:
        variables = bundle.parse_vars(args.var or [])
    except bundle.BundleError as exc:
        raise _fail(f"error: {exc}") from exc
    chunk = cli._dispatch_validate(args)
    if chunk == cli._DISPATCH_REFUSED:
        raise _Stop(1)
    needs_diff = args.role == "reviewer" and args.stage != "plan-review"
    worktree = root
    if needs_diff:
        # Before any dispatched row exists: a worktree this container lacks must not leave one.
        res = _call(call, ["show", args.card_id, "--json"], None, "dispatch-record")
        if res.returncode != 0:
            _relay(res)
            return res.returncode
        recorded = json.loads(res.stdout).get("worktree")
        worktree = Path(recorded) if recorded else root
        if not worktree.is_dir():
            raise _fail(f"error: worktree {worktree} recorded for {args.card_id} is not present in "
                        "this container; run dispatch-prep from the container that bootstrapped it")
    res = _call(call, _record_argv(args), None, "dispatch-record")
    _relay(res)
    if res.returncode != 0:
        return res.returncode
    record = _record(res, "dispatch-record")
    diff_text = None
    if needs_diff:
        try:
            review = gitops.review_diff(worktree)
        except gitops.GitError as exc:
            raise _fail(f"error: could not write the diff: {exc}") from exc
        diff_text = review.text
        for warning in review.warnings:
            print(f"dispatch-prep: {warning}", file=sys.stderr)
    directory = dispatch_dir(root, record["card"]["id"], args.stage)
    cli_cmd = f"{sys.executable} {bundle.CLI_PATH} --root {root}"
    lines: list[str] = []
    try:
        for slot in record["slots"]:
            spec = bundle.spec_from_record(
                record, stage=args.stage, role=args.role, round_no=args.round,
                slot=slot["slot"] or None, lens=slot["lens"])
            path = bundle.render(spec, diff_text, directory, cli_cmd, root, dict(variables))
            lines.append(f"{AGENT_PREFIX}{args.role} {slot['model']} {path}" if args.panel
                         else str(path))
    except bundle.BundleError as exc:
        raise _fail(f"error: {exc}") from exc
    print("\n".join(lines))
    return 0
