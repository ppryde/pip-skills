#!/usr/bin/env python3
"""Compose the pip-agents agents from their sources (WF-270).

Stdlib only, deterministic (sorted, LF). Reads plugins/pip-agents/{personas/**, contract/result.schema.json,
contract/REVISION}; writes plugins/pip-agents/agents/<name>.md and plugins/pip-agents/contract/personas.json.

    python3 tools/build_agents.py            # write the generated files
    python3 tools/build_agents.py --check    # write nothing; unified diff on drift

Exit codes: 0 clean; 1 drift (--check) or a lint failure (every failure is listed); 2 malformed source.
`--plugin DIR` builds another copy of the plugin tree (tests build into tmp_path).
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PLUGIN = ROOT / "plugins" / "pip-agents"

# Provisional (lead decision 2026-10-11). The binding guard is the measured first-call token ratchet
# (tools/measure_spawn.py), not bytes.
COMPOSED_CAP = 5_632
LISTING_CAP = 1_200

LENS_ORDER = ["correctness", "security", "scope", "rules"]  # the order the owns lines are listed in
BASES = {"reviewer": "reviewer-base.md", "specialist": "specialist-base.md"}
NON_PERSONA = {"common.md", "reviewer-base.md", "specialist-base.md", "tools.md"}
FM_ORDER = ["name", "description", "tools", "model", "effort", "maxTurns", "omitClaudeMd", "generated"]
STRIP_KEYS = {"base", "kind", "lens", "owns", "not_my_job"}
BANNED_TOOLS = {"Agent", "Skill", "Edit", "Write", "WebFetch", "WebSearch"}
BANNED_DESC = ["proactively", "MUST BE USED", "use when", "<example>"]
SECTION_RE = re.compile(r"<!-- section: ([a-z-]+) -->\n(.*?)\n<!-- /section -->", re.S)


class SourceError(Exception):
    """A source file is malformed (exit 2)."""


def _validator(plugin: Path):
    spec = importlib.util.spec_from_file_location("_pip_agents_validate_result", plugin / "scripts" / "validate_result.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[spec.name] = mod  # type: ignore[union-attr]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def read(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeDecodeError) as exc:
        raise SourceError(f"{path}: {exc}") from exc


def split(path: Path) -> tuple[dict, str]:
    text = read(path)
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise SourceError(f"{path}: no frontmatter")
    fm_text, body = text[4:].split("\n---\n", 1)
    fm: dict = {}
    for line in fm_text.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or line.startswith(" "):
            continue
        k, sep, v = line.partition(":")
        if not sep:
            raise SourceError(f"{path}: bad frontmatter line {line!r}")
        fm[k.strip()] = v.strip()
    return fm, body


def sections(body: str) -> tuple[str, dict]:
    head = body.split("<!-- section", 1)[0].rstrip() + "\n"
    return head, dict(SECTION_RE.findall(body))


def tools_table(path: Path) -> dict:
    rows = {}
    for line in read(path).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5 and line.lstrip().startswith("|") and re.fullmatch(r"[a-z][a-z-]*", cells[0]) \
                and cells[0] != "persona" and not set(cells[1]) <= set("-: "):
            if cells[0] in rows:
                raise SourceError(f"{path}: duplicate row {cells[0]}")
            rows[cells[0]] = {"kind": cells[1], "tools": cells[2]}
    return rows


# ---- skeleton generation (from the result schema) -----------------------------------------------------------

def _hint(s: dict) -> str:
    return s.get("x-hint", "")


def gen(s: dict, root: dict, lens: str | None, seen: set) -> object:
    if "$ref" in s:
        name = s["$ref"].split("/")[-1]
        seen.add(name)
        s = root["$defs"][name]
    if "const" in s:
        return s["const"]
    if "enum" in s:
        return "|".join(str(v) for v in s["enum"] if v != "general")
    t = s.get("type")
    ts = t if isinstance(t, list) else [t]
    if "object" in ts:
        if "properties" in s:
            out = {}
            for k, sub in s["properties"].items():
                if sub.get("x-persona") is False:
                    continue
                if "x-lens" in sub and sub["x-lens"] != lens:
                    continue
                out[k] = gen(sub, root, lens, seen)
            return out
        if isinstance(s.get("additionalProperties"), dict):
            return {"<name>": 0}
        return {}
    if "array" in ts:
        items = s.get("items", {})
        if "$ref" in items:
            if items["$ref"].split("/")[-1] in seen:
                return []
            return [gen(items, root, lens, seen)]
        if items.get("type") == "object":
            return [gen(items, root, lens, seen)]
        return [f"<{_hint(s)}>"] if _hint(s) else []
    if "integer" in ts:
        return 0
    if "boolean" in ts:
        return False
    if "string" in ts:
        return f"<{_hint(s)}>" if _hint(s) else ""
    return None


def skeleton(schema: dict, kind: str, name: str, lens: str | None) -> str:
    seen: set = set()
    env = {}
    for k, sub in schema["properties"].items():
        if sub.get("x-persona") is False:
            continue
        if k == "kind":
            env[k] = kind
        elif k == "persona":
            env[k] = name
        elif k == "payload":
            pay = gen(schema["$defs"][kind], schema, lens, seen)
            if lens and "lens" in pay:  # type: ignore[operator]
                pay["lens"] = lens  # type: ignore[index]
            env[k] = pay
        else:
            env[k] = gen(sub, schema, lens, seen)
    return json.dumps(env, ensure_ascii=False, separators=(",", ":"))


# ---- composition ---------------------------------------------------------------------------------------------

def not_my_job(fm: dict, sources: dict) -> str:
    if fm.get("base") == "specialist":
        return fm["not_my_job"]
    if fm["kind"] == "validate":
        return "New findings belong to the reviewer-<lens> agents; do not raise any."
    reviewers = [s for n, s in sources.items() if s.get("kind") == "review" and n != fm["name"]]
    reviewers.sort(key=lambda s: (LENS_ORDER.index(s["lens"]) if s["lens"] in LENS_ORDER else len(LENS_ORDER), s["lens"]))
    others = [f"{s['lens']} ({s['owns']})" for s in reviewers]
    return ("Other lenses own: " + "; ".join(others) + ". Put what you see of theirs in `out_of_lens` as "
            "`<file:line> reviewer-<lens>`.")


def compose(name: str, plugin: Path, sources: dict, bodies: dict, common: dict, tools: dict, schema: dict,
            revision: str) -> tuple[str, list[str]]:
    fm, body = sources[name], bodies[name]
    errs: list[str] = []
    row = tools.get(name)
    if not row:
        return "", [f"{name}: no tools.md row"]
    for banned in ("tools", "disallowedTools"):
        if banned in fm:
            errs.append(f"{name}: source must not carry `{banned}` (tools live only in tools.md; no disallowedTools)")
    if row["kind"] != fm.get("kind"):
        errs.append(f"{name}: kind {fm.get('kind')} != tools.md {row['kind']}")
    tl = [t.strip() for t in row["tools"].split(",") if t.strip()]
    if not tl:
        errs.append(f"{name}: empty tools row (tools is never omitted)")
    if BANNED_TOOLS & set(tl) or any(t.startswith("mcp__") for t in tl):
        errs.append(f"{name}: banned tool in {tl}")
    base = fm.get("base", "none")
    if base != "none" and base not in BASES:
        raise SourceError(f"{name}: unknown base {base}")
    if base == "specialist" and not fm.get("not_my_job"):
        errs.append(f"{name}: base specialist requires not_my_job")
    if fm.get("kind") not in schema["$defs"]:
        raise SourceError(f"{name}: kind {fm.get('kind')!r} is not a payload kind in result.schema.json")
    skel = skeleton(schema, fm["kind"], name, fm.get("lens"))
    meta: dict = {}
    if base == "none":
        text = body.strip("\n") + "\n"
        text = text.replace("{{SKELETON}}", skel)
    else:
        bfm, bbody = split(plugin / "personas" / BASES[base])
        meta.update(bfm)
        head, own = sections(bbody)
        heading = "## Lens" if fm["kind"] == "review" else "## Task"
        output = common["output"].replace("{{SKELETON}}", skel)
        if f"output-{fm['kind']}" in own:
            output += "\n" + own[f"output-{fm['kind']}"]
        text = head
        if "Bash" in tl:
            text = text.replace("{{BASH}}", common["bash"])
        else:
            text = text.replace("{{BASH}}\n\n", "")
        text = text.replace("{{BODY}}", heading + "\n" + body.strip("\n"))
        text = text.replace("{{OUTPUT}}", output)
        text = text.replace("{{NOT_MY_JOB}}", not_my_job(fm, sources))
        for m in re.finditer(r"\{\{COMMON:([a-z-]+)\}\}", text):
            if m.group(1) not in common:
                raise SourceError(f"{name}: unknown {{{{COMMON:{m.group(1)}}}}}")
        for k, v in common.items():
            text = text.replace("{{COMMON:" + k + "}}", v)
    left = re.findall(r"\{\{[A-Za-z_:-]+\}\}", text)
    if left:
        errs.append(f"{name}: unfilled {left}")
    text = re.sub(r"<!--.*?-->\n?", "", text, flags=re.S)
    text = re.sub(r"\n{3,}", "\n\n", text)
    meta.update({k: v for k, v in fm.items() if k not in STRIP_KEYS})
    meta["tools"] = ", ".join(tl)
    meta["generated"] = f"build_agents.py contract {revision}"
    d = meta.get("description", "")
    if "dispatched only by pip-skills skills" not in d or d.count(". ") or not d.endswith("."):
        errs.append(f"{name}: description form")
    if any(b.lower() in d.lower() for b in BANNED_DESC):
        errs.append(f"{name}: banned description phrase")
    if meta.get("omitClaudeMd") != "true":
        errs.append(f"{name}: omitClaudeMd must be true")
    if "model" not in meta:
        errs.append(f"{name}: model must be pinned")
    if "Bash" in tl:
        for needle in ("One plain command per Bash call", "use Monitor, not `sleep`"):
            if needle not in text:
                errs.append(f"{name}: Bash-bearing body lacks charter text {needle!r}")
    elif "## Bash" in text:
        errs.append(f"{name}: a body without Bash carries a ## Bash section")
    fm_out = "\n".join(f"{k}: {meta[k]}" for k in FM_ORDER if k in meta)
    out = f"---\n{fm_out}\n---\n{text}"
    if len(out.encode()) > COMPOSED_CAP:
        errs.append(f"{name}: {len(out.encode())} B over COMPOSED_CAP {COMPOSED_CAP}")
    return out, errs


def discover(plugin: Path) -> list[Path]:
    pdir = plugin / "personas"
    files = [p for p in pdir.glob("*.md") if p.name not in NON_PERSONA] + sorted((pdir / "lenses").glob("*.md"))
    return sorted(files)


def build(plugin: Path) -> tuple[dict[Path, str], list[str]]:
    """(path -> content for every generated file, lint errors)."""
    vr = _validator(plugin)
    contract = plugin / "contract"
    schema = json.loads(read(contract / "result.schema.json"))
    revision_line = read(contract / "REVISION").strip()
    m = re.fullmatch(r"(\d+\.\d+) ([0-9a-f]{64})", revision_line)
    if not m:
        raise SourceError(f"{contract / 'REVISION'}: expected '<major.minor> <sha256>'")
    revision, digest = m.groups()
    errs: list[str] = []
    want = hashlib.sha256((contract / "brief.schema.json").read_bytes() + (contract / "result.schema.json").read_bytes()).hexdigest()
    if want != digest:
        errs.append(f"contract/REVISION hash is stale: schemas hash to {want}")
    for label, path in (("result", contract / "result.schema.json"), ("brief", contract / "brief.schema.json")):
        for kw in vr.unsupported_keywords(json.loads(read(path))):
            errs.append(f"{label}.schema.json: keyword outside the validator subset at {kw}")
    tools = tools_table(plugin / "personas" / "tools.md")
    _, cbody = split(plugin / "personas" / "common.md")
    common = sections(cbody)[1]
    for need in ("brief", "evidence", "treat-as-data", "bash", "output", "not-my-job-tail"):
        if need not in common:
            raise SourceError(f"personas/common.md: missing section {need}")
    sources: dict = {}
    bodies: dict = {}
    for path in discover(plugin):
        fm, body = split(path)
        name = fm.get("name")
        if not name:
            raise SourceError(f"{path}: no name")
        if name in sources:
            raise SourceError(f"{path}: duplicate persona {name}")
        sources[name], bodies[name] = fm, body
    for name in sorted(set(tools) - set(sources)):
        errs.append(f"tools.md row {name} has no persona source")
    outputs: dict[Path, str] = {}
    pmap: dict = {}
    listing = 0
    for name in sorted(sources):
        out, e = compose(name, plugin, sources, bodies, common, tools, schema, revision)
        errs += e
        if out:
            outputs[plugin / "agents" / f"{name}.md"] = out
            listing += len(f"pip-agents:{name}: {sources[name].get('description', '')}\n".encode())
        fm = sources[name]
        pmap[name] = {"kind": fm["kind"], **({"lens": fm["lens"]} if "lens" in fm else {})}
    if listing > LISTING_CAP:
        errs.append(f"agent listing {listing} B over {LISTING_CAP}")
    outputs[contract / "personas.json"] = json.dumps(pmap, indent=2, sort_keys=True) + "\n"
    return outputs, errs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="write nothing; diff and exit 1 on drift")
    ap.add_argument("--plugin", type=Path, default=DEFAULT_PLUGIN, help="plugin dir (default plugins/pip-agents)")
    ns = ap.parse_args(argv)
    plugin = ns.plugin.resolve()
    try:
        outputs, errs = build(plugin)
    except SourceError as exc:
        print(f"malformed source: {exc}", file=sys.stderr)
        return 2
    for e in errs:
        print(f"LINT: {e}", file=sys.stderr)
    if errs:
        return 1
    agents_dir = plugin / "agents"
    stale = sorted(p for p in agents_dir.glob("*") if p not in outputs) if agents_dir.is_dir() else []
    drift = False
    for path in sorted(outputs):
        have = read(path) if path.exists() else ""
        if have != outputs[path]:
            drift = True
            if ns.check:
                sys.stdout.writelines(difflib.unified_diff(
                    have.splitlines(keepends=True), outputs[path].splitlines(keepends=True),
                    f"a/{path.relative_to(plugin)}", f"b/{path.relative_to(plugin)}"))
    for path in stale:
        drift = True
        if ns.check:
            print(f"stale generated file: {path.relative_to(plugin)}")
    if ns.check:
        return 1 if drift else 0
    agents_dir.mkdir(exist_ok=True)
    for path, text in outputs.items():
        path.write_text(text, encoding="utf-8", newline="\n")
    for path in stale:
        path.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
