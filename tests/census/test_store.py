import json
import os
import subprocess

import pytest

from scripts import store as st


def _payload(sid="s1", cwd="/wt/a", **extra):
    base = {"session_id": sid, "cwd": cwd}
    base.update(extra)
    return json.dumps(base)


def _read(store_file):
    return st.read_all()


_GIT_ENV = {
    # no global or system config (signing, hooks, templates) and fixed identities
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def _git(path, *args):
    subprocess.run(
        ["git", *args], cwd=str(path), check=True, capture_output=True, env={**os.environ, **_GIT_ENV}
    )


def _init_git_repo(path, branch=None):
    """Create a real git repo at ``path`` with one commit, on ``branch`` if given."""
    _git(path, "init")
    (path / "file.txt").write_text("hello")
    _git(path, "add", "file.txt")
    _git(path, "commit", "-m", "initial")
    if branch:
        _git(path, "checkout", "-b", branch)


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
    """The branch is read through the git cache; every git failure is a None."""

    @pytest.fixture
    def fake_repo(self, tmp_path):
        (tmp_path / ".git").mkdir()  # enough for the cache to decide git must run
        return tmp_path

    def _git_says(self, monkeypatch, returncode=0, stdout=""):
        class _Result:
            pass

        result = _Result()
        result.returncode, result.stdout = returncode, stdout
        monkeypatch.setattr(st.gitcache.subprocess, "run", lambda *a, **k: result)

    def test_none_cwd_returns_none_without_invoking_subprocess(self):
        assert st._git_branch(None) is None

    def test_subprocess_oserror_returns_none_not_raise(self, monkeypatch, fake_repo):
        def _boom(*args, **kwargs):
            raise OSError("git binary not found")

        monkeypatch.setattr(st.gitcache.subprocess, "run", _boom)
        assert st._git_branch(str(fake_repo)) is None

    def test_subprocess_timeout_returns_none_not_raise(self, monkeypatch, fake_repo):
        def _hang(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="git", timeout=1)

        monkeypatch.setattr(st.gitcache.subprocess, "run", _hang)
        assert st._git_branch(str(fake_repo)) is None

    def test_nonzero_returncode_returns_none(self, monkeypatch, fake_repo):
        self._git_says(monkeypatch, returncode=128)
        assert st._git_branch(str(fake_repo)) is None

    def test_detached_head_returns_none(self, monkeypatch, fake_repo):
        self._git_says(monkeypatch, stdout="# branch.oid 0123456789\n# branch.head (detached)\n")
        assert st._git_branch(str(fake_repo)) is None

    def test_blank_output_returns_none(self, monkeypatch, fake_repo):
        self._git_says(monkeypatch, stdout="   \n")
        assert st._git_branch(str(fake_repo)) is None

    def test_valid_output_is_the_branch(self, monkeypatch, fake_repo):
        self._git_says(monkeypatch, stdout="# branch.oid 0123456789\n# branch.head main\n")
        assert st._git_branch(str(fake_repo)) == "main"


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


class TestReviewRound2:
    def test_a_session_id_with_a_trailing_newline_is_refused(self):
        assert st.safe_session_id("abc\n") is None and st.safe_session_id("abc") == "abc"

    def test_an_oversized_number_is_unusable_not_a_crash(self):
        assert st._number(10**400) is None

    def test_an_oversized_timestamp_does_not_break_readers(self, store_file):
        st.ingest(_payload(sid="s1"), now=1.0)
        path = st.session_path("s1")
        path.write_text(path.read_text().replace('"updated_at": 1.0', '"updated_at": ' + "9" * 400))
        st.read_all()
        assert st.for_session("s1") is not None

    def test_deeply_nested_store_json_is_unreadable_not_fatal(self, store_file):
        st.ingest(_payload(sid="s1"), now=1.0)
        st.session_path("s1").write_text("[" * 200_000)
        assert st.for_session("s1") is None and "s1" not in st.read_all()["sessions"]

    def test_a_v1_store_named_limits_json_keeps_its_sessions(self, tmp_path, monkeypatch):
        legacy = tmp_path / "data" / "limits.json"
        legacy.parent.mkdir()
        legacy.write_text(json.dumps({
            "version": 1, "limits": None,
            "sessions": {"s1": {"worktree_cwd": "/wt/a", "updated_at": 5.0, "payload": {"session_id": "s1"}}},
        }))
        monkeypatch.setenv("CENSUS_STORE", str(legacy))
        assert "s1" in st.read_all()["sessions"]
