from datetime import datetime, timezone

import pytest

from scripts.adapters import registry
from scripts.adapters.notion import NotionAdapter, urllib_transport
from scripts.config import Source
from scripts.gather import AdapterError, Window

WINDOW = Window(datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc),
                datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc))
ME = "user-me"
RHONA = "user-rhona"
USERS = {ME: {"id": ME, "name": "Me", "type": "person", "person": {"email": "me@example.com"}},
         RHONA: {"id": RHONA, "name": "Rhona Baird", "type": "person",
                 "person": {"email": "rhona@example.com"}}}


def _page(pid, edited, title="Launch plan"):
    return {"object": "page", "id": pid, "url": f"https://www.notion.so/{pid}",
            "last_edited_time": edited,
            "properties": {"Name": {"type": "title", "title": [{"plain_text": title}]},
                           "Status": {"type": "select"}}}


def _comment(cid, author, created, text, discussion="d1"):
    return {"object": "comment", "id": cid, "discussion_id": discussion,
            "created_time": created, "created_by": {"object": "user", "id": author},
            "rich_text": [{"plain_text": text}]}


class FakeNotion:
    def __init__(self, pages, comments, users=None, fail=None):
        self.pages, self.comments, self.users, self.fail = pages, comments, users or {}, fail
        self.calls = []

    def __call__(self, method, path, body):
        self.calls.append((method, path, body))
        if self.fail and path.startswith(self.fail[0]):
            raise self.fail[1]
        if path == "/search":
            return {"results": self.pages, "has_more": False, "next_cursor": None}
        if path.startswith("/comments?"):
            pid = path.split("block_id=")[1].split("&")[0]
            return {"results": self.comments.get(pid, []), "has_more": False,
                    "next_cursor": None}
        if path.startswith("/users?"):
            return {"results": list(self.users.values()), "has_more": False,
                    "next_cursor": None}
        if path.startswith("/users/"):
            uid = path.split("/users/")[1]
            if uid not in self.users:
                raise AdapterError("notion: HTTP 404")
            return self.users[uid]
        raise AssertionError(f"unexpected call {method} {path}")


def _adapter(fake, **options):
    return NotionAdapter(Source("notion", "api", "notion", "work", options), fake)


class TestCollapse:
    def test_one_row_per_page_with_every_open_comment(self):
        fake = FakeNotion([_page("p1", "2026-09-15T09:00:00.000Z")], {"p1": [
            _comment("c1", RHONA, "2026-09-15T08:00:00.000Z", "can you review?"),
            _comment("c2", RHONA, "2026-09-15T08:01:00.000Z", "esp. section 2",
                     discussion="d2"),
        ]}, USERS)
        result = _adapter(fake, me=ME).fetch(WINDOW)
        [item] = result.items
        assert item["id"] == "notion:p1" and item["title"] == "Launch plan"
        assert item["count"] == 2 and item["awaiting"] is True and item["who"] == "Rhona Baird"
        assert item["messages"][1]["url"] == "https://www.notion.so/p1?d=d2"
        assert result.cursor == "2026-09-15T09:00:00.000Z"

    def test_my_reply_last_means_not_awaiting(self):
        fake = FakeNotion([_page("p1", "2026-09-15T09:00:00.000Z")], {"p1": [
            _comment("c1", RHONA, "2026-09-15T08:00:00.000Z", "can you review?"),
            _comment("c2", ME, "2026-09-15T08:30:00.000Z", "done"),
        ]}, USERS)
        assert _adapter(fake, me=ME).fetch(WINDOW).items[0]["awaiting"] is False

    def test_reader_given_as_email_is_resolved(self):
        fake = FakeNotion([_page("p1", "2026-09-15T09:00:00.000Z")], {"p1": [
            _comment("c1", ME, "2026-09-15T08:30:00.000Z", "note"),
        ]}, USERS)
        assert _adapter(fake, me="ME@example.com").fetch(WINDOW).items[0]["awaiting"] is False

    def test_without_a_reader_awaiting_is_absent(self):
        fake = FakeNotion([_page("p1", "2026-09-15T09:00:00.000Z")], {"p1": [
            _comment("c1", RHONA, "2026-09-15T08:00:00.000Z", "hello"),
        ]}, USERS)
        assert "awaiting" not in _adapter(fake).fetch(WINDOW).items[0]

    def test_reply_in_one_discussion_does_not_hide_another_left_open(self):
        # Rhona's question in d1 is never answered; the reader only replies
        # in d2, which is also the newest message overall. The whole-row
        # last-speaker rule would call that answered — the per-thread rule
        # must not, because d1 is still open.
        fake = FakeNotion([_page("p1", "2026-09-15T09:00:00.000Z")], {"p1": [
            _comment("c1", RHONA, "2026-09-15T08:00:00.000Z", "ask in d1", discussion="d1"),
            _comment("c2", RHONA, "2026-09-15T08:10:00.000Z", "ask in d2", discussion="d2"),
            _comment("c3", ME, "2026-09-15T08:20:00.000Z", "reply in d2", discussion="d2"),
        ]}, USERS)
        item = _adapter(fake, me=ME).fetch(WINDOW).items[0]
        assert item["awaiting"] is True

    def test_unknown_author_name_degrades_to_no_who(self):
        fake = FakeNotion([_page("p1", "2026-09-15T09:00:00.000Z")], {"p1": [
            _comment("c1", "user-gone", "2026-09-15T08:00:00.000Z", "hello"),
        ]}, {})
        item = _adapter(fake).fetch(WINDOW).items[0]
        assert "who" not in item and "who" not in item["messages"][0]


class TestFilter:
    def test_pages_without_open_or_new_comments_are_suppressed_not_dropped(self):
        fake = FakeNotion([_page("p1", "2026-09-15T09:00:00.000Z"),
                           _page("p2", "2026-09-14T09:00:00.000Z")],
                          {"p2": [_comment("c1", RHONA, "2026-09-01T08:00:00.000Z", "old")]},
                          USERS)
        result = _adapter(fake, me=ME).fetch(WINDOW)
        assert result.items == []
        assert result.suppressed == [("notion:p1", "notion:no-open-comments"),
                                     ("notion:p2", "notion:no-new-comments")]

    def test_stops_paging_at_the_window_edge(self):
        fake = FakeNotion([_page("p1", "2026-09-15T09:00:00.000Z"),
                           _page("old", "2026-09-10T09:00:00.000Z")], {}, USERS)
        _adapter(fake).fetch(WINDOW)
        assert not any("block_id=old" in path for _, path, _ in fake.calls)

    def test_is_read_only(self):
        fake = FakeNotion([_page("p1", "2026-09-15T09:00:00.000Z")], {}, USERS)
        _adapter(fake, me="me@example.com").fetch(WINDOW)
        assert {(m, p) for m, p, _ in fake.calls if m != "GET"} == {("POST", "/search")}


class TestErrors:
    def test_search_failure_propagates_as_an_adapter_error(self):
        fake = FakeNotion([], {}, fail=("/search", AdapterError("notion: token rejected (401)")))
        with pytest.raises(AdapterError, match="401"):
            _adapter(fake).fetch(WINDOW)


class TestCap:
    def test_cap_hit_with_more_pages_sets_incomplete_and_warns(self, monkeypatch):
        monkeypatch.setattr("scripts.adapters.notion.MAX_PAGES", 1)
        fake = FakeNotion([_page("p1", "2026-09-15T09:30:00.000Z"),
                           _page("p2", "2026-09-15T09:00:00.000Z")], {
            "p1": [_comment("c1", RHONA, "2026-09-15T08:00:00.000Z", "hi")],
        }, USERS)
        result = _adapter(fake, me=ME).fetch(WINDOW)
        cap_warning = ("notion: stopped after 1 recently edited pages; older pages in the "
                      "window were not read")
        assert result.complete is False
        assert result.warnings == [cap_warning]

    def test_cap_hit_with_nothing_left_stays_complete(self, monkeypatch):
        monkeypatch.setattr("scripts.adapters.notion.MAX_PAGES", 1)
        fake = FakeNotion([_page("p1", "2026-09-15T09:30:00.000Z")], {
            "p1": [_comment("c1", RHONA, "2026-09-15T08:00:00.000Z", "hi")],
        }, USERS)
        result = _adapter(fake, me=ME).fetch(WINDOW)
        assert result.complete is True and result.warnings == []


class TestReaderWarning:
    def test_unresolved_email_warns(self):
        fake = FakeNotion([_page("p1", "2026-09-15T09:00:00.000Z")], {"p1": [
            _comment("c1", RHONA, "2026-09-15T08:00:00.000Z", "hi"),
        ]}, USERS)
        result = _adapter(fake, me="nobody@example.com").fetch(WINDOW)
        reader_warning = "notion: could not resolve the configured reader; awaiting is unknown"
        assert "awaiting" not in result.items[0]
        assert result.warnings == [reader_warning]

    def test_no_reader_configured_warns_nothing(self):
        fake = FakeNotion([_page("p1", "2026-09-15T09:00:00.000Z")], {"p1": [
            _comment("c1", RHONA, "2026-09-15T08:00:00.000Z", "hi"),
        ]}, USERS)
        assert _adapter(fake).fetch(WINDOW).warnings == []


class TestArchived:
    def test_archived_page_is_suppressed_not_read(self):
        archived = _page("gone", "2026-09-15T09:30:00.000Z")
        archived["archived"] = True
        fake = FakeNotion([archived, _page("p1", "2026-09-15T09:00:00.000Z")], {
            "p1": [_comment("c1", RHONA, "2026-09-15T08:00:00.000Z", "hi")],
        }, USERS)
        result = _adapter(fake, me=ME).fetch(WINDOW)
        assert [item["id"] for item in result.items] == ["notion:p1"]
        assert ("notion:gone", "notion:archived") in result.suppressed
        assert not any("block_id=gone" in path for _, path, _ in fake.calls)

    def test_in_trash_page_is_suppressed_not_read(self):
        trashed = _page("gone", "2026-09-15T09:30:00.000Z")
        trashed["in_trash"] = True
        fake = FakeNotion([trashed, _page("p1", "2026-09-15T09:00:00.000Z")], {
            "p1": [_comment("c1", RHONA, "2026-09-15T08:00:00.000Z", "hi")],
        }, USERS)
        result = _adapter(fake, me=ME).fetch(WINDOW)
        assert ("notion:gone", "notion:archived") in result.suppressed


class TestClosed:
    def test_no_open_comments_page_is_reported_closed(self):
        fake = FakeNotion([_page("p1", "2026-09-15T09:00:00.000Z")], {}, USERS)
        result = _adapter(fake, me=ME).fetch(WINDOW)
        assert result.closed == ["notion:p1"]

    def test_no_new_comments_page_is_not_closed(self):
        fake = FakeNotion([_page("p1", "2026-09-15T09:00:00.000Z")], {
            "p1": [_comment("c1", RHONA, "2026-09-01T08:00:00.000Z", "old")],
        }, USERS)
        result = _adapter(fake, me=ME).fetch(WINDOW)
        assert result.closed == []


class TestMalformed:
    def test_malformed_page_is_suppressed_not_fatal(self):
        bad = _page("bad", "2026-09-15T09:30:00.000Z")
        del bad["url"]
        fake = FakeNotion([bad, _page("p1", "2026-09-15T09:00:00.000Z")], {
            "p1": [_comment("c1", RHONA, "2026-09-15T08:00:00.000Z", "hi")],
        }, USERS)
        result = _adapter(fake, me=ME).fetch(WINDOW)
        assert [item["id"] for item in result.items] == ["notion:p1"]
        assert ("notion:bad", "notion:malformed-page") in result.suppressed

    def test_comment_missing_discussion_id_links_to_the_page(self):
        comment = _comment("c1", RHONA, "2026-09-15T08:00:00.000Z", "hi")
        del comment["discussion_id"]
        fake = FakeNotion([_page("p1", "2026-09-15T09:00:00.000Z")], {"p1": [comment]}, USERS)
        item = _adapter(fake, me=ME).fetch(WINDOW).items[0]
        assert item["messages"][0]["url"] == "https://www.notion.so/p1"

    def test_comment_missing_created_time_is_dropped(self):
        bad_comment = _comment("c1", RHONA, "2026-09-15T08:00:00.000Z", "no time")
        del bad_comment["created_time"]
        fake = FakeNotion([_page("p1", "2026-09-15T09:00:00.000Z")], {"p1": [
            bad_comment,
            _comment("c2", RHONA, "2026-09-15T08:30:00.000Z", "ok"),
        ]}, USERS)
        item = _adapter(fake, me=ME).fetch(WINDOW).items[0]
        assert item["count"] == 1

    def test_page_with_only_malformed_comments_is_suppressed(self):
        bad_comment = _comment("c1", RHONA, "2026-09-15T08:00:00.000Z", "no time")
        del bad_comment["created_time"]
        fake = FakeNotion([_page("p1", "2026-09-15T09:00:00.000Z")], {"p1": [bad_comment]}, USERS)
        result = _adapter(fake, me=ME).fetch(WINDOW)
        assert result.items == []
        assert result.suppressed == [("notion:p1", "notion:malformed-comments")]

    def test_comment_missing_author_gives_unknown_mine(self):
        comment = _comment("c1", RHONA, "2026-09-15T08:00:00.000Z", "hi")
        del comment["created_by"]
        fake = FakeNotion([_page("p1", "2026-09-15T09:00:00.000Z")], {"p1": [comment]}, USERS)
        item = _adapter(fake, me=ME).fetch(WINDOW).items[0]
        assert "awaiting" not in item


class TestTransport:
    def test_unreadable_response_becomes_a_named_error(self, monkeypatch):
        class FakeResponse:
            def read(self):
                return b"not json"

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: FakeResponse())
        call = urllib_transport("invented-token")
        with pytest.raises(AdapterError, match="unreadable"):
            call("GET", "/search", None)


def test_registered_under_notion_via_api():
    factory = registry()[("notion", "api")]
    adapter = factory(Source("notion", "api", "notion", "work"), "invented-token")
    assert isinstance(adapter, NotionAdapter)
