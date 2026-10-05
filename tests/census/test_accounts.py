"""Limits are keyed by Claude account, not by folder (spec amendment 2026-10-06)."""
import hashlib
import json
import time

import pytest
from scripts import cli
from scripts import store as st


def _login(monkeypatch, tmp_path, name, oauth=None, raw=None):
    """Point CLAUDE_CONFIG_DIR at tmp_path/name and write a fake .claude.json there."""
    cfg = tmp_path / name
    cfg.mkdir(exist_ok=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    if raw is not None:
        (cfg / ".claude.json").write_text(raw)
    elif oauth is not None:
        (cfg / ".claude.json").write_text(json.dumps({"oauthAccount": oauth}))
    st.reset_account_cache()
    return cfg


def _acct(uuid, org="org-1"):
    return {"accountUuid": uuid, "organizationUuid": org,
            "organizationName": f"{org} name", "billingType": "stripe_subscription"}


def _ingest(sid, rate_limits, now=None):
    payload = {"session_id": sid, "cwd": "/wt/a", "rate_limits": rate_limits}
    st.ingest(json.dumps(payload), now=now)


def _win(pct, offset=3600):
    return {"used_percentage": pct, "resets_at": time.time() + offset}


@pytest.fixture
def shared(tmp_path, monkeypatch):
    monkeypatch.setenv("CENSUS_STORE", str(tmp_path / "shared"))
    return tmp_path


def _read(capsys, *argv):
    cli.main(["read", *argv])
    return json.loads(capsys.readouterr().out)


def test_two_accounts_share_one_folder_without_mixing(shared, monkeypatch, capsys):
    _login(monkeypatch, shared, "cfg-a", _acct("uuid-a", "org-a"))
    _ingest("s1", {"five_hour": _win(10), "seven_day": _win(20, 86400)})
    _login(monkeypatch, shared, "cfg-b", _acct("uuid-b", "org-b"))
    _ingest("s2", {"five_hour": _win(70), "seven_day": _win(80, 86400)})
    files = sorted(p.name for p in (shared / "shared" / "limits").iterdir())
    assert files == ["uuid-a.json", "uuid-b.json"]
    mine = _read(capsys, "--limits")
    assert mine["five_hour"]["used_percentage"] == 70
    _login(monkeypatch, shared, "cfg-a")
    assert _read(capsys, "--limits")["five_hour"]["used_percentage"] == 10
    assert _read(capsys)["limits"]["five_hour"]["used_percentage"] == 10
    both = _read(capsys, "--limits", "--all")
    assert set(both) == {"uuid-a", "uuid-b"}
    assert both["uuid-a"]["org"] == "org-a"
    assert both["uuid-b"]["billing"] == "stripe_subscription"
    assert both["uuid-b"]["five_hour"]["used_percentage"] == 70
    assert "version" not in both["uuid-a"]


def test_all_requires_limits(capsys):
    assert cli.main(["read", "--all"]) != 0


def test_no_oauth_account_uses_cfg_key_stable_and_per_dir(shared, monkeypatch):
    cfg = _login(monkeypatch, shared, "cfg-a", {"emailAddress": "x"})
    want = "cfg-" + hashlib.sha256(str(cfg.resolve()).encode()).hexdigest()[:12]
    assert st.account_info()["key"] == want
    assert st.account_info()["key"] == want
    _login(monkeypatch, shared, "cfg-b")
    assert st.account_info()["key"] != want
    assert st.account_info()["key"].startswith("cfg-")


@pytest.mark.parametrize("raw", ["{not json", "[]", '{"oauthAccount": "x"}'])
def test_bad_claude_json_falls_back_and_ingest_works(shared, monkeypatch, raw):
    _login(monkeypatch, shared, "cfg-a", raw=raw)
    _ingest("s1", {"five_hour": _win(10)})
    key = st.account_info()["key"]
    assert key.startswith("cfg-")
    assert (shared / "shared" / "limits" / f"{key}.json").exists()


def test_missing_claude_json_falls_back(shared, monkeypatch):
    _login(monkeypatch, shared, "cfg-a")
    assert st.account_info()["key"].startswith("cfg-")


@pytest.mark.parametrize("bad", ["../x", "a/b", "", ".hidden", "x" * 200])
def test_unsafe_account_uuid_falls_back(shared, monkeypatch, bad):
    _login(monkeypatch, shared, "cfg-a", {"accountUuid": bad})
    assert st.account_info()["key"].startswith("cfg-")


def test_new_window_name_merges_forward_only(shared, monkeypatch, capsys):
    _login(monkeypatch, shared, "cfg-a", _acct("uuid-a"))
    reset = time.time() + 3600
    _ingest("s1", {"spend_limit": {"used_percentage": 40, "resets_at": reset}})
    _ingest("s2", {"spend_limit": {"used_percentage": 10, "resets_at": reset}})
    assert _read(capsys, "--limits")["spend_limit"]["used_percentage"] == 40
    _ingest("s3", {"spend_limit": {"used_percentage": 55, "resets_at": reset}})
    assert _read(capsys, "--limits")["spend_limit"]["used_percentage"] == 55


def test_unknown_shape_stored_verbatim(shared, monkeypatch, capsys):
    _login(monkeypatch, shared, "cfg-a", _acct("uuid-a"))
    _ingest("s1", {"weird": {"used_usd": 3}})
    assert _read(capsys)["limits"]["weird"] == {"used_usd": 3}
    _ingest("s1", {"weird": {"used_usd": 1}})
    assert _read(capsys)["limits"]["weird"] == {"used_usd": 1}
    assert _read(capsys, "--limits")["weird"] == {"used_usd": 1}


def test_session_entries_carry_account_and_org(shared, monkeypatch, capsys):
    _login(monkeypatch, shared, "cfg-a", _acct("uuid-a", "org-a"))
    _ingest("s1", {"five_hour": _win(10)})
    session = _read(capsys, "--session", "s1")
    assert session["account"] == "uuid-a"
    assert session["org"] == "org-a"
    assert _read(capsys)["sessions"]["s1"]["account"] == "uuid-a"


def test_v2_limits_json_migrates_into_account_file(shared, monkeypatch, capsys):
    _login(monkeypatch, shared, "cfg-a", _acct("uuid-a", "org-a"))
    folder = shared / "shared"
    folder.mkdir()
    reset = time.time() + 3600
    (folder / "limits.json").write_text(json.dumps(
        {"version": 2, "five_hour": {"used_percentage": 33, "resets_at": reset}, "updated_at": 1}))
    assert _read(capsys, "--limits")["five_hour"]["used_percentage"] == 33
    assert not (folder / "limits.json").exists()
    body = json.loads((folder / "limits" / "uuid-a.json").read_text())
    assert body["account"] == "uuid-a" and body["org"] == "org-a"
    # forward-only merge into an existing account file: a lower reading never wins
    (folder / "limits.json").write_text(json.dumps(
        {"version": 2, "five_hour": {"used_percentage": 5, "resets_at": reset}, "updated_at": 1}))
    assert _read(capsys, "--limits")["five_hour"]["used_percentage"] == 33
    assert not (folder / "limits.json").exists()


def test_v1_status_json_limits_land_in_calling_account(shared, monkeypatch, capsys):
    _login(monkeypatch, shared, "cfg-a", _acct("uuid-a"))
    folder = shared / "shared"
    folder.mkdir()
    reset = time.time() + 3600
    (folder / "status.json").write_text(json.dumps({
        "version": 1, "sessions": {},
        "limits": {"five_hour": {"used_percentage": 21, "resets_at": reset}, "updated_at": 1}}))
    assert _read(capsys, "--limits")["five_hour"]["used_percentage"] == 21
    assert (folder / "limits" / "uuid-a.json").exists()


def test_purge_removes_limits_dir(shared, monkeypatch):
    from scripts import install
    _login(monkeypatch, shared, "cfg-a", _acct("uuid-a"))
    _ingest("s1", {"five_hour": _win(10)})
    folder = shared / "shared"
    (folder / "limits.json").write_text("{}")
    assert (folder / "limits").is_dir()
    install._purge(folder, True)
    assert not (folder / "limits").exists()
    assert not (folder / "limits.json").exists()
