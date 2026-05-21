import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock


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


def test_discover_prs_dedupes_across_handles():
    from scripts.collect import discover_prs

    fixture = Path("tests/fixtures/sample_search.json").read_text()

    with patch("scripts.collect._gh_search") as mock_search:
        mock_search.return_value = [
            {"number": 100, "updatedAt": "2026-05-01T10:00:00Z"},
            {"number": 200, "updatedAt": "2026-04-15T10:00:00Z"},
        ]
        prs = discover_prs("owner/repo", ["a", "b"], since="2026-01-01")

    # Each handle queried once, results deduped
    assert mock_search.call_count == 2
    assert sorted(prs) == [100, 200]
