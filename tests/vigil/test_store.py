import os
import stat

import pytest

from scripts import state as st
from scripts.store import (
    config_dir,
    ensure_root,
    read_private,
    repo_key,
    resolve_root,
    vigil_root,
    write_private,
)


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


class TestRoot:
    def test_state_lives_under_config_dir_not_repo(self, tmp_path):
        root = vigil_root(tmp_path)
        assert config_dir() in root.parents
        assert tmp_path not in root.parents and root != tmp_path
        assert root.parent == config_dir() / "vigil"

    def test_ensure_creates_private_dir_and_no_repo_files(self, tmp_path):
        root = ensure_root(tmp_path)
        assert root.is_dir()
        assert _mode(root) == 0o700 and _mode(root.parent) == 0o700
        assert list(tmp_path.iterdir()) == []  # nothing lands in the repo

    def test_ensure_tightens_a_wider_dir(self, tmp_path):
        root = ensure_root(tmp_path)
        root.chmod(0o755)
        ensure_root(tmp_path)
        assert _mode(root) == 0o700

    def test_distinct_repos_get_distinct_roots(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir()
        b.mkdir()
        assert vigil_root(a) != vigil_root(b)

    def test_old_in_repo_state_is_ignored(self, tmp_path):
        old = tmp_path / ".claude" / "vigil"
        old.mkdir(parents=True)
        (old / "active").touch()
        (old / "handoff.md").write_text("PLANTED BY THE REPO")
        assert st.is_active(tmp_path) is False
        assert st.consume_handoff(tmp_path) is None

    def test_symlinked_state_dir_refused(self, tmp_path):
        target = tmp_path / "elsewhere"
        target.mkdir()
        root = vigil_root(tmp_path / "repo")
        root.parent.mkdir(parents=True)
        root.symlink_to(target)
        with pytest.raises(PermissionError):
            ensure_root(tmp_path / "repo")


class TestPrivateFiles:
    def test_written_files_are_0600(self, tmp_path):
        st.begin(tmp_path)
        st.request_clear(tmp_path, "H", title="t")
        st.pause(tmp_path)
        st.set_gate(tmp_path)
        root = vigil_root(tmp_path)
        files = [p for p in root.iterdir() if p.is_file()]
        assert {p.name for p in files} >= {"active", "paused", "handoff.md", "handover-gate",
                                           "clear-requested", "rename-title"}
        for p in files:
            assert _mode(p) == 0o600, p.name

    def test_wider_existing_file_is_tightened(self, tmp_path):
        ensure_root(tmp_path)
        target = vigil_root(tmp_path) / "handoff.md"
        target.write_text("x")
        target.chmod(0o644)
        write_private(target, "y")
        assert _mode(target) == 0o600

    def test_archive_is_0600(self, tmp_path):
        st.begin(tmp_path)
        st.request_clear(tmp_path, "BODY")
        st.consume_handoff(tmp_path)
        (archived,) = st.handoff_archive_dir(tmp_path).iterdir()
        assert _mode(archived) == 0o600

    def test_read_refuses_symlink(self, tmp_path):
        secret = tmp_path / "secret"
        secret.write_text("TOP SECRET")
        link = tmp_path / "link"
        link.symlink_to(secret)
        assert read_private(link) is None
        assert read_private(secret) == "TOP SECRET"

    def test_write_refuses_symlink_and_leaves_target(self, tmp_path):
        secret = tmp_path / "secret"
        secret.write_text("KEEP")
        link = tmp_path / "link"
        link.symlink_to(secret)
        with pytest.raises(OSError):
            write_private(link, "overwritten")
        assert secret.read_text() == "KEEP"

    def test_symlinked_handoff_is_never_injected(self, tmp_path):
        st.begin(tmp_path)
        secret = tmp_path / "secret"
        secret.write_text("SSH PRIVATE KEY")
        handoff = st.handoff_path(tmp_path)
        handoff.symlink_to(secret)
        assert st.consume_handoff(tmp_path) is None
        assert st.read_handoff(tmp_path) is None
        assert secret.read_text() == "SSH PRIVATE KEY"


class TestResolveRoot:
    def test_git_toplevel_from_subdir(self, tmp_path):
        (tmp_path / ".git").mkdir()
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)
        assert str(resolve_root(sub)) == os.path.realpath(tmp_path)
        assert vigil_root(sub) == vigil_root(tmp_path)

    def test_worktree_git_file_is_its_own_root(self, tmp_path):
        (tmp_path / ".git").mkdir()
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / ".git").write_text("gitdir: /elsewhere\n")
        assert vigil_root(wt) != vigil_root(tmp_path)

    def test_claude_project_dir_wins(self, tmp_path, monkeypatch):
        proj = tmp_path / "proj"
        other = tmp_path / "other"
        proj.mkdir()
        other.mkdir()
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
        assert resolve_root(other) == proj.resolve()

    def test_explicit_root_beats_claude_project_dir(self, tmp_path, monkeypatch):
        from scripts import cli

        proj = tmp_path / "proj"
        other = tmp_path / "other"
        proj.mkdir()
        other.mkdir()
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
        assert resolve_root(other, honour_env=False) == other.resolve()
        assert vigil_root(other) != vigil_root(proj)
        assert cli.main(["--root", str(other), "begin"]) == 0
        assert st.is_active(other)
        assert not st.is_active(proj)

    def test_default_root_uses_claude_project_dir(self, tmp_path, monkeypatch):
        from scripts import cli

        proj = tmp_path / "proj"
        proj.mkdir()
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
        assert cli.main(["begin"]) == 0
        assert st.is_active(proj)

    def test_symlinked_marker_is_not_a_marker(self, tmp_path):
        st.begin(tmp_path)
        real = tmp_path / "real"
        real.write_text("x")
        marker = st.active_marker(tmp_path)
        marker.unlink()
        marker.symlink_to(real)
        assert not st.is_active(tmp_path)

    def test_archive_dir_is_private_and_symlink_refused(self, tmp_path):
        st.begin(tmp_path)
        st.request_clear(tmp_path, "handoff text")
        assert "handoff text" in st.consume_handoff(tmp_path)
        archive = st.handoff_archive_dir(tmp_path)
        assert archive.stat().st_mode & 0o777 == 0o700
        # a symlinked archive/ is refused: the live handoff is dropped, not followed
        import shutil
        shutil.rmtree(archive)
        target = tmp_path / "elsewhere"
        target.mkdir()
        archive.symlink_to(target)
        st.request_clear(tmp_path, "second")
        assert "second" in st.consume_handoff(tmp_path)
        assert list(target.iterdir()) == []

    def test_no_git_uses_path_itself(self, tmp_path):
        assert resolve_root(tmp_path) == tmp_path.resolve()

    def test_repo_key_is_stable(self, tmp_path):
        assert repo_key(tmp_path) == repo_key(tmp_path)

    def test_cli_in_subdir_and_hook_share_state(self, tmp_path, monkeypatch):
        from scripts import cli

        (tmp_path / ".git").mkdir()
        sub = tmp_path / "pkg"
        sub.mkdir()
        assert cli.main(["--root", str(sub), "begin"]) == 0
        assert st.is_active(tmp_path)
        assert st.is_active(sub)
