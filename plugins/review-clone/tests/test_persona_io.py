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
