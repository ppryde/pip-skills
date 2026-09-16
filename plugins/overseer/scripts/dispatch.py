"""Dispatch directory layout and agent-identity helpers (WF-113 §4).

Every overseer agent writes its detail to a file under
``<state_root>/dispatch/<card>/<stage>/`` and ends its final message with a
typed JSON report block (``scripts/schemas.py``) instead of pasting content
into the reply. The guard hook (``scripts/guard.py``) and the report hook
(``scripts/report_hook.py``) both need to tell an overseer agent apart from
the orchestrator and from each other; that identity logic lives here.
"""
from __future__ import annotations

from pathlib import Path

from scripts.store import state_root

ROLES = ("planner", "implementer", "reviewer", "fixer", "verifier")


def agent_name(agent_type: object) -> str | None:
    """``overseer:overseer-reviewer`` (plugin agents carry the plugin prefix
    in hook payloads) or ``overseer-reviewer`` → ``overseer-reviewer``."""
    if not isinstance(agent_type, str) or not agent_type:
        return None
    return agent_type.split(":")[-1]


def role_of(agent_type: object) -> str | None:
    name = agent_name(agent_type)
    if not name or not name.startswith("overseer-"):
        return None
    role = name[len("overseer-"):]
    return role if role in ROLES else None


def is_hub_agent(agent_type: object) -> bool:
    """A hub dispatches rather than works (Phase 2's foreman); the guard
    holds it to the orchestrator's no-work rule."""
    return agent_name(agent_type) == "overseer-foreman"


def dispatch_dir(repo_root: Path, card_id: str, stage: str) -> Path:
    return state_root(repo_root) / "dispatch" / card_id / stage
