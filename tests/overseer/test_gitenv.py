"""WF-100 C6: the git lookups that stay reachable over exec run with a hardened
environment, and no other module in the overseer plugin runs git.

`rev-parse --git-common-dir` and `rev-parse --verify <ref>` read only `.git`
metadata and refs: they never touch the index or the working tree, so no
clean/smudge filter, textconv or diff driver can run, and `rev-parse` invokes no
hook. `core.fsmonitor` is consulted only by index-refreshing commands. The
hardened environment is belt and braces for config-driven execution.
"""
import ast
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest
from factories import git_init
from scripts import boards, db, gitenv, resume, store

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "overseer"


# --- the environment ------------------------------------------------------------------

def _pairs(env):
    n = int(env["GIT_CONFIG_COUNT"])
    return [(env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"]) for i in range(n)]


def test_hardened_env_turns_off_hooks_and_fsmonitor_and_prompts():
    env = gitenv.hardened_git_env({"PATH": "/bin", "KEEP": "me"})
    assert _pairs(env) == [("core.hooksPath", os.devnull), ("core.fsmonitor", "false")]
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["KEEP"] == "me" and env["PATH"] == "/bin"


def test_hardened_env_appends_after_an_existing_config_count():
    base = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "user.name", "GIT_CONFIG_VALUE_0": "x"}
    env = gitenv.hardened_git_env(base)
    assert env["GIT_CONFIG_COUNT"] == "3"
    assert _pairs(env) == [
        ("user.name", "x"), ("core.hooksPath", os.devnull), ("core.fsmonitor", "false"),
    ]
    assert base["GIT_CONFIG_COUNT"] == "1"  # the input is not mutated


@pytest.mark.parametrize("bad", ["", "abc", "-3", "1.5"])
def test_hardened_env_survives_a_garbage_config_count(bad):
    env = gitenv.hardened_git_env({"GIT_CONFIG_COUNT": bad})
    assert _pairs(env)[-2:] == [("core.hooksPath", os.devnull), ("core.fsmonitor", "false")]


def test_hardened_env_defaults_to_the_process_environment(monkeypatch):
    monkeypatch.setenv("WF100_MARKER", "1")
    assert gitenv.hardened_git_env()["WF100_MARKER"] == "1"


# --- the two lookups pass it ----------------------------------------------------------

class _Run:
    def __init__(self, real):
        self.real, self.envs = real, []

    def __call__(self, cmd, **kw):
        if cmd and cmd[0] == "git":
            self.envs.append(kw.get("env"))
        return self.real(cmd, **kw)


def test_store_and_resume_lookups_run_git_with_the_hardened_env(tmp_path, monkeypatch):
    repo = tmp_path / "r"
    repo.mkdir()
    git_init(repo)
    spy = _Run(subprocess.run)
    monkeypatch.setattr(store.subprocess, "run", spy)
    monkeypatch.setattr(resume.subprocess, "run", spy)
    assert store._git_common_dir_uncached(repo) is not None
    resume._branch_exists(repo, "main")
    assert len(spy.envs) == 2
    for env in spy.envs:
        assert env is not None
        assert ("core.hooksPath", os.devnull) in _pairs(env)
        assert ("core.fsmonitor", "false") in _pairs(env)
        assert env["GIT_TERMINAL_PROMPT"] == "0"


# --- a booby-trapped repo --------------------------------------------------------------

@pytest.fixture
def trapped(tmp_path):
    """A repo whose config plants an fsmonitor, a hooksPath of hooks, a clean/smudge
    filter and a textconv driver. Anything that fires appends to FIRED."""
    fired = tmp_path / "FIRED"
    trap = tmp_path / "trap.sh"
    trap.write_text(f'#!/bin/sh\necho "$0 $*" >> "{fired}"\ncat > /dev/null 2>&1\nexit 0\n')
    trap.chmod(trap.stat().st_mode | stat.S_IEXEC)
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    for name in ("pre-commit", "post-commit", "post-checkout", "reference-transaction",
                 "post-index-change", "pre-push", "post-merge"):
        (hooks / name).write_bytes(trap.read_bytes())
        (hooks / name).chmod(0o755)
    repo = tmp_path / "booby"
    repo.mkdir()
    git_init(repo)
    (repo / "a.txt").write_text("x\n")
    (repo / ".gitattributes").write_text("* filter=boom\n*.txt diff=boom\n")
    for key, value in (
        ("core.fsmonitor", str(trap)),
        ("core.hooksPath", str(hooks)),
        ("filter.boom.clean", str(trap)),
        ("filter.boom.smudge", str(trap)),
        ("diff.boom.textconv", str(trap)),
    ):
        subprocess.run(["git", "config", key, value], cwd=repo, check=True)
    return repo, fired


def test_the_trap_is_live_for_commands_that_do_consult_it(trapped):
    # Control: without it the "nothing fired" assertions below prove nothing.
    repo, fired = trapped
    subprocess.run(["git", "status"], cwd=repo, capture_output=True, check=False)
    assert fired.exists(), "core.fsmonitor must fire on `git status`"
    fired.unlink()
    subprocess.run(["git", "commit", "--allow-empty", "-m", "x"], cwd=repo, capture_output=True, check=False)
    assert fired.exists(), "a hook must fire on `git commit`"


def test_the_hardened_env_disarms_fsmonitor_and_hooks(trapped):
    repo, fired = trapped
    env = gitenv.hardened_git_env()
    subprocess.run(["git", "status"], cwd=repo, capture_output=True, check=False, env=env)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "x"], cwd=repo, capture_output=True, check=False, env=env)
    assert not fired.exists()


def test_the_lookups_fire_nothing_in_a_trapped_repo(trapped, tmp_path, monkeypatch):
    repo, fired = trapped
    assert store._git_common_dir_uncached(repo) == (repo / ".git").resolve()
    store.derive_repo_label(repo)
    store.derive_repo_root(repo)
    assert resume._branch_exists(repo, "nope") is False
    # a board for it, so discover() derives the label of the trapped repo
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    monkeypatch.delenv("CLAUDE_CONFIG_DIRS", raising=False)
    monkeypatch.delenv("OVERSEER_DB", raising=False)
    monkeypatch.setenv("OVERSEER_CENTRAL", str(cfg / "overseer" / "booby-seed"))
    db.connect(repo, migrate=False).close()
    monkeypatch.delenv("OVERSEER_CENTRAL")
    boards._discover_cache_clear()
    assert [e["root"] for e in boards.discover()] == [str(repo)]
    assert not fired.exists(), fired.read_text() if fired.exists() else ""


# --- the control: git runs only where it is classified -----------------------------------

_GIT_ARGV = re.compile(r"""\[\s*["']git["']""")
GIT_CALLERS = {"store.py", "gitops.py", "resume.py"}
GITOPS_IMPORTERS = {"cli.py", "bundle.py"}


def _sources():
    yield from (PLUGIN / "scripts").glob("*.py")
    yield from (PLUGIN / "dashboard" / "backend" / "app").glob("*.py")


def test_git_subprocesses_live_only_in_classified_modules():
    callers = {p.name for p in _sources() if _GIT_ARGV.search(p.read_text())}
    assert callers == GIT_CALLERS, (
        "a new module runs git: classify it (and, if exec can reach it, deny or harden it) first"
    )


def _imports_gitops(path: Path) -> bool:
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            if node.module == "scripts.gitops" or (
                node.module == "scripts" and any(a.name == "gitops" for a in node.names)
            ):
                return True
        elif isinstance(node, ast.Import) and any(a.name == "scripts.gitops" for a in node.names):
            return True
    return False


def test_gitops_is_imported_only_by_the_git_running_verbs():
    assert {p.name for p in _sources() if _imports_gitops(p)} == GITOPS_IMPORTERS


def test_the_only_two_lookups_use_the_hardened_env():
    for name in ("store.py", "resume.py"):
        text = (PLUGIN / "scripts" / name).read_text()
        assert "hardened_git_env" in text, name


def test_overseer_handover_never_asks_vigil_for_a_snapshot_and_vigil_has_no_snapshot_verb():
    import argparse
    import inspect

    from scripts import cli

    assert '"--no-snapshot"' in inspect.getsource(cli.cmd_handover)
    (sub,) = [a for a in cli.build_parser()._actions if isinstance(a, argparse._SubParsersAction)]
    (choice,) = [a for a in sub.choices["vigil"]._actions if a.dest == "vigil_verb"]
    assert list(choice.choices) == ["begin", "context", "pause", "resume"]
