"""Outbox staging and drain behaviour."""

from ledgerlite.outbox import Outbox

from ._waiting import wait_until_drained


def test_staged_write_is_applied_after_drain():
    outbox = Outbox()
    outbox.stage("entry-1", 10)
    outbox.drain()
    wait_until_drained(outbox)
    assert outbox.get("entry-1") == 10


def test_staging_alone_does_not_apply():
    outbox = Outbox()
    outbox.stage("entry-2", 20)
    assert outbox.get("entry-2") is None
    outbox.drain()
    wait_until_drained(outbox)
    assert outbox.get("entry-2") == 20


def test_tick_applies_exactly_one_entry():
    outbox = Outbox()
    outbox.stage("a", 1)
    outbox.stage("b", 2)
    outbox.tick()
    assert outbox.pending_count() == 1
    outbox.drain()
    wait_until_drained(outbox)
    assert outbox.get("b") == 2


def test_last_write_wins_for_repeated_key():
    outbox = Outbox()
    outbox.stage("dup", 1)
    outbox.stage("dup", 9)
    outbox.drain()
    wait_until_drained(outbox)
    assert outbox.get("dup") == 9


def test_unknown_key_reads_as_none():
    outbox = Outbox()
    outbox.drain()
    wait_until_drained(outbox)
    assert outbox.get("never-staged") is None


def test_drain_is_idempotent():
    outbox = Outbox()
    outbox.stage("once", 5)
    outbox.drain()
    outbox.drain()
    wait_until_drained(outbox)
    assert outbox.get("once") == 5


def test_empty_outbox_reports_drained():
    outbox = Outbox()
    wait_until_drained(outbox)
    assert outbox.is_drained()


def test_zero_value_is_applied():
    outbox = Outbox()
    outbox.stage("zero", 0)
    outbox.drain()
    wait_until_drained(outbox)
    assert outbox.get("zero") == 0


def test_negative_value_is_applied():
    outbox = Outbox()
    outbox.stage("neg", -42)
    outbox.drain()
    wait_until_drained(outbox)
    assert outbox.get("neg") == -42


def test_separate_keys_do_not_interfere():
    outbox = Outbox()
    outbox.stage("left", 1)
    outbox.stage("right", 2)
    outbox.drain()
    wait_until_drained(outbox)
    assert (outbox.get("left"), outbox.get("right")) == (1, 2)


def test_large_batch_drains_completely():
    outbox = Outbox()
    for i in range(50):
        outbox.stage(f"bulk-{i}", i)
    outbox.drain()
    wait_until_drained(outbox)
    assert outbox.pending_count() == 0
    assert outbox.get("bulk-49") == 49


def test_pending_count_tracks_staging():
    outbox = Outbox()
    assert outbox.pending_count() == 0
    outbox.stage("p", 1)
    assert outbox.pending_count() == 1
    outbox.drain()
    wait_until_drained(outbox)
    assert outbox.pending_count() == 0


def test_entries_apply_in_staged_order():
    outbox = Outbox()
    outbox.stage("order", 1)
    outbox.stage("order", 2)
    outbox.stage("order", 3)
    outbox.drain()
    wait_until_drained(outbox)
    assert outbox.get("order") == 3


def test_fresh_outbox_starts_empty():
    outbox = Outbox()
    wait_until_drained(outbox)
    assert outbox.pending_count() == 0
    assert outbox.get("anything") is None
