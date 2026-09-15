"""Notion, reached directly with an internal integration token (``via: api``).

Notion's API has no inbox and no mentions feed, so "what is asking for you" is
rebuilt: recently edited pages the integration can see, and their open comment
threads. The grain is the PAGE — every open thread on one document is one thing
to deal with. Only pages shared with the integration are visible; anything else
is indistinguishable from quiet, which the README says plainly.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime
from typing import Any

from scripts.config import Source
from scripts.gather import AdapterError, FetchResult, Window
from scripts.model import InMessage, conversation

API = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"
MAX_PAGES = 50

Transport = Callable[[str, str, dict[str, Any] | None], dict[str, Any]]

_HTTP_ERRORS = {
    401: "notion: token rejected (401)",
    403: "notion: integration lacks a capability or page access (403)",
    429: "notion: rate limited (429)",
}


def urllib_transport(token: str, *, timeout: float = 15.0) -> Transport:
    def call(method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(f"{API}{path}", data=data, method=method, headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return dict(json.loads(response.read().decode()))
        except urllib.error.HTTPError as exc:
            raise AdapterError(_HTTP_ERRORS.get(exc.code, f"notion: HTTP {exc.code}")) from None
        except (urllib.error.URLError, TimeoutError):
            raise AdapterError("notion: unreachable") from None
        except ValueError:
            raise AdapterError("notion: unreadable response") from None
    return call


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _try_parse(ts: Any) -> datetime | None:
    if not isinstance(ts, str):
        return None
    try:
        return _parse(ts)
    except ValueError:
        return None


def _title(page: dict[str, Any]) -> str:
    for prop in (page.get("properties") or {}).values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            text = "".join(part.get("plain_text", "") for part in prop.get("title") or [])
            if text:
                return text
    return "Untitled"


class NotionAdapter:
    def __init__(self, source: Source, transport: Transport) -> None:
        self.source = source
        self.call = transport
        self._names: dict[str, str | None] = {}

    @classmethod
    def from_source(cls, source: Source, secret: str) -> NotionAdapter:
        return cls(source, urllib_transport(secret))

    def fetch(self, window: Window) -> FetchResult:
        me = self._reader_id()
        items: list[dict[str, Any]] = []
        pages, suppressed = self._recent_pages(window)
        for page in pages:
            item_id = f"notion:{page['id']}"
            raw_comments = self._open_comments(page["id"])
            comments = [c for c in raw_comments if _try_parse(c.get("created_time")) is not None]
            if raw_comments and not comments:
                suppressed.append((item_id, "notion:malformed-comments"))
                continue
            if not comments:
                suppressed.append((item_id, "notion:no-open-comments"))
                continue
            if all(_parse(c["created_time"]) < window.since for c in comments):
                suppressed.append((item_id, "notion:no-new-comments"))
                continue
            items.append(conversation(
                id=item_id, source="notion", context=self.source.context, title=_title(page),
                url=page["url"], messages=[self._message(page, c, me) for c in comments]))
        cursor = pages[0]["last_edited_time"] if pages else None
        return FetchResult(items=items, suppressed=suppressed, cursor=cursor)

    def _recent_pages(self, window: Window) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
        # A page missing id/url/last_edited_time is unusable but not fatal: skip it,
        # keep paging (it doesn't count toward MAX_PAGES or the window-edge stop),
        # and name it in `suppressed` when it at least has an id to name it by.
        pages: list[dict[str, Any]] = []
        suppressed: list[tuple[str, str]] = []
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {
                "filter": {"property": "object", "value": "page"},
                "sort": {"direction": "descending", "timestamp": "last_edited_time"},
                "page_size": 100,
            }
            if cursor:
                body["start_cursor"] = cursor
            response = self.call("POST", "/search", body)
            for page in response.get("results") or []:
                edited = _try_parse(page.get("last_edited_time"))
                page_id = page.get("id")
                if edited is None or not isinstance(page_id, str) or \
                        not isinstance(page.get("url"), str):
                    if isinstance(page_id, str):
                        suppressed.append((f"notion:{page_id}", "notion:malformed-page"))
                    continue
                if edited < window.since:
                    return pages, suppressed
                pages.append(page)
                if len(pages) >= MAX_PAGES:
                    return pages, suppressed
            if not response.get("has_more"):
                return pages, suppressed
            cursor = response.get("next_cursor")

    def _open_comments(self, page_id: str) -> list[dict[str, Any]]:
        comments: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            query = {"block_id": page_id, "page_size": "100"}
            if cursor:
                query["start_cursor"] = cursor
            response = self.call("GET", f"/comments?{urllib.parse.urlencode(query)}", None)
            comments.extend(response.get("results") or [])
            if not response.get("has_more"):
                return comments
            cursor = response.get("next_cursor")

    def _reader_id(self) -> str | None:
        me = self.source.options.get("me")
        if not isinstance(me, str) or not me:
            return None
        if "@" not in me:
            return me
        cursor: str | None = None
        while True:
            query = {"page_size": "100"}
            if cursor:
                query["start_cursor"] = cursor
            try:
                response = self.call("GET", f"/users?{urllib.parse.urlencode(query)}", None)
            except AdapterError:
                return None
            for user in response.get("results") or []:
                email = ((user.get("person") or {}).get("email") or "").lower()
                if email == me.lower():
                    return str(user["id"])
            if not response.get("has_more"):
                return None
            cursor = response.get("next_cursor")

    def _name(self, user_id: str) -> str | None:
        if user_id not in self._names:
            try:
                self._names[user_id] = self.call("GET", f"/users/{user_id}", None).get("name")
            except AdapterError:
                self._names[user_id] = None
        return self._names[user_id]

    def _message(self, page: dict[str, Any], comment: dict[str, Any],
                 me: str | None) -> InMessage:
        author = (comment.get("created_by") or {}).get("id", "")
        discussion_id = comment.get("discussion_id")
        url = f"{page['url']}?d={discussion_id}" if discussion_id else page["url"]
        return InMessage(
            text="".join(part.get("plain_text", "") for part in comment.get("rich_text") or []),
            at=_parse(comment["created_time"]),
            who=self._name(author) if author else None,
            url=url,
            mine=None if me is None or not author else author == me,
        )
