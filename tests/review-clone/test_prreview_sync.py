"""review-clone's vendored prreview.py must be a byte-identical copy of review-panel's."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "plugins"
CANON = ROOT / "review-panel" / "scripts" / "prreview.py"
COPY = ROOT / "review-clone" / "scripts" / "prreview.py"


def test_vendored_prreview_has_not_drifted():
    assert COPY.read_bytes() == CANON.read_bytes(), (
        "plugins/review-clone/scripts/prreview.py drifted from "
        "plugins/review-panel/scripts/prreview.py: run plugins/review-clone/sync-prreview.sh")


def test_docstring_names_canonical_path_and_sync_script():
    text = CANON.read_text()
    assert "plugins/review-panel/scripts/prreview.py" in text
    assert "sync-prreview.sh" in text
