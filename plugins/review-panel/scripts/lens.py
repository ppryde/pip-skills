"""Which pip-agents persona seats a catalogue reviewer.

A reviewer file may open with a frontmatter block carrying `lens: <name>`; without one the lens is `rules` (the file
is a rulebook: its "What to look for" table). The lens names and their personas come from the vendored contract
(`personas.json`), so a lens added to pip-agents is available here after a sync, with no list to keep in step."""
from __future__ import annotations

import re

from scripts.pip_agents import validator

DEFAULT_LENS = "rules"
_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_LENS_LINE = re.compile(r"^lens:[ \t]*(\S+)[ \t]*$", re.MULTILINE)


class LensError(Exception):
    """A reviewer file names a lens no pip-agents reviewer persona carries."""


def lens_personas() -> dict[str, str]:
    """lens -> persona name, for every persona of kind `review` that has a lens (so not `general`)."""
    return {
        info["lens"]: name
        for name, info in validator().personas().items()
        if info.get("kind") == "review" and info.get("lens")
    }


def persona_for_lens(lens: str) -> str:
    try:
        return lens_personas()[lens]
    except KeyError:
        raise LensError(f"unknown lens {lens!r}; expected one of {sorted(lens_personas())}") from None


def seat_persona(lens: str) -> str:
    """The Agent `subagent_type` for a seat with this lens."""
    return f"pip-agents:{persona_for_lens(lens)}"


def lens_of(text: str) -> str:
    """The lens a reviewer file declares in its opening frontmatter (default `rules`)."""
    m = _FRONTMATTER.match(text)
    found = _LENS_LINE.search(m.group(1)) if m else None
    lens = found.group(1) if found else DEFAULT_LENS
    persona_for_lens(lens)  # raises LensError when unknown
    return lens
