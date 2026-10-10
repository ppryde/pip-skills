"""Round-3 review findings (WF-265 PR A), driven through the real hook entry
point (``hooks/pretool.sh``) wherever the finding is about the shell layer.

B1  python itself failing must not open the guard for an orchestrating session.
B2  the first-call sentinel is only written after a COMPLETE board lookup; the
    marker dir is swept (rate limited) from that path, tmp leftovers included.
A1  the upgrade-window backfill also finds boards under OVERSEER_CENTRAL and a
    config ``central_dir``.
B3  every command the skills document is exercised against the guard."""
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_guard_round2 import (  # noqa: F401 -- `world` is a fixture
    BASH,
    OTHER,
    OWN,
    PLUGIN,
    SESSION,
    _stamp,
    assert_allowed,
    assert_denied,
    hook,
    world,
)

from scripts import hookfast, marker
from scripts.cli import main

UNAVAILABLE = "overseer guard unavailable"


def run_pretool(plugin_root, tool_input, *, tool="Bash", session=SESSION, python=None,
                extra_env=None, cwd="/w"):
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(plugin_root),
           "OVERSEER_PYTHON": python or sys.executable}
    env.pop("OVERSEER_REMOTE", None)
    env.update(extra_env or {})
    body = {"session_id": session, "cwd": cwd, "tool_name": tool, "tool_input": tool_input}
    run = subprocess.run([BASH, str(plugin_root / "hooks" / "pretool.sh")], input=json.dumps(body),
                         capture_output=True, text=True, check=False, env=env)
    assert run.returncode == 0, run.stderr
    if not run.stdout.strip():
        return "allow", ""
    out = json.loads(run.stdout)["hookSpecificOutput"]
    return out.get("permissionDecision", "allow"), out.get("permissionDecisionReason", "")


GUARDED = [
    ("Bash", {"command": "ls"}),
    ("Edit", {"file_path": "/r/a.py"}),
    ("Write", {"file_path": "/r/a.py"}),
    ("MultiEdit", {"file_path": "/r/a.py"}),
    ("NotebookEdit", {"notebook_path": "/r/a.ipynb"}),
    ("Agent", {"subagent_type": "general-purpose"}),
]


@pytest.fixture
def broken_plugin(tmp_path):
    """A copy of the plugin whose guard module no longer imports (a
    half-upgraded tree)."""
    root = tmp_path / "plugin"
    shutil.copytree(PLUGIN / "scripts", root / "scripts",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(PLUGIN / "hooks", root / "hooks")
    (root / "scripts" / "guard.py").write_text("def broken(:\n")
    return root


class TestPythonFailureFailsClosed:
    """B1 medium: the shell layer fell open whenever the interpreter failed."""

    @pytest.fixture
    def live(self, world):
        return world

    @pytest.mark.parametrize(("tool", "tool_input"), GUARDED)
    def test_missing_interpreter_denies_guarded_tools(self, live, tool, tool_input):
        verdict, why = run_pretool(PLUGIN, tool_input, tool=tool, python="/nonexistent/python")
        assert (verdict, why) == ("deny", UNAVAILABLE)

    @pytest.mark.parametrize(("tool", "tool_input"), GUARDED)
    def test_silent_nonzero_exit_denies_guarded_tools(self, live, tmp_path, tool, tool_input):
        stub = tmp_path / "dies"
        stub.write_text("#!/bin/sh\nexit 3\n")
        stub.chmod(0o755)
        assert run_pretool(PLUGIN, tool_input, tool=tool, python=str(stub)) == ("deny", UNAVAILABLE)

    def test_an_mcp_tool_is_guarded_too(self, live):
        verdict, why = run_pretool(PLUGIN, {}, tool="mcp__plugin_x-y__do", python="/nonexistent/python")
        assert (verdict, why) == ("deny", UNAVAILABLE)

    @pytest.mark.parametrize(("tool", "tool_input"), GUARDED)
    def test_an_import_failure_in_hookfast_denies(self, live, broken_plugin, tool, tool_input):
        verdict, why = run_pretool(broken_plugin, tool_input, tool=tool)
        assert verdict == "deny" and why, "import failure must deny, not traceback and allow"

    def test_an_import_failure_with_a_stub_that_just_tracebacks_still_denies(self, live, tmp_path):
        # even if python died before the import-failure net (rc != 0), the shell denies
        stub = tmp_path / "boom"
        stub.write_text('#!/bin/sh\necho Traceback >&2\nexit 1\n')
        stub.chmod(0o755)
        assert run_pretool(PLUGIN, {"command": "ls"}, python=str(stub))[0] == "deny"

    @pytest.mark.parametrize("tool", ["Read", "Grep", "Glob"])
    def test_read_only_tools_stay_open_when_python_fails(self, live, tool):
        assert run_pretool(PLUGIN, {"file_path": "/r/a"}, tool=tool,
                           python="/nonexistent/python")[0] == "allow"

    def test_a_session_without_a_marker_keeps_the_fast_allow_path(self, live):
        # sentinel present, no marker: the shell decides alone, python is never started
        (marker.marker_dir() / ".checked-sess-idle").touch()
        verdict, _ = run_pretool(PLUGIN, {"command": "ls"}, session="sess-idle",
                                 python="/nonexistent/python")
        assert verdict == "allow"

    def test_a_first_call_without_a_marker_is_not_blocked_by_a_broken_python(self, live):
        verdict, _ = run_pretool(PLUGIN, {"command": "ls"}, session="sess-new",
                                 python="/nonexistent/python")
        assert verdict == "allow"

    def test_the_healthy_path_is_unchanged(self, live):
        assert_denied(live, "cat README.md", session=SESSION)


class TestSentinelOnlyAfterACompleteLookup:
    """B2 low: a locked/unreadable board must not stick the session as checked."""

    def test_an_unreadable_board_leaves_no_sentinel_and_the_next_call_retries(
        self, world, monkeypatch
    ):
        shutil.rmtree(marker.marker_dir())
        real = marker.live_cards
        monkeypatch.setattr(marker, "live_cards", lambda db, sid: None)  # locked
        body = {"session_id": SESSION, "cwd": str(world["repo"]), "tool_name": "Bash",
                "tool_input": {"command": "ls"}}
        hookfast.run(json.dumps(body))
        assert not marker.is_checked(SESSION)
        assert marker.read_boards(SESSION) == []
        monkeypatch.setattr(marker, "live_cards", real)
        hookfast.run(json.dumps(body))
        assert marker.read_boards(SESSION), "the retry finds the board and writes the marker"

    def test_a_complete_lookup_with_nothing_found_still_writes_the_sentinel(self, world):
        body = {"session_id": "sess-idle", "cwd": str(world["repo"]), "tool_name": "Bash",
                "tool_input": {"command": "ls"}}
        hookfast.run(json.dumps(body))
        assert marker.is_checked("sess-idle")

    def test_a_missing_board_file_is_not_an_incomplete_lookup(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OVERSEER_DB", str(tmp_path / "nope.db"))
        assert marker.lookup_boards("s1") == ([], True)


class TestSweepOnTheFirstCallPath:
    def _age(self, path, seconds):
        old = time.time() - seconds
        os.utime(path, (old, old))

    def test_first_call_sweeps_stale_files_including_tmp_leftovers(self, world):
        d = marker.marker_dir()
        stale_sentinel = d / ".checked-old"
        stale_tmp = d / f".{SESSION}.4242.tmp"
        fresh_tmp = d / ".fresh.1.tmp"
        for path in (stale_sentinel, stale_tmp, fresh_tmp):
            path.touch()
        self._age(stale_sentinel, 8 * 24 * 3600)
        self._age(stale_tmp, 2 * 3600)
        body = {"session_id": "sess-first", "cwd": str(world["repo"]), "tool_name": "Bash",
                "tool_input": {"command": "ls"}}
        hookfast.run(json.dumps(body))
        assert not stale_sentinel.exists() and not stale_tmp.exists()
        assert fresh_tmp.exists() and (d / SESSION).exists()

    def test_sweep_runs_at_most_once_an_hour(self, world):
        d = marker.marker_dir()
        marker.sweep_if_due()
        late = d / ".checked-late"
        late.touch()
        self._age(late, 8 * 24 * 3600)
        assert marker.sweep_if_due() == 0 and late.exists()  # inside the hour
        self._age(d / marker.SWEEP_STAMP, 2 * 3600)
        marker.sweep_if_due()
        assert not late.exists()


class TestCentralBoardsAreFoundInTheUpgradeWindow:
    """A1 low: boards under OVERSEER_CENTRAL / config central_dir were never candidates."""

    @pytest.fixture
    def central_world(self, tmp_path, monkeypatch):
        central = tmp_path / "custom-central"
        repo = tmp_path / "repo"
        repo.mkdir()
        monkeypatch.setenv("OVERSEER_CENTRAL", str(central))
        monkeypatch.setenv("OVERSEER_DB", str(central / "board.db"))
        assert main(["--root", str(repo), "init"]) == 0
        assert main(["--root", str(repo), "new-card", "--title", "T"]) == 0
        _stamp(repo, SESSION, "WF-001")
        monkeypatch.delenv("OVERSEER_DB")  # the hook's own env never carries it
        shutil.rmtree(marker.marker_dir())  # the upgrade state
        return {"repo": repo, "tmp": tmp_path, "central": central}

    def test_overseer_central_without_overseer_db(self, central_world):
        boards = marker.find_boards_for_session(SESSION)
        assert [b.db for b in boards] == [central_world["central"] / "board.db"]

    def test_the_first_call_through_pretool_denies_and_writes_the_marker(self, central_world):
        verdict, _ = run_pretool(PLUGIN, {"command": "cat README.md"},
                                 cwd=str(central_world["repo"]))
        assert verdict == "deny"
        assert (marker.marker_dir() / SESSION).exists()

    def test_config_central_dir_from_the_payload_cwd(self, central_world, monkeypatch):
        cfg_dir = central_world["repo"] / ".overseer"
        cfg_dir.mkdir(exist_ok=True)
        (cfg_dir / "config.local.json").write_text(
            json.dumps({"central_dir": str(central_world["central"])}))
        monkeypatch.delenv("OVERSEER_CENTRAL")
        assert marker.find_boards_for_session(SESSION) == []  # no cwd, no config
        boards = marker.find_boards_for_session(SESSION, central_world["repo"])
        assert [b.db for b in boards] == [central_world["central"] / "board.db"]


# --------------------------------------------------------------------------
# B3: every documented command
# --------------------------------------------------------------------------

SKILLS = PLUGIN / "skills"
DOC_FILES = sorted([*SKILLS.glob("*/SKILL.md"), *SKILLS.glob("*/references/*.md"),
                    *SKILLS.glob("*/policy.md")])
ORCH_DIR = SKILLS / "orchestrate"
CLI_TOKEN = 'python3 "<base directory>/../../scripts/cli.py" --root .'
VERBS = set(re.findall(r'add_parser\("([a-z-]+)"', (PLUGIN / "scripts" / "cli.py").read_text()))
VERBS |= {"vigil", "handover", "handoff"}
HEREDOC = "<<'EOF'\nbody with $(x) and `y`\nEOF"

# Documented commands the guard deliberately denies to an orchestrating
# session, each with the reason. Key: the command exactly as extracted.
EXPECTED_DENY = {
    'main=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)") && (cd "$HOME" '
    '&& tmux new-session -d -s <name> -c "$main" -e CLAUDE_CODE_TASK_LIST_ID=<id> claude)':
        "install-time tmux relaunch: VAR=value, $(..) and a subshell -- run by the user, "
        "not by the guarded orchestrator",
}

_PLACEHOLDERS = {"<id>": "WF-001", "<P-id>": "P-1", "<other>": "WF-002", "<repo-root>": "."}
_ALT_WORD = re.compile(r"\S+(?:\\\|\S+)+")


def _alternatives(text: str) -> list[str]:
    parts = [p.strip() for p in text.split("\\|")]
    return parts


def _choices(command: str) -> list[list[str]]:
    """``command`` as a sequence of (literal | choice) slots; each slot is a
    list of options, option 0 being the default."""
    slots: list[list[str]] = []
    pos = 0
    group = re.compile(r"\[([^\[\]]*)\]|\(([^()]*\\\|[^()]*)\)|<([^<>]*\\\|[^<>]*)>")
    for m in group.finditer(command):
        slots.extend(_word_choices(command[pos:m.start()]))
        inner = next(g for g in m.groups() if g is not None)
        opts = _alternatives(inner)
        slots.append(["", *opts] if m.group(1) is not None else opts)
        pos = m.end()
    slots.extend(_word_choices(command[pos:]))
    return slots


def _word_choices(text: str) -> list[list[str]]:
    slots: list[list[str]] = []
    pos = 0
    for m in _ALT_WORD.finditer(text):
        slots.append([text[pos:m.start()]])
        slots.append(m.group(0).split("\\|"))
        pos = m.end()
    slots.append([text[pos:]])
    return slots


def _variants(command: str) -> list[str]:
    """The default reading, plus every other option of every choice varied one
    at a time (so each alternative and each optional group is exercised)."""
    slots = _choices(command)
    picks = [0] * len(slots)
    out = [list(picks)]
    for i, opts in enumerate(slots):
        for k in range(1, len(opts)):
            variant = list(picks)
            variant[i] = k
            out.append(variant)
    return [" ".join("".join(slots[i][p] for i, p in enumerate(v)).split()) for v in out]


def _fill(text: str) -> str:
    for key, value in _PLACEHOLDERS.items():
        text = text.replace(key, value)
    text = re.sub(r"\s*\.\.\.(?=\s|$)", "", text)  # "k=v ..." / "<command> ..."
    text = re.sub(r"<[^<>\n]*>", "x", text)
    return text.strip()


def _with_heredoc(command: str) -> str:
    return f"{command} {HEREDOC}" if re.search(r"(^|\s)-$", command) else command


def _cli(verb_command: str) -> str:
    return f"{CLI_TOKEN} {verb_command}"


def extract_documented_commands() -> list[tuple[str, str, str]]:
    """(source, key, shell command) for every command the skills document:
    the verb table, inline verb / vigil / git / gh spans, fenced lines and the
    heredoc forms. ``key`` is the text as written (EXPECTED_DENY's key)."""
    found: list[tuple[str, str, str]] = []
    for path in DOC_FILES:
        text = path.read_text()
        for m in re.finditer(r"^```[^\n]*\n(.*?)^```", text, re.S | re.M):
            for line in m.group(1).splitlines():
                line = line.strip()
                if not line:
                    continue
                real = line.replace("<base directory>", str(ORCH_DIR))
                real = real.replace("python plugins/overseer/scripts/cli.py", f"python3 {OWN}")
                real = real.replace(".../cli.py", str(OWN))
                for variant in _variants(real):
                    found.append((path.name, line, _fill(variant)))
        prose = re.sub(r"^```[^\n]*\n.*?^```", "", text, flags=re.S | re.M)
        for m in re.finditer(r"(?<!`)`([^`]+)`(?!`)", prose):
            span = re.sub(r"(?<!\\)\|", r"\\|", " ".join(m.group(1).split()))  # prose `a|b`
            first = span.split()[0]
            if first in VERBS and (len(span.split()) > 1 or first in {
                    "resume", "handover", "handoff", "usage", "init", "backup"}):
                for variant in _variants(span):
                    found.append((path.name, span, _cli(_with_heredoc(_fill(variant)))))
            elif first in {"vigil", "git", "gh"} and len(span.split()) > 1:
                for variant in _variants(span):
                    found.append((path.name, span, _fill(variant)))
            elif first in {"cd", "main=$(dirname"}:
                found.append((path.name, span, _fill(span)))
            for flag in re.findall(r"--(?:brief|text) -(?=\s|$)", span):
                verb = "bootstrap --title x" if "brief" in flag else "set-section WF-001 --section Plan"
                found.append((path.name, f"{verb} {flag} <heredoc>",
                              _cli(f"{verb} {flag} {HEREDOC}")))
    for path in DOC_FILES:  # verb table rows
        for line in path.read_text().splitlines():
            if not line.startswith("| `"):
                continue
            cells = [c for c in re.split(r"(?<!\\)\|", line) if c.strip()]
            if len(cells) < 2:
                continue
            for span in re.findall(r"`([^`]+)`", cells[1]):
                if span.split()[0] not in VERBS:
                    continue  # not a verb row (e.g. a template-variable table)
                for variant in _variants(span.strip()):
                    found.append((path.name, span, _cli(_with_heredoc(_fill(variant)))))
    # de-duplicate on the command, keep the first source
    seen: dict[str, tuple[str, str, str]] = {}
    for item in found:
        seen.setdefault(item[2], item)
    return list(seen.values())


class TestEveryDocumentedCommand:
    """B3 low: the old test matched two lines; the skills document dozens."""

    def test_the_extractor_sees_the_whole_vocabulary(self):
        commands = [c for _s, _k, c in extract_documented_commands()]
        text = "\n".join(commands)
        for needle in ("show WF-001", " resume", " handover", "vigil begin", "vigil context",
                       "set-section WF-001 --section Plan --text-file", "--text - <<'EOF'",
                       "bootstrap --title", "--brief - <<'EOF'", "dispatch-prep WF-001 --stage",
                       "--role verifier", "accept-fact P-1", "git push", "git worktree remove",
                       "block WF-001 --reason"):
            assert needle in text, needle
        assert len(commands) >= 60, len(commands)
        for _s, key, _c in extract_documented_commands():
            bare = _c.replace(HEREDOC, "").replace("<base directory>", "")
            assert "<" not in bare or key in EXPECTED_DENY, _c

    def test_every_documented_command_is_allowed_or_expected_denied(self, world):
        wrong: list[str] = []
        for source, key, command in extract_documented_commands():
            real = command.replace("<base directory>", str(ORCH_DIR))
            verdict, why = hook(world, real)
            if key in EXPECTED_DENY:
                if verdict != "deny":
                    wrong.append(f"{source}: expected deny, got allow: {key}")
            elif verdict != "allow":
                wrong.append(f"{source}: {command!r} denied: {why[:100]}")
        assert not wrong, "\n".join(wrong)

    def test_expected_denies_are_all_still_documented(self):
        keys = {k for _s, k, _c in extract_documented_commands()}
        stale = [k for k in EXPECTED_DENY if " ".join(k.split()) not in keys]
        assert not stale, f"EXPECTED_DENY entries no longer documented: {stale}"
