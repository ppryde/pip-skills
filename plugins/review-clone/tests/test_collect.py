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


def test_fetch_pr_handles_null_user_accounts():
    """Comments/PRs with user=null (deleted accounts) don't crash."""
    from scripts.collect import fetch_pr

    with patch("scripts.collect._gh_get") as mock_get:
        mock_get.side_effect = [
            # pr_meta with null user (ghosted PR author)
            {
                "number": 999,
                "title": "Ghost PR",
                "user": None,
                "merged": False,
                "body": "ignored",
            },
            # review_comments with one ghost commenter + one real
            [
                {
                    "id": 9001,
                    "user": None,
                    "path": "x.tsx",
                    "body": "from ghost",
                    "diff_hunk": "@@",
                    "html_url": "u1",
                    "in_reply_to_id": None,
                    "created_at": "2026-01-01T00:00:00Z",
                },
                {
                    "id": 9002,
                    "user": {"login": "jen"},
                    "path": "x.tsx",
                    "body": "from jen",
                    "diff_hunk": "@@",
                    "html_url": "u2",
                    "in_reply_to_id": None,
                    "created_at": "2026-01-01T00:01:00Z",
                },
            ],
            # issue_comments with one ghost
            [{
                "id": 9003,
                "user": None,
                "body": "issue from ghost",
                "html_url": "u3",
                "created_at": "2026-01-01T00:02:00Z",
            }],
        ]
        result = fetch_pr(repo="o/r", number=999, handles=["jen"], paths=[], extensions=[])

    # Ghost reviewer skipped, jen's comment kept
    assert len(result["review_comments"]) == 1
    assert result["review_comments"][0]["id"] == 9002
    # Ghost issue comment skipped (None can never be in handle_set)
    assert len(result["issue_comments"]) == 0
    # Ghost PR author → pr_description not captured
    assert result["pr_description"] is None
    # pr_meta.author is None (preserves the ghosted state for downstream)
    assert result["pr_meta"]["author"] is None


def test_run_collect_writes_raw_and_snapshot(tmp_path, monkeypatch):
    import scripts.collect as collect_mod

    monkeypatch.setattr(collect_mod, "PERSONA_ROOT", tmp_path)

    fixture = json.loads(Path("tests/fixtures/sample_pr.json").read_text())

    with patch.object(collect_mod, "discover_prs", return_value=[100]), \
         patch.object(collect_mod, "fetch_pr", return_value={
             "pr_meta": {"number": 100, "title": "x", "author": "jane", "merged": True},
             "review_comments": [{"id": 1, "user": "jen", "path": "f.tsx",
                                  "body": "x", "diff_hunk": "@@", "reply_thread": [],
                                  "html_url": "u", "created_at": "2026-05-01T10:00:00Z"}],
             "issue_comments": [],
             "pr_description": None,
         }):
        snapshot = collect_mod.run_collect(
            alias="jen",
            handles=["jen"],
            repo="o/r",
            months=6,
            paths=["frontend/"],
            extensions=[".tsx"],
            since=None,
        )

    persona_dir = tmp_path / "jen"
    raw_dir = persona_dir / "raw"
    assert raw_dir.exists()
    assert (raw_dir / "pr-100.json").exists()
    assert (persona_dir / "snapshot.json").exists()

    saved = json.loads((persona_dir / "snapshot.json").read_text())
    assert saved["counts"]["prs"] == 1
    assert saved["counts"]["review_comments"] == 1
    assert saved["counts"]["issue_comments"] == 0
    assert saved["counts"]["pr_descriptions"] == 0
    assert saved["window"]["months"] == 6


def test_run_collect_skips_unchanged_prs_in_refresh_mode(tmp_path, monkeypatch):
    """When --since is set, discover_prs is called with that date directly,
    NOT a recomputed months-based date."""
    import scripts.collect as collect_mod

    monkeypatch.setattr(collect_mod, "PERSONA_ROOT", tmp_path)

    captured_since = []

    def fake_discover(repo, handles, since):
        captured_since.append(since)
        return []

    with patch.object(collect_mod, "discover_prs", side_effect=fake_discover):
        collect_mod.run_collect(
            alias="jen",
            handles=["jen"],
            repo="o/r",
            months=6,
            paths=[],
            extensions=[],
            since="2026-05-01T00:00:00Z",
        )

    assert captured_since == ["2026-05-01T00:00:00Z"]
