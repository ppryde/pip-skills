"""core/home.ts exists once per mod (plugins share no code); the copies must be identical."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COPIES = [REPO / "plugins" / p / "plugin" / "core" / "home.ts" for p in ("census-mod", "context-vigil-mod", "agent-roster")]
TESTS = [REPO / "plugins" / p / "tests" / "home.test.ts" for p in ("census-mod", "context-vigil-mod", "agent-roster")]


def test_the_three_home_helpers_are_identical():
    texts = {c.read_text() for c in COPIES}
    assert len(texts) == 1, "plugins/*/plugin/core/home.ts differ: edit one and copy it to the others"


def test_the_three_home_test_files_are_identical():
    assert len({t.read_text() for t in TESTS}) == 1
