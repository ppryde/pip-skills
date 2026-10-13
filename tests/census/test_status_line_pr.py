"""The engine's own status-line `pr` is kept apart from `payload`, so a census mod's write does not lose it (WF-269)."""
import json

import pytest

from scripts import store as st


@pytest.fixture
def on_branch(monkeypatch):
    """The git block the ingest sees: `feat/x` unless a test moves it."""
    state = {"branch": "feat/x", "detached": False}

    def fake(_worktree):
        return {**dict(st._NO_GIT), **state}

    monkeypatch.setattr(st, "_git_state", fake)
    return state


def _payload(sid="s1", **extra):
    return json.dumps({"session_id": sid, "cwd": "/wt/a", **extra})


def _entry(sid="s1"):
    return st.read_all()["sessions"][sid]


def test_a_status_line_ingest_records_the_payload_pr_with_its_branch(store_file, on_branch):
    st.ingest(_payload(pr={"number": 12, "url": "https://github.com/o/r/pull/12", "review_state": "approved"}), now=100.0)
    assert _entry()["status_line_pr"] == {
        "number": 12, "branch": "feat/x", "url": "https://github.com/o/r/pull/12", "review_state": "approved", "at": 100.0,
    }


def test_after_a_checkout_the_pr_names_the_new_branch(store_file, on_branch):
    st.ingest(_payload(pr={"number": 12}), now=100.0)
    on_branch["branch"] = "feat/y"
    st.ingest(_payload(pr={"number": 30}), now=200.0)
    assert _entry()["status_line_pr"] == {"number": 30, "branch": "feat/y", "at": 200.0}


def test_no_branch_no_record(store_file, on_branch):
    on_branch["detached"] = True
    st.ingest(_payload(pr={"number": 12}), now=100.0)
    assert "status_line_pr" not in _entry()


def test_a_payload_without_pr_drops_it(store_file, on_branch):
    st.ingest(_payload(pr={"number": 12}), now=100.0)
    st.ingest(_payload(), now=200.0)
    assert "status_line_pr" not in _entry()


def test_a_mod_write_carries_it_forward_untouched(store_file, on_branch):
    st.ingest(_payload(pr={"number": 12, "review_state": "approved"}), now=100.0)
    st.ingest(_payload(census_mod={"event": "turn.complete"}, pr={"number": 99}), now=300.0)
    entry = _entry()
    assert entry["status_line_pr"] == {"number": 12, "branch": "feat/x", "review_state": "approved", "at": 100.0}
    assert entry["payload"]["pr"] == {"number": 99}  # the mod's own word stays in the payload


def test_a_mod_write_with_nothing_to_carry_adds_nothing(store_file, on_branch):
    st.ingest(_payload(census_mod={"event": "x"}, pr={"number": 5}), now=1.0)
    assert "status_line_pr" not in _entry()


def test_malformed_pr_is_ignored(store_file, on_branch):
    for bad in ({"number": True}, {"number": 0}, {"number": "7"}, {"url": "u"}, "7", [7]):
        st.ingest(_payload(pr=bad), now=1.0)
        assert "status_line_pr" not in _entry(), bad
