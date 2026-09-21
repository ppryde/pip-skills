"""Open a link in the Chrome profile signed in as a given Claude account.

For multi-account work (a contracting setup with one ``CLAUDE_CONFIG_DIR`` per
client): an artifact link only works in the browser identity that created it,
and today that means hunting through Chrome windows by hand. This reads the
email straight from the ACTIVE config dir — the same one the session printing
the link is already running under — and matches it against Chrome's own
signed-in profiles.

Deliberately separate from ``store.account_profile``: that function is a
whitelist by design, because its output is stamped onto rows in a store that
is copied around (see its docstring). ``emailAddress`` never enters that
whitelist, and does not enter this module's return values into any store
either — it is read fresh on every call and used only to pick a profile
directory, never persisted.

macOS only: both ``open --args --profile-directory`` and Chrome's
``Local State`` layout are Chrome-on-macOS specifics.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_LOCAL_STATE = Path.home() / "Library/Application Support/Google/Chrome/Local State"


def account_email(config_dir: Path) -> str | None:
    """The email signed into ``<config_dir>/.claude.json``'s ``oauthAccount``,
    or None (no file, unreadable, malformed, or an API-key session with no
    ``oauthAccount`` at all)."""
    try:
        data = json.loads((config_dir / ".claude.json").read_text() or "{}")
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    oauth = data.get("oauthAccount")
    if not isinstance(oauth, dict):
        return None
    email = oauth.get("emailAddress")
    return email if isinstance(email, str) and email else None


def read_profiles(local_state_path: Path) -> dict[str, str]:
    """Every Chrome profile that is signed in, as ``{lowercased email:
    profile directory name}`` — ``"Default"``, ``"Profile 1"``, etc, exactly
    as ``--profile-directory`` expects them. A profile with no signed-in
    account (``user_name`` empty or absent) is left out: there is nothing to
    match it against. Missing/malformed ``Local State`` reads as no profiles,
    not an error — the caller reports that as "no match" either way."""
    try:
        data = json.loads(local_state_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    info_cache = data.get("profile", {}).get("info_cache", {})
    if not isinstance(info_cache, dict):
        return {}
    out: dict[str, str] = {}
    for profile_dir, info in info_cache.items():
        if not isinstance(info, dict):
            continue
        email = info.get("user_name")
        if isinstance(email, str) and email:
            out[email.lower()] = profile_dir
    return out


def profile_for_email(email: str, profiles: dict[str, str]) -> str | None:
    """The profile directory signed in as `email`, or None."""
    return profiles.get(email.lower())


def open_command(url: str, profile_dir: str) -> list[str]:
    """The ``open`` argv that launches a NEW Chrome window on `profile_dir`
    showing `url` — ``-na`` so it never reuses whatever window already has
    focus (the common bug this whole thing exists to avoid)."""
    return ["open", "-na", "Google Chrome", "--args", f"--profile-directory={profile_dir}", url]
