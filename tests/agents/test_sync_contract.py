"""tools/sync_contract.py: consumers carry a byte-identical copy of the validator and contract (WF-270 PR E).

A consumer cannot reach a dependency plugin's files at run time, so it vendors them. These tests fail when a
committed copy drifts from plugins/pip-agents; the fix is `python3 tools/sync_contract.py`.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

import pytest

from conftest import EXAMPLES, PLUGIN, ROOT, load

SYNC = ROOT / "tools" / "sync_contract.py"


@pytest.fixture(scope="module")
def sc():
    return load("pip_agents_sync_contract", SYNC)


@pytest.fixture
def tree(tmp_path, sc):
    """A throwaway repo layout: the real pip-agents plugin plus empty consumer plugin folders."""
    root = tmp_path / "repo"
    shutil.copytree(PLUGIN, root / "plugins" / "pip-agents", ignore=shutil.ignore_patterns("__pycache__"))
    for c in sc.CONSUMERS:
        (root / "plugins" / c).mkdir(parents=True)
    return root


def run(*args):
    return subprocess.run([sys.executable, str(SYNC), *args], capture_output=True, text=True)


@pytest.mark.parametrize("consumer", ["review-panel", "review-clone"])
def test_committed_copy_has_no_drift(sc, consumer):
    assert sc.drift(ROOT, consumer) == []


def test_every_consumer_is_known_and_depends_on_pip_agents(sc):
    assert set(sc.CONSUMERS) == {"review-panel", "review-clone"}
    for c in sc.CONSUMERS:
        manifest = json.loads((ROOT / "plugins" / c / ".claude-plugin" / "plugin.json").read_text())
        assert "pip-agents" in manifest.get("dependencies", []), c


def test_check_cli_clean_on_the_repo():
    p = run("--check")
    assert p.returncode == 0, p.stdout + p.stderr


def test_sync_then_check_is_clean_and_idempotent(tree, sc):
    for c in sc.CONSUMERS:
        sc.sync(tree, c)
        assert sc.drift(tree, c) == []
    before = {p: p.read_bytes() for p in (tree / "plugins").rglob("*") if p.is_file()}
    for c in sc.CONSUMERS:
        sc.sync(tree, c)
    assert before == {p: p.read_bytes() for p in (tree / "plugins").rglob("*") if p.is_file()}


def test_manifest_records_revision_and_hashes(tree, sc):
    sc.sync(tree, "review-panel")
    dest = tree / "plugins" / "review-panel" / "vendor" / "pip-agents"
    m = json.loads((dest / "VENDORED.json").read_text())
    assert m["source"] == "plugins/pip-agents"
    assert m["revision"] == (PLUGIN / "contract" / "REVISION").read_text().strip()
    assert set(m["files"]) == set(sc.FILES)
    for rel, digest in m["files"].items():
        assert sc.sha256((dest / rel).read_bytes()) == digest


def test_drift_when_source_changes(tree, sc):
    sc.sync(tree, "review-clone")
    schema = tree / "plugins" / "pip-agents" / "contract" / "result.schema.json"
    schema.write_text(schema.read_text() + "\n")
    problems = sc.drift(tree, "review-clone")
    assert any("result.schema.json differs" in p for p in problems), problems
    assert any("VENDORED.json differs" in p for p in problems), problems  # the recorded hash moved too


def test_drift_when_copy_is_edited_or_removed_or_padded(tree, sc):
    sc.sync(tree, "review-panel")
    dest = tree / "plugins" / "review-panel" / "vendor" / "pip-agents"
    (dest / "scripts" / "validate_result.py").write_text("# edited\n")
    (dest / "contract" / "REVISION").unlink()
    (dest / "contract" / "stray.json").write_text("{}")
    problems = sc.drift(tree, "review-panel")
    assert any("validate_result.py differs" in p for p in problems)
    assert any("REVISION is missing" in p for p in problems)
    assert any("stray.json is not part of the bundle" in p for p in problems)
    sc.sync(tree, "review-panel")  # the fix
    assert sc.drift(tree, "review-panel") == []


def test_check_cli_reports_drift_and_writes_nothing(tree):
    p = run("--root", str(tree), "--check")
    assert p.returncode == 1 and "is missing" in p.stdout
    assert not (tree / "plugins" / "review-panel" / "vendor").exists()
    assert run("--root", str(tree)).returncode == 0
    assert run("--root", str(tree), "--check").returncode == 0


def test_missing_source_and_unknown_consumer_exit_2(tree):
    (tree / "plugins" / "pip-agents" / "contract" / "personas.json").unlink()
    p = run("--root", str(tree), "review-panel")
    assert p.returncode == 2 and "missing source file" in p.stderr
    p = run("--root", str(tree), "nope")
    assert p.returncode == 2


@pytest.mark.parametrize("consumer", ["review-panel", "review-clone"])
def test_vendored_validator_runs_standalone_and_accepts_the_examples(consumer):
    """The copy must work from its own location: it finds `../contract` next to itself."""
    dest = ROOT / "plugins" / consumer / "vendor" / "pip-agents"
    brief = EXAMPLES / "review.brief.txt"
    message = EXAMPLES / "review.result.md"
    p = subprocess.run(
        [sys.executable, "-I", str(dest / "scripts" / "validate_result.py"),
         "--brief", str(brief), "--message", str(message), "--persona", "reviewer-scope"],
        capture_output=True, text=True,
    )
    assert p.returncode == 0, p.stdout + p.stderr
    assert json.loads(p.stdout)["ok"] is True
