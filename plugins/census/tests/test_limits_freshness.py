"""Rate-limit windows are gated on a FUTURE resets_at.

A window whose reset time is in the past is a fossil — typically a dormant
session whose status line still writes but whose last API response (and thus its
rate_limits) is days old. Such readings must neither be hoisted nor served, or
the account-global figure flip-flops to whoever wrote the store last.
"""
import json

from scripts import store as st


def _payload(sid, cwd, rate, **extra):
    base = {"session_id": sid, "cwd": cwd, "rate_limits": rate}
    base.update(extra)
    return json.dumps(base)


def _read(store_file):
    return json.loads(store_file.read_text())


NOW = 1000.0
FUTURE = NOW + 5000  # resets_at in the future -> live
PAST = NOW - 5000    # resets_at in the past -> expired/stale


class TestHoistGate:
    def test_live_window_is_hoisted(self, store_file):
        rate = {"five_hour": {"used_percentage": 89, "resets_at": FUTURE}}
        st.ingest(_payload("s1", "/wt/a", rate), now=NOW)
        assert _read(store_file)["limits"]["five_hour"]["used_percentage"] == 89

    def test_expired_window_is_not_hoisted(self, store_file):
        rate = {"five_hour": {"used_percentage": 105, "resets_at": PAST}}
        st.ingest(_payload("s1", "/wt/a", rate), now=NOW)
        assert _read(store_file).get("limits") in (None, {})

    def test_missing_resets_at_is_not_hoisted(self, store_file):
        rate = {"five_hour": {"used_percentage": 42}}  # no resets_at
        st.ingest(_payload("s1", "/wt/a", rate), now=NOW)
        assert _read(store_file).get("limits") in (None, {})

    def test_per_window_gating(self, store_file):
        rate = {
            "five_hour": {"used_percentage": 105, "resets_at": PAST},   # expired
            "seven_day": {"used_percentage": 41, "resets_at": FUTURE},  # live
        }
        st.ingest(_payload("s1", "/wt/a", rate), now=NOW)
        limits = _read(store_file)["limits"]
        assert "five_hour" not in limits
        assert limits["seven_day"]["used_percentage"] == 41

    def test_stale_write_does_not_clobber_live_reading(self, store_file):
        """The ledger-poc scenario: a dormant session writing an old reading must
        not overwrite the current account figure a live session established."""
        live = {"five_hour": {"used_percentage": 89, "resets_at": FUTURE}}
        st.ingest(_payload("live", "/wt/a", live), now=NOW)
        # a dormant session writes a fresh entry carrying a 3-day-old reading
        stale = {"five_hour": {"used_percentage": 105, "resets_at": PAST}}
        st.ingest(_payload("dormant", "/wt/b", stale), now=NOW + 10)
        assert _read(store_file)["limits"]["five_hour"]["used_percentage"] == 89


class TestReadGate:
    def test_limits_reader_drops_expired_window(self, store_file):
        # write a live window, then read at a time AFTER it has reset
        rate = {"five_hour": {"used_percentage": 89, "resets_at": FUTURE}}
        st.ingest(_payload("s1", "/wt/a", rate), now=NOW)
        assert st.limits(now=NOW)["five_hour"]["used_percentage"] == 89
        # now is past the window's reset -> reader returns None (no live windows)
        assert st.limits(now=FUTURE + 1) is None

    def test_latest_for_worktree_limits_are_gated(self, store_file):
        rate = {"five_hour": {"used_percentage": 89, "resets_at": FUTURE}}
        st.ingest(_payload("s1", "/wt/a", rate), now=NOW)
        assert st.latest_for_worktree("/wt/a", now=NOW)["limits"]["five_hour"]["used_percentage"] == 89
        # after the window resets, the merged limits drop it
        assert st.latest_for_worktree("/wt/a", now=FUTURE + 1)["limits"] is None
