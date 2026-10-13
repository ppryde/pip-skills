"""WF-280: ``next <card>`` -- one line: stage, what to dispatch, the verdict state."""
import pytest
from factories import make_card

from scripts import nextstep
from scripts.gates import Evidence

_ids = iter(range(1, 10_000))


def ev(stage, kind, *, round=None, slot="", status="", c=None, i=None, m=None, detail=""):
    return Evidence(next(_ids), stage, kind, round, slot, status, c, i, m, detail)


def review(stage, rnd, slot, status, c=0, i=0, m=0):
    return ev(stage, "review", round=rnd, slot=slot, status=status, c=c, i=i, m=m)


def sent(stage, rnd, slot, role="reviewer"):
    return ev(stage, "dispatch", round=rnd, slot=slot, status="dispatched", detail=role)


def card(stage, complexity="M", **kw):
    return make_card("WF-12", stage=stage, complexity=complexity, **kw)


def line(c, *evidence):
    return nextstep.next_step(c, list(evidence))


class TestPanel:
    @pytest.mark.parametrize("complexity,rnd,slots,models", [
        ("S", 1, "A", ["sonnet"]),
        ("M", 1, "AB", ["sonnet", "sonnet"]),
        (None, 2, "AB", ["sonnet", "sonnet"]),
        ("L", 1, "ABC", ["opus", "sonnet", "sonnet"]),
        ("L", 2, "AB", ["opus", "sonnet"]),
        ("XL", 3, "AB", ["opus", "sonnet"]),
    ])
    def test_panel_follows_the_policy_table(self, complexity, rnd, slots, models):
        got = nextstep.panel(card("impl-review", complexity), rnd)
        assert "".join(s.slot for s in got) == slots
        assert [s.model for s in got] == models

    def test_lenses_are_distinct_for_a_multi_slot_panel(self):
        lenses = [s.lens for s in nextstep.panel(card("impl-review", "M"), 1)]
        assert len(set(lenses)) == len(lenses) == 2 and all(lenses)

    def test_an_s_panel_has_no_lens(self):
        assert nextstep.panel(card("impl-review", "S"), 1)[0].lens is None


class TestStages:
    def test_unstarted_card(self):
        assert line(card(None, status="planned")) == (
            "WF-12 unstarted: no worktree · next: bootstrap --card WF-12")

    def test_planning_without_plan_dispatches_the_planner(self):
        out = line(card("planning", body="## Plan\n_(pending)_"))
        assert "next: dispatch-prep WF-12 --stage planning --role planner" in out
        assert "overseer:overseer-planner sonnet" in out and "--advance" not in out

    def test_an_l_planner_is_strong(self):
        assert "overseer:overseer-planner opus" in line(card("planning", "L"))

    def test_planning_with_a_plan_goes_to_the_plan_review_panel(self):
        out = line(card("planning", body="## Plan\n1. x"))
        assert ("dispatch-prep WF-12 --stage plan-review --role reviewer --panel --round 1 --advance"
                in out)

    def test_implementation_names_the_next_chunk(self):
        body = "## Progress log\n- t — chunk 1 — DONE tests 3/3 abc (~1k tokens)"
        out = line(card("implementation", body=body))
        assert "chunks done: 1" in out
        assert "--role implementer --chunk 2" in out and "overseer:overseer-implementer sonnet" in out
        assert "then: dispatch-prep WF-12 --stage impl-review --role reviewer --panel" in out

    def test_an_s_implementer_is_cheap(self):
        assert "overseer:overseer-implementer haiku" in line(card("implementation", "S"))

    def test_verification_dispatches_the_verifier(self):
        out = line(card("verification"))
        assert "dispatch-prep WF-12 --stage verification --role verifier" in out
        assert "overseer:overseer-verifier sonnet" in out

    def test_verifier_pass_moves_to_awaiting_merge(self):
        out = line(card("verification"), ev("verification", "verify", status="PASS"))
        assert "verification: PASS" in out and "set-stage WF-12 awaiting-merge" in out

    def test_verifier_fail_sends_back_to_implementation(self):
        out = line(card("verification"), ev("verification", "verify", status="FAIL"))
        assert "verification: FAIL" in out and "--stage implementation --role implementer" in out

    def test_awaiting_merge_without_a_pr(self):
        assert "set-field WF-12 --pr" in line(card("awaiting-merge"))

    def test_awaiting_merge_with_a_pr_is_the_users(self):
        out = line(card("awaiting-merge", pr="https://x/pr/1"))
        assert "the merge is the user's" in out


class TestStatus:
    @pytest.mark.parametrize("status", ["done", "abandoned"])
    def test_closed(self, status):
        assert line(card("awaiting-merge", status=status)).endswith(f"{status} · nothing to dispatch")

    def test_blocked_names_the_reason(self):
        out = line(card("planning", status="blocked", blocked_on="user: review deadlock"))
        assert "blocked: user: review deadlock" in out

    def test_parked(self):
        assert "unpark WF-12" in line(card("planning", status="parked"))

    def test_tripwire_stops(self):
        hot = card("implementation", budget_estimate=100, budget_actual=250)
        assert line(hot).startswith("WF-12 implementation: TRIPWIRE") and "escalate" in line(hot)


class TestReviewLoop:
    S = "impl-review"

    def test_no_reviewers_yet_starts_round_one(self):
        out = line(card(self.S))
        assert "impl-review: no reviewers dispatched" in out
        assert "--role reviewer --panel --round 1" in out and "--advance" not in out
        assert "cap 3" in out

    def test_every_slot_approved_passes_to_verification(self):
        out = line(card(self.S), sent(self.S, 1, "A"), sent(self.S, 1, "B"),
                   review(self.S, 1, "A", "approved"), review(self.S, 1, "B", "approved", m=2))
        assert "impl-review r1: A approved, B approved 0C/0I" not in out  # no noise for approvals
        assert "impl-review r1: A approved, B approved" in out
        assert "--stage verification --role verifier --advance" in out

    def test_found_wanting_sends_a_fixer(self):
        out = line(card(self.S), sent(self.S, 1, "A"), sent(self.S, 1, "B"),
                   review(self.S, 1, "A", "approved"),
                   review(self.S, 1, "B", "found wanting", i=2))
        assert "impl-review r1: A approved, B found wanting 0C/2I" in out
        assert "dispatch-prep WF-12 --stage impl-review --role fixer --round 1" in out
        assert "overseer:overseer-fixer sonnet" in out and "cap 3" in out

    def test_after_the_fixer_the_next_round_is_a_re_review(self):
        out = line(card(self.S), sent(self.S, 1, "A"), review(self.S, 1, "A", "found wanting", c=1),
                   ev(self.S, "fix", round=1, status="DONE"))
        assert "--role reviewer --panel --round 2" in out and "fixed, re-review" in out

    def test_a_slot_that_never_reported_is_re_run_not_approved(self):
        out = line(card(self.S), sent(self.S, 1, "A"), sent(self.S, 1, "B"),
                   review(self.S, 1, "A", "approved"))
        assert "B pending" in out
        assert "--role reviewer --slot B --round 1" in out and "--panel" not in out

    def test_deadlock_at_the_cap(self):
        out = line(card(self.S, "S"), sent(self.S, 2, "A"),
                   review(self.S, 2, "A", "found wanting", i=1))
        assert "cap 2" in out and 'block WF-12 --reason "user: review deadlock' in out

    def test_the_latest_round_is_the_newest_evidence_not_the_highest_number(self):
        # a clean round 2 from before a rework, then a fresh round 1
        out = line(card(self.S), sent(self.S, 2, "A"), review(self.S, 2, "A", "approved"),
                   sent(self.S, 1, "A"))
        assert "impl-review r1" in out and "A pending" in out

    def test_plan_review_clean_is_the_plan_gate(self):
        s = "plan-review"
        out = line(card(s), sent(s, 1, "A"), sent(s, 1, "B"),
                   review(s, 1, "A", "approved"), review(s, 1, "B", "approved"))
        assert "PLAN GATE" in out and "set-stage WF-12 implementation" in out

    def test_legacy_verdict_without_counts_counts_as_open(self):
        out = line(card(self.S), sent(self.S, 1, "A"),
                   ev(self.S, "review", round=1, slot="A", status="found wanting"))
        assert "--role fixer --round 1" in out


def test_the_line_is_one_line():
    for st in ("planning", "plan-review", "implementation", "impl-review", "verification"):
        assert "\n" not in line(card(st))
