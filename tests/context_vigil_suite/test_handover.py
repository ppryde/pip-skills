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


@pytest.fixture
def notes_file(iso: Path) -> Path:
    """Valid handover notes (``GOOD``) in a file outside the repository."""
    notes = iso / "notes.md"
    notes.write_text(GOOD)
    return notes


def test_template_parses_and_names_every_section() -> None:
    sections = handover.parse_sections(handover.template_path().read_text())
    assert set(handover.SECTIONS) <= set(sections)


def test_template_does_not_promise_a_file_list() -> None:
    text = handover.template_path().read_text().lower()
    assert "lists changed files" not in text and "recently modified files" not in text
    assert "snapshot already lists" not in text
    assert "branch" in text and "git" in text   # tells the agent what the snapshot does give


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


def test_assemble_over_budget_refuses_with_trim_amount(repo: Path) -> None:
    big = GOOD.replace("- ✅ Done: a", "word " * 2000)          # ~2500 tokens of extra notes
    with pytest.raises(handover.HandoverError) as err:
        handover.assemble(big, repo, [], include_snapshot=False, max_tokens=500)
    msg = str(err.value)
    assert "handover.max_tokens" in msg and "500" in msg and "trim" in msg
    assert "\n" not in msg                      # one line
    import re
    over = int(re.search(r"trim ~(\d+)", msg).group(1))
    assert over > 1500


def test_assemble_within_budget_is_untouched(repo: Path) -> None:
    doc = handover.assemble(GOOD, repo, [], include_snapshot=False, max_tokens=8000)
    assert "Ship it." in doc


def test_inline_file_is_capped_with_marker(repo: Path, iso: Path) -> None:
    big = iso / "big.md"
    big.write_text("\n".join(f"line {i:05d} " + "x" * 40 for i in range(2000)))
    doc = handover.assemble(GOOD, repo, [big], include_snapshot=False, max_tokens=10**6)
    assert "line 00000" in doc and "line 01999" not in doc
    match = __import__("re").search(
        r"… \[truncated: (\d+) more lines — " + __import__("re").escape(str(big)) + r"\]", doc)
    assert match and int(match.group(1)) > 1000
    assert len(doc) < handover.INLINE_MAX_TOKENS * 4 + 2000


def test_inline_small_file_is_whole(repo: Path, iso: Path) -> None:
    small = iso / "small.md"
    small.write_text("a\nb\nc")
    doc = handover.assemble(GOOD, repo, [small], include_snapshot=False)
    assert "a\nb\nc" in doc and "truncated" not in doc


def test_inline_counts_against_budget(repo: Path, iso: Path) -> None:
    f = iso / "f.md"
    f.write_text("y" * 7000)                     # under the per-file cap
    with pytest.raises(handover.HandoverError, match="max_tokens"):
        handover.assemble(GOOD, repo, [f], include_snapshot=False, max_tokens=500)


def test_assemble_unreadable_inline(repo: Path, iso: Path) -> None:
    with pytest.raises(handover.HandoverError, match="--inline"):
        handover.assemble(GOOD, repo, [iso / "missing.md"], include_snapshot=False)


def test_cli_handover_arms(run_cli, repo: Path, notes_file: Path) -> None:
    result = run_cli("handover", "--file", str(notes_file), cwd=repo)
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


def test_cli_handover_proceeds_during_cooldown(run_cli, repo: Path, notes_file: Path) -> None:
    from context_vigil import paths, state
    scope = paths.scope_dir(repo)
    state.begin_cycle(scope, cooldown=True)
    result = run_cli("handover", "--file", str(notes_file), cwd=repo)
    assert result.returncode == 0, result.stderr
    assert state.clear_requested(scope)


def test_cli_handover_inside_reachable_tmux_says_clear_is_automatic(
        run_cli, repo: Path, iso: Path, notes_file: Path) -> None:
    stub = iso / "tmux"
    stub.write_text("#!/usr/bin/env bash\nexit 0\n")
    stub.chmod(0o755)
    result = run_cli("handover", "--file", str(notes_file), cwd=repo, env={
        "CONTEXT_VIGIL_TMUX_BIN": str(stub), "TMUX": "/tmp/fake,1,0", "TMUX_PANE": "%7"})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "handover saved — /clear will be sent at the end of this turn"
    assert "type /clear" not in result.stdout


def test_cli_handover_refuses_over_budget(run_cli, repo: Path, iso: Path) -> None:
    notes = iso / "notes.md"
    notes.write_text(GOOD.replace("- ✅ Done: a", "word " * 12000))
    result = run_cli("handover", "--file", str(notes), cwd=repo)
    assert result.returncode == 1
    assert "handover refused" in result.stderr and "trim" in result.stderr
    from context_vigil import paths, state
    assert not state.clear_requested(paths.scope_dir(repo))     # never armed


def test_cli_handover_budget_is_configurable(run_cli, repo: Path, iso: Path) -> None:
    notes = iso / "notes.md"
    notes.write_text(GOOD.replace("- ✅ Done: a", "word " * 12000))
    result = run_cli("handover", "--file", str(notes), cwd=repo,
                     env={"CONTEXT_VIGIL_HANDOVER_MAX_TOKENS": "50000"})
    assert result.returncode == 0, result.stderr


def test_cli_no_tmux_message_says_send_a_message(run_cli, repo: Path, notes_file: Path) -> None:
    result = run_cli("handover", "--file", str(notes_file), cwd=repo)
    assert "type /clear" in result.stdout and "go" in result.stdout
