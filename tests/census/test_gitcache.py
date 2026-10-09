import json
import os
import subprocess
import time

import pytest

from scripts import gitcache as gc
from scripts import store as st


def git(repo, *args):
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    (path / "a.txt").write_text("a")
    git(path, "add", "a.txt")
    git(path, "commit", "-q", "-m", "one")
    return path


@pytest.fixture
def cache(tmp_path):
    return tmp_path / "census" / "gitcache"


@pytest.fixture
def count_git(monkeypatch):
    """Count how many times the git subprocess is launched."""
    calls = []
    real = subprocess.run

    def spy(cmd, *a, **k):
        if "--porcelain=2" in cmd:  # the census pass, not the test's own setup git calls
            calls.append(cmd)
        return real(cmd, *a, **k)

    monkeypatch.setattr(gc.subprocess, "run", spy)
    return calls


def test_parse_status_counts_tracked_changes_not_untracked():
    text = (
        "# branch.oid abcdef1234567\n# branch.head feat/x\n# branch.upstream origin/feat/x\n"
        "# branch.ab +2 -0\n1 .M N... 100644 100644 100644 a b a.txt\n"
        "2 R. N... 100644 100644 100644 a b R100 new\told\nu UU N... 1 2 3 4 a b c f\n? untracked\n! ignored\n"
    )
    got = gc.parse_status(text)
    assert got == {"branch": "feat/x", "detached": False, "uncommitted": 3, "ahead": 2, "has_upstream": True}


def test_parse_status_ahead_is_zero_without_upstream():
    got = gc.parse_status("# branch.oid a\n# branch.head main\n")
    assert got["ahead"] == 0 and got["has_upstream"] is False


def test_parse_status_detached_uses_short_sha():
    got = gc.parse_status("# branch.oid 0123456789abcdef\n# branch.head (detached)\n")
    assert got["branch"] == "0123456" and got["detached"] is True


def test_lookup_reports_branch_and_changes(repo, cache):
    (repo / "a.txt").write_text("changed")
    (repo / "new.txt").write_text("untracked")
    got = gc.lookup(cache, str(repo))
    assert got["branch"] == "main" and got["uncommitted"] == 1 and got["ahead"] == 0


def test_warm_lookup_runs_no_git(repo, cache, count_git):
    gc.lookup(cache, str(repo))
    assert len(count_git) == 1
    again = gc.lookup(cache, str(repo))
    assert len(count_git) == 1 and again["branch"] == "main"


def test_entry_shape_and_location(repo, cache):
    gc.lookup(cache, str(repo))
    files = list(cache.glob("*.json"))
    assert len(files) == 1 and len(files[0].stem) == 16
    entry = __import__("json").loads(files[0].read_text())
    assert set(entry) >= {
        "version", "worktree", "head_path", "head_mtime", "branch", "uncommitted", "ahead", "has_upstream", "at",
    }
    assert entry["head_path"] == str(repo / ".git" / "HEAD")


def test_ttl_expiry_reruns_git(repo, cache, count_git):
    t0 = time.time()
    gc.lookup(cache, str(repo), now=t0)
    gc.lookup(cache, str(repo), now=t0 + 14)
    assert len(count_git) == 1
    gc.lookup(cache, str(repo), now=t0 + 16)
    assert len(count_git) == 2


def test_checkout_invalidates_without_waiting_for_ttl(repo, cache, count_git):
    now = time.time()
    gc.lookup(cache, str(repo), now=now)
    git(repo, "checkout", "-q", "-b", "other")
    os.utime(repo / ".git" / "HEAD", (now + 5, now + 5))  # mtime granularity guard
    got = gc.lookup(cache, str(repo), now=now + 1)
    assert got["branch"] == "other" and len(count_git) == 2


def test_ttl_zero_disables_the_cache(repo, cache, count_git, monkeypatch):
    monkeypatch.setenv(gc.TTL_ENV, "0")
    gc.lookup(cache, str(repo))
    gc.lookup(cache, str(repo))
    assert len(count_git) == 2 and not cache.exists()


def test_bad_ttl_falls_back_to_default(monkeypatch):
    monkeypatch.setenv(gc.TTL_ENV, "soon")
    assert gc.ttl_seconds() == gc.DEFAULT_TTL_SECONDS


def test_linked_worktree_head_path_resolves_the_gitdir(repo, tmp_path):
    linked = tmp_path / "linked"
    git(repo, "worktree", "add", "-q", "-b", "wt", str(linked))
    head = gc.head_path(str(linked))
    assert head is not None and os.path.basename(head) == "HEAD" and "worktrees" in os.path.normpath(head).split(os.sep)
    assert os.path.exists(head)


def test_subdirectory_resolves_to_the_enclosing_repo(repo):
    sub = repo / "pkg"
    sub.mkdir()
    assert gc.head_path(str(sub)) == str(repo / ".git" / "HEAD")


def test_not_a_repo_runs_no_git_and_gives_no_branch(tmp_path, cache, count_git):
    plain = tmp_path / "plain"
    plain.mkdir()
    got = gc.lookup(cache, str(plain))
    assert got["branch"] is None and count_git == []


def test_detached_head_is_a_short_sha(repo, cache):
    git(repo, "checkout", "-q", "--detach")
    got = gc.lookup(cache, str(repo))
    assert got["detached"] is True and len(got["branch"]) == 7


def test_timeout_keeps_the_last_cached_value(repo, cache, monkeypatch):
    t0 = time.time()
    gc.lookup(cache, str(repo), now=t0)

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("git", 1)

    monkeypatch.setattr(gc.subprocess, "run", boom)
    got = gc.lookup(cache, str(repo), now=t0 + 60)
    assert got["branch"] == "main"
    # re-stamped: the next refresh inside the TTL does not retry
    assert gc.lookup(cache, str(repo), now=t0 + 61)["at"] == t0 + 60


def test_missing_git_binary_never_raises(repo, cache, monkeypatch):
    def gone(*a, **k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(gc.subprocess, "run", gone)
    assert gc.lookup(cache, str(repo))["branch"] is None


def test_corrupt_entry_is_a_miss(repo, cache):
    gc.lookup(cache, str(repo))
    (next(cache.glob("*.json"))).write_text("{not json")
    assert gc.lookup(cache, str(repo))["branch"] == "main"


def test_prune_removes_old_entries_only(cache):
    cache.mkdir(parents=True)
    old, new = cache / "old.json", cache / "new.json"
    old.write_text("{}")
    new.write_text("{}")
    os.utime(old, (1, 1))
    gc.prune(cache, 3600)
    assert not old.exists() and new.exists()


class TestIngestReadsThroughTheCache:
    """Ingest's branch comes from the same cache: a fresh entry means no git."""

    def payload(self, repo, sid="s1"):
        import json

        return json.dumps({"session_id": sid, "cwd": str(repo)})

    def test_branch_recorded(self, repo, store_file):
        st.ingest(self.payload(repo))
        assert st.for_session("s1")["branch"] == "main"

    def test_second_ingest_runs_no_git(self, repo, store_file, count_git):
        st.ingest(self.payload(repo))
        first = len(count_git)
        st.ingest(self.payload(repo, "s2"))
        assert first == 1 and len(count_git) == 1

    def test_detached_head_stays_null_in_the_record(self, repo, store_file):
        git(repo, "checkout", "-q", "--detach")
        st.ingest(self.payload(repo))
        assert st.for_session("s1")["branch"] is None

    def test_cache_lives_under_the_census_dir(self, repo, store_file):
        st.ingest(self.payload(repo))
        assert list((st.census_dir() / "gitcache").glob("*.json"))


def test_unborn_branch_records_no_branch(tmp_path, cache):
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    git(fresh, "init", "-q", "-b", "main")
    assert gc.lookup(cache, str(fresh))["branch"] is None


def test_parse_status_initial_commit_has_no_branch():
    assert gc.parse_status("# branch.oid (initial)\n# branch.head main\n")["branch"] is None


def test_failed_git_with_no_entry_is_remembered_briefly(repo, cache, monkeypatch):
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise subprocess.TimeoutExpired("git", 1)

    monkeypatch.setattr(gc.subprocess, "run", boom)
    t0 = time.time()
    assert gc.lookup(cache, str(repo), now=t0)["branch"] is None
    gc.lookup(cache, str(repo), now=t0 + 30)
    assert len(calls) == 1  # the negative entry held
    gc.lookup(cache, str(repo), now=t0 + 61)
    assert len(calls) == 2  # and it is short-lived


@pytest.mark.parametrize("raw", ["inf", "-inf", "nan", "Infinity"])
def test_non_finite_ttl_falls_back_to_the_default(raw, monkeypatch):
    monkeypatch.setenv(gc.TTL_ENV, raw)
    assert gc.ttl_seconds() == gc.DEFAULT_TTL_SECONDS


def test_the_failed_marker_survives_a_second_failure(repo, cache, monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired("git", 1)

    monkeypatch.setattr(gc.subprocess, "run", boom)
    t0 = time.time()
    gc.lookup(cache, str(repo), now=t0)
    gc.lookup(cache, str(repo), now=t0 + 61)  # retried, failed again
    entry = json.loads(next(cache.glob("*.json")).read_text())
    assert entry["failed"] is True and entry["at"] == t0 + 61
