"""Tests for the dashboard launcher (`dashboard/serve.py`).

`serve.py` lives one directory up from this backend package (in
`dashboard/`), so it isn't reachable through the backend's own
`pythonpath=["."]` pytest config. Add `dashboard/` to `sys.path` before
importing it, mirroring what `serve.py` itself does for `backend/`.

None of these tests bind a real port or open a real browser: `uvicorn.run`,
`webbrowser.open` and `threading.Timer` are all patched.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_DASHBOARD_DIR = Path(__file__).resolve().parents[2]
if str(_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_DIR))

import serve  # noqa: E402  (import must follow the sys.path setup above)


# --- argument parsing ------------------------------------------------------


def test_parse_args_defaults() -> None:
    args = serve.parse_args([])

    assert args.root == "."
    assert args.host == "127.0.0.1"
    assert args.port == serve.DEFAULT_PORT
    assert args.no_browser is False


def test_parse_args_overrides() -> None:
    args = serve.parse_args(
        ["--root", "/tmp/somewhere", "--host", "0.0.0.0", "--port", "9999", "--no-browser"]
    )

    assert args.root == "/tmp/somewhere"
    assert args.host == "0.0.0.0"
    assert args.port == 9999
    assert args.no_browser is True


def test_parse_args_help_exits_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        serve.parse_args(["--help"])

    assert exc_info.value.code == 0
    assert "--no-browser" in capsys.readouterr().out


# --- main(): app construction + uvicorn wiring ------------------------------


def test_main_builds_app_from_resolved_root_and_runs_uvicorn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sentinel_app = object()
    fake_create_app = MagicMock(return_value=sentinel_app)
    fake_run = MagicMock()
    monkeypatch.setattr(serve, "create_app", fake_create_app)
    monkeypatch.setattr(serve.uvicorn, "run", fake_run)
    monkeypatch.setattr(serve.threading, "Timer", MagicMock())

    rc = serve.main(["--root", str(tmp_path), "--port", "9001", "--no-browser"])

    assert rc == 0
    fake_create_app.assert_called_once_with(tmp_path.resolve())
    fake_run.assert_called_once_with(sentinel_app, host="127.0.0.1", port=9001)


def test_main_passes_through_custom_host(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_run = MagicMock()
    monkeypatch.setattr(serve, "create_app", MagicMock(return_value=object()))
    monkeypatch.setattr(serve.uvicorn, "run", fake_run)
    monkeypatch.setattr(serve.threading, "Timer", MagicMock())

    serve.main(["--root", str(tmp_path), "--host", "0.0.0.0", "--port", "8080", "--no-browser"])

    fake_run.assert_called_once_with(fake_run.call_args.args[0], host="0.0.0.0", port=8080)


# --- browser open behaviour --------------------------------------------------


def test_main_schedules_browser_open_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(serve, "create_app", MagicMock(return_value=object()))
    monkeypatch.setattr(serve.uvicorn, "run", MagicMock())
    fake_timer_cls = MagicMock()
    monkeypatch.setattr(serve.threading, "Timer", fake_timer_cls)

    serve.main(["--root", str(tmp_path), "--port", "8770"])

    fake_timer_cls.assert_called_once()
    (_delay, function), kwargs = fake_timer_cls.call_args
    assert function is serve._open_browser
    assert kwargs["args"] == ("http://127.0.0.1:8770/",)
    fake_timer_cls.return_value.start.assert_called_once()


def test_main_no_browser_skips_scheduling(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(serve, "create_app", MagicMock(return_value=object()))
    monkeypatch.setattr(serve.uvicorn, "run", MagicMock())
    fake_timer_cls = MagicMock()
    monkeypatch.setattr(serve.threading, "Timer", fake_timer_cls)

    serve.main(["--root", str(tmp_path), "--no-browser"])

    fake_timer_cls.assert_not_called()


def test_open_browser_opens_the_given_url(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_open = MagicMock()
    monkeypatch.setattr(serve.webbrowser, "open", fake_open)

    serve._open_browser("http://127.0.0.1:8770/")

    fake_open.assert_called_once_with("http://127.0.0.1:8770/")


def test_open_browser_swallows_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(_url: str) -> None:
        raise RuntimeError("no display available")

    monkeypatch.setattr(serve.webbrowser, "open", _raise)

    serve._open_browser("http://127.0.0.1:8770/")  # must not raise
