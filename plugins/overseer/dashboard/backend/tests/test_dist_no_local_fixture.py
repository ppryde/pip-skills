"""`dist/` is committed, so it must never carry a developer's own inflow.

The Almoner's demo can be pointed at `src/board/almoner/fixture.local.ts`, a
gitignored file holding real gathered mail, Slack and Linear content. The file
itself is safe — git ignores it. The BUILD is not: `npm run build` compiles
whatever is in `src/` into `dist/assets/*.js`, and `dist/` is committed.

So a build run on a machine that happens to have an override writes someone's
real inbox into a public repository, and the only thing standing between that
and `git push` is whether anyone thought to look.

This is not hypothetical. It happened on this branch: a dist built with an
override was committed and pushed, carrying real colleague names, real customer
names and a real loan amount, and was caught by grepping the built asset
afterwards rather than by any check. Hence this file.

`demo.ts` re-exports the override's `LOCAL_MARKER` precisely so that bundling
the override necessarily carries a known string into `dist/`. A clean checkout
has no override, so the marker is absent and this test is a no-op.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Must match `LOCAL_MARKER` in `fixture.local.ts`. Split so that this file's
# own source cannot satisfy the grep it performs.
MARKER = "ALMONER_LOCAL_DIGEST" + "_DO_NOT_SHIP"

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _assets() -> list[Path]:
    if not DIST.is_dir():
        return []
    return sorted(p for p in DIST.rglob("*") if p.suffix in {".js", ".css", ".html"})


def test_committed_dist_carries_no_local_digest() -> None:
    """No built asset may contain the local-override marker."""
    assets = _assets()
    if not assets:
        pytest.skip("no dist/ built here — nothing could have been committed")

    offenders = [
        p.relative_to(DIST).as_posix()
        for p in assets
        if MARKER in p.read_text(encoding="utf-8", errors="ignore")
    ]

    assert not offenders, (
        "dist/ was built with a local Almoner override and carries real inflow: "
        f"{offenders}. Move src/board/almoner/fixture.local.ts aside, re-run "
        "`npm run build`, and commit that dist instead. If this build was "
        "already pushed, the content is public — treat it as disclosed."
    )
