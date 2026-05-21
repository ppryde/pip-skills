import json
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


def test_fetch_pr_filters_by_handle_and_path():
    from scripts.collect import fetch_pr

    fixture = json.loads(Path("tests/fixtures/sample_pr.json").read_text())

    with patch("scripts.collect._gh_get") as mock_get:
        mock_get.side_effect = [
            fixture["pr"],
            fixture["review_comments"],
            fixture["issue_comments"],
        ]
        result = fetch_pr(
            repo="o/r",
            number=100,
            handles=["jen"],
            paths=["frontend/"],
            extensions=[".tsx"],
        )

    # Filter to jen's comments on frontend .tsx files only
    assert len(result["review_comments"]) == 1
    assert result["review_comments"][0]["id"] == 1001
    assert result["review_comments"][0]["diff_hunk"].startswith("@@")
    # Reply chains: jane's reply 1002 is kept under 1001's thread
    assert result["review_comments"][0]["reply_thread"] == [
        {"id": 1002, "user": "jane", "body": "Good catch, fixed."}
    ]
    # Issue comments NOT path-filtered (no path); jen's comment kept
    assert len(result["issue_comments"]) == 1
    # PR description authored by jane (not in handles) → not captured
    assert result.get("pr_description") is None


def test_fetch_pr_captures_pr_description_if_authored_by_handle():
    from scripts.collect import fetch_pr

    fixture = json.loads(Path("tests/fixtures/sample_pr.json").read_text())

    with patch("scripts.collect._gh_get") as mock_get:
        mock_get.side_effect = [
            fixture["pr"],
            fixture["review_comments"],
            fixture["issue_comments"],
        ]
        result = fetch_pr(
            repo="o/r",
            number=100,
            handles=["jane"],
            paths=[],
            extensions=[],
        )

    assert result["pr_description"] == "FUNDE-123 — adds a new widget."
