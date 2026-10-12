import subprocess
from types import SimpleNamespace

import pytest
from context_vigil import census as st

from .conftest import census_payload as _payload
from .conftest import read_store as _read


def _init_git_repo(path, branch=None):
    """Create a real git repo at ``path`` with one commit, on ``branch`` if given."""
    subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(path), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=str(path), check=True, capture_output=True
    )
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

    @pytest.mark.parametrize("returncode, stdout, expected", [
        pytest.param(128, "", None, id="nonzero_returncode"),
        pytest.param(0, "HEAD\n", None, id="detached_head"),
        pytest.param(0, "   \n", None, id="blank_output"),
        pytest.param(0, "main\n", "main", id="valid_output_is_stripped"),
    ])
    def test_git_output_is_interpreted(self, monkeypatch, tmp_path, returncode, stdout, expected):
        result = SimpleNamespace(returncode=returncode, stdout=stdout)
        monkeypatch.setattr(st.subprocess, "run", lambda *a, **k: result)
        assert st._git_branch(str(tmp_path)) == expected


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


class TestBranchCacheAndWriteSkip:
    """CV-6 (WF-268 lean bundle): the branch is cached by .git/HEAD's stamp, and a
    render that moved only ``updated_at`` does not rewrite the store."""

    def _repo(self, tmp_path, branch="feat/x"):
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo, branch=branch)
        return repo

    def test_unchanged_head_does_not_spawn_git(self, store_file, tmp_path, monkeypatch):
        repo = self._repo(tmp_path)
        st.ingest(_payload(sid="abc", cwd=str(repo)), now=1.0)
        calls = []
        real = st._git_branch
        monkeypatch.setattr(st, "_git_branch", lambda cwd: calls.append(cwd) or real(cwd))
        st.ingest(_payload(sid="abc", cwd=str(repo)), now=2.0)
        assert calls == []
        assert _read(store_file)["sessions"]["abc"]["branch"] == "feat/x"

    def test_branch_switch_is_noticed(self, store_file, tmp_path):
        repo = self._repo(tmp_path)
        st.ingest(_payload(sid="abc", cwd=str(repo)), now=1.0)
        subprocess.run(["git", "checkout", "-b", "feat/y"], cwd=str(repo), check=True,
                       capture_output=True)
        st.ingest(_payload(sid="abc", cwd=str(repo)), now=2.0)
        assert _read(store_file)["sessions"]["abc"]["branch"] == "feat/y"

    def test_linked_worktree_head_is_followed(self, store_file, tmp_path):
        repo = self._repo(tmp_path)
        wt = tmp_path / "wt"
        subprocess.run(["git", "worktree", "add", "-b", "wt/one", str(wt)], cwd=str(repo),
                       check=True, capture_output=True)
        st.ingest(_payload(sid="abc", cwd=str(wt)), now=1.0)
        assert _read(store_file)["sessions"]["abc"]["branch"] == "wt/one"
        subprocess.run(["git", "checkout", "-b", "wt/two"], cwd=str(wt), check=True,
                       capture_output=True)
        st.ingest(_payload(sid="abc", cwd=str(wt)), now=2.0)
        assert _read(store_file)["sessions"]["abc"]["branch"] == "wt/two"

    def test_cwd_change_does_not_reuse_another_repos_branch(self, store_file, tmp_path):
        a = self._repo(tmp_path, "feat/a")
        b = tmp_path / "b"
        b.mkdir()
        _init_git_repo(b, branch="feat/b")
        st.ingest(_payload(sid="abc", cwd=str(a)), now=1.0)
        st.ingest(_payload(sid="abc", cwd=str(b)), now=2.0)
        assert _read(store_file)["sessions"]["abc"]["branch"] == "feat/b"

    def test_failed_branch_lookup_is_retried_next_render(self, store_file, tmp_path, monkeypatch):
        repo = self._repo(tmp_path)
        real = st._git_branch
        monkeypatch.setattr(st, "_git_branch", lambda cwd: None)   # git timed out once
        st.ingest(_payload(sid="abc", cwd=str(repo)), now=1.0)
        assert _read(store_file)["sessions"]["abc"]["branch"] is None
        monkeypatch.setattr(st, "_git_branch", real)
        st.ingest(_payload(sid="abc", cwd=str(repo)), now=2.0)
        assert _read(store_file)["sessions"]["abc"]["branch"] == "feat/x"

    def test_non_repo_cwd_still_none(self, store_file, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        st.ingest(_payload(sid="abc", cwd=str(plain)), now=1.0)
        st.ingest(_payload(sid="abc", cwd=str(plain)), now=2.0)
        assert _read(store_file)["sessions"]["abc"]["branch"] is None

    def test_repeat_render_inside_heartbeat_skips_the_write(self, store_file, tmp_path):
        st.ingest(_payload(sid="abc", cwd="/wt/a"), now=100.0)
        before = store_file.stat().st_mtime_ns
        st.ingest(_payload(sid="abc", cwd="/wt/a"), now=105.0)
        assert store_file.stat().st_mtime_ns == before
        assert _read(store_file)["sessions"]["abc"]["updated_at"] == 100.0

    def test_heartbeat_refreshes_updated_at_before_the_stale_horizon(self, store_file):
        st.ingest(_payload(sid="abc", cwd="/wt/a"), now=100.0)
        later = 100.0 + st.WRITE_HEARTBEAT_SECONDS + 1
        st.ingest(_payload(sid="abc", cwd="/wt/a"), now=later)
        assert _read(store_file)["sessions"]["abc"]["updated_at"] == later
        assert st.WRITE_HEARTBEAT_SECONDS < st.STALE_HORIZON_SECONDS / 2

    def test_a_changed_payload_is_always_written(self, store_file):
        st.ingest(_payload(sid="abc", cwd="/wt/a", cost={"total": 1}), now=100.0)
        st.ingest(_payload(sid="abc", cwd="/wt/a", cost={"total": 2}), now=101.0)
        entry = _read(store_file)["sessions"]["abc"]
        assert entry["updated_at"] == 101.0 and entry["payload"]["cost"] == {"total": 2}

    def test_a_new_session_is_always_written(self, store_file):
        st.ingest(_payload(sid="abc", cwd="/wt/a"), now=100.0)
        st.ingest(_payload(sid="def", cwd="/wt/a"), now=101.0)
        assert set(_read(store_file)["sessions"]) == {"abc", "def"}

    def test_a_prune_forces_the_write(self, store_file):
        ttl = st.SESSION_TTL_SECONDS
        st.ingest(_payload(sid="old", cwd="/wt/o"), now=100.0)
        st.ingest(_payload(sid="abc", cwd="/wt/a"), now=ttl + 90.0)   # old still inside the TTL
        assert "old" in _read(store_file)["sessions"]
        # 15s later: inside the heartbeat, only updated_at moved for abc, but old is now
        # past the TTL, so the prune changes the session count and the store is rewritten.
        st.ingest(_payload(sid="abc", cwd="/wt/a"), now=ttl + 105.0)
        assert "old" not in _read(store_file)["sessions"]
