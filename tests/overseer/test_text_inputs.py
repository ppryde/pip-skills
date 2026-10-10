"""--text-file / --brief-file / `--text -` / `--brief -`, and the vigil and
handover passthrough verbs (WF-265 PR A: OR-7 text without inline quoting,
verdict change 8)."""
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
from factories import git_init

from scripts import cli, db
from scripts.cli import main

MULTILINE = "Fix it.\n\nStep 1: run `make` and $(date).\nStep 2: don't 'quote' \"this\".\n"


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    git_init(root)
    (root / "a.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=root, check=True)
    assert main(["--root", str(root), "init"]) == 0
    local = root / ".overseer" / "config.local.json"
    cfg = json.loads(local.read_text() or "{}")
    cfg["worktree_dir"] = str(tmp_path / "wt")
    local.write_text(json.dumps(cfg))
    return root


def card_body(repo, card_id="WF-001"):
    return db.load_card(db.connect(repo, migrate=False), card_id).body


class TestSetSection:
    @pytest.fixture(autouse=True)
    def _card(self, repo):
        assert main(["--root", str(repo), "new-card", "--title", "T"]) == 0

    def test_text_file(self, repo, tmp_path):
        f = tmp_path / "plan.md"
        f.write_text(MULTILINE)
        assert main(["--root", str(repo), "set-section", "WF-001", "--section", "Plan",
                     "--text-file", str(f)]) == 0
        assert "run `make` and $(date)" in card_body(repo)

    def test_file_is_still_the_same_flag(self, repo, tmp_path):
        f = tmp_path / "plan.md"
        f.write_text("via --file")
        assert main(["--root", str(repo), "set-section", "WF-001", "--section", "Plan",
                     "--file", str(f)]) == 0
        assert "via --file" in card_body(repo)

    def test_text_dash_reads_stdin(self, repo, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO(MULTILINE))
        assert main(["--root", str(repo), "set-section", "WF-001", "--section", "Plan",
                     "--text", "-"]) == 0
        assert "don't 'quote' \"this\"" in card_body(repo)

    def test_text_literal_unchanged(self, repo):
        assert main(["--root", str(repo), "set-section", "WF-001", "--section", "Plan",
                     "--text", "short"]) == 0
        assert "short" in card_body(repo)

    def test_exactly_one_source(self, repo, tmp_path):
        f = tmp_path / "p.md"
        f.write_text("x")
        assert main(["--root", str(repo), "set-section", "WF-001", "--section", "Plan"]) == 1
        assert main(["--root", str(repo), "set-section", "WF-001", "--section", "Plan",
                     "--text", "a", "--text-file", str(f)]) == 1


class TestAppendBody:
    @pytest.fixture(autouse=True)
    def _card(self, repo):
        assert main(["--root", str(repo), "new-card", "--title", "T"]) == 0

    def test_text_file(self, repo, tmp_path):
        f = tmp_path / "d.md"
        f.write_text(MULTILINE)
        assert main(["--root", str(repo), "append-body", "WF-001", "Decisions",
                     "--text-file", str(f)]) == 0
        assert "Step 2" in card_body(repo)

    def test_text_dash_still_reads_stdin(self, repo, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO("from stdin\n"))
        assert main(["--root", str(repo), "append-body", "WF-001", "Decisions", "--text", "-"]) == 0
        assert "from stdin" in card_body(repo)

    def test_one_source_required(self, repo):
        assert main(["--root", str(repo), "append-body", "WF-001", "Decisions"]) == 1


class TestBootstrapBrief:
    def test_brief_file(self, repo, tmp_path):
        f = tmp_path / "brief.md"
        f.write_text(MULTILINE)
        assert main(["--root", str(repo), "bootstrap", "--title", "T", "--complexity", "S",
                     "--brief-file", str(f)]) == 0
        card = db.load_card(db.connect(repo, migrate=False), "WF-001")
        assert card.stage == "implementation"
        assert "run `make` and $(date)" in card.body

    def test_brief_dash_reads_stdin(self, repo, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO(MULTILINE))
        assert main(["--root", str(repo), "bootstrap", "--title", "T", "--complexity", "S",
                     "--brief", "-"]) == 0
        card = db.load_card(db.connect(repo, migrate=False), "WF-001")
        assert card.stage == "implementation" and "Step 1" in card.body

    def test_literal_brief_unchanged(self, repo):
        assert main(["--root", str(repo), "bootstrap", "--title", "T", "--brief", "Do x."]) == 0
        assert "Do x." in card_body(repo)

    def test_both_sources_refused_before_anything_is_created(self, repo, tmp_path, capsys):
        f = tmp_path / "b.md"
        f.write_text("x")
        assert main(["--root", str(repo), "bootstrap", "--title", "T", "--brief", "a",
                     "--brief-file", str(f)]) == 1
        assert "not both" in capsys.readouterr().err
        assert db.load_card(db.connect(repo, migrate=False), "WF-001") is None

    def test_missing_brief_file_fails_before_a_card_or_worktree_exists(self, repo, tmp_path):
        with pytest.raises(FileNotFoundError):
            cli.cmd_bootstrap(cli.build_parser().parse_args(
                ["--root", str(repo), "bootstrap", "--title", "T",
                 "--brief-file", str(tmp_path / "nope.md")]))
        assert db.load_card(db.connect(repo, migrate=False), "WF-001") is None
        assert not (tmp_path / "wt").exists()
        # ... and through main() it is a clean error exit
        assert main(["--root", str(repo), "bootstrap", "--title", "T",
                     "--brief-file", str(tmp_path / "nope.md")]) == 1


class FakeVigil:
    """A stand-in vigil CLI that records its argv and stdin."""

    def __init__(self, tmp_path):
        self.out = tmp_path / "vigil-calls.jsonl"
        self.script = tmp_path / "fake_vigil.py"
        self.script.write_text(
            "import json, sys\n"
            f"open({str(self.out)!r}, 'a').write(json.dumps({{'argv': sys.argv[1:], "
            "'stdin': None if sys.stdin.isatty() else sys.stdin.read()}) + '\\n')\n"
            "print('fake-vigil ok')\n"
            "sys.exit(int(__import__('os').environ.get('FAKE_VIGIL_RC', '0')))\n")

    def calls(self):
        return [json.loads(line) for line in self.out.read_text().splitlines()] if self.out.exists() else []


@pytest.fixture
def vigil(tmp_path, monkeypatch):
    fake = FakeVigil(tmp_path)
    monkeypatch.setattr(cli, "_vigil_cli", lambda: fake.script)
    return fake


class TestVigilVerbs:
    @pytest.mark.parametrize("verb", ["begin", "context", "pause", "resume"])
    def test_passthrough(self, repo, vigil, capfd, verb):
        assert main(["--root", str(repo), "vigil", verb]) == 0
        assert capfd.readouterr().out.strip().endswith("fake-vigil ok")
        assert [c["argv"] for c in vigil.calls()] == [["--root", str(repo), verb]]

    def test_unknown_vigil_verb_is_a_usage_error(self, repo, vigil):
        assert main(["--root", str(repo), "vigil", "handover"]) == 1
        assert vigil.calls() == []

    def test_exit_code_passes_through(self, repo, vigil, monkeypatch):
        monkeypatch.setenv("FAKE_VIGIL_RC", "3")
        assert main(["--root", str(repo), "vigil", "begin"]) == 3

    def test_absent_vigil_is_exit_zero_with_the_tell_the_user_line(self, repo, monkeypatch, capsys):
        monkeypatch.setattr(cli, "_vigil_cli", lambda: None)
        assert main(["--root", str(repo), "vigil", "begin"]) == 0
        assert "vigil is not installed" in capsys.readouterr().out
        assert main(["--root", str(repo), "handover"]) == 0
        assert "vigil is not installed" in capsys.readouterr().out


class TestHandoverVerb:
    def test_pipes_the_ledger_rollup_to_vigil_handover_without_a_shell_pipe(self, repo, vigil):
        assert main(["--root", str(repo), "new-card", "--title", "Rollup me"]) == 0
        assert main(["--root", str(repo), "handover"]) == 0
        (call,) = [c for c in vigil.calls() if "handover" in c["argv"]]
        assert call["argv"] == ["--root", str(repo), "handover", "--no-snapshot",
                                "--content-file", "-"]
        assert "WF-001" in call["stdin"] and "Rollup me" in call["stdin"]

    def test_notes_are_forwarded(self, repo, vigil):
        assert main(["--root", str(repo), "handover", "--notes", "keep going"]) == 0
        (call,) = [c for c in vigil.calls() if "handover" in c["argv"]]
        assert call["argv"][-2:] == ["--notes", "keep going"]


class TestVigilLocation:
    """Change 8: `_vigil_cli()` searches the trusted plugin dirs, newest wins."""

    def test_resolves_the_sibling_in_this_repo(self):
        found = cli._vigil_cli()
        assert found is not None and found.parts[-3:] == ("vigil", "scripts", "cli.py")

    def test_cache_layout(self, tmp_path, monkeypatch):
        from scripts import guard

        cfg = tmp_path / "cfg"
        base = cfg / "plugins" / "cache" / "pip-skills"
        for name, version in (("overseer", "0.25.1"), ("vigil", "0.1.0"), ("vigil", "0.2.0")):
            root = base / name / version
            (root / "scripts").mkdir(parents=True)
            (root / "scripts" / "cli.py").write_text("print(1)\n")
            (root / ".claude-plugin").mkdir()
            (root / ".claude-plugin" / "plugin.json").write_text(
                json.dumps({"name": name, "version": version}))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
        monkeypatch.setattr(guard, "_own_cli",
                            lambda: (base / "overseer" / "0.25.1" / "scripts" / "cli.py").resolve())
        guard._manifest_name.cache_clear()
        try:
            assert cli._vigil_cli() == (base / "vigil" / "0.2.0" / "scripts" / "cli.py").resolve()
        finally:
            guard._manifest_name.cache_clear()


class TestDocumentedForms:
    def test_cli_help_lists_the_new_flags(self, capsys):
        for argv, needle in ((["set-section", "--help"], "--text-file"),
                             (["append-body", "--help"], "--text-file"),
                             (["bootstrap", "--help"], "--brief-file"),
                             (["vigil", "--help"], "begin"),
                             (["handover", "--help"], "--notes")):
            assert main(argv) == 0
            assert needle in capsys.readouterr().out
        assert Path(cli.__file__).exists()
