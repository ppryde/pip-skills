from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys

import pytest

from conftest import CONTRACT, PLUGIN, ROOT

AGENTS = PLUGIN / "agents"
NAMES = ["explorer", "gatekeeper", "reviewer-correctness", "reviewer-rules", "reviewer-scope", "reviewer-security", "validator"]
LENSES = {"reviewer-correctness": "correctness", "reviewer-security": "security", "reviewer-scope": "scope", "reviewer-rules": "rules"}
BANNED_TOOLS = {"Agent", "Skill", "Edit", "Write", "WebFetch", "WebSearch"}


def split(path):
    text = path.read_text()
    fm_text, body = text[4:].split("\n---\n", 1)
    return dict(line.split(": ", 1) for line in fm_text.splitlines()), body


def tools_rows(ba):
    return ba.tools_table(PLUGIN / "personas" / "tools.md")


def build_cli(*args):
    return subprocess.run([sys.executable, str(ROOT / "tools" / "build_agents.py"), *args], capture_output=True, text=True)


def test_build_check_clean():
    p = build_cli("--check")
    assert p.returncode == 0, p.stdout + p.stderr


def test_agents_set():
    assert sorted(p.stem for p in AGENTS.glob("*")) == NAMES
    assert all(p.suffix == ".md" for p in AGENTS.glob("*"))


def test_size_cap(ba):
    assert ba.COMPOSED_CAP == 5_632
    for n in NAMES:
        assert (AGENTS / f"{n}.md").stat().st_size <= ba.COMPOSED_CAP, n


def test_frontmatter(ba):
    rev = (CONTRACT / "REVISION").read_text().split()[0]
    rows = tools_rows(ba)
    for n in NAMES:
        fm, _ = split(AGENTS / f"{n}.md")
        keys = list(fm)
        order = [k for k in ba.FM_ORDER if k in fm]
        assert keys == order, n
        assert fm["name"] == n
        assert fm["tools"] == rows[n]["tools"], n
        assert not BANNED_TOOLS & set(fm["tools"].split(", ")) and "mcp__" not in fm["tools"], n
        assert fm["omitClaudeMd"] == "true" and fm["model"] in {"sonnet", "haiku"}, n
        assert "disallowedTools" not in fm, n
        assert fm["generated"] == f"build_agents.py contract {rev}", n
    assert split(AGENTS / "gatekeeper.md")[0]["maxTurns"] == "4"


def test_descriptions(ba):
    total = 0
    for n in NAMES:
        d = split(AGENTS / f"{n}.md")[0]["description"]
        assert d.endswith(".") and ". " not in d and "dispatched only by pip-skills skills" in d, n
        assert not any(b.lower() in d.lower() for b in ba.BANNED_DESC), n
        total += len(f"pip-agents:{n}: {d}\n".encode())
    assert total <= 1_200, total


def _skeleton_of(body):
    m = re.search(r"^(\{\"result\".*)$", body, re.M)
    assert m, "no skeleton line"
    return m.group(1)


def test_skeletons(ba):
    schema = json.loads((CONTRACT / "result.schema.json").read_text())
    pmap = json.loads((CONTRACT / "personas.json").read_text())
    for n in NAMES:
        _, body = split(AGENTS / f"{n}.md")
        want = ba.skeleton(schema, pmap[n]["kind"], n, pmap[n].get("lens"))
        assert _skeleton_of(body) == want, n
        obj = json.loads(want)
        assert "detail" not in obj, n
        pay = obj["payload"]
        for banned in ("counts", "outcome"):
            if pmap[n]["kind"] == "review":
                assert banned not in pay, (n, banned)
        if pmap[n]["kind"] == "review":
            others = {"trigger", "commands_run", "old", "new", "intent", "affected", "rules_checked", "n_a", "rule", "citation"}
            own = {
                "correctness": {"trigger", "commands_run"},
                "scope": {"old", "new", "intent", "affected"},
                "rules": {"rules_checked", "n_a", "rule", "citation"},
                "security": set(),
            }[pmap[n]["lens"]]
            seen = set(pay) | set(pay["findings"][0])
            assert (seen & others) == own, n


def test_charter_text():
    for n in NAMES:
        _, body = split(AGENTS / f"{n}.md")
        tools = split(AGENTS / f"{n}.md")[0]["tools"]
        if "Bash" in tools:
            assert "One plain command per Bash call" in body, n
            assert "use Monitor, not `sleep`" in body, n
        else:
            assert "## Bash" not in body and "Bash call" not in body, n


def test_not_my_job(ba):
    lens_names = [n for n in LENSES]
    for n in lens_names:
        _, body = split(AGENTS / f"{n}.md")
        section = body.split("## Not your job\n", 1)[1]
        for other in lens_names:
            if other == n:
                assert f"{LENSES[other]} (" not in section, n
                continue
            src = (PLUGIN / "personas" / "lenses" / f"{LENSES[other]}.md").read_text()
            owns = re.search(r"^owns: (.*)$", src, re.M).group(1)
            assert f"{LENSES[other]} ({owns})" in section, (n, other)
    _, body = split(AGENTS / "validator.md")
    assert "reviewer-<lens>" in body.split("## Not your job\n", 1)[1]
    _, body = split(AGENTS / "explorer.md")
    assert "Judging, ranking or explaining" in body.split("## Not your job\n", 1)[1]


def test_sources_outside_agents(ba):
    rows = tools_rows(ba)
    assert sorted(rows) == NAMES
    sources = {p.stem for p in (PLUGIN / "personas").glob("*.md")} - {"common", "reviewer-base", "specialist-base", "tools"}
    sources |= {f"reviewer-{p.stem}" for p in (PLUGIN / "personas" / "lenses").glob("*.md")}
    assert sources == set(NAMES)
    for p in AGENTS.glob("*.md"):
        assert "generated:" in p.read_text().split("\n---\n", 1)[0], p
        assert "{{" not in p.read_text()
    assert not [p for p in AGENTS.rglob("*") if p.is_dir()], "a subfolder of agents/ would load as agents"


def test_personas_json(ba):
    pmap = json.loads((CONTRACT / "personas.json").read_text())
    rows = tools_rows(ba)
    assert sorted(pmap) == NAMES
    for n, meta in pmap.items():
        assert meta["kind"] == rows[n]["kind"], n
        assert meta.get("lens") == LENSES.get(n), n


# ---- the build tool itself, on a copy of the plugin -------------------------------------------------------

def copy_plugin(tmp_path):
    dst = tmp_path / "pip-agents"
    shutil.copytree(PLUGIN, dst, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    return dst


def test_build_writes_identical_files(tmp_path):
    dst = copy_plugin(tmp_path)
    shutil.rmtree(dst / "agents")
    (dst / "contract" / "personas.json").unlink()
    assert build_cli("--plugin", str(dst)).returncode == 0
    for n in NAMES:
        assert (dst / "agents" / f"{n}.md").read_bytes() == (AGENTS / f"{n}.md").read_bytes()
    assert (dst / "contract" / "personas.json").read_bytes() == (CONTRACT / "personas.json").read_bytes()


def test_check_reports_drift(tmp_path):
    dst = copy_plugin(tmp_path)
    (dst / "agents" / "validator.md").write_text("edited\n")
    (dst / "agents" / "stray.md").write_text("x\n")
    p = build_cli("--check", "--plugin", str(dst))
    assert p.returncode == 1 and "validator.md" in p.stdout and "stray.md" in p.stdout
    assert (dst / "agents" / "validator.md").read_text() == "edited\n", "--check writes nothing"


def test_malformed_source_exits_2(tmp_path):
    dst = copy_plugin(tmp_path)
    (dst / "personas" / "explorer.md").write_text("no frontmatter here\n")
    p = build_cli("--check", "--plugin", str(dst))
    assert p.returncode == 2 and "malformed source" in p.stderr


@pytest.mark.parametrize("edit, needle", [
    (lambda t: t.replace("Read, Grep, Glob", "Read, Grep, Write", 1), "banned tool"),
    (lambda t: t.replace("| locate |", "| review |", 1), "kind"),
])
def test_lint_failures_listed(tmp_path, edit, needle):
    dst = copy_plugin(tmp_path)
    tools = dst / "personas" / "tools.md"
    tools.write_text(edit(tools.read_text()))
    p = build_cli("--check", "--plugin", str(dst))
    assert p.returncode == 1 and needle in p.stderr, p.stderr


def test_lint_description_and_cap(tmp_path):
    dst = copy_plugin(tmp_path)
    src = dst / "personas" / "explorer.md"
    src.write_text(src.read_text().replace("dispatched only by pip-skills skills", "use when you need to search"))
    big = dst / "personas" / "lenses" / "scope.md"
    big.write_text(big.read_text() + "\n" + "padding line to blow the cap. " * 400)
    p = build_cli("--check", "--plugin", str(dst))
    assert p.returncode == 1
    assert "description form" in p.stderr and "banned description phrase" in p.stderr and "over COMPOSED_CAP" in p.stderr


def test_lint_specialist_needs_not_my_job(tmp_path):
    dst = copy_plugin(tmp_path)
    src = dst / "personas" / "explorer.md"
    src.write_text(re.sub(r"^not_my_job:.*\n", "", src.read_text(), flags=re.M))
    p = build_cli("--check", "--plugin", str(dst))
    assert p.returncode in (1, 2) and "not_my_job" in (p.stderr)


def test_stale_revision_hash_fails(tmp_path):
    dst = copy_plugin(tmp_path)
    schema = dst / "contract" / "result.schema.json"
    schema.write_text(schema.read_text().replace("pip-agents result envelope", "pip-agents result envelope!"))
    p = build_cli("--check", "--plugin", str(dst))
    assert p.returncode == 1 and "REVISION hash is stale" in p.stderr
