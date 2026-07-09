"""Filesystem operations for the .workflow/ tree. Single-writer by convention."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from scripts.models import Card, CardParseError

WORKFLOW_DIRNAME = ".workflow"
SCRATCH_DIRNAME = "scratch"
SCRATCH_STATE_SUBDIR = "workflow"
_MINTED_ID_RE = re.compile(r"\AWF-(\d+)-")


def workflow_root(repo_root: Path) -> Path:
    return repo_root / WORKFLOW_DIRNAME


def _is_gitignored(repo_root: Path, relpath: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", relpath],
            cwd=repo_root,
            capture_output=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def state_root(repo_root: Path) -> Path:
    """Resolve the overseer state root. Existing .workflow/ always wins."""
    existing = workflow_root(repo_root)
    if existing.is_dir() and any(existing.iterdir()):
        return existing
    scratch = repo_root / SCRATCH_DIRNAME
    if scratch.is_dir() and _is_gitignored(repo_root, SCRATCH_DIRNAME):
        return scratch / SCRATCH_STATE_SUBDIR
    return existing


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
