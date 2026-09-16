"""`/api/almoner/*` — the optional inflow-triage page's API.

almoner is a SOFT sibling-plugin dependency on the same terms as chronicle:
every route must degrade to a shape the page can render (never a 500) when
the plugin is missing, unreachable, or answering nonsense.

The plugin now lives in the tree, so the "not installed" paths are simulated
by monkeypatching `almoner_installed`, the same way the installed paths are.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import main


def test_status_reports_not_installed_when_the_plugin_is_absent(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "almoner_installed", lambda: False)
    body = client.get("/api/almoner/status").json()
    assert body == {"installed": False, "configured": False, "sources": []}


def test_digest_is_empty_rather_than_erroring_when_absent(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An absent plugin must not fail the page — the Almoner coin is simply
    never offered, and a direct hit on the route still answers."""
    monkeypatch.setattr(main, "almoner_installed", lambda: False)
    res = client.get("/api/almoner/digest")
    assert res.status_code == 200
    assert res.json() == {"items": [], "sources": []}


def test_installed_but_no_sources_is_reported_as_unconfigured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The published plugin ships an empty source list. That state must be
    distinguishable from "configured and nothing needs you" — otherwise a
    fresh install reads as good news."""
    monkeypatch.setattr(main, "almoner_installed", lambda: True)
    monkeypatch.setattr(main, "run_almoner", lambda *a, **k: {"sources": []})
    body = client.get("/api/almoner/status").json()
    assert body["installed"] is True
    assert body["configured"] is False


def test_status_reports_configured_sources(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = [{"label": "slack", "type": "slack", "via": "agent", "ok": True}]
    monkeypatch.setattr(main, "almoner_installed", lambda: True)
    monkeypatch.setattr(main, "run_almoner", lambda *a, **k: {"sources": sources})
    body = client.get("/api/almoner/status").json()
    assert body["configured"] is True
    assert body["sources"] == sources


def test_a_wedged_cli_degrades_instead_of_failing_the_page(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`run_almoner` returns None for a timeout, a non-zero exit or bad JSON
    alike, while the plugin IS installed. The route must turn that into a
    200, never a 500 — but it must NOT be byte-identical to a genuinely
    empty digest: that would render as "every source answered and none of it
    was asking anything", which is false. `error` is what lets the frontend
    tell the two apart."""
    monkeypatch.setattr(main, "almoner_installed", lambda: True)
    monkeypatch.setattr(main, "run_almoner", lambda *a, **k: None)
    res = client.get("/api/almoner/digest")
    assert res.status_code == 200
    body = res.json()
    assert body["items"] == []
    assert body["sources"] == []
    assert body.get("error")


def test_a_genuinely_empty_digest_carries_no_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mirror image of the test above: a real run that legitimately
    found nothing must not be flagged as a failure."""
    monkeypatch.setattr(main, "almoner_installed", lambda: True)
    monkeypatch.setattr(
        main,
        "run_almoner",
        lambda *a, **k: {"items": [], "sources": [{"label": "slack", "type": "slack", "ok": True}]},
    )
    res = client.get("/api/almoner/digest")
    assert res.status_code == 200
    body = res.json()
    assert body["items"] == []
    assert "error" not in body


def test_digest_passes_the_window_and_context_through(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, ...]] = []

    def fake(*args: str, **_: Any) -> dict[str, Any]:
        seen.append(args)
        return {"items": [], "sources": []}

    monkeypatch.setattr(main, "almoner_installed", lambda: True)
    monkeypatch.setattr(main, "run_almoner", fake)
    client.get("/api/almoner/digest?hours=72&context=work&new=1")
    assert seen == [("digest", "--json", "--hours", "72", "--context", "work", "--new")]


def test_digest_refuses_an_absurd_window(client: TestClient) -> None:
    assert client.get("/api/almoner/digest?hours=0").status_code == 400
    assert client.get("/api/almoner/digest?hours=100000").status_code == 400


def test_digest_refuses_a_context_that_is_not_an_identifier(client: TestClient) -> None:
    """`context` reaches a subprocess argv, so it goes through `check_id`
    like every other client-supplied token on this server."""
    assert client.get("/api/almoner/digest?context=--oops").status_code >= 400
