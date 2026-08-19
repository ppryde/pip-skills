import importlib.util
from pathlib import Path

# Load the launcher module by path (it lives above the backend package).
_LAUNCHER = Path(__file__).resolve().parents[2] / "serve_board_api.py"
_spec = importlib.util.spec_from_file_location("serve_board_api", _LAUNCHER)
serve_board_api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(serve_board_api)


def test_resolve_remote_token_env_wins(monkeypatch):
    monkeypatch.setenv("OVERSEER_REMOTE_TOKEN", "fixed")
    assert serve_board_api.resolve_remote_token("0.0.0.0") == "fixed"
    assert serve_board_api.resolve_remote_token("127.0.0.1") == "fixed"


def test_resolve_remote_token_autogen_on_non_loopback(monkeypatch):
    monkeypatch.delenv("OVERSEER_REMOTE_TOKEN", raising=False)
    tok = serve_board_api.resolve_remote_token("0.0.0.0")
    assert tok and len(tok) >= 20


def test_resolve_remote_token_none_on_loopback(monkeypatch):
    monkeypatch.delenv("OVERSEER_REMOTE_TOKEN", raising=False)
    assert serve_board_api.resolve_remote_token("127.0.0.1") is None


def test_parse_args_defaults():
    args = serve_board_api.parse_args([])
    assert args.host == "0.0.0.0"
    assert args.port == 8771
    assert args.root == "."
