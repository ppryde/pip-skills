"""FastAPI app factory for the overseer dashboard backend.

`create_app(root)` wires `/api` routes that shell the overseer/vigil CLIs
(see `app.cli_client`) against `root`, plus a static mount / placeholder for
the (separately built) frontend `dist/` (chunk 4). This module is a CLIENT
of the CLIs only — it never imports overseer/vigil internals and never
touches `.workflow/` directly, with one narrow exception: `derive_repo_root`
(a pure `git rev-parse` path helper, no filesystem/board access) is imported
directly below to compute the launch root's OWN main-repo root, matching how
`board.db`'s `meta['repo_root']` was derived when the CLI wrote it.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.cli_client import CliError, check_id, run_census, run_census_all, run_overseer, run_vigil

# backend/app/main.py -> parents: [0]=app [1]=backend [2]=dashboard [3]=overseer
# `scripts` (the overseer CLI's package) isn't on sys.path by default when
# this app is imported/served from `dashboard/backend` — add the overseer
# root so `derive_repo_root` resolves the same way the CLI does.
_OVERSEER_ROOT = Path(__file__).resolve().parents[3]
if str(_OVERSEER_ROOT) not in sys.path:
    sys.path.insert(0, str(_OVERSEER_ROOT))

from scripts.store import derive_repo_label, derive_repo_root  # noqa: E402  (must follow sys.path setup above)

_PCT_RE = re.compile(r"ctx (\d+)%")

_MOVE_STATUS_VERBS = {
    "parked": ("park",),
    "done": ("done",),
    "abandoned": ("abandon",),
    "planned": ("unblock",),
    "in-flight": ("unblock",),
}


class OrderBody(BaseModel):
    order: int


class PriorityBody(BaseModel):
    priority: str | None = None


class ParentBody(BaseModel):
    parent: str | None = None


class DependsBody(BaseModel):
    on: str | None = None
    off: str | None = None


class MoveBody(BaseModel):
    stage: str | None = None
    status: str | None = None
    reason: str | None = None


class ThresholdBody(BaseModel):
    value: int


class ClaimBody(BaseModel):
    session_id: str | None = None


def _context_pct(root: Path) -> int | None:
    """`vigil context` has no --json; parse `ctx NN%` out of its one-line stdout."""
    try:
        out = run_vigil(root, "context")
    except CliError:
        return None
    match = _PCT_RE.search(out)
    return int(match.group(1)) if match else None


def _context_threshold(root: Path) -> int | None:
    try:
        out = run_vigil(root, "config", "get", "context.threshold")
    except CliError:
        return None
    try:
        return int(out.strip())
    except ValueError:
        return None


def _census_extras(entry: dict[str, Any] | None) -> dict[str, Any]:
    """Rich, worktree-indexed session facts from census (soft — {} when absent).

    ``pct`` still comes from vigil (which reads census itself, with a transcript
    fallback); these are the extras vigil's one-line gauge does not carry.
    """
    if not entry:
        return {}
    payload = entry.get("payload") or {}
    out: dict[str, Any] = {"stale": bool(entry.get("stale"))}
    model = payload.get("model") or {}
    if model.get("display_name"):
        out["model"] = model["display_name"]
    if payload.get("session_name"):
        out["session_name"] = payload["session_name"]
    pr = payload.get("pr") or {}
    if pr:
        out["pr"] = {k: pr.get(k) for k in ("number", "url", "review_state") if pr.get(k) is not None}
    return out


def _limits_section(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    """Account-global 5h/7d rate-limit usage from census; None when unavailable."""
    limits = (entry or {}).get("limits") or {}
    windows = {k: limits[k] for k in ("five_hour", "seven_day") if limits.get(k)}
    return windows or None


# Mirrored from census.store.STALE_HORIZON_SECONDS (90 seconds)
_STALE_HORIZON_SECONDS = 90


def _entry_ts(entry: dict[str, Any]) -> float:
    """The entry's ``updated_at`` as a float; malformed/missing reads as 0.0.

    Mirrors vigil's defensive coercion (vigil/scripts/census.py:_entry_ts).
    Malformed timestamps (None, non-numeric strings) are treated as 0, which
    places them beyond any staleness horizon — quarantine-safe, never raises.
    """
    try:
        return float(entry.get("updated_at", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _session_summary(sid: str, entry: dict[str, Any], now: float) -> dict[str, Any]:
    """Convert a census session entry into a session summary response object.

    Returns {id, session_name?, model?, worktree_cwd, branch?, pct?, pr?, updated_at, stale}.
    Optional fields (model, pr, session_name, branch, pct) are omitted when absent,
    mirroring _census_extras's "forward what's there" style. Malformed updated_at
    values are coerced to 0.0 (treating as stale) rather than raising.
    """
    payload = entry.get("payload") or {}
    ts = _entry_ts(entry)
    out: dict[str, Any] = {
        "id": sid,
        "worktree_cwd": entry.get("worktree_cwd"),
        "updated_at": entry.get("updated_at"),
        "stale": (now - ts) > _STALE_HORIZON_SECONDS,
    }
    if entry.get("branch"):
        out["branch"] = entry["branch"]
    model = payload.get("model") or {}
    if model.get("display_name"):
        out["model"] = model["display_name"]
    if payload.get("session_name"):
        out["session_name"] = payload["session_name"]
    pr = payload.get("pr") or {}
    if pr:
        out["pr"] = {k: pr.get(k) for k in ("number", "url", "review_state") if pr.get(k) is not None}
    context_window = payload.get("context_window") or {}
    if context_window.get("used_percentage") is not None:
        out["pct"] = context_window["used_percentage"]
    return out


def _sessions_list(repo_root: Path) -> list[dict[str, Any]]:
    """Fetch all sessions from census, scoped to ``repo_root``, sorted by
    updated_at descending.

    Census tracks sessions across every repo on the machine (it has no
    per-repo scoping of its own), so this filters to only those sessions
    whose `worktree_cwd` derives — via `derive_repo_root` — to the repo this
    dashboard instance is serving. A session whose `worktree_cwd` no longer
    resolves to a repo at all (e.g. a removed worktree) is a ghost and is
    dropped rather than surfaced against the wrong repo. `derive_repo_root`
    shells `git rev-parse` per session; memoized by cwd within this call
    since census may report the same cwd for multiple sessions.

    Returns [] when census is unavailable (soft dependency, never 500s).
    Handles malformed timestamps defensively (treated as 0, sort last).
    """
    data = run_census_all()
    if not data:
        return []
    sessions_dict = data.get("sessions") or {}
    now = time.time()
    root_cache: dict[str, Path | None] = {}

    def _derived_root(cwd: str) -> Path | None:
        if cwd not in root_cache:
            root_cache[cwd] = derive_repo_root(Path(cwd))
        return root_cache[cwd]

    sessions = [
        _session_summary(sid, entry, now)
        for sid, entry in sessions_dict.items()
        if entry.get("worktree_cwd") and _derived_root(entry["worktree_cwd"]) == repo_root
    ]
    # Sort by coerced updated_at descending (freshest first); malformed -> 0.0 -> sorts last
    sessions.sort(key=lambda s: _entry_ts({"updated_at": s.get("updated_at")}), reverse=True)
    return sessions


def _live_session_counts_by_root() -> dict[Path, int]:
    """Count LIVE (non-stale) census sessions per derived repo root, across
    every repo on the machine census knows about (not scoped to any single
    board) — feeds `GET /api/repos`'s per-repo `live_sessions` count and its
    "unbegun" repo union (a live session in a repo with no board.db).

    "Live" mirrors `_session_summary`'s `stale` computation: a session is
    live when `(now - updated_at) <= _STALE_HORIZON_SECONDS`. Ghost sessions
    (a `worktree_cwd` that no longer resolves to any repo — e.g. a removed
    worktree) are dropped, same as `_sessions_list`. `derive_repo_root`
    shells `git rev-parse` per distinct cwd; memoized within this call.

    Soft-degrades to `{}` when census is unavailable — never raises, mirrors
    every other census read in this module.
    """
    data = run_census_all()
    if not data:
        return {}
    sessions_dict = data.get("sessions") or {}
    now = time.time()
    root_cache: dict[str, Path | None] = {}
    counts: dict[Path, int] = {}
    for entry in sessions_dict.values():
        cwd = entry.get("worktree_cwd")
        if not cwd:
            continue
        if cwd not in root_cache:
            root_cache[cwd] = derive_repo_root(Path(cwd))
        root = root_cache[cwd]
        if root is None:
            continue
        if (now - _entry_ts(entry)) > _STALE_HORIZON_SECONDS:
            continue
        counts[root] = counts.get(root, 0) + 1
    return counts


def _discover_roots(launch_root: Path) -> list[dict[str, Any]]:
    """The `repos` CLI verb's discovery list — every board.db the CLI can
    find, each `{"label": ..., "root": ...}`. `[]` if the CLI errors (soft
    degrade, same spirit as every other CLI call this module treats as
    optional); never raises."""
    try:
        data = run_overseer(launch_root, "repos", "--json", json_out=True)
    except CliError:
        return []
    return data if isinstance(data, list) else []


def _resolve_root(launch_root: Path, default_root: Path, requested: str | None) -> Path:
    """Resolve the effective repo root for a request, VALIDATING a
    client-supplied ``root`` against the ``repos`` discovery allowlist
    before it is ever used to shell the CLI.

    Security-critical: this server can bind 0.0.0.0 with no auth (see
    module docstring), so an unvalidated ``root`` would let any LAN client
    point the overseer CLI at an arbitrary filesystem path. ``requested``
    must match — after resolution — one of the roots ``repos`` discovery
    ACTUALLY returned, not merely "look like a path". Raises HTTP 400
    (never shells anything with the rejected value) when it doesn't.

    ``default_root`` (used only when ``requested`` is None) is the SERVER's
    own derived main-repo root, not client input — trusted, so it bypasses
    the allowlist check entirely. Client-supplied roots always go through
    validation above; only the omitted-root default changes here.
    """
    if requested is None:
        return default_root
    candidate = Path(requested).resolve()
    allowed = {
        Path(entry["root"]).resolve()
        for entry in _discover_roots(launch_root)
        if isinstance(entry, dict) and entry.get("root")
    }
    if candidate not in allowed:
        raise HTTPException(status_code=400, detail=f"unknown root: {requested!r}")
    return candidate


def _board_response(root: Path) -> dict[str, Any]:
    """The payload every read AND every mutation returns.

    Vigil and census calls are wrapped so neither ever 500s the board read: a
    vigil CliError degrades pct/threshold to None, and census is a soft
    dependency that degrades to {} / None.
    """
    board = run_overseer(root, "board", "--json", json_out=True)
    entry = run_census(root)
    context: dict[str, Any] = {
        "pct": _context_pct(root),
        "threshold": _context_threshold(root),
    }
    context.update(_census_extras(entry))
    return {
        "board": board,
        "context": context,
        "limits": _limits_section(entry),
    }


def _show_error(exc: CliError) -> HTTPException:
    """GET /api/card/{id} mapping.

    `cmd_show` exits 1 for three distinct reasons: genuine not-found, a
    corrupt-but-present card (CardParseError), and argparse usage errors —
    so returncode alone can't disambiguate. Only "no card with id" in
    stderr is a real 404; everything else (incl. corrupt-card parse
    errors) is a 400 that surfaces the real CLI message.
    """
    if exc.returncode == 504:
        return HTTPException(status_code=504, detail=exc.stderr)
    if exc.returncode == 2:
        return HTTPException(status_code=400, detail=exc.stderr)
    if "no card with id" in exc.stderr:
        return HTTPException(status_code=404, detail=exc.stderr)
    return HTTPException(status_code=400, detail=exc.stderr)


def _mutation_error(exc: CliError) -> HTTPException:
    """Mutation mapping: timeout -> 504, everything else (incl. id validation) -> 400."""
    if exc.returncode == 504:
        return HTTPException(status_code=504, detail=exc.stderr)
    return HTTPException(status_code=400, detail=exc.stderr)


def create_app(root: Path, *, host: str = "127.0.0.1", dist_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="overseer dashboard")
    launch_root = root
    launch_host = host
    # The dashboard is normally launched from inside a worktree (e.g.
    # `.claude/worktrees/<name>`), whose path differs from the main-repo
    # root `board.db` records as `meta['repo_root']`. Derive the MAIN repo
    # root the launch root belongs to — same resolution the CLI used when
    # it wrote that meta — so `/api/repos`'s `current` flag matches the
    # repo actually being served, not the raw (possibly worktree) launch
    # path. Falls back to the launch root itself when derivation fails (not
    # a git repo, git missing) — same as a launch root with no worktree.
    _derived_launch_root = (derive_repo_root(launch_root) or launch_root).resolve()

    def _mutate(fn: Callable[[], None], effective_root: Path) -> dict[str, Any]:
        try:
            fn()
        except CliError as exc:
            raise _mutation_error(exc) from exc
        return _board_response(effective_root)

    @app.get("/api/board")
    def get_board(root: str | None = None) -> dict[str, Any]:
        effective = _resolve_root(launch_root, _derived_launch_root, root)
        return _board_response(effective)

    @app.get("/api/repos")
    def get_repos() -> dict[str, Any]:
        """Board repos (from `repos --json`, `has_board:true`) UNIONED with
        "unbegun" repos — repos with live census sessions but no board.db
        yet (`has_board:false`). Unbegun roots are a display-only addition:
        they are never added to `_resolve_root`'s allowlist (that allowlist
        is recomputed fresh, from `_discover_roots` only, on every request),
        so `/api/board` etc. still 400 an unbegun root — the dashboard never
        fetches the board for one (see docs/superpowers/specs/2026-07-28
        -overseer-worktree-branch-distinction.md).
        """
        live_counts = _live_session_counts_by_root()
        repos_list: list[dict[str, Any]] = []
        board_roots: set[Path] = set()
        for entry in _discover_roots(launch_root):
            if not isinstance(entry, dict) or not entry.get("root"):
                continue
            root = Path(entry["root"]).resolve()
            item = dict(entry)
            item["current"] = root == _derived_launch_root
            item["has_board"] = True
            item["live_sessions"] = live_counts.get(root, 0)
            repos_list.append(item)
            board_roots.add(root)

        for root, count in live_counts.items():
            if root in board_roots:
                continue
            repos_list.append({
                "label": derive_repo_label(root) or root.name,
                "root": str(root),
                "current": False,
                "has_board": False,
                "live_sessions": count,
            })

        return {"repos": repos_list}

    @app.get("/api/sessions")
    def get_sessions(root: str | None = None) -> dict[str, Any]:
        effective = _resolve_root(launch_root, _derived_launch_root, root)
        return {"sessions": _sessions_list(effective)}

    @app.get("/api/card/{card_id}")
    def get_card(card_id: str, root: str | None = None) -> Any:
        effective = _resolve_root(launch_root, _derived_launch_root, root)
        try:
            check_id(card_id)
            return run_overseer(effective, "show", card_id, "--json", json_out=True)
        except CliError as exc:
            raise _show_error(exc) from exc

    @app.post("/api/card/{card_id}/order")
    def set_order(card_id: str, body: OrderBody, root: str | None = None) -> dict[str, Any]:
        effective = _resolve_root(launch_root, _derived_launch_root, root)

        def do() -> None:
            check_id(card_id)
            run_overseer(effective, "set-field", card_id, "--order", str(body.order))

        return _mutate(do, effective)

    @app.post("/api/card/{card_id}/priority")
    def set_priority(card_id: str, body: PriorityBody, root: str | None = None) -> dict[str, Any]:
        effective = _resolve_root(launch_root, _derived_launch_root, root)

        def do() -> None:
            check_id(card_id)
            value = body.priority if body.priority is not None else ""
            run_overseer(effective, "set-field", card_id, "--priority", value)

        return _mutate(do, effective)

    @app.post("/api/card/{card_id}/parent")
    def set_parent(card_id: str, body: ParentBody, root: str | None = None) -> dict[str, Any]:
        effective = _resolve_root(launch_root, _derived_launch_root, root)

        def do() -> None:
            check_id(card_id)
            value = body.parent if body.parent is not None else ""
            if value:
                check_id(value)
            run_overseer(effective, "set-field", card_id, "--parent", value)

        return _mutate(do, effective)

    @app.post("/api/card/{card_id}/depends")
    def set_depends(card_id: str, body: DependsBody, root: str | None = None) -> dict[str, Any]:
        if body.on is None and body.off is None:
            raise HTTPException(status_code=400, detail="on or off required")
        effective = _resolve_root(launch_root, _derived_launch_root, root)

        def do() -> None:
            check_id(card_id)
            args = ["depends", card_id]
            if body.on is not None:
                check_id(body.on)
                args += ["--on", body.on]
            if body.off is not None:
                check_id(body.off)
                args += ["--off", body.off]
            run_overseer(effective, *args)

        return _mutate(do, effective)

    @app.post("/api/card/{card_id}/park")
    def park_card(card_id: str, root: str | None = None) -> dict[str, Any]:
        effective = _resolve_root(launch_root, _derived_launch_root, root)

        def do() -> None:
            check_id(card_id)
            run_overseer(effective, "park", card_id)

        return _mutate(do, effective)

    @app.post("/api/card/{card_id}/unpark")
    def unpark_card(card_id: str, root: str | None = None) -> dict[str, Any]:
        effective = _resolve_root(launch_root, _derived_launch_root, root)

        def do() -> None:
            check_id(card_id)
            run_overseer(effective, "unpark", card_id)

        return _mutate(do, effective)

    @app.post("/api/card/{card_id}/claim")
    def claim_card(card_id: str, body: ClaimBody, root: str | None = None) -> dict[str, Any]:
        session_id = body.session_id
        if not session_id:
            raise HTTPException(status_code=400, detail="session_id required")
        effective = _resolve_root(launch_root, _derived_launch_root, root)

        def do() -> None:
            check_id(card_id)
            run_overseer(effective, "claim", card_id, "--session", session_id)  # type: ignore[arg-type]

        return _mutate(do, effective)

    @app.post("/api/card/{card_id}/unclaim")
    def unclaim_card(card_id: str, root: str | None = None) -> dict[str, Any]:
        effective = _resolve_root(launch_root, _derived_launch_root, root)

        def do() -> None:
            check_id(card_id)
            run_overseer(effective, "unclaim", card_id)

        return _mutate(do, effective)

    @app.post("/api/card/{card_id}/move")
    def move_card(card_id: str, body: MoveBody, root: str | None = None) -> dict[str, Any]:
        """Dispatch table — overseer has no unified set-status verb.

        `stage` wins if present (`set-stage id <stage>`); else `status` maps to
        park/done/abandon/block/unblock. The resulting status after `unblock`
        is stage-derived (`in-flight` if the card has a stage else `planned`) —
        this endpoint returns the refreshed board so the client sees the
        ACTUAL resulting status; it does not fake-honor a requested
        planned-vs-in-flight distinction.
        """
        effective = _resolve_root(launch_root, _derived_launch_root, root)

        if body.stage is not None:
            def do_stage() -> None:
                check_id(card_id)
                run_overseer(effective, "set-stage", card_id, body.stage)  # type: ignore[arg-type]

            return _mutate(do_stage, effective)

        if body.status == "blocked":
            if not body.reason:
                raise HTTPException(status_code=400, detail="reason required to block")

            def do_block() -> None:
                check_id(card_id)
                run_overseer(effective, "block", card_id, "--reason", body.reason)  # type: ignore[arg-type]

            return _mutate(do_block, effective)

        verbs = _MOVE_STATUS_VERBS.get(body.status or "")
        if verbs is None:
            raise HTTPException(status_code=400, detail=f"unknown move status: {body.status!r}")

        def do_status() -> None:
            check_id(card_id)
            run_overseer(effective, *verbs, card_id)

        return _mutate(do_status, effective)

    @app.post("/api/config/threshold")
    def set_threshold(body: ThresholdBody, root: str | None = None) -> dict[str, Any]:
        effective = _resolve_root(launch_root, _derived_launch_root, root)

        def do() -> None:
            run_vigil(effective, "config", "set", "context.threshold", str(body.value))

        return _mutate(do, effective)

    _mount_frontend(app, dist_dir)

    return app


def _mount_frontend(app: FastAPI, dist_dir: Path | None = None) -> None:
    """Serve the built frontend `dist/` if present; else a 200 placeholder.

    Presence-checked BEFORE mounting — StaticFiles raises if the dir is
    missing. API routes are registered above and always win over the
    catch-all placeholder route.

    `dist_dir` defaults to the real, committed `frontend/dist/` (resolved
    relative to this file). Tests that need to exercise the dist-absent
    placeholder path (chunk 7 reconciliation — dist is now committed, so
    the real path always exists) pass an explicit dist_dir that is
    guaranteed not to exist instead.
    """
    # backend/app/main.py -> parents[0]=app [1]=backend [2]=dashboard
    dist = dist_dir if dist_dir is not None else Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="static")
        return

    placeholder = "Frontend not built — run `npm run build` in dashboard/frontend"

    @app.get("/{full_path:path}")
    def serve_placeholder(full_path: str) -> HTMLResponse:
        return HTMLResponse(content=placeholder, status_code=200)
