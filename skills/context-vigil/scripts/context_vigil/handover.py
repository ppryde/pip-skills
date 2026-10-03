"""Handover notes: validate the agent's structured notes, assemble the document.

The notes follow templates/handover.md (structure adapted from Andrew OE's
handover-work skill). Two sections are mandatory because they are what a fresh
session cannot reconstruct: Failed Attempts (dead ends cost the most context to
rediscover) and a single Next Step (a list invites the next session to re-plan).
"""
from __future__ import annotations

import fnmatch
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from context_vigil import paths, secretscan, snapshot

SECTIONS = ("Goal", "Current State", "Files in Flight", "Failed Attempts", "Next Step")
REQUIRED = ("Failed Attempts", "Next Step")
# Rough token estimate: chars / 4. Cheap, dependency-free, good enough to bound size.
CHARS_PER_TOKEN = 4
INLINE_MAX_TOKENS = 2000
INJECT_CAP_FACTOR = 2        # injection / --resume hard cap, in multiples of max_tokens
SUMMARY_FIELD_CHARS = 80     # branch and goal in the waiting notice
RESUME_PREAMBLE = (
    "Resume from this handover. Don't re-investigate anything marked complete, "
    "don't retry anything under Failed Attempts — start with the Next Step."
)

_HEADING = re.compile(r"^##\s+(.*)$")
_NON_WORD = re.compile(r"[^a-z ]")
_CANON = {s.lower(): s for s in SECTIONS}
_ITEM = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+")
_PLACEHOLDER = re.compile(r"^<.*>$", re.DOTALL)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


class HandoverError(ValueError):
    """Notes that cannot become a handover; the message says exactly why."""


# --inline never takes these, whatever the path given (it is resolved first, so a
# harmless-looking symlink does not get past): names that hold credentials, the
# user's shell rc files, and everything under a credential or Claude config dir.
_SECRET_NAMES = (".env", ".env.*", ".envrc", "*.env", "*.pem", "*.key", "id_*",
                 "*credential*", "*secret*", "*token*", "*.htpasswd", ".htpasswd", ".s3cfg",
                 ".boto", ".my.cnf", "*.ppk", ".netrc", ".npmrc", ".pypirc", ".pgpass",
                 ".git-credentials", ".dockercfg", "*.p12", "*.pfx", "*.jks", "*.keystore",
                 "*.kdbx", "*.tfvars", "*.tfstate", ".zshrc", ".zshenv", ".zprofile",
                 ".zlogin", ".bashrc", ".bash_profile", ".bash_login", ".profile")
_SECRET_HOME_DIRS = (".ssh", ".aws", ".gnupg", ".config/gh", ".config/gcloud", ".azure",
                     ".docker", ".kube")


def _under(path: Path, root: Path) -> bool:
    return any(path == r or r in path.parents
               for r in {root, Path(os.path.realpath(str(root)))})


def secret_bearing(path: Path) -> bool:
    """True when ``path`` (as given or resolved through symlinks) is a file --inline
    must never embed: see ``_SECRET_NAMES`` and ``_SECRET_HOME_DIRS``; also anything
    under ``~/.claude*``, the Claude config dir or context-vigil's data root."""
    given = Path(os.path.abspath(str(path)))
    resolved = Path(os.path.realpath(str(path)))
    for candidate in (given, resolved):
        if any(fnmatch.fnmatchcase(candidate.name.lower(), pattern)
               for pattern in _SECRET_NAMES):
            return True
    home = Path.home()
    roots = [home / d for d in _SECRET_HOME_DIRS] + [paths.config_dir(), paths.data_root()]
    for candidate in (given, resolved):
        if any(_under(candidate, root) for root in roots):
            return True
        for base in {home, Path(os.path.realpath(str(home)))}:
            try:
                first = candidate.relative_to(base).parts[:1]
            except ValueError:
                continue
            if first and first[0].startswith(".claude"):
                return True
    return False


def secret_refusal(notes: str) -> Optional[str]:
    """Why ``notes`` must not be saved (the line number only, never the match)."""
    line = secretscan.first_secret_line(notes)
    if line is None:
        return None
    return (f"notes contain what looks like a secret at line {line} — remove it (say "
            "where it lives instead) and re-run")


def template_path() -> Path:
    return paths.skill_dir() / "templates" / "handover.md"


def _canonical(heading: str) -> Optional[str]:
    key = " ".join(_NON_WORD.sub(" ", heading.lower()).split())
    return _CANON.get(key)


def parse_sections(notes: str) -> Dict[str, str]:
    """Map canonical section name → stripped body, ignoring emoji and case."""
    sections: Dict[str, List[str]] = {}
    current: Optional[str] = None
    for line in _COMMENT.sub("", notes).splitlines():
        match = _HEADING.match(line)
        if match:
            current = _canonical(match.group(1))
            if current is not None:
                sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return {name: "\n".join(body).strip() for name, body in sections.items()}


def validate(notes: str) -> None:
    sections = parse_sections(notes)
    for name in REQUIRED:
        body = sections.get(name, "")
        if not body or _PLACEHOLDER.match(body):
            raise HandoverError(
                f"'## {name}' is missing or empty — "
                + ("write 'None' if nothing failed" if name == "Failed Attempts"
                   else "give exactly one concrete action")
            )
    step = sections["Next Step"]
    items = [line for line in step.splitlines() if _ITEM.match(line)]
    paragraphs = [p for p in re.split(r"\n\s*\n", step) if p.strip()]
    if len(items) > 1 or (not items and len(paragraphs) > 1):
        raise HandoverError("'## Next Step' must hold exactly one action, not a list")


def summary(document: str, written_at: Optional[float]) -> str:
    """One line for the launch notice: when, branch, goal."""
    when = "earlier"
    if written_at:
        try:
            when = datetime.fromtimestamp(written_at).strftime("%a %H:%M")
        except (OverflowError, OSError, ValueError):
            pass
    branch = re.search(r"- Branch: `([^`\n]+)`", document)
    goal = parse_sections(document).get("Goal", "").splitlines()
    text = f"a handover is waiting from {when}"
    # This line reaches the model and the screen before anyone asked to load the
    # handover: a branch or goal that looks key-shaped is dropped, not shown.
    if branch and not secretscan.looks_secret(branch.group(1)):
        text += f" on `{branch.group(1).strip()[:SUMMARY_FIELD_CHARS]}`"
    if goal and goal[0].strip() and not secretscan.looks_secret(goal[0]):
        text += f": \"{goal[0].strip()[:SUMMARY_FIELD_CHARS]}\""
    return text


def cap_for_injection(document: str, max_tokens: int) -> str:
    """The handover as injected at SessionStart or printed by ``--resume``: whole
    when within 2x ``handover.max_tokens`` (``handover`` itself refuses above 1x, so
    only a hand-edited file or one written under a larger budget is cut), else cut at
    a line boundary with a marker saying so."""
    limit = INJECT_CAP_FACTOR * max(max_tokens, 1) * CHARS_PER_TOKEN
    if len(document) <= limit:
        return document
    kept = document[:limit]
    if "\n" in kept:
        kept = kept[:kept.rindex("\n")]
    return (f"{kept}\n… [truncated by context-vigil: the handover was ~"
            f"{estimate_tokens(document)} tokens, over {INJECT_CAP_FACTOR}x "
            f"handover.max_tokens ({max_tokens})]")


def estimate_tokens(text: str) -> int:
    return -(-len(text) // CHARS_PER_TOKEN)


def _cap_inline(body: str, path: Path) -> str:
    """Cut an inlined file at INLINE_MAX_TOKENS, saying exactly what was left out."""
    limit = INLINE_MAX_TOKENS * CHARS_PER_TOKEN
    if len(body) <= limit:
        return body
    kept = body[:limit]
    if "\n" in kept:
        kept = kept[:kept.rindex("\n")]
    more = len(body[len(kept):].strip("\n").splitlines())
    return f"{kept}\n… [truncated: {more} more lines — {path}]"


def assemble(notes: str, cwd: Path, inline: List[Path], include_snapshot: bool,
             max_tokens: Optional[int] = None) -> str:
    validate(notes)
    refusal = secret_refusal(notes)
    if refusal:
        raise HandoverError(refusal)
    parts = [f"# Handover — {datetime.now().strftime('%Y-%m-%d %H:%M')}", notes.strip()]
    if include_snapshot:
        parts.append(snapshot.session_snapshot(cwd.resolve()).strip())
    for path in inline:
        if secret_bearing(path):
            raise HandoverError(
                f"--inline refused: {path} is a secret-bearing file (keys, credentials, env, "
                "shell rc, Claude or context-vigil config) — never inline secrets; "
                "reference it by path instead")
        try:
            body = path.read_text(encoding="utf-8").strip()
        except UnicodeError as exc:
            raise HandoverError(f"--inline is not UTF-8 text: {path}") from exc
        except OSError as exc:
            raise HandoverError(f"--inline unreadable: {path} "
                                f"({exc.strerror or type(exc).__name__})") from exc
        if secretscan.looks_secret(body):
            raise HandoverError(
                f"--inline refused: {path} holds what looks like a secret (a key, token or "
                "password) — not inlined; never inline secrets")
        parts.append(f"## Inlined: `{path}`\n\n```\n{_cap_inline(body, path)}\n```")
    document = "\n\n".join(parts) + "\n"
    if max_tokens is not None:
        size = estimate_tokens(document)
        if size > max_tokens:
            raise HandoverError(
                f"~{size} tokens exceeds handover.max_tokens ({max_tokens}) — "
                f"trim ~{size - max_tokens} tokens from the notes (or drop --inline "
                "files) and re-run")
    return document
