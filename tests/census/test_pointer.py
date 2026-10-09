import io
import os
import sys
from pathlib import Path

from scripts import cli
from scripts import install as ins
from scripts import store as st

PAYLOAD = '{"session_id": "s1", "cwd": "/wt/a"}'


def _ingest(monkeypatch, payload=PAYLOAD):
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    return cli.main(["ingest"])


def test_pointer_path_is_inside_census_dir(store_file):
    assert st.pointer_path() == store_file.parent / "cli.path"


def test_ingest_publishes_resolved_cli_path(store_file, monkeypatch):
    assert _ingest(monkeypatch) == 0
    recorded = st.pointer_path().read_bytes().decode("utf-8")
    assert recorded == str(Path(cli.__file__).resolve())


def test_same_path_is_not_rewritten(store_file, monkeypatch):
    _ingest(monkeypatch)
    pointer = st.pointer_path()
    replaced = []
    real = os.replace
    monkeypatch.setattr(os, "replace", lambda src, dst, *a, **k: (replaced.append(str(dst)), real(src, dst))[1])
    _ingest(monkeypatch)
    assert str(pointer) not in replaced  # mtime granularity cannot hide a rewrite from a spy


def test_different_recorded_path_is_replaced(store_file, monkeypatch):
    store_file.parent.mkdir(parents=True, exist_ok=True)
    st.pointer_path().write_bytes(b"/old/place/cli.py")
    _ingest(monkeypatch)
    assert st.pointer_path().read_bytes().decode() == str(Path(cli.__file__).resolve())


def test_unwritable_census_dir_does_not_fail_ingest(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory")
    monkeypatch.setenv("CENSUS_STORE", str(blocker / "census"))
    assert _ingest(monkeypatch) == 0
    st.publish_location(Path("/x/cli.py"))  # must not raise


def test_publish_location_swallows_write_errors(store_file, monkeypatch):
    def boom(*_a, **_k):
        raise OSError("nope")

    monkeypatch.setattr(os, "replace", boom)
    st.publish_location(Path("/x/cli.py"))


def test_purge_removes_pointer(tmp_path):
    data = tmp_path / "census"
    data.mkdir()
    (data / "cli.path").write_text("/x/cli.py")
    ins._purge(data, True)
    assert not data.exists()
