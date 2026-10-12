"""OR-11: the impl-review diff warns on a dirty worktree, drops lockfiles and
binaries, caps its size, and never waits forever on git."""
import subprocess

import pytest
from factories import git_init

from scripts import bundle, gitops


def _git(path, *argv):
    subprocess.run(["git", *argv], cwd=path, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    git_init(tmp_path)
    (tmp_path / "a.txt").write_text("one\n")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "checkout", "-qb", "feat/x")
    return tmp_path


def _commit(repo, files: dict[str, bytes | str]):
    for name, content in files.items():
        data = content if isinstance(content, bytes) else content.encode()
        (repo / name).write_bytes(data)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "work")


def test_plain_diff_is_unchanged_and_unwarned(repo):
    _commit(repo, {"a.txt": "one\ntwo\n"})
    out = gitops.review_diff(repo)
    assert "+two" in out.text
    assert out.warnings == []
    assert out.text == gitops.diff_against_base(repo)


def test_dirty_worktree_warns_and_names_the_files(repo):
    _commit(repo, {"a.txt": "one\ntwo\n"})
    (repo / "a.txt").write_text("one\ntwo\nthree\n")  # tracked, uncommitted
    (repo / "new.py").write_text("x = 1\n")  # untracked
    out = gitops.review_diff(repo)
    joined = "\n".join(out.warnings)
    assert "uncommitted" in joined and "a.txt" in joined and "new.py" in joined
    assert "+three" not in out.text  # the diff itself stays branch-vs-base
    assert out.text.startswith("# WARNING")  # the reviewer sees it in the file


def test_lockfiles_and_binaries_are_excluded_and_listed(repo):
    _commit(repo, {
        "a.txt": "one\ntwo\n",
        "package-lock.json": "{" + '"x":1,' * 500 + "}\n",
        "poetry.lock": "# lock\n" * 50,
        "logo.png": bytes(range(256)) * 4,
    })
    out = gitops.review_diff(repo)
    assert "+two" in out.text
    assert "package-lock.json" not in out.text.split("# Excluded", 1)[0]
    for name in ("package-lock.json", "poetry.lock", "logo.png"):
        assert name in out.text.split("# Excluded", 1)[1]
    assert "lockfile" in out.text and "binary" in out.text
    assert "+# lock" not in out.text and "PNG" not in out.text
    assert any("excluded" in w for w in out.warnings)


def test_oversize_diff_falls_back_to_stat_plus_whole_files_until_the_cap(repo):
    _commit(repo, {f"f{i}.txt": "line\n" * 400 for i in range(6)})
    full = gitops.diff_against_base(repo)
    cap = len(full) // 2
    out = gitops.review_diff(repo, max_bytes=cap)
    assert len(out.text.encode()) <= cap + 2000  # cap on the diff body; notes are small
    assert "# Diff exceeds" in out.text
    assert "f0.txt" in out.text  # stat lists every file
    assert "f5.txt" in out.text
    assert "git diff" in out.text and "--" in out.text  # how to read an omitted file
    assert any("exceeds" in w for w in out.warnings)
    # never a half-file: each included file's hunk is whole
    assert out.text.count("diff --git") < 6


def test_a_single_file_over_the_cap_is_omitted_not_truncated(repo):
    _commit(repo, {"big.txt": "line\n" * 5000, "small.txt": "x\n"})
    out = gitops.review_diff(repo, max_bytes=2000)
    assert "diff --git a/small.txt" in out.text
    assert "diff --git a/big.txt" not in out.text
    assert "big.txt" in out.text  # but named in the omitted list


def test_git_calls_for_the_diff_carry_a_timeout(repo, monkeypatch):
    _commit(repo, {"a.txt": "one\ntwo\n"})
    seen = []
    real = gitops._git

    def spy(cwd, *argv, timeout=None):
        if argv and argv[0] in ("diff", "status"):
            seen.append(timeout)
        return real(cwd, *argv, timeout=timeout)

    monkeypatch.setattr(gitops, "_git", spy)
    gitops.review_diff(repo)
    assert seen and all(t == gitops.DIFF_TIMEOUT for t in seen)


def test_a_hung_git_diff_becomes_a_git_error(repo, monkeypatch):
    def hang(cwd, *argv, timeout=None):
        if argv[0] == "diff":
            raise subprocess.TimeoutExpired(["git", *argv], timeout)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(gitops, "_git", hang)
    with pytest.raises(gitops.GitError, match="timed out"):
        gitops.review_diff(repo)


def test_fetch_timeout_is_the_named_constant(tmp_path, monkeypatch):
    calls = []

    def fake(cwd, *argv, timeout=None):
        calls.append((argv, timeout))
        if "fetch" in argv:
            raise subprocess.TimeoutExpired(["git", *argv], timeout)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(gitops, "_git", fake)
    gitops.worktree_add(tmp_path, tmp_path / "wt", "b", "HEAD")
    assert [t for a, t in calls if "fetch" in a] == [gitops.FETCH_TIMEOUT]


def test_bundle_writes_the_notes_into_diff_patch_and_warns_on_stderr(repo, capsys, monkeypatch):
    from scripts import db
    from scripts.cli import main
    from scripts.dispatch import dispatch_dir

    _commit(repo, {"a.txt": "one\ntwo\n", "yarn.lock": "x\n" * 10})
    (repo / "dirty.txt").write_text("d\n")
    assert main(["--root", str(repo), "init"]) == 0
    assert main(["--root", str(repo), "new-card", "--title", "T", "--goal", "g"]) == 0
    conn = db.connect(repo, migrate=False)
    card = db.load_card(conn, "WF-001")
    card.worktree = str(repo)
    db.save_card(conn, card)
    capsys.readouterr()
    code = main(["--root", str(repo), "dispatch-prep", "WF-001", "--stage", "impl-review",
                 "--role", "reviewer", "--slot", "A", "--lens", "general"])
    out = capsys.readouterr()
    assert code == 0
    patch = (dispatch_dir(repo, "WF-001", "impl-review") / "diff.patch").read_text()
    assert patch.startswith("# WARNING") and "dirty.txt" in patch and "yarn.lock" in patch
    assert "uncommitted" in out.err
    assert out.out.strip().endswith("bundle-reviewer-A-r1.md")  # stdout stays one path
    assert bundle  # module imported for the public surface


def test_no_dirty_warning_when_there_is_no_base_and_the_diff_is_against_head(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "trunk"], cwd=tmp_path, check=True)
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.txt").write_text("one\n")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-qm", "base")
    (tmp_path / "a.txt").write_text("one\ntwo\n")
    out = gitops.review_diff(tmp_path)
    assert "+two" in out.text and out.warnings == []
