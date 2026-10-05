import json
from pathlib import Path

from scripts import chrome_profile


def _write_claude_json(config_dir: Path, oauth: dict | None) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    data = {"oauthAccount": oauth} if oauth is not None else {}
    (config_dir / ".claude.json").write_text(json.dumps(data))


def _write_local_state(path: Path, profiles: dict[str, str]) -> None:
    """`profiles` maps a Chrome profile directory name to its signed-in
    email ("" for a profile that isn't signed in)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    info_cache = {name: {"user_name": email} for name, email in profiles.items()}
    path.write_text(json.dumps({"profile": {"info_cache": info_cache}}))


class TestAccountEmail:
    def test_reads_the_signed_in_email(self, tmp_path):
        config_dir = tmp_path / "config"
        _write_claude_json(config_dir, {"emailAddress": "client-a@example.com"})
        assert chrome_profile.account_email(config_dir) == "client-a@example.com"

    def test_none_when_claude_json_is_missing(self, tmp_path):
        assert chrome_profile.account_email(tmp_path / "no-such-dir") is None

    def test_none_for_an_api_key_session_with_no_oauth_account(self, tmp_path):
        config_dir = tmp_path / "config"
        _write_claude_json(config_dir, None)
        assert chrome_profile.account_email(config_dir) is None

    def test_none_when_claude_json_is_malformed(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / ".claude.json").write_text("not json")
        assert chrome_profile.account_email(config_dir) is None


class TestReadProfiles:
    def test_maps_lowercased_email_to_profile_directory(self, tmp_path):
        local_state = tmp_path / "Local State"
        _write_local_state(local_state, {
            "Default": "Client-A@Example.com",
            "Profile 1": "client-b@example.com",
        })
        assert chrome_profile.read_profiles(local_state) == {
            "client-a@example.com": "Default",
            "client-b@example.com": "Profile 1",
        }

    def test_skips_profiles_with_no_signed_in_email(self, tmp_path):
        local_state = tmp_path / "Local State"
        _write_local_state(local_state, {"Default": ""})
        assert chrome_profile.read_profiles(local_state) == {}

    def test_empty_when_local_state_is_missing(self, tmp_path):
        assert chrome_profile.read_profiles(tmp_path / "no-such-file") == {}

    def test_empty_when_local_state_is_malformed(self, tmp_path):
        local_state = tmp_path / "Local State"
        local_state.parent.mkdir(parents=True, exist_ok=True)
        local_state.write_text("not json")
        assert chrome_profile.read_profiles(local_state) == {}


class TestProfileForEmail:
    def test_matches_case_insensitively(self):
        profiles = {"client-a@example.com": "Profile 1"}
        assert chrome_profile.profile_for_email("Client-A@Example.com", profiles) == "Profile 1"

    def test_none_when_no_profile_is_signed_in_as_that_email(self):
        assert chrome_profile.profile_for_email("nobody@example.com", {}) is None


class TestOpenCommand:
    def test_builds_a_new_window_on_the_named_profile(self):
        assert chrome_profile.open_command("https://claude.ai/x", "Profile 2") == [
            "open", "-na", "Google Chrome", "--args",
            "--profile-directory=Profile 2", "https://claude.ai/x",
        ]
