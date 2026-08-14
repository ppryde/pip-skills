import os
from pathlib import Path

from scripts.discovery import (
    discover_strategies, discover_builtin_reviewers,
    discover_clone_personas, available_reviewers, review_clone_root,
)


def _touch(p: Path, name: str):
    (p / name).parent.mkdir(parents=True, exist_ok=True)
    (p / name).write_text("x")


def test_discover_excludes_underscore_and_nonmd(tmp_path):
    d = tmp_path / "strategies"
    d.mkdir()
    for f in ["committee.md", "blind.md", "_template.md", "README.txt"]:
        _touch(d, f)
    assert discover_strategies(d) == ["blind", "committee"]


def test_discover_builtin_reviewers(tmp_path):
    d = tmp_path / "reviewers"
    d.mkdir()
    for f in ["general.md", "_template.md"]:
        _touch(d, f)
    assert discover_builtin_reviewers(d) == ["general"]


def test_discover_missing_dir_is_empty(tmp_path):
    assert discover_strategies(tmp_path / "absent") == []


def test_review_clone_root_prefers_env(tmp_path):
    # REVIEW_CLONE_ROOT is pinned into tmp_path by the isolation fixture.
    assert review_clone_root() == Path(os.environ["REVIEW_CLONE_ROOT"])


def test_review_clone_root_falls_back_to_config_dir(monkeypatch):
    # With REVIEW_CLONE_ROOT unset, it derives from CLAUDE_CONFIG_DIR.
    monkeypatch.delenv("REVIEW_CLONE_ROOT", raising=False)
    cfg = os.environ["CLAUDE_CONFIG_DIR"]  # pinned into tmp_path by the fixture
    assert review_clone_root() == Path(cfg) / "review-clone"


def test_discover_clone_personas(tmp_path):
    root = Path(os.environ["REVIEW_CLONE_ROOT"])
    for alias in ["danvk", "kentbeck"]:
        (root / alias).mkdir(parents=True)
        (root / alias / "PERSONA.md").write_text("---\n---\n")
    (root / "empty").mkdir()  # no PERSONA.md -> ignored
    assert discover_clone_personas() == ["danvk", "kentbeck"]


def test_available_reviewers_merges_sources(tmp_path):
    rd = tmp_path / "reviewers"
    rd.mkdir()
    _touch(rd, "general.md")
    root = Path(os.environ["REVIEW_CLONE_ROOT"])
    (root / "danvk").mkdir(parents=True)
    (root / "danvk" / "PERSONA.md").write_text("---\n---\n")
    assert available_reviewers(rd) == ["general", "clone:danvk"]
