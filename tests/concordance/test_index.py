import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from scripts.index import LockTimeout, ensure_view, maybe_gc, view_lock
from scripts.store import Store
from scripts.views import worktree_view

FILES = {f"m{i}.py": f"def f{i}():\n    return {i}\n" for i in range(5)}


def test_second_worktree_parses_only_what_differs(tmp_path: Path, make_repo) -> None:
    repo = make_repo(FILES)
    st = Store(tmp_path / "i.db")
    first = ensure_view(st, worktree_view(repo.root))
    assert (first.parsed, first.reused) == (5, 0)
    wt = repo.worktree("wt1", "feat")
    wt.write({"m0.py": "def f0():\n    return 99\n"})
    second = ensure_view(st, worktree_view(wt.root))
    assert (second.parsed, second.reused) == (1, 4)


def test_parse_failures_are_reported_and_not_retried(tmp_path: Path, make_repo) -> None:
    repo = make_repo({"bad.py": "def (:\n"})
    st = Store(tmp_path / "i.db")
    report = ensure_view(st, worktree_view(repo.root))
    assert [p for p, _ in report.failed] == ["bad.py"]
    assert ensure_view(st, worktree_view(repo.root)).reused == 1


def test_deadline_skips_the_rest_and_the_next_run_continues(tmp_path: Path, make_repo) -> None:
    repo = make_repo(FILES)
    st = Store(tmp_path / "i.db")
    report = ensure_view(st, worktree_view(repo.root), deadline_s=-1)
    assert report.parsed == 0 and set(report.skipped) == set(FILES)
    assert set(report.skipped.values()) == {"deadline"}
    assert st.coverage(report.view_id).not_indexed == sorted(FILES)
    assert ensure_view(st, worktree_view(repo.root)).parsed == 5


def test_stale_lock_is_stolen(tmp_path: Path) -> None:  # Review Focus 4
    lock = tmp_path / "locks" / "wt-x.lock"
    lock.parent.mkdir()
    lock.write_text("99999")
    old = time.time() - 1000
    os.utime(lock, (old, old))
    with view_lock(tmp_path / "i.db", "wt-x", wait_s=1):
        assert lock.exists()
    assert not lock.exists()


def test_live_lock_times_out(tmp_path: Path) -> None:
    with (
        view_lock(tmp_path / "i.db", "wt-x", wait_s=1),
        pytest.raises(LockTimeout, match="index busy"),
        view_lock(tmp_path / "i.db", "wt-x", wait_s=0.2),
    ):
        pass


def test_concurrent_indexers_share_facts_without_duplicates(tmp_path: Path, make_repo) -> None:
    repo = make_repo(FILES)
    wt = repo.worktree("wt1", "feat")
    db = tmp_path / "i.db"
    Store(db).close()

    def build(root: Path) -> int:
        st = Store(db)
        try:
            return ensure_view(st, worktree_view(root)).parsed
        finally:
            st.close()

    with ThreadPoolExecutor(2) as pool:
        list(pool.map(build, [repo.root, wt.root]))
    st = Store(db)
    assert st.conn.execute("SELECT COUNT(*) FROM file_facts").fetchone()[0] == 5
    assert st.conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0] == 10


def test_gc_drops_removed_worktrees_and_their_orphan_facts(tmp_path: Path, make_repo) -> None:
    repo = make_repo(FILES)
    st = Store(tmp_path / "i.db")
    ensure_view(st, worktree_view(repo.root))
    wt = repo.worktree("wt1", "feat")
    wt.write({"only_here.py": "def z():\n    pass\n"})
    ensure_view(st, worktree_view(wt.root))
    repo.git("worktree", "remove", "--force", str(wt.root))
    report = maybe_gc(st, repo.root, now=time.time() + 7200)
    assert report is not None and report.views_removed == 1 and report.facts_removed == 1
    assert st.has_facts([("m0.py", worktree_view(repo.root).files["m0.py"])])
    assert maybe_gc(st, repo.root, now=time.time() + 7300) is None  # throttled to hourly


def test_gc_keeps_facts_still_referenced_by_a_surviving_view(
    tmp_path: Path, make_repo
) -> None:
    repo = make_repo(FILES)
    st = Store(tmp_path / "i.db")
    ensure_view(st, worktree_view(repo.root))
    wt = repo.worktree("wt1", "feat")
    ensure_view(st, worktree_view(wt.root))
    repo.git("worktree", "remove", "--force", str(wt.root))
    sha = worktree_view(repo.root).files["m0.py"]
    report = maybe_gc(st, repo.root, now=time.time() + 7200)
    assert report is not None and report.views_removed == 1 and report.facts_removed == 0
    assert st.file_facts("m0.py", sha) is not None
