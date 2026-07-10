"""Root-keyed orchestrator runtime state under <state_root>/orchestrator/.

The state root is the per-orchestrator key: one root, one writer, one orchestrator.
Every function is quarantine-safe by construction — it only touches its own marker
files and never raises on a missing path.
"""
from __future__ import annotations

from pathlib import Path

from scripts.store import state_root


def orchestrator_dir(repo_root: Path) -> Path:
    return state_root(repo_root) / "orchestrator"


def _ensure(repo_root: Path) -> Path:
    d = orchestrator_dir(repo_root)
    d.mkdir(parents=True, exist_ok=True)
    return d


def active_marker(repo_root: Path) -> Path:
    return orchestrator_dir(repo_root) / "active"


def clear_flag(repo_root: Path) -> Path:
    return orchestrator_dir(repo_root) / "clear-requested"


def paused_flag(repo_root: Path) -> Path:
    return orchestrator_dir(repo_root) / "paused"


def cooldown_marker(repo_root: Path) -> Path:
    return orchestrator_dir(repo_root) / "cooldown"


def handoff_path(repo_root: Path) -> Path:
    return orchestrator_dir(repo_root) / "handoff.md"


def promote(repo_root: Path) -> None:
    _ensure(repo_root)
    active_marker(repo_root).touch()


def is_active(repo_root: Path) -> bool:
    return active_marker(repo_root).exists()


def is_paused(repo_root: Path) -> bool:
    return paused_flag(repo_root).exists()


def pause(repo_root: Path) -> None:
    _ensure(repo_root)
    paused_flag(repo_root).touch()


def resume(repo_root: Path) -> None:
    paused_flag(repo_root).unlink(missing_ok=True)


def request_clear(repo_root: Path, handoff_text: str) -> str:
    if not is_active(repo_root):
        return "inactive"
    if is_paused(repo_root):
        return "paused"
    if cooldown_marker(repo_root).exists():
        return "cooldown"
    _ensure(repo_root)
    handoff_path(repo_root).write_text(handoff_text)
    clear_flag(repo_root).touch()
    return "armed"


def consume_clear_flag(repo_root: Path) -> bool:
    if not is_active(repo_root) or is_paused(repo_root):
        return False
    if not clear_flag(repo_root).exists():
        return False
    clear_flag(repo_root).unlink(missing_ok=True)  # remove FIRST: cannot re-fire
    _ensure(repo_root)
    cooldown_marker(repo_root).touch()
    return True


def arm_ready(repo_root: Path) -> None:
    cooldown_marker(repo_root).unlink(missing_ok=True)
    clear_flag(repo_root).unlink(missing_ok=True)


def read_handoff(repo_root: Path) -> str | None:
    path = handoff_path(repo_root)
    if not path.exists():
        return None
    try:
        return path.read_text()
    except OSError:
        return None
