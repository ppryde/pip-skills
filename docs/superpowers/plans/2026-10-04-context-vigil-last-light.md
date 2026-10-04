# context-vigil: last light, end-of-turn notice, vigil bar — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add last light (prepare a handover before an idle 1-hour prompt cache goes cold), a user-only end-of-turn Stop notice, an optional pop-up "vigil bar" mod, a never-type-into-a-dialog safety net, install questions as AskUserQuestion cards, and an emoji-led user-facing voice.

**Architecture:** Python stays the single source of truth: hooks (`hooks.py`) and the status-line ingest (`cli._cmd_ingest`) call small focused modules — `messages.py` (user-facing strings, one JSON emitter), `pane.py` (is this tmux pane safe to type into), `last_light.py` (the tick and its gates), `cards.py` (install question cards). State stays in the existing session records (`session.py`) and scope markers (`state.py`). The vigil bar is a separate Claude Code mod under `skills/context-vigil/mod/` that reads context-vigil's config file read-only.

**Tech Stack:** Python ≥ 3.9 stdlib only (the suite has a py3.9 smoke test — `from __future__ import annotations`, `typing.Optional/List/Dict`, no `match`, no `X | Y` at runtime), pytest; a TypeScript/TSX Claude Code mod (`claude plugin validate`, `claude plugin test`); tmux.

**Spec:** `docs/superpowers/specs/2026-10-04-context-vigil-last-light-design.md` — read it first; this plan argues from it.

## Global Constraints

- Run tests from the repo root: `PYTHONPATH=skills/context-vigil/scripts .venv/bin/python -m pytest -q tests/context_vigil_suite` (plain `pytest` cannot import `context_vigil`). Full suite ≈ 65 s, 687 tests green at start.
- Lint only files you touch: `.venv/bin/ruff check <files>` (a directory-wide run surfaces pre-existing findings in untouched files — leave those alone).
- Tests never touch real state: the autouse `iso` fixture in `tests/context_vigil_suite/conftest.py` pins `HOME`, `CLAUDE_CONFIG_DIR`, `CONTEXT_VIGIL_HOME`, strips `TMUX*`/`CONTEXT_VIGIL_*`, and points `CONTEXT_VIGIL_TMUX_BIN` at a missing binary. Every new test relies on it; tmux is only ever a stub script.
- Stop-hook output is **exactly one `json.dumps(...)` object or nothing**; never `decision`, `block`, `continue`, `reason`; the launcher already forces exit 0 for `hook`. Message text ≤ 300 chars.
- Config for last light is **global only**: `last_light.enabled` (default `false`), `last_light.threshold` (default `25`, 1–95), `last_light.lead_seconds` (default `300`, 1–3600, never asked). Env overrides `CONTEXT_VIGIL_LAST_LIGHT`, `CONTEXT_VIGIL_LAST_LIGHT_THRESHOLD`, `CONTEXT_VIGIL_LAST_LIGHT_LEAD_SECONDS`.
- Last light fires only when `prompt_cache.ttl == "1h"`, `prompt_cache.warm is True`, `0 < expires_at − now ≤ lead_seconds`. A missing/odd `prompt_cache` means do nothing.
- The last-light prompt starts with the marker `[context-vigil:last-light]`. Human prompt = neither that marker, nor `<task-notification>` prefix, nor context-vigil's own kick prompt.
- Model-facing text stays plain; user-facing text uses the §4 strings verbatim (copied into `messages.py` in Task 1).
- Commit after every task with the session's attribution lines:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf
  ```

## Review Focus

1. **Stop at the end of a handover turn with the input box not yet redrawn** — auto `/clear` must still be sent when the pane is idle; if `pane_safe` is too strict, auto mode silently degrades to "type /clear". Pinned by Task 3's idle-after-turn capture test and Task 12's live `auto` smoke.
2. **A background-task notification arriving while a prepared handover waits** — must neither discard it nor re-arm last light. Pinned in Task 6 (`test_background_prompt_neither_discards_nor_arms`).
3. **Two status-line ticks at once near expiry** (two refreshes, or ingest racing a UserPromptSubmit) — exactly one prompt typed. Pinned in Task 7 (`test_concurrent_ticks_fire_once`).
4. **Hostile strings in hook payloads** (quotes, newlines, backslashes, NUL, emoji, 10 kB) — Stop output still one valid JSON object ≤ 300 chars of message. Pinned in Task 8 (`test_stop_output_is_one_json_object_for_hostile_payloads`).
5. **User typing a message in the box when last light or auto `/clear` would fire** — nothing typed over them. Pinned in Task 3 (`typed text` case) and Task 7 (`unsafe` reason).

---

## File Structure

| File | Responsibility |
|---|---|
| `skills/context-vigil/scripts/context_vigil/messages.py` (new) | Every user-facing string (§4) and `system_message(text)` — the only JSON emitter for Stop notices. |
| `skills/context-vigil/scripts/context_vigil/pane.py` (new) | Parse a `capture-pane -e` screen: is the input box visible, empty (dim placeholder allowed), with no dialog footer. |
| `skills/context-vigil/scripts/context_vigil/tmux.py` | + `capture(target)`. |
| `skills/context-vigil/scripts/context_vigil/config.py` | + three `last_light.*` keys, bool coercion, global-only rule, accessors. |
| `skills/context-vigil/scripts/context_vigil/state.py` | + prepared-handover marker, `write_prepared`, `discard_prepared`; archive name parameter. |
| `skills/context-vigil/scripts/context_vigil/session.py` | + record fields `last_light_armed`, `last_noticed_pct`. |
| `skills/context-vigil/scripts/context_vigil/last_light.py` (new) | `MARKER`, `PROMPT`, `tick(payload, now)` and `session_state(...)` for `status`. |
| `skills/context-vigil/scripts/context_vigil/hooks.py` | Prompt classification, arming/discard, Stop notice, safety net on `/clear` and kick, `NUDGE_NOTICED`. |
| `skills/context-vigil/scripts/context_vigil/cards.py` (new) | Install/last-light question cards (AskUserQuestion shape) and their option → flag map. |
| `skills/context-vigil/scripts/context_vigil/install.py` | + last-light/bar flags, `CLAUDE_CODE_PLUGIN_DIRS` edit, mods detection, summary lines. |
| `skills/context-vigil/scripts/context_vigil/cli.py` | + `handover --prepared`, `last-light` command, `install --questions-json/--last-light/--last-light-threshold/--bar`, ingest → tick, status lines. |
| `skills/context-vigil/mod/` (new) | The vigil-bar mod: `.claude-plugin/plugin.json`, `hooks/hooks.json`, `hooks/register.tsx`, `types/index.d.ts`, `hooks/register.test.ts`. |
| `skills/context-vigil/SKILL.md`, `README.md`, `dev/live-smoke`, `dev/README.md` | Docs, card flow, known limits, live scenarios. |
| Tests: `tests/context_vigil_suite/test_messages.py`, `test_pane.py`, `test_last_light.py`, `test_notice.py`, `test_cards.py` (new); `test_config.py`, `test_state.py`, `test_hooks.py`, `test_install.py`, `test_cli.py` (extend). |

---

### Task 1: User-facing strings and the single JSON emitter

**Files:**
- Create: `skills/context-vigil/scripts/context_vigil/messages.py`
- Modify: `skills/context-vigil/scripts/context_vigil/hooks.py:129-134` (the no-tmux `systemMessage` in `stop`)
- Test: `tests/context_vigil_suite/test_messages.py`

**Interfaces:**
- Produces: `messages.NOTICE_FIRST`, `NOTICE_REPEAT` (both `.format(pct=int, threshold=int)`), `SAVED_TYPE_CLEAR`, `SAVED_DIALOG_OPEN`, `LAST_LIGHT_PREPARED`, `MAX_LEN = 300`, `system_message(text: str) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/context_vigil_suite/test_messages.py
"""User-facing strings and the one JSON emitter the Stop path uses."""
from __future__ import annotations

import json

import pytest
from context_vigil import messages


def test_system_message_is_one_json_object_with_only_system_message() -> None:
    out = messages.system_message('say "hand over" \\ now\n🕯️')
    data = json.loads(out)
    assert list(data) == ["systemMessage"]
    assert data["systemMessage"] == 'say "hand over" \\ now\n🕯️'


def test_system_message_caps_length() -> None:
    data = json.loads(messages.system_message("x" * 5000))
    assert len(data["systemMessage"]) == messages.MAX_LEN


@pytest.mark.parametrize("template", [messages.NOTICE_FIRST, messages.NOTICE_REPEAT])
def test_notices_format_ints_and_fit(template: str) -> None:
    text = template.format(pct=41, threshold=35)
    assert "41%" in text and len(text) <= messages.MAX_LEN
    assert "{" not in text


def test_strings_lead_with_emoji() -> None:
    for text in (messages.NOTICE_FIRST, messages.SAVED_TYPE_CLEAR,
                 messages.SAVED_DIALOG_OPEN, messages.LAST_LIGHT_PREPARED):
        assert not text[0].isascii()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/context-vigil/scripts .venv/bin/python -m pytest -q tests/context_vigil_suite/test_messages.py`
Expected: FAIL — `ImportError: cannot import name 'messages'`

- [ ] **Step 3: Write the module**

```python
# skills/context-vigil/scripts/context_vigil/messages.py
"""Every user-facing line (spec §4) and the one emitter for hook systemMessages.

User-facing text is shown on screen (terminal, desktop, phone) and never reaches the
model. Model-facing text lives in hooks.py and stays plain.
"""
from __future__ import annotations

import json

MAX_LEN = 300

NOTICE_FIRST = ('🕯️ context-vigil · context at {pct}% (threshold {threshold}%) · say '
                '"hand over" to pass the torch 🔥 — or keep going 🚀')
NOTICE_REPEAT = ('🕯️ context-vigil · now at {pct}% ⬆️ · say "hand over" whenever '
                 "you're ready 📜")
SAVED_TYPE_CLEAR = ('📜 Handover saved — type /clear, then send any message (e.g. "go") '
                    'to pick it back up ✨ (run Claude inside tmux for hands-free '
                    'handovers 🤖)')
SAVED_DIALOG_OPEN = ('📜 Handover saved — a dialog is open, so /clear was not typed for '
                     'you: answer it, then type /clear ✨')
LAST_LIGHT_PREPARED = ('🌅 Last light: a handover is ready 📜 — carry on as normal, or '
                       '/clear to resume from it ✨')


def system_message(text: str) -> str:
    """The hook's whole stdout: one JSON object whose only key is ``systemMessage``.

    ``json.dumps`` does all escaping; the text is cut to ``MAX_LEN`` characters."""
    return json.dumps({"systemMessage": text[:MAX_LEN]})
```

In `hooks.py`, `import messages` (add to the `from context_vigil import …` line) and replace the no-tmux return in `stop`:

```python
    if not tmux.reachable() or target is None:
        return messages.system_message(messages.SAVED_TYPE_CLEAR)
```

- [ ] **Step 4: Run the new test and the hook tests**

Run: `PYTHONPATH=skills/context-vigil/scripts .venv/bin/python -m pytest -q tests/context_vigil_suite/test_messages.py tests/context_vigil_suite/test_hooks.py`
Expected: PASS. If an existing `test_hooks.py` assertion pinned the old wording ("handover saved — type /clear"), update it to `messages.SAVED_TYPE_CLEAR`.

- [ ] **Step 5: Commit**

```bash
git add skills/context-vigil/scripts/context_vigil/messages.py skills/context-vigil/scripts/context_vigil/hooks.py tests/context_vigil_suite/test_messages.py tests/context_vigil_suite/test_hooks.py
git commit -m "feat(context-vigil): user-facing strings and one systemMessage emitter"
```

---

### Task 2: Last-light config keys (global only)

**Files:**
- Modify: `skills/context-vigil/scripts/context_vigil/config.py`
- Test: `tests/context_vigil_suite/test_config.py` (append)

**Interfaces:**
- Produces: `config.GLOBAL_ONLY: frozenset[str]`, `config.last_light_enabled(cwd) -> bool`, `config.last_light_threshold(cwd) -> int`, `config.last_light_lead_seconds(cwd) -> int`. `config.set_value(cwd, key, raw, worktree=True)` raises `ConfigError` for a `GLOBAL_ONLY` key.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/context_vigil_suite/test_config.py
from context_vigil import config as cfgmod


def test_last_light_defaults(repo) -> None:
    assert cfgmod.last_light_enabled(repo) is False
    assert cfgmod.last_light_threshold(repo) == 25
    assert cfgmod.last_light_lead_seconds(repo) == 300


@pytest.mark.parametrize("raw,expected", [("on", True), ("true", True), ("1", True),
                                          ("yes", True), ("off", False), ("false", False),
                                          ("0", False), ("no", False)])
def test_last_light_enabled_coerces_words(repo, raw: str, expected: bool) -> None:
    cfgmod.set_value(repo, "last_light.enabled", raw)
    assert cfgmod.last_light_enabled(repo) is expected


def test_last_light_keys_are_global_only(repo) -> None:
    with pytest.raises(cfgmod.ConfigError, match="global"):
        cfgmod.set_value(repo, "last_light.enabled", "on", worktree=True)


def test_worktree_layer_is_ignored_for_global_only_keys(repo) -> None:
    import json
    from context_vigil import paths
    path = paths.worktree_config_path(repo)
    paths.ensure_dir(path.parent)
    paths.write_private(path, json.dumps({"last_light.threshold": 60}))
    assert cfgmod.last_light_threshold(repo) == 25


@pytest.mark.parametrize("key,bad", [("last_light.threshold", "0"),
                                     ("last_light.threshold", "96"),
                                     ("last_light.lead_seconds", "0"),
                                     ("last_light.lead_seconds", "3601"),
                                     ("last_light.enabled", "maybe")])
def test_last_light_ranges(repo, key: str, bad: str) -> None:
    with pytest.raises(cfgmod.ConfigError):
        cfgmod.set_value(repo, key, bad)


def test_env_overrides_last_light(repo, monkeypatch) -> None:
    monkeypatch.setenv("CONTEXT_VIGIL_LAST_LIGHT", "on")
    monkeypatch.setenv("CONTEXT_VIGIL_LAST_LIGHT_LEAD_SECONDS", "3595")
    assert cfgmod.last_light_enabled(repo) is True
    assert cfgmod.last_light_lead_seconds(repo) == 3595
```

(`test_config.py` already imports `pytest`; if it does not, add `import pytest`.)

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=skills/context-vigil/scripts .venv/bin/python -m pytest -q tests/context_vigil_suite/test_config.py -k last_light`
Expected: FAIL — `AttributeError: module 'context_vigil.config' has no attribute 'last_light_enabled'`

- [ ] **Step 3: Implement**

In `config.py`, extend `DEFAULTS` and `ENV_VARS`:

```python
    "last_light.enabled": False,
    "last_light.threshold": 25,
    "last_light.lead_seconds": 300,
```
```python
    "last_light.enabled": "CONTEXT_VIGIL_LAST_LIGHT",
    "last_light.threshold": "CONTEXT_VIGIL_LAST_LIGHT_THRESHOLD",
    "last_light.lead_seconds": "CONTEXT_VIGIL_LAST_LIGHT_LEAD_SECONDS",
```

Below `_MODES`:

```python
GLOBAL_ONLY = frozenset({"last_light.enabled", "last_light.threshold",
                         "last_light.lead_seconds"})
_TRUE = ("true", "on", "yes", "1")
_FALSE = ("false", "off", "no", "0")
```

In `coerce`, before the `int(...)` conversion:

```python
    if key == "last_light.enabled":
        if isinstance(raw, bool):
            return raw
        word = str(raw).strip().lower()
        if word in _TRUE:
            return True
        if word in _FALSE:
            return False
        raise ConfigError("last_light.enabled must be on or off")
```

and after the existing range checks:

```python
    if key == "last_light.threshold" and not 1 <= number <= 95:
        raise ConfigError("last_light.threshold must be a whole number 1–95")
    if key == "last_light.lead_seconds" and not 1 <= number <= 3600:
        raise ConfigError("last_light.lead_seconds must be a whole number 1–3600")
```

In `resolve`, skip the worktree layer for global-only keys — replace the inner `for layer, data in layers:` loop with:

```python
            for layer, data in layers:
                if layer == "worktree" and key in GLOBAL_ONLY:
                    continue
                if key in data:
                    ok, value = _valid(key, data[key])
                    if ok:
                        chosen = (value, layer)
                        break
```

In `set_value`, first line:

```python
    if worktree and key in GLOBAL_ONLY:
        raise ConfigError(f"{key} is global only — set it without --worktree")
```

Accessors at the end:

```python
def last_light_enabled(cwd: Path) -> bool:
    return load(cwd)["last_light.enabled"] is True


def last_light_threshold(cwd: Path) -> int:
    return int(str(load(cwd)["last_light.threshold"]))


def last_light_lead_seconds(cwd: Path) -> int:
    return int(str(load(cwd)["last_light.lead_seconds"]))
```

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=skills/context-vigil/scripts .venv/bin/python -m pytest -q tests/context_vigil_suite/test_config.py tests/context_vigil_suite/test_cli.py`
Expected: PASS (if a `status`/`config` test enumerates `config.KEYS` exactly, extend its expectation with the three new keys).

- [ ] **Step 5: Commit**

```bash
git add skills/context-vigil/scripts/context_vigil/config.py tests/context_vigil_suite/test_config.py tests/context_vigil_suite/test_cli.py
git commit -m "feat(context-vigil): global-only last_light config keys"
```

---

### Task 3: Is this pane safe to type into?

**Files:**
- Create: `skills/context-vigil/scripts/context_vigil/pane.py`
- Modify: `skills/context-vigil/scripts/context_vigil/tmux.py` (add `capture`)
- Test: `tests/context_vigil_suite/test_pane.py`

**Interfaces:**
- Produces: `tmux.capture(target: str) -> Optional[str]` (visible screen with escapes, `None` on failure); `pane.typed_text(row: str) -> str`; `pane.input_row(screen: str) -> Optional[str]`; `pane.safe_to_type(screen: str) -> bool`; `pane.pane_safe(target: str) -> bool`.

The screens below are real captures from Claude Code 2.1.289 (`capture-pane -p -e`, 2026-10-04): the idle placeholder is `\x1b[2m` (dim) after `❯` + NBSP; typed text has no dim; the trust menu's cursor row is `❯ No, exit` (no number) under a footer `Enter to confirm`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/context_vigil_suite/test_pane.py
"""pane.safe_to_type against real capture shapes (Claude Code 2.1.289)."""
from __future__ import annotations

from pathlib import Path

import pytest
from context_vigil import pane

RULE = "\x1b[38;5;244m" + "─" * 60 + "\x1b[39m"
IDLE_ROW = '\x1b[39m❯\xa0\x1b[2mTry "how do I log an error?"\x1b[0m'
EMPTY_ROW = "\x1b[39m❯\xa0"
TYPED_ROW = "\x1b[39m❯\xa0hello typed"
STATUS = "  🧠 22% │ 🌿 master"


def screen(*rows: str) -> str:
    return "\n".join(rows) + "\n"


IDLE = screen("⏺ done.", "", RULE, IDLE_ROW, RULE, STATUS)
IDLE_EMPTY = screen(RULE, EMPTY_ROW, RULE, STATUS)
TYPED = screen(RULE, TYPED_ROW, RULE, STATUS)
TRUST = screen(" Quick safety check: Is this a project you created or one you trust?",
               " \x1b[38;5;153m❯\x1b[39m \x1b[38;5;153mNo, exit\x1b[39m",
               "   Yes, I trust this folder", "", " Enter to confirm · Esc to cancel")
PERMISSION = screen(" Do you want to proceed?", " ❯ 1. Yes", "   2. No",
                    " Esc to cancel · Tab to amend")
REMOTE_MENU = screen("   Remote Control", "   ❯ Continue", "   Enter to select · Esc to continue")
TRANSCRIPT_PROMPT_ONLY = screen("❯ Use the Bash tool to run exactly: sleep 30",
                                "  Ran 2 shell commands")


@pytest.mark.parametrize("text,safe", [
    (IDLE, True), (IDLE_EMPTY, True),
    (TYPED, False), (TRUST, False), (PERMISSION, False), (REMOTE_MENU, False),
    (TRANSCRIPT_PROMPT_ONLY, False), ("", False),
])
def test_safe_to_type(text: str, safe: bool) -> None:
    assert pane.safe_to_type(text) is safe


def test_typed_text_ignores_dim_placeholder() -> None:
    assert pane.typed_text(IDLE_ROW) == ""
    assert pane.typed_text(TYPED_ROW) == "hello typed"


def test_dim_reset_by_22_counts_as_typed() -> None:
    row = "❯\xa0\x1b[2mTry\x1b[22m x"
    assert pane.typed_text(row) == "x"


def test_pane_safe_uses_tmux_capture(iso: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shot = iso / "shot.txt"
    shot.write_text(IDLE)
    stub = iso / "tmux"
    stub.write_text(f'#!/usr/bin/env bash\n[ "$1" = capture-pane ] && cat "{shot}"\nexit 0\n')
    stub.chmod(0o755)
    monkeypatch.setenv("CONTEXT_VIGIL_TMUX_BIN", str(stub))
    assert pane.pane_safe("%7") is True
    shot.write_text(TRUST)
    assert pane.pane_safe("%7") is False


def test_pane_safe_false_when_capture_fails(iso: Path) -> None:
    assert pane.pane_safe("%7") is False   # iso points the tmux binary at nothing
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=skills/context-vigil/scripts .venv/bin/python -m pytest -q tests/context_vigil_suite/test_pane.py`
Expected: FAIL — `ImportError: cannot import name 'pane'`

- [ ] **Step 3: Implement**

Append to `tmux.py`:

```python
def capture(target: str) -> Optional[str]:
    """The pane's visible screen with SGR escapes (``capture-pane -p -e``), or None."""
    try:
        result = subprocess.run(
            [binary(), "capture-pane", "-p", "-e", "-t", target], timeout=5,
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
        )
    except Exception:
        return None
    return result.stdout if result.returncode == 0 else None
```

Create `pane.py`:

```python
"""Is a Claude Code pane safe to type into? Read from a ``capture-pane -p -e`` screen.

Safe means: the prompt box is on screen (a ``❯`` row directly under a full-width
rule), it holds nothing the person typed (the idle placeholder is drawn dim, SGR 2,
and does not count), and no menu/dialog footer is showing. Anything we cannot read
is unsafe: typing into a dialog can answer a permission prompt or a trust prompt.
"""
from __future__ import annotations

import re
from typing import List, Optional

from context_vigil import tmux

_SGR = re.compile(r"\x1b\[([0-9;]*)m")
_OTHER_ESC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
_RULE = re.compile(r"^\s*─{10,}\s*$")
_FOOTER = re.compile(r"(?i)enter to (select|confirm)|esc to (cancel|continue)")
_BLANKS = " \t\xa0"


def plain(text: str) -> str:
    return _SGR.sub("", _OTHER_ESC.sub("", text))


def typed_text(row: str) -> str:
    """The characters after the first ``❯`` that are NOT drawn dim, stripped."""
    _, _, rest = row.partition("❯")
    rest = _OTHER_ESC.sub("", rest)
    out: List[str] = []
    dim = False
    pos = 0
    for match in _SGR.finditer(rest):
        if not dim:
            out.append(rest[pos:match.start()])
        params = [p for p in match.group(1).split(";") if p] or ["0"]
        for p in params:
            if p == "2":
                dim = True
            elif p in ("0", "22"):
                dim = False
        pos = match.end()
    if not dim:
        out.append(rest[pos:])
    return "".join(out).strip(_BLANKS)


def input_row(screen: str) -> Optional[str]:
    """The prompt box's ``❯`` row (raw, escapes kept): the last ``❯`` row whose
    line above is a full-width rule. None when no prompt box is on screen."""
    raw = screen.splitlines()
    found: Optional[str] = None
    for i in range(1, len(raw)):
        if plain(raw[i]).lstrip(_BLANKS).startswith("❯") and _RULE.match(plain(raw[i - 1])):
            found = raw[i]
    return found


def safe_to_type(screen: str) -> bool:
    row = input_row(screen)
    if row is None:
        return False
    if _FOOTER.search(plain(screen)):
        return False
    return typed_text(row) == ""


def pane_safe(target: str) -> bool:
    screen = tmux.capture(target)
    return screen is not None and safe_to_type(screen)
```

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=skills/context-vigil/scripts .venv/bin/python -m pytest -q tests/context_vigil_suite/test_pane.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/context-vigil/scripts/context_vigil/pane.py skills/context-vigil/scripts/context_vigil/tmux.py tests/context_vigil_suite/test_pane.py
git commit -m "feat(context-vigil): tell a typeable prompt box from a dialog"
```

---

### Task 4: Safety net — never type `/clear` or the kick into a dialog

**Files:**
- Modify: `skills/context-vigil/scripts/context_vigil/hooks.py` (`stop`, `session_start`)
- Test: `tests/context_vigil_suite/test_hooks.py` (append)

**Interfaces:**
- Consumes: `pane.pane_safe(target)`, `messages.SAVED_DIALOG_OPEN`, `messages.system_message`.
- Produces: `hooks.stop` returns `system_message(SAVED_DIALOG_OPEN)` and keeps the clear flag when the pane is unsafe; `session_start` skips the kick when unsafe.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/context_vigil_suite/test_hooks.py
from context_vigil import messages


@pytest.fixture
def screen_tmux(iso: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """A tmux stub: logs argv; `capture-pane` prints the file `shot`."""
    log, shot = iso / "tmux.log", iso / "shot.txt"
    stub = iso / "tmux"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'if [ "$1" = capture-pane ]; then cat "{shot}"; exit 0; fi\n'
        f'echo "$@" >> "{log}"\nexit 0\n')
    stub.chmod(0o755)
    monkeypatch.setenv("CONTEXT_VIGIL_TMUX_BIN", str(stub))
    monkeypatch.setenv("TMUX", "/tmp/fake,1,0")
    monkeypatch.setenv("TMUX_PANE", "%7")
    monkeypatch.setenv("CONTEXT_VIGIL_CLEAR_DELAY", "0")
    monkeypatch.setenv("CONTEXT_VIGIL_KICK_DELAY", "0")
    return log, shot


IDLE_SCREEN = "─" * 40 + "\n❯\xa0\x1b[2mTry it\x1b[0m\n" + "─" * 40 + "\n"
DIALOG_SCREEN = " Do you want to proceed?\n ❯ 1. Yes\n   2. No\n Esc to cancel\n"


def _arm_clear(repo: Path) -> Path:
    scope = paths.scope_dir(repo)
    state.request_clear(scope, "# handover\n")
    return scope


def test_stop_refuses_to_type_clear_into_a_dialog(repo: Path, screen_tmux) -> None:
    log, shot = screen_tmux
    shot.write_text(DIALOG_SCREEN)
    scope = _arm_clear(repo)
    out = hooks.stop(_payload(repo))
    assert json.loads(out) == {"systemMessage": messages.SAVED_DIALOG_OPEN}
    assert state.clear_flag(scope).exists()          # still armed for the manual /clear
    assert not log.exists() or "/clear" not in log.read_text()


def test_stop_types_clear_into_an_idle_box(repo: Path, screen_tmux) -> None:
    log, shot = screen_tmux
    shot.write_text(IDLE_SCREEN)
    _arm_clear(repo)
    assert hooks.stop(_payload(repo)) is None
    assert "/clear" in _wait_for(log, "/clear")


def test_kick_skipped_when_a_dialog_is_open(repo: Path, screen_tmux) -> None:
    log, shot = screen_tmux
    shot.write_text(DIALOG_SCREEN)
    scope = paths.scope_dir(repo)
    state.write_handoff(scope, "# handover\n## Next Step\ngo\n")
    out = hooks.session_start(_payload(repo, source="clear"))
    assert out is not None and "additionalContext" in out   # handover still injected
    time.sleep(0.3)
    assert not log.exists() or "resume from the injected handover" not in log.read_text()
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=skills/context-vigil/scripts .venv/bin/python -m pytest -q tests/context_vigil_suite/test_hooks.py -k "dialog or idle_box"`
Expected: FAIL — `/clear` typed into the dialog / kick sent.

- [ ] **Step 3: Implement**

`hooks.py` — import `messages, pane`. In `stop`, replace the tail from `target = tmux.pane()`:

```python
    target = tmux.pane()
    if not tmux.reachable() or target is None:
        return messages.system_message(messages.SAVED_TYPE_CLEAR)
    if not pane.pane_safe(target):
        # a dialog (or the person's own typing) holds the box: typing /clear + Enter
        # would answer it. Leave the flag armed; the manual /clear still loads it.
        return messages.system_message(messages.SAVED_DIALOG_OPEN)
    if state.consume_clear_flag(scope):
        delay = os.environ.get("CONTEXT_VIGIL_CLEAR_DELAY", "2")
        tmux.send_detached(target, [["/clear", "Enter"]], delay)
    return None
```

In `session_start`, change the kick guard:

```python
            if target is not None and tmux.reachable() and pane.pane_safe(target):
```

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=skills/context-vigil/scripts .venv/bin/python -m pytest -q tests/context_vigil_suite/test_hooks.py`
Expected: PASS. Existing tests that used the `fake_tmux` fixture (which never prints a screen) and expect `/clear` or the kick to be sent will now fail because the capture is empty → unsafe. Fix them by making `fake_tmux` print `IDLE_SCREEN` for `capture-pane` (edit the fixture's stub body to the `screen_tmux` form with an idle default), not by weakening `pane_safe`.

- [ ] **Step 5: Commit**

```bash
git add skills/context-vigil/scripts/context_vigil/hooks.py tests/context_vigil_suite/test_hooks.py
git commit -m "feat(context-vigil): never type /clear or the kick into an open dialog"
```

---

### Task 5: Prepared handovers

**Files:**
- Modify: `skills/context-vigil/scripts/context_vigil/state.py`, `skills/context-vigil/scripts/context_vigil/cli.py` (`build_parser`, `_cmd_handover`)
- Test: `tests/context_vigil_suite/test_state.py`, `tests/context_vigil_suite/test_cli.py` (append)

**Interfaces:**
- Produces: `state.prepared_marker(scope) -> Path`, `state.is_prepared(scope) -> bool`, `state.write_prepared(scope, text, keep) -> None`, `state.discard_prepared(scope, keep) -> bool`; `_archive(scope, path, keep, name="handoff.md")`; `consume_handoff` and `write_handoff` remove the marker. CLI: `handover --file F --prepared` prints `messages.LAST_LIGHT_PREPARED`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/context_vigil_suite/test_state.py
def test_write_prepared_sets_marker_without_clear_flag(tmp_path) -> None:
    scope = tmp_path / "scope"
    state.write_prepared(scope, "# prepared\n", 20)
    assert state.is_prepared(scope)
    assert not state.clear_flag(scope).exists()
    assert state.read_handoff(scope) == "# prepared\n"


def test_discard_prepared_archives_with_discarded_name(tmp_path) -> None:
    scope = tmp_path / "scope"
    state.write_prepared(scope, "# prepared\n", 20)
    assert state.discard_prepared(scope, 20) is True
    assert not state.handoff_path(scope).exists()
    assert not state.prepared_marker(scope).exists()
    names = [p.name for p in state.handoff_archive_dir(scope).iterdir()]
    assert names == ["handoff.discarded.md"]


def test_discard_prepared_leaves_a_real_handover_alone(tmp_path) -> None:
    scope = tmp_path / "scope"
    state.request_clear(scope, "# real\n")
    assert state.discard_prepared(scope, 20) is False
    assert state.read_handoff(scope) == "# real\n"


def test_consume_and_real_write_drop_the_marker(tmp_path) -> None:
    scope = tmp_path / "scope"
    state.write_prepared(scope, "# prepared\n", 20)
    assert state.consume_handoff(scope) == "# prepared\n"
    assert not state.prepared_marker(scope).exists()
    state.write_prepared(scope, "# prepared again\n", 20)
    state.request_clear(scope, "# real\n")
    assert not state.is_prepared(scope)
```

```python
# append to tests/context_vigil_suite/test_cli.py
def test_handover_prepared_saves_without_arming_clear(run_cli, repo) -> None:
    from context_vigil import messages, paths, state
    notes = run_cli("notes-path", cwd=repo).stdout.strip()
    Path(notes).write_text(
        "## Goal\ng\n## Current State\ns\n## Failed Attempts\nNone\n## Next Step\nn\n")
    r = run_cli("handover", "--file", notes, "--prepared", "--no-snapshot", cwd=repo)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == messages.LAST_LIGHT_PREPARED
    scope = paths.scope_dir(repo)
    assert state.is_prepared(scope) and not state.clear_flag(scope).exists()


def test_handover_prepared_refused_over_a_real_pending_one(run_cli, repo) -> None:
    from context_vigil import paths, state
    state.request_clear(paths.scope_dir(repo), "# real\n")
    notes = run_cli("notes-path", cwd=repo).stdout.strip()
    Path(notes).write_text(
        "## Goal\ng\n## Current State\ns\n## Failed Attempts\nNone\n## Next Step\nn\n")
    r = run_cli("handover", "--file", notes, "--prepared", "--no-snapshot", cwd=repo)
    assert r.returncode == 1 and "already pending" in r.stderr
```

(Check `templates/handover.md` for the exact required headings; mirror them in the notes text if they differ.)

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=skills/context-vigil/scripts .venv/bin/python -m pytest -q tests/context_vigil_suite/test_state.py tests/context_vigil_suite/test_cli.py -k prepared`
Expected: FAIL — `AttributeError: ... 'write_prepared'` / `unrecognized arguments: --prepared`.

- [ ] **Step 3: Implement**

`state.py`:

```python
def prepared_marker(scope: Path) -> Path:
    """Beside handoff.md: this handoff was prepared by last light, not requested."""
    return scope / "handoff-prepared"


def is_prepared(scope: Path) -> bool:
    return prepared_marker(scope).exists() and handoff_path(scope).exists()
```

Give `_archive` a name parameter and use it:

```python
def _archive(scope: Path, path: Path, keep: int, name: str = "handoff.md") -> None:
    ...
    target = _uniquify(archive / name)
```

`write_handoff` — first line after `paths.ensure_dir(scope)`:

```python
    prepared_marker(scope).unlink(missing_ok=True)   # a new handoff is never "prepared" by default
```

New functions:

```python
def write_prepared(scope: Path, handoff_text: str, keep: int = ARCHIVE_KEEP) -> None:
    """Save a last-light handoff: no clear flag, so nothing is cleared; /clear loads it."""
    write_handoff(scope, handoff_text, keep)
    _touch(prepared_marker(scope))


def discard_prepared(scope: Path, keep: int = ARCHIVE_KEEP) -> bool:
    """Archive a prepared handoff as ``handoff.discarded.md``. A real (requested)
    handoff is never touched. Returns whether one was discarded; never raises."""
    if not is_prepared(scope):
        prepared_marker(scope).unlink(missing_ok=True)   # a stray marker
        return False
    try:
        _archive(scope, handoff_path(scope), keep, name="handoff.discarded.md")
    except OSError:
        handoff_path(scope).unlink(missing_ok=True)
    prepared_marker(scope).unlink(missing_ok=True)
    return True
```

`consume_handoff` — just before `return text`:

```python
    prepared_marker(scope).unlink(missing_ok=True)
```

`cli.py` — in `build_parser` after `--no-snapshot`:

```python
    hp.add_argument("--prepared", action="store_true",
                    help="last light: save without arming /clear (carry on, or /clear to resume)")
```

In `_cmd_handover`, import `messages`, and right after the `handover.assemble(...)` try/except:

```python
    if args.prepared:
        if session.is_headless(_env_session_id()):
            raise CliError("--prepared is for interactive sessions")
        if state.is_paused(scope):
            raise CliError("handover refused: paused here (`context-vigil resume` to re-enable)")
        if state.handoff_path(scope).exists() and not state.is_prepared(scope):
            raise CliError("a handover is already pending — --prepared will not replace it")
        state.write_prepared(scope, document, config.archive_keep(cwd))
        _tidy_notes(notes_file, [scope, kept])
        print(messages.LAST_LIGHT_PREPARED)
        return 0
```

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=skills/context-vigil/scripts .venv/bin/python -m pytest -q tests/context_vigil_suite/test_state.py tests/context_vigil_suite/test_cli.py tests/context_vigil_suite/test_hooks.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/context-vigil/scripts/context_vigil/state.py skills/context-vigil/scripts/context_vigil/cli.py tests/context_vigil_suite/test_state.py tests/context_vigil_suite/test_cli.py
git commit -m "feat(context-vigil): prepared handovers (saved, not cleared)"
```

---

### Task 6: Prompt classification — arm on human prompts, discard stale prepared handovers

**Files:**
- Modify: `skills/context-vigil/scripts/context_vigil/session.py` (`_DEFAULTS`, docstring), `skills/context-vigil/scripts/context_vigil/hooks.py` (`nudge`)
- Create: `skills/context-vigil/scripts/context_vigil/last_light.py` (only `MARKER` in this task)
- Test: `tests/context_vigil_suite/test_last_light.py` (new; grows in Task 7)

**Interfaces:**
- Produces: `last_light.MARKER = "[context-vigil:last-light]"`; `hooks.classify_prompt(payload) -> str` ∈ {`"ours"`, `"background"`, `"human"`}; session record keys `last_light_armed: bool` (default `False`) and `last_noticed_pct: Optional[int]` (default `None`, used in Task 8).
- Behaviour: on `UserPromptSubmit`, `human` → arm + `state.discard_prepared(scope)`; `ours` → no nudge at all (return `None`); `background` → nudge uses `NUDGE_UNATTENDED`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/context_vigil_suite/test_last_light.py
"""Last light: prompt classification, the tick's gates, and the loop locks."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from context_vigil import hooks, last_light, paths, session, state


def _prompt(repo: Path, text: str, sid: str = "s1") -> dict:
    return {"cwd": str(repo), "session_id": sid, "hook_event_name": "UserPromptSubmit",
            "prompt": text}


@pytest.mark.parametrize("text,kind", [
    ("fix the bug", "human"),
    (last_light.MARKER + " The prompt cache expires…", "ours"),
    (hooks.KICK_PROMPT, "ours"),
    ("<task-notification>\n<task-id>b1</task-id>", "background"),
    ("", "human"),
])
def test_classify_prompt(repo: Path, text: str, kind: str) -> None:
    assert hooks.classify_prompt(_prompt(repo, text)) == kind


def test_human_prompt_arms_and_discards_prepared(repo: Path) -> None:
    scope = paths.scope_dir(repo)
    state.write_prepared(scope, "# prepared\n", 20)
    hooks.nudge(_prompt(repo, "carry on"))
    assert session.load("s1")["last_light_armed"] is True
    assert not state.is_prepared(scope)


def test_our_prompt_neither_arms_nor_nudges(repo: Path) -> None:
    out = hooks.nudge(_prompt(repo, last_light.MARKER + " prepare"))
    assert out is None
    assert session.load("s1")["last_light_armed"] is False


def test_background_prompt_neither_discards_nor_arms(repo: Path) -> None:
    scope = paths.scope_dir(repo)
    state.write_prepared(scope, "# prepared\n", 20)
    hooks.nudge(_prompt(repo, "<task-notification>\n<status>completed</status>"))
    assert state.is_prepared(scope)
    assert session.load("s1")["last_light_armed"] is False


def test_post_tool_use_never_arms(repo: Path) -> None:
    hooks.nudge({"cwd": str(repo), "session_id": "s1", "hook_event_name": "PostToolUse"})
    assert session.load("s1")["last_light_armed"] is False
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=skills/context-vigil/scripts .venv/bin/python -m pytest -q tests/context_vigil_suite/test_last_light.py`
Expected: FAIL — `ImportError: cannot import name 'last_light'`

- [ ] **Step 3: Implement**

Create `last_light.py` (it grows in Task 7):

```python
"""Last light: before an idle session's 1-hour prompt cache goes cold, ask the agent
to *prepare* a handover. Nothing is cleared. Spec §1."""
from __future__ import annotations

MARKER = "[context-vigil:last-light]"
```

`session.py` — add to `_DEFAULTS` and document both in the module docstring list:

```python
    "last_light_armed": False,
    "last_noticed_pct": None,
```
```
- ``last_light_armed``: a human prompt arrived since last light last fired (lock 1);
- ``last_noticed_pct``: the ctx % of the most recent end-of-turn notice this cycle.
```

`hooks.py` — import `last_light`; add:

```python
_BACKGROUND_PREFIX = "<task-notification>"


def classify_prompt(payload: Dict[str, object]) -> str:
    """``ours`` (last light's prompt, or our resume kick), ``background`` (a finished
    background task starting a turn), else ``human``."""
    text = payload.get("prompt")
    text = text.lstrip() if isinstance(text, str) else ""
    if text.startswith(last_light.MARKER) or text.startswith(KICK_PROMPT):
        return "ours"
    if text.startswith(_BACKGROUND_PREFIX):
        return "background"
    return "human"


def _on_human_prompt(cwd: Path, session_id: Optional[str], scope: Path) -> None:
    """Lock 1 arms; a prepared handover is stale once the person carries on."""
    if session_id:
        with session.locked(session_id) as got:
            if got:
                record = session.load(session_id)
                record["last_light_armed"] = True
                session.save(session_id, record)
    state.discard_prepared(scope, config.archive_keep(cwd))
```

At the top of `nudge`, after `scope = session.scope(...)` and before `if quiet(scope)`:

```python
    event = _str(payload, "hook_event_name")
    kind = classify_prompt(payload) if event == "UserPromptSubmit" else None
    if kind == "ours":
        return None
    if kind == "human":
        _on_human_prompt(cwd, session_id, scope)
```

and replace the template choice near the end (remove the later duplicate `event = …` line):

```python
    template = (NUDGE_ATTENDED if event == "UserPromptSubmit" and kind == "human"
                else NUDGE_UNATTENDED)
```

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=skills/context-vigil/scripts .venv/bin/python -m pytest -q tests/context_vigil_suite/test_last_light.py tests/context_vigil_suite/test_hooks.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/context-vigil/scripts/context_vigil/last_light.py skills/context-vigil/scripts/context_vigil/session.py skills/context-vigil/scripts/context_vigil/hooks.py tests/context_vigil_suite/test_last_light.py
git commit -m "feat(context-vigil): classify prompts; human prompts arm last light and drop stale prepared handovers"
```

---

### Task 7: The last-light tick, wired to status-line ingest

**Files:**
- Modify: `skills/context-vigil/scripts/context_vigil/last_light.py`, `skills/context-vigil/scripts/context_vigil/cli.py` (`_cmd_ingest`)
- Test: `tests/context_vigil_suite/test_last_light.py` (append)

**Interfaces:**
- Consumes: `config.last_light_*`, `session.load/save/locked/scope`, `state.is_prepared/handoff_path/clear_requested/is_paused`, `tmux.pane/reachable/send_detached`, `pane.pane_safe`, `census.worktree_cwd(payload) -> Path`.
- Produces: `last_light.PROMPT` (format keys `minutes`, `launcher`); `last_light.tick(payload: dict, now: Optional[float] = None) -> str` returning one of `off, no-cache, not-near, below, no-session, disarmed, prepared, pending, paused, no-tmux, unsafe, locked, fired`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/context_vigil_suite/test_last_light.py
import threading
import time as _time

NOW = 1_800_000_000.0
IDLE_SCREEN = "─" * 40 + "\n❯\xa0\x1b[2mTry it\x1b[0m\n" + "─" * 40 + "\n"


@pytest.fixture
def lit(repo: Path, iso: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Last light on, inside a stub tmux whose pane is an idle prompt box; returns the
    keystroke log."""
    monkeypatch.setenv("CONTEXT_VIGIL_LAST_LIGHT", "on")
    log, shot = iso / "tmux.log", iso / "shot.txt"
    shot.write_text(IDLE_SCREEN)
    stub = iso / "tmux"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'if [ "$1" = capture-pane ]; then cat "{shot}"; exit 0; fi\n'
        f'echo "$@" >> "{log}"\nexit 0\n')
    stub.chmod(0o755)
    monkeypatch.setenv("CONTEXT_VIGIL_TMUX_BIN", str(stub))
    monkeypatch.setenv("TMUX", "/tmp/fake,1,0")
    monkeypatch.setenv("TMUX_PANE", "%7")
    return log


def _arm(sid: str = "s1") -> None:
    record = session.load(sid)
    record["last_light_armed"] = True
    session.save(sid, record)


def _tick_payload(repo: Path, pct: float = 40, left: float = 200, ttl: str = "1h",
                  warm: bool = True, sid: str = "s1") -> dict:
    return {"session_id": sid, "cwd": str(repo),
            "workspace": {"current_dir": str(repo)},
            "context_window": {"used_percentage": pct},
            "prompt_cache": {"warm": warm, "ttl": ttl, "expires_at": NOW + left}}


def _typed(log: Path) -> str:
    for _ in range(50):
        if log.exists() and last_light.MARKER in log.read_text():
            return log.read_text()
        _time.sleep(0.05)
    return log.read_text() if log.exists() else ""


def test_fires_once_when_every_gate_holds(repo: Path, lit: Path) -> None:
    _arm()
    assert last_light.tick(_tick_payload(repo), now=NOW) == "fired"
    assert last_light.MARKER in _typed(lit)
    assert session.load("s1")["last_light_armed"] is False


@pytest.mark.parametrize("kwargs,reason", [
    ({"ttl": "5m"}, "no-cache"), ({"warm": False}, "no-cache"),
    ({"left": 301}, "not-near"), ({"left": 0}, "not-near"), ({"left": -5}, "not-near"),
    ({"pct": 24}, "below"),
])
def test_gates(repo: Path, lit: Path, kwargs: dict, reason: str) -> None:
    _arm()
    assert last_light.tick(_tick_payload(repo, **kwargs), now=NOW) == reason


def test_off_by_default(repo: Path, lit: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONTEXT_VIGIL_LAST_LIGHT")
    _arm()
    assert last_light.tick(_tick_payload(repo), now=NOW) == "off"


@pytest.mark.parametrize("cache", [None, "nope", {"ttl": "1h", "warm": True},
                                   {"ttl": "1h", "warm": True, "expires_at": "soon"}])
def test_odd_prompt_cache_does_nothing(repo: Path, lit: Path, cache: object) -> None:
    _arm()
    payload = _tick_payload(repo)
    payload["prompt_cache"] = cache
    assert last_light.tick(payload, now=NOW) == "no-cache"


def test_disarmed_until_a_human_prompt(repo: Path, lit: Path) -> None:
    assert last_light.tick(_tick_payload(repo), now=NOW) == "disarmed"


def test_pending_paused_and_unsafe(repo: Path, lit: Path, iso: Path) -> None:
    scope = paths.scope_dir(repo)
    _arm()
    state.pause(scope)
    assert last_light.tick(_tick_payload(repo), now=NOW) == "paused"
    state.resume(scope)
    state.request_clear(scope, "# real\n")
    assert last_light.tick(_tick_payload(repo), now=NOW) == "pending"
    state.consume_handoff(scope)
    state.begin_cycle(scope)
    (iso / "shot.txt").write_text("─" * 40 + "\n❯\xa0half-typed message\n")
    assert last_light.tick(_tick_payload(repo), now=NOW) == "unsafe"


def test_no_tmux(repo: Path, lit: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TMUX")
    _arm()
    assert last_light.tick(_tick_payload(repo), now=NOW) == "no-tmux"


def _loop_cycle(repo: Path) -> dict:
    """After a fire: the agent's marked turn refreshes the cache for another hour."""
    hooks.nudge(_prompt(repo, last_light.MARKER + " prepare"))
    return _tick_payload(repo, left=200)


def test_loop_both_locks(repo: Path, lit: Path) -> None:
    _arm()
    assert last_light.tick(_tick_payload(repo), now=NOW) == "fired"
    state.write_prepared(paths.scope_dir(repo), "# prepared\n", 20)
    later = NOW + 3300
    assert last_light.tick(_loop_cycle(repo), now=later) != "fired"


def test_loop_lock2_alone_holds(repo: Path, lit: Path) -> None:
    """Lock 1 forced open: armed stays true; the prepared handover alone stops it."""
    _arm()
    assert last_light.tick(_tick_payload(repo), now=NOW) == "fired"
    state.write_prepared(paths.scope_dir(repo), "# prepared\n", 20)
    _arm()                                              # lock 1 broken
    assert last_light.tick(_loop_cycle(repo), now=NOW + 3300) == "prepared"


def test_loop_lock1_alone_holds(repo: Path, lit: Path) -> None:
    """Lock 2 forced open: no prepared handover was written; disarm alone stops it."""
    _arm()
    assert last_light.tick(_tick_payload(repo), now=NOW) == "fired"
    assert last_light.tick(_loop_cycle(repo), now=NOW + 3300) == "disarmed"


def test_concurrent_ticks_fire_once(repo: Path, lit: Path) -> None:
    _arm()
    results: list = []
    threads = [threading.Thread(
        target=lambda: results.append(last_light.tick(_tick_payload(repo), now=NOW)))
        for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("fired") == 1


def test_ingest_cli_runs_the_tick(run_cli, repo: Path, lit: Path) -> None:
    _arm()
    payload = _tick_payload(repo, left=200)
    payload["prompt_cache"]["expires_at"] = _time.time() + 200
    env = {"CONTEXT_VIGIL_LAST_LIGHT": "on", "TMUX": "/tmp/fake,1,0", "TMUX_PANE": "%7"}
    assert run_cli("ingest", stdin=json.dumps(payload), cwd=repo, env=env).returncode == 0
    assert last_light.MARKER in _typed(lit)
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=skills/context-vigil/scripts .venv/bin/python -m pytest -q tests/context_vigil_suite/test_last_light.py`
Expected: FAIL — `AttributeError: module 'context_vigil.last_light' has no attribute 'tick'`

- [ ] **Step 3: Implement**

Append to `last_light.py` (and extend its imports):

```python
import time
from pathlib import Path
from typing import Dict, Optional

from context_vigil import census, config, pane, paths, session, state, tmux

PROMPT = (
    MARKER + " The prompt cache expires in about {minutes} minutes and this session is "
    "idle. Prepare a handover: run `\"{launcher}\" notes-path`, fill in the file it "
    "prints, then run `\"{launcher}\" handover --file <the path notes-path printed> "
    "--prepared`. Then reply with exactly the line that command prints and stop. Do not "
    "/clear and do not continue the task."
)


def _expires_at(payload: Dict[str, object]) -> Optional[float]:
    cache = payload.get("prompt_cache")
    if not isinstance(cache, dict):
        return None
    expires = cache.get("expires_at")
    if cache.get("ttl") != "1h" or cache.get("warm") is not True:
        return None
    if isinstance(expires, bool) or not isinstance(expires, (int, float)):
        return None
    return float(expires)


def _pct(payload: Dict[str, object]) -> Optional[float]:
    window = payload.get("context_window")
    value = window.get("used_percentage") if isinstance(window, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _blocked(scope: Path) -> Optional[str]:
    if state.is_prepared(scope):
        return "prepared"                      # lock 2
    if state.handoff_path(scope).exists() or state.clear_requested(scope):
        return "pending"
    if state.is_paused(scope):
        return "paused"
    return None


def tick(payload: Dict[str, object], now: Optional[float] = None) -> str:
    """One status-line tick. Returns why it did or did not fire; never raises."""
    now = time.time() if now is None else now
    where = census.worktree_cwd(payload)        # str | None
    raw_cwd = payload.get("cwd")
    cwd = Path(where) if where else Path(raw_cwd) if isinstance(raw_cwd, str) and raw_cwd \
        else Path.cwd()
    if not config.last_light_enabled(cwd):
        return "off"
    expires = _expires_at(payload)
    if expires is None:
        return "no-cache"
    left = expires - now
    lead = config.last_light_lead_seconds(cwd)
    if not 0 < left <= lead:
        return "not-near"
    pct = _pct(payload)
    if pct is None or pct < config.last_light_threshold(cwd):
        return "below"
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return "no-session"
    if session.load(session_id)["last_light_armed"] is not True:
        return "disarmed"                      # lock 1
    transcript = payload.get("transcript_path")
    scope = session.scope(cwd, session_id, transcript if isinstance(transcript, str) else None)
    blocked = _blocked(scope)
    if blocked:
        return blocked
    target = tmux.pane()
    if target is None or not tmux.reachable():
        return "no-tmux"
    if not pane.pane_safe(target):
        return "unsafe"
    with session.locked(session_id) as got:
        if not got:
            return "locked"
        record = session.load(session_id)
        if record["last_light_armed"] is not True:
            return "disarmed"
        blocked = _blocked(scope)
        if blocked:
            return blocked
        record["last_light_armed"] = False
        session.save(session_id, record)
        text = PROMPT.format(minutes=max(1, int(left // 60)), launcher=paths.launcher_path())
        tmux.send_detached(target, [["-l", text], ["Enter"]], "0")
    return "fired"
```

(`census.worktree_cwd(payload: dict) -> str | None` — hence the fallback chain above.)

`cli.py` — import `last_light`; replace `_cmd_ingest`:

```python
def _cmd_ingest(args: argparse.Namespace) -> int:
    raw = sys.stdin.read()
    census.ingest(raw)
    try:   # the status line must never fail: last light is best-effort
        payload = json.loads(raw)
        if isinstance(payload, dict):
            last_light.tick(payload)
    except Exception:
        pass
    return 0
```

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=skills/context-vigil/scripts .venv/bin/python -m pytest -q tests/context_vigil_suite/test_last_light.py tests/context_vigil_suite/test_census_ingest.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/context-vigil/scripts/context_vigil/last_light.py skills/context-vigil/scripts/context_vigil/cli.py tests/context_vigil_suite/test_last_light.py
git commit -m "feat(context-vigil): last light tick on the status line, with both loop locks"
```

---

### Task 8: End-of-turn notice (Stop) and the lighter next-prompt context

**Files:**
- Modify: `skills/context-vigil/scripts/context_vigil/hooks.py` (`stop`, `nudge`, new `NUDGE_NOTICED`)
- Test: `tests/context_vigil_suite/test_notice.py` (new)

**Interfaces:**
- Consumes: `context.current_reading(cwd, session_id, transcript_path, window)` (returns an object with `.pct` and `.confident`), `config.threshold/repeat_step/window`, `session.locked/load/save`, `messages.*`.
- Produces: `hooks.stop` emits `system_message(NOTICE_FIRST|NOTICE_REPEAT)` when due; record `last_noticed_pct` set; `hooks.NUDGE_NOTICED`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/context_vigil_suite/test_notice.py
"""The end-of-turn notice: user-only, once per step, hostile-input safe."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from context_vigil import hooks, messages, session

from .conftest import LAUNCHER, cli_env
from .test_context_window import _ingest


def _stop(repo: Path, **extra: object) -> dict:
    return {"cwd": str(repo), "session_id": "s1", "hook_event_name": "Stop", **extra}


def _confident(repo: Path, pct: float) -> None:
    _ingest(repo, "s1", pct, size=200000, model="claude-haiku-4-5")


def test_no_notice_below_threshold(repo: Path) -> None:
    _confident(repo, 20)
    assert hooks.stop(_stop(repo)) is None


def test_first_notice_then_silent_until_next_step(repo: Path) -> None:
    _confident(repo, 41)
    out = json.loads(hooks.stop(_stop(repo)))
    assert out == {"systemMessage": messages.NOTICE_FIRST.format(pct=41, threshold=35)}
    assert session.load("s1")["last_noticed_pct"] == 41
    _confident(repo, 44)
    assert hooks.stop(_stop(repo)) is None
    _confident(repo, 46)
    out = json.loads(hooks.stop(_stop(repo)))
    assert out["systemMessage"] == messages.NOTICE_REPEAT.format(pct=46, threshold=35)


def test_silent_when_stop_hook_active(repo: Path) -> None:
    _confident(repo, 60)
    assert hooks.stop(_stop(repo, stop_hook_active=True)) is None


def test_never_blocks(repo: Path) -> None:
    _confident(repo, 60)
    out = json.loads(hooks.stop(_stop(repo)))
    assert set(out) == {"systemMessage"}


@pytest.mark.parametrize("hostile", ['"; rm -rf ~ #', "line\nbreak", "back\\slash",
                                     "nul\x00byte", "🕯️" * 50, "x" * 10_000])
def test_stop_output_is_one_json_object_for_hostile_payloads(repo: Path, hostile: str) -> None:
    _confident(repo, 70)
    payload = _stop(repo, transcript_path=hostile, extra_field=hostile)
    out = hooks.run("stop", json.dumps(payload))
    if out is not None:
        data = json.loads(out)
        assert set(data) == {"systemMessage"}
        assert len(data["systemMessage"]) <= messages.MAX_LEN


def test_launcher_stop_exits_zero_with_empty_stdout_on_garbage(repo: Path) -> None:
    r = subprocess.run(["bash", str(LAUNCHER), "hook", "stop"], input="{not json",
                       capture_output=True, text=True, env=cli_env(), cwd=repo, timeout=30)
    assert r.returncode == 0 and r.stdout == ""


def test_next_prompt_gets_the_noticed_context(repo: Path) -> None:
    _confident(repo, 41)
    hooks.stop(_stop(repo))
    out = hooks.nudge({"cwd": str(repo), "session_id": "s1",
                       "hook_event_name": "UserPromptSubmit", "prompt": "hand over"})
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "already been shown" in context
```

(If `_ingest`'s `model`/`size` arguments do not make the reading confident in this codebase, use whatever `test_hooks.py` already does to reach a nudge — e.g. `_over(repo, pct)` — and keep the assertions.)

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=skills/context-vigil/scripts .venv/bin/python -m pytest -q tests/context_vigil_suite/test_notice.py`
Expected: FAIL — `stop` returns `None` at 41%.

- [ ] **Step 3: Implement**

`hooks.py` — add after `NUDGE_UNATTENDED`:

```python
NUDGE_NOTICED = (
    "**context-vigil: context at {pct}% — over the {threshold}% threshold.** "
    "The user has already been shown this on screen. If their message asks you to "
    "hand over, do it now: " + NOTES_STEP + "\nOtherwise answer their message normally "
    "and do not bring the handover up."
)
```

Add the notice function:

```python
def _notice(payload: Dict[str, object], scope: Path) -> Optional[str]:
    """The end-of-turn notice (spec §2): shown to the user, never to the model; first
    crossing, then every repeat step. One JSON object or nothing."""
    session_id = _str(payload, "session_id")
    if not session_id or state.is_paused(scope):
        return None
    cwd = _cwd(payload)
    reading = context.current_reading(cwd, session_id, _str(payload, "transcript_path"),
                                      config.window(cwd))
    if reading.pct is None or not reading.confident:
        return None
    pct, threshold, step = int(reading.pct), config.threshold(cwd), config.repeat_step(cwd)
    if pct < threshold:
        return None
    with session.locked(session_id) as got:
        if not got:
            return None
        record = session.load(session_id)
        last = record["last_noticed_pct"]
        if isinstance(last, int) and pct < last + step:
            return None
        record["last_noticed_pct"] = pct
        session.save(session_id, record)
    template = messages.NOTICE_FIRST if not isinstance(last, int) else messages.NOTICE_REPEAT
    return messages.system_message(template.format(pct=pct, threshold=threshold))
```

Rewrite `stop`:

```python
def stop(payload: Dict[str, object]) -> Optional[str]:
    if payload.get("stop_hook_active") is True:
        return None
    session_id = _str(payload, "session_id")
    transcript_path = _str(payload, "transcript_path")
    if session.is_headless(session_id, transcript_path):
        return None   # a headless session never types into a pane, inherited or not
    scope = session.scope(_cwd(payload), session_id, transcript_path)
    if state.drop_orphan_clear(scope):
        return None   # its handover was resumed or discarded elsewhere: nothing to /clear for
    if not state.clear_requested(scope):
        return _notice(payload, scope)
    target = tmux.pane()
    if not tmux.reachable() or target is None:
        return messages.system_message(messages.SAVED_TYPE_CLEAR)
    if not pane.pane_safe(target):
        return messages.system_message(messages.SAVED_DIALOG_OPEN)
    if state.consume_clear_flag(scope):
        delay = os.environ.get("CONTEXT_VIGIL_CLEAR_DELAY", "2")
        tmux.send_detached(target, [["/clear", "Enter"]], delay)
    return None
```

In `nudge`, choose the template (replacing Task 6's line):

```python
    noticed = (session_id is not None and record is not None
               and isinstance(record.get("last_noticed_pct"), int))
    if event == "UserPromptSubmit" and kind == "human":
        template = NUDGE_NOTICED if noticed else NUDGE_ATTENDED
    else:
        template = NUDGE_UNATTENDED
```

(`record` is the one loaded inside the lock earlier in `nudge`; make it visible after the `with` block by assigning `record = None` before it.)

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=skills/context-vigil/scripts .venv/bin/python -m pytest -q tests/context_vigil_suite/test_notice.py tests/context_vigil_suite/test_hooks.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/context-vigil/scripts/context_vigil/hooks.py tests/context_vigil_suite/test_notice.py
git commit -m "feat(context-vigil): end-of-turn notice for the user, never the model"
```

---

### Task 9: Install question cards

**Files:**
- Create: `skills/context-vigil/scripts/context_vigil/cards.py`
- Test: `tests/context_vigil_suite/test_cards.py`

**Interfaces:**
- Produces: `cards.install_cards(mods: bool) -> dict` with keys `card1` (`{"questions": [...]}`), `followups` (`{"last_light_threshold": {...}, "always_confirm": {...}}`), `flags` (label → install flag string, e.g. `"35% (Recommended)": "--threshold 35"`); `cards.last_light_card() -> dict` (`{"questions": [...]}`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/context_vigil_suite/test_cards.py
"""Install questions as AskUserQuestion cards: shape limits and flag round-trips."""
from __future__ import annotations

import pytest
from context_vigil import cards, cli


def _all_cards(mods: bool) -> list:
    data = cards.install_cards(mods)
    return [data["card1"], *data["followups"].values(), cards.last_light_card()]


@pytest.mark.parametrize("mods", [True, False])
def test_cards_respect_ask_user_question_limits(mods: bool) -> None:
    for card in _all_cards(mods):
        assert 1 <= len(card["questions"]) <= 4
        for q in card["questions"]:
            assert len(q["header"]) <= 12
            assert q["question"].endswith("?")
            assert 2 <= len(q["options"]) <= 4
            assert q["options"][0]["label"].endswith("(Recommended)")
            assert q["multiSelect"] is False


def test_bar_question_only_with_mods() -> None:
    headers = lambda m: [q["header"] for q in cards.install_cards(m)["card1"]["questions"]]
    assert "🎛️ Vigil bar" in headers(True)
    assert "🎛️ Vigil bar" not in headers(False)


def test_every_option_maps_to_a_valid_install_flag() -> None:
    data = cards.install_cards(True)
    parser = cli.build_parser()
    for card in [data["card1"], data["followups"]["last_light_threshold"]]:
        for q in card["questions"]:
            for opt in q["options"]:
                flag = data["flags"][opt["label"]]
                parser.parse_args(["install", *flag.split()])   # raises SystemExit if invalid
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=skills/context-vigil/scripts .venv/bin/python -m pytest -q tests/context_vigil_suite/test_cards.py`
Expected: FAIL — `ImportError: cannot import name 'cards'`. (The flag round-trip also needs Task 10's install flags; it will keep failing until Task 10 — implement Task 10 next and run both together.)

- [ ] **Step 3: Implement**

```python
# skills/context-vigil/scripts/context_vigil/cards.py
"""Install questions in AskUserQuestion's exact input shape (spec §3b, §4).

The agent passes these to its AskUserQuestion tool as printed, so the strings live
here and nowhere else. Limits: ≤ 4 questions per card, header ≤ 12 chars, 2–4
options, the default first and marked "(Recommended)"."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from context_vigil import launcher

Option = Tuple[str, str, str]   # label, description, install flag


def _question(header: str, question: str, options: List[Option]) -> Dict[str, Any]:
    return {"header": header, "question": question, "multiSelect": False,
            "options": [{"label": label, "description": desc} for label, desc, _ in options]}


THRESHOLD: List[Option] = [
    ("35% (Recommended)", "A balance of lean context and fewer handovers.", "--threshold 35"),
    ("25%", "Hand over sooner, with a leaner context.", "--threshold 25"),
    ("50%", "Fewer handovers, more degradation before each.", "--threshold 50"),
]
LAUNCH: List[Option] = [
    ("🚀 On demand (Recommended)", "Adds a `claude-tmux` command; `claude` is unchanged.",
     "--launcher on-demand"),
    ("♾️ Always", "`claude` always starts inside tmux (asks to confirm).",
     "--launcher always --confirm-always"),
    ("⏸ Not now", "No launcher; you type /clear after a handover.", "--launcher not-now"),
]
LAST_LIGHT: List[Option] = [
    ("Off (Recommended)", "Nothing happens while you are away.", "--last-light off"),
    ("On", "When you've stepped away with context ≥ 25% and the cache is 5 minutes from "
           "going cold, the agent prepares a handover. Nothing is cleared: come back, carry "
           "on, or /clear to resume ✨ Needs tmux.", "--last-light on"),
]
LAST_LIGHT_THRESHOLD: List[Option] = [
    ("25% (Recommended)", "Step in once a cold cache would cost a quarter of the window.",
     "--last-light on --last-light-threshold 25"),
    ("35%", "Only for larger contexts.", "--last-light on --last-light-threshold 35"),
    ("50%", "Only for very large contexts.", "--last-light on --last-light-threshold 50"),
]
BAR: List[Option] = [
    ("No (Recommended)", "The end-of-turn notice is enough.", "--bar off"),
    ("Yes", "[1] hand over · [2] remind me later · [0] dismiss. Terminal and desktop; "
            "needs a Claude Code build with mods.", "--bar on"),
]
ALWAYS_CONFIRM: List[Option] = [
    ("Yes, always (Recommended)", launcher.ALWAYS_CONFIRM, "--launcher always --confirm-always"),
    ("No, on demand", "Use `claude-tmux` instead.", "--launcher on-demand"),
]


def install_cards(mods: bool) -> Dict[str, Any]:
    card1 = [
        _question("🎚️ Threshold", "At what context % should I tap you on the shoulder?",
                  THRESHOLD),
        _question("🖥️ Launcher", "How should Claude start for hands-free handovers?", LAUNCH),
        _question("🌅 Last light",
                  "Prepare a handover before an idle 1-hour cache goes cold 🧊?", LAST_LIGHT),
    ]
    options = THRESHOLD + LAUNCH + LAST_LIGHT + LAST_LIGHT_THRESHOLD + ALWAYS_CONFIRM
    if mods:
        card1.append(_question("🎛️ Vigil bar", "Add a pop-up bar above the prompt when "
                                                "context crosses the threshold?", BAR))
        options += BAR
    return {
        "card1": {"questions": card1},
        "followups": {
            "last_light_threshold": last_light_card(),
            "always_confirm": {"questions": [_question(
                "♾️ Always", "Make `claude` always start inside tmux?", ALWAYS_CONFIRM)]},
        },
        "flags": {label: flag for label, _, flag in options},
    }


def last_light_card() -> Dict[str, Any]:
    return {"questions": [_question("🎚️ Last light", "At what context % should last light "
                                                     "step in?", LAST_LIGHT_THRESHOLD)]}
```

- [ ] **Step 4: Run tests** — after Task 10 (flag round-trip depends on it):

Run: `PYTHONPATH=skills/context-vigil/scripts .venv/bin/python -m pytest -q tests/context_vigil_suite/test_cards.py -k "limits or bar_question"`
Expected: PASS for the shape tests now.

- [ ] **Step 5: Commit**

```bash
git add skills/context-vigil/scripts/context_vigil/cards.py tests/context_vigil_suite/test_cards.py
git commit -m "feat(context-vigil): install questions as AskUserQuestion cards"
```

---

### Task 10: Install/CLI flags — last light, the bar's plugin dir, `--questions-json`, `last-light`, status

**Files:**
- Modify: `skills/context-vigil/scripts/context_vigil/install.py` (`plan_install`, `plan_uninstall`, `apply`, `Plan`, `settings_summary`, new `claude_supports_mods`, `mod_dir`), `skills/context-vigil/scripts/context_vigil/cli.py` (`build_parser`, `_cmd_install`, new `_cmd_last_light`, `_cmd_status`), `skills/context-vigil/scripts/context_vigil/last_light.py` (`session_state`)
- Test: `tests/context_vigil_suite/test_install.py`, `tests/context_vigil_suite/test_cli.py`, `tests/context_vigil_suite/test_cards.py` (round-trip now passes)

**Interfaces:**
- Consumes: `cards.install_cards`, `cards.last_light_card`, `config.set_value`.
- Produces: `install.MOD_ENV = "CLAUDE_CODE_PLUGIN_DIRS"`, `install.mod_dir() -> Path` (= `paths.skill_dir() / "mod"`), `install.claude_supports_mods() -> bool`, `plan_install(threshold, launcher=None, last_light=None, last_light_threshold=None, bar=None)`; `Plan.last_light: Optional[bool]`, `Plan.last_light_threshold: Optional[int]`; record key `"bar"` (the mod path or absent). CLI: `install --questions-json`, `--last-light on|off`, `--last-light-threshold N`, `--bar on|off`; `last-light [on|off] [--threshold N] [--yes]`; status lines `🌅 last light: …` and `🎛️ vigil bar: …`; `last_light.session_state(cwd, session_id) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/context_vigil_suite/test_install.py
import os

from context_vigil import install as inst


def test_bar_on_adds_our_mod_dir_preserving_others(cfg, run_cli, monkeypatch) -> None:
    write_settings(cfg, {"env": {"CLAUDE_CODE_PLUGIN_DIRS": "/x/other", "KEEP": "1"}})
    r = run_cli("install", "--yes", "--bar", "on")
    assert r.returncode == 0, r.stderr
    env = read_settings(cfg)["env"]
    assert env["KEEP"] == "1"
    assert env["CLAUDE_CODE_PLUGIN_DIRS"].split(os.pathsep) == ["/x/other",
                                                               str(inst.mod_dir())]
    assert "/x/other" not in r.stdout          # other entries are never printed


def test_bar_off_and_uninstall_remove_only_ours(cfg, run_cli) -> None:
    write_settings(cfg, {"env": {"CLAUDE_CODE_PLUGIN_DIRS": "/x/other"}})
    run_cli("install", "--yes", "--bar", "on")
    run_cli("install", "--yes", "--bar", "off")
    assert read_settings(cfg)["env"]["CLAUDE_CODE_PLUGIN_DIRS"] == "/x/other"
    run_cli("install", "--yes", "--bar", "on")
    run_cli("uninstall", "--yes")
    assert read_settings(cfg)["env"]["CLAUDE_CODE_PLUGIN_DIRS"] == "/x/other"


def test_bar_removal_drops_an_emptied_key(cfg, run_cli) -> None:
    run_cli("install", "--yes", "--bar", "on")
    run_cli("install", "--yes", "--bar", "off")
    assert "CLAUDE_CODE_PLUGIN_DIRS" not in read_settings(cfg).get("env", {})


def test_install_sets_last_light_globally(run_cli, repo) -> None:
    from context_vigil import config
    assert run_cli("install", "--yes", "--last-light", "on",
                   "--last-light-threshold", "30", cwd=repo).returncode == 0
    assert config.last_light_enabled(repo) is True
    assert config.last_light_threshold(repo) == 30


@pytest.mark.parametrize("version,ok", [("2.1.287 (Claude Code)", True),
                                        ("2.1.289", True), ("2.1.200", False),
                                        ("garbage", False)])
def test_claude_supports_mods(iso, monkeypatch, version: str, ok: bool) -> None:
    stub = iso / "claude"
    stub.write_text(f'#!/usr/bin/env bash\necho "{version}"\n')
    stub.chmod(0o755)
    monkeypatch.setenv("CONTEXT_VIGIL_CLAUDE_BIN", str(stub))
    assert inst.claude_supports_mods() is ok
```

```python
# append to tests/context_vigil_suite/test_cli.py
def test_install_questions_json(run_cli) -> None:
    r = run_cli("install", "--questions-json", env={"CONTEXT_VIGIL_CLAUDE_BIN": "/nonexistent"})
    data = json.loads(r.stdout)
    assert [q["header"] for q in data["card1"]["questions"]] == [
        "🎚️ Threshold", "🖥️ Launcher", "🌅 Last light"]          # no mods → no bar


def test_last_light_command(run_cli, repo) -> None:
    dry = run_cli("last-light", "on", cwd=repo)
    assert json.loads(dry.stdout.split("\n\n")[0])["questions"][0]["header"] == "🎚️ Last light"
    assert "last-light on --yes" in dry.stdout
    on = run_cli("last-light", "on", "--yes", "--threshold", "30", cwd=repo)
    assert on.stdout.strip() == "🌅 last light: on (30%)"
    off = run_cli("last-light", "off", cwd=repo)
    assert off.stdout.strip() == "🌅 last light: off"


def test_status_shows_last_light_and_bar(run_cli, repo) -> None:
    out = run_cli("status", cwd=repo).stdout
    assert "🌅 last light: off" in out
    assert "🎛️ vigil bar: off" in out
```

(`test_install.py` already imports `read_settings`/`write_settings` from `.conftest`; `test_cli.py` imports `json` — add the imports if missing.)

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=skills/context-vigil/scripts .venv/bin/python -m pytest -q tests/context_vigil_suite/test_install.py tests/context_vigil_suite/test_cli.py tests/context_vigil_suite/test_cards.py -k "bar or last_light or questions or mods or round or every_option"`
Expected: FAIL — `unrecognized arguments: --bar` etc.

- [ ] **Step 3: Implement**

`install.py`:

```python
MOD_ENV = "CLAUDE_CODE_PLUGIN_DIRS"
MODS_SINCE = (2, 1, 287)


def mod_dir() -> Path:
    return paths.skill_dir() / "mod"


def claude_supports_mods() -> bool:
    """True when `claude --version` is a build with mods (≥ 2.1.287). Never raises."""
    binary = os.environ.get("CONTEXT_VIGIL_CLAUDE_BIN", "claude")
    try:
        out = subprocess.run([binary, "--version"], capture_output=True, text=True,
                             timeout=5, stdin=subprocess.DEVNULL).stdout
    except Exception:
        return False
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", out or "")
    return bool(match) and tuple(int(g) for g in match.groups()) >= MODS_SINCE


def _plugin_dirs(data: Dict[str, Any]) -> List[str]:
    env = data.get("env")
    raw = env.get(MOD_ENV) if isinstance(env, dict) else None
    return [p for p in raw.split(os.pathsep) if p] if isinstance(raw, str) else []


def _set_plugin_dirs(data: Dict[str, Any], dirs: List[str]) -> None:
    env = data.get("env")
    if not isinstance(env, dict):
        if not dirs:
            return
        env = data["env"] = {}
    if dirs:
        env[MOD_ENV] = os.pathsep.join(dirs)
    else:
        env.pop(MOD_ENV, None)
        if not env:
            del data["env"]


def _with_mod(data: Dict[str, Any], on: bool, ours: List[str]) -> None:
    """Add (on) or remove every path of ours from CLAUDE_CODE_PLUGIN_DIRS; others kept."""
    dirs = [d for d in _plugin_dirs(data) if d not in ours]
    if on:
        dirs.append(str(mod_dir()))
    _set_plugin_dirs(data, dirs)
```

Add `import subprocess` at the top if absent. Extend `Plan`:

```python
    last_light: Optional[bool] = None
    last_light_threshold: Optional[int] = None
```

`plan_install` signature and body additions:

```python
def plan_install(threshold: Optional[int], launcher: Optional[str] = None,
                 last_light: Optional[bool] = None,
                 last_light_threshold: Optional[int] = None,
                 bar: Optional[bool] = None) -> Plan:
    if threshold is not None:
        config.coerce("context.threshold", threshold)
    if last_light_threshold is not None:
        config.coerce("last_light.threshold", last_light_threshold)
    ...
    plan = Plan(threshold=threshold, last_light=last_light,
                last_light_threshold=last_light_threshold)
    ...
    if prior.get("bar") is not None:
        record["bar"] = prior["bar"]
    ours_mod = [str(mod_dir())] + ([str(prior["bar"])] if prior.get("bar") else [])
    if bar is not None:
        _with_mod(data, bar, ours_mod)
        record["bar"] = str(mod_dir()) if bar else None
```

(place the `bar` block after `data = _with_hooks(data, ours)`, before the status-line handling, and pass `mod_paths=ours_mod` into `settings_summary`.)

`settings_summary` — new keyword `mod_paths: Optional[List[str]] = None`; before `return lines`:

```python
    for mod in mod_paths or []:
        had, has = mod in _plugin_dirs(before), mod in _plugin_dirs(after)
        if has and not had:
            lines.append(f"  + env.{MOD_ENV}: adds {mod} (the vigil bar)")
        elif had and not has:
            lines.append(f"  - env.{MOD_ENV}: removes {mod} (the vigil bar)")
```

`plan_uninstall` — after `data = _without_hooks(data, ours)`:

```python
    ours_mod = [str(mod_dir())] + ([str(record["bar"])] if record.get("bar") else [])
    _with_mod(data, False, ours_mod)
```

and pass `mod_paths=ours_mod` to its `settings_summary` call. `apply` — after the threshold line:

```python
    if plan.last_light is not None:
        config.set_value(Path.cwd(), "last_light.enabled", "on" if plan.last_light else "off")
    if plan.last_light_threshold is not None:
        config.set_value(Path.cwd(), "last_light.threshold", str(plan.last_light_threshold))
```

`last_light.py` — add (import `json`):

```python
def session_state(cwd: Path, session_id: Optional[str]) -> str:
    """One word or phrase for `status`: why last light is or is not ready."""
    if not config.last_light_enabled(cwd):
        return "off"
    if not session_id:
        return "no session"
    scope = session.scope(cwd, session_id)
    if state.is_prepared(scope):
        return "prepared handover waiting"
    if tmux.pane() is None or not tmux.reachable():
        return "inactive: not tmux"
    try:
        store = json.loads(paths.read_private(census.store_path()))
        payload = store["sessions"][session_id]["payload"]
    except (OSError, ValueError, KeyError, TypeError):
        payload = {}
    cache = payload.get("prompt_cache") if isinstance(payload, dict) else None
    if not isinstance(cache, dict):
        return "inactive: no prompt_cache in status line"
    if cache.get("ttl") != "1h":
        return f"inactive: cache TTL {cache.get('ttl')}"
    return "armed" if session.load(session_id)["last_light_armed"] is True else "disarmed"
```

`cli.py` — import `cards`. Parser:

```python
    ip.add_argument("--questions-json", action="store_true",
                    help="print the install questions as AskUserQuestion cards")
    ip.add_argument("--last-light", choices=("on", "off"), default=None)
    ip.add_argument("--last-light-threshold", type=int, default=None)
    ip.add_argument("--bar", choices=("on", "off"), default=None)
    llp = sub.add_parser("last-light", help="prepare a handover before an idle cache goes cold")
    llp.add_argument("choice", nargs="?", choices=("on", "off"))
    llp.add_argument("--threshold", type=int, default=None)
    llp.add_argument("--yes", action="store_true")
    llp.set_defaults(func=_cmd_last_light)
```

`_cmd_install` — first lines:

```python
    if args.questions_json:
        print(json.dumps(cards.install_cards(install.claude_supports_mods()),
                         ensure_ascii=False, indent=2))
        return 0
    flag = {"on": True, "off": False, None: None}
    try:
        plan = install.plan_install(args.threshold, args.launcher, flag[args.last_light],
                                    args.last_light_threshold, flag[args.bar])
```

and in the dry-run "Apply with" line append `[--last-light on|off] [--last-light-threshold N] [--bar on|off]`.

New command:

```python
def _cmd_last_light(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    try:
        if args.choice == "off":
            config.set_value(cwd, "last_light.enabled", "off")
        elif args.choice == "on" and not args.yes:
            print(json.dumps(cards.last_light_card(), ensure_ascii=False, indent=2))
            print("\nApply with:  context-vigil last-light on --yes [--threshold N]")
            return 0
        elif args.choice == "on":
            if args.threshold is not None:
                config.set_value(cwd, "last_light.threshold", str(args.threshold))
            config.set_value(cwd, "last_light.enabled", "on")
    except config.ConfigError as exc:
        raise CliError(str(exc)) from exc
    print(_last_light_line(cwd))
    return 0


def _last_light_line(cwd: Path) -> str:
    if not config.last_light_enabled(cwd):
        return "🌅 last light: off"
    return f"🌅 last light: on ({config.last_light_threshold(cwd)}%)"
```

`_cmd_status` — add to `lines` after `nudge gate`:

```python
        _last_light_line(cwd) + (
            f", lead {config.last_light_lead_seconds(cwd)} s — this session: "
            f"{last_light.session_state(cwd, _env_session_id())}"
            if config.last_light_enabled(cwd) else ""),
        _bar_line(),
```

with

```python
def _bar_line() -> str:
    try:
        record = json.loads(paths.read_private(paths.install_record_path()))
    except (OSError, ValueError):
        record = {}
    if not (isinstance(record, dict) and record.get("bar")):
        return "🎛️ vigil bar: off"
    note = "" if install.claude_supports_mods() else " — but this Claude Code build has no mods"
    return f"🎛️ vigil bar: on{note}"
```

Note: `test_status_shows_last_light_and_bar` asserts the exact substring `🌅 last light: off`; the "this session" suffix is only added when on.

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=skills/context-vigil/scripts .venv/bin/python -m pytest -q tests/context_vigil_suite/test_install.py tests/context_vigil_suite/test_cli.py tests/context_vigil_suite/test_cards.py tests/context_vigil_suite/test_secrets.py tests/context_vigil_suite/test_setup_truth.py`
Expected: PASS (the secrets/setup-truth suites guard that summaries never print user values — the new `env` lines name only our path).

- [ ] **Step 5: Commit**

```bash
git add skills/context-vigil/scripts/context_vigil/install.py skills/context-vigil/scripts/context_vigil/cli.py skills/context-vigil/scripts/context_vigil/last_light.py tests/context_vigil_suite/test_install.py tests/context_vigil_suite/test_cli.py tests/context_vigil_suite/test_cards.py
git commit -m "feat(context-vigil): install cards, last-light command, the bar's plugin dir, status lines"
```

---

### Task 11: The vigil-bar mod

**Files:**
- Create: `skills/context-vigil/mod/.claude-plugin/plugin.json`, `skills/context-vigil/mod/hooks/hooks.json`, `skills/context-vigil/mod/hooks/register.tsx`, `skills/context-vigil/mod/types/index.d.ts`, `skills/context-vigil/mod/hooks/register.test.ts`
- Reference: the throwaway prototype at `~/.claude-personal/dev-mods/4a320dd1-a5b6-454b-99b2-c8b5f6d507e8/vigil-bar/` (validated, rendered on terminal) — copy its structure, not its test-only pieces (`/vigil-bar-test`, logging, the ask card).
- API reference: the plugin-authoring skill (`Skill plugin-authoring`) — it writes this build's `claude-code.d.ts`; grep it for `'turn.complete'`, `AbovePrompt: {`, `prompt: {`, `env: {`, `fs: {`, and `export const test`.

**Interfaces:**
- Consumes (read-only): context-vigil's data root — `$CONTEXT_VIGIL_HOME`, else `$CLAUDE_CONFIG_DIR/context-vigil` (else `$HOME/.claude/context-vigil`); if that directory has no `.context-vigil-root` but `<it>/context-vigil/.context-vigil-root` exists, use the nested one (mirrors `paths.data_root`). Config file `<root>/config.json` keys `context.threshold` (default 35), `nudge.repeat_step` (default 5); env `CONTEXT_VIGIL_THRESHOLD` / `CONTEXT_VIGIL_REPEAT_STEP` win. The worktree config layer is ignored (documented).
- Produces: the `AbovePrompt` band; `[1]` submits `"hand over now"` as the user.

- [ ] **Step 1: Write the manifest, hooks list and state contract**

```json
// skills/context-vigil/mod/.claude-plugin/plugin.json
{ "name": "vigil-bar", "version": "0.1.0",
  "description": "context-vigil: a pop-up bar above the prompt when context crosses the threshold",
  "types": "./types/index.d.ts" }
```
```json
// skills/context-vigil/mod/hooks/hooks.json
{ "modules": ["./register.tsx"] }
```
```ts
// skills/context-vigil/mod/types/index.d.ts
export type Due = { pct: number; threshold: number; step: number }

declare module 'claude-code' {
  interface PluginState {
    'vigil-bar': { band: Due | null; lastShownPct: number | null; dismissed: boolean }
  }
}
```

- [ ] **Step 2: Write the failing mod test**

```ts
// skills/context-vigil/mod/hooks/register.test.ts
import { expect, test } from 'claude-code/testing'

// Each test answers the engine calls the module makes beneath it (the kit's bottom
// hook throws naming any event left unanswered — read that name and add the answer).
// Drive: answer session usage with { context: { percent, window: 200000 } }, the env
// reads (CONTEXT_VIGIL_HOME → '/cv'), and $.fs.read('/cv/.context-vigil-root') → '',
// $.fs.read('/cv/config.json') → '{"context.threshold": 35}'; raise turn.complete;
// mount AbovePrompt on each surface and inspect it.

for (const surface of ['terminal', 'desktop'] as const) {
  test(`band appears once due (${surface})`, async ($, on) => {
    // answers for usage (percent 41), env, fs as described above
    // raise turn.complete, then mount { plugin: 'vigil-bar', surface, component: 'AbovePrompt',
    //   props: { hasSurvey: false, isWorking: false, maxRows: 10, bodyColumns: 120 } }
    // expect(await ui.find({ key: 'go' })).toBeDefined()
  })
}

test('no band below threshold', async ($, on) => { /* percent 20 → find('go') undefined */ })
test('no band while the survey shows', async ($, on) => { /* props.hasSurvey true */ })
test('no band when the last human prompt came over the bridge', async ($, on) => {
  /* raise prompt.submit with origin { kind: 'bridge' } first */ })
test('[1] submits "hand over now" as the user', async ($, on) => {
  /* answer prompt.submit beneath and record its input; press 'go';
     expect(recorded).toMatchObject({ text: 'hand over now', asUser: true }) */ })
test('[2] hides until the next step; [0] hides for the cycle', async ($, on) => {
  /* press 'later' → gone; raise turn.complete at 43 → still gone; at 46 → back;
     press 'no' → gone; at 51 → still gone */ })
```

Fill each body with real kit calls from the typings (`test(name, body)`, `on(...)` answering beneath, the `ui` noun's `mount`/`find`/`press`). The skeleton fixes WHAT each test proves; the kit's exact call names come from `claude-code.d.ts` in this build. A test whose body is still a comment is not done.

- [ ] **Step 3: Run to verify failure**

Run: `claude plugin validate skills/context-vigil/mod && claude plugin test skills/context-vigil/mod`
Expected: validate fails (no `register.tsx`), or tests fail.

- [ ] **Step 4: Implement `register.tsx`**

```tsx
// skills/context-vigil/mod/hooks/register.tsx
// context-vigil's vigil bar: when context crosses the threshold (then every repeat
// step), a band above the prompt — [1] hand over · [2] remind me at +step · [0] dismiss.
// Skipped when the person last spoke from the phone (origin 'bridge'): the band is
// terminal/desktop only, and the Stop notice already reached them there.
import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Due } from '../types'

const HAND_OVER = '📜 Hand over now'
const DISMISS = '✖ Dismiss'

const band = atom({ plugin: 'vigil-bar', key: 'band' } as const, null)
const lastShownPct = atom({ plugin: 'vigil-bar', key: 'lastShownPct' } as const, null)
const dismissed = atom({ plugin: 'vigil-bar', key: 'dismissed' } as const, false)

async function readText($: EngineInterface, path: string): Promise<string | null> {
  try {
    return await $.fs.read(path)
  } catch {
    return null
  }
}

async function dataRoot($: EngineInterface): Promise<string | null> {
  const home = await $.env.get('CONTEXT_VIGIL_HOME')
  const configDir = await $.env.get('CLAUDE_CONFIG_DIR')
  const userHome = await $.env.get('HOME')
  const base = home ?? (configDir ? `${configDir}/context-vigil`
    : userHome ? `${userHome}/.claude/context-vigil` : null)
  if (base === null) return null
  if ((await readText($, `${base}/.context-vigil-root`)) !== null) return base
  if ((await readText($, `${base}/context-vigil/.context-vigil-root`)) !== null) {
    return `${base}/context-vigil`
  }
  return null
}

function whole(raw: unknown, lo: number, hi: number): number | null {
  const n = typeof raw === 'number' ? raw : typeof raw === 'string' ? Number(raw) : NaN
  return Number.isInteger(n) && n >= lo && n <= hi ? n : null
}

async function settings($: EngineInterface): Promise<{ threshold: number; step: number } | null> {
  const root = await dataRoot($)
  if (root === null) return null
  let cfg: Record<string, unknown> = {}
  try {
    cfg = JSON.parse((await readText($, `${root}/config.json`)) ?? '{}')
  } catch {
    cfg = {}
  }
  const threshold = whole(await $.env.get('CONTEXT_VIGIL_THRESHOLD'), 1, 95)
    ?? whole(cfg['context.threshold'], 1, 95) ?? 35
  const step = whole(await $.env.get('CONTEXT_VIGIL_REPEAT_STEP'), 1, 50)
    ?? whole(cfg['nudge.repeat_step'], 1, 50) ?? 5
  return { threshold, step }
}

async function percent($: EngineInterface): Promise<number | null> {
  const usage = await $.session.usage()
  const pct = usage?.context?.percent
  return typeof pct === 'number' ? pct : null
}

async function choose($: EngineInterface, key: 'go' | 'later' | 'no'): Promise<void> {
  await update($, band, () => null)
  if (key === 'go') {
    await $.prompt.submit({ text: 'hand over now', asUser: true })
  } else if (key === 'no') {
    await update($, dismissed, () => true)
  }
}

export const register: Register = on => {
  let lastOrigin = 'composer'

  on('session.start', async ($, e, next) => {
    await update($, band, () => null)
    await update($, lastShownPct, () => null)
    await update($, dismissed, () => false)
    return next(e)
  })

  on('prompt.submit', async ($, e, next) => {
    const kind = e.origin?.kind
    if (kind === 'composer' || kind === 'bridge') lastOrigin = kind
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const done = await next(e)
    if (lastOrigin === 'bridge' || (await read($, dismissed))) return done
    const pct = await percent($)
    const cfg = await settings($)
    if (pct === null || cfg === null || pct < cfg.threshold) return done
    const last = await read($, lastShownPct)
    if (last !== null && pct < last + cfg.step) return done
    await update($, lastShownPct, () => pct)
    await update($, band, () => ({ pct, threshold: cfg.threshold, step: cfg.step }))
    return done
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const due = await read($, band)
    if (due === null || e.props.hasSurvey) return next(e)
    const { Box, Button, Text } = $.ui.resolve(e)
    return (
      <Box>
        <Text>🕯️ context {due.pct}% · threshold {due.threshold}%{'   '}</Text>
        <Button key="go" hotkey="1" label={HAND_OVER} variant="primary"
          onPress={() => choose($, 'go')} />
        <Text> </Text>
        <Button key="later" hotkey="2" label={`⏰ Remind me at +${due.step}%`}
          onPress={() => choose($, 'later')} />
        <Text> </Text>
        <Button key="no" hotkey="0" label={DISMISS} role="dismiss"
          onPress={() => choose($, 'no')} />
      </Box>
    )
  })
}
```

If validation reports an unknown property (e.g. `e.origin` on `prompt.submit` or `usage.context.percent`), look the declaration up in `claude-code.d.ts` and use the declared name — keep the behaviour.

- [ ] **Step 5: Validate, type-check and test**

Run: `claude plugin validate skills/context-vigil/mod && claude plugin test skills/context-vigil/mod`
Expected: `✔ Validation passed` (an "author" warning is fine) and every test passes.

- [ ] **Step 6: Commit**

```bash
git add skills/context-vigil/mod
git commit -m "feat(context-vigil): vigil bar mod — a band above the prompt with hotkeys"
```

---

### Task 12: Docs, SKILL.md card flow, live smoke scenarios, final verification

**Files:**
- Modify: `skills/context-vigil/SKILL.md`, `skills/context-vigil/README.md`, `skills/context-vigil/dev/live-smoke`, `skills/context-vigil/dev/README.md`
- Test: `tests/context_vigil_suite/test_live_smoke_helpers.py` (append), full suite

- [ ] **Step 1: SKILL.md install flow** — replace the "ask the threshold question exactly as printed … launch walkthrough" steps with:

```markdown
2. Run `context-vigil install --questions-json`. Ask `card1` with the
   AskUserQuestion tool, passing its `questions` exactly as printed. Then, only if
   needed: `followups.last_light_threshold` (they chose 🌅 Last light → On) and
   `followups.always_confirm` (they chose ♾️ Always). Map every chosen label through
   `flags` and run `context-vigil install --yes <the flags>`. "Other" is accepted
   only for thresholds (1–95). Without the AskUserQuestion tool (`claude -p`), ask the
   same questions in plain text.
```

Add a "Last light" section: what it does (prepare, never clear), that `last-light on` prints a card to ask before enabling, that the agent on receiving a `[context-vigil:last-light]` prompt runs `notes-path`, fills it, runs `handover --file <path> --prepared`, replies with the printed line and stops. Add "When the user says 'hand over now'" pointing at the existing handover steps. Replace the known limit "mid-turn only after TaskCreate/TaskUpdate…" with: "The end-of-turn notice tells you when context crosses the threshold; the agent is asked about it on your next message."

- [ ] **Step 2: README** — settings table gains the three `last_light.*` rows (lead marked "not asked"); a "Last light" section (gates, the two locks, needs tmux + 1-hour cache, nothing ticks while the machine sleeps); a "Vigil bar" section (terminal/desktop, skipped when you last spoke from the phone, install flag, `CLAUDE_CODE_PLUGIN_DIRS`, worktree threshold not read); "Precautions" gains "never types into an open dialog"; known limits updated as in Step 1.

- [ ] **Step 3: live-smoke scenarios** — add two subcommands to `dev/live-smoke`:
  - `notice`: `up` with threshold 2; send one prompt; wait for the turn; assert the pane shows `Stop says: 🕯️ context-vigil` exactly once, and the newest transcript has no `context-vigil · context at` text in any `user` entry.
  - `last-light`: `up` with `CONTEXT_VIGIL_LAST_LIGHT=on`, `CONTEXT_VIGIL_LAST_LIGHT_LEAD_SECONDS=3595`, `CONTEXT_VIGIL_LAST_LIGHT_THRESHOLD=1` in the sandbox settings `env`, and `statusLine.refreshInterval` 10; send a real prompt; wait ≤ 60 s for `handoff-prepared` under the data root; assert no `/clear` happened (session id unchanged), wait 30 s more and assert the marker prompt was typed exactly once (count `[context-vigil:last-light]` in the transcript); send a real prompt and assert `handoff.discarded.md` appears in the archive.

  Add pure-helper tests for any new parsing helper you write (e.g. counting marker prompts in a transcript) to `test_live_smoke_helpers.py`.

- [ ] **Step 4: Full verification**

Run: `PYTHONPATH=skills/context-vigil/scripts .venv/bin/python -m pytest -q tests/context_vigil_suite`
Expected: all pass (687 + the new tests).
Run: `.venv/bin/ruff check $(git diff --name-only c482ff5 -- '*.py' 'skills/context-vigil/dev/live-smoke')` — clean on touched files.
Run: `/usr/bin/python3 -c "import sys; sys.path.insert(0,'skills/context-vigil/scripts'); import context_vigil.cli, context_vigil.last_light, context_vigil.pane, context_vigil.cards, context_vigil.messages"` — imports on 3.9.
Run (live, haiku — owner-approved token spend): `skills/context-vigil/dev/live-smoke auto --model haiku`, `… headless --model haiku`, `… notice --model haiku`, `… last-light --model haiku`. Expected: all PASS. If `auto` regresses at "new session id", Review Focus #1 bit: capture the pane at Stop (`peek -n 30`) and fix `pane.input_row`, not the test.

- [ ] **Step 5: Commit**

```bash
git add skills/context-vigil/SKILL.md skills/context-vigil/README.md skills/context-vigil/dev tests/context_vigil_suite/test_live_smoke_helpers.py
git commit -m "docs(context-vigil): last light, notice, vigil bar, card install; live smoke scenarios"
```

---

## Self-Review (done while writing)

- **Spec coverage:** §1 gates 1–8 → Tasks 2, 3, 7; firing/locks → 6, 7; prepared lifecycle (/clear loads, human prompt discards, quit keeps) → 5, 6 (the /clear path already loads any handoff via `consume_handoff`; quit-and-offer is the existing SessionStart path); setup/status → 10; §2 notice + safety rules + next-prompt context → 8 (rules 1–6 each tested); §3 bar incl. origin rule and survey yield → 11; install edit/uninstall → 10; §3a safety net → 3, 4 (last light's use in 7); §3b cards → 9, 10, 12; §4 strings → 1, 9; live verification → 12.
- **Placeholders:** the mod test bodies (Task 11 Step 2) name the assertions but defer exact kit call names to this build's typings — deliberate, with an explicit "not done while a body is a comment" rule.
- **Type consistency:** `last_light.tick(payload, now)`, `pane.pane_safe(target)`, `state.write_prepared/discard_prepared/is_prepared`, `messages.system_message`, record keys `last_light_armed`/`last_noticed_pct`, `cards.install_cards(mods)`/`last_light_card()` are used with the same names throughout.
