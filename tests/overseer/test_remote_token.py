import os
import stat

from scripts.remote_token import read_remote_token, remote_token_path, write_remote_token


def test_path_shape(tmp_path):
    assert remote_token_path(tmp_path) == tmp_path / ".overseer" / "remote-token"


def test_read_missing_returns_none(tmp_path):
    assert read_remote_token(tmp_path) is None


def test_read_blank_returns_none(tmp_path):
    p = remote_token_path(tmp_path)
    p.parent.mkdir(parents=True)
    p.write_text("   \n")
    assert read_remote_token(tmp_path) is None


def test_write_then_read_roundtrip(tmp_path):
    returned = write_remote_token(tmp_path, "tok-abc")
    assert returned == remote_token_path(tmp_path)
    assert read_remote_token(tmp_path) == "tok-abc"


def test_write_creates_overseer_dir_and_is_0600(tmp_path):
    p = write_remote_token(tmp_path, "tok-xyz")
    assert p.parent.name == ".overseer" and p.parent.is_dir()
    mode = stat.S_IMODE(p.stat().st_mode)
    assert mode == 0o600, oct(mode)


def test_write_tightens_preexisting_loose_mode(tmp_path):
    p = remote_token_path(tmp_path)
    p.parent.mkdir(parents=True)
    p.write_text("old")
    p.chmod(0o644)
    write_remote_token(tmp_path, "new")
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert read_remote_token(tmp_path) == "new"


def test_read_non_utf8_returns_none(tmp_path):
    p = remote_token_path(tmp_path)
    p.parent.mkdir(parents=True)
    p.write_bytes(b"\xff\xfe\x00\x01corrupt")
    assert read_remote_token(tmp_path) is None


# --- WF-100 C7: hardened writer, strict server-side reader ------------------


def test_write_refuses_a_symlinked_overseer_dir(tmp_path):
    import pytest

    target = tmp_path / "elsewhere"
    target.mkdir()
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".overseer").symlink_to(target)
    with pytest.raises(OSError):
        write_remote_token(root, "tok-abcdefghijklmnop")
    assert list(target.iterdir()) == []


def test_write_never_follows_a_symlinked_token_path(tmp_path):
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("precious")
    p = remote_token_path(tmp_path)
    p.parent.mkdir(parents=True)
    p.symlink_to(sentinel)
    write_remote_token(tmp_path, "tok-abcdefghijklmnop")
    assert sentinel.read_text() == "precious"
    assert not p.is_symlink()
    assert p.read_text() == "tok-abcdefghijklmnop"
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_write_leaves_no_temp_files(tmp_path):
    write_remote_token(tmp_path, "tok-abcdefghijklmnop")
    assert [x.name for x in remote_token_path(tmp_path).parent.iterdir()] == ["remote-token"]


def test_server_reader_accepts_an_own_0600_file(tmp_path):
    from scripts.remote_token import read_server_token

    write_remote_token(tmp_path, "tok-abcdefghijklmnop")
    assert read_server_token(tmp_path) == "tok-abcdefghijklmnop"


def test_server_reader_ignores_symlink_wide_mode_and_foreign_owner(tmp_path, monkeypatch):
    from scripts import remote_token
    from scripts.remote_token import read_server_token

    p = remote_token_path(tmp_path)
    p.parent.mkdir(parents=True)
    real = tmp_path / "real"
    real.write_text("tok-abcdefghijklmnop")
    real.chmod(0o600)
    p.symlink_to(real)
    assert read_server_token(tmp_path) is None  # symlink
    p.unlink()
    p.write_text("tok-abcdefghijklmnop")
    p.chmod(0o644)
    assert read_server_token(tmp_path) is None  # wide mode
    p.chmod(0o600)
    assert read_server_token(tmp_path) == "tok-abcdefghijklmnop"
    other = os.getuid() + 1
    monkeypatch.setattr(remote_token.os, "getuid", lambda: other)
    assert read_server_token(tmp_path) is None  # not ours


def test_server_reader_ignores_a_symlinked_overseer_dir(tmp_path):
    from scripts.remote_token import read_server_token

    real = tmp_path / "real"
    real.mkdir()
    (real / "remote-token").write_text("tok-abcdefghijklmnop")
    (real / "remote-token").chmod(0o600)
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".overseer").symlink_to(real)
    assert read_server_token(root) is None
