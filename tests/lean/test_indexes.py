"""Generated INDEX files: generator behaviour, and drift once an index is enforced (WF-268)."""
import importlib.util
import re
import shutil
import subprocess
import sys

import pytest

from lean_common import REPO, load_budgets

GEN = REPO / "tools" / "build_index.py"
spec = importlib.util.spec_from_file_location("build_index", GEN)
bi = importlib.util.module_from_spec(spec)
sys.modules["build_index"] = bi
spec.loader.exec_module(bi)

SOURCES = {"optimise-orm": bi.OPTIMISE_ORM_CHECKS, "doctrines": bi.DOCTRINES_DIR}


def run(*args):
    return subprocess.run([sys.executable, str(GEN), *args], capture_output=True, text=True)


@pytest.fixture
def root(tmp_path):
    """A scratch repo root holding copies of the generator's sources."""
    for rel in SOURCES.values():
        shutil.copytree(REPO / rel, tmp_path / rel)
    return tmp_path


@pytest.mark.parametrize("name", sorted(SOURCES))
def test_generate_is_deterministic_lf_and_check_passes(root, name):
    assert run(name, "--root", str(root)).returncode == 0
    target = root / SOURCES[name] / "INDEX.md"
    first = target.read_bytes()
    assert b"\r" not in first and first.endswith(b"\n")
    assert run(name, "--root", str(root)).returncode == 0
    assert target.read_bytes() == first
    assert run(name, "--check", "--root", str(root)).returncode == 0


@pytest.mark.parametrize("name", sorted(SOURCES))
def test_check_normalises_crlf(root, name):
    run(name, "--root", str(root))
    target = root / SOURCES[name] / "INDEX.md"
    target.write_bytes(target.read_bytes().replace(b"\n", b"\r\n"))
    assert run(name, "--check", "--root", str(root)).returncode == 0


def test_check_prints_unified_diff_on_drift(root):
    run("optimise-orm", "--root", str(root))
    target = root / SOURCES["optimise-orm"] / "INDEX.md"
    target.write_text(target.read_text().replace("AGG-001", "AGG-9XX"))
    r = run("optimise-orm", "--check", "--root", str(root))
    assert r.returncode == 1
    assert "--- " in r.stdout and "+++ " in r.stdout and "AGG-9XX" in r.stdout


def test_check_fails_when_a_group_file_changes_without_regenerating(root):
    run("optimise-orm", "--root", str(root))
    group = root / SOURCES["optimise-orm"] / "aggregation.md"
    text = group.read_text()
    group.write_text(text.replace("### AGG-001", "\n\n### AGG-001", 1))  # shifts every later span
    assert run("optimise-orm", "--check", "--root", str(root)).returncode == 1


def test_spans_match_headings_and_cover_read_window(root):
    """Each span starts on its `### CODE` heading and ends right before the next heading or EOF."""
    run("optimise-orm", "--root", str(root))
    cdir = root / SOURCES["optimise-orm"]
    rows = re.findall(r"^\| ([A-Z]+-\d+) \|.*\| (\w+\.md) L(\d+)-(\d+) \|$",
                      (cdir / "INDEX.md").read_text(), re.M)
    assert len(rows) >= 72
    assert [r[0] for r in rows] == [r[0] for r in sorted(rows, key=lambda r: (r[1], r[0]))]
    for code, fname, a, b in rows:
        lines = (cdir / fname).read_text().split("\n")
        a, b = int(a), int(b)
        assert lines[a - 1].startswith(f"### {code}")  # offset=a, 1-based
        assert a <= b <= len(lines)
        body = lines[:-1] if lines[-1] == "" else lines
        nxt = next((ln for ln, _, _ in bi.headings(body) if ln > a), None)
        assert b == (nxt - 1 if nxt else len(body))  # limit = b - a + 1
        assert not any(re.match(r"### [A-Z]+-\d+", l) for l in lines[a:b])


def test_header_states_the_read_mapping(root):
    run("optimise-orm", "--root", str(root))
    text = (root / SOURCES["optimise-orm"] / "INDEX.md").read_text()
    assert "offset=<start>, limit=<end>-<start>+1" in text and "1-based" in text


def test_doctrine_audit_span_is_applicable_dirs_to_allowed_exceptions(root):
    run("doctrines", "--root", str(root))
    ddir = root / SOURCES["doctrines"]
    text = (ddir / "INDEX.md").read_text()
    found = re.findall(r"^## (\S+)\n(?:.*\n)*?- audit: L(\d+)-(\d+)$", text, re.M)
    assert len(found) == 13
    for name, a, b in found:
        lines = (ddir / f"{name}.md").read_text().split("\n")
        assert lines[int(a) - 1] == "## Applicable Directories"
        assert lines[int(b)] == "## Cross-Reference"


def test_malformed_source_exits_2(root):
    group = root / SOURCES["optimise-orm"] / "aggregation.md"
    group.write_text(group.read_text().replace("### AGG-001", "### AGG-0010", 1))
    assert run("optimise-orm", "--root", str(root)).returncode == 2


@pytest.mark.parametrize("name", sorted(SOURCES))
def test_committed_index_is_current_once_enforced(name):
    cfg = load_budgets()["indexes"][name]
    if not cfg["enforced"]:
        pytest.skip(cfg["reason"])
    r = run(name, "--check")
    assert r.returncode == 0, r.stdout + r.stderr


def _heading_texts(text):
    return [t for _, _, t in bi.headings(text.split("\n"))]


def test_nested_longer_fence_hides_inner_fence_and_heading():
    text = "## A\n````md\n```\n### H\n```\n### Still inside\n````\n### B\n"
    assert _heading_texts(text) == ["A", "B"]


def test_info_string_line_inside_open_fence_does_not_close_it():
    text = "## A\n```\n```python\n### inside\n```\n### B\n"
    assert _heading_texts(text) == ["A", "B"]


def test_tilde_inside_backtick_fence_does_not_toggle():
    text = "```\n~~~\n### inside\n```\n### B\n"
    assert _heading_texts(text) == ["B"]


GROUP = ("---\nname: g\ntitle: G\nchecks:\n  - id: G-001\n    title: One\n    severity_base: high\n"
         "  - id: G-002\n    title: Two\n    severity_base: low\n---\n# G\n\n### G-001\n{body}\n### G-002\nlast\n")


def _scratch(tmp_path, raw: str):
    cdir = tmp_path / SOURCES["optimise-orm"]
    cdir.mkdir(parents=True)
    (cdir / "g.md").write_bytes(raw.encode())
    return tmp_path


@pytest.mark.parametrize("variant", ["lf", "crlf", "no_trailing_newline", "fenced_heading"])
def test_exact_spans(tmp_path, variant):
    body = "text\n```\n### G-001\n```\nmore" if variant == "fenced_heading" else "text"
    raw = GROUP.format(body=body)
    g1 = raw.split("\n").index("### G-001") + 1
    g2 = raw.split("\n").index("### G-002") + 1
    if variant == "crlf":
        raw = raw.replace("\n", "\r\n")
    if variant == "no_trailing_newline":
        raw = raw.rstrip("\n")
    root = _scratch(tmp_path, raw)
    assert run("optimise-orm", "--root", str(root)).returncode == 0
    text = (root / SOURCES["optimise-orm"] / "INDEX.md").read_text()
    spans = {c: (int(a), int(b)) for c, a, b in re.findall(r"^\| (G-\d+) \|.*g\.md L(\d+)-(\d+) \|$", text, re.M)}
    assert spans == {"G-001": (g1, g2 - 1), "G-002": (g2, g2 + 1)}


def test_folded_scalar_in_frontmatter_is_rejected(tmp_path):
    raw = GROUP.format(body="x").replace("title: One", "title: >\n      folded")
    r = run("optimise-orm", "--root", str(_scratch(tmp_path, raw)))
    assert r.returncode == 2 and "folded" in r.stderr


def test_backtick_opener_with_backtick_in_info_string_is_not_a_fence():
    assert _heading_texts("## A\n``` python extra`\n### H\n") == ["A", "H"]
    assert _heading_texts("## A\n```x``` text\n### H\n") == ["A", "H"]
    assert _heading_texts("## A\n~~~ a`b\n### H\n~~~\n### B\n") == ["A", "B"]


def test_empty_value_with_indented_continuation_is_rejected(tmp_path):
    raw = GROUP.format(body="x").replace("title: One", "title:\n      continued")
    r = run("optimise-orm", "--root", str(_scratch(tmp_path, raw)))
    assert r.returncode == 2 and "multi-line" in r.stderr


def test_trailing_comment_stripped_from_unquoted_values(tmp_path):
    raw = GROUP.format(body="x").replace("title: One", "title: One # note").replace("title: Two", 'title: "Two # kept"')
    root = _scratch(tmp_path, raw)
    assert run("optimise-orm", "--root", str(root)).returncode == 0
    text = (root / SOURCES["optimise-orm"] / "INDEX.md").read_text()
    assert "| One |" in text and "Two # kept" in text and "note" not in text
