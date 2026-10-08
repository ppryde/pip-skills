"""pane.safe_to_type against real capture shapes (Claude Code 2.1.289)."""
from __future__ import annotations

from pathlib import Path

import pytest
from context_vigil import pane

RULE = "\x1b[38;5;244m" + "─" * 60 + "\x1b[39m"
IDLE_ROW = '\x1b[39m❯\xa0\x1b[2mTry "how do I log an error?"\x1b[0m'
EMPTY_ROW = "\x1b[39m❯\xa0"
TYPED_ROW = "\x1b[39m❯\xa0hello typed"
STATUS = "  🧠 22% │ 🌿 master"


def screen(*rows: str) -> str:
    return "\n".join(rows) + "\n"


IDLE = screen("⏺ done.", "", RULE, IDLE_ROW, RULE, STATUS)
IDLE_EMPTY = screen(RULE, EMPTY_ROW, RULE, STATUS)
TYPED = screen(RULE, TYPED_ROW, RULE, STATUS)
TRUST = screen(" Quick safety check: Is this a project you created or one you trust?",
               " \x1b[38;5;153m❯\x1b[39m \x1b[38;5;153mNo, exit\x1b[39m",
               "   Yes, I trust this folder", "", " Enter to confirm · Esc to cancel")
PERMISSION = screen(" Do you want to proceed?", " ❯ 1. Yes", "   2. No",
                    " Esc to cancel · Tab to amend")
REMOTE_MENU = screen("   Remote Control", "   ❯ Continue", "   Enter to select · Esc to continue")
TRANSCRIPT_PROMPT_ONLY = screen("❯ Use the Bash tool to run exactly: sleep 30",
                                "  Ran 2 shell commands")


@pytest.mark.parametrize("text,safe", [
    (IDLE, True), (IDLE_EMPTY, True),
    (TYPED, False), (TRUST, False), (PERMISSION, False), (REMOTE_MENU, False),
    (TRANSCRIPT_PROMPT_ONLY, False), ("", False),
])
def test_safe_to_type(text: str, safe: bool) -> None:
    assert pane.safe_to_type(text) is safe


def test_typed_text_ignores_dim_placeholder() -> None:
    assert pane.typed_text(IDLE_ROW) == ""
    assert pane.typed_text(TYPED_ROW) == "hello typed"


def test_dim_reset_by_22_counts_as_typed() -> None:
    row = "❯\xa0\x1b[2mTry\x1b[22m x"
    assert pane.typed_text(row) == "x"


def test_pane_safe_uses_tmux_capture(iso: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shot = iso / "shot.txt"
    shot.write_text(IDLE)
    stub = iso / "tmux"
    stub.write_text(f'#!/usr/bin/env bash\n[ "$1" = capture-pane ] && cat "{shot}"\nexit 0\n')
    stub.chmod(0o755)
    monkeypatch.setenv("CONTEXT_VIGIL_TMUX_BIN", str(stub))
    assert pane.pane_safe("%7") is True
    shot.write_text(TRUST)
    assert pane.pane_safe("%7") is False


def test_pane_safe_false_when_capture_fails(iso: Path) -> None:
    assert pane.pane_safe("%7") is False   # iso points the tmux binary at nothing


@pytest.mark.parametrize("sgr", ["\x1b[38;5;2m", "\x1b[38;2;0;0;0m", "\x1b[48;2;1;2;3m\x1b[38;5;02m"])
def test_colour_parameters_are_not_dim(sgr: str) -> None:
    row = f"{sgr}❯\xa0{sgr}hello typed\x1b[39m"
    assert pane.typed_text(row) == "hello typed"
    assert pane.safe_to_type(screen(RULE, row, RULE, STATUS)) is False


def test_colon_form_sgr_is_unsafe() -> None:
    row = "❯\xa0\x1b[2m\x1b[38:2::1:2:3mhidden\x1b[0m"
    assert pane.safe_to_type(screen(RULE, row, RULE, STATUS)) is False


def test_dim_placeholder_with_colour_stays_safe() -> None:
    row = "❯\xa0\x1b[2;38;5;244mTry this\x1b[0m"
    assert pane.safe_to_type(screen(RULE, row, RULE, STATUS)) is True
