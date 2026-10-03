# context-vigil: last light, and mid-turn nudges on every tool

Date: 2026-10-04 · Branch: `feat/context-vigil` · Builds on
`2026-10-02-context-vigil-design.md`.

Two changes, delivered as separate chunks so each can ship or be reverted alone:

1. **Last light** — before a 1-hour prompt cache goes cold on an idle session,
   ask the agent to *prepare* a handover. Nothing is cleared; the user returns
   to a choice.
2. **Mid-turn nudges on every tool** — widen the PostToolUse nudge from the
   Task tools to all tools, behind a shell pre-check so the common case stays
   cheap.

---

## 1. Last light

### Intent

An idle session with a large context loses its prompt cache when the TTL
lapses. The next prompt then pays to rewrite the whole context (cache write is
2× input price on the 1-hour TTL, against 0.1× for a read). Last light spends
one warm, cheap turn writing a handover a few minutes before that, so the
returning user can either carry on (and pay the cold cache, their choice) or
`/clear` and resume from a small context.

It **prepares**; it never clears and never resumes. It is **off by default**.

### What the status line gives us

The status-line payload (Claude Code 2.1.288) carries a `prompt_cache` section:

```json
"prompt_cache": {"warm": true, "ttl": "1h", "expires_at": 1791060004,
                 "recache_tokens_if_cold": 48359, "requests": 8, ...}
```

This field is not documented. Its absence, or any shape we do not recognise,
means **last light does nothing** — never a guess from transcript timestamps.

### Clock

The status-line timer. `refreshInterval` re-runs the status line while the
session is idle; a probe (2026-10-04, two idle panes, `refreshInterval` 10 s,
no prompts) measured 9.8–10.1 s gaps both with no tmux client attached and as
a background window of an attached client. The installer already sets
`refreshInterval: 60`, so the check runs at most a minute late — inside a
5-minute lead.

Every tick already runs `capture.sh` → `context-vigil ingest`. After the census
write, `ingest` calls `last_light.tick(payload)`. No new process, no timer to
cancel or reschedule, and every tick decides from current state alone, so a
crash or restart leaves nothing stale. Known limit: nothing ticks while the
machine sleeps or the process is suspended.

### Config (global only, `$CLAUDE_CONFIG_DIR/context-vigil/`)

| Key | Default | Asked? |
|---|---|---|
| `last_light.enabled` | `false` | At install, and via `last-light on` |
| `last_light.threshold` | `25` (ctx %, 1–95) | Whenever it is enabled |
| `last_light.lead_seconds` | `300` | Never — documented, silent |

No `--worktree` override for these keys; `config set --worktree last_light.*`
is refused. Environment overrides follow the existing pattern
(`CONTEXT_VIGIL_LAST_LIGHT`, `…_THRESHOLD`, `…_LEAD_SECONDS`) so tests and the
smoke harness can drive it.

### Gates — all must hold for a tick to fire

1. `last_light.enabled` is true.
2. `prompt_cache.ttl == "1h"`, `prompt_cache.warm is true`, and
   `expires_at` is a number.
3. `0 < expires_at − now ≤ lead_seconds`.
4. Context % (the payload's `context_window.used_percentage`) ≥
   `last_light.threshold`.
5. **Lock 1 — armed:** the session record has `last_light_armed: true`.
6. **Lock 2 — nothing prepared:** no prepared handover exists for the scope.
7. No pending handover / `/clear` flag for the scope, and the scope is not
   paused.
8. The session is in tmux (`tmux_pane` known and reachable), and the pane is
   safe to type into: the capture shows the empty input box, no menu or
   dialog, and no `esc to interrupt`. "Empty" must allow for the placeholder
   an idle box shows (`❯ Try "fix lint errors"`, rendered dim): the check uses
   `capture-pane -e` and treats the `❯` row as empty only when everything after
   the cursor carries the dim attribute (SGR 2) or is blank. Anything typed by
   the user renders normal-weight and blocks the fire. If the attribute
   cannot be read, the pane is not safe.

Gates 1–4 are pure payload/config checks and run first; the tmux capture
(gate 8) runs only when they pass, so an ordinary tick costs no subprocess.

### Firing

Under the session record's lock (`session.locked`), re-check gates 5–7, then:

1. set `last_light_armed = false` and save the record;
2. `tmux send-keys` the marked prompt (literal text, then Enter):

> `[context-vigil:last-light]` The prompt cache expires in about N minutes and
> this session is idle. Prepare a handover: run `<launcher> notes-path`, fill
> in the file it prints, then run `<launcher> handover --file <path>
> --prepared`. Then reply in one line that a handover is ready and stop. Do
> not /clear and do not continue the task.

A lock that cannot be had means no fire this tick.

### Locks against the loop

Preparing a handover is an API call, which refreshes the cache for another
hour; unguarded, the next tick 55 minutes later would fire again, forever.
Two independent locks, on different state:

- **Lock 1 — armed flag (session record).** Only a *real* prompt arms:
  UserPromptSubmit sets `last_light_armed = true` when the prompt does **not**
  start with the marker `[context-vigil:last-light]`. Firing disarms. The
  injected prompt carries the marker and never re-arms.
- **Lock 2 — prepared handover on disk (scope state).** No fire while a
  prepared handover exists for the scope. It leaves only by `/clear` (loads it),
  a real prompt (discards it) or `handover --discard`.

Either lock alone stops the loop after one prepared handover. A session starts
**disarmed**: last light needs one real prompt before it can ever fire.

### The prepared handover

`handover --file <notes> --prepared` runs the normal pipeline (template
validation, git pointer, 8k cap, private storage) and writes the scope's
handoff file **plus** a `prepared` marker beside it. It does **not** set the
clear flag, so the Stop hook does nothing and the turn simply ends.

`--prepared` is refused when a non-prepared handover is pending (a real
handover always wins).

What happens next:

| User does | Result |
|---|---|
| Types `/clear` | SessionStart (`clear`) loads the prepared handover like a normal one, archives it, removes the marker. |
| Sends any other prompt | UserPromptSubmit (real prompt) archives the handover with a `discarded` suffix (recoverable by hand), removes the marker, and re-arms. The work has moved on; a later prepared handover will reflect it. |
| Quits claude | The handover waits; a new session in that scope is offered it as today ("never loaded without asking"). |

The nudge cycle is untouched: a prepared handover does not reset the nudge gate
or `last_nudged_pct`.

### Setup

**Install** prints a third question (after threshold and launcher):

> **Last light** (off by default). With a 1-hour prompt cache, when this
> session is idle with context ≥ 25% and the cache is 5 minutes from expiring,
> context-vigil asks the agent to prepare a handover. Nothing is cleared: when
> you come back, carry on as normal or type /clear to resume from it. Needs
> tmux. Turn it on? [y/N] — if yes: threshold? [25]

Applied by `install --yes … --last-light on|off [--last-light-threshold N]`.
SKILL.md tells the agent to ask it exactly as printed, like the others.

**Later:** `context-vigil last-light [on|off] [--threshold N] [--yes]`, on the
`launcher` subcommand's pattern — `on` without `--yes` is a dry run printing the
threshold question (default 25) so the agent always asks; `off` needs no
question. Thin wrapper over the `last_light.*` keys.

**status** adds `last light: on (25%, lead 300 s)` / `off`, and for the current
session one of: `armed`, `disarmed`, `prepared handover waiting`,
`inactive: not tmux`, `inactive: cache TTL 5m`,
`inactive: no prompt_cache in status line`.

### Files

- New `scripts/context_vigil/last_light.py` — `tick(payload)`, gate checks,
  `pane_safe(target)`, `MARKER`, prompt text. One purpose, testable without
  tmux by injecting the pane capture.
- `census.py` / `cli.py` (`ingest`) — call `last_light.tick` after the write;
  any exception is swallowed (the status line must never fail).
- `hooks.py` — UserPromptSubmit: classify the prompt, arm, discard a prepared
  handover on a real prompt. SessionStart `clear`: load a prepared handover.
- `state.py` — `prepared` marker helpers; discard-to-archive.
- `session.py` — `last_light_armed` field (default false).
- `config.py` — the three keys, global-only.
- `cli.py` / `install.py` — `--prepared`, `last-light` subcommand, install
  question and flags, status lines.
- `SKILL.md`, `README.md`, `templates/` — the question, the prompt's contract,
  the settings table, the known limits.

### Testing

Unit (no tmux, pane capture injected):

- each gate in isolation, including absent/malformed `prompt_cache`, `ttl`
  `5m`, `expires_at` past, cold cache, paused scope, pending handover;
- pane safety: empty box ✓; text in the box, a menu, a dialog,
  `esc to interrupt` ✗;
- prompt classification: marker vs real; arm on real only;
- `--prepared`: writes marker, no clear flag; refused over a pending real
  handover;
- real prompt discards a prepared handover to the archive and re-arms;
  `/clear` loads it and removes the marker;
- concurrency: two ticks racing fire once (record lock).

**The loop test:** fire → marker prompt → cache refreshed (`expires_at` +1 h) →
tick near the new expiry → must not fire. Run three ways: both locks live,
lock 1 forced open (armed stays true), lock 2 forced open (marker never
written). Each must still not fire twice.

Live smoke — new `dev/live-smoke last-light` scenario: `refreshInterval` 10,
`CONTEXT_VIGIL_LAST_LIGHT_LEAD_SECONDS=3595` so the first tick after a real
prompt is "near expiry"; assert a prepared handover appears, no `/clear`
happens, later ticks do not fire again, a real prompt discards it, and a second
cycle's `/clear` loads it.

---

## 2. Mid-turn nudges on every tool

### Today

PostToolUse runs the nudge only for `TaskCreate|TaskUpdate`, so a long run that
never uses the Task tools is nudged at the next prompt (documented known limit).

### Change

- PostToolUse matcher becomes `*` (all tools).
- **Pre-check in the launcher**, before Python starts: for `hook nudge` on a
  PostToolUse event, `ingest` maintains a per-session flag file
  `sessions/<session_id>.due`, present only when a nudge would fire now
  (pct ≥ threshold and not yet nudged this cycle, or pct ≥ last nudged +
  repeat step, with a confident window). The launcher extracts `session_id` from
  stdin with a shell pattern, and if `<data root>/sessions/<id>.due` does not
  exist, exits 0 without starting Python. Target: ≈5 ms per tool call in the
  common case.
- Python `nudge()` remains the authority (it re-checks everything under the
  lock); the flag only decides whether to ask it. A stale or missing flag can
  delay a nudge by one tool call or ingest, never fire a wrong one.
- UserPromptSubmit keeps running Python unconditionally (once per prompt is
  cheap and it now also arms last light).
- Data-root resolution in shell mirrors `paths.data_root()` for the read only
  (`CONTEXT_VIGIL_HOME`, else `$CLAUDE_CONFIG_DIR/context-vigil`, else
  `~/.claude/context-vigil`); on any doubt (unparseable id, unexpected
  characters, missing root) it falls through to Python.

### Install migration

`install` replaces an existing context-vigil PostToolUse entry with matcher
`TaskCreate|TaskUpdate` by the `*` entry (ours only, matched exactly as today);
`status` reports the old matcher as "outdated — re-run install".

### Testing

- Launcher pre-check: no flag → Python not started (stub interpreter records
  calls); flag → Python started; odd session ids fall through to Python.
- `.due` lifecycle in `ingest`: appears at threshold, clears after a nudge,
  reappears at +repeat step, cleared on SessionStart.
- Install migration from the old matcher; uninstall removes either form.
- SKILL.md / README: drop the "only after Task tools" limit.

---

## Out of scope

- Keeping the cache warm with keep-alive prompts (that *is* the loop).
- Last light outside tmux, or for headless runs.
- Anything for the 5-minute TTL.
- A firing cap/fuse (considered and dropped: it could block genuine use).
