"""WF-300 C3: `bootstrap` / `dispatch-prep` under `--remote` run git in the CONTAINER.

Host = `create_app` + a real CLI child (board in a host state dir). Container = a second
git repo with its own state dir. The container's `exec_remote` is replaced by a function that
POSTs to the host's `/api/exec` through the TestClient, with the host's env swapped in for the
child (one process plays both machines) and the container's restored after.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from scripts import db, remote
from scripts.cli import main
from scripts.dispatch import dispatch_dir

from app.cli_client import run_overseer
from app.main import create_app

TOKEN = {"X-Overseer-Token": "t"}
URL = "http://host.test:8770"
SESSION = "container-session"


def _git(path: Path, *argv: str) -> str:
    return subprocess.run(["git", *argv], cwd=path, check=True, capture_output=True,
                          text=True).stdout


def _make_repo(path: Path) -> None:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")
    (path / "a.txt").write_text("one\n")
    _git(path, "add", "a.txt")
    _git(path, "commit", "-qm", "base")


class Machines:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp = tmp_path
        self.monkeypatch = monkeypatch
        self.host_env = {"OVERSEER_DB": str(tmp_path / "host" / "board.db"),
                         "OVERSEER_CENTRAL": str(tmp_path / "host" / "state")}
        self.container_env = {"OVERSEER_DB": str(tmp_path / "container-state" / "never.db"),
                              "OVERSEER_CENTRAL": str(tmp_path / "container-state")}
        # host board
        self.host_root = tmp_path / "host-repo"
        _make_repo(self.host_root)
        self._env(self.host_env)
        run_overseer(self.host_root, "init")
        self.client = TestClient(create_app(self.host_root, exec_token="t"))
        # container checkout with a bare origin and its own worktree_dir
        self.origin = tmp_path / "origin.git"
        self.root = tmp_path / "container" / "proj"
        _make_repo(self.root)
        subprocess.run(["git", "clone", "-q", "--bare", str(self.root), str(self.origin)], check=True)
        _git(self.root, "remote", "add", "origin", str(self.origin))
        _git(self.root, "fetch", "-q", "origin")
        _git(self.root, "remote", "set-head", "origin", "main")
        cfg = self.root / ".overseer"
        cfg.mkdir()
        (cfg / "config.local.json").write_text(json.dumps({"worktree_dir": str(tmp_path / "wt")}))
        self._env(self.container_env)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
        monkeypatch.setenv("OVERSEER_REMOTE_TOKEN", "tok")
        monkeypatch.delenv("OVERSEER_REMOTE_REPO", raising=False)
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        self.posted: list[tuple[list[str], str | None]] = []
        self.fail_on: dict[str, Exception] = {}
        self.rewrite: Any = None
        monkeypatch.setattr(remote, "exec_remote", self._exec)
        self.worktree = tmp_path / "wt" / "proj-wf-001"

    def _env(self, env: dict[str, str]) -> None:
        for key, value in env.items():
            self.monkeypatch.setenv(key, value)

    def _exec(self, url: str, token: str | None, argv: list[str], stdin: str | None,
              **kw: Any) -> remote.RemoteResult:
        self.posted.append((list(argv), stdin))
        verb = next((t for t in argv if not t.startswith("--")), "")
        if verb in self.fail_on:
            exc = self.fail_on.pop(verb)
            raise exc
        if self.rewrite is not None and (out := self.rewrite(argv)) is not None:
            return out
        self._env(self.host_env)
        try:
            resp = self.client.post("/api/exec", json={"argv": argv, "stdin": stdin}, headers=TOKEN)
        finally:
            self._env(self.container_env)
        if resp.status_code == 403:
            raise remote.RemoteError(f"overseer server refused this request (403): {resp.json()['detail']}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        return remote.RemoteResult(data["stdout"], data["stderr"], data["returncode"])

    def run(self, *argv: str, root: Path | None = None) -> int:
        return main(["--remote", URL, "--root", str(root or self.root), *argv])

    def host(self, *argv: str) -> dict[str, Any]:
        self._env(self.host_env)
        try:
            return self.client.post("/api/exec", json={"argv": list(argv), "stdin": None},
                                    headers=TOKEN).json()
        finally:
            self._env(self.container_env)

    def conn(self) -> Any:
        """The HOST's board (the container's env is restored after the connect)."""
        self._env(self.host_env)
        try:
            return db.connect(self.host_root, migrate=False)
        finally:
            self._env(self.container_env)

    def card(self, card_id: str = "WF-001") -> dict[str, Any]:
        return json.loads(self.host("show", card_id, "--json")["stdout"])

    def posted_verbs(self) -> list[str]:
        return [next(t for t in argv if not t.startswith("--")) for argv, _ in self.posted]


@pytest.fixture
def m(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Machines:
    return Machines(tmp_path, monkeypatch)


def _worktree_count(root: Path) -> int:
    return _git(root, "worktree", "list", "--porcelain").count("worktree ")


# --- (a) bootstrap end to end ---------------------------------------------------------

def test_remote_bootstrap_creates_the_worktree_in_the_container(m: Machines, capsys) -> None:
    assert m.run("bootstrap", "--title", "Add thing") == 0
    assert m.worktree.is_dir() and (m.worktree / "a.txt").exists()
    assert _git(m.worktree, "branch", "--show-current").strip() == "feat/WF-001-add-thing"
    card = m.card()
    assert (card["stage"], card["branch"], card["worktree"]) == (
        "planning", "feat/WF-001-add-thing", str(m.worktree))
    assert m.posted_verbs() == ["bootstrap-begin", "bootstrap-finish"]
    out = capsys.readouterr().out
    assert f"WF-001 planning · feat/WF-001-add-thing · {m.worktree} (base origin/main)" in out
    # the host never stamped the container's session or wrote a guard marker
    conn = m.conn()
    assert db.orchestrated_cards(conn, SESSION) == []
    marker_dir = Path(m.tmp / "no-ambient-config" / "overseer" / ".orchestrating")
    assert not marker_dir.exists() or not any(marker_dir.iterdir())
    assert not Path(m.container_env["OVERSEER_DB"]).exists()  # no board in the container


# --- (b) reviewer dispatch-prep -------------------------------------------------------

def test_remote_reviewer_dispatch_writes_the_diff_from_the_container_worktree(m: Machines) -> None:
    assert m.run("bootstrap", "--title", "T") == 0
    (m.worktree / "a.txt").write_text("one\ntwo\n")
    _git(m.worktree, "commit", "-qam", "change")
    assert m.host("set-stage", "WF-001", "impl-review", "--force-gate", "user: test")["returncode"] == 0
    m.posted.clear()
    assert m.run("dispatch-prep", "WF-001", "--stage", "impl-review", "--role", "reviewer",
                 "--slot", "A", "--lens", "scope") == 0
    d = dispatch_dir(m.root, "WF-001", "impl-review")
    assert "+two" in (d / "diff.patch").read_text()
    text = (d / "bundle-reviewer-A-r1.md").read_text()
    assert str(d / "r1-A.md") in text and str(m.worktree) in text
    assert str(m.host_root) not in text and m.host_env["OVERSEER_CENTRAL"] not in text
    assert set(m.posted_verbs()) == {"show", "dispatch-record"}
    rows = db.evidence_for(m.conn(), "WF-001")
    assert [r.status for r in rows if r.kind == "dispatch"] == ["dispatched"]


def test_remote_planner_dispatch_needs_no_worktree(m: Machines, capsys) -> None:
    assert m.run("bootstrap", "--title", "T") == 0
    capsys.readouterr()
    assert m.run("dispatch-prep", "WF-001", "--stage", "planning", "--role", "planner") == 0
    path = Path(capsys.readouterr().out.strip())
    assert path == dispatch_dir(m.root, "WF-001", "planning") / "bundle-planner-r1.md" and path.exists()
    assert m.posted_verbs()[-1] == "dispatch-record"


# --- (c) finish fails once -> rerun adopts --------------------------------------------

def test_failed_finish_then_rerun_adopts_the_worktree(m: Machines, capsys) -> None:
    m.fail_on["bootstrap-finish"] = remote.RemoteError("cannot reach overseer server")
    assert m.run("bootstrap", "--title", "T") == 1
    err = capsys.readouterr().err
    assert "WF-001 is at bootstrap on the host; rerun bootstrap --card WF-001" in err
    assert m.card()["stage"] == "bootstrap" and m.worktree.is_dir()
    assert m.run("bootstrap", "--card", "WF-001") == 0
    assert "adopting existing worktree" in capsys.readouterr().err
    assert _worktree_count(m.root) == 2  # main checkout + one worktree
    card = m.card()
    assert (card["stage"], card["worktree"]) == ("planning", str(m.worktree))
    assert "bootstrap --card" not in m.host("next", "WF-001")["stdout"]


# --- (d) failure matrix ---------------------------------------------------------------

def test_no_checkout_fails_before_any_host_call(m: Machines, tmp_path: Path, capsys) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert m.run("bootstrap", "--title", "T", root=plain) == 1
    assert "needs a git checkout in this container" in capsys.readouterr().err
    assert m.posted == []


def test_branch_checked_out_elsewhere_leaves_the_card_at_bootstrap(m: Machines, tmp_path: Path, capsys) -> None:
    _git(m.root, "worktree", "add", "-q", "-b", "feat/WF-001-t", str(tmp_path / "other"))
    assert m.run("bootstrap", "--title", "T") == 1
    assert "WF-001 left at bootstrap - feat/WF-001-t is already checked out at" in capsys.readouterr().err
    assert m.card()["stage"] == "bootstrap"


def test_path_on_a_different_branch_is_an_error(m: Machines, capsys) -> None:
    _git(m.root, "worktree", "add", "-q", "-b", "other-branch", str(m.worktree))
    assert m.run("bootstrap", "--title", "T") == 1
    err = capsys.readouterr().err
    assert "is already a worktree on other-branch, not feat/WF-001-t" in err
    assert m.card()["stage"] == "bootstrap"


def test_host_down_at_begin(m: Machines, capsys) -> None:
    m.fail_on["bootstrap-begin"] = remote.RemoteError("cannot reach overseer server at http://x")
    assert m.run("bootstrap", "--title", "T") == 1
    assert "cannot reach" in capsys.readouterr().err
    assert not m.worktree.exists()


def test_worktree_absent_at_dispatch_writes_no_rows(m: Machines, capsys) -> None:
    assert m.run("bootstrap", "--title", "T") == 0
    assert m.host("set-field", "WF-001", "--worktree", "/nowhere/else")["returncode"] == 0
    assert m.host("set-stage", "WF-001", "impl-review", "--force-gate", "user: test")["returncode"] == 0
    capsys.readouterr()
    assert m.run("dispatch-prep", "WF-001", "--stage", "impl-review", "--role", "reviewer",
                 "--slot", "A") == 1
    assert "is not present in this container" in capsys.readouterr().err
    assert [e.kind for e in db.evidence_for(m.conn(), "WF-001")] == ["force"]  # no dispatched row
    assert "dispatch-record" not in m.posted_verbs()


@pytest.mark.parametrize("verb,argv", [
    ("bootstrap", ["--title", "T"]),
    ("dispatch-prep", ["WF-001", "--stage", "planning", "--role", "planner"]),
])
def test_older_host_gets_the_update_message(m: Machines, capsys, verb, argv) -> None:
    from scripts.remote import RemoteResult
    m.rewrite = lambda a: RemoteResult("", "usage: ...\nerror: argument command: invalid choice: "
                                       f"'{a[0]}'\n", 1)
    assert m.run(verb, *argv) == 1
    assert "update overseer on the host/in this container" in capsys.readouterr().err


def test_a_403_for_the_new_verbs_also_reads_as_skew(m: Machines, capsys) -> None:
    m.fail_on["bootstrap-begin"] = remote.RemoteError(
        "overseer server refused this request (403): verb 'bootstrap-begin' is not permitted over remote exec")
    assert m.run("bootstrap", "--title", "T") == 1
    assert "update overseer on the host/in this container" in capsys.readouterr().err


# --- (e) the denied verbs are never posted --------------------------------------------

def test_bootstrap_and_dispatch_prep_are_never_posted_and_stay_403(m: Machines) -> None:
    m.run("bootstrap", "--title", "T")
    m.run("dispatch-prep", "WF-001", "--stage", "planning", "--role", "planner")
    assert not {"bootstrap", "dispatch-prep"} & set(m.posted_verbs())
    for argv in (["bootstrap", "--title", "x"], ["dispatch-prep", "WF-001", "--stage", "planning",
                                                  "--role", "planner"]):
        resp = m.client.post("/api/exec", json={"argv": argv, "stdin": None}, headers=TOKEN)
        assert resp.status_code == 403


# --- (f) the brief ---------------------------------------------------------------------

@pytest.mark.parametrize("how", ["file", "dash"])
def test_brief_reaches_begin_and_finish_as_stdin(m: Machines, monkeypatch, tmp_path: Path, how: str) -> None:
    if how == "file":
        f = tmp_path / "brief.txt"
        f.write_text("Fix the typo.\n")
        extra = ["--brief-file", str(f)]
    else:
        monkeypatch.setattr(sys, "stdin", io.StringIO("Fix the typo.\n"))
        extra = ["--brief", "-"]
    assert m.run("bootstrap", "--title", "T", "--complexity", "S", *extra) == 0
    sent = {argv[0]: (argv, stdin) for argv, stdin in m.posted}
    for verb in ("bootstrap-begin", "bootstrap-finish"):
        argv, stdin = sent[verb]
        assert argv[argv.index("--brief") + 1] == "-" and stdin == "Fix the typo."
        assert not any(t.startswith("--") and "file" in t for t in argv)
    card = m.card()
    assert card["stage"] == "implementation" and card["sections"]["## Plan"] == "Fix the typo."


# --- (g) local mode is untouched ---------------------------------------------------------

def test_local_main_never_imports_remote_git(m: Machines, monkeypatch) -> None:
    for name in ("scripts.remote_git",):
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.delenv("OVERSEER_REMOTE", raising=False)
    main(["--root", str(m.root), "resume"])
    assert "scripts.remote_git" not in sys.modules


# --- (h) label mismatch ---------------------------------------------------------------

def test_label_mismatch_warns_but_never_fails(m: Machines, monkeypatch, capsys) -> None:
    monkeypatch.setenv("OVERSEER_REMOTE_REPO", "some-other-label")
    assert m.run("bootstrap", "--title", "T") == 0
    assert "OVERSEER_REMOTE_REPO is 'some-other-label' but this checkout is 'proj'" in capsys.readouterr().err


# --- (i) the host never touches the container's tree -----------------------------------

def test_host_verbs_never_run_git_in_the_recorded_worktree(m: Machines, tmp_path: Path) -> None:
    evil = tmp_path / "evil"
    _make_repo(evil)
    sentinel = tmp_path / "RAN"
    hook = tmp_path / "hook.sh"
    hook.write_text(f"#!/bin/sh\ntouch {sentinel}\n")
    hook.chmod(0o755)
    _git(evil, "config", "core.fsmonitor", str(hook))
    _git(evil, "status")  # arms the planted fsmonitor: any git run in the tree trips it
    assert sentinel.exists()
    sentinel.unlink()
    assert m.run("bootstrap", "--title", "T", "--type", "feat") == 0
    assert m.host("set-field", "WF-001", "--worktree", str(evil))["returncode"] == 0
    m.host("set-stage", "WF-001", "impl-review", "--force-gate", "user: test")
    for argv in (["dispatch-record", "WF-001", "--stage", "impl-review", "--role", "reviewer",
                  "--slot", "A", "--lens", "scope"],
                 ["resume", "--remote-client"], ["handoff", "--remote-client"], ["show", "WF-001"]):
        assert m.host(*argv)["returncode"] == 0, argv
    assert not sentinel.exists()


def test_session_id_in_the_container_is_not_stamped_by_dispatch(m: Machines) -> None:
    m.run("bootstrap", "--title", "T")
    m.run("dispatch-prep", "WF-001", "--stage", "planning", "--role", "planner")
    assert db.orchestrated_cards(m.conn(), SESSION) == []


def test_resume_and_handoff_forward_the_client_flag(m: Machines, capsys) -> None:
    m.run("bootstrap", "--title", "T")
    m.posted.clear()
    capsys.readouterr()
    assert m.run("resume") == 0
    assert m.posted[0][0][-1] == "--remote-client"
    out = capsys.readouterr().out
    assert "(not checked, remote)" in out and "MISSING" not in out
    for verb in ("handoff", "handover"):
        m.run(verb)
        assert m.posted[-1][0][-1] == "--remote-client"
