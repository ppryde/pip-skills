from scripts.conflicts import find_conflicts, paths_overlap
from scripts.models import Card


def card(cid, touches, status="planned", sprint=None):
    return Card(id=cid, title=f"T {cid}", status=status, sprint=sprint,
                created="2026-07-09", updated="2026-07-09T10:00",
                touches=touches, body="x")


class TestPathsOverlap:
    def test_equal(self):
        assert paths_overlap("src/a.py", "src/a.py")

    def test_dir_prefix_of_file(self):
        assert paths_overlap("src/auth", "src/auth/views.py")
        assert paths_overlap("src/auth/", "src/auth/views.py")

    def test_leading_dot_slash_normalised(self):
        assert paths_overlap("./src/auth", "src/auth/views.py")

    def test_sibling_prefix_no_false_positive(self):
        assert not paths_overlap("src/models.py", "src/models_helper.py")

    def test_disjoint(self):
        assert not paths_overlap("src/a", "src/b")

    def test_empty(self):
        assert not paths_overlap("", "src/a")


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
