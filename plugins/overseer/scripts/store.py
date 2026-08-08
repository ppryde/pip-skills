"""Filesystem operations for the .workflow/ tree. Single-writer by convention."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from scripts.models import Card, CardParseError

WORKFLOW_DIRNAME = ".workflow"
_MINTED_ID_RE = re.compile(r"\AWF-(\d+)-")
_MIGRATE_SKIP_TOP = {"ledger.md", "cards"}  # DB owns cards; ledger.md is a view
_MIGRATE_SKIP_PATHS = {("archive", "cards")}  # DB owns archived cards too


def workflow_root(repo_root: Path) -> Path:
    return repo_root / WORKFLOW_DIRNAME


def _git_common_dir(repo_root: Path) -> Path | None:
    """Resolve ``git rev-parse --git-common-dir`` for ``repo_root`` to an
    absolute path; shared resolution step behind ``derive_repo_label`` and
    ``derive_repo_root`` — see ``derive_repo_label``'s docstring for the
    git-common-dir rationale and portability notes.

    None on any failure — not a git repo, git missing, unreadable output.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout.strip()
    if not raw:
        return None
    # Deliberately uses plain ``--git-common-dir`` plus manual path
    # resolution rather than git's ``--path-format=absolute`` flag (needs
    # git >= 2.31) for broader portability: the raw output is relative to
    # ``repo_root`` on some git versions and already absolute on others;
    # ``Path(repo_root, raw).resolve()`` handles both, since `Path` discards
    # the first component whenever the second is already absolute.
    return Path(repo_root, raw).resolve()


def derive_repo_label(repo_root: Path) -> str | None:
    """The top-level repo name that owns ``repo_root``, even from a worktree.

    Ledgers can live inside a linked worktree (e.g.
    ``.claude/worktrees/some-branch``), so a naive ``repo_root.name`` would
    record the worktree directory, not the repo. ``git rev-parse
    --git-common-dir`` resolves to the MAIN repo's ``.git`` dir in every
    case, worktree or not (unlike ``--git-dir``, which points at the
    worktree's private gitdir under ``.git/worktrees/<name>``) — see
    git-worktree(1). That dir's parent directory's basename is the repo
    name (``.../pip-skills/.git`` -> ``"pip-skills"``); a bare-ish common
    dir that doesn't end in ``.git`` uses its own basename instead.

    None on any failure — not a git repo, git missing, unreadable output —
    this is a display label, not load-bearing state.
    """
    common_dir = _git_common_dir(repo_root)
    if common_dir is None:
        return None
    label = common_dir.parent.name if common_dir.name == ".git" else common_dir.name
    return label or None


def derive_repo_root(repo_root: Path) -> Path | None:
    """The MAIN repo's root PATH that owns ``repo_root``, even from a worktree.

    Mirrors ``derive_repo_label``'s git-common-dir resolution (see its
    docstring for the rationale/portability notes), but returns the actual
    root PATH rather than a display name — stable across worktrees, so
    every worktree of the same repo resolves to this same absolute path.
    ``db.connect`` records this as ``meta['repo_root']`` so the dashboard's
    ``repos`` verb can enumerate one board per repo regardless of which
    worktree wrote to it.

    None on any failure — not a git repo, git missing, unreadable output —
    same as ``derive_repo_label``.
    """
    common_dir = _git_common_dir(repo_root)
    if common_dir is None:
        return None
    return common_dir.parent if common_dir.name == ".git" else common_dir


def state_root(repo_root: Path) -> Path:
    """Resolve the overseer state root: the central per-repo folder."""
    from scripts.config import central_root
    return central_root(repo_root)


def migrate_workflow_to_central(repo_root: Path) -> int:
    """Copy legacy .workflow/ sprint/usage/knowledge/archive state into the
    central folder, once. Never overwrites an existing central file. Sources
    from the canonical repo's .workflow/ (not a worktree's). Returns files copied.

    Skips top-level ``cards/`` and ``ledger.md`` (the DB owns live cards;
    ledger.md is a generated view) and ``archive/cards/`` (the DB owns
    archived cards too, imported by ``db.migrate_from_workflow``). Keeps
    ``archive/corrupt/`` — quarantined files are never in the DB and would
    otherwise be lost. The skip checks are path-specific (top-level name, or
    the exact ``archive/cards`` prefix), not a basename match, so e.g. a file
    literally named ``ledger.md`` nested inside ``knowledge/`` is still
    copied.
    """
    from scripts.config import central_root
    source_root = (derive_repo_root(repo_root) or repo_root) / WORKFLOW_DIRNAME
    if not source_root.is_dir():
        return 0
    dest_root = central_root(repo_root)
    copied = 0
    for src in source_root.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(source_root)
        if rel.parts and rel.parts[0] in _MIGRATE_SKIP_TOP:
            continue
        if rel.parts[:2] in _MIGRATE_SKIP_PATHS:
            continue
        dest = dest_root / rel
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied += 1
    return copied


def init_workflow(repo_root: Path) -> Path:
    root = state_root(repo_root)
    for sub in ("cards", "sprints", "archive/cards", "archive/corrupt"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    if root == workflow_root(repo_root):
        gitignore = repo_root / ".gitignore"
        existing = gitignore.read_text() if gitignore.exists() else ""
        if f"{WORKFLOW_DIRNAME}/" not in existing.split("\n"):
            suffix = "" if existing in ("", "\n") or existing.endswith("\n") else "\n"
            gitignore.write_text(f"{existing}{suffix}{WORKFLOW_DIRNAME}/\n")
    return root


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:40].rstrip("-")


def mint_id(root: Path) -> str:
    highest = 0
    for directory in (root / "cards", root / "archive" / "cards"):
        for path in directory.glob("WF-*.md"):
            match = _MINTED_ID_RE.match(path.name)
            if match:
                highest = max(highest, int(match.group(1)))
    return f"WF-{highest + 1:03d}"


def card_path(root: Path, card: Card) -> Path:
    return root / "cards" / f"{card.id}-{slugify(card.title)}.md"


def find_card_path(root: Path, card_id: str) -> Path:
    matches = sorted((root / "cards").glob(f"{card_id}-*.md"))
    if not matches:
        raise FileNotFoundError(f"no live card with id {card_id}")
    return matches[0]


def load_card(path: Path) -> Card:
    try:
        return Card.from_text(path.read_text())
    except CardParseError as exc:
        raise CardParseError(f"{path.name}: {exc}") from exc


def save_card(root: Path, card: Card) -> Path:
    path = card_path(root, card)
    path.write_text(card.to_text())
    return path


def _uniquify(target: Path) -> Path:
    """If target exists, append a numeric suffix ({stem}.1{suffix}, .2, …) until free."""
    original = target
    counter = 0
    while target.exists():
        counter += 1
        target = original.parent / f"{original.stem}.{counter}{original.suffix}"
    return target


def quarantine(root: Path, path: Path) -> Path:
    corrupt_dir = root / "archive" / "corrupt"
    target = _uniquify(corrupt_dir / path.name)
    path.rename(target)
    return target


def load_live_cards(root: Path) -> tuple[list[Card], list[Path]]:
    cards: list[Card] = []
    quarantined: list[Path] = []
    for path in sorted((root / "cards").glob("*.md")):
        try:
            cards.append(load_card(path))
        except CardParseError:
            quarantined.append(quarantine(root, path))
    cards.sort(key=lambda c: c.id)
    return cards, quarantined


def archive_card(root: Path, card: Card) -> Path:
    target = _uniquify(root / "archive" / "cards" / f"{card.id}-{slugify(card.title)}.md")
    target.write_text(card.to_text())
    live = card_path(root, card)
    if live.exists():
        live.unlink()
    return target


def load_archived_cards(root: Path) -> list[Card]:
    cards = []
    for path in (root / "archive" / "cards").glob("*.md"):
        try:
            cards.append(Card.from_text(path.read_text()))
        except CardParseError:
            continue
    return sorted(cards, key=lambda c: c.updated, reverse=True)
