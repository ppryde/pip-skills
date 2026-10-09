"""census-mod's pyrun.sh picks python3, python or py -3, and never leaks a failed attempt into the output."""
import os
import stat
import subprocess
from pathlib import Path

import pytest

SH = Path(__file__).resolve().parents[2] / "plugins" / "census-mod" / "plugin" / "bin" / "pyrun.sh"


def _stub(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _run(tmp_path, stubs: dict[str, str]):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in stubs.items():
        _stub(bin_dir, name, body)
    # only the stubs, plus the few tools the script itself needs
    for tool in ("sh", "dirname"):
        real = next((Path(p) / tool for p in os.environ["PATH"].split(os.pathsep) if (Path(p) / tool).exists()), None)
        if real:
            (bin_dir / tool).symlink_to(real)
    script = tmp_path / "hello.py"
    script.write_text("")
    return subprocess.run(
        ["/bin/sh", str(SH), str(script), "--x"], env={"PATH": str(bin_dir)}, capture_output=True, text=True,
    )


WORKS = 'case "$1" in -c) exit 0;; esac\necho "ran $0 $2"\n'
BROKEN = "exit 9\n"


def test_python3_first(tmp_path):
    r = _run(tmp_path, {"python3": WORKS, "python": WORKS})
    assert r.returncode == 0 and r.stdout.startswith("ran") and r.stderr == ""


def test_a_python3_that_fails_is_skipped_silently(tmp_path):
    r = _run(tmp_path, {"python3": BROKEN, "python": WORKS})
    assert r.returncode == 0 and "ran" in r.stdout and r.stderr == ""


def test_only_the_windows_launcher(tmp_path):
    r = _run(tmp_path, {"py": 'case "$2" in -c) exit 0;; esac\necho "py $1"\n'})
    assert r.returncode == 0 and r.stdout.strip() == "py -3" and r.stderr == ""


def test_none_found_says_so_once_on_stderr(tmp_path):
    r = _run(tmp_path, {})
    assert r.returncode == 127 and r.stdout == "" and r.stderr.count("no Python found") == 1


@pytest.mark.parametrize("md", ["commands/vitals.md", "skills/vitals-lean/SKILL.md", "skills/vitals-detailed/SKILL.md"])
def test_the_vitals_files_go_through_pyrun(md):
    text = (SH.parents[1] / md).read_text(encoding="utf-8")
    bang = next(line for line in text.splitlines() if line.startswith("!`"))
    assert bang.startswith('!`sh "${CLAUDE_PLUGIN_ROOT}/bin/pyrun.sh" ') and "|| " not in bang
    assert "Bash(sh:*)" in text
