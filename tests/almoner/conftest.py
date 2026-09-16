from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_almoner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin every path almoner resolves into this test's ``tmp_path``.

    ``CLAUDE_CONFIG_DIR`` is what ``paths.home()`` derives from; ``ALMONER_HOME``
    and ``ALMONER_DB`` are pinned too so no test can read a developer's real
    source config, secrets or cached work content.
    """
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("ALMONER_HOME", str(tmp_path / "config" / "almoner"))
    monkeypatch.setenv("ALMONER_DB", str(tmp_path / "config" / "almoner" / "almoner.db"))
