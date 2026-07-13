"""FastAPI app factory for the overseer dashboard backend.

`create_app(root)` wires `/api` routes that shell the overseer/vigil CLIs
(see `app.cli_client`) against `root`, plus a static mount / placeholder for
the (separately built) frontend `dist/` (chunk 4). This module is a CLIENT
of the CLIs only — it never imports overseer/vigil internals and never
touches `.workflow/` directly.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.cli_client import CliError, check_id, run_census, run_census_all, run_overseer, run_vigil

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

    Returns {id, session_name?, model?, worktree_cwd, pct?, pr?, updated_at, stale}.
    Optional fields (model, pr, session_name, pct) are omitted when absent, mirroring
    _census_extras's "forward what's there" style. Malformed updated_at values are
    coerced to 0.0 (treating as stale) rather than raising.
    """
    payload = entry.get("payload") or {}
    ts = _entry_ts(entry)
    out: dict[str, Any] = {
        "id": sid,
        "worktree_cwd": entry.get("worktree_cwd"),
        "updated_at": entry.get("updated_at"),
        "stale": (now - ts) > _STALE_HORIZON_SECONDS,
    }
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


def _sessions_list() -> list[dict[str, Any]]:
    """Fetch all sessions from census and return sorted by updated_at descending.

    Returns [] when census is unavailable (soft dependency, never 500s).
    Handles malformed timestamps defensively (treated as 0, sort last).
    """
    data = run_census_all()
    if not data:
        return []
    sessions_dict = data.get("sessions") or {}
    now = time.time()
    sessions = [
        _session_summary(sid, entry, now)
        for sid, entry in sessions_dict.items()
    ]
    # Sort by coerced updated_at descending (freshest first); malformed -> 0.0 -> sorts last
    sessions.sort(key=lambda s: _entry_ts({"updated_at": s.get("updated_at")}), reverse=True)
    return sessions


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


def create_app(root: Path, *, dist_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="overseer dashboard")

    def _mutate(fn: Callable[[], None]) -> dict[str, Any]:
        try:
            fn()
        except CliError as exc:
            raise _mutation_error(exc) from exc
        return _board_response(root)

    @app.get("/api/board")
    def get_board() -> dict[str, Any]:
        return _board_response(root)

    @app.get("/api/sessions")
    def get_sessions() -> dict[str, Any]:
        return {"sessions": _sessions_list()}

    @app.get("/api/card/{card_id}")
    def get_card(card_id: str) -> Any:
        try:
            check_id(card_id)
            return run_overseer(root, "show", card_id, "--json", json_out=True)
        except CliError as exc:
            raise _show_error(exc) from exc

    @app.post("/api/card/{card_id}/order")
    def set_order(card_id: str, body: OrderBody) -> dict[str, Any]:
        def do() -> None:
            check_id(card_id)
            run_overseer(root, "set-field", card_id, "--order", str(body.order))

        return _mutate(do)

    @app.post("/api/card/{card_id}/priority")
    def set_priority(card_id: str, body: PriorityBody) -> dict[str, Any]:
        def do() -> None:
            check_id(card_id)
            value = body.priority if body.priority is not None else ""
            run_overseer(root, "set-field", card_id, "--priority", value)

        return _mutate(do)

    @app.post("/api/card/{card_id}/parent")
    def set_parent(card_id: str, body: ParentBody) -> dict[str, Any]:
        def do() -> None:
            check_id(card_id)
            value = body.parent if body.parent is not None else ""
            if value:
                check_id(value)
            run_overseer(root, "set-field", card_id, "--parent", value)

        return _mutate(do)

    @app.post("/api/card/{card_id}/depends")
    def set_depends(card_id: str, body: DependsBody) -> dict[str, Any]:
        if body.on is None and body.off is None:
            raise HTTPException(status_code=400, detail="on or off required")

        def do() -> None:
            check_id(card_id)
            args = ["depends", card_id]
            if body.on is not None:
                check_id(body.on)
                args += ["--on", body.on]
            if body.off is not None:
                check_id(body.off)
                args += ["--off", body.off]
            run_overseer(root, *args)

        return _mutate(do)

    @app.post("/api/card/{card_id}/park")
    def park_card(card_id: str) -> dict[str, Any]:
        def do() -> None:
            check_id(card_id)
            run_overseer(root, "park", card_id)

        return _mutate(do)

    @app.post("/api/card/{card_id}/unpark")
    def unpark_card(card_id: str) -> dict[str, Any]:
        def do() -> None:
            check_id(card_id)
            run_overseer(root, "unpark", card_id)

        return _mutate(do)

    @app.post("/api/card/{card_id}/move")
    def move_card(card_id: str, body: MoveBody) -> dict[str, Any]:
        """Dispatch table — overseer has no unified set-status verb.

        `stage` wins if present (`set-stage id <stage>`); else `status` maps to
        park/done/abandon/block/unblock. The resulting status after `unblock`
        is stage-derived (`in-flight` if the card has a stage else `planned`) —
        this endpoint returns the refreshed board so the client sees the
        ACTUAL resulting status; it does not fake-honor a requested
        planned-vs-in-flight distinction.
        """
        if body.stage is not None:
            def do_stage() -> None:
                check_id(card_id)
                run_overseer(root, "set-stage", card_id, body.stage)  # type: ignore[arg-type]

            return _mutate(do_stage)

        if body.status == "blocked":
            if not body.reason:
                raise HTTPException(status_code=400, detail="reason required to block")

            def do_block() -> None:
                check_id(card_id)
                run_overseer(root, "block", card_id, "--reason", body.reason)  # type: ignore[arg-type]

            return _mutate(do_block)

        verbs = _MOVE_STATUS_VERBS.get(body.status or "")
        if verbs is None:
            raise HTTPException(status_code=400, detail=f"unknown move status: {body.status!r}")

        def do_status() -> None:
            check_id(card_id)
            run_overseer(root, *verbs, card_id)

        return _mutate(do_status)

    @app.post("/api/config/threshold")
    def set_threshold(body: ThresholdBody) -> dict[str, Any]:
        def do() -> None:
            run_vigil(root, "config", "set", "context.threshold", str(body.value))

        return _mutate(do)

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
