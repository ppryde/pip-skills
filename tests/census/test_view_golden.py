import json

from scripts import cli
from scripts import store as st

NOW = 1_000.0
V1 = {
    "version": 1,
    "limits": {"five_hour": {"used_percentage": 30, "resets_at": 5_000},
               "seven_day": {"used_percentage": 12, "resets_at": 90_000}, "updated_at": 900},
    "sessions": {
        "a": {"worktree_cwd": "/wt/x", "updated_at": 990.0, "active_at": 700.0,
              "branch": "main", "tmux_pane": "%3", "payload": {"session_id": "a", "cwd": "/wt/x"}},
        "b": {"worktree_cwd": "/wt/x", "updated_at": 800.0, "active_at": 950.0,
              "branch": None, "payload": {"session_id": "b", "cwd": "/wt/x"}},
        "c": {"worktree_cwd": "/wt/y", "updated_at": 100.0, "active_at": 50.0,
              "branch": "old", "payload": {"session_id": "c", "cwd": "/wt/y"}},
    },
}


def _cli(capsys, *argv):
    cli.main(["read", *argv])
    return json.loads(capsys.readouterr().out)


def test_read_forms_match_v1(store_file, capsys, monkeypatch):
    monkeypatch.setattr(st.time, "time", lambda: NOW)
    store_file.parent.mkdir(parents=True, exist_ok=True)
    store_file.write_text(json.dumps(V1))
    assert _cli(capsys) == V1
    assert not store_file.exists()
    assert st.session_path("a").exists()
    live = {k: V1["limits"][k] for k in ("five_hour", "seven_day")}
    assert _cli(capsys, "--limits") == live
    session = _cli(capsys, "--session", "a")
    assert session == {**V1["sessions"]["a"], "stale": False, "idle": False, "limits": live}
    # b has the lower updated_at but the higher active_at: activity ranks first
    assert _cli(capsys, "--worktree", "/wt/x") == {
        **V1["sessions"]["b"], "stale": True, "idle": False, "limits": live}
    # c is past both horizons
    assert _cli(capsys, "--session", "c") == {
        **V1["sessions"]["c"], "stale": True, "idle": True, "limits": live}
    assert _cli(capsys, "--session", "missing") == {}
