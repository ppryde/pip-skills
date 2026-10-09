"""Session records carry an additive `git` block: from census_mod.git when the mod sent a
valid one, else from the git cache. `census read` shows it in every form."""
import json
import os
import subprocess

import pytest

from scripts import cli
from scripts import gitcache as gc
from scripts import store as st

FIELDS = {"branch", "uncommitted", "ahead", "has_upstream", "detached"}


def git(repo, *args):
    env = {
        **os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
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
def count_git(monkeypatch):
    calls = []
    real = subprocess.run

    def spy(cmd, *a, **k):
        if "--porcelain=2" in cmd:
            calls.append(cmd)
        return real(cmd, *a, **k)

    monkeypatch.setattr(gc.subprocess, "run", spy)
    return calls


def ingest(sid, cwd, **extra):
    st.ingest(json.dumps({"session_id": sid, "cwd": str(cwd), **extra}), now=1.0)
    return st.for_session(sid, now=1.0)


def mod_git(**over):
    return {"branch": "feat/x", "uncommitted": 3, "ahead": 2, "has_upstream": True, "detached": False, **over}


class TestUnoFlag:
    def test_the_status_call_excludes_untracked_files_at_the_source(self, repo, tmp_path, count_git):
        gc.lookup(tmp_path / "gc", str(repo))
        assert count_git[0] == [
            "git", "--no-optional-locks", "-C", str(repo), "status", "--porcelain=2", "--branch", "-uno",
        ]

    def test_untracked_files_do_not_count(self, repo, tmp_path):
        (repo / "new.txt").write_text("x")
        (repo / "a.txt").write_text("changed")
        assert gc.lookup(tmp_path / "gc", str(repo))["uncommitted"] == 1


class TestFromTheCache:
    def test_block_has_exactly_the_cache_fields(self, repo, store_file):
        (repo / "a.txt").write_text("changed")
        block = ingest("s1", repo)["git"]
        assert set(block) == FIELDS
        assert block == {"branch": "main", "uncommitted": 1, "ahead": 0, "has_upstream": False, "detached": False}

    def test_top_level_branch_is_unchanged(self, repo, store_file):
        assert ingest("s1", repo)["branch"] == "main"

    def test_one_git_pass_fills_both(self, repo, store_file, count_git):
        ingest("s1", repo)
        assert len(count_git) == 1

    def test_detached_head_keeps_null_branch_at_the_top_and_the_sha_in_the_block(self, repo, store_file):
        git(repo, "checkout", "-q", "--detach")
        entry = ingest("s1", repo)
        assert entry["branch"] is None
        assert entry["git"]["detached"] is True and len(entry["git"]["branch"]) == 7

    def test_not_a_repo_is_a_null_safe_block(self, tmp_path, store_file):
        plain = tmp_path / "plain"
        plain.mkdir()
        assert ingest("s1", plain)["git"] == {
            "branch": None, "uncommitted": 0, "ahead": 0, "has_upstream": False, "detached": False,
        }

    def test_no_cwd_is_a_null_safe_block(self, store_file):
        st.ingest(json.dumps({"session_id": "s1"}), now=1.0)
        assert set(st.for_session("s1", now=1.0)["git"]) == FIELDS


class TestFromTheMod:
    def test_a_valid_block_is_used_verbatim_and_runs_no_git(self, repo, store_file, count_git):
        entry = ingest("s1", repo, census_mod={"pid": 4242, "git": mod_git()})
        assert entry["git"] == mod_git()
        assert count_git == []

    def test_the_top_level_branch_follows_the_mods_block(self, repo, store_file):
        assert ingest("s1", repo, census_mod={"git": mod_git()})["branch"] == "feat/x"
        assert ingest("s2", repo, census_mod={"git": mod_git(detached=True)})["branch"] is None

    def test_extra_keys_are_dropped(self, repo, store_file):
        entry = ingest("s1", repo, census_mod={"git": {**mod_git(), "untracked": 9, "x": 1}})
        assert set(entry["git"]) == FIELDS

    @pytest.mark.parametrize("bad", [
        {"branch": 7}, {"uncommitted": "3"}, {"uncommitted": True}, {"uncommitted": -1}, {"ahead": 1.5},
        {"has_upstream": "yes"}, {"detached": None}, {"uncommitted": float("nan")},
    ])
    def test_an_invalid_field_falls_back_to_the_cache(self, repo, store_file, bad):
        entry = ingest("s1", repo, census_mod={"git": mod_git(**bad)})
        assert entry["git"]["branch"] == "main"

    @pytest.mark.parametrize("missing", sorted(FIELDS))
    def test_a_missing_field_falls_back_to_the_cache(self, repo, store_file, missing):
        block = mod_git()
        del block[missing]
        assert ingest("s1", repo, census_mod={"git": block})["git"]["branch"] == "main"

    @pytest.mark.parametrize("junk", ["x", [1], None, 5])
    def test_a_git_that_is_not_an_object_falls_back(self, repo, store_file, junk):
        assert ingest("s1", repo, census_mod={"git": junk})["git"]["branch"] == "main"

    def test_a_null_branch_is_valid(self, repo, store_file):
        assert ingest("s1", repo, census_mod={"git": mod_git(branch=None)})["git"]["branch"] is None


class TestReadShowsIt:
    def _cli(self, capsys, *argv):
        cli.main(["read", *argv])
        return json.loads(capsys.readouterr().out)

    def test_every_form_includes_the_block(self, repo, store_file, capsys):
        ingest("s1", repo)
        full = self._cli(capsys)["sessions"]["s1"]
        assert set(full["git"]) == FIELDS
        assert self._cli(capsys, "--session", "s1")["git"] == full["git"]
        assert self._cli(capsys, "--worktree", str(repo))["git"] == full["git"]

    def test_an_old_record_without_the_block_still_reads(self, repo, store_file, capsys):
        ingest("s1", repo)
        path = st.session_path("s1")
        data = json.loads(path.read_text())
        del data["git"]
        path.write_text(json.dumps(data))
        assert "git" not in self._cli(capsys, "--session", "s1")
