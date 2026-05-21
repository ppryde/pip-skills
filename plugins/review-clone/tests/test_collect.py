import subprocess
import sys


def test_collect_cli_help():
    """`python scripts/collect.py --help` exits 0 and shows known args."""
    result = subprocess.run(
        [sys.executable, "scripts/collect.py", "--help"],
        capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "--alias" in result.stdout
    assert "--handles" in result.stdout
    assert "--repo" in result.stdout
    assert "--months" in result.stdout
    assert "--paths" in result.stdout
    assert "--extensions" in result.stdout
    assert "--since" in result.stdout
