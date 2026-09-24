"""Report-side per-turn account attribution (WF-118): a turn counts toward
the account whose bridge owned it (`COALESCE(t.account_uuid, s.account_uuid)`),
so a session that moved between accounts splits its cost and tokens.
"""
import time
from pathlib import Path

from scripts import ingest, report, store

from .conftest import TranscriptBuilder
from .test_turn_account import T0, T1, _bridge

# A = the config dir's account (sessions.account_uuid), B = a second account the
# session was bridged to. Three sessions:
#   mixed    A-config; turns before any bridge -> A (fallback), then bridged to B
#   all-b    A-config, but every turn written under a B bridge
#   plain    A-config, never bridged
# Every turn costs the same (conftest's default usage), so cost splits by count.

def _seed_accounts(projects, tmp_path):
    (TranscriptBuilder(projects, "-a", "mixed")
     .turn("x1", T0).turn("x2", T0)
     .raw(_bridge("acc-B", "mixed"))
     .turn("x3", T1).turn("x4", T1).turn("x5", T1).write())
    (TranscriptBuilder(projects, "-a", "all-b")
     .raw(_bridge("acc-B", "all-b"))
     .turn("y1", T1).turn("y2", T1).write())
    TranscriptBuilder(projects, "-a", "plain").turn("z1", T1).write()
    conn = store.connect()
    ingest.sync(conn, projects)
    conn.execute("UPDATE sessions SET account_uuid = 'acc-A'")
    conn.commit()
    return conn


def _money(out: dict) -> float:
    return out["totals"]["cost_usd"]


class TestReportsSplitByTurn:
    def test_per_account_sums_add_up_to_the_unfiltered_total(self, projects, tmp_path):
        conn = _seed_accounts(projects, tmp_path)
        whole = report.summary(conn)
        a = report.summary(conn, account="acc-A")
        b = report.summary(conn, account="acc-B")
        for key in ("turns", "input_tokens", "cache_read_tokens", "cache_creation_tokens",
                    "output_tokens", "thinking_tokens", "cold_turns", "tool_calls"):
            assert a["totals"][key] + b["totals"][key] == whole["totals"][key], key
        assert round(_money(a) + _money(b), 6) == round(_money(whole), 6)
        # mixed: 2 A-turns (before the bridge) + plain's 1 = 3; B: 3 + 2 = 5.
        assert (a["totals"]["turns"], b["totals"]["turns"]) == (3, 5)

    def test_by_day_and_by_model_count_only_that_accounts_turns(self, projects, tmp_path):
        conn = _seed_accounts(projects, tmp_path)
        for account, turns in (("acc-A", 3), ("acc-B", 5)):
            out = report.summary(conn, account=account)
            assert sum(d["turns"] for d in out["by_day"]) == turns
            assert sum(m["turns"] for m in out["by_model"]) == turns
            assert round(sum(d["cost_usd"] for d in out["by_day"]), 6) == round(_money(out), 6)

    def test_a_mixed_session_appears_under_both_accounts(self, projects, tmp_path):
        conn = _seed_accounts(projects, tmp_path)
        ids_a = {r["session_id"] for r in report.sessions(conn, account="acc-A")}
        ids_b = {r["session_id"] for r in report.sessions(conn, account="acc-B")}
        assert ids_a == {"mixed", "plain"}
        assert ids_b == {"mixed", "all-b"}

    def test_a_fully_bridged_session_moves_entirely_to_the_bridge_account(
            self, projects, tmp_path):
        conn = _seed_accounts(projects, tmp_path)
        assert "all-b" not in {r["session_id"] for r in report.sessions(conn, account="acc-A")}
        row = next(r for r in report.sessions(conn, account="acc-B") if r["session_id"] == "all-b")
        assert row["turns"] == 2
        assert row["cost_usd"] > 0

    def test_session_rows_carry_only_the_accounts_own_tokens_and_cost(self, projects, tmp_path):
        conn = _seed_accounts(projects, tmp_path)
        by_id = {r["session_id"]: r for r in report.sessions(conn)}
        a = next(r for r in report.sessions(conn, account="acc-A") if r["session_id"] == "mixed")
        b = next(r for r in report.sessions(conn, account="acc-B") if r["session_id"] == "mixed")
        mixed = by_id["mixed"]
        assert (a["turns"], b["turns"]) == (2, 3)
        assert a["output_tokens"] + b["output_tokens"] == mixed["output_tokens"]
        assert a["context_tokens"] + b["context_tokens"] == mixed["context_tokens"]
        assert round(a["cost_usd"] + b["cost_usd"], 6) == round(mixed["cost_usd"], 6)

    def test_the_attribution_block_counts_only_the_accounts_turns(self, projects, tmp_path):
        conn = _seed_accounts(projects, tmp_path)
        assert report.summary(conn, account="acc-A")["attribution"]["turns"] == 3
        assert report.summary(conn, account="acc-B")["attribution"]["turns"] == 5

    def test_accounts_lists_a_mixed_session_under_every_owner(self, projects, tmp_path):
        conn = _seed_accounts(projects, tmp_path)
        counts = {r["account_uuid"]: r["sessions"] for r in report.accounts(conn)}
        assert counts == {"acc-A": 2, "acc-B": 2}

    def test_a_bridge_only_account_is_listed_even_though_no_config_dir_is_it(
            self, projects, tmp_path):
        conn = _seed_accounts(projects, tmp_path)
        assert "acc-B" in {r["account_uuid"] for r in report.accounts(conn)}

    def test_a_session_with_no_turns_still_belongs_to_its_config_dir_account(
            self, projects, tmp_path):
        conn = _seed_accounts(projects, tmp_path)
        conn.execute("INSERT INTO sessions(session_id, account_uuid, updated_at) "
                     "VALUES ('empty', 'acc-A', 0)")
        conn.commit()
        assert "empty" in {r["session_id"] for r in report.sessions(conn, account="acc-A")}
        counts = {r["account_uuid"]: r["sessions"] for r in report.accounts(conn)}
        assert counts["acc-A"] == 3

    def test_no_account_filter_is_untouched_by_the_stamps(self, projects, tmp_path):
        conn = _seed_accounts(projects, tmp_path)
        def read():
            rows = report.sessions(conn)
            for row in rows:
                row.pop("bridge_owner_uuid")   # the new column itself, by definition
            return report.summary(conn), rows

        stamped = read()
        conn.execute("UPDATE turns SET account_uuid = NULL")
        conn.execute("UPDATE sessions SET bridge_owner_uuid = NULL")
        conn.commit()
        assert stamped == read()

    def test_with_no_stamps_an_account_filter_is_the_old_session_level_read(
            self, projects, tmp_path):
        conn = _seed_accounts(projects, tmp_path)
        conn.execute("UPDATE turns SET account_uuid = NULL")
        conn.commit()
        whole = report.summary(conn)
        a = report.summary(conn, account="acc-A")
        assert a["totals"] == whole["totals"] | {"cache_hit_rate": a["totals"]["cache_hit_rate"]}
        assert report.summary(conn, account="acc-B")["totals"]["sessions"] == 0

    def test_a_store_lacking_the_new_columns_still_reads(self, projects, tmp_path):
        # The report verbs open the store READ-ONLY, before `_migrate` can add
        # a column — so an upgraded-but-unsynced store lacks both.
        conn = _seed_accounts(projects, tmp_path)
        whole = report.summary(conn)
        conn.execute("ALTER TABLE turns DROP COLUMN account_uuid")
        conn.execute("ALTER TABLE sessions DROP COLUMN bridge_owner_uuid")
        conn.commit()
        assert report.summary(conn) == whole
        a = report.summary(conn, account="acc-A")     # falls back to session-level
        assert a["totals"]["sessions"] == 3
        assert report.summary(conn, account="acc-B")["totals"]["sessions"] == 0
        assert {r["account_uuid"] for r in report.accounts(conn)} == {"acc-A"}
        assert report.sessions(conn, account="acc-A")
        assert report.limits(conn, account="acc-A")["events"] == []


class TestLimitAccounting:
    def test_session_windows_follow_the_turns_effective_account(self, projects, tmp_path):
        conn = _seed_accounts(projects, tmp_path)
        b = report._session_windows(conn, "acc-B")
        a = report._session_windows(conn, "acc-A")
        # B's first window opens on its first BRIDGED turn (T1), not on the
        # session's earlier config-dir-account turns at T0.
        assert b[0][0] == report.transcript.parse_ts(T1)
        assert a[0][0] == report.transcript.parse_ts(T0)

    def test_tokens_in_a_window_are_summed_per_effective_account(self, projects, tmp_path):
        conn = _seed_accounts(projects, tmp_path)
        lo = report.transcript.parse_ts(T0) - 1
        hi = report.transcript.parse_ts(T1) + 1
        a = report._sum_account_tokens(conn, "acc-A", lo, hi)
        b = report._sum_account_tokens(conn, "acc-B", lo, hi)
        assert a["output_tokens"] == 3 * 40
        assert b["output_tokens"] == 5 * 40


    def test_a_limit_hit_belongs_to_the_account_the_session_was_on_when_it_landed(
            self, projects):
        (TranscriptBuilder(projects, "-a", "s1")
         .turn("m1", T0).limit_hit("h1", T0, "You've hit your session limit")
         .raw(_bridge("acc-B", "s1"))
         .turn("m2", T1).limit_hit("h2", T1, "You've hit your weekly limit")
         .write())
        conn = store.connect()
        ingest.sync(conn, projects)
        conn.execute("UPDATE sessions SET account_uuid = 'acc-A'")
        conn.commit()
        by_account = {e["account_uuid"]: e["kind"] for e in report.limits(conn)["events"]}
        assert by_account == {"acc-A": "session", "acc-B": "weekly"}
        for account, kind in (("acc-A", "session"), ("acc-B", "weekly")):
            events = report.limits(conn, account=account)["events"]
            assert [(e["account_uuid"], e["kind"]) for e in events] == [(account, kind)]


class TestAccountFilterScales:
    """The account clause must be evaluated ONCE, not once per joined row.

    A correlated `EXISTS (... turns WHERE session_id = s.session_id ...)` is
    re-run for every tool_call / turn row the query joins, and for a session
    that belongs to ANOTHER account each run scans all of that session's turns:
    O(rows x turns-per-session). On a real 414k-turn store the filtered summary
    ran past 200s. Tiny fixtures cannot see it; this one is shaped like the
    real thing, small enough to stay quick."""

    BIG_TURNS = 40_000
    BIG_CALLS = 4_000

    def _big_store(self):
        conn = store.connect()
        rows_s = [("big", "acc-B", 0.0), ("mine", "acc-A", 0.0)]
        rows_s += [(f"other{i}", "acc-B", 0.0) for i in range(200)]
        conn.executemany(
            "INSERT INTO sessions(session_id, account_uuid, updated_at, last_activity_at) "
            "VALUES (?,?,?,1e9)", rows_s)
        conn.executemany(
            "INSERT INTO turns(session_id, agent_id, message_id, ts, model, input_tokens, "
            "output_tokens) VALUES (?,?,?,?,?,?,?)",
            [("big", "", f"b{i}", 1e9 + i, "claude-opus-5", 10, 5) for i in range(self.BIG_TURNS)]
            + [("mine", "", f"m{i}", 1e9 + i, "claude-opus-5", 10, 5) for i in range(5)]
            + [(f"other{i}", "", f"o{i}", 1e9, "claude-opus-5", 10, 5) for i in range(200)])
        conn.executemany(
            "INSERT INTO tool_calls(session_id, tool_use_id, agent_id, message_id, tool_name) "
            "VALUES (?,?,?,?,?)",
            [("big", f"tb{i}", "", f"b{i}", "Bash") for i in range(self.BIG_CALLS)]
            + [("mine", f"tm{i}", "", f"m{i}", "Read") for i in range(5)])
        conn.commit()
        return conn

    def test_a_filtered_summary_over_a_huge_other_account_session_is_fast_and_right(self):
        conn = self._big_store()
        started = time.monotonic()
        mine = report.summary(conn, account="acc-A")
        theirs = report.summary(conn, account="acc-B")
        elapsed = time.monotonic() - started
        assert elapsed < 5, f"account-filtered summary took {elapsed:.1f}s"
        assert mine["totals"]["sessions"] == 1
        assert mine["totals"]["turns"] == 5
        assert mine["totals"]["output_tokens"] == 25
        assert [t["tool_name"] for t in mine["tools"]] == ["Read"]
        assert theirs["totals"]["sessions"] == 201
        assert theirs["totals"]["turns"] == self.BIG_TURNS + 200
        assert theirs["tools"][0]["calls"] == self.BIG_CALLS

    def test_the_other_account_reads_stay_fast_too(self):
        conn = self._big_store()
        started = time.monotonic()
        assert len(report.sessions(conn, account="acc-A")) == 1
        assert {r["account_uuid"]: r["sessions"] for r in report.accounts(conn)} == {
            "acc-A": 1, "acc-B": 201}
        report.limits(conn, account="acc-A")
        assert time.monotonic() - started < 5


def test_the_test_module_never_touches_a_real_store(tmp_path: Path):
    # The autouse conftest fixture pins both paths into tmp_path.
    assert Path(store.db_path()).is_relative_to(tmp_path)
