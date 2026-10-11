"""Hard stage gates, evidence recording and the --force-gate escape (WF-265 D2)."""
import io
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from factories import git_init

from scripts import db, gates
from scripts.cli import main
from scripts.dispatch import dispatch_dir
from scripts.gates import Evidence
from scripts.models import ROUND_CAPS, Card

PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "overseer"


@pytest.fixture(autouse=True)
def hard_gates(monkeypatch):
    monkeypatch.setenv("OVERSEER_GATES", "hard")


@pytest.fixture
def repo(tmp_path):
    git_init(tmp_path)
    (tmp_path / "a.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    assert main(["--root", str(tmp_path), "init"]) == 0
    assert main(["--root", str(tmp_path), "new-card", "--title", "T", "--complexity", "M"]) == 0
    return tmp_path


def run(repo, *argv):
    return main(["--root", str(repo), *argv])


def card(repo):
    return db.load_card(db.connect(repo, migrate=False), "WF-001")


def evidence(repo):
    return db.evidence_for(db.connect(repo, migrate=False), "WF-001")


def seed(repo, *rows):
    """rows: (stage, kind, round, slot, status, c, i, m, detail)."""
    conn = db.connect(repo, migrate=False)
    for stage, kind, rnd, slot, status, c, i, m, detail in rows:
        db.record_evidence(conn, "WF-001", stage, kind, round_no=rnd, slot=slot, status=status,
                           critical=c, important=i, minor=m, detail=detail)
    conn.commit()


def set_plan(repo, text="1. do it"):
    assert run(repo, "set-section", "WF-001", "--section", "Plan", "--text", text) == 0


def at(repo, stage):
    """Put the card at ``stage`` the way a pre-D2 board would have: gates off."""
    import os
    old = os.environ.get("OVERSEER_GATES")
    os.environ["OVERSEER_GATES"] = "off"
    try:
        assert run(repo, "set-stage", "WF-001", stage) == 0
    finally:
        os.environ["OVERSEER_GATES"] = old


def review(stage, rnd, slot, c=0, i=0):
    return (stage, "review", rnd, slot, "approved" if not (c or i) else "found wanting", c, i, 0, "")


def dispatched(stage, rnd, slot, role="reviewer"):
    return (stage, "dispatch", rnd, slot, "dispatched", None, None, None, role)


# --- pure rules --------------------------------------------------------------

def mk(stage=None, complexity="M", plan="", verification=""):
    body = f"## Plan\n{plan}\n\n## Verification\n{verification}\n"
    return Card(id="WF-001", title="t", status="in-flight", stage=stage, complexity=complexity,
                body=body, created="2099-01-01")


def ev(n, stage, kind, rnd=None, slot="", status="", c=None, i=None, detail=""):
    return Evidence(n, stage, kind, rnd, slot, status, c, i, 0 if c is not None else None, detail)


class TestRules:
    def test_into_implementation_needs_plan_and_clean_review(self):
        c = mk("planning", plan="_(pending)_")
        problems = gates.check_transition(c, "implementation", [])
        assert any("## Plan is empty" in p for p in problems)
        assert any("plan-review has no reviewer evidence" in p for p in problems)
        c = mk("planning", plan="x")
        assert gates.check_transition(c, "implementation", [
            ev(1, "plan-review", "review", 1, "A", "approved", 0, 0)]) == []

    def test_open_findings_block(self):
        c = mk("plan-review", plan="x")
        out = gates.check_transition(c, "implementation", [
            ev(1, "plan-review", "review", 1, "A", "found wanting", 0, 2)])
        assert len(out) == 1 and "open findings (0C 2I)" in out[0]

    def test_latest_round_wins(self):
        c = mk("plan-review", plan="x")
        rows = [ev(1, "plan-review", "review", 1, "A", "found wanting", 1, 0),
                ev(2, "plan-review", "fix", 1),
                ev(3, "plan-review", "review", 2, "A", "approved", 0, 0)]
        assert gates.check_transition(c, "implementation", rows) == []

    def test_crashed_reviewer_is_not_an_approval(self):
        c = mk("impl-review")
        rows = [ev(1, "impl-review", "dispatch", 1, "A", detail="reviewer"),
                ev(2, "impl-review", "dispatch", 1, "B", detail="reviewer"),
                ev(3, "impl-review", "review", 1, "A", "approved", 0, 0)]
        out = gates.check_transition(c, "verification", rows)
        assert len(out) == 1 and "reviewer B never reported" in out[0]

    def test_redispatched_slot_needs_a_newer_report(self):
        c = mk("impl-review")
        rows = [ev(1, "impl-review", "review", 1, "A", "approved", 0, 0),
                ev(2, "impl-review", "dispatch", 1, "A", detail="reviewer")]
        assert gates.check_transition(c, "verification", rows)

    def test_brief_exempts_only_s(self):
        brief = [ev(1, "planning", "brief")]
        assert gates.check_transition(mk("bootstrap", "S", plan="x"), "implementation", brief) == []
        assert gates.check_transition(mk("bootstrap", "M", plan="x"), "implementation", brief)

    def test_verification_needs_pass_not_prose(self):
        c = mk("verification", verification="FAIL: tests red")
        assert any("no verifier PASS" in p for p in gates.check_transition(c, "awaiting-merge", []))
        fail = [ev(1, "verification", "verify", status="FAIL")]
        assert any("is FAIL" in p for p in gates.check_transition(c, "awaiting-merge", fail))
        ok = [ev(1, "verification", "verify", status="PASS")]
        assert gates.check_transition(c, "awaiting-merge", ok) == []
        assert any("empty" in p for p in gates.check_transition(
            mk("verification"), "awaiting-merge", ok))

    def test_dispatched_verifier_that_never_reported(self):
        c = mk("verification", verification="x")
        rows = [ev(1, "verification", "verify", status="PASS"),
                ev(2, "verification", "dispatch", detail="verifier")]
        assert any("never reported" in p for p in gates.check_transition(c, "awaiting-merge", rows))

    def test_back_moves_and_non_moves_are_free(self):
        c = mk("impl-review")
        assert gates.check_transition(c, "implementation", []) == []
        assert gates.check_transition(c, "impl-review", []) == []

    def test_skipping_a_stage_does_not_skip_its_gate(self):
        c = mk("planning", plan="x")
        out = gates.check_transition(c, "awaiting-merge", [])
        assert any("plan-review" in p for p in out) and any("impl-review" in p for p in out)
        assert any("Verification" in p for p in out)

    def test_round_caps(self):
        c = mk("impl-review", "M")
        assert gates.check_dispatch(c, "impl-review", "reviewer", 3, [ev(1, "impl-review", "fix", 2)]) == []
        assert any("exceeds the cap (3)" in p
                   for p in gates.check_dispatch(c, "impl-review", "reviewer", 4, []))
        out = gates.check_dispatch(c, "impl-review", "fixer", 3, [])
        assert out and 'block WF-001 --reason "user: review deadlock' in out[0]
        assert gates.check_dispatch(c, "impl-review", "fixer", 2, []) == []
        assert any("fixer report for round 1" in p
                   for p in gates.check_dispatch(c, "impl-review", "reviewer", 2, []))
        assert gates.check_dispatch(mk("impl-review", "S"), "impl-review", "fixer", 2, [])
        assert gates.check_dispatch(mk("impl-review", "L"), "impl-review", "fixer", 3, []) == []

    def test_other_dispatches_are_ungated(self):
        c = mk("implementation")
        assert gates.check_dispatch(c, "implementation", "implementer", 9, []) == []

    def test_d1_backfilled_evidence_is_read_by_the_gates(self):
        """Rows migrate.py backfilled from a legacy ## Review log satisfy the same rules."""
        from scripts import migrate
        body = ("## Plan\nx\n\n## Review log\n### plan-review — round 1\n"
                "- A: found wanting 0C 1I 0M → /p\n### plan-review — round 2\n"
                "- A: approved 0C 0I 1M → /q\n\n## Verification\nPASS all green\n")
        card = Card(id="WF-009", title="t", status="in-flight", stage="plan-review",
                    complexity="M", body=body, created="2020-01-01")
        rows = [Evidence(n + 1, r["stage"], r["kind"], r["round"], r["slot"], r["status"],
                         r["critical"], r["important"], r["minor"], "")
                for n, r in enumerate(migrate._evidence_rows(card))]
        assert gates.check_transition(card, "implementation", rows) == []
        verify = [r for r in rows if r.kind == "verify"]
        assert verify and verify[0].status == "PASS"

    def test_caps_agree_with_policy_table(self):
        text = (PLUGIN_ROOT / "skills" / "orchestrate" / "policy.md").read_text()
        for size, cap in ROUND_CAPS.items():
            row = re.search(rf"^\| {size} \|.*$", text, re.M)
            if row:
                assert f"| {cap} |" in row.group(0), size


# --- the CLI -----------------------------------------------------------------

class TestSetStage:
    def test_refused_by_default_exit_3(self, repo, capsys):
        capsys.readouterr()
        assert run(repo, "set-stage", "WF-001", "implementation") == 3
        err = capsys.readouterr().err
        assert "GATE: ## Plan is empty" in err and "--force-gate" in err
        assert card(repo).stage is None  # rolled back

    def test_passes_with_plan_and_clean_review(self, repo):
        set_plan(repo)
        seed(repo, review("plan-review", 1, "A"))
        assert run(repo, "set-stage", "WF-001", "implementation") == 0
        assert card(repo).stage == "implementation"

    def test_force_requires_a_reason(self, repo, capsys):
        for reason in ("", "   "):
            assert run(repo, "set-stage", "WF-001", "implementation", "--force-gate", reason) == 1
        assert card(repo).stage is None
        assert "non-empty reason" in capsys.readouterr().err

    def test_force_is_recorded_and_auditable(self, repo, capsys):
        assert run(repo, "set-stage", "WF-001", "implementation",
                   "--force-gate", "user: plan agreed on a call") == 0
        c = card(repo)
        assert c.stage == "implementation"
        decisions = c.sections["## Decisions"]
        assert "GATE FORCED (new -> implementation): user: plan agreed on a call" in decisions
        assert "unmet: ## Plan is empty" in decisions
        [row] = [e for e in evidence(repo) if e.kind == "force"]
        assert row.stage == "implementation" and "plan agreed" in row.detail
        assert "GATE FORCED" in capsys.readouterr().err

    def test_force_with_nothing_unmet_leaves_no_trace(self, repo):
        assert run(repo, "set-stage", "WF-001", "planning", "--force-gate", "user: x") == 0
        assert "## Decisions" not in card(repo).sections or "FORCED" not in card(repo).sections["## Decisions"]
        assert not [e for e in evidence(repo) if e.kind == "force"]

    def test_warn_mode_prints_and_proceeds(self, repo, capsys, monkeypatch):
        monkeypatch.setenv("OVERSEER_GATES", "warn")
        capsys.readouterr()
        assert run(repo, "set-stage", "WF-001", "implementation") == 0
        assert "WARNING GATE: ## Plan is empty" in capsys.readouterr().err
        assert "FORCED" not in card(repo).body

    def test_off_and_warn_leave_a_bypass_row(self, repo, monkeypatch):
        monkeypatch.setenv("OVERSEER_GATES", "off")
        assert run(repo, "set-stage", "WF-001", "implementation") == 0
        [row] = [e for e in evidence(repo) if e.kind == "force"]
        assert row.status == "bypassed" and "gates=off" in row.detail
        monkeypatch.setenv("OVERSEER_GATES", "warn")
        assert run(repo, "set-stage", "WF-001", "awaiting-merge") == 0
        assert len([e for e in evidence(repo) if e.status == "bypassed"]) == 2

    def test_off_via_env_and_config(self, repo, monkeypatch):
        monkeypatch.setenv("OVERSEER_GATES", "off")
        assert run(repo, "set-stage", "WF-001", "implementation") == 0
        monkeypatch.setenv("OVERSEER_GATES", "")
        (repo / ".overseer").mkdir(exist_ok=True)
        (repo / ".overseer" / "config.local.json").write_text('{"gates": "off"}')
        assert run(repo, "set-stage", "WF-001", "awaiting-merge") == 0

    def test_config_typo_is_hard(self, repo, monkeypatch):
        monkeypatch.setenv("OVERSEER_GATES", "")
        (repo / ".overseer").mkdir(exist_ok=True)
        (repo / ".overseer" / "config.local.json").write_text('{"gates": "of"}')
        assert run(repo, "set-stage", "WF-001", "implementation") == 3

    def test_verification_gate_needs_clean_impl_review(self, repo, capsys):
        seed(repo, review("impl-review", 1, "A", i=1))
        assert run(repo, "set-stage", "WF-001", "verification") == 3
        assert "open findings (0C 1I)" in capsys.readouterr().err

    def test_awaiting_merge_needs_a_recorded_pass(self, repo):
        at(repo, "verification")
        assert run(repo, "set-section", "WF-001", "--section", "Verification", "--text", "FAIL: red") == 0
        seed(repo, ("verification", "verify", None, "", "FAIL", None, None, None, ""))
        assert run(repo, "set-stage", "WF-001", "awaiting-merge",
                   "--force-gate", "x") == 0  # forced
        c = card(repo)
        assert c.stage == "awaiting-merge"

    def test_prose_alone_never_passes_the_merge_gate(self, repo):
        at(repo, "verification")
        assert run(repo, "set-section", "WF-001", "--section", "Verification", "--text", "all green, honest") == 0
        assert run(repo, "set-stage", "WF-001", "awaiting-merge") == 3

    def test_pre_gate_cards_only_warn(self, repo, capsys):
        conn = db.connect(repo, migrate=False)
        db.set_meta(conn, "gates_from", "2999-01-01")
        conn.commit()
        capsys.readouterr()
        assert run(repo, "set-stage", "WF-001", "implementation") == 0
        assert "WARNING GATE" in capsys.readouterr().err

    def test_d1_era_board_is_stamped_on_first_check_and_stays_warn_only_today(self, repo):
        conn = db.connect(repo, migrate=False)
        conn.execute("DELETE FROM meta WHERE key = 'gates_from'")
        conn.commit()
        assert run(repo, "set-stage", "WF-001", "implementation") == 0
        assert db.get_meta(db.connect(repo, migrate=False), "gates_from") > card(repo).created

    def test_unblock_and_unpark_are_not_gated(self, repo):
        set_plan(repo)
        seed(repo, review("plan-review", 1, "A"))
        assert run(repo, "set-stage", "WF-001", "implementation") == 0
        assert run(repo, "block", "WF-001", "--reason", "user: x") == 0
        assert run(repo, "unblock", "WF-001") == 0
        assert run(repo, "park", "WF-001") == 0
        assert run(repo, "unpark", "WF-001") == 0


class TestDispatchPrep:
    def prep(self, repo, *extra, role="reviewer", stage="impl-review", rnd="1", slot="A"):
        argv = ["dispatch-prep", "WF-001", "--stage", stage, "--role", role, "--round", rnd]
        if role == "reviewer":
            argv += ["--slot", slot]
        return run(repo, *argv, *extra)

    def test_records_a_dispatch_row_and_blocks_the_gate_until_it_reports(self, repo, capsys):
        assert self.prep(repo) == 0
        [row] = [e for e in evidence(repo) if e.kind == "dispatch"]
        assert (row.stage, row.round, row.slot, row.detail) == ("impl-review", 1, "A", "reviewer")
        assert run(repo, "set-stage", "WF-001", "verification") == 3
        assert "reviewer A never reported" in capsys.readouterr().err

    def test_redispatch_replaces_not_duplicates(self, repo):
        assert self.prep(repo) == 0 and self.prep(repo) == 0
        assert len([e for e in evidence(repo) if e.kind == "dispatch"]) == 1

    def test_failed_bundle_leaves_no_phantom_dispatch(self, repo, monkeypatch):
        assert run(repo, "dispatch-prep", "WF-001", "--stage", "impl-review", "--role",
                   "reviewer", "--round", "1") == 1  # no --slot: BundleError
        assert not [e for e in evidence(repo) if e.kind == "dispatch"]

    def test_round_cap_and_fixer_ordering(self, repo, capsys):
        assert self.prep(repo, rnd="2") == 3  # no fixer report for round 1
        assert self.prep(repo, role="fixer", rnd="3") == 3  # M cap is 3
        err = capsys.readouterr().err
        assert 'block WF-001 --reason "user: review deadlock' in err
        assert self.prep(repo, rnd="4") == 3
        seed(repo, ("impl-review", "fix", 1, "", "DONE", None, None, None, ""))
        assert self.prep(repo, rnd="2") == 0

    def test_force_overrides_the_cap_and_is_recorded(self, repo):
        assert self.prep(repo, "--force-gate", "user: one more try", rnd="4") == 0
        assert "GATE FORCED (reviewer round 4)" in card(repo).sections["## Decisions"]

    def test_advance_is_gated_too(self, repo):
        assert run(repo, "dispatch-prep", "WF-001", "--stage", "verification", "--role",
                   "verifier", "--advance") == 3
        assert card(repo).stage is None
        assert not [e for e in evidence(repo) if e.kind == "dispatch"]

    def test_verifier_dispatch_blocks_merge_until_it_reports(self, repo):
        at(repo, "impl-review")
        seed(repo, review("impl-review", 1, "A"))
        assert run(repo, "dispatch-prep", "WF-001", "--stage", "verification", "--role",
                   "verifier", "--advance") == 0
        assert run(repo, "set-section", "WF-001", "--section", "Verification", "--text", "PASS") == 0
        assert run(repo, "set-stage", "WF-001", "awaiting-merge") == 3


class TestBootstrapBrief:
    @pytest.fixture
    def proj(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        git_init(root)
        (root / "a.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=root, check=True)
        assert main(["--root", str(root), "init"]) == 0
        (root / ".overseer" / "config.local.json").write_text(
            json.dumps({"worktree_dir": str(tmp_path / "wt")}))
        return root

    def test_s_brief_lands_at_implementation_with_brief_evidence(self, proj):
        assert main(["--root", str(proj), "bootstrap", "--title", "T", "--complexity", "S",
                     "--brief", "do the thing"]) == 0
        c = db.load_card(db.connect(proj, migrate=False), "WF-001")
        assert c.stage == "implementation"
        assert [e.kind for e in db.evidence_for(db.connect(proj, migrate=False), "WF-001")] == ["brief"]

    def test_m_brief_is_refused_and_leaves_no_brief_evidence(self, proj, capsys):
        assert main(["--root", str(proj), "bootstrap", "--title", "T", "--complexity", "M",
                     "--brief", "do the thing"]) == 3
        conn = db.connect(proj, migrate=False)
        assert db.load_card(conn, "WF-001").stage == "bootstrap"
        assert db.evidence_for(conn, "WF-001") == []

    def test_m_brief_with_force_is_recorded(self, proj):
        assert main(["--root", str(proj), "bootstrap", "--title", "T", "--complexity", "M",
                     "--brief", "x", "--force-gate", "user: tiny"]) == 0
        c = db.load_card(db.connect(proj, migrate=False), "WF-001")
        assert "GATE FORCED" in c.sections["## Decisions"]

    def test_plain_bootstrap_lands_at_planning_ungated(self, proj):
        assert main(["--root", str(proj), "bootstrap", "--title", "T", "--complexity", "L"]) == 0


class TestPullChildren:
    def test_child_carried_past_a_gate_is_recorded_not_refused(self, repo):
        assert run(repo, "new-card", "--title", "child") == 0
        assert run(repo, "set-field", "WF-002", "--parent", "WF-001") == 0
        assert run(repo, "set-stage", "WF-001", "implementation", "--force-gate", "user: x") == 0
        assert run(repo, "pull-children", "WF-001") == 0
        child = db.load_card(db.connect(repo, migrate=False), "WF-002")
        assert child.stage == "implementation"
        assert "pull-children moved WF-002" in card(repo).sections["## Decisions"]
        rows = db.evidence_for(db.connect(repo, migrate=False), "WF-002")
        assert [r.kind for r in rows] == ["force"]


# --- evidence recorded by the report hook -------------------------------------

def _hook(repo, monkeypatch, role, obj):
    msg = f"x\n```overseer-report\n{json.dumps(obj)}\n```\n"
    payload = {"cwd": str(repo), "agent_type": f"overseer:overseer-{role}", "agent_id": "a",
               "last_assistant_message": msg}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert main(["--root", str(repo), "report-hook"]) == 0


def _detail(repo, stage, name):
    d = dispatch_dir(repo, "WF-001", stage)
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text("body")
    return str(d / name)


def reviewer_obj(repo, rnd, slot, c=0, i=0, stage="impl-review"):
    return {"schema": "overseer.reviewer/1", "card": "WF-001", "stage": stage, "round": rnd,
            "slot": slot, "status": "found wanting" if c or i else "approved",
            "counts": {"critical": c, "important": i, "minor": 0},
            "detail": _detail(repo, stage, f"r{rnd}-{slot}.md"), "learned": []}


class TestHookEvidence:
    def test_review_loop_end_to_end(self, repo, monkeypatch):
        at(repo, "implementation")
        run(repo, "dispatch-prep", "WF-001", "--stage", "impl-review", "--role", "reviewer",
            "--slot", "A", "--round", "1")
        _hook(repo, monkeypatch, "reviewer", reviewer_obj(repo, 1, "A", i=2))
        assert run(repo, "set-stage", "WF-001", "verification") == 3
        run(repo, "dispatch-prep", "WF-001", "--stage", "impl-review", "--role", "fixer", "--round", "1")
        _hook(repo, monkeypatch, "fixer", {
            "schema": "overseer.fixer/1", "card": "WF-001", "stage": "impl-review", "round": 1,
            "status": "DONE", "counts": {"fixed": 2, "disputed": 0}, "commits": ["abc"],
            "detail": _detail(repo, "impl-review", "fix.md"), "learned": []})
        assert run(repo, "dispatch-prep", "WF-001", "--stage", "impl-review", "--role",
                   "reviewer", "--slot", "A", "--round", "2") == 0
        _hook(repo, monkeypatch, "reviewer", reviewer_obj(repo, 2, "A"))
        assert run(repo, "set-stage", "WF-001", "verification") == 0

    def test_duplicate_hook_fire_records_once(self, repo, monkeypatch):
        obj = reviewer_obj(repo, 1, "A")
        _hook(repo, monkeypatch, "reviewer", obj)
        _hook(repo, monkeypatch, "reviewer", obj)
        assert len([e for e in evidence(repo) if e.kind == "review"]) == 1

    def test_rerun_slot_supersedes_and_orders_after_its_dispatch(self, repo, monkeypatch):
        at(repo, "implementation")
        _hook(repo, monkeypatch, "reviewer", reviewer_obj(repo, 1, "A", c=1))
        run(repo, "dispatch-prep", "WF-001", "--stage", "impl-review", "--role", "reviewer",
            "--slot", "A", "--round", "1")
        _hook(repo, monkeypatch, "reviewer", reviewer_obj(repo, 1, "A"))
        rows = [e for e in evidence(repo) if e.kind == "review"]
        assert len(rows) == 1 and rows[0].critical == 0
        assert run(repo, "set-stage", "WF-001", "verification") == 0

    def test_identical_rerun_after_redispatch_still_counts(self, repo, monkeypatch):
        at(repo, "implementation")
        obj = reviewer_obj(repo, 1, "A")
        _hook(repo, monkeypatch, "reviewer", obj)
        run(repo, "dispatch-prep", "WF-001", "--stage", "impl-review", "--role", "reviewer",
            "--slot", "A", "--round", "1")
        assert run(repo, "set-stage", "WF-001", "verification") == 3
        _hook(repo, monkeypatch, "reviewer", obj)
        assert run(repo, "set-stage", "WF-001", "verification") == 0

    def test_verifier_pass_and_fail(self, repo, monkeypatch):
        at(repo, "impl-review")
        seed(repo, review("impl-review", 1, "A"))
        for status, expect in (("FAIL", 3), ("PASS", 0)):
            run(repo, "dispatch-prep", "WF-001", "--stage", "verification", "--role", "verifier",
                "--advance")
            _hook(repo, monkeypatch, "verifier", {
                "schema": "overseer.verifier/1", "card": "WF-001", "stage": "verification",
                "status": status, "detail": _detail(repo, "verification", "v.md"), "learned": []})
            assert run(repo, "set-stage", "WF-001", "awaiting-merge") == expect

    def test_planner_records_plan_evidence_and_fills_plan(self, repo, monkeypatch):
        _hook(repo, monkeypatch, "planner", {
            "schema": "overseer.planner/1", "card": "WF-001", "stage": "planning",
            "status": "DONE", "detail": _detail(repo, "planning", "plan.md"), "learned": []})
        assert [e.kind for e in evidence(repo)] == ["plan"]
        assert card(repo).sections["## Plan"] == "body"
