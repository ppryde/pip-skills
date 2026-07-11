import pytest

from scripts.conflicts import find_conflicts, paths_overlap
from scripts.models import Card


def card(cid, touches, status="planned", sprint=None):
    return Card(id=cid, title=f"T {cid}", status=status, sprint=sprint,
                created="2026-07-09", updated="2026-07-09T10:00",
                touches=touches, body="x")


class TestPathsOverlap:
    @pytest.mark.parametrize("a, b, expected", [
        pytest.param("src/a.py", "src/a.py", True, id="equal"),
        pytest.param("src/auth", "src/auth/views.py", True, id="dir-prefix-of-file"),
        pytest.param(
            "src/auth/", "src/auth/views.py", True,
            id="dir-prefix-of-file-trailing-slash",
        ),
        pytest.param(
            "./src/auth", "src/auth/views.py", True,
            id="leading-dot-slash-normalised",
        ),
        pytest.param(
            "src/models.py", "src/models_helper.py", False,
            id="sibling-prefix-no-false-positive",
        ),
        pytest.param("src/a", "src/b", False, id="disjoint"),
        pytest.param("", "src/a", False, id="empty"),
    ])
    def test_overlap(self, a, b, expected):
        assert paths_overlap(a, b) == expected


class TestFindConflicts:
    def test_reports_overlapping_pair(self):
        cards = [
            card("WF-001", ["src/auth/"]),
            card("WF-002", ["src/auth/views.py"]),
            card("WF-003", ["docs/"]),
        ]
        conflicts = find_conflicts(cards)
        assert conflicts == [("WF-001", "WF-002", ["src/auth ~ src/auth/views.py"])]

    def test_ignores_done_and_abandoned(self):
        cards = [
            card("WF-001", ["src/x.py"], status="done"),
            card("WF-002", ["src/x.py"], status="in-flight"),
        ]
        assert find_conflicts(cards) == []

    def test_no_conflicts_returns_empty(self):
        assert find_conflicts([card("WF-001", ["a"]), card("WF-002", ["b"])]) == []
