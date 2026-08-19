import importlib.util
from pathlib import Path

# Load the launcher module by path (it lives above the backend package).
_LAUNCHER = Path(__file__).resolve().parents[2] / "serve_board_api.py"
_spec = importlib.util.spec_from_file_location("serve_board_api", _LAUNCHER)
serve_board_api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(serve_board_api)


def test_resolve_remote_token_env_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("OVERSEER_REMOTE_TOKEN", "fixed")
    assert serve_board_api.resolve_remote_token("0.0.0.0", tmp_path) == "fixed"
    assert serve_board_api.resolve_remote_token("127.0.0.1", tmp_path) == "fixed"
    assert not (tmp_path / ".overseer" / "remote-token").exists()  # env path writes nothing


def test_resolve_remote_token_none_on_loopback(monkeypatch, tmp_path):
    monkeypatch.delenv("OVERSEER_REMOTE_TOKEN", raising=False)
    assert serve_board_api.resolve_remote_token("127.0.0.1", tmp_path) is None
    assert not (tmp_path / ".overseer" / "remote-token").exists()


def test_resolve_remote_token_generates_and_persists_on_non_loopback(monkeypatch, tmp_path):
    monkeypatch.delenv("OVERSEER_REMOTE_TOKEN", raising=False)
    tok = serve_board_api.resolve_remote_token("0.0.0.0", tmp_path)
    assert tok and len(tok) >= 20
    from scripts.remote_token import read_remote_token
    assert read_remote_token(tmp_path) == tok  # persisted for the container to read


def test_resolve_remote_token_reuses_existing_file(monkeypatch, tmp_path):
    monkeypatch.delenv("OVERSEER_REMOTE_TOKEN", raising=False)
    from scripts.remote_token import write_remote_token
    write_remote_token(tmp_path, "persisted-tok")
    assert serve_board_api.resolve_remote_token("0.0.0.0", tmp_path) == "persisted-tok"  # stable across restarts


def test_startup_token_lines_no_token():
    assert serve_board_api._startup_token_lines(None, None, Path("/x")) == []


def test_startup_token_lines_env_token_omits_file_line(tmp_path):
    # OVERSEER_REMOTE_TOKEN never gets a file written for it — the file-location
    # line would point at a path nothing wrote, so it must not print.
    lines = serve_board_api._startup_token_lines("env-tok", "env-tok", tmp_path)
    assert lines == ["board API token: env-tok"]


def test_startup_token_lines_file_token_includes_file_line(tmp_path):
    lines = serve_board_api._startup_token_lines("gen-tok", None, tmp_path)
    assert lines[0] == "board API token: gen-tok"
    assert len(lines) == 2
    assert "token file" in lines[1]
    assert str(tmp_path) in lines[1]


def test_parse_args_defaults():
    args = serve_board_api.parse_args([])
    assert args.host == "0.0.0.0"
    assert args.port == 8771
    assert args.root == "."
