import os

from scripts.resolve import normalise, worktree_cwd


class TestWorktreeCwd:
    def test_worktree_path_wins(self, tmp_path):
        payload = {
            "worktree": {"path": str(tmp_path)},
            "workspace": {"current_dir": "/other"},
            "cwd": "/another",
        }
        assert worktree_cwd(payload) == normalise(str(tmp_path))

    def test_workspace_current_dir_when_no_worktree(self, tmp_path):
        payload = {"workspace": {"current_dir": str(tmp_path)}, "cwd": "/another"}
        assert worktree_cwd(payload) == normalise(str(tmp_path))

    def test_cwd_last_resort(self, tmp_path):
        assert worktree_cwd({"cwd": str(tmp_path)}) == normalise(str(tmp_path))

    def test_none_when_nothing_present(self):
        assert worktree_cwd({"session_id": "x"}) is None

    def test_ignores_non_string_and_empty(self, tmp_path):
        payload = {
            "worktree": {"path": ""},
            "workspace": {"current_dir": None},
            "cwd": str(tmp_path),
        }
        assert worktree_cwd(payload) == normalise(str(tmp_path))

    def test_trailing_slash_collapses(self, tmp_path):
        with_slash = worktree_cwd({"cwd": str(tmp_path) + "/"})
        without = worktree_cwd({"cwd": str(tmp_path)})
        assert with_slash == without

    def test_symlink_collapses_to_real_path(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        os.symlink(real, link)
        assert worktree_cwd({"cwd": str(link)}) == worktree_cwd({"cwd": str(real)})
