#!/usr/bin/env python3
"""Propose agent `tools:` changes from `chronicle permits --json` evidence (permits PR 3).

Stdlib only, deterministic, and READ-ONLY: it prints to stdout and opens no file for writing. A person applies
a diff with `git apply` in a reviewed PR; nothing is ever changed automatically.

    chronicle permits --json > permits.json
    python3 tools/derive_agent_tools.py --evidence permits.json              # proposals: diffs + settings snippet
    python3 tools/derive_agent_tools.py --evidence permits.json --snapshot   # the tests/agents/evidence.json text
    python3 tools/derive_agent_tools.py --evidence permits.json --check      # diff the committed snapshot; exit 1 on drift

Rules (each enforced by tests/agents/test_derive_agent_tools.py):

* TIGHTENING (remove a granted tool that was exposed and unused across >= --min-runs runs; deny a shape the
  classifier keeps refusing) is proposed normally.
* LOOSENING (add a tool, or an allow rule) is proposed only for evidence of need: "No such tool available" for an
  ungranted tool, or a read-only shape a person approved THIS time (`user_temporary`) at least 3 times and
  never otherwise. Every such line is marked LOOSENS.
* NEVER proposed: an allow rule for anything the classifier, the safety check, the worktree guard or the sleep
  guard refused. Those are listed under "investigate the command shape" with their sub-cause; the remedy is
  charter text a human writes ("one plain command per Bash call; Monitor, not sleep"), never a rule that approves
  the shape.
* A persona below --min-runs gets nothing proposed (day one: no `pip-agents:*` run exists, so every grant is
  `unobserved:` with a reason in the snapshot).
* "Unused" means exposed and unused: with Bash granted this build exposes no separate Grep or Glob (0 calls in
  33k results), so those two are never proposed for removal (UNOBSERVABLE).

Exit codes: 0 ok; 1 --check found drift; 2 bad input.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AGENTS = [ROOT / "plugins" / "pip-agents" / "agents"]
DEFAULT_SNAPSHOT = ROOT / "tests" / "agents" / "evidence.json"
FORMAT = 1
DEFAULT_MIN_RUNS = 10
MIN_APPROVALS = 3          # "prompted >= 3 and approved every time"
MIN_DENIALS = 3            # "repeatedly classifier-denied"

# A tool this build does not expose next to Bash, so zero calls prove nothing.
UNOBSERVABLE = {"Grep": "Bash", "Glob": "Bash"}
# The only shapes ever suggested as allow rules (read-only; never a compound).
READ_ONLY_SHAPES = ("git status", "git diff", "git log", "git show", "ls", "grep", "cat", "pytest")
# Denials whose remedy is never a rule (permissions.verdict, WORKER_BRIEF).
NEVER_ALLOW = ("denied:classifier", "denied:safety-check", "denied:worktree-guard", "denied:sleep-guard",
               "denied:classifier-unavailable", "denied:hook", "denied:config-rule",
               "denied:file-outside-root", "denied:no-prompt-available")


class InputError(Exception):
    """Unusable evidence or agent files (exit 2)."""


@dataclass
class Persona:
    id: str                    # "<plugin>:<name>", the form agentType carries
    name: str
    path: Path                 # the agent file
    tools: list[str]
    source: Path | None = None  # personas/tools.md when the plugin keeps its grants there


@dataclass
class Proposal:
    persona: str
    kind: str                  # TIGHTENS | LOOSENS
    tool: str
    why: str
    unobserved_note: str = ""


@dataclass
class Plan:
    proposals: list[Proposal] = field(default_factory=list)
    below_min: list[tuple[str, int]] = field(default_factory=list)
    allow: list[tuple[str, str]] = field(default_factory=list)       # (rule, why) LOOSENS
    deny: list[tuple[str, str]] = field(default_factory=list)        # (rule, why) TIGHTENS
    investigate: list[tuple[str, str, str]] = field(default_factory=list)  # (shape, cause, count text)


# ---- inputs --------------------------------------------------------------------------------------------------

def load_evidence(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise InputError(f"{path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("supported") is not True:
        note = data.get("note") if isinstance(data, dict) else None
        raise InputError(f"{path}: not a `chronicle permits --json` report ({note or 'supported is not true'})")
    for key in ("groups", "tools"):
        if not isinstance(data.get(key), list):
            raise InputError(f"{path}: missing {key!r}")
    return data


def _frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n") or "\n---\n" not in text:
        return {}
    head = text[4:].split("\n---\n", 1)[0]
    return dict(line.split(": ", 1) for line in head.splitlines() if ": " in line)


def load_personas(agent_dirs: list[Path]) -> list[Persona]:
    personas: list[Persona] = []
    for directory in agent_dirs:
        plugin = directory.resolve().parent.name
        tools_md = directory.resolve().parent / "personas" / "tools.md"
        for path in sorted(directory.glob("*.md")):
            fm = _frontmatter(path.read_text())
            if "tools" not in fm:
                continue
            name = fm.get("name", path.stem)
            personas.append(Persona(
                id=f"{plugin}:{name}", name=name, path=path,
                tools=[t.strip() for t in fm["tools"].split(",") if t.strip()],
                source=tools_md if tools_md.is_file() else None))
    return personas


def load_snapshot(path: Path) -> dict:
    if not path.is_file():
        return {"format": FORMAT, "personas": {}, "unobserved": {}}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise InputError(f"{path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise InputError(f"{path}: not an evidence snapshot of format {FORMAT}")
    return data


# ---- evidence -> per-persona aggregates ---------------------------------------------------------------------

def summarise(evidence: dict, persona_id: str) -> dict:
    """Runs, calls, tools used (with counts), denial causes and prompts for one persona (agent type)."""
    groups = [g for g in evidence["groups"] if g.get("agent_type") == persona_id]
    denied: dict[str, int] = {}
    for g in groups:
        for cause, n in (g.get("denied_by_cause") or {}).items():
            denied[cause] = denied.get(cause, 0) + int(n)
    tools: dict[str, int] = {}
    for t in evidence["tools"]:
        if t.get("agent_type") == persona_id:
            tools[t["tool"]] = tools.get(t["tool"], 0) + int(t.get("calls", 0))
    return {
        "runs": sum(int(g.get("agents", 0)) for g in groups),
        "calls": sum(int(g.get("calls", 0)) for g in groups),
        "tools": dict(sorted(tools.items())),
        "denied": dict(sorted(denied.items())),
        "prompts": sum(int(g.get("prompts_total", 0)) for g in groups),
    }


def build_snapshot(evidence: dict, personas: list[Persona], previous: dict) -> dict:
    """The committed aggregates: only personas with evidence, plus the human-written `unobserved` reasons carried
    over from the previous snapshot (the generator never invents or drops a reason)."""
    seen = {}
    for persona in personas:
        summary = summarise(evidence, persona.id)
        if summary["runs"] or summary["calls"]:
            seen[persona.id] = summary
    return {"format": FORMAT, "personas": dict(sorted(seen.items())),
            "unobserved": previous.get("unobserved", {})}


def render_snapshot(snapshot: dict) -> str:
    return json.dumps(snapshot, indent=2, sort_keys=True) + "\n"


# ---- proposals ----------------------------------------------------------------------------------------------

def _unobservable(tool: str, granted: list[str]) -> bool:
    return UNOBSERVABLE.get(tool) in granted


def _shape_rule(shape: str) -> str | None:
    if "+compound" in shape or shape.startswith("("):
        return None
    return f"Bash({shape}:*)"


def plan_for(evidence: dict, personas: list[Persona], snapshot: dict, min_runs: int) -> Plan:
    plan = Plan()
    unobserved = snapshot.get("unobserved", {})
    for persona in personas:
        summary = summarise(evidence, persona.id)
        if summary["runs"] < min_runs:
            if summary["runs"]:
                plan.below_min.append((persona.id, summary["runs"]))
            continue
        for tool in persona.tools:
            if tool in summary["tools"] or _unobservable(tool, persona.tools):
                continue
            note = (unobserved.get(persona.id) or {}).get(tool, "")
            plan.proposals.append(Proposal(
                persona.id, "TIGHTENS", tool,
                f"granted, exposed and unused across {summary['runs']} runs ({summary['calls']} calls)",
                f"listed unobserved ({note}): check that reason still holds" if note else ""))
        for row in evidence["tools"]:
            if row.get("agent_type") != persona.id or row["tool"] in persona.tools:
                continue
            outcomes = row.get("outcomes") or {}
            hits = int(outcomes.get("error:no-such-tool", 0)) + int(outcomes.get("error:input-validation", 0))
            if hits:
                plan.proposals.append(Proposal(
                    persona.id, "LOOSENS", row["tool"],
                    f"{hits} 'no such tool' / input-validation hit(s) for an ungranted tool across "
                    f"{summary['runs']} runs"))
    _shape_rules(evidence, plan)
    return plan


def _shape_rules(evidence: dict, plan: Plan) -> None:
    """Allow/deny lines from flagged Bash shapes, across every agent type."""
    merged: dict[str, dict] = {}
    for row in evidence["tools"]:
        if row.get("tool") != "Bash":
            continue
        for flagged in row.get("flagged_shapes") or []:
            slot = merged.setdefault(flagged["shape"], {"outcomes": {}, "temporary": 0, "reasons": {}})
            for outcome, n in (flagged.get("outcomes") or {}).items():
                slot["outcomes"][outcome] = slot["outcomes"].get(outcome, 0) + int(n)
            slot["temporary"] += int(flagged.get("approved_temporary", 0))
            for reason, n in (flagged.get("reasons") or {}).items():
                slot["reasons"][reason] = slot["reasons"].get(reason, 0) + int(n)
    for shape, slot in sorted(merged.items()):
        outcomes = slot["outcomes"]
        refused = {o: n for o, n in outcomes.items() if o in NEVER_ALLOW}
        for outcome, n in sorted(refused.items()):
            causes = ", ".join(f"{r}={c}" for r, c in sorted(slot["reasons"].items())) or "no sub-cause"
            plan.investigate.append((shape, outcome, f"{n}x ({causes})"))
        classifier = outcomes.get("denied:classifier", 0)
        rule = _shape_rule(shape)
        if classifier >= MIN_DENIALS and rule:
            plan.deny.append((rule, (f"classifier-denied {classifier}x; a deny also blocks the runs the "
                                     f"classifier allowed, so review before applying")))
        only_approved = set(outcomes) == {"prompted:approved"}
        if (only_approved and slot["temporary"] >= MIN_APPROVALS and rule
                and shape in READ_ONLY_SHAPES):
            plan.allow.append((rule, (f"prompted {outcomes['prompted:approved']}x, approved every time "
                                      f"({slot['temporary']} temporary approvals); read-only shape")))


# ---- diffs --------------------------------------------------------------------------------------------------

def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix().lstrip("/")


def _edit_row(text: str, persona: str, tools: list[str]) -> str:
    out = []
    for line in text.splitlines(keepends=True):
        cells = line.split("|")
        if len(cells) >= 6 and cells[1].strip() == persona.split(":", 1)[1]:
            cells[3] = f" {', '.join(tools)} "
            line = "|".join(cells)
        out.append(line)
    return "".join(out)


def _edit_frontmatter(text: str, tools: list[str]) -> str:
    return re.sub(r"^tools: .*$", f"tools: {', '.join(tools)}", text, count=1, flags=re.MULTILINE)


def tools_after(persona: Persona, proposals: list[Proposal]) -> list[str]:
    tools = list(persona.tools)
    for p in proposals:
        if p.persona != persona.id:
            continue
        if p.kind == "TIGHTENS" and p.tool in tools:
            tools.remove(p.tool)
        elif p.kind == "LOOSENS" and p.tool not in tools:
            tools.append(p.tool)
    return tools


def diffs(personas: list[Persona], plan: Plan) -> list[tuple[Path, list[Proposal], str]]:
    """One unified diff per file that would change: the plugin's `personas/tools.md` when it keeps its grants
    there (re-run its build afterwards), else the agent file's own frontmatter."""
    by_file: dict[Path, tuple[str, list[Proposal]]] = {}
    for persona in personas:
        mine = [p for p in plan.proposals if p.persona == persona.id]
        if not mine:
            continue
        target = persona.source or persona.path
        text = by_file.get(target, (target.read_text(), []))[0]
        after = tools_after(persona, mine)
        text = _edit_row(text, persona.id, after) if persona.source else _edit_frontmatter(text, after)
        by_file[target] = (text, by_file.get(target, ("", []))[1] + mine)
    out = []
    for target, (new_text, proposals) in sorted(by_file.items()):
        old = target.read_text().splitlines(keepends=True)
        patch = "".join(difflib.unified_diff(old, new_text.splitlines(keepends=True),
                                             f"a/{_rel(target)}", f"b/{_rel(target)}"))
        out.append((target, proposals, patch))
    return out


# ---- output -------------------------------------------------------------------------------------------------

def render_plan(plan: Plan, personas: list[Persona], min_runs: int, source: str) -> str:
    lines = ["# derive_agent_tools: proposals for human review. Nothing was written.",
             f"# evidence: {source}; --min-runs {min_runs}", ""]
    changed = diffs(personas, plan)
    if not changed:
        lines.append("# No tool-list change is proposed.")
    for target, proposals, patch in changed:
        for p in proposals:
            lines.append(f"# {p.kind} {p.persona}: {'remove' if p.kind == 'TIGHTENS' else 'add'} {p.tool}: {p.why}"
                         + (f" [{p.unobserved_note}]" if p.unobserved_note else ""))
        if target.name == "tools.md":
            lines.append("# After applying, run `python3 tools/build_agents.py` (the agent files are generated).")
        lines.append(patch.rstrip("\n"))
        lines.append("")
    for persona_id, runs in plan.below_min:
        lines.append(f"# {persona_id}: {runs} of {min_runs} runs; below --min-runs, nothing proposed.")
    if plan.investigate:
        lines += ["", "# Investigate the command shape (never an allow rule; the remedy is charter text):"]
        lines += [f"#   {shape}: {outcome} {detail}" for shape, outcome, detail in plan.investigate]
    if plan.allow or plan.deny:
        lines += ["", "# Suggested lines for YOUR OWN settings.json permissions (plugins ship no allow rules).",
                  "# The // comments below are labels, not JSON."]
        lines += [f'#   allow  "{rule}",  // LOOSENS: {why}' for rule, why in plan.allow]
        lines += [f'#   deny   "{rule}",  // TIGHTENS: {why}' for rule, why in plan.deny]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--evidence", required=True, type=Path, help="output of `chronicle permits --json`")
    parser.add_argument("--agents", action="append", type=Path, default=None,
                        help="an agents/ directory (repeatable; default plugins/pip-agents/agents)")
    parser.add_argument("--snapshot-file", type=Path, default=DEFAULT_SNAPSHOT,
                        help="the committed snapshot (default tests/agents/evidence.json)")
    parser.add_argument("--min-runs", type=int, default=DEFAULT_MIN_RUNS)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--snapshot", action="store_true", help="print the snapshot text; write nothing")
    mode.add_argument("--check", action="store_true", help="diff the committed snapshot; exit 1 on drift")
    args = parser.parse_args(argv)
    try:
        evidence = load_evidence(args.evidence)
        personas = load_personas(args.agents or DEFAULT_AGENTS)
        previous = load_snapshot(args.snapshot_file)
    except InputError as exc:
        print(f"derive_agent_tools: {exc}", file=sys.stderr)
        return 2
    snapshot = build_snapshot(evidence, personas, previous)
    if args.snapshot:
        sys.stdout.write(render_snapshot(snapshot))
        return 0
    if args.check:
        committed = args.snapshot_file.read_text() if args.snapshot_file.is_file() else ""
        fresh = render_snapshot(snapshot)
        if committed == fresh:
            print(f"{_rel(args.snapshot_file)} matches the evidence.")
            return 0
        sys.stdout.writelines(difflib.unified_diff(
            committed.splitlines(keepends=True), fresh.splitlines(keepends=True),
            f"a/{_rel(args.snapshot_file)}", f"b/{_rel(args.snapshot_file)}"))
        return 1
    plan = plan_for(evidence, personas, snapshot, args.min_runs)
    sys.stdout.write(render_plan(plan, personas, args.min_runs, args.evidence.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
