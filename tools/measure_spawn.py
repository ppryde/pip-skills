#!/usr/bin/env python3
"""Measure what dispatching a pip-agents persona costs (WF-270). Run by hand; never from CI or the test suite.

Stdlib only. Two commands:

    python3 tools/measure_spawn.py report SESSION_DIR [--persona NAME]
        Read the subagent transcripts under SESSION_DIR (a `<session-id>` folder holding `subagents/*.jsonl`)
        and print, per subagent, its first-call input tokens, turns, tools used and attachment bytes.

    python3 tools/measure_spawn.py run --plugin-dir plugins/pip-agents --persona reviewer-scope \
            [--config-dir ~/.claude-personal] [--model haiku] [--ask-tools]
        Copy the plugin to a temp dir (a --plugin-dir under .claude/worktrees silently loads the installed
        version), start `claude -p` there with a throwaway brief, ask it to dispatch the persona once, then
        `report` on the transcripts. Costs a few cents of the account in --config-dir (default
        $CLAUDE_CONFIG_DIR); it never touches the repo.

First-call input tokens = input + cache creation + cache read of the subagent's first assistant message: the
fixed cost of the spawn (system prompt, tool schemas, agent body, brief). The ratchet: PR B onwards may not raise
any persona's first call by more than 5 % without saying why.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def report_subagent(jsonl: Path) -> dict:
    meta = jsonl.with_suffix(".meta.json")
    agent_type = json.loads(meta.read_text()).get("agentType", "?") if meta.exists() else "?"
    first = None
    turns = 0
    tools: dict[str, int] = {}
    attachments: dict[str, int] = {}
    for line in jsonl.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("type") == "attachment":
            a = r.get("attachment", {})
            t = a.get("type", "?")
            attachments[t] = attachments.get(t, 0) + len(json.dumps(a))
        if r.get("type") == "assistant":
            turns += 1
            if first is None:
                u = r["message"]["usage"]
                first = u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
            for block in r["message"].get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tools[block["name"]] = tools.get(block["name"], 0) + 1
    return {"agent": agent_type, "first_call_input_tokens": first, "turns": turns, "tools": tools,
            "attachment_bytes": attachments, "file": str(jsonl)}


def report(session_dir: Path, persona: str | None) -> list[dict]:
    rows = [report_subagent(p) for p in sorted(session_dir.glob("**/subagents/*.jsonl"))]
    return [r for r in rows if persona is None or r["agent"].endswith(persona)]


def run(plugin_dir: Path, persona: str, config_dir: Path | None, model: str | None, ask_tools: bool = False) -> int:
    claude = shutil.which("claude")
    if not claude:
        print("claude not on PATH", file=sys.stderr)
        return 2
    work = Path(tempfile.mkdtemp(prefix="measure-spawn-"))
    plugin = work / "plugin"
    shutil.copytree(plugin_dir, plugin, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    project = work / "project"
    project.mkdir()
    (project / "target.py").write_text("def add(a, b):\n    return a - b\n")
    (project / "diff.patch").write_text("--- a/target.py\n+++ b/target.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a + b\n+    return a - b\n")
    (project / "claims.json").write_text('[{"id": "c1", "claim": "add subtracts", "where": "target.py:2"}]')
    (project / "scope.txt").write_text(str(project / "target.py") + "\n")
    head = "brief: pip-agents/1\nkind: {kind}\nref: probe\n"
    briefs = {
        "review": head + f"target: {project / 'diff.patch'}\n",
        "validate": head + f"claims: {project / 'claims.json'}\ntarget: {project / 'diff.patch'}\n",
        "locate": head + f"question: where is add defined\ntarget: {project / 'scope.txt'}\nnames: add\n",
        "run": head + "run: echo hello\n",
    }
    kind = {"validator": "validate", "explorer": "locate", "gatekeeper": "run"}.get(persona, "review")
    brief = briefs[kind].format(kind=kind)
    if ask_tools:  # probe which tools resolve in the agent: its prompt is replaced by a question
        brief = "List the exact name of every tool you can call, one per line, then stop. Do not call any."
    prompt = (f"Dispatch the agent pip-agents:{persona} exactly once with the Agent tool. Its prompt is exactly these "
              f"lines and nothing else:\n{brief}\nWhen it returns, print its final message verbatim, then the word done.")
    env = dict(os.environ, CLAUDE_NO_TMUX="1")
    if config_dir is not None:
        env["CLAUDE_CONFIG_DIR"] = str(config_dir.expanduser())
    cmd = [claude, "-p", "--plugin-dir", str(plugin), "--output-format", "json", "--permission-mode", "bypassPermissions"]
    if model:
        cmd += ["--model", model]
    cmd.append(prompt)
    proc = subprocess.run(cmd, cwd=project, env=env, capture_output=True, text=True, timeout=600)
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        print(proc.stdout[-500:], proc.stderr[-500:], file=sys.stderr)
        return 1
    cfg = Path(env.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    found = list(cfg.glob(f"projects/*/{out['session_id']}"))
    rows = report(found[0], persona) if found else []
    print(json.dumps({"session_id": out["session_id"], "cost_usd": out.get("total_cost_usd"), "subagents": rows,
                      "reply": out.get("result", "")[:1500] if ask_tools else None}, indent=2))
    shutil.rmtree(work, ignore_errors=True)
    return 0 if rows else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("report")
    rp.add_argument("session_dir", type=Path)
    rp.add_argument("--persona")
    rn = sub.add_parser("run")
    rn.add_argument("--plugin-dir", type=Path, required=True)
    rn.add_argument("--persona", required=True)
    rn.add_argument("--config-dir", type=Path)
    rn.add_argument("--model", help="model of the dispatching main session (the persona pins its own)")
    rn.add_argument("--ask-tools", action="store_true", help="replace the brief with a request to list the agent's tools")
    ns = ap.parse_args(argv)
    if ns.cmd == "report":
        print(json.dumps(report(ns.session_dir, ns.persona), indent=2))
        return 0
    return run(ns.plugin_dir, ns.persona, ns.config_dir, ns.model, ns.ask_tools)


if __name__ == "__main__":
    sys.exit(main())
