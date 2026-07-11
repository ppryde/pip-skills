"""FastAPI app factory for the overseer dashboard backend.

`create_app(root)` wires `/api` routes that shell the overseer/vigil CLIs
(see `app.cli_client`) against `root`, plus a static mount / placeholder for
the (separately built) frontend `dist/` (chunk 4). This module is a CLIENT
of the CLIs only — it never imports overseer/vigil internals and never
touches `.workflow/` directly.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.cli_client import CliError, _check_id, run_overseer, run_vigil

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


def _board_response(root: Path) -> dict[str, Any]:
    """The payload every read AND every mutation returns.

    Vigil calls are wrapped so a vigil CliError never 500s the board read —
    it degrades to pct/threshold = None.
    """
    board = run_overseer(root, "board", "--json", json_out=True)
    return {
        "board": board,
        "context": {
            "pct": _context_pct(root),
            "threshold": _context_threshold(root),
        },
    }


def _show_error(exc: CliError) -> HTTPException:
    """GET /api/card/{id} mapping: 1 (not found) -> 404, else -> 400/504."""
    if exc.returncode == 504:
        return HTTPException(status_code=504, detail=exc.stderr)
    if exc.returncode == 1:
        return HTTPException(status_code=404, detail=exc.stderr)
    return HTTPException(status_code=400, detail=exc.stderr)


def _mutation_error(exc: CliError) -> HTTPException:
    """Mutation mapping: timeout -> 504, everything else (incl. id validation) -> 400."""
    if exc.returncode == 504:
        return HTTPException(status_code=504, detail=exc.stderr)
    return HTTPException(status_code=400, detail=exc.stderr)


def create_app(root: Path) -> FastAPI:
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

    @app.get("/api/card/{card_id}")
    def get_card(card_id: str) -> Any:
        try:
            _check_id(card_id)
            return run_overseer(root, "show", card_id, "--json", json_out=True)
        except CliError as exc:
            raise _show_error(exc) from exc

    @app.post("/api/card/{card_id}/order")
    def set_order(card_id: str, body: OrderBody) -> dict[str, Any]:
        def do() -> None:
            _check_id(card_id)
            run_overseer(root, "set-field", card_id, "--order", str(body.order))

        return _mutate(do)

    @app.post("/api/card/{card_id}/priority")
    def set_priority(card_id: str, body: PriorityBody) -> dict[str, Any]:
        def do() -> None:
            _check_id(card_id)
            value = body.priority if body.priority is not None else ""
            run_overseer(root, "set-field", card_id, "--priority", value)

        return _mutate(do)

    @app.post("/api/card/{card_id}/parent")
    def set_parent(card_id: str, body: ParentBody) -> dict[str, Any]:
        def do() -> None:
            _check_id(card_id)
            value = body.parent if body.parent is not None else ""
            run_overseer(root, "set-field", card_id, "--parent", value)

        return _mutate(do)

    @app.post("/api/card/{card_id}/depends")
    def set_depends(card_id: str, body: DependsBody) -> dict[str, Any]:
        if body.on is None and body.off is None:
            raise HTTPException(status_code=400, detail="on or off required")

        def do() -> None:
            _check_id(card_id)
            args = ["depends", card_id]
            if body.on is not None:
                _check_id(body.on)
                args += ["--on", body.on]
            if body.off is not None:
                _check_id(body.off)
                args += ["--off", body.off]
            run_overseer(root, *args)

        return _mutate(do)

    @app.post("/api/card/{card_id}/park")
    def park_card(card_id: str) -> dict[str, Any]:
        def do() -> None:
            _check_id(card_id)
            run_overseer(root, "park", card_id)

        return _mutate(do)

    @app.post("/api/card/{card_id}/unpark")
    def unpark_card(card_id: str) -> dict[str, Any]:
        def do() -> None:
            _check_id(card_id)
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
                _check_id(card_id)
                run_overseer(root, "set-stage", card_id, body.stage)  # type: ignore[arg-type]

            return _mutate(do_stage)

        if body.status == "blocked":
            if not body.reason:
                raise HTTPException(status_code=400, detail="reason required to block")

            def do_block() -> None:
                _check_id(card_id)
                run_overseer(root, "block", card_id, "--reason", body.reason)  # type: ignore[arg-type]

            return _mutate(do_block)

        verbs = _MOVE_STATUS_VERBS.get(body.status or "")
        if verbs is None:
            raise HTTPException(status_code=400, detail=f"unknown move status: {body.status!r}")

        def do_status() -> None:
            _check_id(card_id)
            run_overseer(root, *verbs, card_id)

        return _mutate(do_status)

    @app.post("/api/config/threshold")
    def set_threshold(body: ThresholdBody) -> dict[str, Any]:
        def do() -> None:
            run_vigil(root, "config", "set", "context.threshold", str(body.value))

        return _mutate(do)

    return app
