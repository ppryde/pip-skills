"""PR B (lean): the small verbs the lean skills lean on."""
import pytest

from scripts import cli, resume
from scripts.cli import main


@pytest.fixture
def repo(tmp_path):
    assert main(["--root", str(tmp_path), "init"]) == 0
    return tmp_path


def run(repo, *argv):
    return main(["--root", str(repo), *argv])


class TestShowSection:
    def _card(self, repo):
        run(repo, "new-card", "--title", "T", "--goal", "G")
        run(repo, "set-section", "WF-001", "--section", "Plan", "--text", "1. do it")
        run(repo, "set-section", "WF-001", "--section", "Decisions", "--text", "- chose X")

    @pytest.mark.parametrize("spelling", ["Plan", "## Plan", "plan"])
    def test_prints_only_that_section(self, repo, capsys, spelling):
        self._card(repo)
        capsys.readouterr()
        assert run(repo, "show", "WF-001", "--section", spelling) == 0
        out = capsys.readouterr().out
        assert "1. do it" in out
        assert "chose X" not in out and "WF-001" not in out

    def test_review_log_has_a_space(self, repo, capsys):
        self._card(repo)
        run(repo, "append-body", "WF-001", "Review log", "--text", "r1 approved")
        capsys.readouterr()
        assert run(repo, "show", "WF-001", "--section", "Review log") == 0
        assert "r1 approved" in capsys.readouterr().out

    def test_missing_section_is_a_clear_error(self, repo, capsys):
        self._card(repo)
        capsys.readouterr()
        assert run(repo, "show", "WF-001", "--section", "Nope") == 1
        err = capsys.readouterr().err
        assert "no section" in err and "Plan" in err  # names what does exist

    def test_section_with_json_is_just_the_text_in_a_key(self, repo, capsys):
        import json

        self._card(repo)
        capsys.readouterr()
        assert run(repo, "show", "WF-001", "--section", "Plan", "--json") == 0
        assert json.loads(capsys.readouterr().out) == {"id": "WF-001", "section": "## Plan", "text": "1. do it"}


class TestHelpVerb:
    def test_one_line_usage_for_a_verb(self, repo, capsys):
        capsys.readouterr()
        assert run(repo, "help", "dispatch-prep") == 0
        out = capsys.readouterr().out.strip().splitlines()
        assert len(out) == 1
        assert out[0].startswith("dispatch-prep <card-id> ") and "--stage" in out[0]

    def test_unknown_verb_lists_the_known_ones(self, repo, capsys):
        capsys.readouterr()
        assert run(repo, "help", "nope") == 1
        assert "set-stage" in capsys.readouterr().err

    def test_no_verb_lists_every_verb_one_per_line(self, repo, capsys):
        capsys.readouterr()
        assert run(repo, "help") == 0
        lines = capsys.readouterr().out.strip().splitlines()
        assert any(line.startswith("set-stage ") for line in lines)
        assert all(" " in line or line.isalpha() or "-" in line for line in lines)


class TestHandoffPlannedCap:
    def _board(self, repo, n):
        for i in range(n):
            run(repo, "new-card", "--title", f"card {i}")

    def test_planned_list_is_capped_with_a_pointer(self, repo):
        self._board(repo, 14)
        report = resume.handoff_report(repo)
        planned = report.split("## Planned", 1)[1].split("\n## ", 1)[0]
        assert planned.count("\n- WF-") == resume.PLANNED_CAP == 10
        assert "4 more" in planned and "board" in planned

    def test_short_list_is_untouched(self, repo):
        self._board(repo, 3)
        planned = resume.handoff_report(repo).split("## Planned", 1)[1].split("\n## ", 1)[0]
        assert planned.count("\n- WF-") == 3 and "more" not in planned

    def test_json_keeps_every_planned_card(self, repo):
        self._board(repo, 14)
        assert len(resume.handoff_data(repo)["planned"]) == 14

    def test_resume_line_carries_the_real_cli_path(self, repo):
        report = resume.handoff_report(repo)
        assert str(resume.CLI_PATH) in report and "python plugins/overseer/scripts/cli.py" not in report
        assert resume.CLI_PATH.is_file()


def test_cli_exposes_the_help_verb():
    assert "help" in cli.build_parser()._subparsers._group_actions[0].choices
