"""Size budgets for every SKILL.md and commands/*.md (WF-268)."""
import pytest

from lean_common import REPO, load_budgets, prompt_files, size_lf

B = load_budgets()
BUDGETS = B["budgets"]
EXEMPT = B["exemptions"]
DEFAULT = B["default_target_bytes"]


@pytest.mark.parametrize("path", prompt_files())
def test_within_budget(path):
    assert path in BUDGETS, f"{path} has no row in tests/lean/budgets.json; add one (target <= {DEFAULT} bytes)"
    size = size_lf(REPO / path)
    assert size <= BUDGETS[path], (
        f"{path} is {size} bytes, over its budget of {BUDGETS[path]}. "
        "Move single-mode or single-phase procedure into references/ with an explicit read instruction."
    )


def test_no_stale_rows():
    present = set(prompt_files())
    stale = sorted(set(BUDGETS) - present)
    assert not stale, f"budgets.json rows for files that no longer exist: {stale}"


def test_budget_above_default_is_exempted_with_a_reason():
    for path, budget in BUDGETS.items():
        if budget > DEFAULT:
            assert EXEMPT.get(path, "").strip(), f"{path}: budget {budget} > {DEFAULT} needs an exemptions entry with a reason"


def test_exemptions_are_live():
    for path, reason in EXEMPT.items():
        assert path in BUDGETS, f"exemption for unknown file {path}"
        assert BUDGETS[path] > DEFAULT, f"{path} is exempted but its budget is within the default; drop the exemption"
        assert reason.strip()


def test_test_suite_health_exception_is_recorded():
    note = B["_comments"]["plugins/test-crucible/skills/test-suite-health/SKILL.md"]
    assert "12288" in note
