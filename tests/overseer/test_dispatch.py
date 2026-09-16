from pathlib import Path

import pytest

from scripts.dispatch import (
    REPLY_WORD_CAP,
    ReplyError,
    agent_name,
    dispatch_dir,
    is_hub_agent,
    parse_reply,
    reply_words,
    role_of,
)

D = "/x/state/dispatch/WF-12/impl-review"


class TestRoleOf:
    @pytest.mark.parametrize("agent_type, expected", [
        ("overseer:overseer-reviewer", "reviewer"),
        ("overseer-fixer", "fixer"),
        ("overseer:overseer-implementer", "implementer"),
        ("overseer:overseer-foreman", None),
        ("general-purpose", None),
        ("", None),
        (None, None),
        (42, None),
    ])
    def test_role_of(self, agent_type, expected):
        assert role_of(agent_type) == expected

    def test_agent_name_strips_plugin_prefix(self):
        assert agent_name("overseer:overseer-reviewer") == "overseer-reviewer"

    def test_hub_agent_is_foreman_only(self):
        assert is_hub_agent("overseer:overseer-foreman")
        assert not is_hub_agent("overseer:overseer-reviewer")
        assert not is_hub_agent(None)


class TestParseReply:
    def test_reviewer(self):
        r = parse_reply("reviewer", f"found wanting 2C 1I 0M → {D}/r1-A.md")
        assert (r.status, r.card, r.stage, r.round, r.slot) == (
            "found wanting", "WF-12", "impl-review", 1, "A")
        assert r.counts == {"C": 2, "I": 1, "M": 0}
        assert r.path == Path(f"{D}/r1-A.md")

    def test_ascii_arrow_and_surrounding_whitespace(self):
        r = parse_reply("reviewer", f"  approved 0C 0I 3M -> {D}/r2-B.md\n")
        assert (r.status, r.round, r.slot) == ("approved", 2, "B")

    def test_fixer_with_sha(self):
        r = parse_reply("fixer", f"DISPUTED fixed 2 disputed 1 abc1234 → {D}/r1-fix.md")
        assert r.counts == {"fixed": 2, "disputed": 1}
        assert (r.sha, r.slot, r.round) == ("abc1234", "fix", 1)

    def test_implementer_without_sha(self):
        r = parse_reply("implementer",
                        "BLOCKED tests 3/5 - → /x/state/dispatch/WF-12/implementation/c2.md")
        assert (r.status, r.chunk, r.sha) == ("BLOCKED", 2, None)
        assert r.counts == {"passed": 3, "total": 5}

    def test_planner_and_verifier(self):
        assert parse_reply("planner", "DONE → /s/dispatch/WF-1/planning/plan.md").name == "plan"
        v = parse_reply("verifier", "FAIL → /s/dispatch/WF-1/verification/verification.md")
        assert v.status == "FAIL"

    @pytest.mark.parametrize("role, text, message", [
        ("reviewer", f"approved 0C 0I 0M → {D}/r1-A.md\nextra", "more than one line"),
        ("reviewer", "Looks good to me!", "does not match"),
        ("reviewer", "approved 0C 0I 0M → /tmp/elsewhere/r1-A.md", "not a dispatch file"),
        ("reviewer", f"approved 0C 0I 0M → {D}/c1.md", "does not fit"),
        ("reviewer", f"approved 0C 0I 0M → {D}/r1-fix.md", "does not fit"),
        ("fixer", f"DONE fixed 1 disputed 0 - → {D}/r1-A.md", "does not fit"),
        ("planner", f"DONE → {D}/verification.md", "does not fit"),
        ("foreman", "anything", "no reply grammar"),
    ])
    def test_rejections(self, role, text, message):
        with pytest.raises(ReplyError, match=message):
            parse_reply(role, text)


def test_reply_words_and_cap():
    assert reply_words("approved 0C 0I 0M → /a/b.md") == 6
    assert REPLY_WORD_CAP == 25


def test_dispatch_dir_under_state_root(tmp_path):
    # conftest pins OVERSEER_CENTRAL to tmp_path / "state"
    assert dispatch_dir(tmp_path, "WF-1", "impl-review") == (
        tmp_path / "state" / "dispatch" / "WF-1" / "impl-review")
