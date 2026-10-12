"""Which tool calls concordance could have answered, what that would have cost, and whether
the answer would have been enough. Each estimator: match(call) -> Query | None and a rule."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from scripts.render import est_tokens
from scripts.replay import runner
from scripts.replay.transcript import ToolCall

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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


def match(call: ToolCall) -> Query | None:
    if call.name == "Grep":
        pattern = call.input.get("pattern")
        if isinstance(pattern, str) and _IDENT.match(pattern):
            return Query("callers", "grep", ["callers", pattern])
    if call.name == "Bash":
        command = call.input.get("command")
        if isinstance(command, str) and "concordance" in command and "cli.py" in command:
            return Query("passthrough", "concordance", [])
    return None


def _rel(path: str, root: str) -> str:
    try:
        return os.path.relpath(os.path.realpath(path), os.path.realpath(root))
    except ValueError:
        return path


def _grep_files(text: str, root: str) -> set[str]:
    files: set[str] = set()
    for line in text.splitlines():
        candidate = line.split(":", 1)[0].strip()
        if not candidate:
            continue
        full = candidate if os.path.isabs(candidate) else os.path.join(root, candidate)
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
    read_after = {_rel(str(c.input["file_path"]), root) for c in later
                  if c.name == "Read" and isinstance(c.input.get("file_path"), str)}
    opened = _grep_files(call.result_text, root) & read_after
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
    return Estimate(True, int(tokens) if isinstance(tokens, int) else 0, ans.latency_ms,
                    ans.exit_code, _callers_answerable(ans.doc, call, later))
