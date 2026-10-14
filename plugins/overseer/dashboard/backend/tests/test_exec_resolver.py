"""WF-101 W1: the pure resolver that turns a repo LABEL into (root, board_dir).

No app, no discovery, no filesystem walk: the label is only ever compared with
the labels of entries the host already discovered, so nothing a container sends
can reach a path.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import board_service
from app.board_service import ExecRequest, resolve_exec_board


@pytest.fixture(autouse=True)
def _fresh_warnings() -> None:
    board_service._WARNED.clear()


def entry(tmp_path: Path, label: str, name: str | None = None) -> dict:
    root = tmp_path / "repos" / (name or label)
    root.mkdir(parents=True, exist_ok=True)
    board = tmp_path / "boards" / (name or label)
    board.mkdir(parents=True, exist_ok=True)
    (board / "board.db").write_bytes(b"")
    return {
        "label": label,
        "root": str(root),
        "board_dir": str(tmp_path / "boards" / (name or label)),
        "archived": False,
        "aliases": [],
    }


def status(repo: str, entries: list[dict], aliases: dict | None = None) -> int:
    with pytest.raises(HTTPException) as err:
        resolve_exec_board(repo, entries, aliases)
    return err.value.status_code


def detail(repo: str, entries: list[dict], aliases: dict | None = None) -> str:
    with pytest.raises(HTTPException) as err:
        resolve_exec_board(repo, entries, aliases)
    return str(err.value.detail)


def test_request_model_has_an_optional_repo_defaulting_to_none() -> None:
    assert ExecRequest(argv=["board"]).repo is None
    assert ExecRequest(argv=["board"], repo=None).repo is None
    assert ExecRequest(argv=["board"], repo="pip-skills").repo == "pip-skills"


def test_exact_label_resolves_to_its_root_and_board(tmp_path: Path) -> None:
    entries = [entry(tmp_path, "alpha"), entry(tmp_path, "beta")]
    root, board = resolve_exec_board("beta", entries)
    assert root == Path(entries[1]["root"]).resolve()
    assert board == Path(entries[1]["board_dir"])


@pytest.mark.parametrize("label", ["a", "pip-skills", "wf_100", "a.b", "A" * 100, "x-1.2_3"])
def test_valid_label_shapes_pass_the_charset(tmp_path: Path, label: str) -> None:
    root, _ = resolve_exec_board(label, [entry(tmp_path, label, name="r")])
    assert root.name == "r"


@pytest.mark.parametrize("bad", [
    "", ".", "..", "a/b", "../x", "/etc/passwd", "a\\b", "a b", "a\0b", "a\nb", "a\r\n",
    "%2e%2e", "..%2f", "é", "ａｂ", "a" * 101, "a;b", "a$(x)", "~", "a:b",
])
def test_hostile_or_malformed_labels_are_400_before_any_lookup(tmp_path: Path, bad: str) -> None:
    entries = [entry(tmp_path, "alpha")]
    assert status(bad, entries) == 400


def test_a_discovered_root_string_is_not_a_label(tmp_path: Path) -> None:
    entries = [entry(tmp_path, "alpha")]
    assert status(entries[0]["root"], entries) == 400


def test_empty_string_is_400_not_the_pinned_board(tmp_path: Path) -> None:
    assert status("", [entry(tmp_path, "alpha")]) == 400


def test_label_comparison_is_exact_case_and_whitespace_sensitive(tmp_path: Path) -> None:
    entries = [entry(tmp_path, "Alpha")]
    assert status("alpha", entries) == 404
    assert status("Alpha ", entries) == 400  # a space is not in the charset
    assert resolve_exec_board("Alpha", entries)[0] == Path(entries[0]["root"]).resolve()


def test_unknown_label_is_404_listing_the_valid_labels(tmp_path: Path) -> None:
    entries = [entry(tmp_path, "alpha"), entry(tmp_path, "beta")]
    msg = detail("gamma", entries)
    assert status("gamma", entries) == 404
    assert "unknown repo 'gamma'" in msg and "valid: alpha, beta" in msg


def test_no_fallback_when_there_are_no_entries(tmp_path: Path) -> None:
    assert status("alpha", []) == 404
    assert "valid: (none)" in detail("alpha", [])


def test_duplicate_label_is_409_naming_both_candidates_and_the_alias_hint(tmp_path: Path) -> None:
    one, two = entry(tmp_path, "twin", name="one"), entry(tmp_path, "twin", name="two")
    entries = [one, two, entry(tmp_path, "solo")]
    assert status("twin", entries) == 409
    msg = detail("twin", entries)
    assert f"twin ({one['root']})" in msg and f"twin ({two['root']})" in msg
    assert '"aliases"' in msg and "machine config" in msg
    assert resolve_exec_board("solo", entries)[0].name == "solo"  # others still route


def test_a_root_that_is_no_longer_a_directory_is_404(tmp_path: Path) -> None:
    e = entry(tmp_path, "gone")
    Path(e["root"]).rmdir()
    assert status("gone", [e]) == 404


# --- aliases (owner round 3, R5-A3) -----------------------------------------------

def test_alias_resolves_to_its_live_entry(tmp_path: Path) -> None:
    e = entry(tmp_path, "wayflyer")
    root, board = resolve_exec_board("wayflyer-old", [e], {"wayflyer-old": e["root"]})
    assert root == Path(e["root"]).resolve() and board == Path(e["board_dir"])


def test_alias_target_is_expanded_and_resolved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    e = entry(tmp_path, "wayflyer")
    monkeypatch.setenv("HOME", str(tmp_path))
    root, _ = resolve_exec_board("old", [e], {"old": "~/repos/wayflyer/../wayflyer"})
    assert root == Path(e["root"]).resolve()


def test_alias_to_an_undiscovered_path_is_ignored_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    e = entry(tmp_path, "alpha")
    caplog.set_level(logging.WARNING)
    assert status("ghost", [e], {"ghost": str(tmp_path / "nowhere")}) == 404
    assert "ghost" in caplog.text and "not a live discovered board" in caplog.text
    assert "ghost" not in detail("other", [e], {"ghost": str(tmp_path / "nowhere")})


def test_alias_to_an_archived_path_is_ignored(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    live = entry(tmp_path, "alpha")
    archived_root = tmp_path / "repos" / "oldrepo"
    archived_root.mkdir(parents=True)
    # the route hands over LIVE entries only, so the archived repo is simply absent
    caplog.set_level(logging.WARNING)
    assert status("old", [live], {"old": str(archived_root)}) == 404
    assert "old" in caplog.text


def test_alias_wins_over_a_bare_label_with_one_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    mine, theirs = entry(tmp_path, "mine"), entry(tmp_path, "spoof")
    caplog.set_level(logging.WARNING)
    root, _ = resolve_exec_board("spoof", [mine, theirs], {"spoof": mine["root"]})
    assert root == Path(mine["root"]).resolve()
    assert caplog.text.count("shadows") == 1


def test_container_spoofed_label_equal_to_an_alias_cannot_hijack_alias_users(tmp_path: Path) -> None:
    owner, spoofer, other = entry(tmp_path, "wayflyer"), entry(tmp_path, "wayflyer-old"), entry(tmp_path, "zed")
    entries = [owner, spoofer, other]
    aliases = {"wayflyer-old": owner["root"]}
    assert resolve_exec_board("wayflyer-old", entries, aliases)[0] == Path(owner["root"]).resolve()
    assert resolve_exec_board("zed", entries, aliases)[0].name == "zed"
    assert resolve_exec_board("wayflyer", entries, aliases)[0].name == "wayflyer"


def test_alias_disambiguates_a_twin_pair(tmp_path: Path) -> None:
    one, two = entry(tmp_path, "twin", name="one"), entry(tmp_path, "twin", name="two")
    assert status("twin", [one, two]) == 409
    root, _ = resolve_exec_board("twin-b", [one, two], {"twin-b": two["root"]})
    assert root == Path(two["root"]).resolve()


def test_alias_over_a_twin_label_also_wins(tmp_path: Path) -> None:
    one, two = entry(tmp_path, "twin", name="one"), entry(tmp_path, "twin", name="two")
    root, _ = resolve_exec_board("twin", [one, two], {"twin": one["root"]})
    assert root == Path(one["root"]).resolve()


@pytest.mark.parametrize("name", ["", "..", "a/b", "a b", "é"])
def test_invalid_alias_name_is_ignored_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, name: str
) -> None:
    e = entry(tmp_path, "alpha")
    caplog.set_level(logging.WARNING)
    assert resolve_exec_board("alpha", [e], {name: e["root"]})[0].name == "alpha"
    assert "not a valid label" in caplog.text


def test_unknown_listing_includes_alias_names(tmp_path: Path) -> None:
    e = entry(tmp_path, "alpha")
    assert "valid: alpha, old" in detail("nope", [e], {"old": e["root"]})


def test_malformed_aliases_value_is_ignored(tmp_path: Path) -> None:
    e = entry(tmp_path, "alpha")
    assert resolve_exec_board("alpha", [e], ["not", "a", "dict"])[0].name == "alpha"  # type: ignore[arg-type]
    assert resolve_exec_board("alpha", [e], {"x": 5})[0].name == "alpha"  # type: ignore[dict-item]


def test_a_board_whose_db_is_gone_is_404_not_a_fresh_board(tmp_path: Path) -> None:
    """A stale discovery entry (board moved into an archive) must not let the
    child create a new board.db at the old path."""
    e = entry(tmp_path, "moved")
    (Path(e["board_dir"]) / "board.db").unlink()
    assert status("moved", [e]) == 404
    assert not (Path(e["board_dir"]) / "board.db").exists()


def test_each_alias_warning_is_logged_once_per_process(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    e = entry(tmp_path, "alpha")
    caplog.set_level(logging.WARNING)
    for _ in range(3):
        resolve_exec_board("alpha", [e], {"ghost": str(tmp_path / "nowhere"), "a b": e["root"]})
    assert caplog.text.count("ghost") == 1 and caplog.text.count("not a valid label") == 1
