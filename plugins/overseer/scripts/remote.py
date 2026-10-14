"""HTTP client for the overseer board API service (the ``--remote`` transport).

``overseer --remote <url>`` forwards its whole argv (and any hook stdin) to the
host's ``/api/exec``, which runs the real CLI there and returns
stdout/stderr/exit code. This module is the container-side half: a thin httpx
POST. Kept dependency-light (httpx only) so it runs in a minimal dev-container
overseer install; it is imported lazily, so a local (non-remote) CLI never needs
httpx installed.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

_TIMEOUT = 35


@dataclass
class RemoteResult:
    stdout: str
    stderr: str
    returncode: int


class RemoteError(Exception):
    """Transport-level failure (unreachable host, refused, malformed response)."""


def _detail(resp: httpx.Response) -> str:
    try:
        detail = resp.json().get("detail")
    except (ValueError, AttributeError):
        return ""
    return detail if isinstance(detail, str) else ""


def exec_remote(url: str, token: str | None, argv: list[str], stdin: str | None,
                *, repo: str | None = None,
                transport: httpx.BaseTransport | None = None) -> RemoteResult:
    headers = {"X-Overseer-Token": token} if token else {}
    payload: dict[str, object] = {"argv": argv, "stdin": stdin}
    if repo is not None:
        payload["repo"] = repo
    endpoint = f"{url.rstrip('/')}/api/exec"
    try:
        with httpx.Client(transport=transport, timeout=_TIMEOUT) as client:
            resp = client.post(endpoint, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise RemoteError(f"cannot reach overseer board API at {url}: {exc}") from exc
    if resp.status_code == 401:
        raise RemoteError("overseer board API rejected the token (401) — check OVERSEER_REMOTE_TOKEN")
    if resp.status_code == 403:
        detail = ""
        try:
            detail = str(resp.json().get("detail") or "")
        except (ValueError, AttributeError):
            pass
        raise RemoteError(
            "overseer board API refused this request (403)"
            + (f": {detail}" if detail else " — the caller must be on the LAN")
        )
    if resp.status_code in (400, 404, 409) and (detail := _detail(resp)):
        hint = {
            404: " - check OVERSEER_REMOTE_REPO",
            409: " - set OVERSEER_REMOTE_REPO to a unique label or an alias",
        }.get(resp.status_code, "")
        raise RemoteError(f"overseer board API: {detail} ({resp.status_code}){hint}")
    if resp.status_code != 200:
        raise RemoteError(f"overseer board API error {resp.status_code}: {resp.text[:200]}")
    try:
        data = resp.json()
        return RemoteResult(stdout=data["stdout"], stderr=data["stderr"], returncode=data["returncode"])
    except (ValueError, KeyError) as exc:
        raise RemoteError(f"malformed response from overseer board API: {exc}") from exc
