import json
import subprocess

from scripts import store as st


def _payload(sid="s1", cwd="/wt/a", **extra):
    base = {"session_id": sid, "cwd": cwd}
    base.update(extra)
    return json.dumps(base)


def _read(store_file):
    return json.loads(store_file.read_text())


def _init_git_repo(path, branch=None):
    """Create a real git repo at ``path`` with one commit, on ``branch`` if given."""
    subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=str(path), check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), check=True, capture_output=True)
    (path / "file.txt").write_text("hello")
    subprocess.run(["git", "add", "file.txt"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=str(path), check=True, capture_output=True
    )
    if branch:
        subprocess.run(
            ["git", "checkout", "-b", branch], cwd=str(path), check=True, capture_output=True
        )


class TestGitBranchCapture:
    def test_ingest_records_branch_for_real_git_repo(self, store_file, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo, branch="feat/x")

        st.ingest(_payload(sid="abc", cwd=str(repo)), now=1.0)

        entry = _read(store_file)["sessions"]["abc"]
        assert entry["branch"] == "feat/x"

    def test_ingest_records_default_branch_when_none_checked_out(self, store_file, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)  # stays on whatever the default branch is (main/master)

        st.ingest(_payload(sid="abc", cwd=str(repo)), now=1.0)

        entry = _read(store_file)["sessions"]["abc"]
        # git init's default branch name varies by user config, but it must be
        # a real branch name, not None/HEAD.
        assert entry["branch"] not in (None, "HEAD")

    def test_non_git_cwd_yields_none_branch(self, store_file, tmp_path):
        plain_dir = tmp_path / "not_a_repo"
        plain_dir.mkdir()

        st.ingest(_payload(sid="abc", cwd=str(plain_dir)), now=1.0)

        entry = _read(store_file)["sessions"]["abc"]
        assert entry["branch"] is None

    def test_missing_cwd_yields_none_branch(self, store_file):
        st.ingest(_payload(sid="abc", cwd="/definitely/does/not/exist/anywhere"), now=1.0)

        entry = _read(store_file)["sessions"]["abc"]
        assert entry["branch"] is None


class TestGitBranchFailSafe:
    def test_none_cwd_returns_none_without_invoking_subprocess(self):
        assert st._git_branch(None) is None

    def test_subprocess_oserror_returns_none_not_raise(self, monkeypatch, tmp_path):
        def _boom(*args, **kwargs):
            raise OSError("git binary not found")

        monkeypatch.setattr(st.subprocess, "run", _boom)
        assert st._git_branch(str(tmp_path)) is None

    def test_subprocess_timeout_returns_none_not_raise(self, monkeypatch, tmp_path):
        def _hang(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="git", timeout=2)

        monkeypatch.setattr(st.subprocess, "run", _hang)
        assert st._git_branch(str(tmp_path)) is None

    def test_nonzero_returncode_returns_none(self, monkeypatch, tmp_path):
        class _Result:
            returncode = 128
            stdout = ""

        monkeypatch.setattr(st.subprocess, "run", lambda *a, **k: _Result())
        assert st._git_branch(str(tmp_path)) is None

    def test_detached_head_returns_none(self, monkeypatch, tmp_path):
        class _Result:
            returncode = 0
            stdout = "HEAD\n"

        monkeypatch.setattr(st.subprocess, "run", lambda *a, **k: _Result())
        assert st._git_branch(str(tmp_path)) is None

    def test_blank_output_returns_none(self, monkeypatch, tmp_path):
        class _Result:
            returncode = 0
            stdout = "   \n"

        monkeypatch.setattr(st.subprocess, "run", lambda *a, **k: _Result())
        assert st._git_branch(str(tmp_path)) is None

    def test_valid_output_is_stripped(self, monkeypatch, tmp_path):
        class _Result:
            returncode = 0
            stdout = "main\n"

        monkeypatch.setattr(st.subprocess, "run", lambda *a, **k: _Result())
        assert st._git_branch(str(tmp_path)) == "main"


class TestMergeBackwardCompatibility:
    def test_merge_still_works_without_branch_key_in_prior_store(self, store_file):
        """An entry written before this feature existed (no ``branch`` key) must
        not break a subsequent merge/read cycle."""
        store = st._empty_store()
        store["sessions"]["abc"] = {
            "worktree_cwd": "/wt/a",
            "updated_at": 1.0,
            "payload": {"session_id": "abc", "cwd": "/wt/a"},
        }
        result = st.merge(store, {"session_id": "abc", "cwd": "/wt/a"}, "/wt/a", None, 2.0)
        assert result["sessions"]["abc"]["branch"] is None
