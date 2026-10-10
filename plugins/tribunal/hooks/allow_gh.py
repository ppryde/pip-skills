#!/usr/bin/env python3
"""PreToolUse hook: pre-approve the exact `gh` commands tribunal:reckoning runs.

Policy (fail closed): the hook only ever prints an "allow" decision. For anything
it does not positively recognise it prints nothing and exits 0, which leaves the
decision to the normal permission prompt (and to the user's own allow/deny rules).

How a command is judged:
  1. `tokenize` parses it with a deliberately tiny shell-word subset (no operators,
     no expansions, no escapes, no globs). Anything outside the subset => decline.
     For every string it accepts, the argv it returns equals what bash and zsh
     produce (proved by the differential tests).
  2. `decide` matches the argv against a table of exact `gh` command specs. Every
     flag must be listed for that spec; unknown flags, clusters (-XPOST, -fk=v),
     `--` and flag-looking values are declined.
  3. GraphQL documents are compared token-by-token with the two canonical documents
     (the thread query in queries/threads.graphql, and the resolve mutation).

The module never executes anything and does no I/O other than stdin/stdout and one
read-only load of queries/threads.graphql from its own directory.
"""
from __future__ import annotations

import json
import os
import re
import sys

MAX_STDIN = 1024 * 1024  # 1 MiB: payloads also carry cwd, transcript_path, ...
MAX_COMMAND = 20000

ALLOW_JSON = (
    '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow",'
    '"permissionDecisionReason":"tribunal: pre-approved gh command for PR review workflow"}}'
)

# --------------------------------------------------------------------------- tokenizer

_BARE = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_@%+:,./-=")
_SPACE = frozenset(" \t")
_DQ_BANNED = frozenset('$`\\!')


def _quotable(ch: str) -> bool:
    """Printable ASCII, newline and tab only (no NUL, no control chars, no non-ASCII)."""
    return ch == "\n" or ch == "\t" or " " <= ch <= "~"


def tokenize(cmd: str) -> list[str] | None:
    """Split `cmd` into words, or return None if it leaves the safe subset."""
    if not isinstance(cmd, str) or not cmd or len(cmd) > MAX_COMMAND:
        return None
    words: list[str] = []
    cur: list[str] = []
    in_word = False
    i, n = 0, len(cmd)
    while i < n:
        ch = cmd[i]
        if ch in _SPACE:
            if in_word:
                words.append("".join(cur))
                cur, in_word = [], False
            i += 1
        elif ch in _BARE:
            if not in_word and ch == "=":
                return None  # zsh expands a word-initial `=cmd`
            cur.append(ch)
            in_word = True
            i += 1
        elif ch == "'":
            end = cmd.find("'", i + 1)
            if end < 0:
                return None
            body = cmd[i + 1 : end]
            if not all(_quotable(c) for c in body):
                return None
            cur.append(body)
            in_word = True
            i = end + 1
        elif ch == '"':
            end = cmd.find('"', i + 1)
            if end < 0:
                return None
            body = cmd[i + 1 : end]
            if not all(_quotable(c) and c not in _DQ_BANNED for c in body):
                return None
            cur.append(body)
            in_word = True
            i = end + 1
        else:
            return None
    if in_word:
        words.append("".join(cur))
    return words or None


# --------------------------------------------------------------------------- GraphQL

_GQL = re.compile(
    r"(?P<ws>[ \t\r\n,]+)"
    r"|(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<var>\$[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<int>[0-9]+)"
    r"|(?P<punct>[{}():!])"
    r'|(?P<str>"[A-Za-z0-9_=+/-]{8,128}")',
    re.ASCII,
)

STRING_SLOT = '"@"'
RESOLVE_TOKENS = [
    "mutation", "{", "resolveReviewThread", "(", "input", ":", "{", "threadId", ":",
    STRING_SLOT, "}", ")", "{", "thread", "{", "isResolved", "}", "}", "}",
]  # fmt: skip


def lex_graphql(text: str, allow_string: bool = False) -> list[str] | None:
    """Tokenise a GraphQL document; any character outside the tiny alphabet => None.

    A string literal (only when allowed) is returned as STRING_SLOT.
    """
    out: list[str] = []
    pos, n = 0, len(text)
    while pos < n:
        m = _GQL.match(text, pos)
        if m is None:
            return None
        kind = m.lastgroup
        if kind == "str":
            if not allow_string:
                return None
            out.append(STRING_SLOT)
        elif kind != "ws":
            out.append(m.group())
        pos = m.end()
    return out


_UNSET = object()
_threads_cache: object = _UNSET


def load_threads_tokens() -> list[str] | None:
    """Canonical thread-query tokens from queries/threads.graphql, or None (fail closed)."""
    global _threads_cache
    if _threads_cache is _UNSET:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "queries", "threads.graphql")
        try:
            with open(path, encoding="utf-8") as fh:
                _threads_cache = lex_graphql(fh.read(MAX_COMMAND + 1)) or None
        except (OSError, UnicodeError):
            _threads_cache = None
    return _threads_cache  # type: ignore[return-value]


# --------------------------------------------------------------------------- validators

_SEG = r"[A-Za-z0-9._-]+"
_FREE_RE = re.compile(r"[A-Za-z0-9._/@+:,=-]+", re.ASCII)
_REPO_RE = re.compile(_SEG + "/" + _SEG, re.ASCII)
_JSON_RE = re.compile(r"[A-Za-z,]+", re.ASCII)
_NUM_RE = re.compile(r"[0-9]+", re.ASCII)
_CACHE_RE = re.compile(r"[0-9]+[smh]?", re.ASCII)
_SEG_RE = re.compile(_SEG, re.ASCII)
_NODE_RE = re.compile(r"[A-Za-z0-9_=+/-]{8,128}", re.ASCII)
_ENDPOINT_RE = re.compile(
    r"repos/" + _SEG + "/" + _SEG + r"/(?:pulls|issues|commits|contents)/[A-Za-z0-9._/@+:,=-]+",
    re.ASCII,
)
_QUERY_KEYS = frozenset({"ref", "per_page", "page"})
_STATES = frozenset({"open", "closed", "merged", "all"})

# jq expressions that can read the process environment or other host state.
_JQ_DENY = re.compile(r"\$ENV\b|(?<![\w.])env\b|input_filename|\$__loc__", re.ASCII)


def _dotty(v: str) -> bool:
    return ".." in v


def v_free(v: str) -> bool:
    return bool(_FREE_RE.fullmatch(v)) and not _dotty(v)


def v_repo(v: str) -> bool:
    return bool(_REPO_RE.fullmatch(v)) and not _dotty(v)


def v_json(v: str) -> bool:
    return bool(_JSON_RE.fullmatch(v))


def v_jq(v: str) -> bool:
    return 0 < len(v) <= 4000 and _JQ_DENY.search(v) is None


def v_state(v: str) -> bool:
    return v in _STATES


def v_num(v: str) -> bool:
    return bool(_NUM_RE.fullmatch(v))


def v_cache(v: str) -> bool:
    return bool(_CACHE_RE.fullmatch(v))


def v_endpoint(v: str) -> bool:
    path, mark, query = v.partition("?")
    if not _ENDPOINT_RE.fullmatch(path):
        return False
    if any(s in ("", ".", "..") for s in path.split("/")):
        return False
    if mark:
        if not query:
            return False
        for pair in query.split("&"):
            key, eq, val = pair.partition("=")
            if key not in _QUERY_KEYS or not eq or not v_free(val):
                return False
    return True


def v_field(v: str) -> bool:
    key, eq, _val = v.partition("=")
    return bool(eq) and bool(re.fullmatch(r"[a-z]+", key))


# --------------------------------------------------------------------------- flag parser

Spec = dict  # flag spelling -> (canonical name, validator | None for a boolean flag)

_JSON = {"--json": ("json", v_json)}
_JQ = {"-q": ("jq", v_jq), "--jq": ("jq", v_jq)}
_REPO_FLAG = {"-R": ("repo", v_repo), "--repo": ("repo", v_repo)}
_REPEATABLE = frozenset({"raw", "typed"})


def parse_flags(args: list[str], spec: Spec) -> tuple[list[str], list[tuple[str, object]]] | None:
    """Return (positionals, [(canonical, value)]) or None.

    Long flags accept `--flag value` and `--flag=value`; short flags only the separate-token
    form. Boolean flags take no value. Values may not be empty or begin with `-`.
    A flag seen twice is refused unless it is repeatable.
    """
    pos: list[str] = []
    flags: list[tuple[str, object]] = []
    seen: set[str] = set()
    i = 0
    while i < len(args):
        a = args[i]
        i += 1
        if not a.startswith("-"):
            pos.append(a)
            continue
        if a.startswith("--"):
            name, eq, val = a.partition("=")
        else:
            name, eq, val = a, "", ""
        entry = spec.get(name)
        if entry is None:
            return None
        canon, check = entry
        if canon in seen and canon not in _REPEATABLE:
            return None
        seen.add(canon)
        if check is None:
            if eq:
                return None
            flags.append((canon, True))
            continue
        if not eq:
            if i >= len(args):
                return None
            val = args[i]
            i += 1
        if val == "" or val.startswith("-") or not check(val):
            return None
        flags.append((canon, val))
    return pos, flags


# --------------------------------------------------------------------------- decide


def _graphql(rest: list[str], threads: list[str] | None) -> bool:
    spec: Spec = {
        "--paginate": ("paginate", None),
        "-f": ("raw", v_field),
        "--raw-field": ("raw", v_field),
        "-F": ("typed", v_field),
        "--field": ("typed", v_field),
    }
    parsed = parse_flags(rest, spec)
    if parsed is None:
        return False
    pos, flags = parsed
    if pos:
        return False
    paginate = False
    raw: dict[str, str] = {}
    typed: dict[str, str] = {}
    for canon, val in flags:
        if canon == "paginate":
            paginate = True
            continue
        key, _eq, value = str(val).partition("=")
        target = raw if canon == "raw" else typed
        if key in target:
            return False
        target[key] = value

    if set(raw) == {"query"} and not typed:  # resolve one thread
        if paginate:
            return False
        toks = lex_graphql(raw["query"], allow_string=True)
        return toks == RESOLVE_TOKENS

    if set(raw) == {"owner", "repo", "query"} and set(typed) == {"number"}:  # read threads
        if not (_SEG_RE.fullmatch(raw["owner"]) and _SEG_RE.fullmatch(raw["repo"])):
            return False
        if raw["owner"] in (".", "..") or raw["repo"] in (".", "..") or not _NUM_RE.fullmatch(typed["number"]):
            return False
        if threads is None:
            return False
        return lex_graphql(raw["query"]) == threads
    return False


def decide(argv: list[str], threads_tokens: object = _UNSET) -> bool:
    """True only for an exact, read-only gh command shape from the allowlist."""
    if len(argv) < 2 or argv[0] != "gh":
        return False
    a = argv[1:]

    if a[0] == "auth":
        return a == ["auth", "status"]

    if a[0] == "repo" and a[1:2] == ["view"]:
        parsed = parse_flags(a[2:], {**_JSON, **_JQ})
        return parsed is not None and len(parsed[0]) <= 1 and all(v_repo(p) for p in parsed[0])

    if a[0] == "pr" and len(a) >= 2:
        if a[1] == "view":
            parsed = parse_flags(a[2:], {**_REPO_FLAG, **_JSON, **_JQ})
            return parsed is not None and len(parsed[0]) <= 1 and all(v_free(p) for p in parsed[0])
        if a[1] == "list":
            spec: Spec = {
                **_REPO_FLAG, **_JSON, **_JQ,
                "--head": ("head", v_free),
                "--state": ("state", v_state),
                "--limit": ("limit", v_num),
            }  # fmt: skip
            parsed = parse_flags(a[2:], spec)
            return parsed is not None and not parsed[0]
        if a[1] == "checkout":
            return len(a) == 3 and v_num(a[2])
        return False

    if a[0] == "api" and len(a) >= 2:
        if a[1] == "graphql":
            threads = load_threads_tokens() if threads_tokens is _UNSET else threads_tokens
            return _graphql(a[2:], threads)  # type: ignore[arg-type]
        spec = {**_JQ, "--paginate": ("paginate", None), "--cache": ("cache", v_cache)}
        parsed = parse_flags(a[2:], spec)  # endpoint is a[1]; flags may precede nothing else
        if a[1].startswith("-"):
            return False
        return parsed is not None and not parsed[0] and v_endpoint(a[1])

    return False


# --------------------------------------------------------------------------- hook entry


def evaluate(payload: object) -> bool:
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return False
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return False
    command = tool_input.get("command")
    if not isinstance(command, str) or len(command) > MAX_COMMAND:
        return False
    if tool_input.get("dangerouslyDisableSandbox"):
        return False
    argv = tokenize(command)
    return argv is not None and decide(argv)


def main() -> None:
    try:
        raw = sys.stdin.buffer.read(MAX_STDIN + 1)
        if len(raw) > MAX_STDIN:
            return
        allowed = evaluate(json.loads(raw.decode("utf-8")))
    except BaseException:  # noqa: BLE001 - any failure must fail closed (silent decline)
        return
    if allowed:
        sys.stdout.write(ALLOW_JSON + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
