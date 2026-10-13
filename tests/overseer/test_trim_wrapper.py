"""WF-283: bootstrap/resume write the short ``<state>/ov`` wrapper the guard approves."""
import os
import subprocess

import pytest
from factories import git_init

from scripts import guard
from scripts.cli import main
from scripts.store import state_root


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    git_init(root)
    (root / "a.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=root, check=True)
    assert main(["--root", str(root), "init"]) == 0
    return root


def _wrapper(repo):
    return state_root(repo) / guard.WRAPPER_NAME


def test_bootstrap_writes_an_executable_wrapper_the_guard_accepts(repo, capsys):
    assert main(["--root", str(repo), "bootstrap", "--title", "T", "--complexity", "S"]) == 0
    wrapper = _wrapper(repo)
    assert wrapper.is_file() and os.access(wrapper, os.X_OK)
    assert guard.is_wrapper(str(wrapper), str(repo), state_root(repo).resolve())
    assert str(wrapper) in capsys.readouterr().err  # stderr: stdout's one line is unchanged


def test_the_wrapper_runs_a_verb_against_that_repo(repo):
    main(["--root", str(repo), "bootstrap", "--title", "T", "--complexity", "S"])
    done = subprocess.run([str(_wrapper(repo)), "show", "WF-001"], capture_output=True, text=True,
                          cwd="/", env=os.environ.copy(), check=False)
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("WF-001")


def test_resume_rewrites_a_missing_wrapper_and_says_where_it_is(repo, capsys):
    main(["--root", str(repo), "new-card", "--title", "T"])
    capsys.readouterr()
    assert not _wrapper(repo).exists()
    assert main(["--root", str(repo), "resume"]) == 0
    assert _wrapper(repo).is_file()
    assert str(_wrapper(repo)) in capsys.readouterr().err


def test_a_stale_wrapper_is_refreshed_not_trusted(repo):
    main(["--root", str(repo), "bootstrap", "--title", "T", "--complexity", "S"])
    _wrapper(repo).write_text("#!/bin/sh\necho hi\n")
    main(["--root", str(repo), "resume"])
    assert guard.is_wrapper(str(_wrapper(repo)), str(repo), state_root(repo).resolve())


def test_an_unquotable_repo_path_writes_no_wrapper(tmp_path, capsys):
    root = tmp_path / "it's"
    root.mkdir()
    git_init(root)
    assert main(["--root", str(root), "init"]) == 0
    assert main(["--root", str(root), "resume"]) == 0
    assert not (state_root(root) / guard.WRAPPER_NAME).exists()
