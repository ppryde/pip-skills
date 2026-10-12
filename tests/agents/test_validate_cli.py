from __future__ import annotations

import json
import subprocess
import sys

from conftest import EXAMPLES, PLUGIN

SCRIPT = PLUGIN / "scripts" / "validate_result.py"


def run(*args, cwd=None):
    p = subprocess.run([sys.executable, "-I", str(SCRIPT), *map(str, args)], capture_output=True, text=True, cwd=cwd)
    return p.returncode, p.stdout, p.stderr


def test_cli_ok_invalid_usage(tmp_path):
    code, out, _ = run("--brief", EXAMPLES / "review.brief.txt", "--message", EXAMPLES / "review.result.md",
                       "--persona", "reviewer-scope", cwd=tmp_path)
    obj = json.loads(out)  # stdout is exactly one JSON object
    assert code == 0 and obj == {"ok": True, "kind": "review", "errors": []}

    code, out, _ = run("--brief", EXAMPLES / "review.brief.txt", "--message", EXAMPLES / "review.result.md",
                       "--persona", "reviewer-security", cwd=tmp_path)
    obj = json.loads(out)
    assert code == 1 and obj["ok"] is False and obj["errors"]

    code, out, _ = run("--brief", tmp_path / "missing.txt", "--message", EXAMPLES / "review.result.md",
                       "--persona", "reviewer-scope")
    assert code == 2 and json.loads(out)["ok"] is False

    code, _, err = run("--brief", EXAMPLES / "review.brief.txt")
    assert code == 2 and err

    code, _, _ = run("--brief-only", EXAMPLES / "review.brief.txt", "--persona", "x")
    assert code == 2


def test_brief_only(tmp_path):
    code, out, _ = run("--brief-only", EXAMPLES / "locate.brief.txt", cwd=tmp_path)
    assert code == 0 and json.loads(out) == {"ok": True, "kind": "locate", "errors": []}
    bad = tmp_path / "bad.txt"
    bad.write_text("brief: pip-agents/1\nkind: review\nsome pasted rule text\n")
    code, out, _ = run("--brief-only", bad)
    assert code == 1 and "not a brief line" in json.loads(out)["errors"][0]
    bad.write_text("brief: pip-agents/1\nkind: review\n")  # review needs target
    code, out, _ = run("--brief-only", bad)
    assert code == 1 and any("target" in e for e in json.loads(out)["errors"])


def test_runs_isolated(tmp_path):
    (tmp_path / "json.py").write_text("raise SystemExit('planted json module imported')\n")
    code, out, err = run("--brief-only", EXAMPLES / "run.brief.txt", cwd=tmp_path)
    assert code == 0, err
    assert json.loads(out)["ok"] is True
