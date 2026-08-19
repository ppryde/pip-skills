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
