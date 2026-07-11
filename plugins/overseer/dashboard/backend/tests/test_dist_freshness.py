"""Dist-freshness guard (WF-005 C7).

`frontend/npm run build` writes `frontend/dist/.srchash` — a content hash of
`frontend/src/**` (see `frontend/scripts/srchash.mjs` for the exact rule).
This test recomputes the SAME hash in Python and asserts it matches the
committed digest, so a `dist/` that has drifted out of sync with `src/`
(someone edited src and forgot to rebuild before committing) fails CI
instead of silently serving stale JS.

Deliberately content-hash only — NOT mtime-based. git does not preserve
file mtimes across clone/checkout, so mtime comparisons are meaningless
here.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

# backend/tests/test_dist_freshness.py -> parents[0]=tests [1]=backend [2]=dashboard
DASHBOARD_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = DASHBOARD_DIR / "frontend"
SRC_DIR = FRONTEND_DIR / "src"
SRCHASH_FILE = FRONTEND_DIR / "dist" / ".srchash"


def _compute_src_hash(src_dir: Path) -> str:
    """Mirror `frontend/scripts/srchash.mjs` byte-for-byte.

    For every file under `src_dir` (recursive), sorted by its POSIX-style
    path relative to `src_dir`: feed the hash the relative path (UTF-8) +
    NUL, then the file's raw bytes + NUL. The hex sha256 digest of that
    stream is the "srchash".
    """
    rel_paths = sorted(
        p.relative_to(src_dir).as_posix() for p in src_dir.rglob("*") if p.is_file()
    )
    digest = hashlib.sha256()
    for rel in rel_paths:
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update((src_dir / rel).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def test_dist_hash_matches_src() -> None:
    if not SRCHASH_FILE.is_file():
        pytest.skip(
            "frontend/dist/.srchash absent — run `npm run build` in "
            "dashboard/frontend before this check can run"
        )

    committed = SRCHASH_FILE.read_text().strip()
    computed = _compute_src_hash(SRC_DIR)

    assert computed == committed, (
        "frontend/dist is stale relative to frontend/src — rebuild with "
        "`npm run build` in dashboard/frontend and recommit dist/"
    )
