# concordance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build concordance v1 (phase 1 of the spec): a worktree-native SQLite symbol index for Python and TypeScript, CLI queries that detect removed contracts, signature drift, callers and guarding tests, a review procedure skill, and a review-panel `blast-radius` lens, judged by a bench replay.

**Architecture:** A pure-stdlib Python package (`plugins/concordance/scripts/`) owns the store, views, extraction, resolution, diff analysis, queries and rendering. Facts are keyed by `(path, blob_sha)` and shared by every worktree of a repo; a *view* maps one worktree (or one base commit) to file versions, and names resolve at query time within a view. TypeScript is parsed per file by a small Node script on the pinned `typescript` package; everything else is Python.

**Tech Stack:** Python ≥ 3.11 stdlib only (`ast`, `tokenize`, `sqlite3`, `difflib`, `subprocess`); Node ≥ 18 with `typescript@5.6.3` (exact, lockfile) for TS extraction; git CLI; pytest, ruff, mypy (dev only).

**Spec:** `docs/superpowers/specs/2026-10-11-concordance-design.md` (read its "Implementation notes" section: it records six refinements this plan implements).

## Global Constraints

- Python runtime code is **stdlib only**. No third-party Python imports under `plugins/concordance/scripts/`.
- The only non-stdlib runtime dependency is `typescript` **5.6.3 exact**, installed by `cli.py setup-ts` with `npm ci --ignore-scripts` from a committed `package-lock.json`. Missing Node/typescript must degrade (TS files reported "not indexed"), never crash.
- The store lives at `$CLAUDE_CONFIG_DIR/concordance/<repo-key>/index.db` (`CLAUDE_CONFIG_DIR` defaulting to `~/.claude`), overridable by `CONCORDANCE_DB`. **Nothing is ever written into the repo** being indexed.
- Repo identity is `git rev-parse --git-common-dir`; all worktrees of a repo share one store.
- Output paths are **relative to the asking worktree's root**; no answer ever names a path in another worktree.
- Default `--budget` is **1500** tokens (estimated as chars/3); default index deadline is **60 s**.
- Diff base default: merge-base of HEAD with the default branch (`origin/HEAD`, else `main`, else `master`). **Never `HEAD~1`.**
- Exit codes: `check` exits 1 on verdicts, 0 when clean; any internal error exits 2 with a message on stderr.
- Tests pin `CLAUDE_CONFIG_DIR` into `tmp_path` (repo rule: CLAUDE.md "Test isolation") and create nothing outside `tmp_path`.
- Style: ruff line length 100; mypy `disallow_untyped_defs = true` (annotate every def); match census's module docstring style.
- Run the suite from `plugins/concordance`: `../../.venv/bin/python -m pytest` (poetry is not used for these plugins; see `tests/run.sh`).
- Commits end with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_014wmY6mtSJuwaUZhLicPW4n
  ```

## Review Focus

1. **No resolvable base** (detached HEAD in a repo whose default branch is neither `origin/HEAD`, `main` nor `master`, or no merge-base): exit 2 with a message telling the user to pass `--base <ref>`; no traceback. Test: Task 10 `test_no_default_branch_exits_2_with_hint`.
2. **Undecodable or invalid source** (non-UTF-8 bytes, NUL bytes, syntax errors): recorded as a parse failure and listed in the coverage footer, never a crash and never silent. Test: Task 3 `test_bad_input_is_a_recorded_failure_not_a_crash`.
3. **Paths with spaces and non-ASCII characters**: indexed and printed correctly (all git listing uses `-z`). Test: Task 1 `test_ls_files_handles_spaces_and_unicode`.
4. **A lock left by a crashed indexer**: stolen after it goes stale, so the index never wedges. Test: Task 5 `test_stale_lock_is_stolen`.
5. **Symlinked files in the repo**: skipped, not followed out of the tree. Test: Task 4 `test_symlinks_are_skipped`.

---

## File Structure

```
plugins/concordance/
  .claude-plugin/plugin.json
  .gitignore                       # scripts/extract_ts/node_modules/
  pyproject.toml                   # pytest/ruff/mypy config (as census)
  README.md
  scripts/
    __init__.py
    paths.py                       # config dir, repo key, store path
    gitio.py                       # every git subprocess call
    facts.py                       # fact dataclasses + JSON (de)serialisation
    store.py                       # SQLite schema and the one writer
    extract_py.py                  # Python facts (ast + tokenize)
    extract_ts.py                  # bridge to the Node extractor
    extract_ts/package.json        # pins typescript 5.6.3
    extract_ts/package-lock.json
    extract_ts/extract.mjs         # TS facts (compiler parser, per file)
    views.py                       # worktree view, base view, blob hashing
    index.py                       # ensure_view: hash-gated build, lock, deadline, GC
    resolve.py                     # ViewIndex: query-time resolution, callers, lookup
    classify.py                    # pure-refactor and reorder detection (Python)
    diff.py                        # base vs head analysis
    query.py                       # removed-contract, sig-drift, tests, literals
    render.py                      # budgeted sections
    review.py                      # review-context assembly, verdicts
    cli.py                         # argparse entry point
  skills/review-procedure/SKILL.md
plugins/review-panel/skills/reviewers/blast-radius.md
tests/concordance/
  __init__.py
  conftest.py
  test_gitio.py  test_store.py  test_extract_py.py  test_views.py  test_index.py
  test_resolve.py  test_classify.py  test_diff.py  test_query.py  test_render.py
  test_cli.py  test_extract_ts.py
  bench/README.md  bench/make_case.py  bench/tools-concordance.md  bench/judge.md
```

Modified: `tests/run.sh` (add the suite), `.claude-plugin/marketplace.json` (new entry, version bump), `plugins/review-panel/.claude-plugin/plugin.json` (version bump), `CLAUDE.md` (plugin list).

---

### Task 1: Scaffold, paths and git layer

**Files:**
- Create: `plugins/concordance/.claude-plugin/plugin.json`, `plugins/concordance/.gitignore`, `plugins/concordance/pyproject.toml`, `plugins/concordance/scripts/__init__.py`, `plugins/concordance/scripts/paths.py`, `plugins/concordance/scripts/gitio.py`
- Create: `tests/concordance/__init__.py`, `tests/concordance/conftest.py`, `tests/concordance/test_gitio.py`
- Modify: `tests/run.sh` (SUITES line)

**Interfaces:**
- Produces: `paths.config_dir() -> Path`, `paths.repo_key(common_dir: Path) -> str`, `paths.store_path(common_dir: Path) -> Path`; `gitio.GitError`, `gitio.git(cwd: Path, *args: str, input: bytes | None = None) -> bytes`, `gitio.git_text(cwd, *args) -> str`, `gitio.worktree_root(cwd) -> Path`, `gitio.common_dir(cwd) -> Path`, `gitio.default_branch(cwd) -> str`, `gitio.merge_base(cwd, a: str, b: str = "HEAD") -> str`, `gitio.rev_parse(cwd, ref: str) -> str`, `gitio.ls_files_stage(cwd) -> dict[str, str]`, `gitio.changed_paths(cwd) -> list[str]`, `gitio.deleted_paths(cwd) -> set[str]`, `gitio.ls_tree(cwd, commit: str) -> dict[str, str]`, `gitio.cat_blobs(cwd, shas: list[str]) -> dict[str, bytes]`, `gitio.show_file(cwd, commit: str, path: str) -> bytes | None`, `gitio.live_worktrees(cwd) -> set[str]`; test fixture `make_repo(files: dict[str, str], name: str = "repo") -> Repo` with `Repo.root`, `Repo.git(*args) -> str`, `Repo.write(files: dict[str, str | None])`, `Repo.commit(msg="c") -> str`, `Repo.worktree(name, branch) -> Repo`.

- [ ] **Step 1: Scaffold the plugin files**

`plugins/concordance/.claude-plugin/plugin.json`:
```json
{
  "name": "concordance",
  "version": "0.1.0",
  "description": "An owned, worktree-native symbol index for Python and TypeScript, built for review: who calls this, which tests guard it, what still relies on what the diff removed, which call sites no longer match a changed signature. Detection runs in the CLI at zero agent tokens; a review procedure and a review-panel blast-radius lens tell the reviewer exactly when to use it.",
  "author": {
    "name": "Pip",
    "url": "https://github.com/ppryde/pip-skills"
  },
  "keywords": ["code-review", "symbols", "callers", "impact", "worktrees", "sqlite", "python", "typescript"]
}
```

`plugins/concordance/.gitignore`:
```
scripts/extract_ts/node_modules/
```

`plugins/concordance/pyproject.toml`:
```toml
[tool.pytest.ini_options]
testpaths = ["../../tests/concordance"]
python_files = ["test_*.py"]
addopts = "-v --tb=short"
pythonpath = ["."]

[tool.ruff]
line-length = 100

[tool.mypy]
python_version = "3.11"
disallow_untyped_defs = true
warn_unused_ignores = true
ignore_missing_imports = true
```

`plugins/concordance/scripts/__init__.py`: empty file. `tests/concordance/__init__.py`: empty file.

In `tests/run.sh` change the SUITES line to:
```bash
SUITES=(overseer census vigil review-clone chronicle almoner concordance)
```

- [ ] **Step 2: Write the test fixtures**

`tests/concordance/conftest.py`:
```python
"""Shared fixtures. Every test runs against a throwaway git repo and a store in tmp_path."""
from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Never touch the real account store (repo rule, CLAUDE.md "Test isolation"):
    # an unpinned run would write index.db under the developer's real config dir.
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("CONCORDANCE_DB", raising=False)
    # Keep user git config (hooks, templates, signing) out of fixture repos.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


class Repo:
    def __init__(self, root: Path) -> None:
        self.root = root

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.root), *args], check=True, capture_output=True, text=True
        ).stdout

    def write(self, files: dict[str, str | None]) -> None:
        for rel, text in files.items():
            path = self.root / rel
            if text is None:
                path.unlink()
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def commit(self, msg: str = "c") -> str:
        self.git("add", "-A")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", msg)
        return self.git("rev-parse", "HEAD").strip()

    def worktree(self, name: str, branch: str) -> Repo:
        path = self.root.parent / name
        self.git("worktree", "add", "-q", "-b", branch, str(path))
        return Repo(path)


@pytest.fixture
def make_repo(tmp_path: Path) -> Callable[..., Repo]:
    def _make(files: dict[str, str], name: str = "repo") -> Repo:
        root = tmp_path / name
        root.mkdir()
        repo = Repo(root)
        repo.git("init", "-q", "-b", "main")
        repo.write(dict(files))
        repo.commit("base")
        return repo

    return _make
```

- [ ] **Step 3: Write the failing tests**

`tests/concordance/test_gitio.py`:
```python
from pathlib import Path

import pytest

from scripts import gitio, paths


def test_store_path_roots_at_config_dir(tmp_path: Path, make_repo) -> None:
    repo = make_repo({"a.py": "x = 1\n"})
    store = paths.store_path(gitio.common_dir(repo.root))
    assert store.is_relative_to(tmp_path / "config" / "concordance")
    assert store.name == "index.db"
    assert store.parent.name.startswith("repo-")


def test_store_path_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_repo) -> None:
    monkeypatch.setenv("CONCORDANCE_DB", str(tmp_path / "x.db"))
    repo = make_repo({"a.py": "x = 1\n"})
    assert paths.store_path(gitio.common_dir(repo.root)) == tmp_path / "x.db"


def test_worktrees_share_a_repo_key(make_repo) -> None:
    repo = make_repo({"a.py": "x = 1\n"})
    wt = repo.worktree("wt1", "feat")
    assert gitio.common_dir(repo.root) == gitio.common_dir(wt.root)
    assert gitio.worktree_root(wt.root / ".") == wt.root.resolve()


def test_default_branch_falls_back_to_main(make_repo) -> None:
    repo = make_repo({"a.py": "x = 1\n"})
    assert gitio.default_branch(repo.root) == "main"


def test_ls_files_handles_spaces_and_unicode(make_repo) -> None:  # Review Focus 3
    repo = make_repo({"dir with space/ünï.py": "x = 1\n"})
    assert "dir with space/ünï.py" in gitio.ls_files_stage(repo.root)


def test_changed_deleted_and_untracked(make_repo) -> None:
    repo = make_repo({"a.py": "x = 1\n", "b.py": "y = 1\n"})
    repo.write({"a.py": "x = 2\n", "new.py": "n = 1\n", "b.py": None})
    assert set(gitio.changed_paths(repo.root)) == {"a.py", "new.py", "b.py"}
    assert gitio.deleted_paths(repo.root) == {"b.py"}


def test_ls_tree_and_cat_blobs_read_a_commit_without_checkout(make_repo) -> None:
    repo = make_repo({"a.py": "x = 1\n", "pkg/b.py": "y = 2\n"})
    sha = repo.git("rev-parse", "HEAD").strip()
    repo.write({"a.py": "x = 99\n"})
    tree = gitio.ls_tree(repo.root, sha)
    assert set(tree) == {"a.py", "pkg/b.py"}
    blobs = gitio.cat_blobs(repo.root, [tree["a.py"], tree["pkg/b.py"]])
    assert blobs[tree["a.py"]] == b"x = 1\n"
    assert gitio.show_file(repo.root, sha, "a.py") == b"x = 1\n"
    assert gitio.show_file(repo.root, sha, "missing.json") is None


def test_live_worktrees_lists_resolved_paths(make_repo) -> None:
    repo = make_repo({"a.py": "x = 1\n"})
    wt = repo.worktree("wt1", "feat")
    live = gitio.live_worktrees(repo.root)
    assert str(repo.root.resolve()) in live and str(wt.root.resolve()) in live


def test_git_error_names_the_command(tmp_path: Path) -> None:
    with pytest.raises(gitio.GitError, match="rev-parse"):
        gitio.worktree_root(tmp_path)
```

- [ ] **Step 4: Run them to verify they fail**

Run: `cd plugins/concordance && ../../.venv/bin/python -m pytest ../../tests/concordance/test_gitio.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.gitio'` (or `scripts.paths`)

- [ ] **Step 5: Implement `paths.py` and `gitio.py`**

`plugins/concordance/scripts/paths.py`:
```python
"""Where concordance keeps its store: under the account's config dir, one folder per repo.

Rooted at CLAUDE_CONFIG_DIR (never a hardcoded ~/.claude) so each Claude account keeps its
own index; keyed by the git common dir so every worktree of a repo shares one store.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path


def config_dir() -> Path:
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env).expanduser() if env else Path.home() / ".claude"


def repo_key(common_dir: Path) -> str:
    common = common_dir.resolve()
    name = common.parent.name if common.name == ".git" else common.name.removesuffix(".git")
    digest = hashlib.sha1(str(common).encode()).hexdigest()[:8]
    return f"{name}-{digest}"


def store_path(common_dir: Path) -> Path:
    override = os.environ.get("CONCORDANCE_DB")
    if override:
        return Path(override)
    return config_dir() / "concordance" / repo_key(common_dir) / "index.db"
```

`plugins/concordance/scripts/gitio.py`:
```python
"""Every git call concordance makes. Argv only (no shell); listings use -z so any path survives."""
from __future__ import annotations

import subprocess
from pathlib import Path

_SKIP_MODES = {b"120000", b"160000"}  # symlinks and submodules are never indexed


class GitError(RuntimeError):
    pass


def git(cwd: Path, *args: str, input: bytes | None = None) -> bytes:
    proc = subprocess.run(["git", "-C", str(cwd), *args], input=input, capture_output=True)
    if proc.returncode != 0:
        err = proc.stderr.decode(errors="replace").strip()
        raise GitError(f"git {' '.join(args)}: {err}")
    return proc.stdout


def git_text(cwd: Path, *args: str) -> str:
    return git(cwd, *args).decode()


def worktree_root(cwd: Path) -> Path:
    return Path(git_text(cwd, "rev-parse", "--show-toplevel").strip()).resolve()


def common_dir(cwd: Path) -> Path:
    out = git_text(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    return Path(out).resolve()


def default_branch(cwd: Path) -> str:
    try:
        ref = git_text(cwd, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD").strip()
        return ref.removeprefix("refs/remotes/")
    except GitError:
        pass
    for candidate in ("main", "master"):
        try:
            git(cwd, "rev-parse", "--verify", "--quiet", f"refs/heads/{candidate}")
            return candidate
        except GitError:
            continue
    raise GitError("no default branch found (origin/HEAD, main, master); pass --base <ref>")


def merge_base(cwd: Path, a: str, b: str = "HEAD") -> str:
    return git_text(cwd, "merge-base", a, b).strip()


def rev_parse(cwd: Path, ref: str) -> str:
    return git_text(cwd, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()


def _split_z(out: bytes) -> list[bytes]:
    return [entry for entry in out.split(b"\0") if entry]


def ls_files_stage(cwd: Path) -> dict[str, str]:
    """Tracked files -> index blob sha (symlinks and submodules skipped)."""
    result: dict[str, str] = {}
    for entry in _split_z(git(cwd, "ls-files", "-s", "-z")):
        meta, path = entry.split(b"\t", 1)
        mode, sha, _stage = meta.split()
        if mode in _SKIP_MODES:
            continue
        result[path.decode()] = sha.decode()
    return result


def changed_paths(cwd: Path) -> list[str]:
    """Paths whose working-tree content differs from the index, plus untracked non-ignored files."""
    modified = _split_z(git(cwd, "diff", "--name-only", "-z"))
    untracked = _split_z(git(cwd, "ls-files", "-o", "--exclude-standard", "-z"))
    return [p.decode() for p in [*modified, *untracked]]


def deleted_paths(cwd: Path) -> set[str]:
    return {p.decode() for p in _split_z(git(cwd, "ls-files", "-d", "-z"))}


def ls_tree(cwd: Path, commit: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for entry in _split_z(git(cwd, "ls-tree", "-r", "-z", commit)):
        meta, path = entry.split(b"\t", 1)
        mode, kind, sha = meta.split()
        if kind != b"blob" or mode in _SKIP_MODES:
            continue
        result[path.decode()] = sha.decode()
    return result


def cat_blobs(cwd: Path, shas: list[str]) -> dict[str, bytes]:
    if not shas:
        return {}
    out = git(cwd, "cat-file", "--batch", input=("\n".join(shas) + "\n").encode())
    result: dict[str, bytes] = {}
    pos = 0
    for sha in shas:
        newline = out.index(b"\n", pos)
        header = out[pos:newline].split()
        if len(header) < 3 or header[1] == b"missing":
            pos = newline + 1
            continue
        size = int(header[2])
        start = newline + 1
        result[sha] = out[start : start + size]
        pos = start + size + 1
    return result


def show_file(cwd: Path, commit: str, path: str) -> bytes | None:
    try:
        return git(cwd, "show", f"{commit}:{path}")
    except GitError:
        return None


def live_worktrees(cwd: Path) -> set[str]:
    out = git_text(cwd, "worktree", "list", "--porcelain")
    return {
        str(Path(line.removeprefix("worktree ")).resolve())
        for line in out.splitlines()
        if line.startswith("worktree ")
    }
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd plugins/concordance && ../../.venv/bin/python -m pytest ../../tests/concordance/test_gitio.py -q`
Expected: 9 passed

- [ ] **Step 7: Commit**

```bash
git add plugins/concordance tests/concordance tests/run.sh
git commit -m "feat(concordance): scaffold, store path and git layer"
```

---

### Task 2: Facts and the store

**Files:**
- Create: `plugins/concordance/scripts/facts.py`, `plugins/concordance/scripts/store.py`
- Test: `tests/concordance/test_store.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces (`facts.py`): frozen dataclasses `Param(name: str, kind: str, has_default: bool)` with kind in `posonly|pos|vararg|kwonly|varkw`; `Signature = tuple[Param, ...]`; `CallShape(positional: int, keywords: tuple[str, ...], star: bool, dstar: bool)`; `Symbol(qualname, kind, line_start, line_end, is_test, signature: Signature | None = None, alias_of: str | None = None)` with kind in `module|class|function|method|type|alias`; `Ref(src, target, kind, line, args: CallShape | None = None)` with kind in `call|name|inherit|decorator`; `Literal(kind, text, line, symbol)` with kind `string|comment`; `Guard(symbol, kind, line, text)` with kind `if|raise|assert`; mutable `FileFacts(path, blob_sha, lang, parsed_ok, error=None, symbols=[], refs=[], literals=[], guards=[])`; `file_facts_from_dict(d: dict[str, Any], blob_sha: str) -> FileFacts`.
- Produces (`store.py`): `Coverage(total: int, failed: list[tuple[str, str]], not_indexed: list[str])`; `ViewRow(view_id, kind, worktree_path, ref, built_at)`; `Store(path: Path)` with `.path`, `.conn`, `meta_get(key) -> str | None`, `meta_set(key, value)`, `has_facts(keys) -> set[tuple[str, str]]`, `put_facts(ff) -> bool`, `file_facts(path, blob_sha) -> FileFacts | None`, `set_view(view_id, kind, worktree_path: str | None, ref: str | None, files: dict[str, str])`, `get_view(view_id) -> ViewRow | None`, `views() -> list[ViewRow]`, `view_files(view_id) -> dict[str, str]`, `delete_view(view_id)`, `delete_orphan_facts() -> int`, `view_symbols(view_id) -> list[tuple[str, Symbol]]`, `view_refs(view_id) -> list[tuple[str, Ref]]`, `literal_occurrences(view_id, texts: list[str]) -> list[tuple[str, str, int]]`, `coverage(view_id) -> Coverage`, `record_event(command, view_id, latency_ms, est_tokens, payload="")`, `close()`.

- [ ] **Step 1: Write the failing tests**

`tests/concordance/test_store.py`:
```python
from pathlib import Path

from scripts.facts import CallShape, FileFacts, Guard, Literal, Param, Ref, Symbol, file_facts_from_dict
from scripts.store import Store


def sample(path: str = "a.py", sha: str = "s1") -> FileFacts:
    return FileFacts(
        path, sha, "python", True, None,
        [
            Symbol("a", "module", 1, 3, False),
            Symbol("a.f", "function", 1, 2, False, (Param("x", "pos", False),)),
            Symbol("a.L", "alias", 1, 1, False, None, "b.Loan"),
        ],
        [Ref("a.f", "b.g", "call", 2, CallShape(1, ("k",), False, False))],
        [Literal("string", "hello", 2, "a.f")],
        [Guard("a.f", "if", 2, "x")],
    )


def test_roundtrip_and_idempotent_insert(tmp_path: Path) -> None:
    st = Store(tmp_path / "i.db")
    assert st.put_facts(sample()) is True
    assert st.put_facts(sample()) is False  # another writer already stored it
    assert st.file_facts("a.py", "s1") == sample()
    assert st.has_facts([("a.py", "s1"), ("a.py", "nope")]) == {("a.py", "s1")}


def test_failed_parse_roundtrips(tmp_path: Path) -> None:
    st = Store(tmp_path / "i.db")
    st.put_facts(FileFacts("bad.py", "s", "python", False, "SyntaxError: line 1: x"))
    back = st.file_facts("bad.py", "s")
    assert back is not None and not back.parsed_ok and back.error == "SyntaxError: line 1: x"


def test_views_joins_and_coverage(tmp_path: Path) -> None:
    st = Store(tmp_path / "i.db")
    st.put_facts(sample())
    st.put_facts(FileFacts("c.py", "s3", "python", False, "boom"))
    st.set_view("wt-1", "wt", "/r", None, {"a.py": "s1", "b.py": "s2", "c.py": "s3"})
    assert st.view_files("wt-1") == {"a.py": "s1", "b.py": "s2", "c.py": "s3"}
    assert [s.qualname for _, s in st.view_symbols("wt-1")] == ["a", "a.f", "a.L"]
    assert [(p, r.target) for p, r in st.view_refs("wt-1")] == [("a.py", "b.g")]
    cov = st.coverage("wt-1")
    assert (cov.total, cov.failed, cov.not_indexed) == (3, [("c.py", "boom")], ["b.py"])
    assert st.literal_occurrences("wt-1", ["hello"]) == [("hello", "a.py", 2)]
    st.set_view("wt-1", "wt", "/r", None, {"a.py": "s1"})  # replaces, not appends
    assert st.view_files("wt-1") == {"a.py": "s1"}


def test_orphan_facts_are_deleted_with_their_children(tmp_path: Path) -> None:
    st = Store(tmp_path / "i.db")
    st.put_facts(sample())
    st.set_view("wt-1", "wt", "/r", None, {"a.py": "s1"})
    assert st.delete_orphan_facts() == 0
    st.delete_view("wt-1")
    assert st.delete_orphan_facts() == 1
    assert st.file_facts("a.py", "s1") is None
    for table in ("symbols", "refs", "literals", "guards"):
        assert st.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_meta_and_events(tmp_path: Path) -> None:
    st = Store(tmp_path / "i.db")
    assert st.meta_get("schema_version") == "1"
    st.meta_set("last_gc", "5")
    assert st.meta_get("last_gc") == "5"
    st.record_event("callers", "wt-1", 12, 300)
    row = st.conn.execute("SELECT command, view_id, latency_ms, est_tokens FROM events").fetchone()
    assert row == ("callers", "wt-1", 12, 300)


def test_file_facts_from_dict() -> None:
    d = {
        "path": "x.ts", "lang": "typescript", "parsed_ok": True, "error": None,
        "symbols": [{"qualname": "ts:x.f", "kind": "function", "line_start": 1, "line_end": 2,
                     "is_test": False, "signature": [["a", "pos", False]], "alias_of": None}],
        "refs": [{"src": "ts:x.f", "target": "ts:y.g", "kind": "call", "line": 2,
                  "args": {"positional": 2, "keywords": [], "star": False, "dstar": False}}],
        "literals": [{"kind": "comment", "text": "hi", "line": 1, "symbol": "ts:x.f"}],
        "guards": [{"symbol": "ts:x.f", "kind": "raise", "line": 2, "text": "new Error()"}],
    }
    ff = file_facts_from_dict(d, "sha")
    assert ff.blob_sha == "sha" and ff.symbols[0].signature == (Param("a", "pos", False),)
    assert ff.refs[0].args == CallShape(2, (), False, False)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd plugins/concordance && ../../.venv/bin/python -m pytest ../../tests/concordance/test_store.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.facts'`

- [ ] **Step 3: Implement `facts.py`**

```python
"""The facts an extractor produces for one file. Plain data; no storage, no resolution.

A Ref's target is a raw name: an absolute dotted Python name ("pkg.mod.func"), "?.name" for a
call on a value whose type is unknown, "ts:<path-without-ext>.<member>" for TypeScript, or
"ts-bare:<specifier>|<member>" for a TS package import. resolve.py turns these into symbols.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Param:
    name: str
    kind: str  # posonly | pos | vararg | kwonly | varkw
    has_default: bool


Signature = tuple[Param, ...]


@dataclass(frozen=True)
class CallShape:
    positional: int
    keywords: tuple[str, ...]
    star: bool
    dstar: bool


@dataclass(frozen=True)
class Symbol:
    qualname: str
    kind: str  # module | class | function | method | type | alias
    line_start: int
    line_end: int
    is_test: bool
    signature: Signature | None = None
    alias_of: str | None = None


@dataclass(frozen=True)
class Ref:
    src: str
    target: str
    kind: str  # call | name | inherit | decorator
    line: int
    args: CallShape | None = None


@dataclass(frozen=True)
class Literal:
    kind: str  # string | comment
    text: str
    line: int
    symbol: str


@dataclass(frozen=True)
class Guard:
    symbol: str
    kind: str  # if | raise | assert
    line: int
    text: str


@dataclass
class FileFacts:
    path: str
    blob_sha: str
    lang: str
    parsed_ok: bool
    error: str | None = None
    symbols: list[Symbol] = field(default_factory=list)
    refs: list[Ref] = field(default_factory=list)
    literals: list[Literal] = field(default_factory=list)
    guards: list[Guard] = field(default_factory=list)


def signature_to_json(sig: Signature | None) -> str | None:
    if sig is None:
        return None
    return json.dumps([[p.name, p.kind, p.has_default] for p in sig])


def signature_from_json(raw: str | None) -> Signature | None:
    if raw is None:
        return None
    return tuple(Param(n, k, bool(d)) for n, k, d in json.loads(raw))


def shape_to_json(shape: CallShape | None) -> str | None:
    if shape is None:
        return None
    return json.dumps([shape.positional, list(shape.keywords), shape.star, shape.dstar])


def shape_from_json(raw: str | None) -> CallShape | None:
    if raw is None:
        return None
    pos, kws, star, dstar = json.loads(raw)
    return CallShape(int(pos), tuple(kws), bool(star), bool(dstar))


def file_facts_from_dict(d: dict[str, Any], blob_sha: str) -> FileFacts:
    """Build FileFacts from the TS extractor's JSON (same shape as the Python side)."""
    def sig(raw: Any) -> Signature | None:
        return None if raw is None else tuple(Param(n, k, bool(h)) for n, k, h in raw)

    def args(raw: Any) -> CallShape | None:
        if raw is None:
            return None
        return CallShape(raw["positional"], tuple(raw["keywords"]), raw["star"], raw["dstar"])

    return FileFacts(
        path=d["path"],
        blob_sha=blob_sha,
        lang=d["lang"],
        parsed_ok=bool(d["parsed_ok"]),
        error=d.get("error"),
        symbols=[
            Symbol(s["qualname"], s["kind"], s["line_start"], s["line_end"], bool(s["is_test"]),
                   sig(s.get("signature")), s.get("alias_of"))
            for s in d["symbols"]
        ],
        refs=[Ref(r["src"], r["target"], r["kind"], r["line"], args(r.get("args")))
              for r in d["refs"]],
        literals=[Literal(x["kind"], x["text"], x["line"], x["symbol"]) for x in d["literals"]],
        guards=[Guard(g["symbol"], g["kind"], g["line"], g["text"]) for g in d["guards"]],
    )
```

- [ ] **Step 4: Implement `store.py`**

```python
"""concordance's SQLite store, and its one writer.

Facts are keyed by (path, blob_sha), so every worktree of a repo shares them. A view maps one
worktree (or one base commit) to the file versions it sees; queries join through view_files.
"""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from scripts.facts import (
    FileFacts,
    Guard,
    Literal,
    Ref,
    Symbol,
    shape_from_json,
    shape_to_json,
    signature_from_json,
    signature_to_json,
)

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS file_facts(
  path TEXT NOT NULL, blob_sha TEXT NOT NULL, lang TEXT NOT NULL,
  parsed_ok INTEGER NOT NULL, error TEXT, PRIMARY KEY(path, blob_sha));
CREATE TABLE IF NOT EXISTS symbols(
  path TEXT NOT NULL, blob_sha TEXT NOT NULL, qualname TEXT NOT NULL, kind TEXT NOT NULL,
  line_start INTEGER NOT NULL, line_end INTEGER NOT NULL, is_test INTEGER NOT NULL,
  signature_json TEXT, alias_of TEXT);
CREATE INDEX IF NOT EXISTS symbols_file ON symbols(path, blob_sha);
CREATE TABLE IF NOT EXISTS refs(
  path TEXT NOT NULL, blob_sha TEXT NOT NULL, src TEXT NOT NULL, target TEXT NOT NULL,
  kind TEXT NOT NULL, line INTEGER NOT NULL, args_json TEXT);
CREATE INDEX IF NOT EXISTS refs_file ON refs(path, blob_sha);
CREATE TABLE IF NOT EXISTS literals(
  path TEXT NOT NULL, blob_sha TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL,
  line INTEGER NOT NULL, symbol TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS literals_file ON literals(path, blob_sha);
CREATE INDEX IF NOT EXISTS literals_text ON literals(text);
CREATE TABLE IF NOT EXISTS guards(
  path TEXT NOT NULL, blob_sha TEXT NOT NULL, symbol TEXT NOT NULL, kind TEXT NOT NULL,
  line INTEGER NOT NULL, text TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS guards_file ON guards(path, blob_sha);
CREATE TABLE IF NOT EXISTS views(
  view_id TEXT PRIMARY KEY, kind TEXT NOT NULL, worktree_path TEXT, ref TEXT,
  built_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS view_files(
  view_id TEXT NOT NULL, path TEXT NOT NULL, blob_sha TEXT NOT NULL,
  PRIMARY KEY(view_id, path));
CREATE INDEX IF NOT EXISTS view_files_fact ON view_files(path, blob_sha);
CREATE TABLE IF NOT EXISTS events(
  ts REAL NOT NULL, session TEXT, command TEXT NOT NULL, view_id TEXT,
  latency_ms INTEGER, est_tokens INTEGER, payload TEXT);
"""

_CHILD_TABLES = ("symbols", "refs", "literals", "guards")


@dataclass(frozen=True)
class Coverage:
    total: int
    failed: list[tuple[str, str]]
    not_indexed: list[str]


@dataclass(frozen=True)
class ViewRow:
    view_id: str
    kind: str
    worktree_path: str | None
    ref: str | None
    built_at: float


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.executescript(_SCHEMA)
        self.conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def _tx(self) -> Iterator[None]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    def meta_get(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return None if row is None else str(row[0])

    def meta_set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def has_facts(self, keys: Iterable[tuple[str, str]]) -> set[tuple[str, str]]:
        wanted = list(keys)
        found: set[tuple[str, str]] = set()
        for i in range(0, len(wanted), 400):
            chunk = wanted[i : i + 400]
            where = " OR ".join("(path=? AND blob_sha=?)" for _ in chunk)
            params = [part for key in chunk for part in key]
            for path, sha in self.conn.execute(
                f"SELECT path, blob_sha FROM file_facts WHERE {where}", params
            ):
                found.add((path, sha))
        return found

    def put_facts(self, ff: FileFacts) -> bool:
        """Store one file's facts. False when another writer already stored this (path, sha)."""
        key = (ff.path, ff.blob_sha)
        with self._tx():
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO file_facts(path, blob_sha, lang, parsed_ok, error) "
                "VALUES (?, ?, ?, ?, ?)",
                (*key, ff.lang, int(ff.parsed_ok), ff.error),
            )
            if cur.rowcount == 0:
                return False
            self.conn.executemany(
                "INSERT INTO symbols VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(*key, s.qualname, s.kind, s.line_start, s.line_end, int(s.is_test),
                  signature_to_json(s.signature), s.alias_of) for s in ff.symbols],
            )
            self.conn.executemany(
                "INSERT INTO refs VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(*key, r.src, r.target, r.kind, r.line, shape_to_json(r.args)) for r in ff.refs],
            )
            self.conn.executemany(
                "INSERT INTO literals VALUES (?, ?, ?, ?, ?, ?)",
                [(*key, x.kind, x.text, x.line, x.symbol) for x in ff.literals],
            )
            self.conn.executemany(
                "INSERT INTO guards VALUES (?, ?, ?, ?, ?, ?)",
                [(*key, g.symbol, g.kind, g.line, g.text) for g in ff.guards],
            )
        return True

    def file_facts(self, path: str, blob_sha: str) -> FileFacts | None:
        key = (path, blob_sha)
        row = self.conn.execute(
            "SELECT lang, parsed_ok, error FROM file_facts WHERE path=? AND blob_sha=?", key
        ).fetchone()
        if row is None:
            return None
        where = "WHERE path=? AND blob_sha=? ORDER BY rowid"
        symbols = [
            Symbol(q, k, a, b, bool(t), signature_from_json(sig), alias)
            for q, k, a, b, t, sig, alias in self.conn.execute(
                "SELECT qualname, kind, line_start, line_end, is_test, signature_json, alias_of "
                f"FROM symbols {where}", key)
        ]
        refs = [
            Ref(src, target, kind, line, shape_from_json(args))
            for src, target, kind, line, args in self.conn.execute(
                f"SELECT src, target, kind, line, args_json FROM refs {where}", key)
        ]
        literals = [
            Literal(kind, text, line, symbol)
            for kind, text, line, symbol in self.conn.execute(
                f"SELECT kind, text, line, symbol FROM literals {where}", key)
        ]
        guards = [
            Guard(symbol, kind, line, text)
            for symbol, kind, line, text in self.conn.execute(
                f"SELECT symbol, kind, line, text FROM guards {where}", key)
        ]
        return FileFacts(path, blob_sha, row[0], bool(row[1]), row[2],
                         symbols, refs, literals, guards)

    def set_view(self, view_id: str, kind: str, worktree_path: str | None, ref: str | None,
                 files: dict[str, str]) -> None:
        with self._tx():
            self.conn.execute(
                "INSERT INTO views(view_id, kind, worktree_path, ref, built_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(view_id) DO UPDATE SET "
                "worktree_path=excluded.worktree_path, ref=excluded.ref, "
                "built_at=excluded.built_at",
                (view_id, kind, worktree_path, ref, time.time()),
            )
            self.conn.execute("DELETE FROM view_files WHERE view_id=?", (view_id,))
            self.conn.executemany(
                "INSERT INTO view_files(view_id, path, blob_sha) VALUES (?, ?, ?)",
                [(view_id, p, s) for p, s in files.items()],
            )

    def get_view(self, view_id: str) -> ViewRow | None:
        row = self.conn.execute(
            "SELECT view_id, kind, worktree_path, ref, built_at FROM views WHERE view_id=?",
            (view_id,),
        ).fetchone()
        return None if row is None else ViewRow(*row)

    def views(self) -> list[ViewRow]:
        return [ViewRow(*row) for row in self.conn.execute(
            "SELECT view_id, kind, worktree_path, ref, built_at FROM views")]

    def view_files(self, view_id: str) -> dict[str, str]:
        return dict(self.conn.execute(
            "SELECT path, blob_sha FROM view_files WHERE view_id=?", (view_id,)))

    def delete_view(self, view_id: str) -> None:
        with self._tx():
            self.conn.execute("DELETE FROM view_files WHERE view_id=?", (view_id,))
            self.conn.execute("DELETE FROM views WHERE view_id=?", (view_id,))

    def delete_orphan_facts(self) -> int:
        with self._tx():
            cur = self.conn.execute(
                "DELETE FROM file_facts WHERE NOT EXISTS (SELECT 1 FROM view_files vf "
                "WHERE vf.path=file_facts.path AND vf.blob_sha=file_facts.blob_sha)"
            )
            removed = cur.rowcount
            for table in _CHILD_TABLES:
                self.conn.execute(
                    f"DELETE FROM {table} WHERE NOT EXISTS (SELECT 1 FROM file_facts ff "
                    f"WHERE ff.path={table}.path AND ff.blob_sha={table}.blob_sha)"
                )
        return removed

    def view_symbols(self, view_id: str) -> list[tuple[str, Symbol]]:
        rows = self.conn.execute(
            "SELECT s.path, s.qualname, s.kind, s.line_start, s.line_end, s.is_test, "
            "s.signature_json, s.alias_of FROM symbols s JOIN view_files vf "
            "ON vf.path=s.path AND vf.blob_sha=s.blob_sha WHERE vf.view_id=? ORDER BY s.rowid",
            (view_id,),
        )
        return [(p, Symbol(q, k, a, b, bool(t), signature_from_json(sig), alias))
                for p, q, k, a, b, t, sig, alias in rows]

    def view_refs(self, view_id: str) -> list[tuple[str, Ref]]:
        rows = self.conn.execute(
            "SELECT r.path, r.src, r.target, r.kind, r.line, r.args_json FROM refs r "
            "JOIN view_files vf ON vf.path=r.path AND vf.blob_sha=r.blob_sha "
            "WHERE vf.view_id=? ORDER BY r.rowid",
            (view_id,),
        )
        return [(p, Ref(src, target, kind, line, shape_from_json(args)))
                for p, src, target, kind, line, args in rows]

    def literal_occurrences(self, view_id: str, texts: list[str]) -> list[tuple[str, str, int]]:
        if not texts:
            return []
        marks = ",".join("?" for _ in texts)
        rows = self.conn.execute(
            "SELECT l.text, l.path, l.line FROM literals l JOIN view_files vf "
            "ON vf.path=l.path AND vf.blob_sha=l.blob_sha "
            f"WHERE vf.view_id=? AND l.kind='string' AND l.text IN ({marks}) "
            "ORDER BY l.path, l.line",
            (view_id, *texts),
        )
        return [(t, p, line) for t, p, line in rows]

    def coverage(self, view_id: str) -> Coverage:
        rows = self.conn.execute(
            "SELECT vf.path, ff.parsed_ok, ff.error FROM view_files vf LEFT JOIN file_facts ff "
            "ON ff.path=vf.path AND ff.blob_sha=vf.blob_sha WHERE vf.view_id=? ORDER BY vf.path",
            (view_id,),
        ).fetchall()
        failed = [(p, err or "parse failed") for p, ok, err in rows if ok == 0]
        missing = [p for p, ok, _ in rows if ok is None]
        return Coverage(len(rows), failed, missing)

    def record_event(self, command: str, view_id: str | None, latency_ms: int, est_tokens: int,
                     payload: str = "", session: str = "") -> None:
        self.conn.execute(
            "INSERT INTO events(ts, session, command, view_id, latency_ms, est_tokens, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (time.time(), session, command, view_id, latency_ms, est_tokens, payload),
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd plugins/concordance && ../../.venv/bin/python -m pytest ../../tests/concordance/test_store.py -q`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add plugins/concordance/scripts/facts.py plugins/concordance/scripts/store.py tests/concordance/test_store.py
git commit -m "feat(concordance): content-keyed facts store with views"
```

---

### Task 3: Python extractor

**Files:**
- Create: `plugins/concordance/scripts/extract_py.py`
- Test: `tests/concordance/test_extract_py.py`

**Interfaces:**
- Consumes: `facts.*` (Task 2).
- Produces: `extract_py.module_name(path: str) -> str`, `extract_py.is_test_path(path: str) -> bool`, `extract_py.extract_python(path: str, blob_sha: str, data: bytes) -> FileFacts`.

Rules this extractor implements (the resolver in Task 6 relies on them):
- Module qualname = file path, dotted, without `.py`, without a trailing `__init__`, without a leading `src`. A path that yields an empty name becomes `__root__`.
- Every symbol in a test file (`tests/` or `test/` directory, `test_*.py`, `*_test.py`, `conftest.py`) has `is_test=True`.
- Module-level imports become `alias` symbols `<module>.<local>` with `alias_of=<absolute target>` (this is how re-exports resolve).
- Ref targets: `self.x`/`cls.x` → `<enclosing class>.x`; deeper `self.a.b` → `?.b`; a name bound by an import → the absolute target; a module-level definition → `<module>.<name>`; a call on any other dotted value → `?.<last>`; bare unknown names and builtins → no ref.
- Guards are recorded only inside functions; docstrings and f-string fragments are not literals; strings shorter than 3 characters are skipped.

- [ ] **Step 1: Write the failing tests**

`tests/concordance/test_extract_py.py`:
```python
from scripts.extract_py import extract_python, module_name

SRC = '''\
"""Module doc."""
from .models import Loan as L
from pkg.events import DomainEvent
import json

TABLE = "scenario_events"


class Repo(Base):
    def save(self, loan, *, flush=True):
        # FK order matters here
        if loan is None:
            raise ValueError("no loan")
        self.validate(loan)
        L.check(loan, strict=True)
        return json.dumps(DomainEvent)


def helper(a, b=1):
    return Repo().save(a, flush=False)
'''


def facts():
    return extract_python("src/pkg/repo.py", "sha1", SRC.encode())


def test_module_name_strips_src_and_init() -> None:
    assert module_name("src/pkg/repo.py") == "pkg.repo"
    assert module_name("pkg/__init__.py") == "pkg"
    assert module_name("__init__.py") == "__root__"


def test_symbols_signature_and_aliases() -> None:
    by = {s.qualname: s for s in facts().symbols}
    assert by["pkg.repo"].kind == "module"
    assert by["pkg.repo.Repo"].kind == "class"
    save = by["pkg.repo.Repo.save"]
    assert save.kind == "method" and (save.line_start, save.line_end) == (10, 16)
    assert [(p.name, p.kind, p.has_default) for p in save.signature] == [
        ("self", "pos", False), ("loan", "pos", False), ("flush", "kwonly", True)]
    assert by["pkg.repo.L"].kind == "alias" and by["pkg.repo.L"].alias_of == "pkg.models.Loan"
    assert by["pkg.repo.json"].alias_of == "json"


def test_refs_resolve_imports_self_and_unknown_receivers() -> None:
    refs = facts().refs
    calls = {(r.src, r.target) for r in refs if r.kind == "call"}
    assert ("pkg.repo.Repo.save", "pkg.repo.Repo.validate") in calls
    assert ("pkg.repo.Repo.save", "pkg.models.Loan.check") in calls
    assert ("pkg.repo.Repo.save", "json.dumps") in calls
    assert ("pkg.repo.helper", "?.save") in calls
    assert ("pkg.repo.helper", "pkg.repo.Repo") in calls
    names = {(r.src, r.target) for r in refs if r.kind == "name"}
    assert ("pkg.repo.Repo.save", "pkg.events.DomainEvent") in names
    assert not any("Base" in r.target or "ValueError" in r.target for r in refs)


def test_call_shapes() -> None:
    refs = facts().refs
    check = next(r for r in refs if r.target == "pkg.models.Loan.check")
    assert check.args is not None
    assert (check.args.positional, check.args.keywords) == (1, ("strict",))
    save = next(r for r in refs if r.target == "?.save")
    assert save.args is not None and save.args.keywords == ("flush",)


def test_decorators_and_bases() -> None:
    src = "from functools import cache\nimport abc\n\nclass A(abc.ABC):\n    @cache\n    def f(self):\n        pass\n"
    refs = extract_python("m.py", "s", src.encode()).refs
    assert ("m.A.f", "functools.cache", "decorator") in {(r.src, r.target, r.kind) for r in refs}
    assert ("m.A", "abc.ABC", "inherit") in {(r.src, r.target, r.kind) for r in refs}


def test_guards_literals_comments() -> None:
    f = facts()
    assert {(g.kind, g.text) for g in f.guards} >= {
        ("if", "loan is None"), ("raise", "ValueError('no loan')")}
    strings = {x.text for x in f.literals if x.kind == "string"}
    assert "scenario_events" in strings and "Module doc." not in strings
    comment = next(x for x in f.literals if x.kind == "comment")
    assert (comment.text, comment.symbol) == ("FK order matters here", "pkg.repo.Repo.save")


def test_relative_import_from_package_init() -> None:
    f = extract_python("src/pkg/__init__.py", "s", b"from .events import DomainEvent\n")
    alias = next(s for s in f.symbols if s.kind == "alias")
    assert (alias.qualname, alias.alias_of) == ("pkg.DomainEvent", "pkg.events.DomainEvent")


def test_test_files_mark_every_symbol_as_test() -> None:
    f = extract_python("tests/test_repo.py", "s", b"def test_x():\n    helper()\n")
    assert f.symbols and all(s.is_test for s in f.symbols)


def test_bad_input_is_a_recorded_failure_not_a_crash() -> None:  # Review Focus 2
    bad = extract_python("a.py", "s", b"\xff\xfe def")
    assert not bad.parsed_ok and bad.error is not None and "UTF-8" in bad.error
    nul = extract_python("b.py", "s", b"x = 1\x00\n")
    assert not nul.parsed_ok
    syn = extract_python("c.py", "s", b"def (:\n")
    assert not syn.parsed_ok and syn.error is not None and syn.error.startswith("SyntaxError: line 1")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd plugins/concordance && ../../.venv/bin/python -m pytest ../../tests/concordance/test_extract_py.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.extract_py'`

- [ ] **Step 3: Implement `extract_py.py`**

```python
"""Python facts from one file, by stdlib ast and tokenize. Nothing is imported or executed.

Facts depend on this file's path and content only, so they can be shared by every worktree
that holds the same blob. Cross-file resolution happens later, at query time (resolve.py).
"""
from __future__ import annotations

import ast
import io
import tokenize
from pathlib import PurePosixPath

from scripts.facts import CallShape, FileFacts, Guard, Literal, Param, Ref, Signature, Symbol

_MIN_LITERAL = 3
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def module_name(path: str) -> str:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    if parts and parts[0] == "src":
        parts.pop(0)
    return ".".join(parts) or "__root__"


def is_test_path(path: str) -> bool:
    p = PurePosixPath(path)
    return (
        "tests" in p.parts[:-1]
        or "test" in p.parts[:-1]
        or p.name.startswith("test_")
        or p.name.endswith("_test.py")
        or p.name == "conftest.py"
    )


def extract_python(path: str, blob_sha: str, data: bytes) -> FileFacts:
    try:
        source = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        return FileFacts(path, blob_sha, "python", False,
                         f"not UTF-8: {exc.reason} at byte {exc.start}")
    try:
        tree = ast.parse(source, filename=path)
    except (SyntaxError, ValueError) as exc:
        line = getattr(exc, "lineno", None)
        msg = getattr(exc, "msg", None) or str(exc)
        return FileFacts(path, blob_sha, "python", False, f"SyntaxError: line {line}: {msg}")
    ex = _Extractor(path, source, tree)
    ex.run()
    return FileFacts(path, blob_sha, "python", True, None,
                     ex.symbols, ex.refs, ex.literals, ex.guards)


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _shape(node: ast.Call) -> CallShape:
    return CallShape(
        positional=sum(1 for a in node.args if not isinstance(a, ast.Starred)),
        keywords=tuple(k.arg for k in node.keywords if k.arg is not None),
        star=any(isinstance(a, ast.Starred) for a in node.args),
        dstar=any(k.arg is None for k in node.keywords),
    )


def _signature(a: ast.arguments) -> Signature:
    params: list[Param] = []
    positional = [*a.posonlyargs, *a.args]
    first_default = len(positional) - len(a.defaults)
    for i, arg in enumerate(positional):
        kind = "posonly" if i < len(a.posonlyargs) else "pos"
        params.append(Param(arg.arg, kind, i >= first_default))
    if a.vararg:
        params.append(Param(a.vararg.arg, "vararg", True))
    for arg, default in zip(a.kwonlyargs, a.kw_defaults):
        params.append(Param(arg.arg, "kwonly", default is not None))
    if a.kwarg:
        params.append(Param(a.kwarg.arg, "varkw", True))
    return tuple(params)


class _Extractor(ast.NodeVisitor):
    def __init__(self, path: str, source: str, tree: ast.Module) -> None:
        self.module = module_name(path)
        self.is_pkg = PurePosixPath(path).name == "__init__.py"
        self.is_test = is_test_path(path)
        self.source = source
        self.tree = tree
        self.imports: dict[str, str] = {}
        self.module_imports: list[tuple[str, str]] = []
        self.top_defs: set[str] = set()
        self.docstrings: set[int] = set()
        self.stack: list[tuple[str, str]] = []
        self.symbols: list[Symbol] = []
        self.refs: list[Ref] = []
        self.literals: list[Literal] = []
        self.guards: list[Guard] = []

    @property
    def current(self) -> str:
        return self.stack[-1][0] if self.stack else self.module

    def _class_qual(self) -> str | None:
        for qual, kind in reversed(self.stack):
            if kind == "class":
                return qual
        return None

    def _in_function(self) -> bool:
        return any(kind in ("function", "method") for _, kind in self.stack)

    def run(self) -> None:
        self._prepass()
        n_lines = max(1, len(self.source.splitlines()))
        self.symbols.append(Symbol(self.module, "module", 1, n_lines, self.is_test))
        for local, target in self.module_imports:
            self.symbols.append(Symbol(f"{self.module}.{local}", "alias", 1, 1, self.is_test,
                                       alias_of=target))
        self.visit(self.tree)
        self._comments()

    # -- pre-pass: imports, module-level names, docstrings ---------------------------------

    def _relative_base(self, level: int) -> str | None:
        parts = self.module.split(".") if self.module != "__root__" else []
        pkg = parts if self.is_pkg else parts[:-1]
        up = level - 1
        if up > len(pkg):
            return None
        return ".".join(pkg[: len(pkg) - up])

    def _import_pairs(self, node: ast.Import | ast.ImportFrom) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    pairs.append((a.asname, a.name))
                else:
                    root = a.name.split(".")[0]
                    pairs.append((root, root))
            return pairs
        base = node.module or ""
        if node.level:
            rel = self._relative_base(node.level)
            if rel is None:
                return pairs
            base = f"{rel}.{base}" if rel and base else (rel or base)
        for a in node.names:
            if a.name != "*":
                pairs.append((a.asname or a.name, f"{base}.{a.name}" if base else a.name))
        return pairs

    def _prepass(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, (*_DEFS, ast.Module)):
                body = node.body
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    self.docstrings.add(id(body[0].value))
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self.imports.update(self._import_pairs(node))
        for node in self.tree.body:
            if isinstance(node, _DEFS):
                self.top_defs.add(node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                self.top_defs.update(t.id for t in targets if isinstance(t, ast.Name))
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                self.module_imports.extend(self._import_pairs(node))

    # -- name resolution within this file --------------------------------------------------

    def _resolve(self, dotted: str) -> str | None:
        head, _, rest = dotted.partition(".")
        if head in ("self", "cls"):
            cls = self._class_qual()
            if cls is None or not rest:
                return None
            return f"?.{rest.rsplit('.', 1)[-1]}" if "." in rest else f"{cls}.{rest}"
        if head in self.imports:
            base = self.imports[head]
            return f"{base}.{rest}" if rest else base
        if head in self.top_defs:
            return f"{self.module}.{dotted}"
        if rest:
            return f"?.{rest.rsplit('.', 1)[-1]}"
        return None

    def _ref(self, target: str, kind: str, line: int, args: CallShape | None = None,
             src: str | None = None) -> None:
        self.refs.append(Ref(src or self.current, target, kind, line, args))

    # -- definitions -----------------------------------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._def(node, "function")

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._def(node, "function")

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._def(node, "class")

    def _def(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, kind: str) -> None:
        parent_kind = self.stack[-1][1] if self.stack else "module"
        if kind == "function" and parent_kind == "class":
            kind = "method"
        qual = f"{self.current}.{node.name}"
        sig = None if isinstance(node, ast.ClassDef) else _signature(node.args)
        self.symbols.append(Symbol(qual, kind, node.lineno, node.end_lineno or node.lineno,
                                   self.is_test, sig))
        for dec in node.decorator_list:
            func = dec.func if isinstance(dec, ast.Call) else dec
            target = self._resolve(_dotted(func) or "")
            if target:
                self._ref(target, "decorator", dec.lineno, src=qual)
            if isinstance(dec, ast.Call):
                for a in dec.args:
                    self.visit(a)
                for k in dec.keywords:
                    self.visit(k.value)
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                target = self._resolve(_dotted(base) or "")
                if target:
                    self._ref(target, "inherit", base.lineno, src=qual)
        else:
            for default in [*node.args.defaults, *node.args.kw_defaults]:
                if default is not None:
                    self.visit(default)
        self.stack.append((qual, kind))
        for stmt in node.body:
            self.visit(stmt)
        self.stack.pop()

    # -- references ------------------------------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        dotted = _dotted(node.func)
        target: str | None = None
        if dotted is not None:
            target = self._resolve(dotted)
        elif isinstance(node.func, ast.Attribute):
            target = f"?.{node.func.attr}"
            self.visit(node.func.value)
        else:
            self.visit(node.func)
        if target is not None:
            self._ref(target, "call", node.lineno, _shape(node))
        for a in node.args:
            self.visit(a)
        for k in node.keywords:
            self.visit(k.value)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and (node.id in self.imports or node.id in self.top_defs):
            target = self._resolve(node.id)
            if target:
                self._ref(target, "name", node.lineno)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        dotted = _dotted(node)
        if isinstance(node.ctx, ast.Load) and dotted and dotted.split(".")[0] in self.imports:
            target = self._resolve(dotted)
            if target:
                self._ref(target, "name", node.lineno)
                return
        self.generic_visit(node)

    # -- guards and literals ---------------------------------------------------------------

    def visit_If(self, node: ast.If) -> None:
        if self._in_function():
            self.guards.append(Guard(self.current, "if", node.lineno, ast.unparse(node.test)))
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        if self._in_function() and node.exc is not None:
            self.guards.append(Guard(self.current, "raise", node.lineno, ast.unparse(node.exc)))
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        if self._in_function():
            self.guards.append(Guard(self.current, "assert", node.lineno, ast.unparse(node.test)))
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if (isinstance(node.value, str) and id(node) not in self.docstrings
                and len(node.value) >= _MIN_LITERAL):
            self.literals.append(Literal("string", node.value, node.lineno, self.current))

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        for part in node.values:
            if isinstance(part, ast.FormattedValue):
                self.visit(part.value)

    def _comments(self) -> None:
        spans = sorted(
            ((s.line_start, s.line_end, s.qualname) for s in self.symbols
             if s.kind not in ("module", "alias")),
            key=lambda t: t[1] - t[0],
        )
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(self.source).readline))
        except (tokenize.TokenError, SyntaxError):
            return
        for tok in tokens:
            if tok.type != tokenize.COMMENT:
                continue
            line = tok.start[0]
            text = tok.string.lstrip("#").strip()
            if not text:
                continue
            owner = next((q for a, b, q in spans if a <= line <= b), self.module)
            self.literals.append(Literal("comment", text, line, owner))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd plugins/concordance && ../../.venv/bin/python -m pytest ../../tests/concordance/test_extract_py.py -q`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add plugins/concordance/scripts/extract_py.py tests/concordance/test_extract_py.py
git commit -m "feat(concordance): Python fact extractor (ast + tokenize)"
```

---

### Task 4: Views

**Files:**
- Create: `plugins/concordance/scripts/views.py`
- Test: `tests/concordance/test_views.py`

**Interfaces:**
- Consumes: `gitio.*` (Task 1).
- Produces: `views.SUPPORTED: dict[str, str]`, `views.lang_of(path: str) -> str | None`, `views.blob_sha(data: bytes) -> str`, `views.View` (frozen, `eq=False`) with fields `view_id: str`, `kind: str` (`"wt"` or `"base"`), `root: Path`, `ref: str | None`, `files: dict[str, str]`, and methods `read(paths: list[str]) -> dict[str, bytes]`, `read_extra(path: str) -> bytes | None` (a file not in `files`, e.g. `tsconfig.json`), `text(path: str) -> str`; `views.worktree_view_id(root: Path) -> str`; `views.worktree_view(cwd: Path) -> View`; `views.base_view(cwd: Path, commit: str) -> View`.

- [ ] **Step 1: Write the failing tests**

`tests/concordance/test_views.py`:
```python
import os

from scripts import gitio
from scripts.views import base_view, blob_sha, lang_of, worktree_view, worktree_view_id


def test_lang_of() -> None:
    assert lang_of("a/b.py") == "python"
    assert lang_of("x.tsx") == "typescript"
    assert lang_of("types.d.ts") is None
    assert lang_of("README.md") is None


def test_blob_sha_matches_git(make_repo) -> None:
    repo = make_repo({"a.py": "x = 1\n"})
    assert blob_sha(b"x = 1\n") == repo.git("hash-object", "a.py").strip()


def test_worktree_view_sees_dirty_untracked_and_skips_deleted(make_repo) -> None:
    repo = make_repo({"a.py": "x = 1\n", "b.py": "y = 1\n", "c.py": "z = 1\n", "R.md": "r"})
    repo.write({"a.py": "x = 2\n", "new.py": "n = 1\n", "c.py": None})
    v = worktree_view(repo.root)
    assert set(v.files) == {"a.py", "b.py", "new.py"}
    assert v.files["a.py"] == blob_sha(b"x = 2\n")
    assert v.read(["a.py", "b.py"]) == {"a.py": b"x = 2\n", "b.py": b"y = 1\n"}
    assert v.kind == "wt" and v.ref is None


def test_base_view_reads_from_git_without_checkout(make_repo) -> None:
    repo = make_repo({"a.py": "x = 1\n", "tsconfig.json": "{}"})
    sha = repo.git("rev-parse", "HEAD").strip()
    repo.write({"a.py": "x = 2\n"})
    repo.commit("second")
    v = base_view(repo.root, sha)
    assert v.view_id == f"base-{sha}" and v.ref == sha
    assert v.read(["a.py"]) == {"a.py": b"x = 1\n"}
    assert v.read_extra("tsconfig.json") == b"{}"


def test_view_ids_are_stable_per_worktree_and_distinct_between_them(make_repo) -> None:
    repo = make_repo({"a.py": "x = 1\n"})
    wt = repo.worktree("wt1", "feat")
    assert worktree_view(repo.root).view_id == worktree_view_id(repo.root)
    assert worktree_view(repo.root / ".").view_id == worktree_view(repo.root).view_id
    assert worktree_view(wt.root).view_id != worktree_view(repo.root).view_id


def test_subdirectory_cwd_resolves_to_the_worktree_root(make_repo) -> None:
    repo = make_repo({"pkg/a.py": "x = 1\n"})
    v = worktree_view(repo.root / "pkg")
    assert v.root == gitio.worktree_root(repo.root) and "pkg/a.py" in v.files


def test_symlinks_are_skipped(make_repo) -> None:  # Review Focus 5
    repo = make_repo({"a.py": "x = 1\n"})
    os.symlink("a.py", repo.root / "link.py")
    repo.commit("tracked link")
    os.symlink("a.py", repo.root / "untracked_link.py")
    assert set(worktree_view(repo.root).files) == {"a.py"}
    sha = repo.git("rev-parse", "HEAD").strip()
    assert set(base_view(repo.root, sha).files) == {"a.py"}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd plugins/concordance && ../../.venv/bin/python -m pytest ../../tests/concordance/test_views.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.views'`

- [ ] **Step 3: Implement `views.py`**

```python
"""A view: the file versions one worktree (or one base commit) sees, as path -> blob sha.

Clean tracked files use the index's blob sha; dirty and untracked files are hashed here the
way git hashes a blob, so a view never needs a commit. Base views come straight from git
objects, so the base never has to be checked out.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from scripts import gitio

SUPPORTED = {".py": "python", ".ts": "typescript", ".tsx": "typescript",
             ".mts": "typescript", ".cts": "typescript"}


def lang_of(path: str) -> str | None:
    if path.endswith(".d.ts"):
        return None
    return SUPPORTED.get(PurePosixPath(path).suffix)


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


@dataclass(frozen=True, eq=False)
class View:
    view_id: str
    kind: str  # wt | base
    root: Path
    ref: str | None
    files: dict[str, str]

    def read(self, paths: list[str]) -> dict[str, bytes]:
        if self.kind == "base":
            blobs = gitio.cat_blobs(self.root, [self.files[p] for p in paths])
            return {p: blobs[self.files[p]] for p in paths if self.files[p] in blobs}
        out: dict[str, bytes] = {}
        for p in paths:
            try:
                out[p] = (self.root / p).read_bytes()
            except OSError:
                continue
        return out

    def read_extra(self, path: str) -> bytes | None:
        if self.kind == "base":
            assert self.ref is not None
            return gitio.show_file(self.root, self.ref, path)
        try:
            return (self.root / path).read_bytes()
        except OSError:
            return None

    def text(self, path: str) -> str:
        return self.read([path]).get(path, b"").decode("utf-8", errors="replace")


def worktree_view_id(root: Path) -> str:
    return "wt-" + hashlib.sha1(str(root.resolve()).encode()).hexdigest()[:12]


def worktree_view(cwd: Path) -> View:
    root = gitio.worktree_root(cwd)
    deleted = gitio.deleted_paths(root)
    files = {p: s for p, s in gitio.ls_files_stage(root).items()
             if p not in deleted and lang_of(p)}
    for p in gitio.changed_paths(root):
        if p in deleted or not lang_of(p):
            continue
        full = root / p
        if full.is_symlink() or not full.is_file():
            files.pop(p, None)
            continue
        files[p] = blob_sha(full.read_bytes())
    return View(worktree_view_id(root), "wt", root, None, files)


def base_view(cwd: Path, commit: str) -> View:
    root = gitio.worktree_root(cwd)
    sha = gitio.rev_parse(root, commit)
    files = {p: s for p, s in gitio.ls_tree(root, sha).items() if lang_of(p)}
    return View(f"base-{sha}", "base", root, sha, files)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd plugins/concordance && ../../.venv/bin/python -m pytest ../../tests/concordance/test_views.py -q`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add plugins/concordance/scripts/views.py tests/concordance/test_views.py
git commit -m "feat(concordance): worktree and base views"
```

---

### Task 5: Indexer: hash gate, lock, deadline, GC

**Files:**
- Create: `plugins/concordance/scripts/index.py`, and a stub `plugins/concordance/scripts/extract_ts.py` (replaced by the real bridge in Task 11)
- Test: `tests/concordance/test_index.py`

**Interfaces:**
- Consumes: `Store` (Task 2), `extract_python` (Task 3), `View`, `lang_of` (Task 4), `gitio.live_worktrees` (Task 1).
- Produces: `index.LockTimeout`, `index.view_lock(store_path: Path, view_id: str, wait_s: float, stale_s: float = 300.0)` (context manager), `index.BuildReport(view_id: str, files: int, reused: int, parsed: int = 0, failed: list[tuple[str, str]], skipped: dict[str, str])` (skipped maps path → reason), `index.ensure_view(store: Store, view: View, deadline_s: float = 60.0) -> BuildReport`, `index.GcReport(views_removed: int, facts_removed: int)`, `index.maybe_gc(store: Store, root: Path, now: float | None = None, interval_s: float = 3600.0) -> GcReport | None`.
- Produces (stub, for Task 11 to replace): `extract_ts.DeadlineExceeded`, `extract_ts.unavailable_reason() -> str | None`, `extract_ts.extract_batch(items: list[tuple[str, str, bytes]], timeout_s: float) -> list[FileFacts]`.

- [ ] **Step 1: Write the failing tests**

`tests/concordance/test_index.py`:
```python
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
    with view_lock(tmp_path / "i.db", "wt-x", wait_s=1):
        with pytest.raises(LockTimeout, match="index busy"):
            with view_lock(tmp_path / "i.db", "wt-x", wait_s=0.2):
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd plugins/concordance && ../../.venv/bin/python -m pytest ../../tests/concordance/test_index.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.index'`

- [ ] **Step 3: Write the TS bridge stub**

`plugins/concordance/scripts/extract_ts.py` (Task 11 replaces this file whole):
```python
"""Bridge to the Node TypeScript extractor. Stub until the extractor lands (plan Task 11)."""
from __future__ import annotations

from scripts.facts import FileFacts


class DeadlineExceeded(RuntimeError):
    pass


def unavailable_reason() -> str | None:
    return "TypeScript extractor not built yet"


def extract_batch(items: list[tuple[str, str, bytes]], timeout_s: float) -> list[FileFacts]:
    raise RuntimeError("TypeScript extractor not built yet")
```

- [ ] **Step 4: Implement `index.py`**

```python
"""Build a view's facts: hash-gated (only unseen (path, blob) pairs are parsed), lazy, deadline
capped, and safe to run from several worktrees at once. GC runs lazily, at most hourly.
"""
from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from scripts import extract_ts, gitio
from scripts.extract_py import extract_python
from scripts.store import Store
from scripts.views import View, lang_of

BATCH = 200
BASE_VIEW_TTL_S = 7 * 86400


class LockTimeout(RuntimeError):
    pass


@contextmanager
def view_lock(store_path: Path, view_id: str, wait_s: float,
              stale_s: float = 300.0) -> Iterator[None]:
    lock = store_path.parent / "locks" / f"{view_id}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    end = time.monotonic() + wait_s
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > stale_s:
                    lock.unlink(missing_ok=True)  # a crashed indexer left it
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= end:
                raise LockTimeout(
                    f"index busy: {view_id} is being built by another process "
                    f"(waited {wait_s:.0f}s)") from None
            time.sleep(0.05)
            continue
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        break
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


@dataclass
class BuildReport:
    view_id: str
    files: int
    reused: int
    parsed: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)


def ensure_view(store: Store, view: View, deadline_s: float = 60.0) -> BuildReport:
    start = time.monotonic()
    with view_lock(store.path, view.view_id, wait_s=max(deadline_s, 1.0)):
        store.set_view(view.view_id, view.kind,
                       str(view.root) if view.kind == "wt" else None, view.ref, view.files)
        have = store.has_facts(view.files.items())
        missing = [(p, s) for p, s in view.files.items() if (p, s) not in have]
        report = BuildReport(view.view_id, len(view.files), len(have))
        py = [k for k in missing if lang_of(k[0]) == "python"]
        ts = [k for k in missing if lang_of(k[0]) == "typescript"]
        _index_python(store, view, py, report, start, deadline_s)
        _index_typescript(store, view, ts, report, start, deadline_s)
    if view.kind == "wt":
        maybe_gc(store, view.root)
    return report


def _index_python(store: Store, view: View, items: list[tuple[str, str]], report: BuildReport,
                  start: float, deadline_s: float) -> None:
    for i in range(0, len(items), BATCH):
        if time.monotonic() - start > deadline_s:
            report.skipped.update({p: "deadline" for p, _ in items[i:]})
            return
        batch = items[i : i + BATCH]
        data = view.read([p for p, _ in batch])
        for p, s in batch:
            if p not in data:
                report.skipped[p] = "unreadable"
                continue
            ff = extract_python(p, s, data[p])
            store.put_facts(ff)
            report.parsed += 1
            if not ff.parsed_ok:
                report.failed.append((p, ff.error or "parse failed"))


def _index_typescript(store: Store, view: View, items: list[tuple[str, str]],
                      report: BuildReport, start: float, deadline_s: float) -> None:
    if not items:
        return
    reason = extract_ts.unavailable_reason()
    remaining = deadline_s - (time.monotonic() - start)
    if reason is None and remaining <= 0:
        reason = "deadline"
    if reason is not None:
        report.skipped.update({p: reason for p, _ in items})
        return
    data = view.read([p for p, _ in items])
    batch = [(p, s, data[p]) for p, s in items if p in data]
    try:
        facts = extract_ts.extract_batch(batch, timeout_s=remaining)
    except extract_ts.DeadlineExceeded:
        report.skipped.update({p: "deadline" for p, _ in items})
        return
    except RuntimeError as exc:
        report.skipped.update({p: str(exc) for p, _ in items})
        return
    for ff in facts:
        store.put_facts(ff)
        report.parsed += 1
        if not ff.parsed_ok:
            report.failed.append((ff.path, ff.error or "parse failed"))


@dataclass(frozen=True)
class GcReport:
    views_removed: int
    facts_removed: int


def maybe_gc(store: Store, root: Path, now: float | None = None,
             interval_s: float = 3600.0) -> GcReport | None:
    now = time.time() if now is None else now
    if now - float(store.meta_get("last_gc") or 0) < interval_s:
        return None
    try:
        live = gitio.live_worktrees(root)
    except gitio.GitError:
        return None
    removed = 0
    for v in store.views():
        gone = v.kind == "wt" and v.worktree_path not in live
        expired = v.kind == "base" and now - v.built_at > BASE_VIEW_TTL_S
        if gone or expired:
            store.delete_view(v.view_id)
            removed += 1
    facts = store.delete_orphan_facts()
    store.meta_set("last_gc", str(now))
    return GcReport(removed, facts)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd plugins/concordance && ../../.venv/bin/python -m pytest ../../tests/concordance/test_index.py -q`
Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
git add plugins/concordance/scripts/index.py plugins/concordance/scripts/extract_ts.py tests/concordance/test_index.py
git commit -m "feat(concordance): hash-gated incremental indexer with lock, deadline and GC"
```

---

### Task 6: Resolver (ViewIndex)

**Files:**
- Create: `plugins/concordance/scripts/resolve.py`
- Test: `tests/concordance/test_resolve.py`

**Interfaces:**
- Consumes: `Store.view_symbols`, `Store.view_refs` (Task 2); `View.read_extra` (Task 4); `ensure_view` (Task 5, tests only).
- Produces: `resolve.Resolved(target: str | None, confidence: str, candidates: tuple[str, ...] = ())` with confidence in `exact|inferred|ambiguous|external|unresolved`; `resolve.INIT = {"python": "__init__", "typescript": "constructor"}`; `resolve.last(q: str) -> str`; `resolve.parent(q: str) -> str`; `resolve.lang_of_qualname(q: str) -> str`; `resolve.ViewIndex(store: Store, view: View)` with attributes `.view`, `.symbols: dict[str, list[tuple[str, Symbol]]]`, `.refs: list[tuple[str, Ref]]`, and methods `symbol(q) -> Symbol | None`, `path_of(q) -> str | None`, `is_test(q) -> bool`, `resolve(target: str) -> Resolved`, `canonical(target: str) -> str`, `lookup(name: str) -> Resolved`, `callers(q: str) -> list[tuple[str, Ref, str]]` (path, ref, confidence), `callers_with_class(q: str) -> list[tuple[str, Ref, str]]` (adds call refs to the class when `q` is its `__init__`/`constructor`), `refs_named(name: str) -> list[tuple[str, Ref]]` (refs whose raw target's last component is `name`).

- [ ] **Step 1: Write the failing tests**

`tests/concordance/test_resolve.py`:
```python
from pathlib import Path

import pytest

from scripts.index import ensure_view
from scripts.resolve import Resolved, ViewIndex
from scripts.store import Store
from scripts.views import worktree_view

FILES = {
    "src/pkg/__init__.py": "from .events import DomainEvent\n",
    "src/pkg/events.py": "class DomainEvent:\n    def apply(self):\n        pass\n",
    "src/pkg/svc.py": (
        "from pkg import DomainEvent\n"
        "from pkg.events import DomainEvent as DE\n\n"
        "def _refund_partial(x):\n    return DE()\n\n"
        "def run():\n    DomainEvent().apply()\n    return _refund_partial(1)\n"
    ),
    "services/api/ledger/core.py": "def append_events():\n    pass\n",
    "services/api/ledger/use.py": (
        "from ledger.core import append_events\n\ndef go():\n    append_events()\n"),
    "tests/test_svc.py": "from pkg.svc import run\n\ndef test_run():\n    run()\n",
}


@pytest.fixture
def vi(tmp_path: Path, make_repo) -> ViewIndex:
    repo = make_repo(FILES)
    st = Store(tmp_path / "i.db")
    view = worktree_view(repo.root)
    ensure_view(st, view)
    return ViewIndex(st, view)


def callers_of(vi: ViewIndex, q: str) -> set[tuple[str, str]]:
    return {(ref.src, conf) for _, ref, conf in vi.callers(q)}


def test_reexport_alias_resolves(vi: ViewIndex) -> None:
    assert vi.resolve("pkg.DomainEvent") == Resolved("pkg.events.DomainEvent", "exact")


def test_private_name_and_aliased_import(vi: ViewIndex) -> None:
    assert ("pkg.svc.run", "exact") in callers_of(vi, "pkg.svc._refund_partial")
    assert ("pkg.svc._refund_partial", "exact") in callers_of(vi, "pkg.events.DomainEvent")


def test_package_root_found_by_suffix(vi: ViewIndex) -> None:
    r = vi.resolve("ledger.core.append_events")
    assert r == Resolved("services.api.ledger.core.append_events", "exact")
    assert vi.canonical("ledger.core.gone") == "services.api.ledger.core.gone"


def test_external_and_unresolved(vi: ViewIndex) -> None:
    assert vi.resolve("json.dumps").confidence == "external"
    assert vi.resolve("pkg.svc.nope").confidence == "unresolved"


def test_method_on_unknown_receiver_is_inferred(vi: ViewIndex) -> None:
    assert ("pkg.svc.run", "inferred") in callers_of(vi, "pkg.events.DomainEvent.apply")


def test_test_symbols_are_marked(vi: ViewIndex) -> None:
    assert vi.is_test("tests.test_svc.test_run") and not vi.is_test("pkg.svc.run")
    assert vi.path_of("pkg.svc.run") == "src/pkg/svc.py"


def test_lookup_suffix_and_did_you_mean(vi: ViewIndex) -> None:
    assert vi.lookup("svc.run").target == "pkg.svc.run"
    miss = vi.lookup("_refund_partail")
    assert miss.target is None and "pkg.svc._refund_partial" in miss.candidates


def test_ambiguous_method_name(tmp_path: Path, make_repo) -> None:
    repo = make_repo({
        "a.py": "class A:\n    def save(self):\n        pass\n",
        "b.py": "class B:\n    def save(self):\n        pass\n",
        "c.py": "def go(x):\n    x.save()\n",
    })
    st = Store(tmp_path / "i.db")
    view = worktree_view(repo.root)
    ensure_view(st, view)
    vi = ViewIndex(st, view)
    r = vi.resolve("?.save")
    assert r.confidence == "ambiguous" and set(r.candidates) == {"a.A.save", "b.B.save"}
    assert ("c.go", "ambiguous") in callers_of(vi, "a.A.save")


def test_class_callers_count_for_init(tmp_path: Path, make_repo) -> None:
    repo = make_repo({"m.py": "class K:\n    def __init__(self, a):\n        pass\n\n"
                              "def mk():\n    return K(1)\n"})
    st = Store(tmp_path / "i.db")
    view = worktree_view(repo.root)
    ensure_view(st, view)
    vi = ViewIndex(st, view)
    assert {r.src for _, r, _ in vi.callers_with_class("m.K.__init__")} == {"m.mk"}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd plugins/concordance && ../../.venv/bin/python -m pytest ../../tests/concordance/test_resolve.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.resolve'`

- [ ] **Step 3: Implement `resolve.py`**

```python
"""Query-time name resolution within one view.

Facts store raw targets; resolving them against the view's own symbol table means two
worktrees with different code never contaminate each other's answers. Every answer carries a
confidence, and a miss is "ambiguous" or "unresolved" with candidates, never silence.
"""
from __future__ import annotations

import difflib
import json
import posixpath
import re
from collections import defaultdict
from dataclasses import dataclass

from scripts.facts import Ref, Symbol
from scripts.store import Store
from scripts.views import View

INIT = {"python": "__init__", "typescript": "constructor"}
_MAX_ALIAS_HOPS = 5
_CALLABLE = ("function", "method")


@dataclass(frozen=True)
class Resolved:
    target: str | None
    confidence: str  # exact | inferred | ambiguous | external | unresolved
    candidates: tuple[str, ...] = ()


def last(q: str) -> str:
    return q.rsplit(".", 1)[-1]


def parent(q: str) -> str:
    return q.rsplit(".", 1)[0]


def lang_of_qualname(q: str) -> str:
    return "typescript" if q.startswith("ts:") else "python"


def _load_ts_paths(view: View) -> tuple[str, list[tuple[str, str]]]:
    """(baseUrl, [(pattern, first target)]) from the view's root tsconfig.json, if any."""
    raw = view.read_extra("tsconfig.json")
    if raw is None:
        return ".", []
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"(?m)^\s*//.*$", "", text)
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    try:
        opts = json.loads(text).get("compilerOptions", {})
    except (json.JSONDecodeError, AttributeError):
        return ".", []
    base = str(opts.get("baseUrl", "."))
    pairs = [(str(pat), str(targets[0])) for pat, targets in (opts.get("paths") or {}).items()
             if isinstance(targets, list) and targets]
    return base, pairs


class ViewIndex:
    def __init__(self, store: Store, view: View) -> None:
        self.view = view
        self.symbols: dict[str, list[tuple[str, Symbol]]] = defaultdict(list)
        for path, sym in store.view_symbols(view.view_id):
            self.symbols[sym.qualname].append((path, sym))
        self.refs: list[tuple[str, Ref]] = store.view_refs(view.view_id)
        self._by_last: dict[str, list[str]] = defaultdict(list)
        self._modules_by_suffix: dict[str, set[str]] = defaultdict(set)
        for q, entries in self.symbols.items():
            kind = entries[0][1].kind
            if kind == "module":
                if not q.startswith("ts:"):
                    parts = q.split(".")
                    for i in range(len(parts)):
                        self._modules_by_suffix[".".join(parts[i:])].add(q)
            elif kind != "alias":
                self._by_last[last(q)].append(q)
        self._ts_base, self._ts_paths = _load_ts_paths(view)
        self._memo: dict[str, Resolved] = {}
        self._callers: dict[str, list[tuple[str, Ref, str]]] | None = None
        self._refs_by_last: dict[str, list[tuple[str, Ref]]] | None = None

    # -- symbol table ------------------------------------------------------------------------

    def symbol(self, q: str) -> Symbol | None:
        entries = self.symbols.get(q)
        return entries[0][1] if entries else None

    def path_of(self, q: str) -> str | None:
        entries = self.symbols.get(q)
        return entries[0][0] if entries else None

    def is_test(self, q: str) -> bool:
        sym = self.symbol(q)
        return bool(sym and sym.is_test)

    # -- resolution --------------------------------------------------------------------------

    def resolve(self, target: str) -> Resolved:
        hit = self._memo.get(target)
        if hit is None:
            hit = self._memo[target] = self._resolve(target, 0)
        return hit

    def _exact(self, q: str, depth: int) -> Resolved | None:
        sym = self.symbol(q)
        if sym is None:
            return None
        if sym.kind == "alias" and sym.alias_of:
            return self._resolve(sym.alias_of, depth + 1)
        return Resolved(q, "exact")

    def _resolve(self, target: str, depth: int) -> Resolved:
        if depth > _MAX_ALIAS_HOPS:
            return Resolved(None, "unresolved")
        if target.startswith("?."):
            name = target[2:]
            cands = sorted(q for q in self._by_last.get(name, [])
                           if (s := self.symbol(q)) is not None and s.kind in _CALLABLE)
            if len(cands) == 1:
                return Resolved(cands[0], "inferred")
            if cands:
                return Resolved(None, "ambiguous", tuple(cands[:5]))
            return Resolved(None, "unresolved")
        if target.startswith("ts-bare:"):
            spec, _, member = target[len("ts-bare:"):].partition("|")
            mapped = self._map_ts_bare(spec)
            if mapped is None:
                return Resolved(None, "external")
            return self._resolve(f"{mapped}.{member}" if member else mapped, depth + 1)
        direct = self._exact(target, depth)
        if direct is not None:
            return direct
        if target.startswith("ts:"):
            return self._resolve_ts_index(target, depth)
        full = self._python_full(target)
        if isinstance(full, Resolved):
            return full
        if full is None:
            return Resolved(None, "external")
        if full == target:
            return Resolved(None, "unresolved")
        return self._exact(full, depth) or Resolved(None, "unresolved")

    def _python_full(self, target: str) -> str | Resolved | None:
        """Map an absolute import name onto a module in this view by dotted-path suffix."""
        parts = target.split(".")
        for i in range(len(parts), 0, -1):
            mods = self._modules_by_suffix.get(".".join(parts[:i]))
            if not mods:
                continue
            rest = parts[i:]
            if len(mods) > 1:
                cands = sorted(".".join([m, *rest]) for m in mods)
                return Resolved(None, "ambiguous", tuple(cands[:5]))
            return ".".join([next(iter(mods)), *rest])
        return None

    def _resolve_ts_index(self, target: str, depth: int) -> Resolved:
        tail_start = target.rfind("/") + 1
        for i in [m.start() for m in re.finditer(r"\.", target[tail_start:])]:
            cut = tail_start + i
            alt = f"{target[:cut]}/index{target[cut:]}"
            hit = self._exact(alt, depth)
            if hit is not None:
                return hit
        return Resolved(None, "unresolved")

    def _map_ts_bare(self, spec: str) -> str | None:
        for pattern, dest in self._ts_paths:
            if "*" in pattern:
                prefix, _, suffix = pattern.partition("*")
                if spec.startswith(prefix) and spec.endswith(suffix):
                    middle = spec[len(prefix): len(spec) - len(suffix) if suffix else None]
                    mapped = dest.replace("*", middle)
                else:
                    continue
            elif spec == pattern:
                mapped = dest
            else:
                continue
            norm = posixpath.normpath(posixpath.join(self._ts_base, mapped))
            return "ts:" + re.sub(r"\.([cm]?[jt]sx?)$", "", norm)
        return None

    def canonical(self, target: str) -> str:
        """The target with its module mapped into this view, without requiring the member."""
        if target.startswith(("?.", "ts:", "ts-bare:")):
            return target
        full = self._python_full(target)
        return full if isinstance(full, str) else target

    def lookup(self, name: str) -> Resolved:
        if self.symbol(name) is not None:
            return self._exact(name, 0) or Resolved(name, "exact")
        r = self.resolve(name)
        if r.target:
            return r
        suffix = sorted(q for q in self.symbols
                        if q.endswith("." + name) and (s := self.symbol(q)) is not None
                        and s.kind != "alias")
        if len(suffix) == 1:
            return Resolved(suffix[0], "inferred")
        if suffix:
            return Resolved(None, "ambiguous", tuple(suffix[:8]))
        close = difflib.get_close_matches(last(name), list(self._by_last), n=5, cutoff=0.6)
        cands = tuple(q for n in close for q in sorted(self._by_last[n]))[:8]
        return Resolved(None, "unresolved", cands)

    # -- reverse edges -----------------------------------------------------------------------

    def callers(self, q: str) -> list[tuple[str, Ref, str]]:
        if self._callers is None:
            idx: dict[str, list[tuple[str, Ref, str]]] = defaultdict(list)
            for path, ref in self.refs:
                r = self.resolve(ref.target)
                if r.target:
                    idx[r.target].append((path, ref, r.confidence))
                elif r.confidence == "ambiguous":
                    for cand in r.candidates:
                        idx[cand].append((path, ref, "ambiguous"))
            self._callers = idx
        return list(self._callers.get(q, []))

    def callers_with_class(self, q: str) -> list[tuple[str, Ref, str]]:
        rows = self.callers(q)
        if last(q) == INIT[lang_of_qualname(q)]:
            rows += [row for row in self.callers(parent(q)) if row[1].kind == "call"]
        return rows

    def refs_named(self, name: str) -> list[tuple[str, Ref]]:
        if self._refs_by_last is None:
            idx: dict[str, list[tuple[str, Ref]]] = defaultdict(list)
            for path, ref in self.refs:
                idx[last(ref.target.split("|")[-1])].append((path, ref))
            self._refs_by_last = idx
        return list(self._refs_by_last.get(name, []))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd plugins/concordance && ../../.venv/bin/python -m pytest ../../tests/concordance/test_resolve.py -q`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add plugins/concordance/scripts/resolve.py tests/concordance/test_resolve.py
git commit -m "feat(concordance): query-time resolver with confidence and did-you-mean"
```

---

### Task 7: Classifier and diff analysis

**Files:**
- Create: `plugins/concordance/scripts/classify.py`, `plugins/concordance/scripts/diff.py`
- Test: `tests/concordance/test_classify.py`, `tests/concordance/test_diff.py`

**Interfaces:**
- Consumes: `Store.file_facts` (Task 2), `View`, `lang_of` (Task 4), `ViewIndex.symbols` (Task 6).
- Produces (`classify.py`): `fingerprint(source: str, line: int) -> str | None`, `behaviour_changed(base_src: str, base_line: int, head_src: str, head_line: int) -> bool`, `reordered(base_src: str, base_line: int, head_src: str, head_line: int) -> bool`.
- Produces (`diff.py`): frozen dataclasses `Touched(qualname, path, kind, line, behaviour_changed: bool, is_new: bool)`, `RemovedItem(kind, qualname, name, path, line, text)` with kind in `symbol|param|guard|decorator`, `SignatureChange(qualname, path, line, old: Signature, new: Signature)`, `LiteralChange(text, change, path, line)` with change in `removed|added`, `Reorder(qualname, path, line)`, `RemovedComment(path, line, text, symbol)`; mutable `DiffResult(changed_files: list[str], touched, removed, signatures, literals, reorders, removed_comments)`; `analyse(store: Store, base: View, head: View, head_vi: ViewIndex) -> DiffResult`.

- [ ] **Step 1: Write the failing classifier tests**

`tests/concordance/test_classify.py`:
```python
from scripts.classify import behaviour_changed, reordered

BASE = 'def f(a, b):\n    """Doc."""\n    total = a + b\n    return total\n'


def test_local_rename_and_docstring_are_a_refactor() -> None:
    head = "def f(a, b):\n    s = a + b\n    return s\n"
    assert not behaviour_changed(BASE, 1, head, 1)


def test_changed_operator_is_behaviour() -> None:
    assert behaviour_changed(BASE, 1, "def f(a, b):\n    total = a - b\n    return total\n", 1)


def test_parameter_rename_is_behaviour() -> None:
    assert behaviour_changed(BASE, 1, "def f(a, c):\n    total = a + c\n    return total\n", 1)


def test_reordered_statements() -> None:
    base = "def g():\n    a()\n    b()\n"
    head = "def g():\n    b()\n    a()\n"
    assert reordered(base, 1, head, 1) and behaviour_changed(base, 1, head, 1)
    assert not reordered(base, 1, base, 1)


def test_missing_definition_counts_as_changed() -> None:
    assert behaviour_changed(BASE, 99, BASE, 1)
```

- [ ] **Step 2: Write the failing diff tests**

`tests/concordance/test_diff.py`:
```python
from pathlib import Path

from scripts.diff import DiffResult, analyse
from scripts.index import ensure_view
from scripts.resolve import ViewIndex
from scripts.store import Store
from scripts.views import base_view, worktree_view


def run(tmp_path: Path, make_repo, base: dict[str, str], edits: dict[str, str | None],
        name: str = "repo") -> DiffResult:
    repo = make_repo(base, name=name)
    sha = repo.git("rev-parse", "HEAD").strip()
    repo.write(edits)  # left uncommitted on purpose: the head view must see dirty edits
    st = Store(tmp_path / f"{name}.db")
    head, bview = worktree_view(repo.root), base_view(repo.root, sha)
    ensure_view(st, head)
    ensure_view(st, bview)
    return analyse(st, bview, head, ViewIndex(st, head))


def removed(d: DiffResult) -> set[tuple[str, str, str]]:
    return {(r.kind, r.qualname, r.name) for r in d.removed}


def test_removed_symbol(tmp_path: Path, make_repo) -> None:
    d = run(tmp_path, make_repo,
            {"m.py": "def keep():\n    gone()\n\n\ndef gone():\n    pass\n"},
            {"m.py": "def keep():\n    gone()\n"})
    assert ("symbol", "m.gone", "gone") in removed(d)
    assert d.changed_files == ["m.py"]


def test_moving_to_another_module_is_a_removal_but_editing_is_not(tmp_path: Path,
                                                                   make_repo) -> None:
    d = run(tmp_path, make_repo,
            {"a.py": "def f():\n    pass\n", "b.py": "x = 1\n"},
            {"a.py": "y = 2\n", "b.py": "x = 1\n\n\ndef f():\n    pass\n"})
    assert ("symbol", "a.f", "f") in removed(d)  # importers of a.f break; b.f is a new qualname
    d2 = run(tmp_path, make_repo,
             {"pkg/a.py": "def f():\n    pass\n"},
             {"pkg/a.py": "def f():\n    return 1\n"}, name="two")
    assert not any(r.kind == "symbol" for r in d2.removed)


def test_removed_param_and_signature_change(tmp_path: Path, make_repo) -> None:
    d = run(tmp_path, make_repo,
            {"m.py": "def f(a, flush=True):\n    return a\n"},
            {"m.py": "def f(a):\n    return a\n"})
    assert ("param", "m.f", "flush") in removed(d)
    assert [s.qualname for s in d.signatures] == ["m.f"]


def test_removed_guard_and_decorator(tmp_path: Path, make_repo) -> None:
    d = run(tmp_path, make_repo,
            {"m.py": "from functools import cache\n\n\n@cache\ndef f(x):\n"
                     "    if x is None:\n        raise ValueError('x')\n    return x\n"},
            {"m.py": "from functools import cache\n\n\ndef f(x):\n    return x\n"})
    kinds = {(r.kind, r.name, r.text) for r in d.removed}
    assert ("guard", "if", "x is None") in kinds
    assert ("guard", "raise", "ValueError('x')") in kinds
    assert ("decorator", "functools.cache", "functools.cache") in kinds


def test_touched_classification(tmp_path: Path, make_repo) -> None:
    d = run(tmp_path, make_repo,
            {"m.py": "def a(x):\n    y = x + 1\n    return y\n\n\ndef b(x):\n    return x\n"},
            {"m.py": "def a(x):\n    z = x + 1\n    return z\n\n\ndef b(x):\n    return -x\n\n\n"
                     "def c():\n    pass\n"})
    by = {t.qualname: t for t in d.touched}
    assert not by["m.a"].behaviour_changed
    assert by["m.b"].behaviour_changed and not by["m.b"].is_new
    assert by["m.c"].is_new


def test_literals_comments_and_reorders(tmp_path: Path, make_repo) -> None:
    d = run(tmp_path, make_repo,
            {"m.py": "SQL = 'DELETE FROM a'\n\n\ndef f():\n    # order matters\n    one()\n    two()\n"},
            {"m.py": "SQL = 'DELETE FROM b'\n\n\ndef f():\n    two()\n    one()\n"})
    assert {(x.change, x.text) for x in d.literals} == {
        ("removed", "DELETE FROM a"), ("added", "DELETE FROM b")}
    assert [(c.text, c.symbol) for c in d.removed_comments] == [("order matters", "m.f")]
    assert [r.qualname for r in d.reorders] == ["m.f"]
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd plugins/concordance && ../../.venv/bin/python -m pytest ../../tests/concordance/test_classify.py ../../tests/concordance/test_diff.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.classify'`

- [ ] **Step 4: Implement `classify.py`**

```python
"""Is a Python change a pure refactor? Compare normalised syntax trees of one definition.

Normalised away: formatting, comments, the docstring, the definition's own name and the names
of local variables (not parameters: renaming a parameter changes the call contract).
"""
from __future__ import annotations

import ast
import copy

_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _find(source: str, line: int) -> ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | None:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, _DEFS) and node.lineno == line:
            return node
    return None


def _body(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> list[ast.stmt]:
    body = node.body
    if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    return body or [ast.Pass()]


class _Renamer(ast.NodeTransformer):
    def __init__(self, names: dict[str, str]) -> None:
        self.names = names

    def visit_Name(self, node: ast.Name) -> ast.Name:
        node.id = self.names.get(node.id, node.id)
        return node


def fingerprint(source: str, line: int) -> str | None:
    found = _find(source, line)
    if found is None:
        return None
    node = copy.deepcopy(found)
    node.body = _body(node)
    node.name = "_"
    if not isinstance(node, ast.ClassDef):
        params = {a.arg for a in ast.walk(node.args) if isinstance(a, ast.arg)}
        order: list[str] = []
        for n in ast.walk(node):
            if (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
                    and n.id not in params and n.id not in order):
                order.append(n.id)
        node = _Renamer({name: f"_v{i}" for i, name in enumerate(order)}).visit(node)
    return ast.dump(node, include_attributes=False)


def behaviour_changed(base_src: str, base_line: int, head_src: str, head_line: int) -> bool:
    a = fingerprint(base_src, base_line)
    b = fingerprint(head_src, head_line)
    return a is None or b is None or a != b


def reordered(base_src: str, base_line: int, head_src: str, head_line: int) -> bool:
    a, b = _find(base_src, base_line), _find(head_src, head_line)
    if a is None or b is None:
        return False
    sa = [ast.dump(s, include_attributes=False) for s in _body(a)]
    sb = [ast.dump(s, include_attributes=False) for s in _body(b)]
    return sa != sb and sorted(sa) == sorted(sb)
```

- [ ] **Step 5: Implement `diff.py`**

```python
"""Base vs head, per changed file: touched symbols, removed items, signature changes, and the
things an index cannot judge (changed literals, reordered statements, removed comments).
"""
from __future__ import annotations

import difflib
from collections import Counter
from dataclasses import dataclass, field

from scripts import classify
from scripts.facts import FileFacts, Signature, Symbol
from scripts.resolve import ViewIndex, last
from scripts.store import Store
from scripts.views import View, lang_of

_NOT_CODE = ("module", "alias", "type")


@dataclass(frozen=True)
class Touched:
    qualname: str
    path: str
    kind: str
    line: int
    behaviour_changed: bool
    is_new: bool


@dataclass(frozen=True)
class RemovedItem:
    kind: str  # symbol | param | guard | decorator
    qualname: str
    name: str
    path: str
    line: int
    text: str


@dataclass(frozen=True)
class SignatureChange:
    qualname: str
    path: str
    line: int
    old: Signature
    new: Signature


@dataclass(frozen=True)
class LiteralChange:
    text: str
    change: str  # removed | added
    path: str
    line: int


@dataclass(frozen=True)
class Reorder:
    qualname: str
    path: str
    line: int


@dataclass(frozen=True)
class RemovedComment:
    path: str
    line: int
    text: str
    symbol: str


@dataclass
class DiffResult:
    changed_files: list[str]
    touched: list[Touched] = field(default_factory=list)
    removed: list[RemovedItem] = field(default_factory=list)
    signatures: list[SignatureChange] = field(default_factory=list)
    literals: list[LiteralChange] = field(default_factory=list)
    reorders: list[Reorder] = field(default_factory=list)
    removed_comments: list[RemovedComment] = field(default_factory=list)


def _changed_lines(base_text: str, head_text: str) -> tuple[set[int], set[int]]:
    a, b = base_text.splitlines(), head_text.splitlines()
    base_lines: set[int] = set()
    head_lines: set[int] = set()
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        base_lines.update(range(i1 + 1, i2 + 1))
        if j2 > j1:
            head_lines.update(range(j1 + 1, j2 + 1))
        else:
            head_lines.add(max(j1, 1))  # a pure deletion touches the line before the gap
    return base_lines, head_lines


def _innermost(symbols: list[Symbol], lines: set[int]) -> list[Symbol]:
    claimed: set[int] = set()
    out: list[Symbol] = []
    for s in sorted(symbols, key=lambda s: s.line_end - s.line_start):
        mine = {n for n in lines if s.line_start <= n <= s.line_end} - claimed
        if mine:
            out.append(s)
            claimed |= mine
    return sorted(out, key=lambda s: s.line_start)


def _code_symbols(ff: FileFacts | None) -> dict[str, Symbol]:
    if ff is None or not ff.parsed_ok:
        return {}
    return {s.qualname: s for s in ff.symbols if s.kind not in _NOT_CODE}


def _norm(text: str) -> str:
    return "".join(text.split())


def analyse(store: Store, base: View, head: View, head_vi: ViewIndex) -> DiffResult:
    paths = sorted(p for p in set(base.files) | set(head.files)
                   if base.files.get(p) != head.files.get(p))
    base_src = {p: d.decode("utf-8", errors="replace")
                for p, d in base.read([p for p in paths if p in base.files]).items()}
    head_src = {p: d.decode("utf-8", errors="replace")
                for p, d in head.read([p for p in paths if p in head.files]).items()}
    result = DiffResult(changed_files=paths)
    for p in paths:
        bff = store.file_facts(p, base.files[p]) if p in base.files else None
        hff = store.file_facts(p, head.files[p]) if p in head.files else None
        b_text, h_text = base_src.get(p, ""), head_src.get(p, "")
        _, h_lines = _changed_lines(b_text, h_text)
        b_syms, h_syms = _code_symbols(bff), _code_symbols(hff)
        _touched(result, p, b_text, h_text, b_syms, h_syms, h_lines)
        for q, s in b_syms.items():
            if q not in head_vi.symbols:
                result.removed.append(RemovedItem("symbol", q, last(q), p, s.line_start, ""))
        _signatures(result, p, b_syms, h_syms)
        if bff is not None and hff is not None and bff.parsed_ok and hff.parsed_ok:
            _guards_and_decorators(result, p, bff, hff, h_syms)
            _literals_and_comments(result, p, bff, hff, h_syms)
    return result


def _touched(result: DiffResult, p: str, b_text: str, h_text: str, b_syms: dict[str, Symbol],
             h_syms: dict[str, Symbol], h_lines: set[int]) -> None:
    is_python = lang_of(p) == "python"
    for s in _innermost(list(h_syms.values()), h_lines):
        old = b_syms.get(s.qualname)
        if old is None:
            changed, new = True, True
        elif is_python:
            changed = classify.behaviour_changed(b_text, old.line_start, h_text, s.line_start)
            new = False
            if classify.reordered(b_text, old.line_start, h_text, s.line_start):
                result.reorders.append(Reorder(s.qualname, p, s.line_start))
        else:
            changed, new = True, False  # no TS classifier: assume behaviour changed
        result.touched.append(Touched(s.qualname, p, s.kind, s.line_start, changed, new))


def _signatures(result: DiffResult, p: str, b_syms: dict[str, Symbol],
                h_syms: dict[str, Symbol]) -> None:
    for q, old in b_syms.items():
        new = h_syms.get(q)
        if new is None or old.signature is None or new.signature is None:
            continue
        if old.signature != new.signature:
            result.signatures.append(SignatureChange(q, p, new.line_start,
                                                     old.signature, new.signature))
        kept = {x.name for x in new.signature}
        for param in old.signature:
            if param.name not in kept:
                result.removed.append(RemovedItem("param", q, param.name, p, old.line_start, ""))


def _guards_and_decorators(result: DiffResult, p: str, bff: FileFacts, hff: FileFacts,
                           h_syms: dict[str, Symbol]) -> None:
    head_guards = {(g.symbol, g.kind, _norm(g.text)) for g in hff.guards}
    for g in bff.guards:
        if g.symbol in h_syms and (g.symbol, g.kind, _norm(g.text)) not in head_guards:
            result.removed.append(RemovedItem("guard", g.symbol, g.kind, p, g.line, g.text))
    head_decs = {(r.src, r.target) for r in hff.refs if r.kind == "decorator"}
    for r in bff.refs:
        if r.kind == "decorator" and r.src in h_syms and (r.src, r.target) not in head_decs:
            result.removed.append(RemovedItem("decorator", r.src, r.target, p, r.line, r.target))


def _literals_and_comments(result: DiffResult, p: str, bff: FileFacts, hff: FileFacts,
                           h_syms: dict[str, Symbol]) -> None:
    def strings(ff: FileFacts) -> Counter[str]:
        return Counter(x.text for x in ff.literals if x.kind == "string")

    b_str, h_str = strings(bff), strings(hff)
    first_line = {}
    for ff in (hff, bff):
        for x in ff.literals:
            if x.kind == "string":
                first_line.setdefault((ff is hff, x.text), x.line)
    for text in sorted((b_str - h_str).keys()):
        result.literals.append(LiteralChange(text, "removed", p, first_line[(False, text)]))
    for text in sorted((h_str - b_str).keys()):
        result.literals.append(LiteralChange(text, "added", p, first_line[(True, text)]))
    head_comments = {x.text for x in hff.literals if x.kind == "comment"}
    module = next((s.qualname for s in hff.symbols if s.kind == "module"), None)
    for x in bff.literals:
        if (x.kind == "comment" and x.text not in head_comments
                and (x.symbol in h_syms or x.symbol == module)):
            result.removed_comments.append(RemovedComment(p, x.line, x.text, x.symbol))
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd plugins/concordance && ../../.venv/bin/python -m pytest ../../tests/concordance/test_classify.py ../../tests/concordance/test_diff.py -q`
Expected: 11 passed

- [ ] **Step 7: Commit**

```bash
git add plugins/concordance/scripts/classify.py plugins/concordance/scripts/diff.py tests/concordance/test_classify.py tests/concordance/test_diff.py
git commit -m "feat(concordance): pure-refactor classifier and base/head diff analysis"
```

---

### Task 8: Queries

**Files:**
- Create: `plugins/concordance/scripts/query.py`
- Test: `tests/concordance/test_query.py`

**Interfaces:**
- Consumes: `ViewIndex` (Task 6), `RemovedItem`, `SignatureChange`, `LiteralChange`, `Touched` (Task 7), `Store.literal_occurrences` (Task 2), `View.text` (Task 4).
- Produces: `Hit(path, line, symbol, confidence, note, snippet="")`; `Snippets(view: View)` with `around(path, line, ctx=0) -> str`; `TestHit(qualname, path, line, hops)`; `ContractHit(item: RemovedItem, hit: Hit)`; `DriftHit(change: SignatureChange, hit: Hit, verdict: str, reason: str)` with verdict `error|undecided`; `LiteralHit(change: LiteralChange, elsewhere: list[tuple[str, int]])`; functions `callers(vi, q, snippets) -> list[Hit]`, `guarding_tests(vi, q, hops=2) -> list[TestHit]`, `removed_contract(vi, items, snippets) -> list[ContractHit]`, `check_call(shape: CallShape, sig: Signature, bound: bool) -> tuple[str, str] | None`, `sig_drift(vi, changes, snippets) -> list[DriftHit]`, `untested_changes(vi, touched: list[Touched]) -> list[Touched]`, `literal_hits(store, view_id, changes) -> list[LiteralHit]`.

- [ ] **Step 1: Write the failing tests**

`tests/concordance/test_query.py`:
```python
from pathlib import Path

import pytest

from scripts.diff import analyse
from scripts.facts import CallShape, Param
from scripts.index import ensure_view
from scripts.query import (
    Snippets, callers, check_call, guarding_tests, literal_hits, removed_contract, sig_drift,
    untested_changes,
)
from scripts.resolve import ViewIndex
from scripts.store import Store
from scripts.views import base_view, worktree_view

BASE = {
    "app/svc.py": (
        "def refund(loan, amount, *, partial=False):\n"
        "    if amount <= 0:\n"
        "        raise ValueError('amount')\n"
        "    return amount\n\n\n"
        "def old_helper():\n    return 1\n"
    ),
    "app/api.py": (
        "from app.svc import refund, old_helper\n\n\n"
        "def handle(loan):\n    old_helper()\n    return refund(loan, 5, partial=True)\n"
    ),
    "tests/test_svc.py": (
        "import pytest\nfrom app.svc import refund\nfrom app.api import handle\n\n\n"
        "def test_rejects_zero():\n    with pytest.raises(ValueError):\n        refund(None, 0)\n\n\n"
        "def test_handle():\n    handle(None)\n"
    ),
    "app/sql.py": "Q = 'DELETE FROM scenario_events'\n",
    "app/other.py": "R = 'DELETE FROM scenario_events'\n",
}
HEAD = {
    "app/svc.py": "def refund(loan, amount):\n    return amount\n",
    "app/sql.py": "Q = 'DELETE FROM events'\n",
}


@pytest.fixture
def world(tmp_path: Path, make_repo):
    repo = make_repo(BASE)
    sha = repo.git("rev-parse", "HEAD").strip()
    repo.write(dict(HEAD))
    st = Store(tmp_path / "i.db")
    head, bview = worktree_view(repo.root), base_view(repo.root, sha)
    ensure_view(st, head)
    ensure_view(st, bview)
    vi = ViewIndex(st, head)
    return st, head, vi, analyse(st, bview, head, vi), Snippets(head)


def test_check_call_verdicts() -> None:
    sig = (Param("self", "pos", False), Param("a", "pos", False), Param("b", "kwonly", True))
    assert check_call(CallShape(1, (), False, False), sig, bound=True) is None
    assert check_call(CallShape(2, (), False, False), sig, bound=True)[0] == "error"
    assert "unknown keyword" in check_call(CallShape(1, ("c",), False, False), sig, True)[1]
    assert "missing required" in check_call(CallShape(0, (), False, False), sig, True)[1]
    assert check_call(CallShape(0, (), True, False), sig, True)[0] == "undecided"
    varkw = (Param("a", "pos", False), Param("kw", "varkw", True))
    assert check_call(CallShape(1, ("anything",), False, False), varkw, bound=False) is None


def test_callers_and_guarding_tests(world) -> None:
    _, _, vi, _, snips = world
    hits = callers(vi, "app.svc.refund", snips)
    assert [h.symbol for h in hits][:1] == ["app.api.handle"]  # non-test callers first
    assert "refund(loan, 5, partial=True)" in hits[0].snippet
    tests = {(t.qualname, t.hops) for t in guarding_tests(vi, "app.svc.refund")}
    assert ("tests.test_svc.test_rejects_zero", 1) in tests
    assert ("tests.test_svc.test_handle", 2) in tests


def test_removed_contract_hits(world) -> None:
    _, _, vi, d, snips = world
    hits = removed_contract(vi, d.removed, snips)
    found = {(h.item.kind, h.item.name, h.hit.symbol) for h in hits}
    assert ("symbol", "old_helper", "app.api.handle") in found
    assert ("param", "partial", "app.api.handle") in found
    assert ("guard", "if", "tests.test_svc.test_rejects_zero") in found
    param_hit = next(h for h in hits if h.item.kind == "param")
    assert param_hit.hit.confidence == "exact" and "partial=True" in param_hit.hit.snippet


def test_sig_drift_flags_the_stale_call_site(world) -> None:
    _, _, vi, d, snips = world
    drift = sig_drift(vi, d.signatures, snips)
    errors = {(x.hit.symbol, x.verdict) for x in drift}
    assert ("app.api.handle", "error") in errors
    assert any("unknown keyword(s): partial" in x.reason for x in drift)


def test_untested_changes_only_for_behaviour_changes(tmp_path: Path, make_repo) -> None:
    repo = make_repo({"m.py": "def f(x):\n    return x\n\n\ndef g(x):\n    return x\n",
                      "tests/test_m.py": "from m import f\n\n\ndef test_f():\n    f(1)\n"})
    sha = repo.git("rev-parse", "HEAD").strip()
    repo.write({"m.py": "def f(x):\n    return -x\n\n\ndef g(x):\n    return -x\n"})
    st = Store(tmp_path / "i.db")
    head, bview = worktree_view(repo.root), base_view(repo.root, sha)
    ensure_view(st, head)
    ensure_view(st, bview)
    vi = ViewIndex(st, head)
    d = analyse(st, bview, head, vi)
    assert [t.qualname for t in untested_changes(vi, d.touched)] == ["m.g"]


def test_literal_hits_find_other_occurrences(world) -> None:
    st, head, _, d, _ = world
    hits = {(h.change.change, h.change.text): h.elsewhere for h in literal_hits(st, head.view_id, d.literals)}
    assert hits[("removed", "DELETE FROM scenario_events")] == [("app/other.py", 1)]
    assert hits[("added", "DELETE FROM events")] == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd plugins/concordance && ../../.venv/bin/python -m pytest ../../tests/concordance/test_query.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.query'`

- [ ] **Step 3: Implement `query.py`**

```python
"""Deterministic review queries. Each returns hits with a line and a code snippet, so the agent
judges meaning without opening files; two of them (signature drift, test gaps) return verdicts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from scripts.diff import LiteralChange, RemovedItem, SignatureChange, Touched
from scripts.facts import CallShape, Signature
from scripts.resolve import ViewIndex, last
from scripts.store import Store
from scripts.views import View

_CONF_RANK = {"exact": 0, "inferred": 1, "ambiguous": 2}
_TESTABLE = ("function", "method", "class")


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    symbol: str
    confidence: str
    note: str
    snippet: str = ""


class Snippets:
    def __init__(self, view: View) -> None:
        self.view = view
        self._cache: dict[str, list[str]] = {}

    def around(self, path: str, line: int, ctx: int = 0) -> str:
        lines = self._cache.get(path)
        if lines is None:
            lines = self._cache[path] = self.view.text(path).splitlines()
        lo, hi = max(1, line - ctx), min(len(lines), line + ctx)
        return "\n".join(f"{n:>6}| {lines[n - 1]}" for n in range(lo, hi + 1))


@dataclass(frozen=True)
class TestHit:
    qualname: str
    path: str
    line: int
    hops: int


@dataclass(frozen=True)
class ContractHit:
    item: RemovedItem
    hit: Hit


@dataclass(frozen=True)
class DriftHit:
    change: SignatureChange
    hit: Hit
    verdict: str  # error | undecided
    reason: str


@dataclass(frozen=True)
class LiteralHit:
    change: LiteralChange
    elsewhere: list[tuple[str, int]]


def callers(vi: ViewIndex, q: str, snippets: Snippets) -> list[Hit]:
    seen: set[tuple[str, int]] = set()
    hits: list[Hit] = []
    for path, ref, conf in vi.callers_with_class(q):
        if (path, ref.line) in seen:
            continue
        seen.add((path, ref.line))
        hits.append(Hit(path, ref.line, ref.src, conf, ref.kind,
                        snippets.around(path, ref.line)))
    return sorted(hits, key=lambda h: (vi.is_test(h.symbol), _CONF_RANK.get(h.confidence, 3),
                                       h.path, h.line))


def guarding_tests(vi: ViewIndex, q: str, hops: int = 2) -> list[TestHit]:
    seen = {q}
    frontier = {q}
    found: dict[str, TestHit] = {}
    for hop in range(1, hops + 1):
        nxt: set[str] = set()
        for target in sorted(frontier):
            for path, ref, _conf in vi.callers_with_class(target):
                src = ref.src
                if src in seen:
                    continue
                seen.add(src)
                sym = vi.symbol(src)
                if sym is None:
                    continue
                if sym.is_test:
                    found.setdefault(src, TestHit(src, path, ref.line, hop))
                elif sym.kind != "module":
                    nxt.add(src)
        frontier = nxt
    return sorted(found.values(), key=lambda t: (t.hops, t.path, t.line))


def removed_contract(vi: ViewIndex, items: list[RemovedItem],
                     snippets: Snippets) -> list[ContractHit]:
    out: list[ContractHit] = []
    for item in items:
        if item.kind == "symbol":
            for path, ref in vi.refs_named(item.name):
                if vi.canonical(ref.target) == item.qualname:
                    conf = "exact"
                elif ref.target.startswith("?.") and vi.resolve(ref.target).target is None:
                    conf = "inferred"
                else:
                    continue
                out.append(ContractHit(item, Hit(
                    path, ref.line, ref.src, conf, f"still references removed {item.qualname}",
                    snippets.around(path, ref.line, ctx=2))))
        elif item.kind == "param":
            for path, ref, conf in vi.callers_with_class(item.qualname):
                if ref.args is not None and item.name in ref.args.keywords:
                    out.append(ContractHit(item, Hit(
                        path, ref.line, ref.src, conf,
                        f"still passes removed keyword `{item.name}`",
                        snippets.around(path, ref.line, ctx=2))))
        else:  # guard or decorator: the tests that exercise the symbol may rely on it
            if item.kind == "guard":
                what = f"guard removed from {item.qualname}: {item.name} {item.text}"
            else:
                what = f"decorator {item.name} removed from {item.qualname}"
            for t in guarding_tests(vi, item.qualname):
                out.append(ContractHit(item, Hit(
                    t.path, t.line, t.qualname, "inferred", f"{what}; this test reaches it",
                    snippets.around(t.path, t.line, ctx=2))))
            if item.kind == "guard" and item.name == "raise":
                exc = re.match(r"[A-Za-z_][\w.]*", item.text)
                if exc:
                    for path, ref in vi.refs_named(last(exc.group(0))):
                        if vi.is_test(ref.src):
                            out.append(ContractHit(item, Hit(
                                path, ref.line, ref.src, "inferred",
                                f"test expects {exc.group(0)}, raised by the removed guard",
                                snippets.around(path, ref.line, ctx=2))))
    return out


def check_call(shape: CallShape, sig: Signature, bound: bool) -> tuple[str, str] | None:
    params = list(sig)
    if bound and params and params[0].name in ("self", "cls"):
        params = params[1:]
    if shape.star or shape.dstar:
        return ("undecided", "call passes *args or **kwargs")
    positional = [p for p in params if p.kind in ("posonly", "pos")]
    has_var = any(p.kind == "vararg" for p in params)
    has_varkw = any(p.kind == "varkw" for p in params)
    if shape.positional > len(positional) and not has_var:
        return ("error", f"{shape.positional} positional args; signature takes {len(positional)}")
    named = {p.name for p in params if p.kind in ("pos", "kwonly")}
    unknown = [k for k in shape.keywords if k not in named]
    if unknown and not has_varkw:
        return ("error", f"unknown keyword(s): {', '.join(unknown)}")
    covered = {p.name for p in positional[: shape.positional]} | set(shape.keywords)
    missing = [p.name for p in params if p.kind in ("posonly", "pos", "kwonly")
               and not p.has_default and p.name not in covered]
    if missing:
        return ("error", f"missing required: {', '.join(missing)}")
    return None


def sig_drift(vi: ViewIndex, changes: list[SignatureChange],
              snippets: Snippets) -> list[DriftHit]:
    out: list[DriftHit] = []
    for ch in changes:
        sym = vi.symbol(ch.qualname)
        bound = sym is not None and sym.kind == "method"
        for path, ref, conf in vi.callers_with_class(ch.qualname):
            if ref.kind != "call":
                continue
            if conf == "ambiguous" or ref.args is None:
                verdict: tuple[str, str] | None = ("undecided", "call target is ambiguous")
            else:
                verdict = check_call(ref.args, ch.new, bound)
            if verdict is not None:
                out.append(DriftHit(ch, Hit(path, ref.line, ref.src, conf, verdict[1],
                                            snippets.around(path, ref.line)), *verdict))
    return out


def untested_changes(vi: ViewIndex, touched: list[Touched]) -> list[Touched]:
    return [t for t in touched
            if t.behaviour_changed and t.kind in _TESTABLE and not vi.is_test(t.qualname)
            and not guarding_tests(vi, t.qualname)]


def literal_hits(store: Store, view_id: str, changes: list[LiteralChange]) -> list[LiteralHit]:
    occurrences = store.literal_occurrences(view_id, sorted({c.text for c in changes}))
    out: list[LiteralHit] = []
    for c in changes:
        elsewhere = [(p, line) for text, p, line in occurrences if text == c.text and p != c.path]
        out.append(LiteralHit(c, elsewhere))
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd plugins/concordance && ../../.venv/bin/python -m pytest ../../tests/concordance/test_query.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add plugins/concordance/scripts/query.py tests/concordance/test_query.py
git commit -m "feat(concordance): removed-contract, signature-drift, callers, tests and literal queries"
```

---

### Task 9: Budgeted rendering

**Files:**
- Create: `plugins/concordance/scripts/render.py`
- Test: `tests/concordance/test_render.py`

**Interfaces:**
- Produces: `CHARS_PER_TOKEN = 3`; `est_tokens(text: str) -> int`; `Section(title: str, rows: list[str], total: int | None = None, exact: bool = True, seed: bool = False)`; `render(header: list[str], sections: list[Section], footer: list[str], budget_tokens: int) -> str`.

Rules: seed sections render first and whole, regardless of budget; other sections render in the given order with whole rows only until the budget is spent; a cut section ends with `  +N more (exact)` (or `(≥)` when `exact=False`); a section whose header no longer fits is listed in one closing `omitted for budget:` line; empty sections are dropped; the footer always renders.

- [ ] **Step 1: Write the failing tests**

`tests/concordance/test_render.py`:
```python
from scripts.render import Section, est_tokens, render


def test_seeds_render_whole_even_over_budget() -> None:
    out = render(["H"], [Section("Verdicts", ["v" * 90] * 5, seed=True)], ["F"], budget_tokens=10)
    assert out.count("v" * 90) == 5 and out.startswith("H") and out.endswith("F")


def test_rows_are_cut_whole_with_an_exact_tail() -> None:
    rows = [f"row {i:02d} " + "x" * 20 for i in range(20)]
    out = render([], [Section("Callers", rows)], [], budget_tokens=60)
    shown = [r for r in rows if r in out]
    assert 0 < len(shown) < 20
    assert f"+{20 - len(shown)} more (exact)" in out
    assert est_tokens(out) <= 60 + 10


def test_lower_bound_tail_and_true_totals() -> None:
    out = render([], [Section("Hits", ["a"], total=7, exact=False)], [], budget_tokens=100)
    assert "## Hits (7+)" in out and "+6 more (≥)" in out


def test_sections_that_do_not_fit_are_named() -> None:
    big = Section("First", ["y" * 300])
    later = Section("Second", ["z"])
    out = render([], [big, later], [], budget_tokens=50)
    assert "omitted for budget: Second (1)" in out


def test_empty_sections_are_dropped() -> None:
    assert "Nothing" not in render([], [Section("Nothing", [])], [], 100)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd plugins/concordance && ../../.venv/bin/python -m pytest ../../tests/concordance/test_render.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.render'`

- [ ] **Step 3: Implement `render.py`**

```python
"""Budgeted text output. Whole rows only; counts say whether they are exact or lower bounds;
seeds (verdicts) are never cut; whatever does not fit is named, never silently dropped.
"""
from __future__ import annotations

from dataclasses import dataclass

CHARS_PER_TOKEN = 3


def est_tokens(text: str) -> int:
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


@dataclass
class Section:
    title: str
    rows: list[str]
    total: int | None = None
    exact: bool = True
    seed: bool = False


def render(header: list[str], sections: list[Section], footer: list[str],
           budget_tokens: int) -> str:
    budget = budget_tokens * CHARS_PER_TOKEN
    out = list(header)
    used = sum(len(line) + 1 for line in [*header, *footer])
    omitted: list[str] = []
    ordered = [s for s in sections if s.seed] + [s for s in sections if not s.seed]
    for sec in ordered:
        total = sec.total if sec.total is not None else len(sec.rows)
        if total == 0:
            continue
        head = f"## {sec.title} ({total}{'' if sec.exact else '+'})"
        if sec.seed:
            out.append(head)
            out.extend(sec.rows)
            used += sum(len(line) + 1 for line in [head, *sec.rows])
            continue
        if used + len(head) + 1 > budget:
            omitted.append(f"{sec.title} ({total})")
            continue
        out.append(head)
        used += len(head) + 1
        shown = 0
        for row in sec.rows:
            if used + len(row) + 1 > budget:
                break
            out.append(row)
            used += len(row) + 1
            shown += 1
        if shown < total:
            out.append(f"  +{total - shown} more ({'exact' if sec.exact else '≥'})")
    if omitted:
        out.append("omitted for budget: " + ", ".join(omitted)
                   + " (rerun with a larger --budget or the section's own command)")
    out.extend(footer)
    return "\n".join(out)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd plugins/concordance && ../../.venv/bin/python -m pytest ../../tests/concordance/test_render.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add plugins/concordance/scripts/render.py tests/concordance/test_render.py
git commit -m "feat(concordance): budgeted section renderer"
```

---

### Task 10: Review context, verdicts and the CLI

**Files:**
- Create: `plugins/concordance/scripts/review.py`, `plugins/concordance/scripts/cli.py`
- Test: `tests/concordance/test_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 1-9.
- Produces (`review.py`): `Verdict(rule: str, path: str, line: int, message: str)`; `Context` (fields: `root`, `store`, `head`, `base`, `base_label`, `reports`, `vi`, `diff`, `snippets`, `contract`, `drift`, `gaps`, `literals`, `head_cov`, `base_cov`); `open_store(cwd: Path) -> Store`; `build(cwd: Path, base_ref: str | None, deadline_s: float) -> Context`; `verdicts(ctx) -> list[Verdict]`; `header(ctx) -> list[str]`; `footer(ctx) -> list[str]`; section builders `verdict_section`, `contract_section`, `drift_section`, `touched_section`, `callers_section`, `tests_section`, `blindspot_sections` (each `(ctx) -> Section` or `list[Section]`); `render_context(ctx, budget: int) -> str`.
- Produces (`cli.py`): `main(argv: list[str] | None = None) -> int`, subcommands `index`, `review-context`, `removed`, `sig-drift`, `literals`, `callers NAME`, `tests NAME`, `check`, `coverage`, `setup-ts`; common options `--base REF`, `--budget N` (default 1500), `--deadline S` (default 60).

- [ ] **Step 1: Write the failing tests**

`tests/concordance/test_cli.py`:
```python
import subprocess
import sys
from pathlib import Path

from scripts.review import open_store

CLI = Path(__file__).resolve().parents[2] / "plugins" / "concordance" / "scripts" / "cli.py"

BASE = {
    "app/svc.py": "def refund(loan, amount, *, partial=False):\n    return amount\n\n\n"
                  "def unused():\n    return 1\n",
    "app/api.py": "from app.svc import refund\n\n\ndef handle(loan):\n"
                  "    return refund(loan, 5, partial=True)\n",
    "tests/test_api.py": "from app.api import handle\n\n\ndef test_handle():\n    handle(None)\n",
}


def cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(CLI), *args], cwd=cwd, capture_output=True,
                          text=True)


def test_review_context_and_check_flag_a_stale_keyword(make_repo) -> None:
    repo = make_repo(BASE)
    repo.git("checkout", "-q", "-b", "feat")
    repo.write({"app/svc.py": "def refund(loan, amount):\n    return amount\n\n\n"
                              "def unused():\n    return 1\n"})
    out = cli(repo.root, "review-context")
    assert out.returncode == 0, out.stderr
    assert "base merge-base with main" in out.stdout
    assert "[BR-002] app/api.py:5" in out.stdout
    assert "still passes removed keyword `partial`" in out.stdout
    assert "coverage: 3/3 files indexed" in out.stdout
    check = cli(repo.root, "check")
    assert check.returncode == 1 and "BR-002" in check.stdout


def test_pure_refactor_is_clean(make_repo) -> None:
    repo = make_repo(BASE)
    repo.git("checkout", "-q", "-b", "feat")
    repo.write({"app/svc.py": "def refund(loan, amount, *, partial=False):\n"
                              "    \"\"\"Refund an amount.\"\"\"\n    return amount\n\n\n"
                              "def unused():\n    return 1\n"})
    check = cli(repo.root, "check")
    assert check.returncode == 0 and "check: clean" in check.stdout


def test_worktrees_do_not_leak_into_each_other(make_repo) -> None:
    repo = make_repo(BASE)
    a = repo.worktree("wt-a", "feat-a")
    b = repo.worktree("wt-b", "feat-b")
    a.write({"app/svc.py": "def refund(loan, amount):\n    return amount\n"})
    out_a = cli(a.root, "check", "--base", "main")
    out_b = cli(b.root, "check", "--base", "main")
    assert out_a.returncode == 1 and out_b.returncode == 0
    assert str(b.root) not in out_a.stdout and str(a.root) not in out_b.stdout
    assert "app/api.py" in out_a.stdout


def test_subdirectory_cwd_prints_root_relative_paths(make_repo) -> None:
    repo = make_repo(BASE)
    repo.write({"app/svc.py": "def refund(loan, amount):\n    return amount\n"})
    out = cli(repo.root / "app", "removed", "--base", "HEAD")
    assert out.returncode == 0, out.stderr
    assert "app/api.py:5" in out.stdout


def test_callers_and_did_you_mean(make_repo) -> None:
    repo = make_repo(BASE)
    out = cli(repo.root, "callers", "refund")
    assert out.returncode == 0 and "app/api.py:5" in out.stdout and "app.api.handle" in out.stdout
    miss = cli(repo.root, "callers", "refnud")
    assert miss.returncode == 0 and "did you mean" in miss.stdout and "app.svc.refund" in miss.stdout
    tests = cli(repo.root, "tests", "app.svc.refund")
    assert "tests.test_api.test_handle" in tests.stdout and "2 hops" in tests.stdout


def test_no_default_branch_exits_2_with_hint(make_repo) -> None:  # Review Focus 1
    repo = make_repo(BASE)
    repo.git("checkout", "-q", "-b", "trunk")
    repo.git("branch", "-q", "-D", "main")
    out = cli(repo.root, "check")
    assert out.returncode == 2 and "--base" in out.stderr and "Traceback" not in out.stderr


def test_outside_a_repo_exits_2(tmp_path: Path) -> None:
    out = cli(tmp_path, "check")
    assert out.returncode == 2 and "Traceback" not in out.stderr


def test_queries_are_recorded_as_events(make_repo) -> None:
    repo = make_repo(BASE)
    cli(repo.root, "callers", "refund")
    st = open_store(repo.root)
    assert st.conn.execute("SELECT command FROM events").fetchall() == [("callers",)]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd plugins/concordance && ../../.venv/bin/python -m pytest ../../tests/concordance/test_cli.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.review'`

- [ ] **Step 3: Implement `review.py`**

```python
"""review-context: one call that builds both views, analyses the diff, runs every query and
renders the result within a budget. Also the source of `check`'s verdicts (BR-002, BR-005).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from scripts import extract_ts, gitio
from scripts.diff import DiffResult, Touched, analyse
from scripts.index import BuildReport, ensure_view
from scripts.paths import store_path
from scripts.query import (
    ContractHit, DriftHit, LiteralHit, Snippets, callers, guarding_tests, literal_hits,
    removed_contract, sig_drift, untested_changes,
)
from scripts.render import Section, render
from scripts.resolve import ViewIndex
from scripts.store import Coverage, Store
from scripts.views import View, base_view, lang_of, worktree_view

TOP_CALLERS = 3


@dataclass(frozen=True)
class Verdict:
    rule: str
    path: str
    line: int
    message: str


@dataclass
class Context:
    root: Path
    store: Store
    head: View
    base: View
    base_label: str
    reports: list[BuildReport]
    vi: ViewIndex
    diff: DiffResult
    snippets: Snippets
    contract: list[ContractHit]
    drift: list[DriftHit]
    gaps: list[Touched]
    literals: list[LiteralHit]
    head_cov: Coverage
    base_cov: Coverage


def open_store(cwd: Path) -> Store:
    return Store(store_path(gitio.common_dir(cwd)))


def build(cwd: Path, base_ref: str | None, deadline_s: float) -> Context:
    root = gitio.worktree_root(cwd)
    store = open_store(root)
    if base_ref is None:
        branch = gitio.default_branch(root)
        try:
            base_sha = gitio.merge_base(root, branch)
        except gitio.GitError as exc:
            raise gitio.GitError(f"no merge-base with {branch}; pass --base <ref> ({exc})") from exc
        label = f"merge-base with {branch}"
    else:
        base_sha = gitio.rev_parse(root, base_ref)
        label = base_ref
    start = time.monotonic()
    head = worktree_view(root)
    base = base_view(root, base_sha)
    reports = [ensure_view(store, head, deadline_s)]
    reports.append(ensure_view(store, base, max(5.0, deadline_s - (time.monotonic() - start))))
    vi = ViewIndex(store, head)
    snippets = Snippets(head)
    d = analyse(store, base, head, vi)
    return Context(
        root=root, store=store, head=head, base=base, base_label=label, reports=reports, vi=vi,
        diff=d, snippets=snippets,
        contract=removed_contract(vi, d.removed, snippets),
        drift=sig_drift(vi, d.signatures, snippets),
        gaps=untested_changes(vi, d.touched),
        literals=literal_hits(store, head.view_id, d.literals),
        head_cov=store.coverage(head.view_id),
        base_cov=store.coverage(base.view_id),
    )


def verdicts(ctx: Context) -> list[Verdict]:
    out = [Verdict("BR-002", x.hit.path, x.hit.line,
                   f"{x.hit.symbol} → {x.change.qualname}: {x.reason}")
           for x in ctx.drift if x.verdict == "error"]
    out += [Verdict("BR-005", t.path, t.line,
                    f"{t.qualname} changed behaviour and no test reaches it within 2 hops")
            for t in ctx.gaps]
    return out


def header(ctx: Context) -> list[str]:
    d = ctx.diff
    changed = sum(t.behaviour_changed and not t.is_new for t in d.touched)
    new = sum(t.is_new for t in d.touched)
    refactor = len(d.touched) - changed - new
    return [
        f"concordance — base {ctx.base_label} ({ctx.base.ref[:7] if ctx.base.ref else '?'}); "
        f"head: this worktree incl. uncommitted edits; paths relative to the worktree root",
        f"changed files: {len(d.changed_files)} · touched symbols: {len(d.touched)} "
        f"({changed} behaviour-changed, {refactor} refactor-only, {new} new)",
    ]


def _not_indexed_reason(path: str) -> str:
    if lang_of(path) == "typescript":
        reason = extract_ts.unavailable_reason()
        if reason:
            return reason
    return "deadline"


def footer(ctx: Context) -> list[str]:
    cov = ctx.head_cov
    indexed = cov.total - len(cov.not_indexed)
    lines = [f"coverage: {indexed}/{cov.total} files indexed in the head view"]
    if cov.failed:
        shown = ", ".join(f"{p} ({err})" for p, err in cov.failed[:5])
        more = f" +{len(cov.failed) - 5} more" if len(cov.failed) > 5 else ""
        lines.append(f"  failed to parse: {shown}{more}")
    if cov.not_indexed:
        reasons = sorted({_not_indexed_reason(p) for p in cov.not_indexed})
        shown = ", ".join(cov.not_indexed[:5])
        more = f" +{len(cov.not_indexed) - 5} more" if len(cov.not_indexed) > 5 else ""
        lines.append(f"  not indexed ({'; '.join(reasons)}): {shown}{more}"
                     " — for these files do steps 1-4 by grep")
    if ctx.base_cov.not_indexed:
        lines.append(f"  base view: {len(ctx.base_cov.not_indexed)} files not indexed; "
                     "removed-item detection is incomplete for them")
    return lines


def verdict_section(ctx: Context) -> Section:
    rows = [f"[{v.rule}] {v.path}:{v.line}  {v.message}" for v in verdicts(ctx)]
    return Section("Verdicts", rows, seed=True)


def contract_section(ctx: Context) -> Section:
    rows = []
    for c in ctx.contract:
        what = c.item.qualname if c.item.kind == "symbol" else f"{c.item.qualname} ({c.item.name})"
        rows.append(f"[removed {c.item.kind}] {what} ← {c.hit.path}:{c.hit.line} in "
                    f"{c.hit.symbol} ({c.hit.confidence}): {c.hit.note}\n{c.hit.snippet}")
    return Section("Removed contract", rows)


def drift_section(ctx: Context) -> Section:
    rows = [f"{x.hit.path}:{x.hit.line} in {x.hit.symbol} → {x.change.qualname}: {x.reason}\n"
            f"{x.hit.snippet}" for x in ctx.drift if x.verdict == "undecided"]
    return Section("Signature drift, undecided", rows)


def touched_section(ctx: Context) -> Section:
    rows = []
    for t in ctx.diff.touched:
        status = "new" if t.is_new else ("behaviour-changed" if t.behaviour_changed
                                         else "refactor-only")
        n_callers = len(ctx.vi.callers_with_class(t.qualname))
        n_tests = len(guarding_tests(ctx.vi, t.qualname))
        rows.append(f"{t.qualname}  {t.path}:{t.line}  {status}  callers {n_callers}  "
                    f"tests {n_tests}")
    return Section("Touched symbols", rows)


def callers_section(ctx: Context) -> Section:
    rows = []
    for t in ctx.diff.touched:
        if not t.behaviour_changed or t.is_new:
            continue
        hits = callers(ctx.vi, t.qualname, ctx.snippets)
        if not hits:
            continue
        lines = [f"{t.qualname}: {len(hits)} caller(s)"]
        lines += [f"  {h.path}:{h.line} in {h.symbol} ({h.confidence})\n{h.snippet}"
                  for h in hits[:TOP_CALLERS]]
        rows.append("\n".join(lines))
    return Section("Callers of behaviour-changed symbols", rows)


def tests_section(ctx: Context) -> Section:
    rows = []
    for t in ctx.diff.touched:
        if not t.behaviour_changed:
            continue
        tests = guarding_tests(ctx.vi, t.qualname)
        if tests:
            listed = ", ".join(f"{x.qualname} ({x.path}:{x.line}, {x.hops} hop"
                               f"{'s' if x.hops > 1 else ''})" for x in tests[:5])
            more = f" +{len(tests) - 5} more" if len(tests) > 5 else ""
            rows.append(f"{t.qualname}: {listed}{more}")
    return Section("Guarding tests", rows)


def blindspot_sections(ctx: Context) -> list[Section]:
    lit_rows = []
    for h in ctx.literals:
        text = h.change.text if len(h.change.text) <= 80 else h.change.text[:77] + "..."
        where = ", ".join(f"{p}:{n}" for p, n in h.elsewhere[:5]) or "nowhere else"
        lit_rows.append(f"[{h.change.change}] {text!r} {h.change.path}:{h.change.line} "
                        f"— also at {where}")
    reorder_rows = [f"{r.qualname} {r.path}:{r.line}: statements reordered"
                    for r in ctx.diff.reorders]
    comment_rows = [f"{c.path}:{c.line} in {c.symbol}: # {c.text}"
                    for c in ctx.diff.removed_comments]
    return [Section("Changed literals", lit_rows), Section("Reordered statements", reorder_rows),
            Section("Removed comments", comment_rows)]


def render_context(ctx: Context, budget: int) -> str:
    sections = [verdict_section(ctx), contract_section(ctx), drift_section(ctx),
                touched_section(ctx), callers_section(ctx), tests_section(ctx),
                *blindspot_sections(ctx)]
    return render(header(ctx), sections, footer(ctx), budget)
```

- [ ] **Step 4: Implement `cli.py`**

```python
"""concordance CLI. Run as `python <plugin>/scripts/cli.py <command>` from inside a worktree."""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

if __package__ in (None, ""):  # direct invocation: put the plugin root on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import extract_ts, gitio  # noqa: E402
from scripts.index import LockTimeout, ensure_view  # noqa: E402
from scripts.query import Snippets, callers, guarding_tests  # noqa: E402
from scripts.render import Section, est_tokens, render  # noqa: E402
from scripts.resolve import Resolved, ViewIndex  # noqa: E402
from scripts.review import (  # noqa: E402
    Context, blindspot_sections, build, contract_section, drift_section, footer, header,
    open_store, render_context, verdict_section, verdicts,
)
from scripts.views import worktree_view  # noqa: E402

DEFAULT_BUDGET = 1500
DEFAULT_DEADLINE = 60.0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="concordance", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    def add(name: str, help_text: str, diff: bool = True, name_arg: bool = False) -> None:
        sp = sub.add_parser(name, help=help_text)
        if name_arg:
            sp.add_argument("name")
        if diff:
            sp.add_argument("--base", default=None,
                            help="base ref (default: merge-base with the default branch)")
        sp.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
        sp.add_argument("--deadline", type=float, default=DEFAULT_DEADLINE)

    add("index", "build or refresh this worktree's view (and the base view)")
    add("review-context", "everything a reviewer needs for this diff, within a budget")
    add("removed", "references to what the diff removed")
    add("sig-drift", "call sites that no longer match a changed signature")
    add("literals", "changed literals, reordered statements, removed comments")
    add("check", "verdicts only (BR-002, BR-005); exit 1 when any")
    add("callers", "who calls NAME", diff=False, name_arg=True)
    add("tests", "tests that reach NAME within --hops", diff=False, name_arg=True)
    sub.choices["tests"].add_argument("--hops", type=int, default=2)
    add("coverage", "files indexed, failed and skipped in this worktree's view", diff=False)
    sub.add_parser("setup-ts", help="install the pinned TypeScript parser (npm ci)")
    return p


def _diff_command(args: argparse.Namespace, cwd: Path) -> tuple[str, int, str]:
    ctx = build(cwd, args.base, args.deadline)
    view_id = ctx.head.view_id
    if args.command == "review-context":
        return render_context(ctx, args.budget), 0, view_id
    if args.command == "removed":
        return render(header(ctx), [contract_section(ctx)], footer(ctx), args.budget), 0, view_id
    if args.command == "sig-drift":
        sections = [verdict_section(ctx), drift_section(ctx)]
        return render(header(ctx), sections, footer(ctx), args.budget), 0, view_id
    if args.command == "literals":
        return render(header(ctx), blindspot_sections(ctx), footer(ctx), args.budget), 0, view_id
    if args.command == "check":
        return _check(ctx), (1 if verdicts(ctx) else 0), view_id
    report = ctx.reports[0]
    lines = [f"head view {report.view_id}: {report.files} files, {report.parsed} parsed, "
             f"{report.reused} reused, {len(report.failed)} failed, {len(report.skipped)} skipped",
             *footer(ctx)]
    return "\n".join(lines), 0, view_id


def _check(ctx: Context) -> str:
    found = verdicts(ctx)
    if not found:
        return "check: clean"
    return "\n".join(f"[{v.rule}] {v.path}:{v.line}  {v.message}" for v in found)


def _name_command(args: argparse.Namespace, cwd: Path) -> tuple[str, int, str]:
    store = open_store(cwd)
    view = worktree_view(cwd)
    ensure_view(store, view, args.deadline)
    vi = ViewIndex(store, view)
    if args.command == "coverage":
        cov = store.coverage(view.view_id)
        lines = [f"coverage: {cov.total - len(cov.not_indexed)}/{cov.total} files indexed",
                 *[f"  failed: {p} ({err})" for p, err in cov.failed],
                 *[f"  not indexed: {p}" for p in cov.not_indexed]]
        return "\n".join(lines), 0, view.view_id
    found = vi.lookup(args.name)
    if found.target is None:
        return _miss(args.name, found), 0, view.view_id
    q = found.target
    note = "" if found.confidence == "exact" else f" ({found.confidence} match for {args.name})"
    if args.command == "callers":
        hits = callers(vi, q, Snippets(view))
        rows = [f"{h.path}:{h.line} in {h.symbol} ({h.confidence})\n{h.snippet}" for h in hits]
        section = Section(f"Callers of {q}{note}", rows)
    else:
        tests = guarding_tests(vi, q, args.hops)
        rows = [f"{t.qualname} {t.path}:{t.line} ({t.hops} hop{'s' if t.hops > 1 else ''})"
                for t in tests]
        section = Section(f"Tests reaching {q}{note}", rows)
    if not section.rows:
        return f"{section.title}: none found", 0, view.view_id
    return render([], [section], [], args.budget), 0, view.view_id


def _miss(name: str, found: Resolved) -> str:
    if found.confidence == "ambiguous":
        return f"{name} is ambiguous; did you mean: " + ", ".join(found.candidates)
    if found.candidates:
        return f"{name} not found; did you mean: " + ", ".join(found.candidates)
    return f"{name} not found in this worktree's view"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "setup-ts":
        return extract_ts.setup()
    cwd = Path.cwd()
    started = time.monotonic()
    try:
        if args.command in ("callers", "tests", "coverage"):
            text, code, view_id = _name_command(args, cwd)
        else:
            text, code, view_id = _diff_command(args, cwd)
    except (gitio.GitError, LockTimeout) as exc:
        print(f"concordance: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # internal error: exit 2, never a bare traceback
        print(f"concordance: internal error: {exc!r}", file=sys.stderr)
        return 2
    print(text)
    try:
        open_store(cwd).record_event(
            args.command, view_id, int((time.monotonic() - started) * 1000), est_tokens(text),
            session=os.environ.get("CLAUDE_SESSION_ID", ""))
    except Exception:  # telemetry must never fail a query
        pass
    return code


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd plugins/concordance && ../../.venv/bin/python -m pytest ../../tests/concordance/test_cli.py -q`
Expected: 8 passed

- [ ] **Step 6: Run the whole suite, ruff and mypy**

Run: `cd plugins/concordance && ../../.venv/bin/python -m pytest -q && ../../.venv/bin/ruff check scripts ../../tests/concordance && ../../.venv/bin/mypy scripts`
Expected: all tests pass; ruff `All checks passed!`; mypy `Success: no issues found`. Fix any lint/type finding before committing (common: missing annotations in test helpers are fine since mypy runs on `scripts` only).

- [ ] **Step 7: Commit**

```bash
git add plugins/concordance/scripts/review.py plugins/concordance/scripts/cli.py tests/concordance/test_cli.py
git commit -m "feat(concordance): review-context, check verdicts and the CLI"
```

---

### Task 11: TypeScript extractor

**Files:**
- Create: `plugins/concordance/scripts/extract_ts/package.json`, `plugins/concordance/scripts/extract_ts/package-lock.json` (generated), `plugins/concordance/scripts/extract_ts/extract.mjs`
- Replace: `plugins/concordance/scripts/extract_ts.py` (the Task 5 stub)
- Test: `tests/concordance/test_extract_ts.py`

**Interfaces:**
- Consumes: `facts.file_facts_from_dict` (Task 2); `ensure_view`, `ViewIndex`, `analyse`, `sig_drift` (tests only).
- Produces: same functions as the stub (`DeadlineExceeded`, `unavailable_reason() -> str | None`, `extract_batch(items, timeout_s) -> list[FileFacts]`) plus `setup() -> int` and `NODE_DIR: Path`. TS qualnames: module `ts:<path without extension>`; members `ts:<path>.<Name>[.<member>]`; class constructors `….<Class>.constructor`; `export default` creates alias `ts:<path>.default`.

- [ ] **Step 1: Pin and install typescript**

`plugins/concordance/scripts/extract_ts/package.json`:
```json
{
  "name": "concordance-extract-ts",
  "private": true,
  "type": "module",
  "description": "concordance's TypeScript fact extractor (parser only, no type checker).",
  "dependencies": {
    "typescript": "5.6.3"
  }
}
```

Run: `cd plugins/concordance/scripts/extract_ts && npm install --package-lock-only --ignore-scripts --no-audit --no-fund && npm ci --ignore-scripts --no-audit --no-fund`
Expected: `package-lock.json` created with `"typescript": { "version": "5.6.3", "resolved": "https://registry.npmjs.org/typescript/-/typescript-5.6.3.tgz", "integrity": "sha512-…" }`; `node_modules/typescript` present (ignored by the plugin `.gitignore`).

- [ ] **Step 2: Write the failing tests**

`tests/concordance/test_extract_ts.py`:
```python
from pathlib import Path

import pytest

from scripts import extract_ts
from scripts.diff import analyse
from scripts.index import ensure_view
from scripts.query import Snippets, sig_drift
from scripts.resolve import ViewIndex
from scripts.store import Store
from scripts.views import base_view, worktree_view

pytestmark = pytest.mark.skipif(extract_ts.unavailable_reason() is not None,
                                reason=f"TS extractor unavailable: {extract_ts.unavailable_reason()}")

MONEY = (
    "export function refund(amount: number, reason?: string): number {\n"
    "  // keep in sync with ledger\n"
    "  if (amount < 0) {\n"
    "    throw new Error('negative');\n"
    "  }\n"
    "  return amount;\n"
    "}\n"
    "export default refund;\n"
)
USE = (
    "import { refund as r } from '../lib/money';\n"
    "import * as M from '../lib/money';\n"
    "import ts from 'typescript';\n"
    "import { fee } from '@lib/fees';\n\n"
    "export class Svc extends Base {\n"
    "  run(): number {\n"
    "    this.helper();\n"
    "    M.refund(1, 'x', 3);\n"
    "    fee();\n"
    "    return r(2);\n"
    "  }\n"
    "  helper(): void {}\n"
    "}\n"
)
FILES = {
    "src/lib/money.ts": MONEY,
    "src/lib/fees.ts": "export function fee(): number {\n  return 1;\n}\n",
    "src/app/use.ts": USE,
    "src/app/use.test.ts": "import { Svc } from './use';\n\ntest('runs', () => {\n  new Svc().run();\n});\n",
    "tsconfig.json": '{\n  // paths\n  "compilerOptions": {"baseUrl": ".", "paths": {"@lib/*": ["src/lib/*"]},},\n}\n',
    "py/money.py": "def refund(amount):\n    return amount\n",
}


def extract(path: str, text: str):
    return extract_ts.extract_batch([(path, "sha", text.encode())], timeout_s=30)[0]


def test_symbols_signatures_and_default_alias() -> None:
    f = extract("src/lib/money.ts", MONEY)
    by = {s.qualname: s for s in f.symbols}
    refund = by["ts:src/lib/money.refund"]
    assert refund.kind == "function"
    assert [(p.name, p.kind, p.has_default) for p in refund.signature] == [
        ("amount", "pos", False), ("reason", "pos", True)]
    assert by["ts:src/lib/money.default"].alias_of == "ts:src/lib/money.refund"


def test_refs_imports_namespaces_this_and_bare_specifiers() -> None:
    f = extract("src/app/use.ts", USE)
    calls = {(r.src, r.target, r.args.positional if r.args else None)
             for r in f.refs if r.kind == "call"}
    assert ("ts:src/app/use.Svc.run", "ts:src/app/use.Svc.helper", 0) in calls
    assert ("ts:src/app/use.Svc.run", "ts:src/lib/money.refund", 3) in calls
    assert ("ts:src/app/use.Svc.run", "ts:src/lib/money.refund", 1) in calls
    assert ("ts:src/app/use.Svc.run", "ts-bare:@lib/fees|fee", 0) in calls
    aliases = {s.qualname: s.alias_of for s in f.symbols if s.kind == "alias"}
    assert aliases["ts:src/app/use.ts"] == "ts-bare:typescript|default"
    assert not any("Base" in r.target for r in f.refs)


def test_guards_comments_and_test_files() -> None:
    f = extract("src/lib/money.ts", MONEY)
    assert {(g.kind, g.text) for g in f.guards} == {
        ("if", "amount < 0"), ("raise", "new Error('negative')")}
    comment = next(x for x in f.literals if x.kind == "comment")
    assert (comment.text, comment.symbol) == ("keep in sync with ledger", "ts:src/lib/money.refund")
    t = extract("src/app/use.test.ts", FILES["src/app/use.test.ts"])
    assert t.symbols and all(s.is_test for s in t.symbols)


def test_syntax_error_is_recorded() -> None:
    f = extract("bad.ts", "function (:\n")
    assert not f.parsed_ok and f.error is not None and f.error.startswith("SyntaxError: line 1")


def test_end_to_end_callers_tsconfig_paths_and_drift(tmp_path: Path, make_repo) -> None:
    repo = make_repo(FILES)
    sha = repo.git("rev-parse", "HEAD").strip()
    repo.write({"src/lib/money.ts": MONEY.replace(", reason?: string", "")})
    st = Store(tmp_path / "i.db")
    head, base = worktree_view(repo.root), base_view(repo.root, sha)
    assert ensure_view(st, head).skipped == {}
    ensure_view(st, base)
    vi = ViewIndex(st, head)
    srcs = {r.src for _, r, _ in vi.callers("ts:src/lib/money.refund")}
    assert "ts:src/app/use.Svc.run" in srcs
    assert all(s.startswith("ts:") for s in srcs)  # py/money.py's refund never matches
    assert {r.src for _, r, _ in vi.callers("ts:src/lib/fees.fee")} == {"ts:src/app/use.Svc.run"}
    tests = {r.src for _, r, _ in vi.callers_with_class("ts:src/app/use.Svc.run")}
    assert "ts:src/app/use.test" in tests
    d = analyse(st, base, head, vi)
    drift = sig_drift(vi, d.signatures, Snippets(head))
    assert any(x.verdict == "error" and "3 positional" in x.reason for x in drift)
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd plugins/concordance && ../../.venv/bin/python -m pytest ../../tests/concordance/test_extract_ts.py -q`
Expected: 5 skipped ("TypeScript extractor not built yet"). Skipped counts as failing here: the stub must be replaced.

- [ ] **Step 4: Write `extract.mjs`**

`plugins/concordance/scripts/extract_ts/extract.mjs`:
```js
// concordance TypeScript extractor. One file at a time, syntax only (the compiler's parser,
// never the type checker), so a file's facts depend on its own content and path and can be
// shared across worktrees. Reads [{path, content}] on stdin; writes FileFacts-shaped dicts.
// Module resolution (relative imports, index files, tsconfig paths) happens in Python.
import ts from "typescript";
import { readFileSync } from "node:fs";
import path from "node:path";

const MIN_LITERAL = 3;

const items = JSON.parse(readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(items.map(safeExtract)));

function safeExtract(item) {
  try {
    return extractFile(item);
  } catch (err) {
    return { path: item.path, lang: "typescript", parsed_ok: false,
             error: `extractor error: ${String(err && err.message ? err.message : err)}`,
             symbols: [], refs: [], literals: [], guards: [] };
  }
}

function modName(p) { return "ts:" + p.replace(/\.[cm]?tsx?$/, ""); }
function isTestPath(p) {
  return /(^|\/)(__tests__|tests?)\//.test(p) || /\.(test|spec)\.[cm]?tsx?$/.test(p);
}

function specTarget(fromPath, spec) {
  if (spec.startsWith(".")) {
    const joined = path.posix.normalize(path.posix.join(path.posix.dirname(fromPath), spec));
    return { rel: true, base: "ts:" + joined.replace(/\.([cm]?[jt]sx?)$/, "") };
  }
  return { rel: false, base: `ts-bare:${spec}|` };
}
function memberTarget(t, member) {
  if (t.rel) return member ? `${t.base}.${member}` : t.base;
  return member ? `${t.base}${member}` : t.base;
}
function joinTarget(base, rest) {
  if (!rest) return base;
  return base.endsWith("|") ? base + rest : `${base}.${rest}`;
}

function extractFile({ path: p, content }) {
  const mod = modName(p);
  const isTest = isTestPath(p);
  const kind = p.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const sf = ts.createSourceFile(p, content, ts.ScriptTarget.Latest, true, kind);
  const lineOf = (pos) => sf.getLineAndCharacterOfPosition(pos).line + 1;
  const facts = { path: p, lang: "typescript", parsed_ok: true, error: null,
                  symbols: [], refs: [], literals: [], guards: [] };
  const diags = sf.parseDiagnostics ?? [];
  if (diags.length) {
    const d = diags[0];
    facts.parsed_ok = false;
    facts.error = `SyntaxError: line ${lineOf(d.start ?? 0)}: ` +
      ts.flattenDiagnosticMessageText(d.messageText, " ");
    return facts;
  }

  const imports = new Map();
  const topDefs = new Set();
  for (const st of sf.statements) {
    if (ts.isImportDeclaration(st) && ts.isStringLiteral(st.moduleSpecifier) && st.importClause) {
      const t = specTarget(p, st.moduleSpecifier.text);
      const clause = st.importClause;
      if (clause.name) imports.set(clause.name.text, memberTarget(t, "default"));
      const nb = clause.namedBindings;
      if (nb && ts.isNamespaceImport(nb)) imports.set(nb.name.text, memberTarget(t, null));
      if (nb && ts.isNamedImports(nb)) {
        for (const el of nb.elements) {
          imports.set(el.name.text, memberTarget(t, (el.propertyName ?? el.name).text));
        }
      }
    } else if ((ts.isFunctionDeclaration(st) || ts.isClassDeclaration(st) ||
                ts.isInterfaceDeclaration(st) || ts.isTypeAliasDeclaration(st) ||
                ts.isEnumDeclaration(st)) && st.name) {
      topDefs.add(st.name.text);
    } else if (ts.isVariableStatement(st)) {
      for (const d of st.declarationList.declarations) {
        if (ts.isIdentifier(d.name)) topDefs.add(d.name.text);
      }
    } else if (ts.isExportDeclaration(st) && st.moduleSpecifier &&
               ts.isStringLiteral(st.moduleSpecifier) && st.exportClause &&
               ts.isNamedExports(st.exportClause)) {
      const t = specTarget(p, st.moduleSpecifier.text);
      for (const el of st.exportClause.elements) {
        addAlias(`${mod}.${el.name.text}`, memberTarget(t, (el.propertyName ?? el.name).text));
      }
    }
  }

  const stack = [];
  const seen = new Set();
  const comments = [];
  const commentPos = new Set();
  const current = () => (stack.length ? stack[stack.length - 1].qual : mod);
  const inFunction = () => stack.some((s) => s.kind === "function" || s.kind === "method");
  const classQual = () => {
    for (let i = stack.length - 1; i >= 0; i--) if (stack[i].kind === "class") return stack[i].qual;
    return null;
  };

  function addAlias(qualname, target) {
    facts.symbols.push({ qualname, kind: "alias", line_start: 1, line_end: 1, is_test: isTest,
                         signature: null, alias_of: target });
  }
  function addSymbol(qual, k, node, sig) {
    facts.symbols.push({ qualname: qual, kind: k, line_start: lineOf(node.getStart(sf)),
                         line_end: lineOf(node.getEnd()), is_test: isTest,
                         signature: sig ?? null, alias_of: null });
  }
  function addRef(target, k, node, args, src) {
    if (!target) return;
    const s = src ?? current();
    const line = lineOf(node.getStart(sf));
    const key = `${s}|${target}|${k}|${line}`;
    if (seen.has(key)) return;
    seen.add(key);
    facts.refs.push({ src: s, target, kind: k, line, args: args ?? null });
  }
  function dotted(node) {
    if (ts.isIdentifier(node)) return node.text;
    if (node.kind === ts.SyntaxKind.ThisKeyword) return "this";
    if (ts.isPropertyAccessExpression(node)) {
      const b = dotted(node.expression);
      return b ? `${b}.${node.name.text}` : null;
    }
    return null;
  }
  function resolveDotted(d) {
    const i = d.indexOf(".");
    const head = i < 0 ? d : d.slice(0, i);
    const rest = i < 0 ? "" : d.slice(i + 1);
    if (head === "this") {
      const c = classQual();
      if (!c || !rest) return null;
      return rest.includes(".") ? `?.${rest.split(".").pop()}` : `${c}.${rest}`;
    }
    if (imports.has(head)) return joinTarget(imports.get(head), rest);
    if (topDefs.has(head)) return `${mod}.${d}`;
    return rest ? `?.${rest.split(".").pop()}` : null;
  }
  function signature(params) {
    return params.map((prm, i) => [
      ts.isIdentifier(prm.name) ? prm.name.text : `_arg${i}`,
      prm.dotDotDotToken ? "vararg" : "pos",
      Boolean(prm.questionToken || prm.initializer || prm.dotDotDotToken),
    ]);
  }
  function hasDefaultExport(node) {
    const mods = ts.canHaveModifiers(node) ? ts.getModifiers(node) ?? [] : [];
    return mods.some((m) => m.kind === ts.SyntaxKind.DefaultKeyword);
  }
  function decorators(node, qual) {
    const decs = ts.canHaveDecorators(node) ? ts.getDecorators(node) ?? [] : [];
    for (const dec of decs) {
      const callee = ts.isCallExpression(dec.expression) ? dec.expression.expression : dec.expression;
      const d = dotted(callee);
      addRef(d && resolveDotted(d), "decorator", dec, null, qual);
    }
  }
  function collectComments(pos) {
    for (const range of ts.getLeadingCommentRanges(content, pos) ?? []) {
      if (commentPos.has(range.pos)) continue;
      commentPos.add(range.pos);
      const raw = content.slice(range.pos, range.end);
      const text = raw.replace(/^\/\/+|^\/\*+|\*+\/$/g, "").trim();
      if (text) comments.push({ line: lineOf(range.pos), text });
    }
  }

  function defn(node, name, k, params, bodyNode) {
    const qual = `${current()}.${name}`;
    addSymbol(qual, k, node, signature(params));
    decorators(node, qual);
    if (k === "function" && hasDefaultExport(node) && stack.length === 0) {
      addAlias(`${mod}.default`, qual);
    }
    stack.push({ qual, kind: k });
    ts.forEachChild(bodyNode ?? node, visit);
    stack.pop();
  }
  function classDefn(node) {
    const qual = `${current()}.${node.name.text}`;
    addSymbol(qual, "class", node, null);
    decorators(node, qual);
    if (hasDefaultExport(node) && stack.length === 0) addAlias(`${mod}.default`, qual);
    for (const h of node.heritageClauses ?? []) {
      for (const t of h.types) {
        const d = dotted(t.expression);
        addRef(d && resolveDotted(d), "inherit", t, null, qual);
      }
    }
    stack.push({ qual, kind: "class" });
    for (const m of node.members) visit(m);
    stack.pop();
  }
  function call(node) {
    const callee = node.expression;
    const d = dotted(callee);
    let target = d ? resolveDotted(d) : null;
    if (!d) {
      if (ts.isPropertyAccessExpression(callee)) {
        target = `?.${callee.name.text}`;
        visit(callee.expression);
      } else {
        visit(callee);
      }
    }
    const args = node.arguments ?? [];
    addRef(target, "call", node, {
      positional: args.filter((a) => !ts.isSpreadElement(a)).length,
      keywords: [], star: args.some((a) => ts.isSpreadElement(a)), dstar: false,
    });
    for (const a of args) visit(a);
  }

  function visit(node) {
    collectComments(node.getFullStart());
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) return;
    if (ts.isFunctionDeclaration(node)) {
      return defn(node, node.name ? node.name.text : "default", "function", node.parameters);
    }
    if (ts.isClassDeclaration(node) && node.name) return classDefn(node);
    if (ts.isMethodDeclaration(node) && ts.isIdentifier(node.name)) {
      return defn(node, node.name.text, "method", node.parameters);
    }
    if (ts.isConstructorDeclaration(node)) return defn(node, "constructor", "method", node.parameters);
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer &&
        (ts.isArrowFunction(node.initializer) || ts.isFunctionExpression(node.initializer)) &&
        stack.length === 0) {
      return defn(node, node.name.text, "function", node.initializer.parameters, node.initializer);
    }
    if ((ts.isInterfaceDeclaration(node) || ts.isTypeAliasDeclaration(node) ||
         ts.isEnumDeclaration(node)) && stack.length === 0) {
      addSymbol(`${mod}.${node.name.text}`, "type", node, null);
      return;
    }
    if (ts.isExportAssignment(node) && ts.isIdentifier(node.expression)) {
      const target = resolveDotted(node.expression.text);
      if (target) addAlias(`${mod}.default`, target);
      return;
    }
    if (ts.isCallExpression(node) || ts.isNewExpression(node)) return call(node);
    if (ts.isPropertyAccessExpression(node)) {
      const d = dotted(node);
      if (d && imports.has(d.split(".")[0])) {
        addRef(resolveDotted(d), "name", node);
        return;
      }
    }
    if (ts.isIdentifier(node) && imports.has(node.text)) addRef(resolveDotted(node.text), "name", node);
    if (ts.isIfStatement(node) && inFunction()) {
      facts.guards.push({ symbol: current(), kind: "if", line: lineOf(node.getStart(sf)),
                          text: node.expression.getText(sf) });
    }
    if (ts.isThrowStatement(node) && inFunction() && node.expression) {
      facts.guards.push({ symbol: current(), kind: "raise", line: lineOf(node.getStart(sf)),
                          text: node.expression.getText(sf) });
    }
    if ((ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) &&
        node.text.length >= MIN_LITERAL) {
      facts.literals.push({ kind: "string", text: node.text, line: lineOf(node.getStart(sf)),
                            symbol: current() });
    }
    ts.forEachChild(node, visit);
  }

  const lastLine = Math.max(1, lineOf(sf.getEnd()));
  facts.symbols.push({ qualname: mod, kind: "module", line_start: 1, line_end: lastLine,
                       is_test: isTest, signature: null, alias_of: null });
  for (const [local, target] of imports) addAlias(`${mod}.${local}`, target);
  ts.forEachChild(sf, visit);

  const spans = facts.symbols
    .filter((s) => !["module", "alias", "type"].includes(s.kind))
    .sort((a, b) => (a.line_end - a.line_start) - (b.line_end - b.line_start));
  for (const c of comments) {
    const owner = spans.find((s) => s.line_start <= c.line && c.line <= s.line_end);
    facts.literals.push({ kind: "comment", text: c.text, line: c.line,
                          symbol: owner ? owner.qualname : mod });
  }
  return facts;
}
```

Implementer note: in `test_refs_imports_namespaces_this_and_bare_specifiers` the alias for the default import `ts` is `ts:src/app/use.ts` (module `ts:src/app/use` + `.` + local name `ts`); that is the intended qualname, not a typo.

- [ ] **Step 5: Replace the bridge stub**

`plugins/concordance/scripts/extract_ts.py`:
```python
"""Bridge to the Node TypeScript extractor (extract_ts/extract.mjs).

Missing Node or an uninstalled typescript package is not an error: the files are reported as
not indexed with the reason, and nothing is stored, so they are picked up once it is installed.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from scripts.facts import FileFacts, file_facts_from_dict

NODE_DIR = Path(__file__).resolve().parent / "extract_ts"


class DeadlineExceeded(RuntimeError):
    pass


def unavailable_reason() -> str | None:
    if shutil.which("node") is None:
        return "node not found on PATH"
    if not (NODE_DIR / "node_modules" / "typescript" / "package.json").is_file():
        cli = Path(__file__).resolve().parent / "cli.py"
        return f"typescript not installed: run `python {cli} setup-ts`"
    return None


def extract_batch(items: list[tuple[str, str, bytes]], timeout_s: float) -> list[FileFacts]:
    if not items:
        return []
    payload = json.dumps([{"path": p, "content": data.decode("utf-8", errors="replace")}
                          for p, _, data in items])
    try:
        proc = subprocess.run(["node", str(NODE_DIR / "extract.mjs")], input=payload,
                              capture_output=True, text=True, timeout=max(timeout_s, 0.1),
                              cwd=NODE_DIR)
    except subprocess.TimeoutExpired as exc:
        raise DeadlineExceeded(f"TypeScript extraction exceeded {timeout_s:.0f}s") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"TypeScript extractor failed: {proc.stderr.strip()[:500]}")
    raw = json.loads(proc.stdout)
    return [file_facts_from_dict(d, sha) for d, (_, sha, _) in zip(raw, items)]


def setup() -> int:
    if shutil.which("npm") is None:
        print("npm not found on PATH; install Node.js 18+ first")
        return 2
    return subprocess.run(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
                          cwd=NODE_DIR).returncode
```

- [ ] **Step 6: Run the TS tests and the whole suite**

Run: `cd plugins/concordance && ../../.venv/bin/python -m pytest -q && ../../.venv/bin/ruff check scripts ../../tests/concordance && ../../.venv/bin/mypy scripts`
Expected: all pass, `test_extract_ts.py` 5 passed (not skipped); ruff and mypy clean.

- [ ] **Step 7: Commit**

```bash
git add plugins/concordance/scripts/extract_ts.py plugins/concordance/scripts/extract_ts/package.json plugins/concordance/scripts/extract_ts/package-lock.json plugins/concordance/scripts/extract_ts/extract.mjs tests/concordance/test_extract_ts.py
git commit -m "feat(concordance): TypeScript extractor on the pinned compiler parser"
```

---

### Task 12: Review procedure, lens, docs and versions

**Files:**
- Create: `plugins/concordance/skills/review-procedure/SKILL.md`, `plugins/concordance/README.md`, `plugins/review-panel/skills/reviewers/blast-radius.md`
- Modify: `.claude-plugin/marketplace.json` (new entry; `version` 1.67.0 → 1.68.0), `plugins/review-panel/.claude-plugin/plugin.json` (`version` 0.1.0 → 0.2.0), `CLAUDE.md` (Plugins list)
- Test: existing `plugins/review-panel/tests/test_docs.py` (lints every reviewer doc) and `test_discovery.py`

**Interfaces:**
- Consumes: the CLI surface from Task 10 (command names and flags exactly as defined there).
- Produces: skill `concordance:review-procedure`; reviewer lens `blast-radius` with rule ids BR-001..BR-005.

- [ ] **Step 1: Write the review procedure skill**

`plugins/concordance/skills/review-procedure/SKILL.md`:
````markdown
---
name: review-procedure
description: Step-by-step blast-radius review of the current diff with concordance — what still relies on removed code, call sites broken by a signature change, callers and tests of changed behaviour, and the changes an index cannot see. Use when reviewing a diff, branch or PR for regressions ("review my diff", "what does this break", "blast radius", "who calls this", "what tests cover this"), or when the review-panel blast-radius lens is seated.
---

# concordance review procedure

The CLI does all the detection; you judge meaning. Every step below is **mandatory** and ends
with either a finding or the word "clean". Do not skip a step because the diff "looks simple".

**CLI:** `python <this skill's base directory>/../../scripts/cli.py <command>`, run from inside
the worktree under review. Paths in its output are relative to the worktree root. If a command
exits 2, read its stderr: usually you must pass `--base <ref>` (the PR's base branch or commit).

## Step 0: orient

Run `review-context` once (add `--base <ref>` when reviewing a PR against a known base):

```bash
python …/scripts/cli.py review-context --base <ref>
```

Read the header (base, counts) and the **coverage footer**. A file listed as failed or not
indexed was not checked by the index: silence about it is not evidence it is safe. For those
files, do steps 1-4 by Grep.

If output says `omitted for budget`, re-run the named section's own command
(`removed`, `sig-drift`, `literals`) or raise `--budget`.

## Step 1: removed contract

For every row under **Removed contract**: the diff removed a symbol, a parameter, a guard or a
decorator, and the row shows code that still references it (with ±2 lines). Decide whether
that code *relies* on the removed behaviour. Open the file only when the snippet is not enough.
A live reliance is finding BR-001.

## Step 2: signature drift

Rows under **Verdicts** tagged `[BR-002]` are already decided by the CLI: report each one.
Rows under **Signature drift, undecided** use `*args`/`**kwargs` or an ambiguous target: judge
each against the new signature.

## Step 3: callers of changed behaviour

Under **Callers of behaviour-changed symbols** (pure refactors are already excluded): for each
symbol, read its callers' call lines and ask what they assume about the old behaviour. For more
than the 3 shown, run `callers <qualname>`. A broken assumption is BR-003.

## Step 4: guarding tests

Under **Guarding tests**: does any listed test still assert the *old* behaviour? That is BR-004.
`[BR-005]` verdicts (behaviour changed, no test within 2 hops) are already decided: report them.
Never report a missing test for a symbol whose behaviour did not change.

## Step 5: what the index cannot see

- **Changed literals**: SQL, config keys, event names. Each row shows where else the old or new
  text appears; check those places agree (table order, renamed keys, event names).
- **Reordered statements**: ordering of writes, events, deletes, locks. Decide if order matters.
- **Removed comments**: a removed comment often explained an invariant. Is the invariant still
  kept by the new code?

## Output

Your findings, then a tool log:

```
TOOL LOG
- step 0 orient: <one line: base, counts, coverage gaps>
- step 1 removed contract: <finding ids | clean>
- step 2 signature drift: <finding ids | clean>
- step 3 callers: <finding ids | clean>
- step 4 tests: <finding ids | clean>
- step 5 blind spots: <finding ids | clean>
- grep fallbacks: <files, or none>
```
````

- [ ] **Step 2: Write the blast-radius lens**

`plugins/review-panel/skills/reviewers/blast-radius.md`:
```markdown
# Blast Radius

## Concern
What this change breaks elsewhere. Code that still relies on something the diff removed, call
sites that no longer match a changed signature, callers whose assumptions changed under them,
tests that pin the old behaviour, and changed behaviour no test reaches. Detection comes from
concordance's index; this reviewer judges what the hits mean.

## When to seat
Diffs that remove code, parameters, guards or decorators; that change a signature; or that
touch symbols with more than one caller. Leave it off for docs-only, config-only or brand-new
isolated files. Requires the concordance plugin: locate its CLI with Glob for
`plugins/cache/*/concordance/*/scripts/cli.py` under `$CLAUDE_CONFIG_DIR` (default `~/.claude`),
or `plugins/concordance/scripts/cli.py` inside the pip-skills repo. If neither exists, say the
lens cannot be seated and stop.

## Techniques
Change-impact and cross-referencing, driven by concordance's review procedure: invoke the
`concordance:review-procedure` skill (or read `<concordance plugin>/skills/review-procedure/SKILL.md`
if the Skill tool is unavailable) and follow every step; each step ends in a finding or "clean".

## What to look for
| ID | category | rule | default severity | what to scan for |
|----|----------|------|------------------|------------------|
| BR-001 | correctness | Removed contract still referenced | error | Removed contract rows whose referencing code still relies on the removed symbol, parameter, guard or decorator |
| BR-002 | correctness | Signature drift at a call site | error | `[BR-002]` verdicts (decided by the CLI), and undecided drift rows that do not fit the new signature |
| BR-003 | correctness | Caller assumption broken by a behaviour change | warning | Callers of behaviour-changed symbols that depend on the old result, side effect or exception |
| BR-004 | tests | Guarding test asserts the old behaviour | warning | Guarding tests whose assertions encode the behaviour the diff changed |
| BR-005 | tests | Behaviour change with no guarding test | info | `[BR-005]` verdicts (decided by the CLI) |

## Severity
`error` — a call or reference that will fail or misbehave at runtime.
`warning` — likely regression or a test that will fail or mislead.
`info` — coverage gap worth recording; never blocking.

## Voice
Neutral, professional, direct. Name the removed or changed contract, the dependent location
(path:line) and why it relies on the old behaviour. No persona flavour.

## Allowed exceptions
- `BR-005` is already `info`, so it never blocks.
- Under `pragmatic` strictness, `BR-003` may be downgraded to `info` when the only callers are
  tests.
```

- [ ] **Step 3: Run the review-panel doc lint and discovery tests**

Run: `cd plugins/review-panel && ../../.venv/bin/python -m pytest tests -q`
Expected: all pass (the new lens has every required section and is discovered as `blast-radius`). If `test_docs.py` reports a missing or misnamed section, fix the heading to match `skills/reviewers/_template.md` exactly.

- [ ] **Step 4: Write the README**

`plugins/concordance/README.md`:
````markdown
# concordance

An owned symbol index for review, in Python and TypeScript. A concordance is the index of
every place a word appears in scripture; this is that, for symbols.

It answers exact questions about a diff, in the CLI, at zero agent tokens:

- **What still relies on what the diff removed?** Deleted symbols, removed parameters, guards
  and decorators, against every remaining reference.
- **Which call sites no longer match a changed signature?** A verdict, not a hint (BR-002).
- **Who calls the changed code, and which tests reach it?** With a pure-refactor classifier,
  so refactors are not reviewed as behaviour changes. Behaviour changes no test reaches are a
  verdict (BR-005).
- **What can't an index see?** Changed literals (SQL, keys, event names) with their other
  occurrences, reordered statements, removed comments.

The `review-procedure` skill tells a reviewer exactly when to use each answer; review-panel's
`blast-radius` lens runs it.

## Use

```bash
python plugins/concordance/scripts/cli.py review-context [--base REF] [--budget 1500]
python plugins/concordance/scripts/cli.py check            # verdicts only; exit 1 on any
python plugins/concordance/scripts/cli.py callers NAME     # did-you-mean on a miss
python plugins/concordance/scripts/cli.py tests NAME [--hops 2]
python plugins/concordance/scripts/cli.py removed | sig-drift | literals | coverage | index
python plugins/concordance/scripts/cli.py setup-ts         # once, for TypeScript
```

The base defaults to the merge-base with the default branch. The index builds lazily on first
use and only re-parses files whose content changed.

## Worktrees

One store per repo (keyed by the git common dir) under
`$CLAUDE_CONFIG_DIR/concordance/`, shared by every worktree. Facts are keyed by file content,
so a new worktree parses only what differs. Each worktree gets its own view, including
uncommitted edits; answers never mention another worktree's paths. Removed worktrees are
garbage-collected lazily. Nothing is written into the repo.

## Requirements

Python 3.11+ (stdlib only). TypeScript needs Node 18+ and `setup-ts`, which installs the
pinned `typescript` 5.6.3 from the committed lockfile with install scripts disabled. Without
it, TypeScript files are reported as not indexed; nothing fails.

## Credits

Ideas borrowed, no code copied: code-review-graph (MIT), graphify (Apache-2.0),
codebase-memory-mcp (MIT), GitNexus (ideas only).
````

- [ ] **Step 5: Register the plugin and bump versions**

In `.claude-plugin/marketplace.json`: change `"version": "1.67.0"` to `"version": "1.68.0"`, and append this object to the `plugins` array (after the last entry):
```json
{
  "name": "concordance",
  "source": "./plugins/concordance",
  "description": "An owned, worktree-native symbol index for Python and TypeScript, built for review: removed contracts, signature drift, callers and guarding tests, detected in the CLI; a review procedure and review-panel lens say when to use them.",
  "category": "engineering",
  "tags": ["code-review", "impact-analysis", "symbols", "callers", "tests", "worktrees", "python", "typescript"]
}
```

In `plugins/review-panel/.claude-plugin/plugin.json`: `"version": "0.1.0"` → `"version": "0.2.0"`.

In `CLAUDE.md`, under `## Plugins`, insert alphabetically after the `chronicle` entry:
```markdown
- **concordance** — an owned, worktree-native symbol index (Python `ast`, TypeScript compiler parser) for review: removed-contract, signature-drift, callers and guarding-test queries in the CLI, with verdicts for drift and untested behaviour changes; ships the review procedure that review-panel's `blast-radius` lens runs (review-procedure)
```

Run: `python3 -c "import json; json.load(open('.claude-plugin/marketplace.json'))" && echo ok`
Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add plugins/concordance/skills plugins/concordance/README.md plugins/review-panel/skills/reviewers/blast-radius.md plugins/review-panel/.claude-plugin/plugin.json .claude-plugin/marketplace.json CLAUDE.md
git commit -m "feat(concordance): review procedure, blast-radius lens, docs and registration"
```

---

### Task 13: Bench harness

**Files:**
- Create: `tests/concordance/bench/README.md`, `tests/concordance/bench/make_case.py`, `tests/concordance/bench/tools-concordance.md`, `tests/concordance/bench/judge.md`
- Test: `tests/concordance/test_bench.py`

**Interfaces:**
- Produces: `make_case.py` CLI: `python make_case.py --source REPO --out DIR (--plant-reverse FIX_SHA | --range BASE HEAD | --patch FILE --on SHA)` building a two-commit case repo whose PR is `HEAD` vs `HEAD~1`; importable `build_case(source: Path, out: Path, *, plant_reverse: str | None = None, range_: tuple[str, str] | None = None, patch: Path | None = None, on: str | None = None) -> Path`.

Case data (which ledger-poc commits, the truth files, results) is **private** and stays local in `$CONCORDANCE_BENCH_DIR` (default `scratch/code-graph/bench`, gitignored). Only the generic harness is committed.

- [ ] **Step 1: Write the failing test**

`tests/concordance/test_bench.py`:
```python
import importlib.util
from pathlib import Path

BENCH = Path(__file__).resolve().parent / "bench" / "make_case.py"
spec = importlib.util.spec_from_file_location("make_case", BENCH)
assert spec and spec.loader
make_case = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_case)


def test_plant_reverse_restores_the_bug_but_keeps_the_tests(tmp_path: Path, make_repo) -> None:
    repo = make_repo({"app.py": "def f():\n    return 1\n", "tests/test_app.py": "x = 0\n"})
    repo.write({"app.py": "def f():\n    return 2  # fixed\n",
                "tests/test_app.py": "x = 1  # new test\n"})
    fix = repo.commit("fix")
    case = make_case.build_case(repo.root, tmp_path / "case", plant_reverse=fix)
    assert (case / "app.py").read_text() == "def f():\n    return 1\n"
    assert (case / "tests/test_app.py").read_text() == "x = 1  # new test\n"
    log = make_case._git(case, "log", "--format=%s")
    assert log.split() == ["pr", "base"]


def test_range_case(tmp_path: Path, make_repo) -> None:
    repo = make_repo({"a.py": "a = 1\n"})
    base = repo.git("rev-parse", "HEAD").strip()
    repo.write({"a.py": "a = 2\n"})
    head = repo.commit("change")
    case = make_case.build_case(repo.root, tmp_path / "case", range_=(base, head))
    assert make_case._git(case, "diff", "HEAD~1", "HEAD", "--stat").strip() != ""
    assert (case / "a.py").read_text() == "a = 2\n"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd plugins/concordance && ../../.venv/bin/python -m pytest ../../tests/concordance/test_bench.py -q`
Expected: FAIL with `FileNotFoundError` for `bench/make_case.py`

- [ ] **Step 3: Implement `make_case.py`**

`tests/concordance/bench/make_case.py`:
```python
"""Build a bench case: a fresh two-commit repo whose PR is HEAD vs HEAD~1, with no history to
read the fix from. Modes: plant a bug by reversing a fix's non-test part; replay a commit
range; or apply a hand-written patch on a commit.
"""
from __future__ import annotations

import argparse
import io
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

_TEST = re.compile(r"(^|/)(tests?|__tests__)/|(^|/)test_[^/]*\.py$|_test\.py$|\.(test|spec)\.[cm]?tsx?$")


def _git(cwd: Path, *args: str, input: bytes | None = None) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], input=input, check=True,
                          capture_output=True).stdout.decode()


def _export(source: Path, sha: str, out: Path) -> None:
    data = subprocess.run(["git", "-C", str(source), "archive", sha], check=True,
                          capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(out, filter="data")


def _commit(case: Path, msg: str) -> None:
    _git(case, "add", "-A")
    _git(case, "-c", "user.email=bench@local", "-c", "user.name=bench", "commit", "-q",
         "--allow-empty", "-m", msg)


def build_case(source: Path, out: Path, *, plant_reverse: str | None = None,
               range_: tuple[str, str] | None = None, patch: Path | None = None,
               on: str | None = None) -> Path:
    out.mkdir(parents=True)
    _git(out, "init", "-q", "-b", "main")
    if plant_reverse is not None:
        _export(source, plant_reverse, out)
        _commit(out, "base")
        changed = _git(source, "diff", "--name-only", "-z", f"{plant_reverse}^", plant_reverse)
        for path in [p for p in changed.split("\0") if p and not _TEST.search(p)]:
            target = out / path
            try:
                old = subprocess.run(["git", "-C", str(source), "show", f"{plant_reverse}^:{path}"],
                                     check=True, capture_output=True).stdout
            except subprocess.CalledProcessError:
                target.unlink(missing_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(old)
    elif range_ is not None:
        _export(source, range_[0], out)
        _commit(out, "base")
        for child in out.iterdir():
            if child.name == ".git":
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        _export(source, range_[1], out)
    elif patch is not None and on is not None:
        _export(source, on, out)
        _commit(out, "base")
        _git(out, "apply", str(patch.resolve()))
    else:
        raise SystemExit("choose --plant-reverse, --range, or --patch with --on")
    _commit(out, "pr")
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--plant-reverse")
    p.add_argument("--range", nargs=2, metavar=("BASE", "HEAD"))
    p.add_argument("--patch", type=Path)
    p.add_argument("--on")
    a = p.parse_args()
    case = build_case(a.source, a.out, plant_reverse=a.plant_reverse,
                      range_=tuple(a.range) if a.range else None, patch=a.patch, on=a.on)
    print(case)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Write the bench documents**

`tests/concordance/bench/tools-concordance.md` (the tool sheet substituted into `{TOOLS}` of the spike's reviewer brief for the concordance arm):
````markdown
## Tools

Read, Grep, Glob, `git -C {CASE} ...`, PLUS concordance, an index of this exact repo state.
Follow its review procedure exactly; every step is mandatory and ends in a finding or "clean":

    {CONCORDANCE_SKILL}

Run its CLI from inside the case repo, always with the PR's base:

    cd {CASE} && python {CLI} review-context --base HEAD~1

In your TOOL LOG, list each concordance command once with a one-word verdict
(useful / noise / wrong), and fill in the procedure's step log.
````

`tests/concordance/bench/judge.md`:
````markdown
# Bench judge

You score one reviewer's output against the ground truth for one case. Be strict and literal.

Inputs: the truth (the fixing commit's message and diff, or the hand-written regression's
description), and the reviewer's FINDINGS block.

1. List each distinct defect in the truth. For each: `caught` (a finding names the same
   location or mechanism and the same consequence), `partial` (right location, wrong or vague
   mechanism) or `missed`.
2. For each finding not matching a truth defect: `valid-extra` (a real defect you can confirm
   from the diff) or `false-positive`.
3. Output exactly:

```json
{"case": "<id>", "arm": "<arm>", "defects": [{"truth": "<short>", "verdict": "caught|partial|missed"}],
 "extras": [{"finding": "<short>", "verdict": "valid-extra|false-positive"}]}
```
````

`tests/concordance/bench/README.md`:
````markdown
# concordance bench

Replays review cases as a regression suite: a baseline arm (Read/Grep only) against the
concordance arm (the review procedure), Sonnet reviewers, identical briefs.

**Case data is private and local:** `$CONCORDANCE_BENCH_DIR` (default
`scratch/code-graph/bench`, gitignored) holds `reviewer-brief.md`, `tools-baseline.md`,
`truth/<case>.txt`, `cases.tsv`, `results/` and `runs.tsv`. Nothing here names private code.

## Build cases

```bash
python tests/concordance/bench/make_case.py --source <repo> --out <dir>/A --plant-reverse <fix-sha>
python tests/concordance/bench/make_case.py --source <repo> --out <dir>/D --range <base> <head>
python tests/concordance/bench/make_case.py --source <repo> --out <dir>/H1 --patch h1.patch --on <sha>
```

`--plant-reverse` removes a fix's explaining comments along with the fix, which makes cases
easier than real life. Hand-written regressions (`--patch`) keep the comments; prefer them.

## Run

For each case × arm, dispatch one Sonnet reviewer with `reviewer-brief.md`, `{TOOLS}` replaced
by `tools-baseline.md` or `tools-concordance.md` (`{CLI}` = the absolute path to
`plugins/concordance/scripts/cli.py`, `{CONCORDANCE_SKILL}` = the text of
`plugins/concordance/skills/review-procedure/SKILL.md`). Record agent id, tokens, tool uses
and duration in `runs.tsv`. Then dispatch one Sonnet judge per result with `judge.md`.

## Pass criteria (spec, "Success criteria")

The concordance arm catches at least every defect the baseline catches, with fewer tokens or
more caught defects overall, and the clean case raises no error or warning finding.
````

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd plugins/concordance && ../../.venv/bin/python -m pytest ../../tests/concordance/test_bench.py -q`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add tests/concordance/bench tests/concordance/test_bench.py
git commit -m "test(concordance): bench harness for baseline vs review-procedure replays"
```

---

### Task 14: Verification: performance and the bench replay

This task is run by the controller session, not delegated as a TDD task: it measures and
judges, it does not change code (any defect it finds becomes a fix task with a covering test).

**Files:**
- Local only: `$CONCORDANCE_BENCH_DIR/` (cases, results, `runs.tsv`)
- Overseer card WF-272: `## Verification` section

- [ ] **Step 1: Full gate**

Run: `./tests/run.sh` from the repo root, then `cd plugins/concordance && ../../.venv/bin/ruff check scripts ../../tests/concordance && ../../.venv/bin/mypy scripts`
Expected: every suite passes; ruff and mypy clean. Paste the summary lines into the card's Verification section.

- [ ] **Step 2: Performance on ledger-poc**

Locate the ledger-poc checkout (`~/repos/ledger-poc`; ask the user if it is elsewhere). With a throwaway store:
```bash
cd ~/repos/ledger-poc
export CONCORDANCE_DB="$(mktemp -d)/bench.db"
/usr/bin/time -p python ~/repos/pip-skills/plugins/concordance/scripts/cli.py index --base HEAD
echo "# touch" >> $(git ls-files '*.py' | head -1)
/usr/bin/time -p python ~/repos/pip-skills/plugins/concordance/scripts/cli.py index --base HEAD
git checkout -- $(git ls-files '*.py' | head -1)
/usr/bin/time -p python ~/repos/pip-skills/plugins/concordance/scripts/cli.py review-context --base HEAD~5 > /dev/null
```
(`git checkout -- <file>` here only reverts the one-line touch just made in ledger-poc, a repo this plan never edits otherwise; confirm with the user before running it.)
Expected (spec targets): cold build ≤ 45 s; the one-file incremental index ≤ 200 ms of parse time above the fixed git-listing cost (report both numbers); warm `review-context` ≤ 2 s. Record the numbers and the store size. A miss is reported, not hidden: add a fix task.

- [ ] **Step 3: Rebuild the four spike cases and write three hand-written regressions**

Rebuild A-D with `make_case.py` from the commits recorded in `$CONCORDANCE_BENCH_DIR/truth/*.txt` (first line of each is the commit sha: A/B/C `--plant-reverse <sha>`, D `--range <sha>^ <sha>`). Then dispatch one Sonnet agent to write three hand-written regressions against ledger-poc that **keep their explaining comments**: one removed guard, one removed keyword still passed by a caller, one reordered write sequence. Each is a patch file plus a truth file in `$CONCORDANCE_BENCH_DIR`, built with `--patch … --on <sha>`.

- [ ] **Step 4: Run both arms and judge**

For each of the 7 cases, dispatch the baseline and concordance arms (Sonnet, identical brief, per `tests/concordance/bench/README.md`), then one Sonnet judge per result. Record tokens and verdicts in `runs.tsv`.

- [ ] **Step 5: Verdict**

Write the result table (case × arm: caught/partial/missed, extras, tokens) into the card's Verification section with a one-paragraph verdict against the spec's success criteria: concordance catches ≥ baseline, at fewer tokens or more catches, and D stays quiet. If it fails, say which step of the procedure or which query let it down; that drives the next card, not a quiet re-run.
