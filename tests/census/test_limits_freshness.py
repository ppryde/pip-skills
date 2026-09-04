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


class TestHoistOrdering:
    """A dormant session's frozen reading must not clobber a working session's.

    Both sessions' windows reset in the future, so ``resets_at`` gating alone
    cannot separate them. Usage only rises within a window, so the readings
    order themselves — no clock and no write order involved.
    """

    def _rate(self, pct, resets_at=10_000.0):
        return {"five_hour": {"used_percentage": pct, "resets_at": resets_at}}

    def _pct(self, store_file):
        return _read(store_file)["limits"]["five_hour"]["used_percentage"]

    def test_dormant_timer_rerun_does_not_clobber_active_reading(self, store_file):
        dormant = {"prompt_id": "p1", "cost": {"total_cost_usd": 1.0}}
        st.ingest(_payload("dormant", "/wt/a", self._rate(36), **dormant), now=100.0)
        st.ingest(_payload("working", "/wt/b", self._rate(60), prompt_id="w1"), now=200.0)
        # The dormant session's status line reruns on the timer: same frozen
        # 36%, and it writes LAST.
        st.ingest(_payload("dormant", "/wt/a", self._rate(36), **dormant), now=260.0)

        assert self._pct(store_file) == 60

    def test_new_prompt_without_an_api_response_cannot_win(self, store_file):
        """A new prompt id advances session activity, but ``rate_limits`` only
        refreshes on an API response — so the reading is still the old one and
        must not displace a higher figure."""
        st.ingest(_payload("working", "/wt/b", self._rate(60), prompt_id="w1"), now=200.0)
        # Session A: user pressed enter (new prompt id), no API response yet.
        st.ingest(_payload("dormant", "/wt/a", self._rate(20), prompt_id="p2"), now=300.0)

        assert self._pct(store_file) == 60

    def test_dormant_session_that_wakes_up_wins(self, store_file):
        st.ingest(_payload("dormant", "/wt/a", self._rate(36), prompt_id="p1"), now=100.0)
        st.ingest(_payload("working", "/wt/b", self._rate(60), prompt_id="w1"), now=200.0)
        # Its counters moved AND its reading rose past the stored figure.
        st.ingest(_payload("dormant", "/wt/a", self._rate(71), prompt_id="p2"), now=300.0)

        assert self._pct(store_file) == 71

    def test_write_order_does_not_matter(self, store_file):
        st.ingest(_payload("working", "/wt/b", self._rate(60), prompt_id="w1"), now=200.0)
        st.ingest(_payload("dormant", "/wt/a", self._rate(36), prompt_id="p1"), now=100.0)
        assert self._pct(store_file) == 60

    def test_a_new_window_wins_however_low_its_percentage(self, store_file):
        st.ingest(_payload("s1", "/wt/a", self._rate(96, resets_at=10_000.0)), now=100.0)
        # The window rolled over: counter restarted, reset time moved out.
        st.ingest(_payload("s2", "/wt/b", self._rate(3, resets_at=28_000.0)), now=110.0)
        limits = _read(store_file)["limits"]["five_hour"]
        assert limits["used_percentage"] == 3
        assert limits["resets_at"] == 28_000.0

    def test_a_superseded_window_loses_however_high_its_percentage(self, store_file):
        st.ingest(_payload("s1", "/wt/a", self._rate(3, resets_at=28_000.0)), now=100.0)
        st.ingest(_payload("s2", "/wt/b", self._rate(96, resets_at=10_000.0)), now=110.0)
        assert self._pct(store_file) == 3

    def test_a_forward_clock_step_cannot_wedge_a_window(self, store_file):
        """A reading written while the clock was hours fast must not lock the
        window until wall clock catches up — the ordering ignores clocks."""
        st.ingest(_payload("skewed", "/wt/a", self._rate(11)), now=100.0 + 7200)
        st.ingest(_payload("normal", "/wt/b", self._rate(88)), now=200.0)
        assert self._pct(store_file) == 88

    def test_nan_percentage_cannot_wedge_a_window(self, store_file):
        """json round-trips a bare NaN, and every comparison against it is
        false — it must never become an unbeatable stored reading."""
        store_file.parent.mkdir(parents=True, exist_ok=True)
        store_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "limits": {
                        "five_hour": {"used_percentage": float("nan"), "resets_at": 10_000.0},
                        "updated_at": 50.0,
                    },
                    "sessions": {},
                }
            )
        )
        st.ingest(_payload("s1", "/wt/a", self._rate(44)), now=100.0)
        assert self._pct(store_file) == 44

    def test_reading_without_a_percentage_never_displaces_a_real_one(self, store_file):
        st.ingest(_payload("s1", "/wt/a", self._rate(44)), now=100.0)
        st.ingest(
            _payload("s2", "/wt/b", {"five_hour": {"resets_at": 10_000.0}}),
            now=110.0,
        )
        assert self._pct(store_file) == 44

    def test_each_window_is_ordered_independently(self, store_file):
        """Per-window, not one global decision: a losing five_hour reading must
        not drag its own seven_day reading down with it, or vice versa."""
        st.ingest(
            _payload(
                "s1",
                "/wt/a",
                {
                    "five_hour": {"used_percentage": 80, "resets_at": 10_000.0},
                    "seven_day": {"used_percentage": 12, "resets_at": 90_000.0},
                },
            ),
            now=100.0,
        )
        st.ingest(
            _payload(
                "s2",
                "/wt/b",
                {
                    "five_hour": {"used_percentage": 30, "resets_at": 10_000.0},
                    "seven_day": {"used_percentage": 44, "resets_at": 90_000.0},
                },
            ),
            now=110.0,
        )
        limits = _read(store_file)["limits"]
        assert limits["five_hour"]["used_percentage"] == 80  # first reading held
        assert limits["seven_day"]["used_percentage"] == 44  # second reading won

    def test_an_expired_window_is_dropped_not_carried(self, store_file):
        """Once a window's reset time has passed, its reading must not survive
        as a fossil that a genuine new reading has to out-rank."""
        st.ingest(_payload("s1", "/wt/a", self._rate(96, resets_at=10_000.0)), now=100.0)
        # Now past that reset. The next reading belongs to a fresh window and
        # must be taken despite being far lower.
        st.ingest(
            _payload("s2", "/wt/b", self._rate(4, resets_at=28_000.0)),
            now=10_500.0,
        )
        limits = _read(store_file)["limits"]
        assert limits["five_hour"]["used_percentage"] == 4
        assert st.limits(now=10_500.0)["five_hour"]["used_percentage"] == 4

    def test_pre_upgrade_limits_are_ordered_not_trusted(self, store_file):
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
        st.ingest(_payload("s1", "/wt/a", self._rate(44)), now=100.0)
        assert self._pct(store_file) == 44
