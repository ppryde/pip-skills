"""census-mod is a standalone plugin: it ships its OWN copy of census's recording and reading code (plugin/scripts/),
byte-identical to plugins/census/scripts/, and never needs, calls or discovers the census plugin."""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "plugins" / "census" / "scripts"
MOD = REPO / "plugins" / "census-mod"
PLUGIN = MOD / "plugin"
BUNDLE = PLUGIN / "scripts"
# ingest, read, where (cli), what the store needs, vitals. Not install/render/statusline: the command status line is
# the census plugin's job.
FILES = ["__init__.py", "cli.py", "gitcache.py", "resolve.py", "store.py", "vitals.py", "where.py"]


def test_the_bundle_is_byte_identical_to_the_source():
    """If this fails the copies drifted: run plugins/census-mod/sync-bundle.sh."""
    drifted = [f for f in FILES if (BUNDLE / f).read_bytes() != (SOURCE / f).read_bytes()]
    assert not drifted, f"{drifted} differ from plugins/census/scripts; run plugins/census-mod/sync-bundle.sh"


def test_the_bundle_holds_exactly_those_files():
    assert sorted(p.name for p in BUNDLE.iterdir() if p.name != "__pycache__") == sorted(FILES)


def test_the_sync_script_copies_the_same_list():
    script = (MOD / "sync-bundle.sh").read_text()
    listed = re.search(r"^FILES=\((.*?)\)$", script, re.M).group(1).split()
    assert sorted(listed) == sorted(FILES)


def test_the_sync_script_makes_the_bundle_identical(tmp_path):
    work = tmp_path / "repo" / "plugins"
    shutil.copytree(REPO / "plugins" / "census" / "scripts", work / "census" / "scripts")
    (work / "census-mod").mkdir(parents=True)
    shutil.copy(MOD / "sync-bundle.sh", work / "census-mod" / "sync-bundle.sh")
    (work / "census-mod" / "plugin" / "scripts").mkdir(parents=True)
    (work / "census-mod" / "plugin" / "scripts" / "stale.py").write_text("old")
    subprocess.run(["bash", str(work / "census-mod" / "sync-bundle.sh")], check=True, capture_output=True)
    got = sorted(p.name for p in (work / "census-mod" / "plugin" / "scripts").iterdir())
    assert got == sorted(FILES)  # and the stale file was removed
    for f in FILES:
        assert (work / "census-mod" / "plugin" / "scripts" / f).read_bytes() == (SOURCE / f).read_bytes()


@pytest.fixture
def lone(tmp_path):
    """The bundle copied to an otherwise empty place: no census plugin anywhere near it."""
    root = tmp_path / "census-mod-plugin"
    shutil.copytree(BUNDLE, root / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    env = {
        k: v for k, v in os.environ.items() if not k.startswith(("CENSUS", "CLAUDE", "PYTHONPATH"))
    } | {
        "HOME": str(tmp_path / "home"),
        "CENSUS_STORE": str(tmp_path / "store"),
        "CLAUDE_CONFIG_DIR": str(tmp_path / "cfg"),
    }
    return root, env, tmp_path


def run_cli(root, env, *args, stdin=""):
    return subprocess.run(
        [sys.executable, str(root / "scripts" / "cli.py"), *args], input=stdin, capture_output=True, text=True, env=env,
        cwd=str(root.parent), timeout=60,
    )


PAYLOAD = {
    "session_id": "s1",
    "cwd": "/tmp",
    "model": {"id": "claude-opus-5-5", "display_name": "Opus 5.5"},
    "context_window": {"used_percentage": 9, "context_window_size": 1000000},
    "cost": {"total_cost_usd": 0.9},
    "census_mod": {"version": 1, "pid": 4242, "event": "session.start"},
}


def test_the_bundle_records_and_reads_with_no_census_plugin_anywhere(lone):
    root, env, tmp = lone
    done = run_cli(root, env, "ingest", stdin=json.dumps(PAYLOAD))
    assert done.returncode == 0, done.stderr
    assert (tmp / "store" / "sessions" / "s1.json").is_file()
    read = run_cli(root, env, "read", "--session", "s1")
    assert read.returncode == 0 and json.loads(read.stdout)["payload"]["model"]["display_name"] == "Opus 5.5"


def test_ingest_publishes_the_bundled_cli_as_cli_path_so_other_tools_find_a_census(lone):
    root, env, tmp = lone
    run_cli(root, env, "ingest", stdin=json.dumps(PAYLOAD))
    pointer = (tmp / "store" / "cli.path").read_text().strip()
    assert Path(pointer) == (root / "scripts" / "cli.py").resolve()


def test_where_and_vitals_work_from_the_bundle(lone):
    root, env, tmp = lone
    run_cli(root, env, "ingest", stdin=json.dumps(PAYLOAD))
    where = run_cli(root, env, "where")
    assert where.returncode == 0 and json.loads(where.stdout)["vitals"] is True
    vitals = subprocess.run(
        [sys.executable, str(root / "scripts" / "vitals.py"), "lean", "--session", "s1", "--cwd", str(tmp)],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert vitals.returncode == 0 and "Opus 5.5" in vitals.stdout and "⚡ 9%" in vitals.stdout


@pytest.mark.parametrize("command", [["statusline", "--preview"], ["install"], ["uninstall"], ["install-statusline"]])
def test_the_bundle_declines_the_commands_that_belong_to_the_census_plugin(lone, command):
    root, env, _ = lone
    done = run_cli(root, env, *command)
    assert done.returncode == 1 and "not part of this bundle" in done.stderr
    assert "Traceback" not in done.stderr


def test_census_mod_ships_the_vitals_command_and_skills():
    command = (PLUGIN / "commands" / "vitals.md").read_text()
    assert "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py" in command and "/census-mod:vitals" in command
    for skill in ("vitals-lean", "vitals-detailed"):
        text = (PLUGIN / "skills" / skill / "SKILL.md").read_text()
        assert f"name: {skill}" in text and "${CLAUDE_PLUGIN_ROOT}/scripts/vitals.py" in text
        assert f"/census-mod:{skill}" in text
    assert not (PLUGIN / "skills" / "vitals-playful").exists()


def test_no_vitals_shell_line_in_census_mod_splices_arguments():
    for f in [PLUGIN / "commands" / "vitals.md", *sorted((PLUGIN / "skills").glob("vitals-*/SKILL.md"))]:
        for line in f.read_text().splitlines():
            if line.startswith("!") or line.lstrip().startswith(("python3 ", "python ")):
                assert "ARGUMENTS" not in line, f"{f.name}: {line}"


def test_census_mod_never_mentions_the_census_plugin_as_a_dependency():
    """No sibling discovery, no cli.path lookup, no CENSUS_CLI, no `census` on PATH, no version floor."""
    code = {f: f.read_text() for f in [*(PLUGIN / "core").glob("*.ts"), PLUGIN / "hooks" / "register.tsx"]}
    for gone in ("findSibling", "siblingCli", "pointerFiles", "CENSUS_CLI", "command -v census", "WHICH_ARGV", "MIN_CENSUS", "ancestors("):
        hits = [f.name for f, text in code.items() if gone in text]
        assert not hits, f"{gone} is still in {hits}"
