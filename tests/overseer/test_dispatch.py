import pytest

from scripts.dispatch import agent_name, dispatch_dir, is_hub_agent, role_of


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


def test_dispatch_dir_under_state_root(tmp_path):
    # conftest pins OVERSEER_CENTRAL to tmp_path / "state"
    assert dispatch_dir(tmp_path, "WF-1", "impl-review") == (
        tmp_path / "state" / "dispatch" / "WF-1" / "impl-review")
