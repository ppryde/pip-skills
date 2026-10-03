from __future__ import annotations

from pathlib import Path

import pytest
from context_vigil import handover

GOOD = """## 🎯 Goal
Ship it.

## Current State
- ✅ Done: a

## Failed Attempts
None

## ➡️ Next Step
Run the tests.
"""


def test_template_parses_and_names_every_section() -> None:
    sections = handover.parse_sections(handover.template_path().read_text())
    assert set(handover.SECTIONS) <= set(sections)


def test_emoji_and_case_insensitive_headings() -> None:
    sections = handover.parse_sections("## 🎯 goal\nx\n## NEXT STEP\ny\n")
    assert sections == {"Goal": "x", "Next Step": "y"}


def test_valid_notes_pass() -> None:
    handover.validate(GOOD)


@pytest.mark.parametrize("notes,msg", [
    ("## Next Step\nGo.\n", "Failed Attempts"),
    ("## Failed Attempts\nNone\n", "Next Step"),
    ("## Failed Attempts\n\n## Next Step\nGo.\n", "Failed Attempts"),
    ("## Failed Attempts\nNone\n## Next Step\n- a\n- b\n", "exactly one"),
    ("## Failed Attempts\nNone\n## Next Step\nfirst\n\nsecond\n", "exactly one"),
])
def test_invalid_notes_rejected(notes: str, msg: str) -> None:
    with pytest.raises(handover.HandoverError, match=msg):
        handover.validate(notes)


def test_template_placeholders_are_rejected() -> None:
    with pytest.raises(handover.HandoverError):
        handover.validate(handover.template_path().read_text())


def test_assemble_order(repo: Path, iso: Path) -> None:
    extra = iso / "plan.md"
    extra.write_text("PLAN BODY")
    doc = handover.assemble(GOOD, repo, [extra], include_snapshot=True)
    assert doc.index("Ship it.") < doc.index("## Session snapshot") < doc.index("PLAN BODY")


def test_assemble_without_snapshot(repo: Path) -> None:
    doc = handover.assemble(GOOD, repo, [], include_snapshot=False)
    assert "Session snapshot" not in doc


def test_assemble_unreadable_inline(repo: Path, iso: Path) -> None:
    with pytest.raises(handover.HandoverError, match="--inline"):
        handover.assemble(GOOD, repo, [iso / "missing.md"], include_snapshot=False)


def test_cli_handover_arms(run_cli, repo: Path, iso: Path) -> None:
    notes = iso / "notes.md"
    notes.write_text(GOOD)
    result = run_cli("handover", "--file", str(notes), cwd=repo)
    assert result.returncode == 0, result.stderr
    assert "type /clear" in result.stdout  # no tmux in tests → manual
    from context_vigil import paths, state
    assert state.clear_requested(paths.scope_dir(repo))


def test_cli_resume_and_discard(run_cli, repo: Path) -> None:
    from context_vigil import paths, state
    scope = paths.scope_dir(repo)
    state.request_clear(scope, "WAITING DOC")
    out = run_cli("handover", "--resume", cwd=repo)
    assert out.returncode == 0
    assert out.stdout.startswith("Resume from this handover.") and "WAITING DOC" in out.stdout
    assert state.read_handoff(scope) is None
    assert run_cli("handover", "--discard", cwd=repo).returncode == 1  # nothing waiting
    state.request_clear(scope, "AGAIN")
    out = run_cli("handover", "--discard", cwd=repo)
    assert out.returncode == 0 and "WAITING" not in out.stdout
    assert state.read_handoff(scope) is None


def test_summary_line() -> None:
    doc = "# Handover\n\n## Goal\nShip it.\n\n## Git\n\n- Branch: `feat/x`\n"
    line = handover.summary(doc, None)
    assert line == 'a handover is waiting from earlier on `feat/x`: "Ship it."'


def test_cli_handover_rejects_bad_notes(run_cli, repo: Path, iso: Path) -> None:
    notes = iso / "notes.md"
    notes.write_text("## Goal\nx\n")
    result = run_cli("handover", "--file", str(notes), cwd=repo)
    assert result.returncode == 1
    assert "Failed Attempts" in result.stderr


def test_summary_survives_corrupt_mtime() -> None:
    assert "from earlier" in handover.summary("## Goal\nx\n", 1e30)
    assert "from earlier" in handover.summary("## Goal\nx\n", -1e30)


def test_cli_handover_cooldown_message(run_cli, repo: Path, iso: Path) -> None:
    from context_vigil import paths, state
    scope = paths.scope_dir(repo)
    state.request_clear(scope, "H")
    state.consume_clear_flag(scope)  # sets cooldown
    notes = iso / "notes.md"
    notes.write_text(GOOD)
    result = run_cli("handover", "--file", str(notes), cwd=repo)
    assert result.returncode == 1
    assert "a session just started" in result.stderr and "cooldown" in result.stderr
    assert "/clear just happened" not in result.stderr
