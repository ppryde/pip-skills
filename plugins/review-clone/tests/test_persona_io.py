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
