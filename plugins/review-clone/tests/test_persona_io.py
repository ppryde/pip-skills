from pathlib import Path
from scripts.persona_io import read_frontmatter


def test_read_frontmatter_parses_yaml_header():
    fm = read_frontmatter(Path("tests/fixtures/sample_persona.md"))
    assert fm["alias"] == "jen"
    assert fm["handles"] == ["jenniferjensen"]
    assert fm["repo"] == "wayflyer/wayflyer"
    assert fm["window"]["months"] == 6
    assert fm["drift_log"] == []
    assert fm["drift_log_archived_count"] == 0


def test_write_persona_roundtrips(tmp_path):
    from scripts.persona_io import write_persona, read_frontmatter

    path = tmp_path / "PERSONA.md"
    frontmatter = {
        "alias": "test",
        "handles": ["a", "b"],
        "repo": "x/y",
        "window": {"months": 6, "since": "2025-11-22"},
        "drift_log": [],
        "drift_log_archived_count": 0,
    }
    body = "## Voice\nTest voice."
    write_persona(path, frontmatter, body)

    assert path.exists()
    fm = read_frontmatter(path)
    assert fm["alias"] == "test"
    assert fm["handles"] == ["a", "b"]
    assert fm["window"]["months"] == 6


def test_append_drift_entry_within_cap(tmp_path):
    from scripts.persona_io import append_drift_entry, read_frontmatter, write_persona

    path = tmp_path / "PERSONA.md"
    write_persona(
        path,
        {"alias": "t", "drift_log": [], "drift_log_archived_count": 0},
        "## Voice\nx",
    )

    for i in range(5):
        append_drift_entry(path, {"date": f"2026-05-0{i+1}", "summary": f"entry {i}"})

    fm = read_frontmatter(path)
    assert len(fm["drift_log"]) == 5
    assert fm["drift_log_archived_count"] == 0


def test_append_drift_entry_archives_beyond_cap(tmp_path):
    from scripts.persona_io import append_drift_entry, read_frontmatter, write_persona

    path = tmp_path / "PERSONA.md"
    write_persona(
        path,
        {"alias": "t", "drift_log": [], "drift_log_archived_count": 0},
        "## Voice\nx",
    )

    for i in range(25):
        append_drift_entry(
            path, {"date": f"2026-05-{i+1:02d}", "summary": f"entry {i}"}
        )

    fm = read_frontmatter(path)
    assert len(fm["drift_log"]) == 20, "frontmatter capped at 20"
    assert fm["drift_log_archived_count"] == 5, "5 oldest archived"

    archive = path.parent / "drift.log"
    assert archive.exists()
    archived_lines = archive.read_text().strip().split("\n")
    assert len(archived_lines) == 5


def test_format_scalar_quotes_ambiguous_literals(tmp_path):
    """Strings that look like type literals must round-trip as strings."""
    from scripts.persona_io import write_persona, read_frontmatter

    path = tmp_path / "PERSONA.md"
    tricky = {
        "alias": "true",
        "handles": ["null", "42", "3.14", "[]", ""],
        "repo": "false",
        "drift_log": [],
        "drift_log_archived_count": 0,
    }
    write_persona(path, tricky, "## Voice\nx")
    fm = read_frontmatter(path)

    assert fm["alias"] == "true"
    assert fm["handles"] == ["null", "42", "3.14", "[]", ""]
    assert fm["repo"] == "false"
