from scripts import orchestrator as orch
from scripts.store import init_workflow


class TestPromotion:
    def test_inactive_by_default(self, tmp_path):
        init_workflow(tmp_path)
        assert orch.is_active(tmp_path) is False

    def test_promote_sets_active(self, tmp_path):
        init_workflow(tmp_path)
        orch.promote(tmp_path)
        assert orch.is_active(tmp_path) is True


class TestRequestClear:
    def test_inactive_refuses(self, tmp_path):
        init_workflow(tmp_path)
        assert orch.request_clear(tmp_path, "HANDOFF") == "inactive"
        assert orch.read_handoff(tmp_path) is None

    def test_active_arms_and_writes_handoff(self, tmp_path):
        init_workflow(tmp_path)
        orch.promote(tmp_path)
        assert orch.request_clear(tmp_path, "HANDOFF BODY") == "armed"
        assert orch.clear_flag(tmp_path).exists()
        assert orch.read_handoff(tmp_path) == "HANDOFF BODY"

    def test_paused_refuses(self, tmp_path):
        init_workflow(tmp_path)
        orch.promote(tmp_path)
        orch.pause(tmp_path)
        assert orch.request_clear(tmp_path, "H") == "paused"
        assert not orch.clear_flag(tmp_path).exists()


class TestConsume:
    def test_consume_removes_flag_and_sets_cooldown(self, tmp_path):
        init_workflow(tmp_path)
        orch.promote(tmp_path)
        orch.request_clear(tmp_path, "H")
        assert orch.consume_clear_flag(tmp_path) is True
        assert not orch.clear_flag(tmp_path).exists()
        assert orch.cooldown_marker(tmp_path).exists()

    def test_consume_noop_without_flag(self, tmp_path):
        init_workflow(tmp_path)
        orch.promote(tmp_path)
        assert orch.consume_clear_flag(tmp_path) is False

    def test_consume_noop_when_inactive(self, tmp_path):
        init_workflow(tmp_path)
        orch.clear_flag(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        orch.clear_flag(tmp_path).touch()
        assert orch.consume_clear_flag(tmp_path) is False

    def test_consume_noop_when_paused(self, tmp_path):
        init_workflow(tmp_path)
        orch.promote(tmp_path)
        orch.request_clear(tmp_path, "H")
        orch.pause(tmp_path)
        assert orch.consume_clear_flag(tmp_path) is False
        assert orch.clear_flag(tmp_path).exists()


class TestCooldown:
    def test_request_clear_refuses_during_cooldown(self, tmp_path):
        init_workflow(tmp_path)
        orch.promote(tmp_path)
        orch.request_clear(tmp_path, "H")
        orch.consume_clear_flag(tmp_path)  # sets cooldown
        assert orch.request_clear(tmp_path, "H2") == "cooldown"

    def test_arm_ready_clears_cooldown_and_flag(self, tmp_path):
        init_workflow(tmp_path)
        orch.promote(tmp_path)
        orch.request_clear(tmp_path, "H")
        orch.consume_clear_flag(tmp_path)
        orch.arm_ready(tmp_path)
        assert not orch.cooldown_marker(tmp_path).exists()
        assert orch.request_clear(tmp_path, "H3") == "armed"
