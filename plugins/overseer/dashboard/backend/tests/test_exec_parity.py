"""WF-100 C5: the long-term control on `POST /api/exec`.

Every option and positional of the CLI parser is classified here by its dest. An
unclassified `(verb, dest)` fails the suite, so a new host-path option cannot
reach the exec route without someone deciding what to do with it. Verbs are
split the same way: every top-level verb is either allowed or denied.
"""
from __future__ import annotations

import argparse
from collections.abc import Iterator

import pytest
from fastapi import HTTPException
from scripts.cli import build_parser

from app import board_service

# dests that carry a host path (or an outbound URL)
PATH_DESTS = {
    "root", "remote", "central", "backup_dir", "dir", "from_bak",
    "file", "text_file", "brief_file", "path",
}
# stored as a string and read later only as `Path.is_dir()` / `rev-parse --verify`
WATCH_DESTS = {("set-field", "worktree"), ("set-field", "branch")}
# everything else: the literal result of enumerating the parser, committed here
SAFE_DESTS = {
    "action", "advance", "body", "brief", "card", "card_id", "chunk", "color_key", "complexity",
    "count", "dry_run", "estimate", "fact_id", "force", "force_gate", "full", "goal", "id",
    "ids", "jira", "json", "labels", "lens", "linear", "name", "no_backup", "note", "notes",
    "off", "on", "order", "panel", "parent", "pending", "pr", "print_dir", "priority", "reason",
    "repo", "reviewers", "role", "round", "scope", "section", "session", "session_id", "slot",
    "slug", "source", "sprint", "sprint_id", "stage", "stale", "statement", "status", "subject",
    "superseded_by", "tag", "tags", "task", "text", "tier", "title", "tokens", "touches", "type",
    "var", "verb", "verdict", "vigil_verb", "yes",
}


def _walk(parser: argparse.ArgumentParser, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], argparse.Action]]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                yield from _walk(sub, path + (name,))
        elif not isinstance(action, argparse._HelpAction):
            yield path, action


def _parsers(parser: argparse.ArgumentParser) -> Iterator[argparse.ArgumentParser]:
    yield parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for sub in action.choices.values():
                yield from _parsers(sub)


def _top_level_verbs() -> set[str]:
    (sub,) = [a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction)]
    return set(sub.choices)


def test_every_verb_and_dest_is_classified() -> None:
    unclassified = []
    for path, action in _walk(build_parser()):
        verb = "/".join(path) or "<global>"
        key = (path[0] if path else "<global>", action.dest)
        if action.dest in PATH_DESTS or key in WATCH_DESTS or action.dest in SAFE_DESTS:
            continue
        unclassified.append((verb, action.dest))
    assert unclassified == [], f"classify these in PATH_DESTS / WATCH_DESTS / SAFE_DESTS: {unclassified}"


def test_classification_sets_are_disjoint_and_have_no_stale_entries() -> None:
    assert not PATH_DESTS & SAFE_DESTS
    assert not {d for _, d in WATCH_DESTS} & PATH_DESTS
    dests = {a.dest for _, a in _walk(build_parser())}
    assert PATH_DESTS <= dests, PATH_DESTS - dests
    assert SAFE_DESTS <= dests, SAFE_DESTS - dests
    pairs = {((p[0] if p else "<global>"), a.dest) for p, a in _walk(build_parser())}
    assert WATCH_DESTS <= pairs


def test_no_parser_abbreviates_options() -> None:
    offenders = [p.prog for p in _parsers(build_parser()) if p.allow_abbrev]
    assert offenders == []


def test_no_verb_has_an_alias() -> None:
    # An alias would be a second name for a verb that the denylist does not know.
    (sub,) = [a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction)]
    assert len({id(p) for p in sub.choices.values()}) == len(sub.choices)


# --- prefixes of path options never bind -----------------------------------------------

# verb, minimal argv that parses, path options of that verb
_PATH_CASES = [
    ("init", ["init"], ["--central", "--backup-dir"]),
    ("backup", ["backup"], ["--dir"]),
    ("restore", ["restore"], ["--dir", "--from-bak"]),
    ("bootstrap", ["bootstrap"], ["--brief-file"]),
    ("set-section", ["set-section", "WF-1", "--section", "Plan"], ["--file", "--text-file"]),
    ("append-body", ["append-body", "WF-1", "Decisions"], ["--text-file"]),
]


def _parses(argv: list[str]) -> bool:
    try:
        build_parser().parse_args(argv)
    except SystemExit:
        return False
    return True


@pytest.mark.parametrize(("verb", "base", "options"), _PATH_CASES, ids=[c[0] for c in _PATH_CASES])
def test_path_option_prefixes_fail_to_parse(verb: str, base: list[str], options: list[str]) -> None:
    (sub,) = [a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction)]
    valid = {o for a in sub.choices[verb]._actions for o in a.option_strings}
    for option in options:
        assert _parses(base + [option, "x"]), f"control: {verb} {option} must parse"
        assert _parses(base + [f"{option}=x"]), f"control: {verb} {option}=x must parse"
        for n in range(3, len(option)):
            prefix = option[:n]
            if prefix in valid:  # `--text` is a real option of its own
                continue
            assert not _parses(base + [prefix, "x"]), f"{verb} {prefix}"
            assert not _parses(base + [f"{prefix}=x"]), f"{verb} {prefix}="


def test_every_path_option_string_is_covered_by_the_prefix_cases() -> None:
    covered = {(v, o) for v, _, opts in _PATH_CASES for o in opts}
    found = {
        (path[0], opt)
        for path, action in _walk(build_parser())
        if path and action.dest in PATH_DESTS and action.option_strings
        for opt in action.option_strings
    }
    assert found <= covered, found - covered


# --- the route either rejects, strips or denies every path option --------------------------

def test_no_path_option_reaches_the_child_of_an_allowed_verb() -> None:
    for path, action in _walk(build_parser()):
        if action.dest not in PATH_DESTS or not path:
            continue
        verb = path[0]
        for opt in action.option_strings:
            for argv in ([verb, opt, "/x"], [verb, f"{opt}=/x"]):
                try:
                    out = board_service.sanitise_argv(argv)
                except HTTPException:
                    continue  # rejected or denied
                assert not [t for t in out if t == opt or t.startswith(f"{opt}=")], (verb, opt, out)


def test_positional_path_of_claude_dirs_is_denied_with_its_verb() -> None:
    assert "claude-dirs" in board_service._DENIED_VERBS


# --- verb classification ------------------------------------------------------------------

def test_denied_verbs_are_real_verbs() -> None:
    assert board_service._DENIED_VERBS <= _top_level_verbs(), (
        board_service._DENIED_VERBS - _top_level_verbs()
    )


def test_every_hook_verb_but_pretool_is_denied() -> None:
    hooks = {v for v in _top_level_verbs() if v.endswith("-hook")}
    assert hooks - {"pretool-hook"} <= board_service._DENIED_VERBS
    assert "pretool-hook" not in board_service._DENIED_VERBS
    assert "pretool-hook" in hooks


def test_allowed_and_denied_partition_the_verbs() -> None:
    verbs = _top_level_verbs()
    denied = board_service._DENIED_VERBS
    allowed = verbs - denied
    assert allowed | denied == verbs
    assert not allowed & denied
    assert {"board", "show", "set-section", "append-body", "pretool-hook", "repos"} <= allowed


# --- git classification (C6): every verb is git-free, a hardened lookup, or git-running ----------
# GIT_RUNNING verbs run `git` against the repo (a checkout, a diff, a status): denied over exec.
# GIT_LOOKUP verbs add a filter-free `rev-parse --verify`; every verb also does the filter-free
# `rev-parse --git-common-dir` identity lookup. Both lookups run with scripts.gitenv.
GIT_RUNNING = {"bootstrap", "dispatch-prep"}
GIT_LOOKUP = {"resume", "handoff", "handover", "repos"}
GIT_FREE = {
    "new-card", "set-stage", "block", "unblock", "done", "abandon", "set-field", "append-body",
    "reorder", "depends", "checklist", "park", "unpark", "pull-children", "claim", "unclaim",
    "release", "claim-nudged", "log-progress", "log-review", "next", "new-sprint", "rollup-sprint",
    "set-sprint-status", "rebuild-index", "conflicts", "vigil", "board", "show", "help", "boards",
    "log-usage", "usage", "calibration", "add-fact", "verify-fact", "retire-fact", "facts",
    "set-section", "accept-fact", "reject-fact", "label-color",
    "pretool-hook",
    # denied for other reasons, but they run no git of their own
    "init", "backup", "restore", "clear", "claude-dirs", "merge-boards",
    "checklist-sync-hook", "claim-stop-hook", "claim-prompt-hook", "report-hook",
    "dashboard-refresh-hook",
}


def test_every_verb_is_classified_for_git_exactly_once() -> None:
    verbs = _top_level_verbs()
    assert GIT_RUNNING | GIT_LOOKUP | GIT_FREE == verbs, (
        verbs - (GIT_RUNNING | GIT_LOOKUP | GIT_FREE), (GIT_RUNNING | GIT_LOOKUP | GIT_FREE) - verbs,
    )
    assert not GIT_RUNNING & GIT_LOOKUP and not GIT_RUNNING & GIT_FREE and not GIT_LOOKUP & GIT_FREE


def test_every_git_running_verb_is_denied() -> None:
    assert GIT_RUNNING <= board_service._DENIED_VERBS
    assert not GIT_LOOKUP & board_service._DENIED_VERBS
