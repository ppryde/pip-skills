#!/usr/bin/env python3
"""Helpers for `run.sh --live` (stdlib only).

    live_helpers.py init-plugin <stream.jsonl> <plugin-name>
        print the path and version Claude Code loaded for that plugin (from the init event)
    live_helpers.py summarize <stream.jsonl> <scratch-dir> <out.txt>
        write the run's final text plus every report file the run wrote to <out.txt>;
        print one JSON line with turns, cost, tokens and bytes read from checks/ and references/
    live_helpers.py tally <log-dir> <expected-dir>
        per fixture and code, detections / runs over every run*.txt under <log-dir>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def events(path: Path):
    for line in path.read_text(errors="replace").splitlines():
        try:
            yield json.loads(line)
        except ValueError:
            continue


def init_plugin(stream: Path, name: str) -> int:
    for ev in events(stream):
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            for p in ev.get("plugins", []):
                if p.get("name") == name:
                    print(f"{p.get('path', '')}\t{p.get('version', '')}")
                    return 0
    return 1


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


def summarize(stream: Path, scratch: Path, out: Path) -> int:
    result = ""
    meta: dict = {"turns": 0, "cost_usd": None, "tokens_in": 0, "tokens_out": 0, "cache_read": 0}
    uses: dict[str, tuple[str, dict]] = {}
    read_checks = read_refs = bash_checks = opened = 0
    opened_spans: list[str] = []
    for ev in events(stream):
        t = ev.get("type")
        if t == "assistant":
            for c in ev.get("message", {}).get("content", []):
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    uses[c["id"]] = (c.get("name", ""), c.get("input", {}))
        elif t == "user":
            msg = ev.get("message", {})
            content = msg.get("content") if isinstance(msg, dict) else None
            for c in content if isinstance(content, list) else []:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    name, inp = uses.get(c.get("tool_use_id"), ("", {}))
                    size = len(_text(c.get("content")))
                    fp = str(inp.get("file_path", ""))
                    if name == "Read" and "/checks/" in fp and not fp.endswith("INDEX.md"):
                        read_checks += size
                        opened += 1
                        opened_spans.append(f"{Path(fp).name}:{inp.get('offset', 0)}+{inp.get('limit', 'all')}")
                    elif name == "Read" and "/references/" in fp:
                        read_refs += size
                    elif name == "Bash" and "/checks" in str(inp.get("command", "")):
                        bash_checks += size  # sed/cat/grep over the check files
        elif t == "result":
            result = ev.get("result", "") or ""
            meta["turns"] = ev.get("num_turns", 0)
            meta["cost_usd"] = ev.get("total_cost_usd")
            u = ev.get("usage", {}) or {}
            meta["tokens_in"] = u.get("input_tokens", 0)
            meta["tokens_out"] = u.get("output_tokens", 0)
            meta["cache_read"] = u.get("cache_read_input_tokens", 0)
    parts = [result]
    for rp in sorted(scratch.glob("reports/**/*.md")):
        parts.append(f"\n\n<<< report file {rp.relative_to(scratch)} >>>\n" + rp.read_text(errors="replace"))
    out.write_text("".join(parts))
    meta.update(read_checks_bytes=read_checks, bash_checks_bytes=bash_checks, read_refs_bytes=read_refs, checks_opened=opened,
                spans=opened_spans, result_chars=len(result))
    print(json.dumps(meta))
    return 0


def tally(logdir: Path, expected_dir: Path) -> int:
    rows = []
    for fx in sorted(p for p in logdir.iterdir() if p.is_dir()):
        runs = sorted(fx.glob("run*.txt"))
        if not runs:
            continue
        exp = expected_dir / fx.name / "expected.json"
        want = json.loads(exp.read_text()) if exp.exists() else []
        texts = [r.read_text(errors="replace") for r in runs]
        seen = []
        for f in want:
            if (f["id"], f.get("location_pattern")) in seen:
                continue
            seen.append((f["id"], f.get("location_pattern")))
            tier = f.get("tier_displayed", "")
            hits_code = sum(1 for t in texts if re.search(re.escape(f["id"]), t))
            hits_loc = sum(1 for t in texts if f["id"] in t and (f.get("location_pattern") or "") in t)
            rows.append((fx.name, f["id"], tier, f.get("location_pattern"), hits_code, hits_loc, len(texts)))
    for r in rows:
        print("\t".join(str(x) for x in r))
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "init-plugin":
        sys.exit(init_plugin(Path(sys.argv[2]), sys.argv[3]))
    if cmd == "summarize":
        sys.exit(summarize(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])))
    if cmd == "tally":
        sys.exit(tally(Path(sys.argv[2]), Path(sys.argv[3])))
    print(__doc__)
    sys.exit(2)
