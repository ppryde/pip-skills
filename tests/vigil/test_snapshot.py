import subprocess

from scripts.snapshot import session_snapshot


def _git(path, *args):
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)


class TestSnapshot:
    def test_non_git_dir_has_cwd_only(self, tmp_path):
        snap = session_snapshot(tmp_path)
        assert str(tmp_path) in snap
        assert "## Git" not in snap  # no git section outside a repo

    def test_git_repo_reports_branch_and_status(self, tmp_path):
        _git(tmp_path, "init", "-q")
        _git(tmp_path, "config", "user.email", "t@t")
        _git(tmp_path, "config", "user.name", "t")
        (tmp_path / "committed.py").write_text("x = 1\n")
        _git(tmp_path, "add", "committed.py")
        _git(tmp_path, "commit", "-qm", "init")
        (tmp_path / "dirty.py").write_text("y = 2\n")  # untracked → shows in status
        snap = session_snapshot(tmp_path)
        assert "## Git" in snap
        assert "committed.py" in snap          # recently-modified tracked file
        assert "dirty.py" in snap              # short status shows the untracked file

    def test_limit_caps_file_list(self, tmp_path):
        _git(tmp_path, "init", "-q")
        _git(tmp_path, "config", "user.email", "t@t")
        _git(tmp_path, "config", "user.name", "t")
        for i in range(5):
            (tmp_path / f"f{i}.py").write_text(str(i))
        _git(tmp_path, "add", ".")
        _git(tmp_path, "commit", "-qm", "many")
        snap = session_snapshot(tmp_path, limit=2)
        listed = [ln for ln in snap.splitlines() if ln.strip().startswith("- ") and ".py" in ln]
        assert len(listed) <= 2
