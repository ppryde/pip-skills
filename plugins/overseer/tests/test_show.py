import json

import pytest

from scripts.cli import main
from scripts.models import Card


@pytest.fixture
def repo(tmp_path):
    assert main(["--root", str(tmp_path), "init"]) == 0
    return tmp_path


def run(repo, *argv: str) -> int:
    return main(["--root", str(repo), *argv])


class TestCardSections:
    def test_splits_on_level_two_headers(self):
        body = (
            "## Goal\n"
            "Ship the thing.\n\n"
            "## Plan\n"
            "Step 1.\n\n"
            "### sub\n"
            "Sub-step detail.\n\n"
            "## Decisions\n"
            "Chose X."
        )
        card = Card(id="WF-001", title="T", body=body)
        sections = card.sections
        assert list(sections.keys()) == ["## Goal", "## Plan", "## Decisions"]
        assert sections["## Goal"] == "Ship the thing."
        assert "### sub" in sections["## Plan"]
        assert "Sub-step detail." in sections["## Plan"]
        assert sections["## Decisions"] == "Chose X."

    def test_empty_body_returns_empty_dict(self):
        card = Card(id="WF-001", title="T", body="")
        assert card.sections == {}

    def test_preamble_before_first_header_keyed_empty_string(self):
        body = "Some intro text.\n\n## Goal\nDo it."
        card = Card(id="WF-001", title="T", body=body)
        sections = card.sections
        assert list(sections.keys()) == ["", "## Goal"]
        assert sections[""] == "Some intro text."
        assert sections["## Goal"] == "Do it."


class TestShowCommand:
    def test_show_live_card_json(self, repo, capsys):
        run(repo, "new-card", "--title", "Fix the thing", "--goal", "Fix it good")
        capsys.readouterr()
        assert run(repo, "show", "WF-001", "--json") == 0
        data = json.loads(capsys.readouterr().out)
        assert data["title"] == "Fix the thing"
        assert "## Goal" in data["sections"]
        assert "Fix it good" in data["sections"]["## Goal"]
        assert "## Goal" in data["body"]

    def test_show_archived_card_json(self, repo, capsys):
        run(repo, "new-card", "--title", "Archive me")
        capsys.readouterr()
        assert run(repo, "done", "WF-001") == 0
        capsys.readouterr()
        assert run(repo, "show", "WF-001", "--json") == 0
        data = json.loads(capsys.readouterr().out)
        assert data["id"] == "WF-001"
        assert data["title"] == "Archive me"
        assert data["status"] == "done"

    def test_show_unknown_card_exits_1(self, repo, capsys):
        assert run(repo, "show", "WF-999", "--json") == 1
        assert "error:" in capsys.readouterr().err

    def test_show_json_carries_budget_as_raw_ints(self, repo, capsys):
        run(repo, "new-card", "--title", "Budgeted", "--estimate", "400k")
        capsys.readouterr()
        run(repo, "show", "WF-001", "--json")
        data = json.loads(capsys.readouterr().out)
        assert data["budget"]["estimate"] == 400_000
        assert isinstance(data["budget"]["estimate"], int)

    def test_show_json_carries_checklist(self, repo, capsys):
        run(repo, "new-card", "--title", "Checklist card")
        capsys.readouterr()
        from scripts.store import find_card_path, state_root
        card_path = find_card_path(state_root(repo), "WF-001")
        text = card_path.read_text().replace(
            "status: planned\n",
            "status: planned\n"
            "checklist:\n"
            "  - {task: '1', subject: write tests, status: pending}\n",
            1,
        )
        card_path.write_text(text)

        assert run(repo, "show", "WF-001", "--json") == 0
        data = json.loads(capsys.readouterr().out)
        assert data["checklist"] == [
            {"task": "1", "subject": "write tests", "status": "pending"},
        ]

    def test_show_json_checklist_defaults_empty(self, repo, capsys):
        run(repo, "new-card", "--title", "No checklist")
        capsys.readouterr()
        assert run(repo, "show", "WF-001", "--json") == 0
        data = json.loads(capsys.readouterr().out)
        assert data["checklist"] == []

    def test_show_human_readable_lists_section_headers(self, repo, capsys):
        run(repo, "new-card", "--title", "Human view")
        capsys.readouterr()
        assert run(repo, "show", "WF-001") == 0
        out = capsys.readouterr().out
        assert "WF-001" in out
        assert "## Goal" in out
