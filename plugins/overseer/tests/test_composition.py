import subprocess
import sys
from pathlib import Path

from scripts.resume import handoff_report
from scripts.store import init_workflow, save_card
from tests.factories import make_card as _card

VIGIL_CLI = Path(__file__).resolve().parents[2] / "vigil" / "scripts" / "cli.py"


def test_overseer_rollup_feeds_vigil_handover(tmp_path):
    # Build an overseer ledger with an in-flight card and get the enriched rollup.
    root = init_workflow(tmp_path)
    save_card(root, _card("WF-001"))
    rollup = handoff_report(tmp_path, notes="preserve the auth spike")
    assert "WF-001" in rollup and "preserve the auth spike" in rollup

    # Activate vigil, then pipe the overseer rollup into vigil handover as the payload.
    subprocess.run(
        [sys.executable, str(VIGIL_CLI), "--root", str(tmp_path), "begin"],
        check=True, capture_output=True, text=True,
    )
    result = subprocess.run(
        [sys.executable, str(VIGIL_CLI), "--root", str(tmp_path),
         "handover", "--no-snapshot", "--content-file", "-"],
        input=rollup, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr

    handoff = (tmp_path / ".vigil" / "handoff.md").read_text()
    assert "WF-001" in handoff                    # the overseer rollup flowed through
    assert "preserve the auth spike" in handoff   # notes preserved
    assert "Session snapshot" not in handoff      # --no-snapshot honored
