"""WF-300 C2: `dispatch-record` + `bundle.render` (the remote client's half of dispatch-prep)
and the `--remote-client` flag on resume / handoff / handover.

The contract: rendering a `dispatch-record` JSON record client-side writes the very bytes the
local `dispatch-prep` writes, and the record needs no git."""
import json
import subprocess

import pytest
from factories import git_init

from scripts import bundle, db, gitops
from scripts.cli import main
from scripts.dispatch import dispatch_dir


def _git(path, *argv):
    subprocess.run(["git", *argv], cwd=path, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    git_init(tmp_path)
    (tmp_path / "a.txt").write_text("one\n")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "branch", "-M", "main")
    _git(tmp_path, "checkout", "-qb", "feat/x")
    (tmp_path / "a.txt").write_text("one\ntwo\n")
    _git(tmp_path, "commit", "-qam", "change")
    assert main(["--root", str(tmp_path), "init"]) == 0
    assert main(["--root", str(tmp_path), "new-card", "--title", "T", "--goal", "Ship it",
                 "--labels", "dbt", "--complexity", "M"]) == 0
    conn = db.connect(tmp_path, migrate=False)
    card = db.load_card(conn, "WF-001")
    card.worktree = str(tmp_path)
    card.branch = "feat/x"
    card.set_section("## Plan", "1. chunk one", "t")
    db.save_card(conn, card)
    return tmp_path


def _run(repo, capsys, verb, *argv):
    capsys.readouterr()
    code = main(["--root", str(repo), verb, "WF-001", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


CASES = [
    ("plan-review", "planner", ["--round", "1"]),
    ("plan-review", "reviewer", ["--slot", "A", "--lens", "correctness"]),
    ("impl-review", "reviewer", ["--slot", "B", "--lens", "scope", "--round", "2"]),
    ("impl-review", "reviewer", ["--panel"]),
    ("impl-review", "fixer", ["--round", "2"]),
    ("plan-review", "fixer", ["--round", "1"]),
    ("implementation", "implementer", ["--chunk", "2"]),
    ("verification", "verifier", []),
    ("impl-review", "reviewer", ["--panel", "--advance", "--force-gate", "user: test"]),
]


@pytest.mark.parametrize("stage,role,extra", CASES)
def test_render_of_a_record_is_byte_identical_to_local_prepare(repo, capsys, stage, role, extra):
    argv = ["--stage", stage, "--role", role, *extra]
    d = dispatch_dir(repo, "WF-001", stage)
    code, _, _ = _run(repo, capsys, "dispatch-prep", *argv)
    assert code == 0
    local = {p.name: p.read_bytes() for p in d.iterdir()}
    for p in d.iterdir():
        p.unlink()

    code, out, _ = _run(repo, capsys, "dispatch-record", *argv)
    assert code == 0
    record = json.loads(out)
    assert record["v"] == 1
    cli = f"{bundle.sys.executable} {bundle.CLI_PATH} --root {repo}"
    round_no = int(extra[extra.index("--round") + 1]) if "--round" in extra else 1
    for slot in record["slots"]:
        spec = bundle.spec_from_record(record, stage=stage, role=role, round_no=round_no,
                                       slot=slot["slot"] or None, lens=slot["lens"])
        # the diff header counts the dispatch files themselves, so reuse the local one
        diff = local["diff.patch"].decode() if "diff.patch" in local and stage != "plan-review" else None
        bundle.render(spec, diff, d, cli, repo, {})
    assert {p.name: p.read_bytes() for p in d.iterdir()} == local


def test_record_shape_and_no_host_paths(repo, capsys):
    code, out, _ = _run(repo, capsys, "dispatch-record", "--stage", "impl-review",
                        "--role", "reviewer", "--slot", "A", "--lens", "scope")
    assert code == 0
    record = json.loads(out)
    assert set(record) == {"v", "card", "slots", "chunk", "knowledge", "calibration", "verbosity"}
    assert record["card"] == {"id": "WF-001", "title": "T", "complexity": "M", "goal": "Ship it",
                              "plan": "1. chunk one", "worktree": str(repo)}
    assert record["slots"] == [{"slot": "A", "lens": "scope", "model": ""}]
    assert str(dispatch_dir(repo, "WF-001", "impl-review")) not in out


def test_record_writes_the_dispatch_rows_but_no_files(repo, capsys):
    _run(repo, capsys, "dispatch-record", "--stage", "impl-review", "--role", "reviewer",
         "--slot", "A", "--lens", "scope")
    rows = db.evidence_for(db.connect(repo, migrate=False), "WF-001")
    assert [(r.kind, r.status) for r in rows if r.kind == "dispatch"] == [("dispatch", "dispatched")]
    assert not dispatch_dir(repo, "WF-001", "impl-review").exists()


def test_record_runs_no_git(repo, capsys, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("git was run")
    monkeypatch.setattr(gitops, "_git", boom)
    for stage, role, extra in CASES:
        gate = [] if "--force-gate" in extra else ["--force-gate", "user: test"]
        code, _, err = _run(repo, capsys, "dispatch-record", "--stage", stage, "--role", role,
                            *extra, *gate)
        assert code == 0, (stage, role, err)


def test_record_shares_the_local_validation(repo, capsys):
    for argv in (["--stage", "impl-review", "--role", "reviewer"],                    # no slot
                 ["--stage", "implementation", "--role", "planner", "--panel"],       # panel misuse
                 ["--stage", "impl-review", "--role", "reviewer", "--panel", "--slot", "A"]):
        local = _run(repo, capsys, "dispatch-prep", *argv)
        remote = _run(repo, capsys, "dispatch-record", *argv)
        assert local[0] == remote[0] == 1 and local[2] == remote[2] and local[2].startswith("error:")
    assert db.evidence_for(db.connect(repo, migrate=False), "WF-001") == []


def test_record_never_stamps_without_a_session(repo, capsys, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    _run(repo, capsys, "dispatch-record", "--stage", "impl-review", "--role", "reviewer",
         "--slot", "A", "--lens", "scope")
    conn = db.connect(repo, migrate=False)
    assert db.orchestrated_cards(conn, "anything") == []


# --- --remote-client on resume / handoff / handover -----------------------------------

@pytest.fixture
def inflight(repo):
    conn = db.connect(repo, migrate=False)
    card = db.load_card(conn, "WF-001")
    card.status = "in-flight"
    card.worktree = "/container/wt"
    db.save_card(conn, card)
    return repo


def test_resume_remote_client_reports_null_not_missing(inflight, capsys):
    _, out, _ = _run_noid(inflight, capsys, "resume", "--json", "--remote-client")
    entry = json.loads(out)[0]
    assert entry["worktree_exists"] is None and entry["branch_exists"] is None
    _, text, _ = _run_noid(inflight, capsys, "resume", "--remote-client")
    assert "/container/wt (not checked, remote)" in text and "MISSING" not in text


def test_resume_without_the_flag_is_unchanged(inflight, capsys):
    _, out, _ = _run_noid(inflight, capsys, "resume", "--json")
    entry = json.loads(out)[0]
    assert entry["worktree_exists"] is False and entry["branch_exists"] is True
    _, text, _ = _run_noid(inflight, capsys, "resume")
    assert "/container/wt (MISSING)" in text and "not checked" not in text


def test_handoff_remote_client(inflight, capsys):
    _, out, _ = _run_noid(inflight, capsys, "handoff", "--json", "--remote-client")
    assert json.loads(out)["in_flight"][0]["worktree_exists"] is None
    _, out, _ = _run_noid(inflight, capsys, "handoff", "--json")
    assert json.loads(out)["in_flight"][0]["worktree_exists"] is False
    _, text, _ = _run_noid(inflight, capsys, "handoff", "--remote-client")
    assert "MISSING" not in text


def test_handover_inherits_the_flag(inflight, capsys, monkeypatch):
    seen = {}
    from scripts import cli
    monkeypatch.setattr(cli, "_vigil_cli", lambda: "vigil")
    monkeypatch.setattr(cli, "_run_vigil", lambda root, argv, stdin=None: seen.update(text=stdin) or 0)
    _run_noid(inflight, capsys, "handover", "--remote-client")
    assert "MISSING" not in seen["text"]
    _run_noid(inflight, capsys, "handover")
    assert "MISSING" in seen["text"]


def _run_noid(repo, capsys, verb, *argv):
    capsys.readouterr()
    code = main(["--root", str(repo), verb, *argv])
    out = capsys.readouterr()
    return code, out.out, out.err
