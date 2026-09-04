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


class TestActivityGatedHoist:
    """A dormant session's frozen reading must not clobber a working session's.

    Both sessions' windows reset in the future, so ``resets_at`` gating alone
    cannot separate them — only the source's ``active_at`` can.
    """

    def _rate(self, pct, resets_at=10_000.0):
        return {"five_hour": {"used_percentage": pct, "resets_at": resets_at}}

    def test_dormant_timer_rerun_does_not_clobber_active_reading(self, store_file):
        # A dormant session establishes itself, then goes quiet.
        dormant = {"prompt_id": "p1", "cost": {"total_cost_usd": 1.0}}
        st.ingest(_payload("dormant", "/wt/a", self._rate(36), **dormant), now=100.0)
        # A working session posts a fresher account figure.
        st.ingest(_payload("working", "/wt/b", self._rate(60), prompt_id="w1"), now=200.0)
        # The dormant session's status line reruns on the timer: same counters,
        # same frozen 36% — and it writes LAST.
        st.ingest(_payload("dormant", "/wt/a", self._rate(36), **dormant), now=260.0)

        assert _read(store_file)["limits"]["five_hour"]["used_percentage"] == 60

    def test_dormant_session_that_wakes_up_wins(self, store_file):
        dormant = {"prompt_id": "p1", "cost": {"total_cost_usd": 1.0}}
        st.ingest(_payload("dormant", "/wt/a", self._rate(36), **dormant), now=100.0)
        st.ingest(_payload("working", "/wt/b", self._rate(60), prompt_id="w1"), now=200.0)
        # Same session, but its counters moved — a real API call, so its reading
        # is now the freshest one there is.
        awake = {"prompt_id": "p2", "cost": {"total_cost_usd": 2.0}}
        st.ingest(_payload("dormant", "/wt/a", self._rate(71), **awake), now=300.0)

        assert _read(store_file)["limits"]["five_hour"]["used_percentage"] == 71

    def test_sources_recorded_per_window(self, store_file):
        st.ingest(_payload("s1", "/wt/a", self._rate(20), prompt_id="p1"), now=100.0)
        limits = _read(store_file)["limits"]
        assert limits["sources"]["five_hour"] == 100.0

    def test_pre_upgrade_limits_without_sources_are_replaced(self, store_file):
        store_file.parent.mkdir(parents=True, exist_ok=True)
        store_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "limits": {**self._rate(9), "updated_at": 50.0},
                    "sessions": {},
                }
            )
        )
        st.ingest(_payload("s1", "/wt/a", self._rate(44), prompt_id="p1"), now=100.0)
        assert _read(store_file)["limits"]["five_hour"]["used_percentage"] == 44

    def test_readers_never_see_the_sources_bookkeeping(self, store_file):
        st.ingest(_payload("s1", "/wt/a", self._rate(20), prompt_id="p1"), now=100.0)
        assert "sources" not in (st.limits(now=100.0) or {})
        entry = st.for_session("s1", now=100.0)
        assert "sources" not in (entry["limits"] or {})
