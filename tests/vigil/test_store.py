from scripts.store import _uniquify, ensure_root, vigil_root


class TestRoot:
    def test_vigil_root_path(self, tmp_path):
        assert vigil_root(tmp_path) == tmp_path / ".claude" / "vigil"

    def test_ensure_creates_dir(self, tmp_path):
        root = ensure_root(tmp_path)
        assert root.is_dir()
        assert root == tmp_path / ".claude" / "vigil"

    def test_ensure_adds_self_contained_gitignore(self, tmp_path):
        root = ensure_root(tmp_path)
        assert (root / ".gitignore").read_text() == "*\n"

    def test_ensure_gitignore_idempotent(self, tmp_path):
        root = ensure_root(tmp_path)
        (root / ".gitignore").write_text("*\ncustom\n")
        ensure_root(tmp_path)
        assert (root / ".gitignore").read_text() == "*\ncustom\n"

    def test_ensure_does_not_touch_repo_gitignore(self, tmp_path):
        (tmp_path / ".gitignore").write_text("node_modules/\n")
        ensure_root(tmp_path)
        assert (tmp_path / ".gitignore").read_text() == "node_modules/\n"

    def test_ensure_creates_no_repo_gitignore_when_absent(self, tmp_path):
        ensure_root(tmp_path)
        assert not (tmp_path / ".gitignore").exists()


class TestUniquify:
    def test_free_path_unchanged(self, tmp_path):
        assert _uniquify(tmp_path / "a.md") == tmp_path / "a.md"

    def test_collision_gets_suffix(self, tmp_path):
        (tmp_path / "a.md").write_text("x")
        assert _uniquify(tmp_path / "a.md") == tmp_path / "a.1.md"
