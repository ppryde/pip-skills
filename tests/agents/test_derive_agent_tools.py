"""tools/derive_agent_tools.py and the evidence lint (permits PR 3)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys

import pytest
from conftest import PLUGIN, ROOT

TOOL = ROOT / "tools" / "derive_agent_tools.py"
SNAPSHOT = ROOT / "tests" / "agents" / "evidence.json"
AGENTS = PLUGIN / "agents"
SECRET = "SECRETARG-acme-4242"


def run(*args, cwd=None):
    return subprocess.run([sys.executable, "-I", str(TOOL), *args], capture_output=True, text=True, cwd=cwd)


def group(agent_type, *, agents, calls=100, denied=None, prompts=0):
    return {"skill": "x", "agent_type": agent_type, "agents": agents, "calls": calls,
            "denied_by_cause": denied or {}, "prompts_total": prompts}


def tool_row(agent_type, tool, calls, outcomes=None, flagged=None):
    return {"skill": "x", "agent_type": agent_type, "tool": tool, "calls": calls,
            "outcomes": outcomes or {"ok": calls}, "flagged_shapes": flagged or []}


def flagged(shape, outcomes, temporary=0, reasons=None):
    return {"shape": shape, "outcomes": outcomes, "calls": sum(outcomes.values()),
            "approved_temporary": temporary, "reasons": reasons or {}}


def write_evidence(tmp_path, groups=(), tools=()):
    path = tmp_path / "permits.json"
    path.write_text(json.dumps({"supported": True, "groups": list(groups), "tools": list(tools),
                                "drift": {}}))
    return path


@pytest.fixture
def agents_dir(tmp_path):
    """A plugin copy whose personas keep their tools in personas/tools.md, plus a hand-written agent."""
    plugin = tmp_path / "plugins" / "demo"
    (plugin / "agents").mkdir(parents=True)
    (plugin / "personas").mkdir()
    (plugin / "personas" / "tools.md").write_text(
        "| persona | kind | tools | evidence | withheld |\n|---|---|---|---|---|\n"
        "| sifter | review | Read, Grep, Glob, Bash | e | w |\n"
        "| runner | run | Bash, Read, Monitor | e | w |\n")
    for name, tools in (("sifter", "Read, Grep, Glob, Bash"), ("runner", "Bash, Read, Monitor")):
        (plugin / "agents" / f"{name}.md").write_text(
            f"---\nname: {name}\ndescription: d.\ntools: {tools}\nmodel: sonnet\n---\nbody\n")
    return plugin / "agents"


# ---- the generator -----------------------------------------------------------------------------------

class TestProposals:
    def test_tightening_removes_an_exposed_unused_tool(self, tmp_path, agents_dir):
        ev = write_evidence(tmp_path, [group("demo:runner", agents=12)],
                            [tool_row("demo:runner", "Bash", 50), tool_row("demo:runner", "Read", 40)])
        p = run("--evidence", str(ev), "--agents", str(agents_dir), "--snapshot-file", str(tmp_path / "none.json"))
        assert p.returncode == 0, p.stderr
        assert "TIGHTENS demo:runner: remove Monitor" in p.stdout
        assert "-| runner | run | Bash, Read, Monitor |" in p.stdout
        assert "+| runner | run | Bash, Read |" in p.stdout
        assert "build_agents.py" in p.stdout            # the agent files are generated from tools.md

    def test_below_min_runs_nothing_is_proposed(self, tmp_path, agents_dir):
        ev = write_evidence(tmp_path, [group("demo:runner", agents=3)], [tool_row("demo:runner", "Bash", 5)])
        p = run("--evidence", str(ev), "--agents", str(agents_dir), "--snapshot-file", str(tmp_path / "n.json"))
        assert "No tool-list change is proposed" in p.stdout
        assert "3 of 10 runs; below --min-runs" in p.stdout
        p = run("--evidence", str(ev), "--agents", str(agents_dir), "--min-runs", "3",
                "--snapshot-file", str(tmp_path / "n.json"))
        assert "remove Monitor" in p.stdout

    def test_day_one_with_no_evidence_proposes_nothing(self, tmp_path, agents_dir):
        ev = write_evidence(tmp_path)
        p = run("--evidence", str(ev), "--agents", str(agents_dir), "--snapshot-file", str(SNAPSHOT))
        assert p.returncode == 0 and "No tool-list change is proposed" in p.stdout

    def test_grep_and_glob_are_never_removed_while_bash_is_granted(self, tmp_path, agents_dir):
        """A persona `Read, Grep, Glob, Bash` with zero Grep calls: Grep/Glob are not exposed next to Bash."""
        ev = write_evidence(tmp_path, [group("demo:sifter", agents=20)],
                            [tool_row("demo:sifter", "Read", 80), tool_row("demo:sifter", "Bash", 80)])
        p = run("--evidence", str(ev), "--agents", str(agents_dir), "--snapshot-file", str(tmp_path / "n.json"))
        assert "remove Grep" not in p.stdout and "remove Glob" not in p.stdout
        assert "No tool-list change is proposed" in p.stdout

    def test_grep_is_removable_when_bash_is_not_granted(self, tmp_path):
        plugin = tmp_path / "plugins" / "demo"
        (plugin / "agents").mkdir(parents=True)
        (plugin / "agents" / "scan.md").write_text(
            "---\nname: scan\ndescription: d.\ntools: Read, Grep, Glob\nmodel: sonnet\n---\nbody\n")
        ev = write_evidence(tmp_path, [group("demo:scan", agents=15)], [tool_row("demo:scan", "Read", 60)])
        p = run("--evidence", str(ev), "--agents", str(plugin / "agents"),
                "--snapshot-file", str(tmp_path / "n.json"))
        assert "remove Grep" in p.stdout and "remove Glob" in p.stdout
        assert "+tools: Read" in p.stdout                 # hand-written frontmatter is edited in place

    def test_loosening_needs_evidence_of_need_and_is_labelled(self, tmp_path, agents_dir):
        ev = write_evidence(tmp_path, [group("demo:runner", agents=12)], [
            tool_row("demo:runner", "Bash", 50), tool_row("demo:runner", "Read", 40),
            tool_row("demo:runner", "Monitor", 9),
            tool_row("demo:runner", "Edit", 4, {"error:no-such-tool": 4}),
            tool_row("demo:runner", "WebFetch", 4, {"denied:classifier": 4})])
        p = run("--evidence", str(ev), "--agents", str(agents_dir), "--snapshot-file", str(tmp_path / "n.json"))
        assert "LOOSENS demo:runner: add Edit" in p.stdout
        assert "add WebFetch" not in p.stdout             # a denial is not a missing tool

    def test_allow_rules_only_for_read_only_shapes_approved_every_time(self, tmp_path, agents_dir):
        bash = tool_row("demo:runner", "Bash", 50, flagged=[
            flagged("git status", {"prompted:approved": 5}, temporary=5),
            flagged("git status +compound", {"prompted:approved": 9}, temporary=9),
            flagged("rm", {"prompted:approved": 9}, temporary=9),            # not read-only
            flagged("ls", {"prompted:approved": 6}, temporary=1),            # mostly permanent: the rule exists
            flagged("cat", {"prompted:approved": 4, "prompted:rejected": 1}, temporary=4)])
        ev = write_evidence(tmp_path, [group("demo:runner", agents=12)], [bash])
        p = run("--evidence", str(ev), "--agents", str(agents_dir), "--snapshot-file", str(tmp_path / "n.json"))
        assert 'allow  "Bash(git status:*)",  // LOOSENS' in p.stdout
        for refused in ("Bash(rm:*)", "Bash(ls:*)", "Bash(cat:*)", "compound"):
            assert f'allow  "{refused}' not in p.stdout, refused

    def test_a_denied_shape_never_becomes_an_allow_rule(self, tmp_path, agents_dir):
        causes = {"denied:classifier": 4, "denied:worktree-guard": 4, "denied:sleep-guard": 4,
                  "denied:safety-check": 4}
        rows = [flagged(f"git log{i}", {cause: n, "prompted:approved": 9}, temporary=9,
                        reasons={"wt:too-complex": n} if "worktree" in cause else {})
                for i, (cause, n) in enumerate(causes.items())]
        rows.append(flagged("git show", {"denied:worktree-guard": 5}, reasons={"wt:git-form-too-complex": 5}))
        ev = write_evidence(tmp_path, [group("demo:runner", agents=12)],
                            [tool_row("demo:runner", "Bash", 50, flagged=rows)])
        p = run("--evidence", str(ev), "--agents", str(agents_dir), "--snapshot-file", str(tmp_path / "n.json"))
        assert "allow " not in "\n".join(line for line in p.stdout.splitlines() if "#   allow" in line)
        assert "git show: denied:worktree-guard 5x (wt:git-form-too-complex=5)" in p.stdout
        assert "Investigate the command shape" in p.stdout

    def test_repeated_classifier_denials_propose_a_labelled_deny(self, tmp_path, agents_dir):
        ev = write_evidence(tmp_path, [group("demo:runner", agents=12)], [tool_row(
            "demo:runner", "Bash", 50, flagged=[flagged("claude", {"denied:classifier": 3})])])
        p = run("--evidence", str(ev), "--agents", str(agents_dir), "--snapshot-file", str(tmp_path / "n.json"))
        assert 'deny   "Bash(claude:*)",  // TIGHTENS' in p.stdout

    def test_unobserved_reason_is_shown_beside_a_tightening(self, tmp_path, agents_dir):
        snap = tmp_path / "snap.json"
        snap.write_text(json.dumps({"format": 1, "personas": {},
                                    "unobserved": {"demo:runner": {"Monitor": "backs the sleep charter"}}}))
        ev = write_evidence(tmp_path, [group("demo:runner", agents=12)],
                            [tool_row("demo:runner", "Bash", 50), tool_row("demo:runner", "Read", 40)])
        p = run("--evidence", str(ev), "--agents", str(agents_dir), "--snapshot-file", str(snap))
        assert "listed unobserved (backs the sleep charter)" in p.stdout

    def test_the_emitted_diff_applies_with_git_apply(self, tmp_path, agents_dir):
        # git apply wants a/ b/ paths relative to the tree root: run it from the plugin's parent
        ev = write_evidence(tmp_path, [group("demo:runner", agents=12)],
                            [tool_row("demo:runner", "Bash", 50), tool_row("demo:runner", "Read", 40)])
        p = run("--evidence", str(ev), "--agents", str(agents_dir), "--snapshot-file", str(tmp_path / "n.json"))
        patch = p.stdout.replace(f"a/{tmp_path.as_posix().lstrip('/')}/", "a/").replace(
            f"b/{tmp_path.as_posix().lstrip('/')}/", "b/")
        (tmp_path / "x.patch").write_text(patch)
        out = subprocess.run(["git", "apply", "--check", "-p1", "x.patch"], cwd=tmp_path,
                             capture_output=True, text=True)
        assert out.returncode == 0, (out.stderr, patch)


class TestReadOnly:
    def test_it_writes_nothing(self, tmp_path, agents_dir):
        ev = write_evidence(tmp_path, [group("demo:runner", agents=12)], [tool_row("demo:runner", "Bash", 50)])
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob("*") if p.is_file()}
        os.chmod(tmp_path, 0o555)
        try:
            for extra in ([], ["--snapshot"], ["--check"]):
                p = run("--evidence", str(ev), "--agents", str(agents_dir),
                        "--snapshot-file", str(tmp_path / "plugins" / "none.json"), *extra)
                assert p.returncode in (0, 1), p.stderr
        finally:
            os.chmod(tmp_path, 0o755)
        after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob("*") if p.is_file()}
        assert before == after

    def test_the_source_opens_no_file_for_writing(self):
        text = TOOL.read_text()
        assert not re.search(r"open\([^)]*['\"][wax+]", text)
        for banned in ("write_text", "write_bytes", ".unlink(", ".rename(", "os.replace", "shutil"):
            assert banned not in text, banned


class TestSnapshot:
    def test_snapshot_is_aggregates_only_and_carries_unobserved_reasons(self, tmp_path):
        ev = write_evidence(
            tmp_path, [group("pip-agents:explorer", agents=4, calls=12, denied={"sleep-guard": 1}, prompts=2),
                       group("overseer:overseer-reviewer", agents=9)],
            [tool_row("pip-agents:explorer", "Read", 12, flagged=[flagged(SECRET, {"denied:sleep-guard": 1})]),
             tool_row("pip-agents:explorer", "Grep", 0)])
        p = run("--evidence", str(ev), "--snapshot")
        assert p.returncode == 0, p.stderr
        snap = json.loads(p.stdout)
        assert snap["personas"] == {"pip-agents:explorer": {
            "runs": 4, "calls": 12, "tools": {"Grep": 0, "Read": 12}, "denied": {"sleep-guard": 1}, "prompts": 2}}
        assert snap["unobserved"] == json.loads(SNAPSHOT.read_text())["unobserved"]
        assert SECRET not in p.stdout                       # shapes never enter the snapshot

    def test_check_reports_drift_and_passes_when_equal(self, tmp_path):
        ev = write_evidence(tmp_path, [group("pip-agents:explorer", agents=4)],
                            [tool_row("pip-agents:explorer", "Read", 4)])
        drift = run("--evidence", str(ev), "--check")
        assert drift.returncode == 1 and "pip-agents:explorer" in drift.stdout
        committed = tmp_path / "evidence.json"
        committed.write_text(run("--evidence", str(ev), "--snapshot").stdout)
        assert run("--evidence", str(ev), "--check", "--snapshot-file", str(committed)).returncode == 0

    def test_bad_evidence_exits_2(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"supported": False, "note": "run chronicle sync"}))
        p = run("--evidence", str(bad))
        assert p.returncode == 2 and "run chronicle sync" in p.stderr
        assert run("--evidence", str(tmp_path / "missing.json")).returncode == 2


# ---- the persona lint --------------------------------------------------------------------------------

def granted(name):
    text = (AGENTS / f"{name}.md").read_text()
    return [t.strip() for t in re.search(r"^tools: (.*)$", text, re.MULTILINE).group(1).split(",")]


PERSONAS = sorted(p.stem for p in AGENTS.glob("*.md"))


class TestEvidenceLint:
    """Every granted tool is observed in the snapshot or listed `unobserved:` with a reason. On day one the
    snapshot has no `pip-agents:*` evidence, so every grant is `unobserved:`: that is the starting state, not a
    defect, and the generator proposes nothing for a persona below --min-runs."""

    def snapshot(self):
        return json.loads(SNAPSHOT.read_text())

    def test_snapshot_shape(self):
        snap = self.snapshot()
        assert snap["format"] == 1 and set(snap) == {"format", "personas", "unobserved"}
        for persona, entry in snap["personas"].items():
            assert persona.startswith("pip-agents:") and persona.split(":")[1] in PERSONAS
            assert set(entry) == {"runs", "calls", "tools", "denied", "prompts"}
            assert all(isinstance(entry[k], int) for k in ("runs", "calls", "prompts"))
            assert all(isinstance(n, int) for n in {**entry["tools"], **entry["denied"]}.values())

    def test_every_granted_tool_is_observed_or_unobserved_with_a_reason(self):
        snap = self.snapshot()
        for name in PERSONAS:
            pid = f"pip-agents:{name}"
            observed = {t for t, n in snap["personas"].get(pid, {}).get("tools", {}).items() if n > 0}
            reasons = snap["unobserved"].get(pid, {})
            for tool in granted(name):
                assert tool in observed or reasons.get(tool, "").strip(), (name, tool)

    def test_unobserved_lists_nothing_stale(self):
        snap = self.snapshot()
        for pid, reasons in snap["unobserved"].items():
            name = pid.split(":")[1]
            assert name in PERSONAS, pid
            observed = {t for t, n in snap["personas"].get(pid, {}).get("tools", {}).items() if n > 0}
            for tool, reason in reasons.items():
                assert tool in granted(name), (pid, tool, "not granted: remove the stale reason")
                assert tool not in observed, (pid, tool, "now observed: drop the reason")
                assert "\n" not in reason and 0 < len(reason) <= 200, (pid, tool)

    def test_agent_and_skill_need_a_reason(self):
        snap = self.snapshot()
        for name in PERSONAS:
            for tool in granted(name):
                if tool in ("Agent", "Skill"):
                    assert snap["unobserved"].get(f"pip-agents:{name}", {}).get(tool), (name, tool)

    def test_snapshot_carries_no_free_text_beyond_reasons(self):
        text = SNAPSHOT.read_text()
        assert "/Users/" not in text and "SECRET" not in text
