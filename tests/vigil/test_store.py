from scripts.store import VIGIL_DIRNAME, _uniquify, ensure_root, vigil_root


class TestRoot:
    def test_vigil_root_path(self, tmp_path):
        assert vigil_root(tmp_path) == tmp_path / ".vigil"

    def test_ensure_creates_dir(self, tmp_path):
        root = ensure_root(tmp_path)
        assert root.is_dir()
        assert root == tmp_path / ".vigil"

    def test_ensure_adds_gitignore_entry(self, tmp_path):
        ensure_root(tmp_path)
        assert f"{VIGIL_DIRNAME}/" in (tmp_path / ".gitignore").read_text().split("\n")

    def test_ensure_gitignore_idempotent(self, tmp_path):
        (tmp_path / ".gitignore").write_text(".vigil/\n")
        ensure_root(tmp_path)
        assert (tmp_path / ".gitignore").read_text().count(".vigil/") == 1

    def test_ensure_appends_without_clobbering(self, tmp_path):
        (tmp_path / ".gitignore").write_text("node_modules/\n")
        ensure_root(tmp_path)
        text = (tmp_path / ".gitignore").read_text()
        assert "node_modules/" in text and ".vigil/" in text


class TestUniquify:
    def test_free_path_unchanged(self, tmp_path):
        assert _uniquify(tmp_path / "a.md") == tmp_path / "a.md"

    def test_collision_gets_suffix(self, tmp_path):
        (tmp_path / "a.md").write_text("x")
        assert _uniquify(tmp_path / "a.md") == tmp_path / "a.1.md"
