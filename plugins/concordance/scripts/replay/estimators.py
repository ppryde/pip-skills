"""Which tool calls concordance could have answered, what that would have cost, and whether
the answer would have been enough. Each estimator: match(call) -> Query | None and a rule."""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass

from scripts.render import est_tokens
from scripts.replay import runner
from scripts.replay.transcript import ToolCall

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# the CLI's query commands: an agent's own concordance call is `<...>/concordance/scripts/cli.py
# <command>` or `concordance <command>`, never merely a command that mentions the files
_QUERIES = ("index", "review-context", "removed", "sig-drift", "literals", "touched", "check",
            "callers", "tests", "coverage")
_INVOCATION = re.compile(
    rf"(?:(?:^|[\s;&|(])concordance|concordance/scripts/cli\.py)\s+(?:{'|'.join(_QUERIES)})\b")


@dataclass(frozen=True)
class Query:
    estimator: str
    kind: str
    args: list[str]


@dataclass(frozen=True)
class Estimate:
    covered: bool
    concordance_tokens: int
    latency_ms: int
    exit_code: int
    answerable: str


NOT_COVERED = Estimate(False, 0, 0, 0, "unknown")


def _repo_root(cwd: str) -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd,
                             capture_output=True, text=True, timeout=10, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return os.path.realpath(out.strip()) if out.strip() else None


def _whole_repo(call: ToolCall) -> bool:
    """A callers query answers a plain whole-repo search, not a filtered or scoped one."""
    inp = call.input
    if any(inp.get(k) for k in ("glob", "type", "multiline", "-i")):
        return False
    path = inp.get("path")
    if path is None:
        return True
    if not isinstance(path, str):
        return False
    here = os.path.realpath(os.path.join(call.cwd, path))
    if here == os.path.realpath(call.cwd):
        return True
    return here == _repo_root(call.cwd)


def match(call: ToolCall) -> Query | None:
    if call.name == "Grep":
        pattern = call.input.get("pattern")
        if isinstance(pattern, str) and _IDENT.match(pattern) and _whole_repo(call):
            return Query("callers", "grep", ["callers", pattern])
    if call.name == "Bash":
        command = call.input.get("command")
        if isinstance(command, str) and _INVOCATION.search(command):
            return Query("passthrough", "concordance", [])
    return None


def _rel(path: str, root: str) -> str:
    try:
        return os.path.relpath(os.path.realpath(path), os.path.realpath(root))
    except ValueError:
        return path


def _grep_files(text: str, base: str, root: str) -> set[str]:
    files: set[str] = set()
    for line in text.splitlines():
        candidate = line.split(":", 1)[0].strip()
        if not candidate:
            continue
        full = candidate if os.path.isabs(candidate) else os.path.join(base, candidate)
        if os.path.isfile(full):
            files.add(_rel(full, root))
    return files


def _callers_answerable(doc: dict[str, object], call: ToolCall, later: list[ToolCall]) -> str:
    root = str(doc.get("root", ""))
    hits = doc.get("hits")
    known = {str(h["path"]) for h in hits if isinstance(h, dict) and "path" in h} \
        if isinstance(hits, list) else set()
    if isinstance(doc.get("definition"), str):
        known.add(str(doc["definition"]))
    read_after = {_rel(os.path.join(c.cwd, str(c.input["file_path"])), root) for c in later
                  if c.name == "Read" and isinstance(c.input.get("file_path"), str)}
    base = os.path.join(call.cwd, str(call.input.get("path") or "."))
    opened = _grep_files(call.result_text, base, root) & read_after
    if not opened:
        return "unknown"
    return "yes" if opened <= known else "no"


def estimate(query: Query, call: ToolCall, later: list[ToolCall]) -> Estimate:
    if query.estimator == "passthrough":
        return Estimate(True, est_tokens(call.result_text), 0, 0, "unknown")
    ans = runner.run(query.args, call.cwd)
    if not ans.ok or ans.exit_code == 2 or ans.doc.get("found") is False:
        return Estimate(False, 0, ans.latency_ms, ans.exit_code, "unknown")
    tokens = ans.doc.get("est_tokens")
    if not isinstance(tokens, int) or isinstance(tokens, bool):
        return Estimate(False, 0, ans.latency_ms, ans.exit_code, "unknown")
    return Estimate(True, tokens, ans.latency_ms, ans.exit_code,
                    _callers_answerable(ans.doc, call, later))
