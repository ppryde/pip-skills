# concordance shadow measurement (WF-273, sub-project 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replay a finished Claude Code session against concordance's real CLI and record, per tool call, the agent's actual token cost beside concordance's counterfactual cost and latency, as numbers only; let chronicle pull those numbers and add carried cost.

**Architecture:** concordance gains `--json` on its query commands, a `replay` command (transcript reader → estimators → real-CLI subprocess runner → numeric rows stored in `usage.db`), and a `mode` flag. chronicle gains an optional, never-fatal sync step that calls `concordance replay` for finished sessions, a `concordance_rows` table, and a `chronicle concordance` report verb that prices carried cost. The dependency runs one way: chronicle → concordance's CLI.

**Tech Stack:** Python 3.11 stdlib only (argparse, sqlite3, subprocess, json), pytest, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-10-12-concordance-delivery-design.md` (sections 1, 2 rows 2 and pass-through, 4, 5).

## Global Constraints

- Python 3.11+, stdlib only; no new dependencies in either plugin.
- Never block, deny, rewrite or replace an agent tool call.
- Replay output and every stored row hold numbers and labels only: no path, pattern, command line or content.
- Transcripts are read in memory and dropped; nothing from them is written except those numbers.
- A session counts as finished only when its transcript has been idle 900 s (chronicle's `LIVE_HORIZON_SECONDS`); `replay` refuses an unfinished one with exit 2 unless `--force`.
- Tokens on both sides use concordance's `scripts.render.est_tokens` (characters / 3, rounded up).
- chronicle stays a statistics store; it never imports concordance and only runs its CLI.
- chronicle's sync never fails because of concordance; kill switch `CHRONICLE_NO_CONCORDANCE=1`.
- Every test pins `CLAUDE_CONFIG_DIR`, `CONCORDANCE_DB`, `CONCORDANCE_USAGE_DB` (and `CHRONICLE_DB`) to `tmp_path` (existing autouse fixtures do this; keep them).
- Concordance gates: from `plugins/concordance`: `../../.venv/bin/python -m pytest`, `../../.venv/bin/python -m ruff check . ../../tests/concordance`, `../../.venv/bin/python -m mypy scripts`. Chronicle gates: same from `plugins/chronicle` with `../../tests/chronicle`.
- Git: never `git stash`, `git checkout <file>`, `git reset`, `git clean`, or push. Stage files by explicit path. Never stage `.devcontainer/devcontainer-lock.json`, `SECURITY.md`, `plugins/context-vigil-mod/tsconfig.json`, `plugins/.DS_Store`.
- Commit trailer (every commit):
  `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_014wmY6mtSJuwaUZhLicPW4n`

## Review Focus

1. A tool_result whose `content` is a list of blocks (text + image) rather than a string: actual tokens count the text blocks only, and replay does not crash. → Task 3 test `test_list_content_counts_text_only`.
2. A session whose `cwd` is not a git repo, or no longer exists: rows come back `covered: false`, exit 0, no traceback. → Task 4 test `test_missing_cwd_is_not_covered`.
3. The concordance CLI is missing, hangs or exits 2 during `chronicle sync`: sync completes, the session is retried next time. → Task 7 tests `test_sync_survives_replay_failure`, `test_failed_session_is_retried`.
4. A Grep pattern full of regex metacharacters (`foo.*\(`) or shell characters (`; rm -rf`): not treated as a symbol, never reaches a shell. → Task 4 test `test_regex_pattern_is_not_a_symbol`.
5. Malformed JSON lines or a truncated last line in a transcript: skipped and counted, replay still emits the rest. → Task 3 test `test_bad_lines_are_skipped`.

---

## File structure

concordance (`plugins/concordance/scripts/`):

| File | Responsibility |
|---|---|
| `cli.py` (modify) | argparse parser and `main` dispatch only |
| `commands/__init__.py` (create) | empty |
| `commands/common.py` (create) | `repo_key_of`, `say`, `session_id`, `log_event`, `utf8_streams` (moved from cli.py) |
| `commands/queries.py` (create) | `diff_command`, `name_command`, `check_text`, `miss_text` (moved), fill a `facts` dict for `--json` |
| `commands/records.py` (create) | `record_review`, `stats`, `parse_steps` (moved), `mode` |
| `replay/__init__.py` (create) | empty |
| `replay/transcript.py` (create) | locate session files; walk tool calls in memory |
| `replay/runner.py` (create) | run the real CLI with `--json`, time it |
| `replay/estimators.py` (create) | `Estimator` protocol, `callers` and `passthrough` estimators, registry |
| `replay/drift.py` (create) | blob hash of a full Read vs the file now |
| `replay/core.py` (create) | `replay_session` → rows; answerable judgement driver |
| `replay/store.py` (create) | `replay_rows` table in `usage.db`; save, summarise |
| `modes.py` (create) | per-session / repo-default mode flags |

chronicle (`plugins/chronicle/scripts/`):

| File | Responsibility |
|---|---|
| `store.py` (modify) | `concordance_rows` table in `_SCHEMA` |
| `concordance.py` (create) | find the CLI, run replay, store rows, sync step |
| `report.py` (modify) | `concordance(conn, …)` carried-cost report |
| `cli.py` (modify) | call the sync step after sync; `concordance` verb |

Tests: `tests/concordance/test_json_output.py`, `test_replay_transcript.py`, `test_replay_estimators.py`, `test_replay_cli.py`, `test_modes.py`; `tests/concordance/fixtures/` helpers in `tests/concordance/replay_support.py`; `tests/chronicle/test_concordance.py`.

---

### Task 1: Split cli.py into a commands package and tag replay-origin usage

**Files:**
- Modify: `plugins/concordance/scripts/cli.py`
- Create: `plugins/concordance/scripts/commands/__init__.py`, `commands/common.py`, `commands/queries.py`, `commands/records.py`
- Modify: `plugins/concordance/scripts/usage.py` (exclude `origin=replay` events from `report`)
- Test: `tests/concordance/test_usage.py` (add one test); existing `tests/concordance/test_cli.py` must pass unchanged

**Interfaces:**
- Produces: `scripts.commands.common.log_event(command: str, cwd: Path, view_id: str | None, started: float, text: str, code: int, payload: dict[str, object]) -> None` — adds `payload["origin"] = os.environ["CONCORDANCE_ORIGIN"]` when that variable is set.
- Produces: `scripts.commands.queries.diff_command(args, cwd, stats, facts) -> tuple[str, int, str]` and `name_command(args, cwd, stats, facts) -> tuple[str, int, str]` (signature gains `facts: dict[str, object]`, unused until Task 2: pass `{}`).
- Produces: `scripts.cli.main(argv: list[str] | None = None) -> int` unchanged; `scripts.cli._parser()` unchanged in behaviour.
- Produces: `usage.report(...)` skips events whose payload has `"origin": "replay"`.

- [ ] **Step 1: Write the failing usage test**

Add to `tests/concordance/test_usage.py`:

```python
def test_replay_origin_events_are_excluded(tmp_path: Path) -> None:
    db = tmp_path / "u.db"
    usage.record("callers", "r", "v", 10, 5, 0, {}, session="s", path=db)
    usage.record("callers", "r", "v", 10, 5, 0, {"origin": "replay"}, session="s", path=db)
    rep = usage.report(path=db)
    assert rep["commands"]["callers"]["runs"] == 1
```

(`from pathlib import Path` and `from scripts import usage` are already imported in that file; add them if not.)

- [ ] **Step 2: Run it and see it fail**

Run (from `plugins/concordance`): `../../.venv/bin/python -m pytest ../../tests/concordance/test_usage.py::test_replay_origin_events_are_excluded -v`
Expected: FAIL, `assert 2 == 1`.

- [ ] **Step 3: Exclude replay-origin events in `usage.report`**

In `usage.report`, directly after the `if not isinstance(p, dict): ... continue` block, add:

```python
        if p.get("origin") == "replay":  # replay's own CLI calls are measurement, not usage
            continue
```

- [ ] **Step 4: Move cli helpers into the commands package**

Create `scripts/commands/__init__.py` (empty).

Create `scripts/commands/common.py` with the bodies of cli.py's `_repo`, `_say`, `_session`, `_log`, `_utf8_streams`, renamed `repo_key_of`, `say`, `session_id`, `log_event`, `utf8_streams`. `log_event` adds the origin tag:

```python
"""Helpers shared by every CLI command group."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from scripts import gitio, paths, usage
from scripts.render import est_tokens


def repo_key_of(cwd: Path) -> str:
    try:
        return paths.repo_key(gitio.common_dir(cwd))
    except gitio.GitError:
        return ""


def say(text: str) -> None:
    """Print to stdout; a closed pipe (`| head`) is a quiet end, not a traceback."""
    try:
        print(text)
        sys.stdout.flush()
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())


def session_id() -> str:
    return os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID", "")


def log_event(command: str, cwd: Path, view_id: str | None, started: float, text: str,
              code: int, payload: dict[str, object]) -> None:
    origin = os.environ.get("CONCORDANCE_ORIGIN")
    if origin:
        payload = {**payload, "origin": origin}
    try:
        usage.record(command, repo_key_of(cwd), view_id,
                     int((time.monotonic() - started) * 1000), est_tokens(text), code,
                     payload, session=session_id())
    except Exception:  # noqa: BLE001, S110 - the usage log must never fail a query
        pass


def utf8_streams() -> None:
    """Never let an odd terminal encoding turn output into a traceback."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
```

Create `scripts/commands/queries.py` holding cli.py's `_diff_command`, `_check`, `_name_command`, `_miss` renamed `diff_command`, `check_text`, `name_command`, `miss_text`, with the imports they need moved from cli.py, and a new last parameter `facts: dict[str, object]` on `diff_command` and `name_command` (unused in this task).

Create `scripts/commands/records.py` holding `_record_review`, `_stats`, `_parse_steps` renamed `record_review`, `stats`, `parse_steps`, using `common.repo_key_of`, `common.say`, `common.session_id`.

Reduce `cli.py` to: the sys.path shim, `DEFAULT_BUDGET`, `REVIEW_BUDGET`, `DEFAULT_DEADLINE`, `_parser()`, and `main()`, which calls `common.utf8_streams()`, dispatches `setup-ts` / `record-review` / `stats` to their functions, and otherwise:

```python
    started = time.monotonic()
    stats: dict[str, object] = {}
    facts: dict[str, object] = {}
    try:
        if args.command in ("callers", "tests", "coverage"):
            text, code, view_id = queries.name_command(args, cwd, stats, facts)
        else:
            text, code, view_id = queries.diff_command(args, cwd, stats, facts)
    except (gitio.GitError, LockTimeout) as exc:
        print(f"concordance: {exc}", file=sys.stderr)
        common.log_event(args.command, cwd, None, started, "", 2, {"error": type(exc).__name__})
        return 2
    except Exception as exc:  # noqa: BLE001 - internal error: exit 2, never a bare traceback
        print(f"concordance: internal error: {exc!r}", file=sys.stderr)
        common.log_event(args.command, cwd, None, started, "", 2, {"error": type(exc).__name__})
        return 2
    common.say(text)
    common.log_event(args.command, cwd, view_id, started, text, code, stats)
    return code
```

`queries.py` needs `REVIEW_BUDGET`/`DEFAULT_BUDGET` only through `args`, so it must not import `cli` (no cycle).

- [ ] **Step 5: Run the whole concordance suite, ruff and mypy**

Run (from `plugins/concordance`): `../../.venv/bin/python -m pytest -q && ../../.venv/bin/python -m ruff check . ../../tests/concordance && ../../.venv/bin/python -m mypy scripts`
Expected: all pass (155 tests), ruff and mypy clean. `test_setup_ts_*` still import `scripts.cli` and call `cli_mod.main`.

- [ ] **Step 6: Commit**

```bash
git add plugins/concordance/scripts/cli.py plugins/concordance/scripts/commands plugins/concordance/scripts/usage.py tests/concordance/test_usage.py
git commit -m "refactor(concordance): split the CLI into a commands package; replay-origin usage is not usage"
```

---

### Task 2: `--json` on every query command

**Files:**
- Modify: `plugins/concordance/scripts/cli.py` (add `--json` to every `add(...)` command)
- Modify: `plugins/concordance/scripts/commands/queries.py` (fill `facts`)
- Test: `tests/concordance/test_json_output.py`

**Interfaces:**
- Consumes: Task 1's `facts` parameter.
- Produces: with `--json`, every query command prints exactly one JSON object:

```json
{"command": "callers", "exit_code": 0, "est_tokens": 42, "root": "/abs/repo",
 "view_id": "…", "found": true, "target": "app.svc.refund", "definition": "app/svc.py",
 "hits": [{"path": "app/api.py", "line": 5}], "sections": [{"title": "…", "count": 1}],
 "verdicts": 0}
```

  `est_tokens` is `est_tokens(text)` of the exact text the same command prints without `--json`; `found`/`target`/`definition`/`hits` appear for `callers` and `tests`; `sections` and `verdicts` for diff commands. Paths are repo-root relative. The usage log records the same `est_tokens` as the text form.

- [ ] **Step 1: Write the failing tests**

Create `tests/concordance/test_json_output.py`:

```python
import json

from scripts.render import est_tokens
from test_cli import BASE, cli


def test_callers_json_matches_text_size_and_names_hits(make_repo) -> None:
    repo = make_repo(BASE)
    text = cli(repo.root, "callers", "refund")
    js = cli(repo.root, "callers", "refund", "--json")
    assert js.returncode == 0, js.stderr
    doc = json.loads(js.stdout)
    assert doc["command"] == "callers" and doc["found"] is True
    assert doc["est_tokens"] == est_tokens(text.stdout.rstrip("\n"))
    assert doc["definition"] == "app/svc.py"
    assert {"path": "app/api.py", "line": 5} in doc["hits"]
    assert doc["root"] == str(repo.root.resolve())


def test_callers_json_miss_is_not_found(make_repo) -> None:
    repo = make_repo(BASE)
    doc = json.loads(cli(repo.root, "callers", "nope_nothing", "--json").stdout)
    assert doc["found"] is False and doc["hits"] == []


def test_check_json_counts_verdicts_and_keeps_exit_code(make_repo) -> None:
    repo = make_repo(BASE)
    repo.git("checkout", "-q", "-b", "feat")
    repo.write({"app/svc.py": "def refund(loan, amount):\n    return amount\n\n\n"
                              "def unused():\n    return 1\n"})
    js = cli(repo.root, "check", "--json")
    assert js.returncode == 1
    doc = json.loads(js.stdout)
    assert doc["exit_code"] == 1 and doc["verdicts"] >= 1


def test_review_context_json_lists_sections(make_repo) -> None:
    repo = make_repo(BASE)
    repo.git("checkout", "-q", "-b", "feat")
    repo.write({"app/svc.py": "def refund(loan, amount):\n    return amount\n\n\n"
                              "def unused():\n    return 1\n"})
    doc = json.loads(cli(repo.root, "review-context", "--json").stdout)
    assert doc["sections"] and all({"title", "count"} <= set(s) for s in doc["sections"])
```

`tests/concordance` has `__init__.py`; if `from test_cli import ...` fails to import, use `from tests.concordance.test_cli import BASE, cli` — match how other test modules import shared helpers (check `test_bench.py`). If neither works, copy `BASE` and `cli` into the new file verbatim.

- [ ] **Step 2: Run and see them fail**

Run: `../../.venv/bin/python -m pytest ../../tests/concordance/test_json_output.py -v`
Expected: FAIL, `unrecognized arguments: --json`.

- [ ] **Step 3: Add the flag**

In `cli._parser`'s inner `add(...)`, append `sp.add_argument("--json", action="store_true", help="one JSON object instead of text")`.

- [ ] **Step 4: Fill `facts` in queries.py**

In `name_command`, after `vi = ViewIndex(store, view)`:

```python
    facts.update(root=str(view.root), view_id=view.view_id, found=False, target=None,
                 definition=None, hits=[])
```

(`View` has a `root` attribute; if it is named differently, use the repo root that `worktree_view(cwd)` computed — read `scripts/views.py`.) When `found.target` is set: `facts.update(found=True, target=q, definition=vi.path_of(q))`; for callers `facts["hits"] = [{"path": h.path, "line": h.line} for h in hits]`; for tests `facts["hits"] = [{"path": t.path, "line": t.line} for t in tests]`.

In `diff_command`, after `ctx = build(...)`:

```python
    facts.update(root=str(ctx.root), view_id=view_id, verdicts=len(verdicts(ctx)), sections=[])
```

and where sections are built (`by_command` branch) set `facts["sections"] = [{"title": s.title, "count": s.count} for s in sections]`. For `review-context`, collect the sections `render_context` uses; if `render_context` builds them internally, add an optional `sections_out: list[Section] | None = None` parameter to `render_context` in `scripts/review.py` that it extends with the sections it rendered.

- [ ] **Step 5: Print JSON in `main`**

Replace `common.say(text)` with:

```python
    if args.json:
        facts.update(command=args.command, exit_code=code, est_tokens=est_tokens(text))
        common.say(json.dumps(facts, sort_keys=True))
    else:
        common.say(text)
```

(`est_tokens` from `scripts.render`, `json` imported.) The usage log line stays `log_event(..., text, ...)` so both forms log the same size.

- [ ] **Step 6: Run the suite, ruff, mypy**

Run: `../../.venv/bin/python -m pytest -q && ../../.venv/bin/python -m ruff check . ../../tests/concordance && ../../.venv/bin/python -m mypy scripts`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add plugins/concordance/scripts/cli.py plugins/concordance/scripts/commands/queries.py plugins/concordance/scripts/review.py tests/concordance/test_json_output.py
git commit -m "feat(concordance): --json on every query command, sized as the text the agent would read"
```

---

### Task 3: Transcript reader (in memory)

**Files:**
- Create: `plugins/concordance/scripts/replay/__init__.py` (empty), `replay/transcript.py`
- Create: `tests/concordance/replay_support.py` (fixture transcript builder)
- Test: `tests/concordance/test_replay_transcript.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True)
class ToolCall:
    tool_use_id: str
    agent_id: str          # "" for the main agent, else the subagent file's agent id
    name: str              # "Read", "Grep", "Bash", ...
    input: dict[str, object]
    result_text: str       # text blocks of the tool_result joined with "\n"; "" if none
    cwd: str               # the record's cwd, "" if absent
    seq: int               # order within its agent's transcript, from 0

@dataclass
class Session:
    session_id: str
    calls: list[ToolCall]
    bad_lines: int

def session_files(session_id: str, projects: Path | None = None,
                  main: Path | None = None) -> list[tuple[str, Path]]
    # [("", main.jsonl), ("<agent id>", subagents/agent-<id>.jsonl), ...]; projects defaults to
    # paths.config_dir() / "projects"; `main` names the main transcript directly (its
    # subagents are still found beside it); raises FileNotFoundError when it does not exist
def is_finished(files: list[tuple[str, Path]], now: float | None = None) -> bool
    # every file's mtime is at least IDLE_S = 900 seconds old
def load(session_id: str, files: list[tuple[str, Path]]) -> Session
```

- [ ] **Step 1: Write the fixture builder**

Create `tests/concordance/replay_support.py`:

```python
"""Hand-built Claude Code transcripts for replay tests. Shapes copied from real transcripts:
assistant records carry message.content tool_use blocks; user records carry tool_result blocks."""
from __future__ import annotations

import json
import os
from pathlib import Path


class Transcript:
    def __init__(self, projects: Path, session_id: str, cwd: Path) -> None:
        self.dir = projects / "-fixture"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id
        self.cwd = str(cwd)
        self.records: list[dict[str, object]] = []
        self.agents: dict[str, list[dict[str, object]]] = {}
        self._n = 0

    def call(self, name: str, inp: dict[str, object], result: object,
             agent: str = "") -> str:
        self._n += 1
        tid = f"toolu_{self._n:04d}"
        target = self.agents.setdefault(agent, []) if agent else self.records
        target.append({"type": "assistant", "sessionId": self.session_id, "cwd": self.cwd,
                       "message": {"role": "assistant", "content": [
                           {"type": "tool_use", "id": tid, "name": name, "input": inp}]}})
        target.append({"type": "user", "sessionId": self.session_id, "cwd": self.cwd,
                       "message": {"role": "user", "content": [
                           {"type": "tool_result", "tool_use_id": tid, "content": result}]}})
        return tid

    def write(self, age_s: float = 3600.0, extra_lines: list[str] | None = None) -> Path:
        main = self.dir / f"{self.session_id}.jsonl"
        lines = [json.dumps(r) for r in self.records] + list(extra_lines or [])
        main.write_text("\n".join(lines) + "\n", encoding="utf-8")
        paths = [main]
        for agent, recs in self.agents.items():
            sub = self.dir / self.session_id / "subagents" / f"agent-{agent}.jsonl"
            sub.parent.mkdir(parents=True, exist_ok=True)
            sub.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
            paths.append(sub)
        for p in paths:
            t = p.stat().st_mtime - age_s
            os.utime(p, (t, t))
        return main
```

- [ ] **Step 2: Write the failing tests**

Create `tests/concordance/test_replay_transcript.py`:

```python
import time
from pathlib import Path

import pytest

from replay_support import Transcript  # or tests.concordance.replay_support, as in Task 2
from scripts.replay import transcript as tr


def _projects(tmp_path: Path) -> Path:
    return tmp_path / "config" / "projects"


def test_pairs_calls_with_results_across_subagents(tmp_path: Path) -> None:
    t = Transcript(_projects(tmp_path), "s1", tmp_path)
    t.call("Read", {"file_path": "/x/a.py"}, "     1\tprint(1)\n")
    t.call("Grep", {"pattern": "refund"}, "Found 1 file\n/x/a.py", agent="abc")
    t.write()
    files = tr.session_files("s1", _projects(tmp_path))
    s = tr.load("s1", files)
    assert [(c.name, c.agent_id, c.seq) for c in s.calls] == [("Read", "", 0), ("Grep", "abc", 0)]
    assert s.calls[0].result_text.endswith("print(1)\n") and s.calls[0].cwd == str(tmp_path)


def test_list_content_counts_text_only(tmp_path: Path) -> None:
    t = Transcript(_projects(tmp_path), "s2", tmp_path)
    t.call("Read", {"file_path": "/x/i.png"},
           [{"type": "text", "text": "hello"}, {"type": "image", "source": {"data": "Zm9v"}}])
    t.write()
    s = tr.load("s2", tr.session_files("s2", _projects(tmp_path)))
    assert s.calls[0].result_text == "hello"


def test_bad_lines_are_skipped(tmp_path: Path) -> None:
    t = Transcript(_projects(tmp_path), "s3", tmp_path)
    t.call("Bash", {"command": "ls"}, "a\nb")
    t.write(extra_lines=["{not json", '{"type": "assistant", "message": {"content": [{"ty'])
    s = tr.load("s3", tr.session_files("s3", _projects(tmp_path)))
    assert len(s.calls) == 1 and s.bad_lines == 2


def test_unanswered_call_has_empty_result(tmp_path: Path) -> None:
    t = Transcript(_projects(tmp_path), "s4", tmp_path)
    t.call("Bash", {"command": "ls"}, "ok")
    t.records.pop()  # drop the tool_result
    t.write()
    s = tr.load("s4", tr.session_files("s4", _projects(tmp_path)))
    assert s.calls[0].result_text == ""


def test_finished_needs_900s_idle(tmp_path: Path) -> None:
    t = Transcript(_projects(tmp_path), "s5", tmp_path)
    t.call("Bash", {"command": "ls"}, "ok")
    t.write(age_s=60)
    files = tr.session_files("s5", _projects(tmp_path))
    assert not tr.is_finished(files)
    assert tr.is_finished(files, now=time.time() + 900)


def test_missing_session_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        tr.session_files("nope", _projects(tmp_path))
    with pytest.raises(FileNotFoundError):
        tr.session_files("nope", main=tmp_path / "nope.jsonl")


def test_explicit_main_still_finds_subagents(tmp_path: Path) -> None:
    t = Transcript(_projects(tmp_path), "s6", tmp_path)
    t.call("Bash", {"command": "ls"}, "ok", agent="zz")
    main = t.write()
    assert [a for a, _ in tr.session_files("s6", main=main)] == ["", "zz"]
```

- [ ] **Step 3: Run and see them fail**

Run: `../../.venv/bin/python -m pytest ../../tests/concordance/test_replay_transcript.py -v`
Expected: FAIL, `No module named 'scripts.replay'`.

- [ ] **Step 4: Implement `replay/transcript.py`**

```python
"""Read a session's transcripts in memory: tool calls paired with their results. Nothing read
here is ever written anywhere; callers keep only numbers derived from it."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from scripts.paths import config_dir

IDLE_S = 900.0  # chronicle's live horizon: a transcript idle this long is finished


@dataclass(frozen=True)
class ToolCall:
    tool_use_id: str
    agent_id: str
    name: str
    input: dict[str, object]
    result_text: str
    cwd: str
    seq: int


@dataclass
class Session:
    session_id: str
    calls: list[ToolCall] = field(default_factory=list)
    bad_lines: int = 0


def session_files(session_id: str, projects: Path | None = None,
                  main: Path | None = None) -> list[tuple[str, Path]]:
    if main is None:
        root = projects or config_dir() / "projects"
        mains = sorted(root.glob(f"*/{session_id}.jsonl"))
        if not mains:
            raise FileNotFoundError(f"no transcript for session {session_id} under {root}")
        main = mains[0]
    elif not main.is_file():
        raise FileNotFoundError(f"no transcript at {main}")
    files: list[tuple[str, Path]] = [("", main)]
    for sub in sorted((main.parent / session_id / "subagents").glob("agent-*.jsonl")):
        files.append((sub.stem.removeprefix("agent-"), sub))
    return files


def is_finished(files: list[tuple[str, Path]], now: float | None = None) -> bool:
    t = time.time() if now is None else now
    return all(t - p.stat().st_mtime >= IDLE_S for _, p in files)


def _text_of(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b["text"] for b in content
                         if isinstance(b, dict) and b.get("type") == "text"
                         and isinstance(b.get("text"), str))
    return ""


def _blocks(record: dict[str, object]) -> list[dict[str, object]]:
    msg = record.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def load(session_id: str, files: list[tuple[str, Path]]) -> Session:
    session = Session(session_id)
    for agent_id, path in files:
        pending: dict[str, tuple[str, dict[str, object], str]] = {}
        order: list[str] = []
        results: dict[str, str] = {}
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    session.bad_lines += 1
                    continue
                if not isinstance(rec, dict):
                    session.bad_lines += 1
                    continue
                cwd = rec.get("cwd") if isinstance(rec.get("cwd"), str) else ""
                for b in _blocks(rec):
                    if b.get("type") == "tool_use" and isinstance(b.get("id"), str):
                        inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                        pending[b["id"]] = (str(b.get("name", "")), inp, str(cwd))
                        order.append(b["id"])
                    elif b.get("type") == "tool_result" and isinstance(b.get("tool_use_id"), str):
                        results[b["tool_use_id"]] = _text_of(b.get("content"))
        for seq, tid in enumerate(order):
            name, inp, cwd = pending[tid]
            session.calls.append(ToolCall(tid, agent_id, name, inp, results.get(tid, ""),
                                          cwd, seq))
    return session
```

- [ ] **Step 5: Run the tests, ruff, mypy**

Run: `../../.venv/bin/python -m pytest ../../tests/concordance/test_replay_transcript.py -v && ../../.venv/bin/python -m ruff check . ../../tests/concordance && ../../.venv/bin/python -m mypy scripts`
Expected: PASS, clean.

- [ ] **Step 6: Commit**

```bash
git add plugins/concordance/scripts/replay tests/concordance/replay_support.py tests/concordance/test_replay_transcript.py
git commit -m "feat(concordance): read a session's tool calls from its transcripts, in memory"
```

---

### Task 4: Runner, estimators and drift

**Files:**
- Create: `plugins/concordance/scripts/replay/runner.py`, `replay/estimators.py`, `replay/drift.py`
- Test: `tests/concordance/test_replay_estimators.py`

**Interfaces:**
- Consumes: Task 2's JSON (`found`, `definition`, `hits`, `root`, `est_tokens`, `exit_code`); Task 3's `ToolCall`.
- Produces:

```python
# runner.py
@dataclass(frozen=True)
class Answer:
    ok: bool                 # the CLI ran and printed parseable JSON
    doc: dict[str, object]   # parsed JSON ({} when not ok)
    latency_ms: int
    exit_code: int
CLI_PATH: Path               # this plugin's scripts/cli.py
def run(args: list[str], cwd: str, timeout: float = 60.0) -> Answer
    # sys.executable CLI_PATH *args --json, env CONCORDANCE_ORIGIN=replay, never a shell

# estimators.py
@dataclass(frozen=True)
class Query:
    estimator: str           # "callers" | "passthrough"
    kind: str                # "grep" | "concordance"
    args: list[str]          # CLI args without --json; [] for passthrough
@dataclass(frozen=True)
class Estimate:
    covered: bool
    concordance_tokens: int
    latency_ms: int
    exit_code: int
    answerable: str          # "yes" | "no" | "unknown"
def match(call: ToolCall) -> Query | None
def estimate(query: Query, call: ToolCall, later: list[ToolCall]) -> Estimate
    # later = calls of the same agent with a higher seq

# drift.py
def full_read_blob(call: ToolCall) -> str | None   # git blob sha of a whole-file Read's content
def drifted(calls: list[ToolCall], path: str, cwd: str) -> str  # "yes" | "no" | "unknown"
```

Rules:
- `callers` matches `Grep` whose `pattern` matches `^[A-Za-z_][A-Za-z0-9_]*$` (a bare identifier). It runs `callers <pattern>`. Not covered when the CLI is not ok, exits 2, or `found` is false. Answerable: let `hit_files` be the paths in the Grep result (lines of `result_text` that are an existing path, or the part before the first `:` of `path:line:text` lines), normalised to repo-root-relative using `doc["root"]`; let `read_after` be repo-relative `file_path`s of later `Read` calls. `opened = hit_files & read_after`. Empty `opened` → `unknown`; `opened ⊆ {h["path"] for h in hits} | {definition}` → `yes`; else `no`.
- `passthrough` matches `Bash` whose `command` contains `concordance` and `cli.py`. It is the agent's own concordance use: covered, `concordance_tokens = est_tokens(call.result_text)`, latency 0, exit 0, answerable `unknown`. It runs nothing.
- `drift.full_read_blob`: only for `Read` calls with no `offset`/`limit` in `input`. Strip the `cat -n` prefix (`^\s*\d+\t`) from each line, rejoin with `\n`, append a trailing newline if the original result ended with one, and hash as git does: `sha1(b"blob %d\0" % len(data) + data)`. `drifted(calls, path, cwd)`: find the last full Read of `path` before; compare with `git hash-object <path>` run in `cwd`; equal → `no`, different → `yes`, no full read or git failure → `unknown`. (Task 5 applies drift to `callers` rows using the Grep hits' definition file.)

- [ ] **Step 1: Write the failing tests**

Create `tests/concordance/test_replay_estimators.py`:

```python
from pathlib import Path

from scripts.replay import drift, estimators, runner
from scripts.replay.transcript import ToolCall
from test_cli import BASE  # same import style as Task 2


def _call(name: str, inp: dict, result: str, cwd: Path, seq: int = 0) -> ToolCall:
    return ToolCall(f"t{seq}", "", name, inp, result, str(cwd), seq)


def test_bare_identifier_grep_matches_callers(tmp_path: Path) -> None:
    q = estimators.match(_call("Grep", {"pattern": "refund"}, "", tmp_path))
    assert q == estimators.Query("callers", "grep", ["callers", "refund"])


def test_regex_pattern_is_not_a_symbol(tmp_path: Path) -> None:
    for pat in ("foo.*\\(", "refund; rm -rf /", "a b", ""):
        assert estimators.match(_call("Grep", {"pattern": pat}, "", tmp_path)) is None


def test_callers_answerable_yes_when_reads_stay_in_callers(make_repo) -> None:
    repo = make_repo(BASE)
    grep = _call("Grep", {"pattern": "refund"},
                 f"Found 2 files\n{repo.root}/app/api.py\n{repo.root}/app/svc.py", repo.root, 0)
    later = [_call("Read", {"file_path": f"{repo.root}/app/api.py"}, "x", repo.root, 1)]
    q = estimators.match(grep)
    assert q is not None
    est = estimators.estimate(q, grep, later)
    assert est.covered and est.concordance_tokens > 0 and est.answerable == "yes"


def test_callers_answerable_no_when_agent_reads_a_non_caller_hit(make_repo) -> None:
    repo = make_repo({**BASE, "docs/notes.py": "# refund is documented here\n"})
    grep = _call("Grep", {"pattern": "refund"},
                 f"{repo.root}/docs/notes.py:1:# refund is documented here", repo.root, 0)
    later = [_call("Read", {"file_path": f"{repo.root}/docs/notes.py"}, "x", repo.root, 1)]
    q = estimators.match(grep)
    assert q is not None
    assert estimators.estimate(q, grep, later).answerable == "no"


def test_missing_cwd_is_not_covered(tmp_path: Path) -> None:
    grep = _call("Grep", {"pattern": "refund"}, "", tmp_path / "gone", 0)
    q = estimators.match(grep)
    assert q is not None
    est = estimators.estimate(q, grep, [])
    assert not est.covered and est.answerable == "unknown"


def test_passthrough_counts_the_agents_own_concordance_call(tmp_path: Path) -> None:
    call = _call("Bash", {"command": "python x/concordance/scripts/cli.py review-context"},
                 "## Touched (3)\n" * 10, tmp_path)
    q = estimators.match(call)
    assert q is not None and q.estimator == "passthrough"
    est = estimators.estimate(q, call, [])
    assert est.covered and est.concordance_tokens > 0


def test_runner_reports_latency_and_never_uses_a_shell(make_repo) -> None:
    repo = make_repo(BASE)
    ans = runner.run(["callers", "refund"], str(repo.root))
    assert ans.ok and ans.exit_code == 0 and ans.latency_ms > 0 and ans.doc["found"] is True


def test_drift_detects_a_changed_file(make_repo) -> None:
    repo = make_repo(BASE)
    seen = "".join(f"{i:>6}\t{line}\n" for i, line in
                   enumerate(BASE["app/api.py"].splitlines(), 1))
    read = _call("Read", {"file_path": str(repo.root / "app/api.py")}, seen, repo.root, 0)
    assert drift.drifted([read], str(repo.root / "app/api.py"), str(repo.root)) == "no"
    repo.write({"app/api.py": "changed = 1\n"})
    assert drift.drifted([read], str(repo.root / "app/api.py"), str(repo.root)) == "yes"
    assert drift.drifted([], str(repo.root / "app/api.py"), str(repo.root)) == "unknown"
```

- [ ] **Step 2: Run and see them fail**

Run: `../../.venv/bin/python -m pytest ../../tests/concordance/test_replay_estimators.py -v`
Expected: FAIL, missing modules.

- [ ] **Step 3: Implement `replay/runner.py`**

```python
"""Run the real concordance CLI for one counterfactual query, as a subprocess, and time it."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

CLI_PATH = Path(__file__).resolve().parent.parent / "cli.py"


@dataclass(frozen=True)
class Answer:
    ok: bool
    doc: dict[str, object] = field(default_factory=dict)
    latency_ms: int = 0
    exit_code: int = 2


def run(args: list[str], cwd: str, timeout: float = 60.0) -> Answer:
    if not cwd or not Path(cwd).is_dir():
        return Answer(False)
    env = {**os.environ, "CONCORDANCE_ORIGIN": "replay"}
    started = time.monotonic()
    try:
        proc = subprocess.run([sys.executable, str(CLI_PATH), *args, "--json"], cwd=cwd,
                              env=env, capture_output=True, text=True, timeout=timeout,
                              check=False)
    except (OSError, subprocess.SubprocessError):
        return Answer(False, latency_ms=int((time.monotonic() - started) * 1000))
    latency = max(1, int((time.monotonic() - started) * 1000))
    try:
        doc = json.loads(proc.stdout)
    except ValueError:
        return Answer(False, latency_ms=latency, exit_code=proc.returncode)
    if not isinstance(doc, dict):
        return Answer(False, latency_ms=latency, exit_code=proc.returncode)
    return Answer(True, doc, latency, proc.returncode)
```

- [ ] **Step 4: Implement `replay/drift.py`**

```python
"""Has a file changed since the agent read it? Compares the blob of a whole-file Read with
the file now. Partial reads cannot tell, so they answer "unknown"."""
from __future__ import annotations

import hashlib
import re
import subprocess

from scripts.replay.transcript import ToolCall

_PREFIX = re.compile(r"^\s*\d+\t")


def full_read_blob(call: ToolCall) -> str | None:
    if call.name != "Read" or "offset" in call.input or "limit" in call.input:
        return None
    text = call.result_text
    body = "\n".join(_PREFIX.sub("", line, count=1) for line in text.splitlines())
    if text.endswith("\n"):
        body += "\n"
    data = body.encode("utf-8")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()  # noqa: S324 - git's id


def drifted(calls: list[ToolCall], path: str, cwd: str) -> str:
    seen = None
    for call in calls:
        if call.name == "Read" and call.input.get("file_path") == path:
            blob = full_read_blob(call)
            if blob is not None:
                seen = blob
    if seen is None:
        return "unknown"
    try:
        now = subprocess.run(["git", "hash-object", "--", path], cwd=cwd, capture_output=True,
                             text=True, timeout=10, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return "no" if now == seen else "yes"
```

- [ ] **Step 5: Implement `replay/estimators.py`**

```python
"""Which tool calls concordance could have answered, what that would have cost, and whether
the answer would have been enough. Each estimator: match(call) -> Query | None and a rule."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from scripts.render import est_tokens
from scripts.replay import runner
from scripts.replay.transcript import ToolCall

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class Query:
    estimator: str
    kind: str
    args: list[str]


@dataclass(frozen=True)
class Estimate:
    covered: bool
    concordance_tokens: int
    latency_ms: int
    exit_code: int
    answerable: str


NOT_COVERED = Estimate(False, 0, 0, 0, "unknown")


def match(call: ToolCall) -> Query | None:
    if call.name == "Grep":
        pattern = call.input.get("pattern")
        if isinstance(pattern, str) and _IDENT.match(pattern):
            return Query("callers", "grep", ["callers", pattern])
    if call.name == "Bash":
        command = call.input.get("command")
        if isinstance(command, str) and "concordance" in command and "cli.py" in command:
            return Query("passthrough", "concordance", [])
    return None


def _rel(path: str, root: str) -> str:
    try:
        return os.path.relpath(os.path.realpath(path), os.path.realpath(root))
    except ValueError:
        return path


def _grep_files(text: str, root: str) -> set[str]:
    files: set[str] = set()
    for line in text.splitlines():
        candidate = line.split(":", 1)[0].strip()
        if candidate and os.path.isfile(os.path.join(root, candidate) if not
                                        os.path.isabs(candidate) else candidate):
            files.add(_rel(candidate if os.path.isabs(candidate)
                           else os.path.join(root, candidate), root))
    return files


def _callers_answerable(doc: dict[str, object], call: ToolCall, later: list[ToolCall]) -> str:
    root = str(doc.get("root", ""))
    hits = doc.get("hits")
    known = {h["path"] for h in hits if isinstance(h, dict) and "path" in h} \
        if isinstance(hits, list) else set()
    if isinstance(doc.get("definition"), str):
        known.add(str(doc["definition"]))
    read_after = {_rel(str(c.input["file_path"]), root) for c in later
                  if c.name == "Read" and isinstance(c.input.get("file_path"), str)}
    opened = _grep_files(call.result_text, root) & read_after
    if not opened:
        return "unknown"
    return "yes" if opened <= known else "no"


def estimate(query: Query, call: ToolCall, later: list[ToolCall]) -> Estimate:
    if query.estimator == "passthrough":
        return Estimate(True, est_tokens(call.result_text), 0, 0, "unknown")
    ans = runner.run(query.args, call.cwd)
    if not ans.ok or ans.exit_code == 2 or ans.doc.get("found") is False:
        return Estimate(False, 0, ans.latency_ms, ans.exit_code, "unknown")
    tokens = ans.doc.get("est_tokens")
    return Estimate(True, int(tokens) if isinstance(tokens, int) else 0, ans.latency_ms,
                    ans.exit_code, _callers_answerable(ans.doc, call, later))
```

- [ ] **Step 6: Run the tests, ruff, mypy**

Run: `../../.venv/bin/python -m pytest ../../tests/concordance/test_replay_estimators.py -v && ../../.venv/bin/python -m ruff check . ../../tests/concordance && ../../.venv/bin/python -m mypy scripts`
Expected: PASS, clean. Fix mypy complaints with explicit `isinstance` narrowing, not `# type: ignore`.

- [ ] **Step 7: Commit**

```bash
git add plugins/concordance/scripts/replay tests/concordance/test_replay_estimators.py
git commit -m "feat(concordance): replay estimators (callers, pass-through), real-CLI runner, read drift"
```

---

### Task 5: `replay` and `mode` commands, rows in usage.db, `stats --replay`

**Files:**
- Create: `plugins/concordance/scripts/replay/core.py`, `replay/store.py`, `plugins/concordance/scripts/modes.py`
- Modify: `plugins/concordance/scripts/cli.py`, `commands/records.py`
- Test: `tests/concordance/test_replay_cli.py`, `tests/concordance/test_modes.py`

**Interfaces:**
- Consumes: Tasks 3-4.
- Produces:

```python
# core.py
ROW_FIELDS = ("session_id", "tool_use_id", "agent_id", "kind", "estimator", "covered",
              "actual_tokens", "concordance_tokens", "latency_ms", "exit_code",
              "answerable", "drifted", "mode")
def replay_session(session: Session, mode: str) -> list[dict[str, object]]
    # one row per tool call; unmatched calls: estimator "", covered False, kind = tool name lowercased

# store.py (usage.db, beside the events table)
def save(rows: list[dict[str, object]], path: Path | None = None) -> None   # replaces by (session_id, tool_use_id)
def summary(days: int = 30, path: Path | None = None, now: float | None = None) -> dict[str, object]
    # {"sessions", "rows", "covered", "by_kind": {kind: {"calls","covered","actual_tokens","concordance_tokens","answerable": {"yes","no","unknown"}, "drifted": n}}}

# modes.py
MODES = ("shadow", "inject")
def set_mode(mode: str, session: str | None, repo: str) -> Path
def get_mode(session: str, repo: str) -> str   # session flag, else repo default, else "shadow"
```

CLI:
- `concordance replay --session ID [--transcript PATH] [--force]` prints a JSON array of rows (always JSON). Exit 2 with a stderr message when the session is not found or not finished (without `--force`).
- `concordance mode {shadow,inject} [--session ID]` prints `mode: <mode> (<scope>)`.
- `concordance stats --replay [--days N]` prints `replay.summary` as JSON with `--json`, else a short table.

- [ ] **Step 1: Write the failing tests**

Create `tests/concordance/test_replay_cli.py`:

```python
import json
import sqlite3
from pathlib import Path

from replay_support import Transcript  # import style as Task 2
from test_cli import BASE, cli


def _session(tmp_path: Path, repo_root: Path, sid: str = "s1", age_s: float = 3600) -> Transcript:
    t = Transcript(tmp_path / "config" / "projects", sid, repo_root)
    t.call("Read", {"file_path": f"{repo_root}/app/api.py"}, "     1\tx\n" * 40)
    t.call("Grep", {"pattern": "refund"}, f"{repo_root}/app/api.py:5:    return refund(")
    t.call("Read", {"file_path": f"{repo_root}/app/api.py"}, "     1\tx\n")
    t.write(age_s=age_s)
    return t


def test_replay_emits_numbers_only(make_repo, tmp_path: Path) -> None:
    repo = make_repo(BASE)
    _session(tmp_path, repo.root)
    out = cli(repo.root, "replay", "--session", "s1")
    assert out.returncode == 0, out.stderr
    rows = json.loads(out.stdout)
    assert [r["kind"] for r in rows] == ["read", "grep", "read"]
    grep = rows[1]
    assert grep["estimator"] == "callers" and grep["covered"] is True
    assert grep["concordance_tokens"] > 0 and grep["latency_ms"] > 0
    assert grep["answerable"] == "yes" and grep["mode"] == "shadow"
    assert not rows[0]["covered"] and rows[0]["actual_tokens"] > 0
    for leak in (str(repo.root), "app/api.py", "refund", "return"):
        assert leak not in out.stdout
    db = sqlite3.connect(tmp_path / "config" / "concordance" / "usage.db")
    stored = db.execute("SELECT * FROM replay_rows").fetchall()
    assert len(stored) == 3
    assert not any(leak in json.dumps(stored) for leak in (str(repo.root), "app/api.py", "refund"))


def test_replay_twice_replaces_rows(make_repo, tmp_path: Path) -> None:
    repo = make_repo(BASE)
    _session(tmp_path, repo.root)
    cli(repo.root, "replay", "--session", "s1")
    cli(repo.root, "replay", "--session", "s1")
    db = sqlite3.connect(tmp_path / "config" / "concordance" / "usage.db")
    assert db.execute("SELECT COUNT(*) FROM replay_rows").fetchone()[0] == 3


def test_unfinished_session_needs_force(make_repo, tmp_path: Path) -> None:
    repo = make_repo(BASE)
    _session(tmp_path, repo.root, age_s=10)
    out = cli(repo.root, "replay", "--session", "s1")
    assert out.returncode == 2 and "not finished" in out.stderr
    assert cli(repo.root, "replay", "--session", "s1", "--force").returncode == 0


def test_unknown_session_exits_2(make_repo) -> None:
    repo = make_repo(BASE)
    out = cli(repo.root, "replay", "--session", "missing")
    assert out.returncode == 2 and "Traceback" not in out.stderr


def test_replay_calls_do_not_count_as_usage(make_repo, tmp_path: Path) -> None:
    repo = make_repo(BASE)
    _session(tmp_path, repo.root)
    cli(repo.root, "replay", "--session", "s1")
    stats = json.loads(cli(repo.root, "stats", "--json").stdout)
    assert "callers" not in stats["commands"]


def test_stats_replay_summarises(make_repo, tmp_path: Path) -> None:
    repo = make_repo(BASE)
    _session(tmp_path, repo.root)
    cli(repo.root, "replay", "--session", "s1")
    doc = json.loads(cli(repo.root, "stats", "--replay", "--json").stdout)
    assert doc["rows"] == 3 and doc["by_kind"]["grep"]["covered"] == 1
```

Create `tests/concordance/test_modes.py`:

```python
from scripts import modes


def test_default_is_shadow() -> None:
    assert modes.get_mode("s", "repo") == "shadow"


def test_session_flag_beats_repo_default() -> None:
    modes.set_mode("inject", None, "repo")
    assert modes.get_mode("s", "repo") == "inject"
    modes.set_mode("shadow", "s", "repo")
    assert modes.get_mode("s", "repo") == "shadow"
    assert modes.get_mode("other", "repo") == "inject"
```

- [ ] **Step 2: Run and see them fail**

Run: `../../.venv/bin/python -m pytest ../../tests/concordance/test_replay_cli.py ../../tests/concordance/test_modes.py -v`
Expected: FAIL (unknown command `replay`, missing `scripts.modes`).

- [ ] **Step 3: Implement `modes.py`**

```python
"""Per-session delivery mode for inject-mode hooks: shadow (default) or inject."""
from __future__ import annotations

import re
from pathlib import Path

from scripts.paths import config_dir

MODES = ("shadow", "inject")
_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def _dir() -> Path:
    return config_dir() / "concordance" / "modes"


def _file(session: str | None, repo: str) -> Path:
    name = f"session-{_SAFE.sub('_', session)}" if session else f"repo-{_SAFE.sub('_', repo)}"
    return _dir() / name


def set_mode(mode: str, session: str | None, repo: str) -> Path:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    path = _file(session, repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(mode, encoding="utf-8")
    return path


def get_mode(session: str, repo: str) -> str:
    for path in (_file(session, repo), _file(None, repo)):
        try:
            mode = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if mode in MODES:
            return mode
    return "shadow"
```

- [ ] **Step 4: Implement `replay/core.py`**

```python
"""Replay one session: every tool call becomes one numeric row."""
from __future__ import annotations

from scripts.render import est_tokens
from scripts.replay import drift, estimators
from scripts.replay.transcript import Session

ROW_FIELDS = ("session_id", "tool_use_id", "agent_id", "kind", "estimator", "covered",
              "actual_tokens", "concordance_tokens", "latency_ms", "exit_code",
              "answerable", "drifted", "mode")


def replay_session(session: Session, mode: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    by_agent: dict[str, list] = {}
    for call in session.calls:
        by_agent.setdefault(call.agent_id, []).append(call)
    for call in session.calls:
        mine = by_agent[call.agent_id]
        query = estimators.match(call)
        kind = query.kind if query else call.name.lower()
        est = estimators.estimate(query, call, [c for c in mine if c.seq > call.seq]) \
            if query else estimators.NOT_COVERED
        drifted = "unknown"
        if call.name == "Read" and isinstance(call.input.get("file_path"), str):
            drifted = drift.drifted([c for c in mine if c.seq <= call.seq],
                                    str(call.input["file_path"]), call.cwd)
        rows.append({
            "session_id": session.session_id, "tool_use_id": call.tool_use_id,
            "agent_id": call.agent_id, "kind": kind,
            "estimator": query.estimator if query else "", "covered": est.covered,
            "actual_tokens": est_tokens(call.result_text),
            "concordance_tokens": est.concordance_tokens, "latency_ms": est.latency_ms,
            "exit_code": est.exit_code, "answerable": est.answerable, "drifted": drifted,
            "mode": mode})
    return rows
```

(The `kind` for an unmatched call is the tool name lowercased: `read`, `bash`, `edit`; that is a tool type, not content.)

- [ ] **Step 5: Implement `replay/store.py`**

```python
"""replay_rows in usage.db: numbers only, replaced per (session_id, tool_use_id)."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from scripts.replay.core import ROW_FIELDS
from scripts.usage import DAY_S, usage_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS replay_rows(
  session_id TEXT NOT NULL, tool_use_id TEXT NOT NULL, agent_id TEXT NOT NULL,
  kind TEXT NOT NULL, estimator TEXT NOT NULL, covered INTEGER NOT NULL,
  actual_tokens INTEGER NOT NULL, concordance_tokens INTEGER NOT NULL,
  latency_ms INTEGER NOT NULL, exit_code INTEGER NOT NULL, answerable TEXT NOT NULL,
  drifted TEXT NOT NULL, mode TEXT NOT NULL, replayed_at REAL NOT NULL,
  PRIMARY KEY (session_id, tool_use_id));
"""


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.executescript(SCHEMA)
    return conn


def save(rows: list[dict[str, object]], path: Path | None = None) -> None:
    conn = _connect(path or usage_path())
    now = time.time()
    try:
        with conn:
            conn.executemany(
                f"INSERT OR REPLACE INTO replay_rows({', '.join(ROW_FIELDS)}, replayed_at) "
                f"VALUES ({', '.join('?' for _ in ROW_FIELDS)}, ?)",
                [(*(int(r[f]) if isinstance(r[f], bool) else r[f] for f in ROW_FIELDS), now)
                 for r in rows])
    finally:
        conn.close()


def summary(days: int = 30, path: Path | None = None,
            now: float | None = None) -> dict[str, object]:
    path = path or usage_path()
    since = (time.time() if now is None else now) - days * DAY_S
    out: dict[str, object] = {"days": days, "sessions": 0, "rows": 0, "covered": 0,
                              "by_kind": {}}
    if not path.exists():
        return out
    conn = _connect(path)
    try:
        rows = conn.execute(
            "SELECT session_id, kind, covered, actual_tokens, concordance_tokens, answerable, "
            "drifted FROM replay_rows WHERE replayed_at >= ?", (since,)).fetchall()
    finally:
        conn.close()
    by_kind: dict[str, dict[str, object]] = {}
    for _sid, kind, covered, actual, conc, answerable, drifted in rows:
        k = by_kind.setdefault(kind, {"calls": 0, "covered": 0, "actual_tokens": 0,
                                      "concordance_tokens": 0, "drifted": 0,
                                      "answerable": {"yes": 0, "no": 0, "unknown": 0}})
        k["calls"] = int(k["calls"]) + 1  # type: ignore[call-overload]
        k["covered"] = int(k["covered"]) + int(covered)  # type: ignore[call-overload]
        k["actual_tokens"] = int(k["actual_tokens"]) + int(actual)  # type: ignore[call-overload]
        k["concordance_tokens"] = int(k["concordance_tokens"]) + int(conc)  # type: ignore[call-overload]
        k["drifted"] = int(k["drifted"]) + (drifted == "yes")  # type: ignore[call-overload]
        ans = k["answerable"]
        assert isinstance(ans, dict)
        ans[answerable] = ans.get(answerable, 0) + 1
    out.update(sessions=len({r[0] for r in rows}), rows=len(rows),
               covered=sum(int(r[2]) for r in rows), by_kind=by_kind)
    return out
```

(If mypy rejects the `type: ignore` comments as unused, replace the counters with a small `@dataclass KindTotals` and convert to a dict at the end; no `type: ignore` may remain unused, because `warn_unused_ignores = true`.)

- [ ] **Step 6: Wire the CLI**

In `cli._parser`, add:

```python
    rp = sub.add_parser("replay", help="replay a finished session: actual vs concordance cost, numbers only")
    rp.add_argument("--session", required=True)
    rp.add_argument("--transcript", default=None, help="main transcript path (default: find it)")
    rp.add_argument("--force", action="store_true", help="replay even if the session looks live")
    md = sub.add_parser("mode", help="set the delivery mode: shadow (default) or inject")
    md.add_argument("mode", choices=("shadow", "inject"))
    md.add_argument("--session", default=None, help="this session only (default: repo default)")
```

and on the existing `stats` parser: `st.add_argument("--replay", action="store_true", help="replay summary instead of usage")`.

In `commands/records.py` add:

```python
def replay(args: argparse.Namespace, cwd: Path) -> int:
    from scripts.replay import core, store as replay_store, transcript
    try:
        files = transcript.session_files(
            args.session, main=Path(args.transcript) if args.transcript else None)
    except FileNotFoundError as exc:
        print(f"concordance: {exc}", file=sys.stderr)
        return 2
    if not args.force and not transcript.is_finished(files):
        print("concordance: session not finished (idle < 15 min); use --force", file=sys.stderr)
        return 2
    session = transcript.load(args.session, files)
    rows = core.replay_session(session, modes.get_mode(args.session, common.repo_key_of(cwd)))
    try:
        replay_store.save(rows)
    except Exception as exc:  # noqa: BLE001 - unusable usage log: exit 2, never a traceback
        print(f"concordance: usage log unavailable: {exc!r}", file=sys.stderr)
        return 2
    common.say(json.dumps(rows))
    return 0


def mode(args: argparse.Namespace, cwd: Path) -> int:
    repo = common.repo_key_of(cwd)
    if not repo and not args.session:
        print("concordance: mode needs a git repository or --session", file=sys.stderr)
        return 2
    modes.set_mode(args.mode, args.session, repo)
    common.say(f"mode: {args.mode} ({'session ' + args.session if args.session else 'repo default'})")
    return 0
```

In `stats`, when `args.replay`: `rep = replay_store.summary(days=args.days)`; print JSON with `--json`, else one line per kind: `f"{kind}: {calls} calls, {covered} covered, actual {actual_tokens} vs concordance {concordance_tokens} tokens, answerable {yes}/{no}/{unknown}, drifted {drifted}"`.

In `cli.main`, dispatch `replay` and `mode` like `stats`, before the query branch.

- [ ] **Step 7: Run the suite, ruff, mypy**

Run: `../../.venv/bin/python -m pytest -q && ../../.venv/bin/python -m ruff check . ../../tests/concordance && ../../.venv/bin/python -m mypy scripts`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add plugins/concordance/scripts tests/concordance/test_replay_cli.py tests/concordance/test_modes.py
git commit -m "feat(concordance): replay and mode commands; replay rows in usage.db; stats --replay"
```

---

### Task 6: chronicle stores and reports concordance rows (carried cost)

**Files:**
- Modify: `plugins/chronicle/scripts/store.py` (`_SCHEMA`)
- Create: `plugins/chronicle/scripts/concordance.py` (parsing and storing only in this task)
- Modify: `plugins/chronicle/scripts/report.py` (add `concordance(...)`)
- Modify: `plugins/chronicle/scripts/cli.py` (`concordance` verb)
- Test: `tests/chronicle/test_concordance.py`

**Interfaces:**
- Produces:

```python
# chronicle/scripts/concordance.py
FIELDS = ("tool_use_id", "agent_id", "kind", "estimator", "covered", "actual_tokens",
          "concordance_tokens", "latency_ms", "answerable", "drifted", "mode")
def store_rows(conn: sqlite3.Connection, session_id: str, rows: list[dict[str, object]]) -> int
    # validates each row has FIELDS with the right types; drops rows that don't; replaces the
    # session's rows; returns the count stored

# chronicle/scripts/report.py
def concordance(conn: sqlite3.Connection, *, repo_root: str | None = None,
                since: float | None = None) -> dict[str, object]
    # {"sessions", "rows", "by_kind": {kind: {"calls","covered","actual_tokens",
    #   "concordance_tokens","actual_carried_usd","concordance_carried_usd",
    #   "unpriced_turns","answerable": {...},"drifted"}}, "by_mode": {...same shape...}}
```

Carried cost for one row: find `tool_calls.result_ts` for its `(session_id, tool_use_id)`; take the turns of the same `session_id` and `agent_id` with `ts > result_ts` and before the first `events` row of `kind='compaction'` for that session and agent after `result_ts`; for each such turn, `rate = ratebook.load(conn).rates_for(turn.model, ts=turn.ts)`; if `rate` is None count an unpriced turn, else add `tokens * rate["cache_read"] / 1_000_000`. Do it for `actual_tokens` and `concordance_tokens`. Rows with no `tool_calls` match contribute size but no carried cost.

Table (append to `_SCHEMA`):

```sql
CREATE TABLE IF NOT EXISTS concordance_rows (
    session_id         TEXT NOT NULL,
    tool_use_id        TEXT NOT NULL,
    agent_id           TEXT NOT NULL DEFAULT '',
    kind               TEXT NOT NULL,
    estimator          TEXT NOT NULL,
    covered            INTEGER NOT NULL,
    actual_tokens      INTEGER NOT NULL,
    concordance_tokens INTEGER NOT NULL,
    latency_ms         INTEGER NOT NULL,
    answerable         TEXT NOT NULL,
    drifted            TEXT NOT NULL,
    mode               TEXT NOT NULL,
    PRIMARY KEY (session_id, tool_use_id)
);
CREATE INDEX IF NOT EXISTS concordance_rows_session ON concordance_rows(session_id);
```

- [ ] **Step 1: Write the failing tests**

Create `tests/chronicle/test_concordance.py` (copy fixture use from `tests/chronicle/test_ingest.py`: `builder` fixture, `T0`-style ISO timestamps, `store.connect()`, `ingest.ingest_session`):

```python
from scripts import concordance, ingest, report, store

T0 = "2026-09-01T10:00:00.000Z"
T1 = "2026-09-01T10:00:05.000Z"
T2 = "2026-09-01T10:01:00.000Z"
T3 = "2026-09-01T10:02:00.000Z"


def _row(tid: str, **kw: object) -> dict[str, object]:
    base: dict[str, object] = {"tool_use_id": tid, "agent_id": "", "kind": "grep",
                               "estimator": "callers", "covered": True, "actual_tokens": 3000,
                               "concordance_tokens": 300, "latency_ms": 900,
                               "answerable": "yes", "drifted": "unknown", "mode": "shadow"}
    base.update(kw)
    return base


def test_store_rows_drops_malformed_and_replaces(builder) -> None:
    conn = store.connect()
    assert concordance.store_rows(conn, "s", [_row("a"), {"tool_use_id": "b"}]) == 1
    assert concordance.store_rows(conn, "s", [_row("a"), _row("c")]) == 2
    assert conn.execute("SELECT COUNT(*) FROM concordance_rows").fetchone()[0] == 2


def test_rows_never_hold_text_columns() -> None:
    conn = store.connect()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(concordance_rows)")}
    assert not cols & {"path", "pattern", "command", "content", "file_path"}


def test_carried_cost_counts_later_turns(builder) -> None:
    path = (builder.turn("m1", T0, tools=["Grep"])
            .tool_result("r1", T1, tool_use_id="m1-tool0", content="x" * 9000)
            .turn("m2", T2).turn("m3", T3).write())
    conn = store.connect()
    ingest.ingest_session(conn, path)
    sid = conn.execute("SELECT session_id FROM tool_calls").fetchone()[0]
    concordance.store_rows(conn, sid, [_row("m1-tool0")])
    out = report.concordance(conn)
    grep = out["by_kind"]["grep"]
    assert grep["calls"] == 1 and grep["actual_tokens"] == 3000
    assert grep["actual_carried_usd"] > grep["concordance_carried_usd"] > 0 \
        or grep["unpriced_turns"] == 2
```

(If `TranscriptBuilder.turn` needs a model for pricing, pass the model the other report-pricing tests use — read `tests/chronicle/test_report_pricing.py` — so the last assert takes its priced branch; keep the `or` only if the builder cannot set a model.)

Add a CLI test in the same file, mirroring how `tests/chronicle/test_cli.py` runs verbs:

```python
def test_concordance_verb_prints_json(builder, capsys) -> None:
    from scripts import cli
    conn = store.connect()
    concordance.store_rows(conn, "s", [_row("a")])
    conn.close()
    assert cli.main(["concordance"]) == 0
    import json
    assert json.loads(capsys.readouterr().out)["rows"] == 1
```

- [ ] **Step 2: Run and see them fail**

Run (from `plugins/chronicle`): `../../.venv/bin/python -m pytest ../../tests/chronicle/test_concordance.py -v`
Expected: FAIL, `cannot import name 'concordance'`.

- [ ] **Step 3: Add the table to `_SCHEMA`** (SQL above, appended inside the existing `_SCHEMA` string).

- [ ] **Step 4: Implement `store_rows` in `chronicle/scripts/concordance.py`**

```python
"""Optional reader for concordance's replay numbers. chronicle never imports concordance: it
runs its CLI (Task 7) and stores the numeric rows it prints. No paths, patterns or content."""
from __future__ import annotations

import sqlite3

FIELDS = ("tool_use_id", "agent_id", "kind", "estimator", "covered", "actual_tokens",
          "concordance_tokens", "latency_ms", "answerable", "drifted", "mode")
_INTS = ("actual_tokens", "concordance_tokens", "latency_ms")
_STRS = ("tool_use_id", "agent_id", "kind", "estimator", "answerable", "drifted", "mode")


def _valid(row: object) -> bool:
    return (isinstance(row, dict) and all(f in row for f in FIELDS)
            and all(isinstance(row[f], int) and not isinstance(row[f], bool) for f in _INTS)
            and all(isinstance(row[f], str) for f in _STRS)
            and isinstance(row["covered"], bool))


def store_rows(conn: sqlite3.Connection, session_id: str, rows: list[dict[str, object]]) -> int:
    good = [r for r in rows if _valid(r)]
    with conn:
        conn.execute("DELETE FROM concordance_rows WHERE session_id = ?", (session_id,))
        conn.executemany(
            f"INSERT INTO concordance_rows(session_id, {', '.join(FIELDS)}) "
            f"VALUES (?, {', '.join('?' for _ in FIELDS)})",
            [(session_id, *(int(r[f]) if isinstance(r[f], bool) else r[f] for f in FIELDS))
             for r in good])
    return len(good)
```

- [ ] **Step 5: Implement `report.concordance`**

Add to `report.py` (it already imports `ratebook`; reuse `_has_table`):

```python
def concordance(conn: sqlite3.Connection, *, repo_root: str | None = None,
                since: float | None = None) -> dict[str, Any]:
    empty: dict[str, Any] = {"sessions": 0, "rows": 0, "by_kind": {}, "by_mode": {}}
    if not _has_table(conn, "concordance_rows"):
        return empty
    where, params = ["1=1"], []
    if since is not None:
        where.append("s.last_activity_at >= ?")
        params.append(since)
    if repo_root is not None:
        where.append("s.repo_root = ?")  # use the sessions column report.py's other filters use
        params.append(repo_root)
    rows = conn.execute(
        "SELECT c.*, t.result_ts FROM concordance_rows c "
        "LEFT JOIN sessions s ON s.session_id = c.session_id "
        "LEFT JOIN tool_calls t ON t.session_id = c.session_id AND t.tool_use_id = c.tool_use_id "
        f"WHERE {' AND '.join(where)}", params).fetchall()
    book = ratebook.load(conn)
    out = dict(empty, sessions=len({r["session_id"] for r in rows}), rows=len(rows))
    for r in rows:
        actual_usd, conc_usd, unpriced = 0.0, 0.0, 0
        if r["result_ts"] is not None:
            cutoff = conn.execute(
                "SELECT MIN(ts) FROM events WHERE session_id = ? AND agent_id = ? "
                "AND kind = 'compaction' AND ts > ?",
                (r["session_id"], r["agent_id"], r["result_ts"])).fetchone()[0]
            turns = conn.execute(
                "SELECT model, ts FROM turns WHERE session_id = ? AND agent_id = ? AND ts > ?"
                + (" AND ts < ?" if cutoff is not None else ""),
                (r["session_id"], r["agent_id"], r["result_ts"],
                 *([cutoff] if cutoff is not None else []))).fetchall()
            for turn in turns:
                rates = book.rates_for(turn["model"], ts=turn["ts"])
                if rates is None or "cache_read" not in rates:
                    unpriced += 1
                    continue
                per_token = rates["cache_read"] / 1_000_000
                actual_usd += r["actual_tokens"] * per_token
                conc_usd += r["concordance_tokens"] * per_token
        for group, key in (("by_kind", r["kind"]), ("by_mode", r["mode"])):
            g = out[group].setdefault(key, {
                "calls": 0, "covered": 0, "actual_tokens": 0, "concordance_tokens": 0,
                "actual_carried_usd": 0.0, "concordance_carried_usd": 0.0,
                "unpriced_turns": 0, "drifted": 0,
                "answerable": {"yes": 0, "no": 0, "unknown": 0}})
            g["calls"] += 1
            g["covered"] += r["covered"]
            g["actual_tokens"] += r["actual_tokens"]
            g["concordance_tokens"] += r["concordance_tokens"]
            g["actual_carried_usd"] += actual_usd
            g["concordance_carried_usd"] += conc_usd
            g["unpriced_turns"] += unpriced
            g["drifted"] += r["drifted"] == "yes"
            g["answerable"][r["answerable"]] = g["answerable"].get(r["answerable"], 0) + 1
    return out
```

Read `report.py` for the real sessions column that holds the repo root (the other report functions filter on it via `_session_filter`); use `_session_filter` instead of the hand-written `repo_root` clause if its signature fits. Confirm `ratebook.RateBook.rates_for(model, ts=...)` takes `ts` as the turns table stores it (REAL epoch).

- [ ] **Step 6: Add the `concordance` verb to `cli.py`**

Mirror `cmd_limits`:

```python
def cmd_concordance(args: argparse.Namespace) -> int:
    conn = _open_readonly()
    if conn is None:
        print(json.dumps({"sessions": 0, "rows": 0, "by_kind": {}, "by_mode": {}}))
        return 0
    try:
        out = report.concordance(conn, repo_root=args.root, since=_resolve_since(args))
    finally:
        conn.close()
    print(json.dumps(out))
    return 0
```

and in `build_parser()` add a subparser `concordance` (help: "replayed concordance counterfactuals: actual vs concordance size and carried cost") with the same `--root` and `--days`/`--since` arguments `limits` takes, `.set_defaults(fn=cmd_concordance)`.

- [ ] **Step 7: Run chronicle's suite, ruff, mypy**

Run (from `plugins/chronicle`): `../../.venv/bin/python -m pytest -q && ../../.venv/bin/python -m ruff check . ../../tests/chronicle && ../../.venv/bin/python -m mypy scripts`
Expected: all pass (770 + new).

- [ ] **Step 8: Commit**

```bash
git add plugins/chronicle/scripts/store.py plugins/chronicle/scripts/concordance.py plugins/chronicle/scripts/report.py plugins/chronicle/scripts/cli.py tests/chronicle/test_concordance.py
git commit -m "feat(chronicle): store concordance replay numbers and report carried cost"
```

---

### Task 7: chronicle sync runs replay for finished sessions

**Files:**
- Modify: `plugins/chronicle/scripts/concordance.py` (find, run, sync step)
- Modify: `plugins/chronicle/scripts/cli.py` (`cmd_sync` calls the step, never fatal)
- Test: `tests/chronicle/test_concordance.py` (add tests)

**Interfaces:**
- Produces:

```python
def find_cli(env: Mapping[str, str] | None = None) -> Path | None
    # CONCORDANCE_CLI if it names an existing file; else the newest
    # <config_dir>/plugins/cache/*/concordance/*/scripts/cli.py; else None
def run_replay(cli: Path, session_id: str, transcript: Path,
               timeout: float = 600.0) -> list[dict[str, object]] | None
    # through _exec (injectable); None on any failure (missing, timeout, non-zero, bad JSON)
def sync_step(conn: sqlite3.Connection, *, now: float | None = None, limit: int = 20,
              env: Mapping[str, str] | None = None) -> dict[str, int]
    # {"replayed", "failed", "skipped"}; never raises
_exec: Callable[[list[str], float], subprocess.CompletedProcess[str]]   # tests replace it
```

Rules: `CHRONICLE_NO_CONCORDANCE=1` or no CLI → `{"replayed": 0, "failed": 0, "skipped": 0}` and nothing else. Candidate sessions: main sessions (`sessions` rows) whose `last_activity_at` is older than `now - report.LIVE_HORIZON_SECONDS` and whose `meta` key `concordance_replayed:<session_id>` is absent or holds a value different from `str(last_activity_at)`, newest first, at most `limit`. Transcript path: the `cursors` row with that `session_id` and `agent_id = ''`. Success → `store_rows`, set the meta key to `str(last_activity_at)`, count replayed. Failure → leave the meta key, count failed (retried next sync). `cmd_sync` calls `sync_step` after ingest inside `try/except Exception` that logs to stderr and continues, like the pricing refresh.

- [ ] **Step 1: Write the failing tests**

Add to `tests/chronicle/test_concordance.py`:

```python
import json
import subprocess
import time
from pathlib import Path


def _finished_session(builder) -> tuple:
    path = (builder.turn("m1", T0, tools=["Grep"])
            .tool_result("r1", T1, tool_use_id="m1-tool0", content="x").write())
    conn = store.connect()
    ingest.ingest_session(conn, path)
    sid = conn.execute("SELECT session_id FROM sessions").fetchone()[0]
    return conn, sid


def _fake_cli(tmp_path: Path) -> dict[str, str]:
    cli = tmp_path / "cli.py"
    cli.write_text("# fake\n")
    return {"CONCORDANCE_CLI": str(cli)}


def test_sync_step_replays_and_marks(builder, tmp_path, monkeypatch) -> None:
    conn, sid = _finished_session(builder)
    calls = []

    def fake(cmd, timeout):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, json.dumps([_row("m1-tool0")]), "")

    monkeypatch.setattr(concordance, "_exec", fake)
    env = _fake_cli(tmp_path)
    assert concordance.sync_step(conn, now=time.time() + 10**7, env=env)["replayed"] == 1
    assert "--session" in calls[0] and sid in calls[0]
    assert concordance.sync_step(conn, now=time.time() + 10**7, env=env)["replayed"] == 0


def test_sync_survives_replay_failure(builder, tmp_path, monkeypatch) -> None:
    conn, _ = _finished_session(builder)

    def boom(cmd, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(concordance, "_exec", boom)
    out = concordance.sync_step(conn, now=time.time() + 10**7, env=_fake_cli(tmp_path))
    assert out == {"replayed": 0, "failed": 1, "skipped": 0}


def test_failed_session_is_retried(builder, tmp_path, monkeypatch) -> None:
    conn, _ = _finished_session(builder)
    results = iter([subprocess.CompletedProcess([], 2, "", "err"),
                    subprocess.CompletedProcess([], 0, json.dumps([_row("m1-tool0")]), "")])
    monkeypatch.setattr(concordance, "_exec", lambda cmd, timeout: next(results))
    env = _fake_cli(tmp_path)
    assert concordance.sync_step(conn, now=time.time() + 10**7, env=env)["failed"] == 1
    assert concordance.sync_step(conn, now=time.time() + 10**7, env=env)["replayed"] == 1


def test_live_session_is_not_replayed(builder, tmp_path, monkeypatch) -> None:
    conn, _ = _finished_session(builder)
    monkeypatch.setattr(concordance, "_exec", lambda cmd, timeout: 1 / 0)
    last = conn.execute("SELECT last_activity_at FROM sessions").fetchone()[0]
    out = concordance.sync_step(conn, now=last + 60, env=_fake_cli(tmp_path))
    assert out["replayed"] == 0 and out["failed"] == 0


def test_kill_switch_and_missing_cli(builder, monkeypatch) -> None:
    conn, _ = _finished_session(builder)
    monkeypatch.setattr(concordance, "_exec", lambda cmd, timeout: 1 / 0)
    assert concordance.sync_step(conn, env={"CHRONICLE_NO_CONCORDANCE": "1"})["replayed"] == 0
    assert concordance.find_cli(env={}) is None
```

(`builder` writes under `<tmp>/config/projects`, where `find_cli`'s cache glob finds nothing, so `find_cli(env={})` is None.)

- [ ] **Step 2: Run and see them fail**

Run: `../../.venv/bin/python -m pytest ../../tests/chronicle/test_concordance.py -v`
Expected: FAIL, `no attribute 'sync_step'`.

- [ ] **Step 3: Implement in `chronicle/scripts/concordance.py`**

```python
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from scripts import report
from scripts.store import config_dir


def _run(cmd: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


_exec: Callable[[list[str], float], subprocess.CompletedProcess[str]] = _run


def find_cli(env: Mapping[str, str] | None = None) -> Path | None:
    e = os.environ if env is None else env
    named = e.get("CONCORDANCE_CLI")
    if named:
        return Path(named) if Path(named).is_file() else None
    found = sorted((config_dir() / "plugins" / "cache").glob("*/concordance/*/scripts/cli.py"),
                   key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def run_replay(cli: Path, session_id: str, transcript: Path,
               timeout: float = 600.0) -> list[dict[str, object]] | None:
    cmd = [sys.executable, str(cli), "replay", "--session", session_id,
           "--transcript", str(transcript), "--force"]  # chronicle already judged it finished
    try:
        proc = _exec(cmd, timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        rows = json.loads(proc.stdout)
    except ValueError:
        return None
    return rows if isinstance(rows, list) else None


def sync_step(conn: sqlite3.Connection, *, now: float | None = None, limit: int = 20,
              env: Mapping[str, str] | None = None) -> dict[str, int]:
    out = {"replayed": 0, "failed": 0, "skipped": 0}
    e = os.environ if env is None else env
    if e.get("CHRONICLE_NO_CONCORDANCE") == "1":
        return out
    cli = find_cli(e)
    if cli is None:
        return out
    t = time.time() if now is None else now
    candidates = conn.execute(
        "SELECT s.session_id, s.last_activity_at, c.path FROM sessions s "
        "JOIN cursors c ON c.session_id = s.session_id AND c.agent_id = '' "
        "LEFT JOIN meta m ON m.key = 'concordance_replayed:' || s.session_id "
        "WHERE s.last_activity_at IS NOT NULL AND s.last_activity_at < ? "
        "AND (m.value IS NULL OR m.value != CAST(s.last_activity_at AS TEXT)) "
        "ORDER BY s.last_activity_at DESC LIMIT ?",
        (t - report.LIVE_HORIZON_SECONDS, limit)).fetchall()
    for sid, last, path in candidates:
        try:
            rows = run_replay(cli, sid, Path(path))
            if rows is None:
                out["failed"] += 1
                continue
            store_rows(conn, sid, rows)
            with conn:
                conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                             (f"concordance_replayed:{sid}", str(last)))
            out["replayed"] += 1
        except Exception:  # noqa: BLE001 - one bad session never stops the rest
            out["failed"] += 1
    return out
```

Check the real names before relying on them: `meta`'s columns (`key`, `value`), the `cursors` path column (`path`), whether `sessions` has `last_activity_at` and whether `cursors` rows for the main transcript use `agent_id = ''`; the `CAST(... AS TEXT)` must match how `str(last)` renders a float in Python; if it does not, store `repr(last)` and compare in Python instead of SQL. Pass `--force` too: chronicle has already applied its own live horizon, so concordance's mtime check must not reject a session chronicle judged finished.

- [ ] **Step 4: Call it from `cmd_sync`**

After the existing post-ingest steps in `cmd_sync`:

```python
    try:
        result["concordance"] = concordance.sync_step(conn)
    except Exception as exc:  # noqa: BLE001 - optional reader: never fails sync
        print(f"chronicle: concordance replay skipped: {exc!r}", file=sys.stderr)
```

(Adapt `result` to the name `cmd_sync` uses for the dict it prints; if it prints nothing structured, print nothing extra.)

- [ ] **Step 5: Run chronicle's suite, ruff, mypy**

Run (from `plugins/chronicle`): `../../.venv/bin/python -m pytest -q && ../../.venv/bin/python -m ruff check . ../../tests/chronicle && ../../.venv/bin/python -m mypy scripts`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add plugins/chronicle/scripts/concordance.py plugins/chronicle/scripts/cli.py tests/chronicle/test_concordance.py
git commit -m "feat(chronicle): sync replays finished sessions through concordance's CLI, never fatal"
```

---

### Task 8: Docs, versions, full gate

**Files:**
- Modify: `plugins/concordance/README.md`, `plugins/chronicle/README.md` (if present; else the chronicle SKILL.md section on commands), `CLAUDE.md` (concordance and chronicle lines)
- Modify: `plugins/concordance/.claude-plugin/plugin.json` (0.1.0 → 0.2.0), `plugins/chronicle/.claude-plugin/plugin.json` (0.5.1 → 0.6.0), `.claude-plugin/marketplace.json` (1.68.0 → 1.69.0, and the two plugin entries' versions if listed there)

- [ ] **Step 1: Document**

concordance README, new section "Measuring it (replay)":

```markdown
## Measuring it: replay

`concordance replay --session <id>` reads a finished session's transcripts in memory and,
for each tool call, asks the real CLI what concordance would have returned. It prints one row
per call: actual tokens, concordance tokens, CLI latency, whether the answer would have been
enough (yes / no / unknown) and whether the file has changed since (drifted). Rows hold
numbers and labels only; nothing from the transcript is stored. `concordance stats --replay`
summarises them. `concordance mode inject|shadow [--session ID]` sets the delivery mode
(shadow by default; inject-mode hooks arrive later). Every query command takes `--json`.
```

chronicle docs: one paragraph on `chronicle concordance` and the optional sync step, the kill switch `CHRONICLE_NO_CONCORDANCE=1`, and that chronicle stores only the numbers.

`CLAUDE.md`: append to the concordance line "; `replay` measures actual vs counterfactual cost per tool call (numbers only)", and to the chronicle line "; optionally pulls concordance replay numbers (`chronicle concordance`)".

- [ ] **Step 2: Bump versions** as listed above.

- [ ] **Step 3: Full gate**

Run from the repo root: `./tests/run.sh -q` and from `plugins/review-panel`: `../../.venv/bin/python -m pytest -q`; ruff and mypy for concordance and chronicle as in Global Constraints.
Expected: every suite passes.

- [ ] **Step 4: Commit**

```bash
git add plugins/concordance/README.md CLAUDE.md plugins/concordance/.claude-plugin/plugin.json plugins/chronicle/.claude-plugin/plugin.json .claude-plugin/marketplace.json
git add plugins/chronicle/README.md  # or the chronicle doc file you edited
git commit -m "docs: concordance replay and chronicle's concordance report; bump versions"
```
