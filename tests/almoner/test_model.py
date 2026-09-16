from datetime import datetime, timedelta, timezone

import pytest

from scripts.model import InMessage, conversation, digest_hash

T0 = datetime(2026, 9, 11, 18, 0, tzinfo=timezone.utc)


def _msg(minutes: int, *, mine, who="Rhona Baird", text=None, thread=None):
    return InMessage(text=text or f"m{minutes}", at=T0 + timedelta(minutes=minutes),
                     who=who, mine=mine, thread=thread)


def _conv(messages):
    return conversation(id="notion:p1", source="notion", context="work",
                        title="Launch plan", messages=messages, url="https://example.invalid/p1")


class TestLastSpeaker:
    def test_last_message_from_someone_else_is_awaiting(self):
        assert _conv([_msg(0, mine=True), _msg(5, mine=False)])["awaiting"] is True

    def test_last_message_mine_is_not_awaiting(self):
        assert _conv([_msg(0, mine=False), _msg(5, mine=True, who="Me")])["awaiting"] is False

    def test_unknown_reader_leaves_awaiting_absent(self):
        # Absence must never manufacture urgency — the key is omitted, not False.
        assert "awaiting" not in _conv([_msg(0, mine=None)])

    def test_order_is_by_time_not_by_input(self):
        item = _conv([_msg(5, mine=True, who="Me"), _msg(0, mine=False)])
        assert item["awaiting"] is False
        assert [m["text"] for m in item["messages"]] == ["m0", "m5"]


class TestPerThreadAwaiting:
    def test_unanswered_thread_a_is_not_hidden_by_reply_in_thread_b(self):
        # Rhona asks in thread A; the reader only answers thread B — A is
        # still open, so the row as a whole must still be awaiting.
        item = _conv([
            _msg(0, mine=False, thread="a", text="ask in a"),
            _msg(5, mine=False, thread="b", text="ask in b"),
            _msg(10, mine=True, who="Me", thread="b", text="reply in b"),
        ])
        assert item["awaiting"] is True

    def test_awaiting_is_false_only_when_every_thread_is_answered(self):
        item = _conv([
            _msg(0, mine=False, thread="a", text="ask in a"),
            _msg(1, mine=True, who="Me", thread="a", text="reply in a"),
            _msg(5, mine=False, thread="b", text="ask in b"),
            _msg(10, mine=True, who="Me", thread="b", text="reply in b"),
        ])
        assert item["awaiting"] is False

    def test_one_thread_unknown_and_none_false_leaves_awaiting_absent(self):
        item = _conv([
            _msg(0, mine=None, thread="a", text="unclear author in a"),
            _msg(5, mine=True, who="Me", thread="b", text="reply in b"),
        ])
        assert "awaiting" not in item

    def test_with_no_threads_behaviour_is_unchanged(self):
        item = _conv([_msg(0, mine=False), _msg(5, mine=True, who="Me")])
        assert item["awaiting"] is False


class TestCollapse:
    def test_excerpt_who_and_arrived_come_from_newest_inbound(self):
        item = _conv([_msg(0, mine=False, text="first ask"),
                      _msg(3, mine=False, who="Tomas Ek", text="second ask"),
                      _msg(9, mine=True, who="Me", text="my answer")])
        assert item["excerpt"] == "second ask"
        assert item["who"] == "Tomas Ek"
        assert item["arrived"] == "2026-09-11T18:03:00+00:00"
        assert item["count"] == 3

    def test_all_mine_falls_back_to_newest(self):
        item = _conv([_msg(0, mine=True, who="Me", text="note to self")])
        assert item["excerpt"] == "note to self"

    def test_serialised_messages_never_carry_mine(self):
        item = _conv([_msg(0, mine=False)])
        assert item["messages"] == [{"text": "m0", "at": "2026-09-11T18:00:00+00:00",
                                     "who": "Rhona Baird"}]

    def test_unjudged_fields_are_null_and_seen_in_names_the_source(self):
        item = _conv([_msg(0, mine=False)])
        assert (item["asks"], item["rank"], item["because"], item["bundled"]) == (
            None, None, None, False)
        assert item["seen_in"] == ["notion"]
        assert item["id"] == "notion:p1" and item["url"] == "https://example.invalid/p1"

    def test_empty_conversation_is_refused(self):
        with pytest.raises(ValueError):
            _conv([])


class TestDigestHash:
    def test_stable_for_the_same_item(self):
        assert digest_hash(_conv([_msg(0, mine=False)])) == digest_hash(
            _conv([_msg(0, mine=False)]))

    def test_moves_when_a_new_message_arrives(self):
        before = digest_hash(_conv([_msg(0, mine=False)]))
        after = digest_hash(_conv([_msg(0, mine=False), _msg(4, mine=False)]))
        assert before != after and len(before) == 16
