import subprocess

from context_vigil.snapshot import session_snapshot


def _git(path, *args):
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)


def _init(path):
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")


def _commit(path, name, body="x = 1\n"):
    (path / name).write_text(body)
    _git(path, "add", name)
    _git(path, "commit", "-qm", f"add {name}")


def _sha(path, ref="HEAD"):
    out = subprocess.run(["git", "rev-parse", "--short", ref], cwd=path,
                         check=True, capture_output=True, text=True)
    return out.stdout.strip()


class TestSnapshot:
    def test_non_git_dir_has_cwd_only(self, tmp_path):
        snap = session_snapshot(tmp_path)
        assert str(tmp_path) in snap
        assert "## Git" not in snap  # no git section outside a repo

    def test_branch_head_and_detail_commands(self, tmp_path):
        _init(tmp_path)
        _commit(tmp_path, "committed.py")
        snap = session_snapshot(tmp_path)
        assert "## Git" in snap
        assert f"- Branch: `main` @ {_sha(tmp_path)}" in snap
        assert "git status --short" in snap and "git diff" in snap

    def test_never_lists_files(self, tmp_path):
        _init(tmp_path)
        for i in range(5):
            _commit(tmp_path, f"tracked{i}.py", str(i))
        (tmp_path / "dirty_untracked.py").write_text("y")
        (tmp_path / "tracked0.py").write_text("changed")
        snap = session_snapshot(tmp_path)
        assert ".py" not in snap
        assert "Recently modified" not in snap

    def test_working_tree_counts(self, tmp_path):
        _init(tmp_path)
        _commit(tmp_path, "a.py")
        _commit(tmp_path, "b.py")
        (tmp_path / "a.py").write_text("changed\n")           # modified
        (tmp_path / "b.py").write_text("changed\n")
        _git(tmp_path, "add", "b.py")                         # staged
        (tmp_path / "new1.py").write_text("n")                # untracked x2
        (tmp_path / "new2.py").write_text("n")
        snap = session_snapshot(tmp_path)
        assert "1 modified, 1 staged, 2 untracked" in snap

    def test_size_is_fixed_regardless_of_dirt(self, tmp_path):
        _init(tmp_path)
        _commit(tmp_path, "a.py")
        clean = len(session_snapshot(tmp_path))
        for i in range(200):
            (tmp_path / f"junk{i}.txt").write_text("j")
        assert abs(len(session_snapshot(tmp_path)) - clean) < 40

    def test_base_is_merge_base_with_origin_main(self, tmp_path):
        remote = tmp_path / "remote.git"
        remote.mkdir()
        _git(remote, "init", "-q", "--bare", "-b", "main")
        work = tmp_path / "work"
        work.mkdir()
        _init(work)
        _commit(work, "a.py")
        _git(work, "remote", "add", "origin", str(remote))
        _git(work, "push", "-q", "origin", "main")
        fork = _sha(work)
        _git(work, "checkout", "-q", "-b", "feat/x")
        _commit(work, "b.py")
        snap = session_snapshot(work)
        assert f"- Base: `origin/main` @ {fork}" in snap
        assert "git diff --stat origin/main...HEAD" in snap
        assert f"- Branch: `feat/x` @ {_sha(work)}" in snap

    def test_no_remote_falls_back_to_local_main(self, tmp_path):
        _init(tmp_path)
        _commit(tmp_path, "a.py")
        fork = _sha(tmp_path)
        _git(tmp_path, "checkout", "-q", "-b", "feat/x")
        _commit(tmp_path, "b.py")
        snap = session_snapshot(tmp_path)
        assert f"- Base: `main` @ {fork}" in snap

    def test_no_base_found_omits_base_line(self, tmp_path):
        _init(tmp_path)
        _git(tmp_path, "checkout", "-q", "-b", "odd")
        _commit(tmp_path, "a.py")
        snap = session_snapshot(tmp_path)
        assert "- Base:" not in snap
        assert "- Branch: `odd`" in snap

    def test_repo_without_commits_does_not_raise(self, tmp_path):
        _init(tmp_path)
        snap = session_snapshot(tmp_path)
        assert str(tmp_path) in snap


class TestGitTimeout:
    def test_hung_git_degrades_to_the_working_directory_line(self, tmp_path, monkeypatch):
        import subprocess as sp
        from context_vigil import snapshot
        seen = []

        def hung(*args, **kwargs):
            seen.append(kwargs.get("timeout"))
            raise sp.TimeoutExpired(args[0], kwargs.get("timeout"))

        monkeypatch.setattr(snapshot.subprocess, "run", hung)
        snap = session_snapshot(tmp_path)
        assert str(tmp_path) in snap and "## Git" not in snap
        assert seen and all(isinstance(t, (int, float)) and 0 < t <= 10 for t in seen)
