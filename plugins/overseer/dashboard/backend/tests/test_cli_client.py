from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.cli_client import CliError, check_id, run_overseer, watched_account_profiles


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    run_overseer(tmp_path, "init")
    return tmp_path


def test_board_round_trips_new_card(root: Path) -> None:
    out = run_overseer(root, "new-card", "--title", "Widget thing", "--complexity", "S")
    card_id = out.strip()

    board = run_overseer(root, "board", "--json", json_out=True)

    assert isinstance(board, dict)
    ids = [c["id"] for c in board["cards"]]
    assert card_id in ids


def test_bad_verb_raises_cli_error(root: Path) -> None:
    with pytest.raises(CliError) as exc_info:
        run_overseer(root, "not-a-real-verb")
    assert exc_info.value.returncode != 0
    assert exc_info.value.stderr


def test_unknown_id_raises_cli_error_with_stderr(root: Path) -> None:
    with pytest.raises(CliError) as exc_info:
        run_overseer(root, "show", "NOPE-999", "--json", json_out=True)
    assert exc_info.value.returncode == 1
    assert "no card with id" in exc_info.value.stderr


def test_check_id_accepts_safe_ids() -> None:
    check_id("ABC-123")
    check_id("abc_123")


@pytest.mark.parametrize(
    "bad_id",
    [
        "a; rm -rf /",
        "../etc/passwd",
        "a/b",
        "a\\b",
        "a*b",
        "a?b",
        "a[b]",
        "a b",
        "--json",
        "-x",
    ],
)
def test_check_id_rejects_metacharacters(bad_id: str) -> None:
    with pytest.raises(CliError) as exc_info:
        check_id(bad_id)
    assert exc_info.value.returncode == 2
    assert exc_info.value.stderr == "invalid card id"


class TestWatchedAccountProfiles:
    """WF-116: `watched_account_profiles` is the ONLY place this backend
    reads a config dir's live login — used both by `/api/accounts` (which
    dirs are logged into which uuid) and by `/api/sessions`'s account
    filter. Every case here uses obviously-fake uuids/plans, never real
    ones (public repo)."""

    def _write_claude_json(self, config_dir: Path, oauth: dict[str, str] | None) -> None:
        config_dir.mkdir(parents=True, exist_ok=True)
        body: dict[str, object] = {"emailAddress": "should-never-be-read@example.invalid"}
        if oauth is not None:
            body["oauthAccount"] = oauth
        (config_dir / ".claude.json").write_text(json.dumps(body))

    def test_reads_uuid_and_plan_whitelisted_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_dir = tmp_path / "claude"
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
        self._write_claude_json(config_dir, {
            "accountUuid": "11111111-aaaa-bbbb-cccc-000000000001",
            "organizationType": "claude_max",
            "emailAddress": "person@example.invalid",
            "fullName": "A Real Name",
        })

        profiles = watched_account_profiles()

        assert len(profiles) == 1
        found_dir, profile = profiles[0]
        assert found_dir == config_dir
        assert profile == {
            "account_uuid": "11111111-aaaa-bbbb-cccc-000000000001",
            "plan": "claude_max",
        }
        # No personal field ever leaks, whitelist or not.
        assert "emailAddress" not in profile and "fullName" not in profile

    def test_api_key_session_has_no_oauth_account(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_dir = tmp_path / "claude"
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
        self._write_claude_json(config_dir, None)

        assert watched_account_profiles() == []

    def test_missing_config_file_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_dir = tmp_path / "claude-never-written"
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
        config_dir.mkdir(parents=True)

        assert watched_account_profiles() == []

    def test_every_watched_dir_is_consulted_ignoring_census_store(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unlike census's `_watched_dirs`, account identity is read
        regardless of `CENSUS_STORE` — that pin is about which census store
        a test targets, not about how many accounts exist on the machine."""
        primary = tmp_path / "claude"
        personal = tmp_path / "claude-personal"
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(primary))
        monkeypatch.setenv("CENSUS_STORE", str(tmp_path / "pinned-store.json"))
        self._write_claude_json(primary, {"accountUuid": "work-uuid-0000"})
        self._write_claude_json(personal, {"accountUuid": "home-uuid-0000"})
        (primary / "overseer").mkdir(parents=True, exist_ok=True)
        (primary / "overseer" / "config.json").write_text(
            json.dumps({"claude_dirs": [str(personal)]})
        )

        profiles = watched_account_profiles()

        assert [(str(d), p["account_uuid"]) for d, p in profiles] == [
            (str(primary), "work-uuid-0000"),
            (str(personal), "home-uuid-0000"),
        ]
