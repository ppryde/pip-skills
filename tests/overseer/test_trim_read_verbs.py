"""WF-281: slim read verbs. show/board --json stop carrying the body twice or in bulk;
conflicts and facts gain count-only and per-card forms. --full keeps the old shape."""
import json

import pytest

from scripts.board import board_data
from scripts.cli import main


@pytest.fixture
def repo(tmp_path):
    assert main(["--root", str(tmp_path), "init"]) == 0
    return tmp_path


def run(repo, *argv):
    return main(["--root", str(repo), *argv])


def out(capsys):
    return capsys.readouterr().out


@pytest.fixture
def planned(repo, capsys):
    run(repo, "new-card", "--title", "T", "--goal", "G")
    run(repo, "set-section", "WF-001", "--section", "Plan", "--text", "1. do it\n" * 300)
    capsys.readouterr()
    return repo


class TestShowJson:
    def test_default_has_sections_and_no_body(self, planned, capsys):
        assert run(planned, "show", "WF-001", "--json") == 0
        data = json.loads(out(capsys))
        assert "body" not in data
        assert "1. do it" in data["sections"]["## Plan"]

    def test_full_restores_the_body(self, planned, capsys):
        run(planned, "show", "WF-001", "--json", "--full")
        full = json.loads(out(capsys))
        assert "1. do it" in full["body"] and "1. do it" in full["sections"]["## Plan"]

    def test_default_is_about_half_the_size(self, planned, capsys):
        run(planned, "show", "WF-001", "--json")
        slim = len(out(capsys))
        run(planned, "show", "WF-001", "--json", "--full")
        assert slim < 0.6 * len(out(capsys))

    def test_full_equals_slim_plus_body(self, planned, capsys):
        run(planned, "show", "WF-001", "--json")
        slim = json.loads(out(capsys))
        run(planned, "show", "WF-001", "--json", "--full")
        full = json.loads(out(capsys))
        assert {k: v for k, v in full.items() if k != "body"} == slim

    def test_text_form_and_section_form_are_unchanged(self, planned, capsys):
        run(planned, "show", "WF-001")
        assert out(capsys).startswith("WF-001 — T")
        run(planned, "show", "WF-001", "--section", "Plan")
        assert "1. do it" in out(capsys)


class TestBoardJson:
    def test_default_cards_carry_no_body_or_checklist(self, planned, capsys):
        assert run(planned, "board", "--json") == 0
        [card] = json.loads(out(capsys))["cards"]
        assert "body" not in card and "checklist" not in card
        assert card["id"] == "WF-001" and card["title"] == "T"

    def test_default_keeps_everything_a_board_row_needs(self, planned, capsys):
        run(planned, "board", "--json")
        slim = json.loads(out(capsys))["cards"][0]
        run(planned, "board", "--json", "--full")
        full = json.loads(out(capsys))["cards"][0]
        assert {k: v for k, v in full.items() if k not in ("body", "checklist")} == slim

    def test_full_restores_body_and_checklist(self, planned, capsys):
        run(planned, "board", "--json", "--full")
        [card] = json.loads(out(capsys))["cards"]
        assert "1. do it" in card["body"] and card["checklist"] == []

    def test_slim_is_much_smaller(self, planned, capsys):
        run(planned, "board", "--json")
        slim = len(out(capsys))
        run(planned, "board", "--json", "--full")
        assert slim < 0.5 * len(out(capsys))

    def test_the_python_api_still_returns_the_full_shape(self, planned):
        [card] = board_data(planned)["cards"]
        assert "body" in card and "checklist" in card
        [slim] = board_data(planned, full=False)["cards"]
        assert "body" not in slim and "checklist" not in slim

    def test_plain_board_line_is_unchanged(self, planned, capsys):
        run(planned, "board")
        assert out(capsys).strip() == "1 cards, 0 sprints"


class TestConflictsSlim:
    @pytest.fixture
    def crowd(self, repo, capsys):
        for n, touches in enumerate(["a.py,b.py", "a.py", "b.py", "z.py"], start=1):
            run(repo, "new-card", "--title", f"T{n}")
            run(repo, "set-field", f"WF-00{n}", "--touches", touches)
        run(repo, "set-stage", "WF-001", "implementation")
        capsys.readouterr()
        return repo

    def test_card_filter_keeps_only_pairs_with_that_card(self, crowd, capsys):
        run(crowd, "conflicts", "--card", "WF-003")
        lines = out(capsys).strip().splitlines()
        assert len(lines) == 1 and "WF-001 ~ WF-003" in lines[0]

    def test_card_filter_with_no_conflict(self, crowd, capsys):
        run(crowd, "conflicts", "--card", "WF-004")
        assert out(capsys).strip() == "No conflicts."

    def test_count_only(self, crowd, capsys):
        run(crowd, "conflicts", "--count")
        assert out(capsys).strip() == "2 conflicts"

    def test_count_json_and_card(self, crowd, capsys):
        run(crowd, "conflicts", "--count", "--card", "WF-001", "--json")
        assert json.loads(out(capsys)) == {"count": 2, "with": ["WF-002", "WF-003"]}

    def test_default_output_is_unchanged(self, crowd, capsys):
        run(crowd, "conflicts")
        assert len(out(capsys).strip().splitlines()) == 2


class TestFactsCount:
    @pytest.fixture
    def facts(self, repo, capsys):
        run(repo, "add-fact", "--statement", "one", "--tags", "a,b")
        run(repo, "add-fact", "--statement", "two", "--tags", "a")
        run(repo, "add-fact", "--statement", "three")
        capsys.readouterr()
        return repo

    def test_count_prints_one_line_with_tag_histogram(self, facts, capsys):
        assert run(facts, "facts", "--count") == 0
        assert out(capsys).strip() == "3 facts · a 2 · b 1"

    def test_count_respects_tag_filter(self, facts, capsys):
        run(facts, "facts", "--count", "--tag", "b")
        assert out(capsys).strip() == "1 fact · a 1 · b 1"

    def test_count_json(self, facts, capsys):
        run(facts, "facts", "--count", "--json")
        assert json.loads(out(capsys)) == {"count": 3, "stale": 0, "tags": {"a": 2, "b": 1}}

    def test_default_listing_is_unchanged(self, facts, capsys):
        run(facts, "facts")
        assert len(out(capsys).strip().splitlines()) == 3
