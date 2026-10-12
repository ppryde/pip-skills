"""prreview.py runs as a standalone script: imports nothing from `scripts`."""
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "plugins/review-panel/scripts/prreview.py"


def run(tmp_path, *args):
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path),
           "CLAUDE_CONFIG_DIR": str(tmp_path / "cfg")}
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], cwd=tmp_path,
                          capture_output=True, text=True, env=env, timeout=30)


def test_runs_isolated_from_an_empty_dir_and_refuses_without_confirmed(tmp_path):
    p = tmp_path / "plan.json"
    p.write_text("{}")
    r = run(tmp_path, "post", "--plan", str(p))
    assert r.returncode == 2
    assert json.loads(r.stdout)["status"] == "error"
    assert "Traceback" not in r.stderr


def test_imports_nothing_from_plugin_packages():
    src = SCRIPT.read_text()
    assert "from scripts" not in src and "import scripts" not in src
