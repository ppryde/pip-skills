# Overseer Context-Limit Auto-Handoff — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a promoted overseer orchestrator cap its own context creep by resetting in-process via `/clear` at points *it* chooses, resuming from a re-injected handover — driven by a `Stop` hook (auto, under tmux) or a human (manual), gated per state root.

**Architecture:** Four new Python modules (`config`, `orchestrator`, `context`, plus an extension to `resume`) hold all decision logic behind the existing single-writer, tested-Python CLI. Two plugin-shipped shell hooks (`Stop`, `SessionStart`) are thin, fail-safe wrappers that delegate every decision to the CLI and only carry out the mechanical side-effect (`tmux send-keys "/clear"`, or print `additionalContext`). All runtime artifacts live under `<state_root>/orchestrator/`, so the state root — overseer's one-writer unit — *is* the per-orchestrator key.

**Tech Stack:** Python 3.11 (stdlib + PyYAML, already a dep), argparse CLI, pytest, bash hook scripts, tmux (new hard dependency), Claude Code plugin hooks (`hooks/hooks.json`, `${CLAUDE_PLUGIN_ROOT}`).

## Global Constraints

- **Python 3.11**; `mypy` runs strict (`disallow_untyped_defs = true`) — annotate **every** `def` (params and return).
- **`ruff` line-length = 100.**
- **Run all gates from `plugins/overseer/`** via the worktree venv (poetry does NOT work here):
  - `../../.venv/bin/python -m pytest -q`
  - `../../.venv/bin/ruff check scripts tests`
  - `../../.venv/bin/mypy scripts`
- **Follow existing house patterns:** modules under `scripts/`, tests under `tests/`, `from __future__ import annotations`, `state_root(repo_root)` for all path resolution (never hard-code `.workflow/`), quarantine-safe reads (corrupt file → fall back, never crash), `Path` throughout.
- **CLI shape:** every subcommand is a `cmd_*(args) -> int` returning an exit code, registered in `build_parser()` with `p.set_defaults(func=cmd_*)`; `--root` is a top-level arg defaulting to `Path(".")`.
- **Stop hook safety — non-negotiable:** the `Stop` hook script **always exits 0** and **never** emits `exit 2` / `{"decision":"block"}`. Every hook script opens with `trap 'exit 0' EXIT`. Exit-0 stdout from a `Stop` hook is not shown to the model (zero context tokens).
- **tmux is a required dependency**, documented up front. Auto mode requires `$TMUX`; without it the orchestrator runs in manual mode (human types `/clear`).
- **Commit after every task** with a `feat(overseer):` / `test(overseer):` / `docs(overseer):` prefix, ending with the two trailer lines this session requires.
- **All artifacts are keyed by state root**, realised as the `<state_root>/orchestrator/` subdir. One state root ⇔ one orchestrator (the ledger already enforces a single writer per root); no filename root-key suffix is needed because separate orchestrators have separate state roots (separate worktrees).

---

## File Structure

**New modules:**
- `scripts/config.py` — per-repo config store (`config.json` under the state root): threshold, mode, context-window.
- `scripts/orchestrator.py` — root-keyed runtime state under `<state_root>/orchestrator/`: the `active` marker, the `clear-requested` flag, the `paused` flag, the `cooldown` marker, and the handoff document; plus the promote / pause / resume / arm / consume transitions.
- `scripts/context.py` — transcript-JSONL token accounting: locate the live transcript, sum context tokens, compute a percentage, format the `ctx NN%` line.

**Modified modules:**
- `scripts/resume.py` — extend `handoff_report` to embed agent-chosen prose (`notes`).
- `scripts/cli.py` — new subcommands `config`, `context`, `promote-orchestrator`, `context-guard`, `request-clear`, `stop-hook`, `session-start-hook`; a `ctx NN%` footer on `resume` and `handoff`.

**New hooks (plugin-shipped):**
- `hooks/hooks.json` — registers the `Stop` and `SessionStart` hooks.
- `hooks/stop.sh` — fail-safe dispatcher: under tmux, ask the CLI whether to clear, then `send-keys "/clear"`.
- `hooks/session-start.sh` — fail-safe re-injector: ask the CLI for the handoff, print it as `additionalContext`.

**New tests:**
- `tests/test_config.py`, `tests/test_orchestrator.py`, `tests/test_context.py`, `tests/test_hooks.py`; extensions to `tests/test_resume.py` and `tests/test_cli.py`.

**Docs:**
- `skills/orchestrate/SKILL.md` — rewrite `## Context stewardship`.
- `README.md` — tmux dependency + feature summary.

---

## Task 1: Per-repo config store

**Files:**
- Create: `plugins/overseer/scripts/config.py`
- Test: `plugins/overseer/tests/test_config.py`

**Interfaces:**
- Consumes: `state_root` from `scripts.store`.
- Produces:
  - `DEFAULTS: dict[str, object]` = `{"context.threshold": 35, "context.mode": "local", "context.window": 200000}`
  - `config_path(repo_root: Path) -> Path`
  - `load_config(repo_root: Path) -> dict[str, object]` — DEFAULTS merged with stored values; corrupt file → DEFAULTS (never raises).
  - `get_config(repo_root: Path, key: str) -> object`
  - `set_config(repo_root: Path, key: str, value: str) -> object` — validates key/value, coerces type, writes, returns the stored value.
  - `ConfigError(ValueError)`

- [ ] **Step 1: Write the failing test**

Create `plugins/overseer/tests/test_config.py`:

```python
import pytest

from scripts.config import (
    DEFAULTS,
    ConfigError,
    config_path,
    get_config,
    load_config,
    set_config,
)
from scripts.store import init_workflow


class TestDefaults:
    def test_load_on_empty_repo_returns_defaults(self, tmp_path):
        init_workflow(tmp_path)
        assert load_config(tmp_path) == DEFAULTS

    def test_get_falls_back_to_default(self, tmp_path):
        init_workflow(tmp_path)
        assert get_config(tmp_path, "context.threshold") == 35
        assert get_config(tmp_path, "context.mode") == "local"


class TestSetAndGet:
    def test_set_threshold_coerces_int(self, tmp_path):
        init_workflow(tmp_path)
        assert set_config(tmp_path, "context.threshold", "40") == 40
        assert get_config(tmp_path, "context.threshold") == 40
        assert config_path(tmp_path).exists()

    def test_set_mode_validates_choice(self, tmp_path):
        init_workflow(tmp_path)
        assert set_config(tmp_path, "context.mode", "remote") == "remote"
        with pytest.raises(ConfigError):
            set_config(tmp_path, "context.mode", "nonsense")

    def test_unknown_key_rejected(self, tmp_path):
        init_workflow(tmp_path)
        with pytest.raises(ConfigError):
            set_config(tmp_path, "context.bogus", "1")

    def test_threshold_out_of_range_rejected(self, tmp_path):
        init_workflow(tmp_path)
        with pytest.raises(ConfigError):
            set_config(tmp_path, "context.threshold", "150")


class TestCorruptFile:
    def test_corrupt_json_falls_back_to_defaults(self, tmp_path):
        init_workflow(tmp_path)
        config_path(tmp_path).write_text("{ not json")
        assert load_config(tmp_path) == DEFAULTS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_config.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.config'`.

- [ ] **Step 3: Write minimal implementation**

Create `plugins/overseer/scripts/config.py`:

```python
"""Per-repo runtime config for context stewardship. Single-writer, under the state root."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.store import state_root

DEFAULTS: dict[str, object] = {
    "context.threshold": 35,
    "context.mode": "local",
    "context.window": 200000,
}

_MODES = {"local", "remote"}


class ConfigError(ValueError):
    """An invalid config key or value."""


def config_path(repo_root: Path) -> Path:
    return state_root(repo_root) / "config.json"


def load_config(repo_root: Path) -> dict[str, object]:
    merged = dict(DEFAULTS)
    path = config_path(repo_root)
    if path.exists():
        try:
            stored = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return merged
        if isinstance(stored, dict):
            for key in DEFAULTS:
                if key in stored:
                    merged[key] = stored[key]
    return merged


def get_config(repo_root: Path, key: str) -> object:
    if key not in DEFAULTS:
        raise ConfigError(f"unknown config key: {key}")
    return load_config(repo_root)[key]


def _coerce(key: str, value: str) -> object:
    if key == "context.mode":
        if value not in _MODES:
            raise ConfigError(f"context.mode must be one of {sorted(_MODES)}")
        return value
    if key in ("context.threshold", "context.window"):
        try:
            number = int(value)
        except ValueError as exc:
            raise ConfigError(f"{key} must be an integer") from exc
        if key == "context.threshold" and not 1 <= number <= 100:
            raise ConfigError("context.threshold must be between 1 and 100")
        if key == "context.window" and number <= 0:
            raise ConfigError("context.window must be positive")
        return number
    raise ConfigError(f"unknown config key: {key}")


def set_config(repo_root: Path, key: str, value: str) -> object:
    if key not in DEFAULTS:
        raise ConfigError(f"unknown config key: {key}")
    coerced = _coerce(key, value)
    stored = load_config(repo_root)
    stored[key] = coerced
    path = config_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stored, indent=2, sort_keys=True) + "\n")
    return coerced
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_config.py -q`
Expected: PASS (all cases).

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd plugins/overseer
../../.venv/bin/ruff check scripts/config.py tests/test_config.py
../../.venv/bin/mypy scripts/config.py
git add scripts/config.py tests/test_config.py
git commit -m "feat(overseer): per-repo context config store"
```

---

## Task 2: Root-keyed orchestrator state

**Files:**
- Create: `plugins/overseer/scripts/orchestrator.py`
- Test: `plugins/overseer/tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `state_root` from `scripts.store`.
- Produces (all take `repo_root: Path`):
  - `orchestrator_dir(repo_root) -> Path` = `state_root(repo_root) / "orchestrator"`
  - Path helpers: `active_marker`, `clear_flag`, `paused_flag`, `cooldown_marker`, `handoff_path`
  - `promote(repo_root) -> None` (touch `active`)
  - `is_active(repo_root) -> bool`
  - `pause(repo_root) -> None`, `resume(repo_root) -> None`, `is_paused(repo_root) -> bool`
  - `request_clear(repo_root, handoff_text: str) -> str` — returns one of `"armed" | "paused" | "cooldown" | "inactive"`; on `"armed"` it writes the handoff and touches the flag.
  - `consume_clear_flag(repo_root) -> bool` — the Stop-hook decision: True iff active, not paused, and flag set; removes the flag and sets the cooldown *before* returning True.
  - `arm_ready(repo_root) -> None` — clears the cooldown (called by SessionStart(clear) after re-inject) and clears any leftover flag.
  - `read_handoff(repo_root) -> str | None`

- [ ] **Step 1: Write the failing test**

Create `plugins/overseer/tests/test_orchestrator.py`:

```python
from scripts import orchestrator as orch
from scripts.store import init_workflow


class TestPromotion:
    def test_inactive_by_default(self, tmp_path):
        init_workflow(tmp_path)
        assert orch.is_active(tmp_path) is False

    def test_promote_sets_active(self, tmp_path):
        init_workflow(tmp_path)
        orch.promote(tmp_path)
        assert orch.is_active(tmp_path) is True


class TestRequestClear:
    def test_inactive_refuses(self, tmp_path):
        init_workflow(tmp_path)
        assert orch.request_clear(tmp_path, "HANDOFF") == "inactive"
        assert orch.read_handoff(tmp_path) is None

    def test_active_arms_and_writes_handoff(self, tmp_path):
        init_workflow(tmp_path)
        orch.promote(tmp_path)
        assert orch.request_clear(tmp_path, "HANDOFF BODY") == "armed"
        assert orch.clear_flag(tmp_path).exists()
        assert orch.read_handoff(tmp_path) == "HANDOFF BODY"

    def test_paused_refuses(self, tmp_path):
        init_workflow(tmp_path)
        orch.promote(tmp_path)
        orch.pause(tmp_path)
        assert orch.request_clear(tmp_path, "H") == "paused"
        assert not orch.clear_flag(tmp_path).exists()


class TestConsume:
    def test_consume_removes_flag_and_sets_cooldown(self, tmp_path):
        init_workflow(tmp_path)
        orch.promote(tmp_path)
        orch.request_clear(tmp_path, "H")
        assert orch.consume_clear_flag(tmp_path) is True
        assert not orch.clear_flag(tmp_path).exists()
        assert orch.cooldown_marker(tmp_path).exists()

    def test_consume_noop_without_flag(self, tmp_path):
        init_workflow(tmp_path)
        orch.promote(tmp_path)
        assert orch.consume_clear_flag(tmp_path) is False

    def test_consume_noop_when_inactive(self, tmp_path):
        init_workflow(tmp_path)
        orch.clear_flag(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        orch.clear_flag(tmp_path).touch()
        assert orch.consume_clear_flag(tmp_path) is False

    def test_consume_noop_when_paused(self, tmp_path):
        init_workflow(tmp_path)
        orch.promote(tmp_path)
        orch.request_clear(tmp_path, "H")
        orch.pause(tmp_path)
        assert orch.consume_clear_flag(tmp_path) is False
        assert orch.clear_flag(tmp_path).exists()


class TestCooldown:
    def test_request_clear_refuses_during_cooldown(self, tmp_path):
        init_workflow(tmp_path)
        orch.promote(tmp_path)
        orch.request_clear(tmp_path, "H")
        orch.consume_clear_flag(tmp_path)  # sets cooldown
        assert orch.request_clear(tmp_path, "H2") == "cooldown"

    def test_arm_ready_clears_cooldown_and_flag(self, tmp_path):
        init_workflow(tmp_path)
        orch.promote(tmp_path)
        orch.request_clear(tmp_path, "H")
        orch.consume_clear_flag(tmp_path)
        orch.arm_ready(tmp_path)
        assert not orch.cooldown_marker(tmp_path).exists()
        assert orch.request_clear(tmp_path, "H3") == "armed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_orchestrator.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.orchestrator'`.

- [ ] **Step 3: Write minimal implementation**

Create `plugins/overseer/scripts/orchestrator.py`:

```python
"""Root-keyed orchestrator runtime state under <state_root>/orchestrator/.

The state root is the per-orchestrator key: one root, one writer, one orchestrator.
Every function is quarantine-safe by construction — it only touches its own marker
files and never raises on a missing path.
"""
from __future__ import annotations

from pathlib import Path

from scripts.store import state_root


def orchestrator_dir(repo_root: Path) -> Path:
    return state_root(repo_root) / "orchestrator"


def _ensure(repo_root: Path) -> Path:
    d = orchestrator_dir(repo_root)
    d.mkdir(parents=True, exist_ok=True)
    return d


def active_marker(repo_root: Path) -> Path:
    return orchestrator_dir(repo_root) / "active"


def clear_flag(repo_root: Path) -> Path:
    return orchestrator_dir(repo_root) / "clear-requested"


def paused_flag(repo_root: Path) -> Path:
    return orchestrator_dir(repo_root) / "paused"


def cooldown_marker(repo_root: Path) -> Path:
    return orchestrator_dir(repo_root) / "cooldown"


def handoff_path(repo_root: Path) -> Path:
    return orchestrator_dir(repo_root) / "handoff.md"


def promote(repo_root: Path) -> None:
    _ensure(repo_root)
    active_marker(repo_root).touch()


def is_active(repo_root: Path) -> bool:
    return active_marker(repo_root).exists()


def is_paused(repo_root: Path) -> bool:
    return paused_flag(repo_root).exists()


def pause(repo_root: Path) -> None:
    _ensure(repo_root)
    paused_flag(repo_root).touch()


def resume(repo_root: Path) -> None:
    paused_flag(repo_root).unlink(missing_ok=True)


def request_clear(repo_root: Path, handoff_text: str) -> str:
    if not is_active(repo_root):
        return "inactive"
    if is_paused(repo_root):
        return "paused"
    if cooldown_marker(repo_root).exists():
        return "cooldown"
    _ensure(repo_root)
    handoff_path(repo_root).write_text(handoff_text)
    clear_flag(repo_root).touch()
    return "armed"


def consume_clear_flag(repo_root: Path) -> bool:
    if not is_active(repo_root) or is_paused(repo_root):
        return False
    if not clear_flag(repo_root).exists():
        return False
    clear_flag(repo_root).unlink(missing_ok=True)  # remove FIRST: cannot re-fire
    _ensure(repo_root)
    cooldown_marker(repo_root).touch()
    return True


def arm_ready(repo_root: Path) -> None:
    cooldown_marker(repo_root).unlink(missing_ok=True)
    clear_flag(repo_root).unlink(missing_ok=True)


def read_handoff(repo_root: Path) -> str | None:
    path = handoff_path(repo_root)
    if not path.exists():
        return None
    try:
        return path.read_text()
    except OSError:
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_orchestrator.py -q`
Expected: PASS (all cases).

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd plugins/overseer
../../.venv/bin/ruff check scripts/orchestrator.py tests/test_orchestrator.py
../../.venv/bin/mypy scripts/orchestrator.py
git add scripts/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(overseer): root-keyed orchestrator runtime state"
```

---

## Task 3: Context accounting from the transcript JSONL

**Files:**
- Create: `plugins/overseer/scripts/context.py`
- Test: `plugins/overseer/tests/test_context.py`

**Interfaces:**
- Consumes: nothing from the plugin (pure stdlib); the CLI wires `Path.home()` and the config window in Task 5.
- Produces:
  - `DEFAULT_WINDOW: int = 200000`
  - `transcript_slug(cwd: Path) -> str` — Claude Code's project-dir munge: the absolute path with every non-alphanumeric char replaced by `-`.
  - `find_transcript(cwd: Path, home: Path) -> Path | None` — newest `*.jsonl` under `home/.claude/projects/<slug>/`.
  - `context_tokens(transcript_path: Path) -> int | None` — last usage-bearing line's `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`; `None` if unreadable/absent.
  - `context_percent(tokens: int, window: int = DEFAULT_WINDOW) -> int` — rounded percent.
  - `context_line(pct: int | None, threshold: int | None) -> str` — `"ctx NN%"`, appending the threshold note only when `pct >= threshold`; `"ctx unknown"` when `pct is None`.

> **Verify at implementation (spec §12):** the transcript slug format and the exact usage field names are validated against a real Claude Code transcript during this task. The functions take explicit paths so tests use synthetic transcripts; adjust `transcript_slug`/`context_tokens` field selection if a live transcript proves a different shape, keeping the tests green.

- [ ] **Step 1: Write the failing test**

Create `plugins/overseer/tests/test_context.py`:

```python
import json

from scripts.context import (
    context_line,
    context_percent,
    context_tokens,
    find_transcript,
    transcript_slug,
)


def _write_transcript(path, *usages):
    lines = []
    for u in usages:
        lines.append(json.dumps({
            "type": "assistant",
            "message": {"usage": u},
        }))
    path.write_text("\n".join(lines) + "\n")


class TestSlug:
    def test_non_alnum_becomes_dash(self, tmp_path):
        slug = transcript_slug(tmp_path)
        assert "/" not in slug
        assert set(slug) <= set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-")


class TestFindTranscript:
    def test_none_when_no_project_dir(self, tmp_path):
        assert find_transcript(tmp_path / "repo", tmp_path / "home") is None

    def test_picks_newest_jsonl(self, tmp_path):
        cwd = tmp_path / "repo"
        cwd.mkdir()
        home = tmp_path / "home"
        proj = home / ".claude" / "projects" / transcript_slug(cwd)
        proj.mkdir(parents=True)
        old = proj / "old.jsonl"
        new = proj / "new.jsonl"
        old.write_text("{}\n")
        new.write_text("{}\n")
        import os
        os.utime(old, (1000, 1000))
        os.utime(new, (2000, 2000))
        assert find_transcript(cwd, home) == new


class TestContextTokens:
    def test_sums_last_usage(self, tmp_path):
        t = tmp_path / "t.jsonl"
        _write_transcript(
            t,
            {"input_tokens": 10, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
            {"input_tokens": 5, "cache_read_input_tokens": 40000,
             "cache_creation_input_tokens": 1000},
        )
        assert context_tokens(t) == 46005

    def test_none_when_no_usage(self, tmp_path):
        t = tmp_path / "t.jsonl"
        t.write_text('{"type":"user"}\n')
        assert context_tokens(t) is None

    def test_none_when_missing_file(self, tmp_path):
        assert context_tokens(tmp_path / "nope.jsonl") is None

    def test_skips_malformed_lines(self, tmp_path):
        t = tmp_path / "t.jsonl"
        t.write_text(
            'not json\n'
            + json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 100}}})
            + "\n"
        )
        assert context_tokens(t) == 100


class TestPercentAndLine:
    def test_percent(self):
        assert context_percent(70000, 200000) == 35

    def test_line_under_threshold_hides_note(self):
        assert context_line(20, 35) == "ctx 20%"

    def test_line_over_threshold_shows_note(self):
        line = context_line(40, 35)
        assert line.startswith("ctx 40%")
        assert "35%" in line

    def test_line_unknown(self):
        assert context_line(None, 35) == "ctx unknown"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_context.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.context'`.

- [ ] **Step 3: Write minimal implementation**

Create `plugins/overseer/scripts/context.py`:

```python
"""Live context-usage accounting from the session transcript JSONL.

Best-effort and quarantine-safe: any read/parse failure yields None, never an
exception — a context read must never break the CLI command it piggybacks on.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

DEFAULT_WINDOW = 200000

_USAGE_FIELDS = (
    "input_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def transcript_slug(cwd: Path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(cwd.resolve()))


def find_transcript(cwd: Path, home: Path) -> Path | None:
    proj = home / ".claude" / "projects" / transcript_slug(cwd)
    if not proj.is_dir():
        return None
    candidates = sorted(
        proj.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    return candidates[0] if candidates else None


def _usage_of(line: str) -> dict | None:
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    message = record.get("message") if isinstance(record, dict) else None
    usage = message.get("usage") if isinstance(message, dict) else None
    return usage if isinstance(usage, dict) else None


def context_tokens(transcript_path: Path) -> int | None:
    try:
        text = transcript_path.read_text()
    except OSError:
        return None
    latest: dict | None = None
    for line in text.splitlines():
        usage = _usage_of(line)
        if usage is not None:
            latest = usage
    if latest is None:
        return None
    return sum(int(latest.get(field, 0) or 0) for field in _USAGE_FIELDS)


def context_percent(tokens: int, window: int = DEFAULT_WINDOW) -> int:
    if window <= 0:
        return 0
    return round(100 * tokens / window)


def context_line(pct: int | None, threshold: int | None) -> str:
    if pct is None:
        return "ctx unknown"
    line = f"ctx {pct}%"
    if threshold is not None and pct >= threshold:
        line += f" — over {threshold}% threshold; consider handover"
    return line
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_context.py -q`
Expected: PASS (all cases).

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd plugins/overseer
../../.venv/bin/ruff check scripts/context.py tests/test_context.py
../../.venv/bin/mypy scripts/context.py
git add scripts/context.py tests/test_context.py
git commit -m "feat(overseer): transcript-JSONL context accounting"
```

---

## Task 4: Enriched handoff with agent-chosen notes

**Files:**
- Modify: `plugins/overseer/scripts/resume.py:99-123` (the `handoff_report` function)
- Test: `plugins/overseer/tests/test_resume.py` (add a `TestEnrichedHandoff` class)

**Interfaces:**
- Consumes: existing `handoff_data`.
- Produces: `handoff_report(repo_root: Path, data: dict | None = None, notes: str | None = None) -> str` — unchanged output when `notes` is None/empty; otherwise inserts a `## Orchestrator notes` section (verbatim prose) directly after the title, before `## In flight`.

- [ ] **Step 1: Write the failing test**

Add to `plugins/overseer/tests/test_resume.py`:

```python
class TestEnrichedHandoff:
    def test_notes_absent_by_default(self, tmp_path):
        from scripts.resume import handoff_report
        from scripts.store import init_workflow

        init_workflow(tmp_path)
        assert "## Orchestrator notes" not in handoff_report(tmp_path)

    def test_notes_embedded_verbatim(self, tmp_path):
        from scripts.resume import handoff_report
        from scripts.store import init_workflow

        init_workflow(tmp_path)
        report = handoff_report(tmp_path, notes="Watch the flaky auth test on WF-002.")
        assert "## Orchestrator notes" in report
        assert "Watch the flaky auth test on WF-002." in report
        # notes precede the in-flight rollup
        assert report.index("## Orchestrator notes") < report.index("## In flight")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_resume.py::TestEnrichedHandoff -q`
Expected: FAIL — `TypeError: handoff_report() got an unexpected keyword argument 'notes'`.

- [ ] **Step 3: Write minimal implementation**

In `plugins/overseer/scripts/resume.py`, replace the `handoff_report` signature and opening lines (currently lines 99-102):

```python
def handoff_report(
    repo_root: Path, data: dict | None = None, notes: str | None = None
) -> str:
    data = data or handoff_data(repo_root)
    lines = [f"# Handoff briefing — {data['project']}", ""]
    if notes and notes.strip():
        lines += ["## Orchestrator notes", "", notes.strip(), ""]
    lines.append("## In flight")
```

(The remainder of the function is unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_resume.py -q`
Expected: PASS — the new class and all existing `TestHandoff` cases (backward compatible).

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd plugins/overseer
../../.venv/bin/ruff check scripts/resume.py tests/test_resume.py
../../.venv/bin/mypy scripts/resume.py
git add scripts/resume.py tests/test_resume.py
git commit -m "feat(overseer): enriched handoff with orchestrator notes"
```

---

## Task 5: CLI — `config` and `context` commands + `ctx` footer

**Files:**
- Modify: `plugins/overseer/scripts/cli.py` (imports, two `cmd_*`, footer helper, `build_parser` entries)
- Test: `plugins/overseer/tests/test_cli.py` (add `TestConfigAndContext`)

**Interfaces:**
- Consumes: `scripts.config` (Task 1), `scripts.context` (Task 3), `scripts.orchestrator` (Task 2).
- Produces CLI commands:
  - `config get <key>` / `config set <key> <value>`
  - `context` — prints the `ctx NN%` line, resolving the transcript from `args.root` + `Path.home()`, the window and threshold from config.
- Produces helper: `_context_footer(repo_root: Path) -> str` — returns `"\n" + context_line(...)` when the orchestrator is active and a transcript resolves, else `""`; never raises.
- Appends `_context_footer` to `cmd_resume` and `cmd_handoff` output.

- [ ] **Step 1: Write the failing test**

Add to `plugins/overseer/tests/test_cli.py`:

```python
class TestConfigAndContext:
    def test_config_get_default(self, repo, capsys):
        assert run(repo, "config", "get", "context.threshold") == 0
        assert capsys.readouterr().out.strip() == "35"

    def test_config_set_then_get(self, repo, capsys):
        assert run(repo, "config", "set", "context.threshold", "42") == 0
        capsys.readouterr()
        run(repo, "config", "get", "context.threshold")
        assert capsys.readouterr().out.strip() == "42"

    def test_config_set_invalid_returns_1(self, repo, capsys):
        assert run(repo, "config", "set", "context.mode", "bogus") == 1
        assert "context.mode" in capsys.readouterr().err

    def test_context_unknown_without_transcript(self, repo, capsys, monkeypatch):
        # No transcript under a throwaway HOME → "ctx unknown"
        monkeypatch.setenv("HOME", str(repo / "empty-home"))
        assert run(repo, "context") == 0
        assert "ctx unknown" in capsys.readouterr().out

    def test_resume_footer_only_when_active(self, repo, capsys, monkeypatch):
        monkeypatch.setenv("HOME", str(repo / "empty-home"))
        run(repo, "resume")
        assert "ctx" not in capsys.readouterr().out
        from scripts import orchestrator as orch
        orch.promote(repo)
        run(repo, "resume")
        assert "ctx" in capsys.readouterr().out
```

> Note: `cmd_context` must read `HOME` via `Path.home()`, which honours the `HOME` env var monkeypatched above.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_cli.py::TestConfigAndContext -q`
Expected: FAIL — `argument command: invalid choice: 'config'`.

- [ ] **Step 3: Write minimal implementation**

In `plugins/overseer/scripts/cli.py`, add imports near the other `scripts.*` imports:

```python
from scripts import context as ctx  # noqa: E402
from scripts import orchestrator as orch  # noqa: E402
from scripts.config import ConfigError, get_config, load_config, set_config  # noqa: E402
```

Add the footer helper and two commands (place after `cmd_handoff`):

```python
def _context_footer(repo_root: Path) -> str:
    """`ctx NN%` line for commands the orchestrator reads at decision points.

    Best-effort: silent empty string unless promoted and a transcript resolves.
    """
    try:
        if not orch.is_active(repo_root):
            return ""
        cfg = load_config(repo_root)
        transcript = ctx.find_transcript(repo_root.resolve(), Path.home())
        tokens = ctx.context_tokens(transcript) if transcript else None
        pct = (
            ctx.context_percent(tokens, int(cfg["context.window"]))
            if tokens is not None
            else None
        )
        return "\n" + ctx.context_line(pct, int(cfg["context.threshold"]))
    except Exception:  # noqa: BLE001 — a footer must never break its host command
        return ""


def cmd_config(args: argparse.Namespace) -> int:
    if args.action == "get":
        print(get_config(args.root, args.key))
        return 0
    set_config(args.root, args.key, args.value)
    print(f"{args.key} = {get_config(args.root, args.key)}")
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    cfg = load_config(args.root)
    transcript = ctx.find_transcript(args.root.resolve(), Path.home())
    tokens = ctx.context_tokens(transcript) if transcript else None
    pct = (
        ctx.context_percent(tokens, int(cfg["context.window"]))
        if tokens is not None
        else None
    )
    print(ctx.context_line(pct, int(cfg["context.threshold"])))
    return 0
```

Append the footer in `cmd_resume` — change its print line to:

```python
    output = json.dumps(entries, indent=2) if args.json else format_report(entries)
    if not args.json:
        output += _context_footer(args.root)
    print(output)
    return 0
```

Append the footer in `cmd_handoff` — in the `else` branch, change to:

```python
    else:
        print(handoff_report(args.root, data) + _context_footer(args.root))
```

Register `ConfigError` in `main`'s except clause:

```python
    except (CardParseError, FactParseError, FileNotFoundError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
```

Add parser entries in `build_parser` (before `return parser`):

```python
    p = sub.add_parser("config")
    csub = p.add_subparsers(dest="action", required=True)
    cget = csub.add_parser("get")
    cget.add_argument("key")
    cset = csub.add_parser("set")
    cset.add_argument("key")
    cset.add_argument("value")
    p.set_defaults(func=cmd_config)

    sub.add_parser("context").set_defaults(func=cmd_context)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_cli.py -q`
Expected: PASS — new class plus all existing CLI tests.

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd plugins/overseer
../../.venv/bin/ruff check scripts/cli.py tests/test_cli.py
../../.venv/bin/mypy scripts/cli.py
git add scripts/cli.py tests/test_cli.py
git commit -m "feat(overseer): config + context CLI with ctx footer on resume/handoff"
```

---

## Task 6: CLI — `promote-orchestrator`, `context-guard`, `request-clear`

**Files:**
- Modify: `plugins/overseer/scripts/cli.py` (three `cmd_*`, parser entries)
- Test: `plugins/overseer/tests/test_cli.py` (add `TestOrchestratorCommands`)

**Interfaces:**
- Consumes: `scripts.orchestrator` (Task 2), `scripts.config` (Task 1), `handoff_report` (Task 4).
- Produces CLI commands:
  - `promote-orchestrator` — `orch.promote`; report `auto` if `$TMUX` set else `manual`, plus the configured mode.
  - `context-guard pause|resume` — `orch.pause`/`orch.resume`.
  - `request-clear [--notes TEXT]` — build `handoff_report(root, notes=...)`, call `orch.request_clear`; map result to exit code (armed→0, else 1 with a reason on stderr).

- [ ] **Step 1: Write the failing test**

Add to `plugins/overseer/tests/test_cli.py`:

```python
class TestOrchestratorCommands:
    def test_promote_reports_manual_without_tmux(self, repo, capsys, monkeypatch):
        monkeypatch.delenv("TMUX", raising=False)
        assert run(repo, "promote-orchestrator") == 0
        out = capsys.readouterr().out
        assert "manual" in out
        from scripts import orchestrator as orch
        assert orch.is_active(repo)

    def test_promote_reports_auto_with_tmux(self, repo, capsys, monkeypatch):
        monkeypatch.setenv("TMUX", "/tmp/tmux-501/default,123,0")
        assert run(repo, "promote-orchestrator") == 0
        assert "auto" in capsys.readouterr().out

    def test_request_clear_refused_when_not_promoted(self, repo, capsys):
        assert run(repo, "request-clear") == 1
        assert "inactive" in capsys.readouterr().err

    def test_request_clear_arms_after_promote(self, repo, capsys):
        run(repo, "promote-orchestrator")
        capsys.readouterr()
        assert run(repo, "request-clear", "--notes", "preserve the auth spike") == 0
        from scripts import orchestrator as orch
        assert orch.clear_flag(repo).exists()
        assert "preserve the auth spike" in orch.read_handoff(repo)

    def test_pause_blocks_request_clear(self, repo, capsys):
        run(repo, "promote-orchestrator")
        assert run(repo, "context-guard", "pause") == 0
        assert run(repo, "request-clear") == 1
        assert "paused" in capsys.readouterr().err
        assert run(repo, "context-guard", "resume") == 0
        assert run(repo, "request-clear") == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_cli.py::TestOrchestratorCommands -q`
Expected: FAIL — `argument command: invalid choice: 'promote-orchestrator'`.

- [ ] **Step 3: Write minimal implementation**

In `plugins/overseer/scripts/cli.py`, add `import os` near the top imports (after `import json`). Add the three commands (after `cmd_context`):

```python
def cmd_promote_orchestrator(args: argparse.Namespace) -> int:
    orch.promote(args.root)
    mode = str(load_config(args.root)["context.mode"])
    auto = "auto" if os.environ.get("TMUX") else "manual"
    hint = (
        "Stop hook will send /clear unattended"
        if auto == "auto"
        else "no tmux — checkpoint and ask the user to type /clear"
    )
    print(f"orchestrator active ({auto}, {mode} run mode) — {hint}")
    return 0


def cmd_context_guard(args: argparse.Namespace) -> int:
    if args.action == "pause":
        orch.pause(args.root)
        print("auto-handover paused")
    else:
        orch.resume(args.root)
        print("auto-handover resumed")
    return 0


_REQUEST_CLEAR_REASON = {
    "inactive": "not an active orchestrator (run promote-orchestrator first)",
    "paused": "auto-handover is paused (context-guard resume to re-enable)",
    "cooldown": "just cleared — cooldown active, nothing to do",
}


def cmd_request_clear(args: argparse.Namespace) -> int:
    text = handoff_report(args.root, notes=args.notes)
    result = orch.request_clear(args.root, text)
    if result == "armed":
        print("handover armed — will /clear at end of this turn (auto) "
              "or on your /clear (manual)")
        return 0
    print(f"request-clear refused: {_REQUEST_CLEAR_REASON[result]}", file=sys.stderr)
    return 1
```

Add parser entries in `build_parser`:

```python
    sub.add_parser("promote-orchestrator").set_defaults(func=cmd_promote_orchestrator)

    p = sub.add_parser("context-guard")
    p.add_argument("action", choices=["pause", "resume"])
    p.set_defaults(func=cmd_context_guard)

    p = sub.add_parser("request-clear")
    p.add_argument("--notes")
    p.set_defaults(func=cmd_request_clear)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_cli.py -q`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd plugins/overseer
../../.venv/bin/ruff check scripts/cli.py tests/test_cli.py
../../.venv/bin/mypy scripts/cli.py
git add scripts/cli.py tests/test_cli.py
git commit -m "feat(overseer): promote/context-guard/request-clear CLI"
```

---

## Task 7: CLI — hook back-ends (`stop-hook`, `session-start-hook`)

**Files:**
- Modify: `plugins/overseer/scripts/cli.py` (two `cmd_*` reading JSON from stdin, parser entries)
- Test: `plugins/overseer/tests/test_cli.py` (add `TestHookBackends`)

**Interfaces:**
- Consumes: `scripts.orchestrator` (Task 2), `sys.stdin`.
- Produces CLI commands (both read a hook JSON payload on stdin and derive the state root from its `cwd`, falling back to `--root`; both always return 0):
  - `stop-hook` — if `consume_clear_flag(root)` → print `DISPATCH_CLEAR`; else print nothing.
  - `session-start-hook` — if active and a handoff exists → print the `additionalContext` JSON carrying the handoff, then `arm_ready(root)`; else print nothing.
- Helper: `_hook_root(args) -> Path` — parse stdin JSON, return `Path(payload["cwd"])` if present else `args.root`.

- [ ] **Step 1: Write the failing test**

Add to `plugins/overseer/tests/test_cli.py` (top of file already imports `json`, `sys`, `pytest`):

```python
class TestHookBackends:
    def _stdin(self, monkeypatch, payload):
        import io
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))

    def test_stop_hook_dispatches_when_armed(self, repo, capsys, monkeypatch):
        from scripts import orchestrator as orch
        orch.promote(repo)
        orch.request_clear(repo, "H")
        self._stdin(monkeypatch, {"cwd": str(repo)})
        assert run(repo, "stop-hook") == 0
        assert "DISPATCH_CLEAR" in capsys.readouterr().out
        assert not orch.clear_flag(repo).exists()

    def test_stop_hook_silent_without_flag(self, repo, capsys, monkeypatch):
        from scripts import orchestrator as orch
        orch.promote(repo)
        self._stdin(monkeypatch, {"cwd": str(repo)})
        assert run(repo, "stop-hook") == 0
        assert capsys.readouterr().out.strip() == ""

    def test_stop_hook_silent_on_bad_stdin(self, repo, capsys, monkeypatch):
        import io
        monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
        assert run(repo, "stop-hook") == 0
        assert capsys.readouterr().out.strip() == ""

    def test_session_start_injects_handoff(self, repo, capsys, monkeypatch):
        from scripts import orchestrator as orch
        orch.promote(repo)
        orch.request_clear(repo, "HANDOFF PAYLOAD")
        orch.consume_clear_flag(repo)  # cooldown set, as after an auto /clear
        self._stdin(monkeypatch, {"cwd": str(repo), "source": "clear"})
        assert run(repo, "session-start-hook") == 0
        out = capsys.readouterr().out
        assert "HANDOFF PAYLOAD" in out
        assert "additionalContext" in out
        assert orch.cooldown_marker(repo).exists() is False  # re-armed

    def test_session_start_silent_when_inactive(self, repo, capsys, monkeypatch):
        self._stdin(monkeypatch, {"cwd": str(repo), "source": "startup"})
        assert run(repo, "session-start-hook") == 0
        assert capsys.readouterr().out.strip() == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_cli.py::TestHookBackends -q`
Expected: FAIL — `argument command: invalid choice: 'stop-hook'`.

- [ ] **Step 3: Write minimal implementation**

In `plugins/overseer/scripts/cli.py`, add the helper and two commands (after `cmd_request_clear`):

```python
def _hook_root(args: argparse.Namespace) -> Path:
    try:
        payload = json.loads(sys.stdin.read())
        cwd = payload.get("cwd") if isinstance(payload, dict) else None
    except (json.JSONDecodeError, OSError, ValueError):
        cwd = None
    return Path(cwd) if cwd else args.root


def cmd_stop_hook(args: argparse.Namespace) -> int:
    root = _hook_root(args)
    if orch.consume_clear_flag(root):
        print("DISPATCH_CLEAR")
    return 0


def cmd_session_start_hook(args: argparse.Namespace) -> int:
    root = _hook_root(args)
    if orch.is_active(root):
        handoff = orch.read_handoff(root)
        if handoff:
            payload = {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": handoff,
                }
            }
            print(json.dumps(payload))
        orch.arm_ready(root)
    return 0
```

Add parser entries:

```python
    sub.add_parser("stop-hook").set_defaults(func=cmd_stop_hook)
    sub.add_parser("session-start-hook").set_defaults(func=cmd_session_start_hook)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_cli.py -q`
Expected: PASS.

- [ ] **Step 5: Lint, type-check, commit**

```bash
cd plugins/overseer
../../.venv/bin/ruff check scripts/cli.py tests/test_cli.py
../../.venv/bin/mypy scripts/cli.py
git add scripts/cli.py tests/test_cli.py
git commit -m "feat(overseer): stdin-driven stop-hook and session-start-hook back-ends"
```

---

## Task 8: Plugin-shipped hook scripts + registration

**Files:**
- Create: `plugins/overseer/hooks/hooks.json`
- Create: `plugins/overseer/hooks/stop.sh`
- Create: `plugins/overseer/hooks/session-start.sh`
- Test: `plugins/overseer/tests/test_hooks.py`

**Interfaces:**
- Consumes: the `stop-hook` / `session-start-hook` CLI back-ends (Task 7); `${CLAUDE_PLUGIN_ROOT}` (set by Claude Code to the plugin dir); `$TMUX`, `$TMUX_PANE` (set by tmux); `$OVERSEER_CLEAR_DELAY` (test override for the send-keys sleep, default 1).
- Produces: two executable bash scripts and the JSON that registers them.

**Design notes for the implementer:**
- `hooks.json` lives at the **plugin root** (`hooks/hooks.json`), NOT under `.claude-plugin/`. Reference scripts via `${CLAUDE_PLUGIN_ROOT}`.
- The `Stop` hook is inert in manual mode: it exits immediately when `$TMUX` is unset, so it never consumes the flag when it could not dispatch (manual mode clears via the human + the SessionStart re-inject).
- Every script opens with `trap 'exit 0' EXIT` and tolerates each side-effect with `|| true`, so any internal failure still exits 0.

- [ ] **Step 1: Write the failing test**

Create `plugins/overseer/tests/test_hooks.py`:

```python
import json
import os
import subprocess
import time
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
STOP = PLUGIN_ROOT / "hooks" / "stop.sh"
SESSION_START = PLUGIN_ROOT / "hooks" / "session-start.sh"
PYTHON = PLUGIN_ROOT.parent.parent / ".venv" / "bin" / "python"


def _run(script, payload, env, cwd):
    return subprocess.run(
        ["bash", str(script)],
        input=json.dumps(payload),
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _base_env(extra):
    env = dict(os.environ)
    env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
    env.update(extra)
    return env


def _promote_and_arm(repo):
    from scripts.cli import main
    main(["--root", str(repo), "init"])
    from scripts import orchestrator as orch
    orch.promote(repo)
    orch.request_clear(repo, "HANDOFF FROM HOOK TEST")
    return orch


class TestStopHook:
    def test_hooks_json_registers_both(self):
        data = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())
        assert "Stop" in data["hooks"]
        assert "SessionStart" in data["hooks"]
        ss = data["hooks"]["SessionStart"][0]
        assert "startup" in ss["matcher"] and "clear" in ss["matcher"]

    def test_manual_mode_exits_0_and_keeps_flag(self, tmp_path):
        orch = _promote_and_arm(tmp_path)
        env = _base_env({"OVERSEER_CLEAR_DELAY": "0"})
        env.pop("TMUX", None)
        result = _run(STOP, {"cwd": str(tmp_path)}, env, tmp_path)
        assert result.returncode == 0
        assert orch.clear_flag(tmp_path).exists()  # not consumed in manual mode

    def test_auto_mode_sends_keys_and_exits_0(self, tmp_path):
        orch = _promote_and_arm(tmp_path)
        # fake tmux on PATH records its argv to a marker file
        bindir = tmp_path / "bin"
        bindir.mkdir()
        marker = tmp_path / "tmux-called"
        fake = bindir / "tmux"
        fake.write_text('#!/usr/bin/env bash\necho "$@" >> "%s"\n' % marker)
        fake.chmod(0o755)
        env = _base_env({
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "TMUX": "/tmp/fake,1,0",
            "TMUX_PANE": "%9",
            "OVERSEER_CLEAR_DELAY": "0",
        })
        result = _run(STOP, {"cwd": str(tmp_path)}, env, tmp_path)
        assert result.returncode == 0
        assert not orch.clear_flag(tmp_path).exists()  # consumed
        deadline = time.time() + 3
        while time.time() < deadline and not marker.exists():
            time.sleep(0.05)
        assert marker.exists()
        assert "/clear" in marker.read_text()

    def test_induced_failure_still_exits_0(self, tmp_path):
        _promote_and_arm(tmp_path)
        # TMUX set but tmux binary absent from PATH, bad pane target, junk stdin
        env = _base_env({
            "PATH": str(tmp_path / "no-such-bin"),
            "TMUX": "/tmp/fake,1,0",
            "TMUX_PANE": "%does-not-exist",
            "OVERSEER_CLEAR_DELAY": "0",
        })
        result = subprocess.run(
            ["bash", str(STOP)], input="not json at all",
            env=env, cwd=tmp_path, capture_output=True, text=True,
        )
        assert result.returncode == 0


class TestSessionStartHook:
    def test_injects_handoff_json(self, tmp_path):
        orch = _promote_and_arm(tmp_path)
        orch.consume_clear_flag(tmp_path)
        env = _base_env({})
        result = _run(SESSION_START, {"cwd": str(tmp_path), "source": "clear"},
                      env, tmp_path)
        assert result.returncode == 0
        assert "HANDOFF FROM HOOK TEST" in result.stdout
        assert "additionalContext" in result.stdout

    def test_silent_and_exit_0_when_inactive(self, tmp_path):
        from scripts.cli import main
        main(["--root", str(tmp_path), "init"])
        env = _base_env({})
        result = _run(SESSION_START, {"cwd": str(tmp_path), "source": "startup"},
                      env, tmp_path)
        assert result.returncode == 0
        assert result.stdout.strip() == ""
```

> The `test_hooks.py` scripts shell out to `bash`; they exercise the real hook scripts against the real CLI. They rely on the worktree venv Python being resolvable from the hook (see Step 3 — the hook must locate a Python interpreter deterministically).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_hooks.py -q`
Expected: FAIL — `FileNotFoundError` / missing `hooks/hooks.json` and scripts.

- [ ] **Step 3: Write the hook scripts and registration**

Create `plugins/overseer/hooks/hooks.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|clear",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/stop.sh"
          }
        ]
      }
    ]
  }
}
```

Create `plugins/overseer/hooks/stop.sh`:

```bash
#!/usr/bin/env bash
# Overseer Stop hook — the /clear dispatcher.
#
# Safety is structural: this hook ALWAYS exits 0. A Stop hook that exits 2 (or
# emits {"decision":"block"}) forces the model to continue — the one and only
# cause of the costly infinite-continuation loop. The trap below forces exit 0
# on EVERY path (normal end, `set -e`, any failed command, a parse error), so a
# blocking exit can never escape. Every side-effect is `|| true`-tolerant too.
trap 'exit 0' EXIT

# Manual mode (no tmux): the hook is inert. A present human types /clear; the
# flag is left for the SessionStart re-inject. Exit before consuming anything.
[ -z "${TMUX:-}" ] && exit 0

input="$(cat)"

# Locate an interpreter: prefer the worktree venv, else system python3.
py="python3"
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python" ]; then
  py="${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python"
fi

decision="$(printf '%s' "$input" \
  | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" stop-hook 2>/dev/null || true)"

if [ "$decision" = "DISPATCH_CLEAR" ]; then
  delay="${OVERSEER_CLEAR_DELAY:-1}"
  # Redirect the WHOLE subshell: a backgrounded child that inherits the hook's
  # stdout pipe would make Claude Code (and captured-output test runners) block
  # until it exits. Detach its fds so the hook returns immediately.
  ( sleep "$delay"; tmux send-keys -t "${TMUX_PANE:-}" "/clear" Enter || true ) \
    >/dev/null 2>&1 </dev/null &
fi

exit 0
```

Create `plugins/overseer/hooks/session-start.sh`:

```bash
#!/usr/bin/env bash
# Overseer SessionStart hook — re-injects the handoff after /clear (or on launch).
# Fires for matchers startup|clear. Exits 0 always; its additionalContext stdout
# is emitted before the trap fires. Inert (silent) unless the cwd's state root is
# a promoted orchestrator with a handoff on file.
trap 'exit 0' EXIT

input="$(cat)"

py="python3"
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python" ]; then
  py="${CLAUDE_PLUGIN_ROOT}/../../.venv/bin/python"
fi

printf '%s' "$input" \
  | "$py" "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" session-start-hook 2>/dev/null || true

exit 0
```

Make them executable:

```bash
chmod +x plugins/overseer/hooks/stop.sh plugins/overseer/hooks/session-start.sh
```

> **Implementer note on the interpreter path:** the `../../.venv/bin/python` heuristic assumes the plugin sits at `<repo>/plugins/overseer` with the venv at `<repo>/.venv` (true in this worktree, where the venv is gitignored). The venv is *preferred* because `cli.py` imports `scripts.knowledge` → `yaml` at module load, so **any** CLI invocation — including the `stop-hook` / `session-start-hook` back-ends — requires PyYAML. The venv guarantees it. The fallback to system `python3` therefore only works if that interpreter also has PyYAML installed; if a target install lacks the venv, document `pip install pyyaml` (or a plugin-local venv) as a prerequisite. Confirm the interpreter resolves and imports cleanly during the manual e2e check (Task 10). A defensive `|| true` on the pipeline already guarantees the hook still exits 0 even if the interpreter import fails.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_hooks.py -q`
Expected: PASS (all cases, including induced-failure exit-0).

- [ ] **Step 5: Lint the JSON, commit**

```bash
cd plugins/overseer
../../.venv/bin/python -c "import json; json.load(open('hooks/hooks.json'))"
../../.venv/bin/ruff check tests/test_hooks.py
git add hooks/ tests/test_hooks.py
git commit -m "feat(overseer): plugin-shipped Stop and SessionStart hooks"
```

---

## Task 9: Register hooks in the plugin manifest

**Files:**
- Modify: `plugins/overseer/.claude-plugin/plugin.json`
- Test: `plugins/overseer/tests/test_hooks.py` (add a manifest assertion)

**Interfaces:**
- Produces: a `plugin.json` that Claude Code loads such that `hooks/hooks.json` is active when the plugin is enabled. (Per the hooks research, a plugin's `hooks/hooks.json` is auto-discovered; this task makes the linkage explicit and bumps the version.)

- [ ] **Step 1: Write the failing test**

Add to `plugins/overseer/tests/test_hooks.py`:

```python
class TestManifest:
    def test_plugin_version_bumped(self):
        data = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())
        assert data["version"] == "0.5.0"

    def test_hooks_file_present_and_valid(self):
        # The shipped hooks file must exist and parse (Claude Code auto-discovers it).
        data = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())
        assert set(data["hooks"]) == {"SessionStart", "Stop"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_hooks.py::TestManifest -q`
Expected: FAIL — version is `0.4.0`.

- [ ] **Step 3: Write minimal implementation**

Edit `plugins/overseer/.claude-plugin/plugin.json` — bump the version to `0.5.0` and update the description to mention context stewardship:

```json
{
  "name": "overseer",
  "version": "0.5.0",
  "description": "Workflow orchestration: a persistent per-repo ledger of cards, sprints and token budgets, plus an orchestrator skill that drives cards end-to-end with delegated agents and adversarial review loops, and in-process context stewardship (agent-driven /clear handover via Stop/SessionStart hooks).",
  "author": {
    "name": "Pip",
    "url": "https://github.com/ppryde/pip-skills"
  },
  "keywords": ["workflow", "ledger", "sprints", "orchestration", "task-tracking", "budgets", "context"]
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_hooks.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd plugins/overseer
../../.venv/bin/python -c "import json; json.load(open('.claude-plugin/plugin.json'))"
git add .claude-plugin/plugin.json tests/test_hooks.py
git commit -m "feat(overseer): register context hooks, bump plugin to 0.5.0"
```

---

## Task 10: Doctrine + README + manual e2e check

**Files:**
- Modify: `plugins/overseer/skills/orchestrate/SKILL.md:142-150` (the `## Context stewardship` section)
- Modify: `plugins/overseer/README.md`
- Create: `docs/superpowers/specs/2026-07-10-overseer-context-limit-e2e.md` (the documented manual check)

**Interfaces:**
- Consumes: every command shipped in Tasks 5–9 (`context`, `promote-orchestrator`, `context-guard`, `request-clear`), referenced by name in the doctrine.
- Produces: doctrine and docs only — no code, no tests. This is the final task; it makes the feature usable.

- [ ] **Step 1: Rewrite the doctrine**

Replace the `## Context stewardship` section in `plugins/overseer/skills/orchestrate/SKILL.md` (lines 142-150) with:

```markdown
## Context stewardship
You reset your OWN context in place — via `/clear` — at points you choose, then
resume from a re-injected handover. This keeps per-turn context small and
cache-friendly on long unsupervised runs. It is real and measured, not
aspirational.

- **Become an orchestrator.** A plain chat is inert until promoted. On first
  taking a card (or on the user's word), run `promote-orchestrator`. It reports
  **auto** (under tmux — the Stop hook can send `/clear` unattended) or
  **manual** (no tmux — you checkpoint and ask the user to type `/clear`).
- **Watch the number.** `resume` and `handoff` now carry a `ctx NN%` footer
  (pulled from config, shown against the threshold only when over — never a
  hardcoded number). Read it at stage boundaries and card completion.
- **You decide to hand over — never a blind threshold.** Hand over when:
  (a) `ctx NN%` is over the configured threshold AND you are at a clean stop
  point (between stages, not mid-dispatch); or (b) a card completes — hand over
  and start fresh regardless of the exact percentage; or (c) the user commands it.
- **How.** Run `request-clear --notes "<the critical prose a fresh you must
  know that the cards don't already capture>"`. It writes the enriched handover
  and arms the reset. In auto mode the Stop hook sends `/clear` when your turn
  ends; in manual mode you tell the user to type `/clear`. Either way
  `SessionStart` re-injects the handover and you resume lean.
- **Defer for a live human.** Never clear a discussion out from under the user:
  while a live exchange is in progress, hold off, and run `context-guard pause`
  when someone joins an overnight run (e.g. on mobile). `context-guard resume`
  re-arms. Always wait for an in-flight dispatch to return before handing over.
- Gaps >5 minutes between actions cost cache re-reads — a fresh session can be
  cheaper for a big batch. No heroic high-context finishes.
```

- [ ] **Step 2: Update the README**

In `plugins/overseer/README.md`, add a `## Requirements` section after the intro (before `## What it does`):

```markdown
## Requirements

- **Python 3.11+** with PyYAML.
- **tmux** — required for automatic in-process context handover (the orchestrator
  resets its own context via `/clear` at points it chooses). tmux owns the pty,
  injects the `/clear` keystroke, and tears down cleanly. Install with
  `brew install tmux` (macOS) or your package manager. Without tmux the
  orchestrator still runs, but context handover is **manual** (it checkpoints and
  asks you to type `/clear`). Apple's bundled `screen` (v4.00.03) cannot drive
  the modern TUI and is not supported.
```

Add a bullet to `## What it does`:

```markdown
- Agent-driven context stewardship (phase 5): a promoted orchestrator caps its
  own context creep by resetting in-process via `/clear` at points it chooses,
  resuming from a re-injected handover. Driven by a fail-safe `Stop` hook (auto,
  under tmux) or the human (manual); configured per-repo via
  `config set context.threshold|context.mode`; toggled with `context-guard
  pause|resume`. See the phase-5 design spec.
```

Add to the Development section's spec list:

```markdown
Phase 5 design spec: `docs/superpowers/specs/2026-07-10-overseer-context-limit-design.md`.
```

- [ ] **Step 3: Write the documented manual e2e check**

Create `docs/superpowers/specs/2026-07-10-overseer-context-limit-e2e.md`:

```markdown
# Overseer context-limit — manual end-to-end check

Generalised from the proving spike. Confirms promote → threshold → `/clear` →
`SessionStart(clear)` re-inject, verified by observable effects.

## Prerequisites
- tmux installed; run from an already-trusted worktree (else Claude Code hangs
  at the folder-trust gate before hooks engage).
- The overseer plugin enabled (its `hooks/hooks.json` active).

## Steps
1. Launch Claude under tmux in the trusted worktree:
   `tmux new-session -d -s overseer-e2e -c <worktree> claude`
   (add `--remote-control <name>` if `context.mode` is `remote`).
2. In the session, initialise + promote:
   `python plugins/overseer/scripts/cli.py init`
   `python plugins/overseer/scripts/cli.py promote-orchestrator`  → expect "auto".
3. Arm a handover with preserved prose:
   `python plugins/overseer/scripts/cli.py request-clear --notes "e2e marker: keep this"`
4. End the turn (let the agent go idle). The Stop hook should
   `tmux send-keys "/clear"` after ~1s.
5. Confirm the reset: the transcript context drops to near-empty and the injected
   handover — including "e2e marker: keep this" — is present in the fresh context
   (SessionStart(clear) re-injected it).
6. Confirm no loop: exactly one `/clear` fired; the session is idle, not spinning.

## Teardown
`tmux kill-session -t overseer-e2e`

## What each layer proved (spike, 2026-07-10)
- SessionStart injects `additionalContext` (incl. `--remote-control`). ✅
- `/clear` fires `SessionStart(source=clear)` and truly empties context. ✅
- Stop hook → `tmux send-keys "/clear"` → reset → re-inject, single dispatch. ✅
- Exit-2/`block` is the sole infinite-loop cause; our hook never blocks. ✅
```

- [ ] **Step 4: Verify the docs are coherent**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest -q`
Expected: PASS — full suite still green (no code changed in this task).

Manually confirm: the doctrine references only commands that exist (`promote-orchestrator`, `request-clear`, `context-guard`, and the `ctx NN%` footer on `resume`/`handoff`).

- [ ] **Step 5: Commit**

```bash
cd plugins/overseer
git add skills/orchestrate/SKILL.md README.md
git add ../../docs/superpowers/specs/2026-07-10-overseer-context-limit-e2e.md
git commit -m "docs(overseer): context-stewardship doctrine, tmux requirement, e2e check"
```

---

## Final verification

After Task 10, run the whole gate from `plugins/overseer/`:

```bash
../../.venv/bin/python -m pytest -q
../../.venv/bin/ruff check scripts tests
../../.venv/bin/mypy scripts
```

Expected: all tests pass; ruff clean; mypy clean. Then confirm the manual e2e
check (Task 10, Step 3 doc) passes on a real tmux-hosted session before relying
on unattended overnight handover.

## Spec coverage map

| Spec section | Task(s) |
|---|---|
| §1 reset loop | 2, 7, 8 (flag → Stop hook → /clear → SessionStart re-inject) |
| §2 agent-decides trigger | 6 (`request-clear`), 10 (doctrine) |
| §3 components: `context` | 3, 5 |
| §3 components: `request-clear` | 4, 6 |
| §3 components: `context-guard` | 2, 6 |
| §3 components: `promote-orchestrator` | 2, 6 |
| §3 enriched handoff | 4 |
| §3 Stop hook | 7, 8 |
| §3 SessionStart hook | 7, 8 |
| §4 state-root keying | 2 (`<state_root>/orchestrator/`) |
| §5 on/off + in-place promotion | 2, 6, 8 (marker-gated; manual-mode inert Stop hook) |
| §5 pause/resume | 2, 6 |
| §5 auto vs manual | 6 (promote report), 8 (Stop hook TMUX gate) |
| §6 launch/env, run modes | 1 (`context.mode`), 10 (README tmux, e2e) |
| §7 no infinite loop | 8 (`trap 'exit 0'`, exit-0 only) |
| §7 fail-safe wrapper | 8 (induced-failure test) |
| §7 no re-fire / cooldown | 2 (`consume_clear_flag` removes flag first, sets cooldown) |
| §7 scoped teardown | 8 (`$TMUX_PANE` only) |
| §7 quarantine-safe | 1, 2, 3 (corrupt/missing → fall back, never raise) |
| §8 config | 1, 5 |
| §9 doctrine | 10 |
| §10 testing | every task's tests; 8 (hook shell tests); 10 (e2e doc) |
| §12 verify-at-implementation | 3 (transcript fields note), 8 (interpreter path note) |
| §13 non-goals | respected — no supervisor process, orchestrator-only |
