"""Read a review-clone persona so the orchestrator can seat it as a
reviewer. This layer only READS persona files — it never scrapes GitHub or
refreshes them (that stays review-clone's job)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from scripts.discovery import review_clone_root

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


@dataclass
class Persona:
    alias: str
    frontmatter: dict
    body: str


def persona_path(alias: str) -> Path:
    return review_clone_root() / alias / "PERSONA.md"


def read_persona(alias: str) -> Persona | None:
    path = persona_path(alias)
    if not path.exists():
        return None
    text = path.read_text()
    match = _FRONTMATTER_RE.match(text)
    if match:
        try:
            front = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            front = {}
        body = match.group(2)
    else:
        front, body = {}, text
    return Persona(alias=alias, frontmatter=front if isinstance(front, dict) else {}, body=body)
