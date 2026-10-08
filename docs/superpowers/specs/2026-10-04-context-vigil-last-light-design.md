# context-vigil: last light, the end-of-turn notice, and the vigil bar

Date: 2026-10-04 · Branch: `feat/context-vigil` · Builds on
`2026-10-02-context-vigil-design.md`.

Three changes, delivered as separate chunks so each can ship or be reverted
alone:

1. **Last light** — before a 1-hour prompt cache goes cold on an idle session,
   ask the agent to *prepare* a handover. Nothing is cleared; the user returns
   to a choice.
2. **End-of-turn notice** — the Stop hook tells the *user* (never the model)
   when context crosses the threshold, so they can say "hand over" on the very
   next turn. Always on.
3. **Vigil bar** (optional mod) — the same moment as a pop-up band above the
   prompt with hotkeys, like Claude Code's own rating bar; skipped when the
   person last spoke from the phone.

Plus two supporting changes: **3a**, every `tmux send-keys` path refuses to
type into an open dialog; **3b**, install questions arrive as AskUserQuestion
cards (terminal, desktop and phone).

User-facing text across all of it (and the existing notices and install
questions) gets a lighter, emoji-led voice — see §4. Model-facing text stays
plain.

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
   safe to type into: the capture shows the empty input box and no menu or
   dialog (no `❯` cursor on a numbered/option row). Busy-detection does not
   rely on spinner text — Claude Code 2.1.289 no longer shows
   `esc to interrupt` — because gate 3 already implies ~55 minutes with no API
   traffic, so no model turn can be running. "Empty" must allow for the placeholder
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
> --prepared`. Then reply with exactly the line it prints (the §4 "prepared"
> line) and stop. Do not /clear and do not continue the task.

A lock that cannot be had means no fire this tick.

### Locks against the loop

Preparing a handover is an API call, which refreshes the cache for another
hour; unguarded, the next tick 55 minutes later would fire again, forever.
Two independent locks, on different state:

- **Lock 1 — armed flag (session record).** Only a *real* prompt arms:
  UserPromptSubmit sets `last_light_armed = true` for a human prompt. Firing
  disarms. Not human, so never arms and never discards: a prompt starting
  with the marker `[context-vigil:last-light]` (ours), and a prompt starting
  with `<task-notification>` (a background task finishing starts a turn of its
  own — observed in the 2026-10-04 Stop probe; counting it would discard a
  prepared handover and re-arm with nobody present).
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
| Sends any other (human) prompt | UserPromptSubmit archives the handover with a `discarded` suffix (recoverable by hand), removes the marker, and re-arms. The work has moved on; a later prepared handover will reflect it. |
| Quits claude | The handover waits; a new session in that scope is offered it as today ("never loaded without asking"). |

The nudge cycle is untouched: a prepared handover does not reset the nudge gate
or `last_nudged_pct`.

### Setup

**Install** prints a third question after threshold and launcher (wording in
§4 "Install: last light"), then the threshold question if yes.

Applied by `install --yes … --last-light on|off [--last-light-threshold N]`
(and `--bar on|off` for §3).
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
- pane safety: empty box and dim placeholder ✓; typed text in the box, a
  menu, a dialog, unreadable attributes ✗;
- prompt classification: marker, `<task-notification>` and human; arm and
  discard on human only;
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

## 2. End-of-turn notice (always on)

### Why

Today the nudge fires at UserPromptSubmit of the turn *after* the threshold is
crossed: the agent answers, then asks, and the handover happens two turns
later. Widening PostToolUse to every tool was assessed and dropped: 581 of 591
turns that grew ≥ 20k tokens never used a Task tool, but a mid-turn nudge only
helps a turn so long it would reach auto-compaction (rare: 33 of 4,716 turns
grew ≥ 100k), it fires inside subagents (which share the parent's session id),
and in an attended session it makes the agent stop mid-task to raise a handover
nobody asked for. The PostToolUse entry for `TaskCreate|TaskUpdate` stays as is.

### Behaviour

At **Stop**, when context is over the threshold and a notice is due (first
crossing, then every `nudge.repeat_step` points — the same sequence the nudge
uses), the hook prints a `systemMessage` the **user** sees (§4 "notice").

The next UserPromptSubmit, in an attended session, injects a shorter
model-facing context in place of today's ask-first template: context is at N%,
the user has been shown the notice; if their message asks to hand over, follow
the handover steps; otherwise answer normally and do not raise it. Unattended
sessions (auto mode, headless) keep today's unattended nudge unchanged; a
notice there is harmless and still shown.

### Verified behaviour (live probe, 2026-10-04, Claude Code 2.1.289, haiku)

A throwaway Stop hook printing one `{"systemMessage": ...}` object, exit 0:

- shown in the transcript as `⎿ Stop says: <text>`, once per turn; quotes and
  a backslash rendered correctly;
- **not sent to the model**: a canary word in the notice was absent from the
  model's context on the next turn (asked to repeat any `zq…` word, it
  answered `NONE`); the transcript stores it as a `hook_system_message`
  attachment;
- no continuation: the turn ended, no extra turn started;
- **Esc interrupt does not fire Stop** (as documented); a background task's
  completion notice starts a turn of its own and so fires Stop again;
- **shown on the phone**: in a Remote Control session opened in the Claude
  mobile app, a turn started from the phone ended with the notice rendered
  there (`Stop says: 🕯️ …`, emoji, quotes and dash intact); one hook call,
  `stop_hook_active` false, no continuation.

### Safety rules for the Stop path (from the hooks docs and the probe)

Only two things make a Stop hook continue the turn: exit 2, and
`decision: "block"`. Plain non-JSON stdout may be added to the model's
context. Therefore:

1. The Stop handler writes **exactly one `json.dumps(...)` object, or
   nothing** — never `print` of free text anywhere on the Stop path. Message
   text is passed as a value to `json.dumps`, which does all escaping.
2. **Never** emits `decision`, `block`, `continue: false` or `reason`.
3. **Exit 0 always** — already guaranteed by the launcher (`hook` swallows
   every failure and exits 0) and kept.
4. Returns nothing when `stop_hook_active` is true.
5. Stays silent when not due; the notice gate lives in the session record
   (`last_noticed_pct`) under the record lock, so a burst of Stops (background
   notifications) shows it once per step.
6. Message length is capped (≤ 300 chars); `pct` and `threshold` are ints
   formatted by Python, never interpolated from payload strings.

Tests assert rules 1–6 directly: Stop output is empty or parses as one JSON
object whose only key is `systemMessage`; payloads with quotes, newlines,
backslashes and non-ASCII in every string field produce valid JSON; a raised
exception yields empty stdout and exit 0 through the real launcher;
`stop_hook_active: true` yields empty stdout.

### Cost

One context measurement per Stop (the same read UserPromptSubmit already
does, ~80 ms per turn — not per tool call).

---

## 3. Vigil bar (optional mod)

A Claude Code mod (plugin hooks module) shipped inside the skill at
`skills/context-vigil/mod/` (`.claude-plugin/plugin.json`, `hooks/hooks.json`,
`hooks/register.tsx`, `types/index.d.ts`, a `*.test.ts`).

### What it does

On `turn.complete`, when context is over the threshold and a bar is due (same
first-crossing / +step rule), it raises an **`AbovePrompt` band**:

```
🕯️ context 41% · threshold 35%    [1] 📜 Hand over now   [2] ⏰ Remind me at +5%   [0] ✖ Dismiss
```

- **[1]** `$.prompt.submit({ text: "hand over now", asUser: true })` — a real
  user turn; the agent hands over (SKILL.md's "when asked to hand over").
- **[2]** hide until context reaches the next step.
- **[0]** hide for this cycle (until a handover or `/clear`).
- Yields while `e.props.hasSurvey` (Claude Code's own rating bar) is showing.
- Reads context from the mod API's live `context_window` figures and the
  threshold / repeat step from context-vigil's global config file (read-only).
- Draws nothing when the figures or config are missing.

Surfaces: the band is raised on **terminal and desktop only**; the phone gets
the Stop notice (verified, §2). **Where the person last spoke from** decides
whether the band is worth raising: the mod records the `origin.kind` of each
`prompt.submit` / `command.run` (`composer` = typed at the terminal, `bridge` =
Remote Control from a phone or web client). When the last human message came
over `bridge`, no band is raised — the person is not at the terminal, and the
Stop notice already reached them. (`$.session.surfaces()` cannot be used for
this: with a phone connected over Remote Control it reported only
`[terminal]` and no `session.attach` fired — prototype test, 2026-10-04.)

**Considered and dropped: an `$.ui.ask` card for the phone.** Prototyped and
shown to render on the phone, but it is the engine's AskUserQuestion dialog:
while open it takes the prompt's place, so anything typed into the pane lands
in it — auto mode's `/clear` + Enter, the resume kick, last light's prompt, the
person's queued messages. With the Stop notice already reaching the phone (a
"hand over" reply is one message), the card's only gain is a tap instead of a
word, at the cost of blocking input.

### Install

A fourth install question (§4), default **no**. Yes adds the mod folder to
`env.CLAUDE_CODE_PLUGIN_DIRS` in the user `settings.json` (the only settings
file Claude Code reads it from), appended with the platform path separator,
preserving any existing entries; uninstall removes only our path. The same
settings.json protections apply (structural preview, atomic write, our entry
only). `status` reports `vigil bar: on|off` and whether the folder is listed.
Requires a Claude Code build with mods (the API this spec was written against
is 2.1.287); `status` says so when the bar is on but the build has no mods.

### Testing

`claude plugin validate` and `claude plugin test` on the mod: band drawn when
due, not when below threshold, not while `hasSurvey`, not when the last human
prompt's origin was `bridge`; [1] submits the prompt as user; [2]/[0] hide as
specified; mounted on `terminal` and `desktop`. Installer tests for the
`CLAUDE_CODE_PLUGIN_DIRS` edit and its removal.

---

## 3a. Safety net: never type into a dialog

Every path that types into a pane with `tmux send-keys` — auto mode's `/clear`
(Stop), the resume kick (SessionStart), last light's prompt — first captures
the pane and refuses to type when any menu or dialog is showing (a `❯` cursor
on an option row: permission prompts, AskUserQuestion, the trust prompt, the
rating survey). On refusal:

- `/clear`: fall back to the no-tmux path — the `systemMessage` "📜 Handover
  saved — type /clear …" — and leave the clear flag so the handover still loads;
- resume kick: skip; the handover is already in context from SessionStart;
- last light: do not fire this tick (the gate re-checks next tick).

The check is one shared function (the same one last light's gate 8 uses), with
tests on captured panes of each dialog kind.

---

## 3b. Install questions as cards

Install is driven by the agent, which has the **AskUserQuestion** tool — the
engine's own question card, drawn in the terminal, the desktop app and the
phone alike. Blocking is fine here: install is interactive by nature.

- `install --questions-json` prints the questions in AskUserQuestion's exact
  input shape (≤ 4 questions per card; `header` ≤ 12 chars; 2–4 options; the
  default first and marked "(Recommended)"). The strings live in code (§4), so
  SKILL.md never paraphrases them.
- **Card 1** (always): 🎚️ Threshold · 🖥️ Launcher · 🌅 Last light · 🎛️ Vigil bar
  (the bar question only when the Claude Code build supports mods; otherwise
  the card has three).
- **Card 2** (only when needed): 🌅 last-light threshold (if On), and the
  existing ♾️ Always confirmation (if chosen).
- Each option maps to exactly one `install --yes` flag value; "Other" free text
  is accepted only for thresholds (validated 1–95).
- SKILL.md: ask with AskUserQuestion using the JSON as printed; where the tool
  is unavailable (`claude -p`), ask the same questions in plain text.
- `last-light on` (§1 Setup) uses the same mechanism for its threshold card.

Tests: the JSON validates against the card limits; every option round-trips to
a valid flag; the bar question is absent when mods are unsupported.

---

## 4. Voice: user-facing strings

Model-facing text (nudges, the last-light prompt, injected contexts) stays
plain. User-facing text gets an emoji lead and a lighter tone. Final wording is
tuned in review; these are the starting strings:

| Where | Text |
|---|---|
| Stop notice | `🕯️ context-vigil · context at {pct}% (threshold {threshold}%) · say "hand over" to pass the torch 🔥 — or keep going 🚀` |
| Stop notice, repeat | `🕯️ context-vigil · now at {pct}% ⬆️ · say "hand over" whenever you're ready 📜` |
| Handover saved, no tmux | `📜 Handover saved — type /clear, then send any message (e.g. "go") to pick it back up ✨ (run Claude inside tmux for hands-free handovers 🤖)` |
| Last light, prepared | `🌅 Last light: a handover is ready 📜 — carry on as normal, or /clear to resume from it ✨` |
| Bar | `🕯️ context {pct}% · threshold {threshold}%` + `📜 Hand over now` / `⏰ Remind me at +{step}%` / `✖ Dismiss` |
| Card: threshold | header `🎚️ Threshold` · `At what context % should I tap you on the shoulder?` · `35% (Recommended)` / `25%` / `50%` (+ Other) |
| Card: launcher | header `🖥️ Launcher` · `How should Claude start for hands-free handovers?` · `🚀 On demand (Recommended)` / `♾️ Always` / `⏸ Not now` (descriptions carry the existing walkthrough) |
| Card: last light | header `🌅 Last light` · `Prepare a handover before an idle 1-hour cache goes cold 🧊?` · `Off (Recommended)` / `On` — description: `When you've stepped away with context ≥ 25% and the cache is 5 minutes from going cold, the agent prepares a handover. Nothing is cleared: come back, carry on, or /clear to resume ✨ Needs tmux.` |
| Card: last-light threshold | header `🎚️ Last light` · `At what context % should last light step in?` · `25% (Recommended)` / `35%` / `50%` (+ Other) |
| Card: vigil bar | header `🎛️ Vigil bar` · `Add a pop-up bar above the prompt when context crosses the threshold?` · `No (Recommended)` / `Yes` — description: `[1] hand over · [2] remind me later · [0] dismiss. Terminal and desktop; needs a Claude Code build with mods.` |
| status | `🕯️ installed` / `🌅 last light: on (25%)` / `🎛️ vigil bar: on` lines |

---

## Out of scope / future

- **The mod as last light's engine** (next iteration): `$.clock` timers and
  `$.prompt.submit` (which waits for idle, and whose `e.origin` tells plugin
  from user) would remove the tmux requirement, `send-keys` and pane-safety
  checks.
- An `$.ui.ask` card for the notice on the phone (prototyped, dropped — §3:
  it blocks input; the Stop notice already reaches the phone).
- Keeping the cache warm with keep-alive prompts (that *is* the loop).
- Last light for headless runs or the 5-minute TTL.
- A firing cap/fuse for last light (considered and dropped: it could block
  genuine use).
- Mid-turn nudges on every tool (assessed above and dropped).

---

## 5. Addendum (2026-10-04, owner decisions) — retiring the old vigil and census

Owner decisions taken while the plan was running. Implemented as plan tasks
13–16, after task 12.

### 5.1 Census parity

context-vigil's status-line store becomes a superset of the census plugin's, so
census can later be retired by repointing its readers (overseer dashboard,
chronicle) — that repointing is a follow-up card, not this branch.

- The store gains census's top-level **`limits`**: account rate-limit windows
  (`five_hour`, `seven_day`, …) hoisted out of each payload with census's exact
  rules — only a fresher window replaces a stored one ("higher % wins" within a
  window), windows whose `resets_at` has passed are dropped on read.
- New command **`context-vigil census read [--worktree CWD | --session ID |
  --limits]`** prints JSON in the census plugin's `read` shapes (same keys, same
  `{}` for nothing), so a reader can switch commands without code changes.
- Entry shape stays census's (`worktree_cwd, updated_at, active_at, branch,
  tmux_pane, payload`); context-vigil's extra keys are kept and ignored by readers.

### 5.2 Activation: everywhere by default, opt-out per repo

- Global **`activation`**: `everywhere` (default) | `opt-in`. Global only.
- Per-worktree **`watch`**: `on` | `off`, set by **`context-vigil on`** /
  **`context-vigil off`** in a repo (stored in the worktree config under the
  data root — nothing is written inside the repository).
- Watched = the worktree's `watch` if set, else `activation == everywhere`.
- Unwatched: no nudge, no end-of-turn notice, no last light, no auto `/clear`
  dispatch for a nudge-less session. Explicit requests still work: the user can
  always say "hand over" (`handover`, `/ho`), and a pending handover is still
  loaded on `/clear`.
- `status` shows `watching: yes|no (why)`.

### 5.3 Free-form handovers: fill the blanks, never refuse

`handover --file` accepts any notes. Before assembling:

- text before the first recognised heading is kept under `## Notes`;
- a missing or empty `## Failed Attempts` becomes `None recorded.`;
- a missing or empty `## Next Step` becomes `Not stated — ask the user what to
  do next before acting.`;
- a `## Next Step` holding several actions is kept, prefixed with
  `(Several steps were listed — confirm with the user which comes first.)`;
- the command prints one extra line naming what it filled (e.g.
  `filled: Failed Attempts, Next Step`) so the agent can improve the notes.

`handover --file -` reads the notes from stdin (overseer's piped rollup).

### 5.4 Short commands: `/ho` and `/handoff`

Install writes two user commands, `$CLAUDE_CONFIG_DIR/commands/ho.md` and
`handoff.md`, each a short prompt telling the agent to hand over now via
context-vigil (finish or hold in-flight work first; `notes-path`; fill it;
`handover --file`), with `$ARGUMENTS` folded into the notes. Each file carries a
managed marker; install refuses (leaves alone, reports by path) a file of that
name it did not write; uninstall removes only its own. The dry run lists both.

### 5.5 Not in this branch

- Repointing overseer (orchestrate skill + dashboard gauge/threshold, which
  shell the old vigil CLI) and census readers — follow-up card.
- Removing `five-hour-guard.py` (registered in the work account's
  `~/.claude/settings.json`, reading the personal census store): Claude Code's
  built-in "Continue automatically at usage limit" replaces it; removal awaits
  the owner's go-ahead.
