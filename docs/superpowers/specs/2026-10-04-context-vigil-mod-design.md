# context-vigil-mod: context handover as a Claude Code mod

Date: 2026-10-04 · Branch: `feat/context-vigil-mod` · Sibling of classic
context-vigil (branch `feat/context-vigil`, tag `context-vigil-v1`, spec
`2026-10-04-context-vigil-last-light-design.md` on that branch).

A second, independent implementation of context-vigil built on the Claude Code
mod API (function hooks) instead of the status line, census, Python CLI and
`tmux send-keys`. It runs **side by side** with classic — personal account on
the mod, work account on classic — so the two can be compared on real work
before either is retired. Classic is not changed by this work.

**Out of scope (parked by the owner):** replacing the status line with a mod
band. The only band in v1 is the vigil bar (§3).

---

## 0. Why — the measurements

Taken on 2026-10-04 with a throwaway probe mod (`vigil-probe`) and a timed run
of the live status-line script, both on this machine.

| Path | Cost |
|---|---|
| `~/.claude/statusline-command.sh` (one refresh) | ≈ 320 ms, 60+ processes (15 `jq`, 5 `git`, ~67 subshells, census ingest) |
| Status-line refreshes, personal account | 175 runs in 6 min across ~20 mostly idle sessions (every 60 s each, plus every message update) |
| `$.session.usage()` (context, rate limits, cost) | 0.14–0.18 ms |
| `$.session.model()` / `cwd()` / `id()` | 0.03–0.07 ms |
| `$.session.repo()` | 0.4–0.7 ms |
| Three `git` questions via `$.process.run`, in parallel | ≈ 33 ms (≈ 45–66 ms sequential) |

The mod is pushed what changed (`session.measure`, `turn.complete`, classic
events) instead of polling, costs nothing while idle, and git is the only
non-trivial cost — paid only when something can have changed.

**The tmux-free handover spike passed** (throwaway mod `handover-spike`):
`$.command.run({ command: 'clear' })` from a `$.clock.after` timer runs
`/clear`; the mod survives it (same process, new session id, no
`session.start`); `classic.SessionStart` with `source: 'clear'` injects the
handover as `additionalContext`; `$.prompt.submit` resumes. Verified in tmux,
in a plain terminal, and driven from a Remote Control phone. `$.prompt.read()`
sees a draft in the **terminal's** prompt box and deferral works there; a
draft typed on the phone is **not** visible to it (§2, Remote Control).

**Approach: B — a pure TypeScript rewrite.** No Python, no CLI, no tmux, no
status-line dependency. Nothing is carried over from classic just because it
exists; classic's behaviour is the reference, not its code.

---

## 1. Architecture

**Location and name.** A mod plugin at `plugins/context-vigil-mod/`:
`.claude-plugin/plugin.json`, `hooks/hooks.json` (`{ "modules":
["./register.ts"] }`), `hooks/register.ts`, pure core modules beside it,
`types/index.d.ts` (the `$.state` contract), and `*.test.ts`. The plugin name
lives in one constant (`NAME` in `core/name.ts`) plus `plugin.json`, so a
rename is a two-line change.

**Shape: pure core, effectful shell.** The mod validator lets `$` be passed
only to functions declared in the hooks file itself, so the split is forced
and deliberate:

- **`hooks/register.ts` — the shell.** The only file that touches `$`. It
  subscribes to events, gathers facts (origins, times, context %, prompt box,
  limits), calls the core, and carries out the **intents** the core returns
  (`clear`, `inject`, `submit`, `showBar`, `notice`, `writeFile`, `log`,
  `ask`). It holds no decisions of its own.
- **`core/*.ts` — pure functions, facts in, decisions out.** Each is unit
  tested alone and imports nothing from `claude-code` at run time:
  - `arming.ts` — origin classification and the engagement state machine (§2).
  - `handover.ts` — thresholds and repeat step, the handover document format,
    the snapshot, the resume text (§3).
  - `last-light.ts` — warm-cache timer arithmetic, fire conditions, the
    return-and-ask choice, the loop guard (§4).
  - `limits.ts` — the limit latch and the 7-day / spend early stop (§5).
  - `surfaces.ts` — the Remote Control rules: first-RC ask, countdown,
    recent-bridge holdback (§2).
  - `setup.ts` — the setup steps, each with its options and "Tell me more" (§6).
  - `voice.ts` — every user-facing string, emoji-led, in one place.
  - `eventlog.ts` — the dashboard event record shape and serialisation.

**State — all per account.**

| Where | What | Lifetime |
|---|---|---|
| `$.state` (`context-vigil-mod` contract) | live session values: armed state, last human / agent activity times, last human origin, pending handover id, bar visibility, latch | the session; survives hot reloads |
| `$.store` | settings (§6), "RC auto-clear answered", pending handover across a process restart | across sessions; a JSON file under the account's config dir |
| `$CLAUDE_CONFIG_DIR/context-vigil-mod/` | `handovers/<session>-<n>.md`, `events/<yyyy-mm-dd>.jsonl` | durable; read by humans and dashboards |

`$CLAUDE_CONFIG_DIR` is read once at `session.start` via
`$.env.get("CLAUDE_CONFIG_DIR")`, falling back to `$HOME/.claude`. Nothing is
ever written under another account's directory.

**Dashboard event log (in v1).** One JSON object per line, one file per day:
`{ ts, session, kind, ...fields }`. Kinds: `arm`, `disarm`, `threshold`,
`bar`, `handover.requested`, `handover.written`, `guard.wait`, `clear`,
`resume`, `last_light.fired`, `last_light.choice`, `limit.latched`,
`limit.cleared`, `limit.early_stop`, `rc.answer`, `setup`. `$.fs.write`
writes whole files, so the shell keeps the day's lines in memory and rewrites
the day file (bounded: a day of one session is small). Every kind carries the
reason and the facts that decided it, so the dashboard can explain each
action and the side-by-side comparison has like-for-like data.

---

## 2. Who is driving — arming and engagement

Every moment is in exactly one of three states; each feature has one home.

| You | The agent | State | At the context threshold |
|---|---|---|---|
| engaged | anything | **attended** | nudge only (bar in the terminal, notice on the phone); never clears |
| idle ≥ idle window | working | **auto armed** | hands over, clears, resumes by itself (§3) |
| idle | idle | **last-light territory** | no clear; before the cache goes cold, write the handover only (§4) |

**Engaged** — any of these within the idle window (default **30 min**, set in
setup):

- a prompt whose origin is `composer` (typed or queued at the terminal),
  `bridge` (Remote Control — phone or web) or `slack-ping`;
- a slash command run by the person (`command.run` with a person origin);
- an edit in the terminal's prompt box (`prompt.edit`), or a non-empty draft
  there (`prompt.read`).

**Working** — a `turn.step` or `turn.complete` within the last **2 min**. This
covers one long self-driven turn as well as turns started by
`task-notification`, `scheduled-trigger` (/loop, wakeups, routines), `peer`,
`peer-send-message`, `coordinator`, `observer` or `plugin`.

**Transitions.** Any engaged signal disarms auto mode at once and restarts the
idle clock. Auto mode arms on the first event after the idle window has
elapsed while the agent is working. A session whose prompts come from `sdk`
(`claude -p`, the Agent SDK) is unattended from its first turn. Auto mode as a
whole is off unless enabled in setup (§6).

**Remote Control.** "The person is on the phone" means the **origin of the
last human prompt was `bridge`**. `$.session.surfaces()` is not used: classic's
prototype showed it reports only `[terminal]` with a phone attached, and no
`session.attach` fired.

- **First RC session:** the first time auto mode would arm while the last
  human origin is `bridge`, the mod asks once — allow auto-clear in Remote
  Control sessions? (options + "Tell me more", §6). The answer is stored in
  `$.store`. Until answered, or if declined, RC sessions never auto-clear: the
  handover is written and a notice offers `/clear`.
- **When allowed, two safety nets stay on,** because phone typing is invisible
  to the mod:
  - a **30 s countdown** shown as a notice (and in the bar where drawn) with a
    Cancel; any `prompt.submit` during the countdown cancels it;
  - **no clear within 2 min** of the last `bridge` prompt.

Every arm, disarm and RC answer is logged with its reason, the idle time and
the deciding origin.

Two guards on an unattended (auto) handover, both learned from a live smoke run:
- **Attended at clear time.** Mode is re-checked at the moment of clearing, not
  only when the handover began. If the session became attended meanwhile, the
  clear is skipped (`clear.skipped`, reason `attended`), the handover is kept
  and the person is told. Requested handovers are attended by definition.
- **Baseline growth.** An auto threshold handover fires only once context has
  grown at least one `step` above the session's baseline (its first context
  reading; a `/clear` starts a new one). Otherwise `guard.baseline` is logged.
  Attended nudges are unchanged.

---

## 3. The handover

**Triggers.**

- **Context threshold:** first at **35%**, then every **+5%** (both in setup).
  Context comes from `session.measure` (`context.percent`).
- **On request:** the bar's 1, or `/vho` / `/vhandoff` (prefixed so they
  never collide with classic's `/ho` / `/handoff`).

**By state (§2):**

- **Attended** — a nudge. In the terminal the **vigil bar** (an `AbovePrompt`
  band) appears, drawn survey-style like Claude Code's feedback bar:
  `🕯️ context 41% · threshold 35%   1: 📜 Hand over now · 2: ⏰ Remind me at +5% · 0: ✖ Dismiss`
  The buttons are `Button`s with `hotkey="1"` / `"2"` / `"0"` and `plain`, so
  a bare digit typed into an **empty** prompt box presses them. 1 starts the
  handover; 2 hides the bar until the next step; 0 hides it until the next
  handover or `/clear`.
  **Consequence:** while the bar is up, a leading bare digit is captured by
  it. So the bar is never always-on: it shows **only from the threshold
  crossing until 1, 2 or 0 is chosen or a handover happens**.
  **Survey.** The bar yields whenever `e.props.hasSurvey` is true: Claude
  Code's feedback survey holds the band, and its digits belong to the survey
  because our Buttons are not mounted. The bar's state (pending / shown)
  lives in `$.state`, so when the survey closes the bar re-appears by itself;
  a threshold crossing during a survey shows the bar after it.
  (Option noted, not required: the band's `isWorking` prop could limit the
  bar to between turns; the owner did not ask for it.)
  (Verified live in a demo mod: the band renders in the terminal, `e.surface`
  `"terminal"`.)
  It is not raised when the last human origin is `bridge`; the phone gets an
  end-of-turn notice instead. With the bar switched off in setup (§6), the
  terminal also gets only the notice. Nothing is cleared unless the person
  asks.
- **Auto armed** — the handover runs by itself.

**Steps.**

1. **Write.** The mod registers a tool, `vigil_handover`, via
   `$.tool.register`, with fields: `goal`, `state`, `decisions` (rulings and
   why), `next_step`, `open_questions`, `failed_attempts`, and `session_name`
   — the name the resuming session will carry (required; a few words saying
   what that session will work on). It submits a short
   instruction prompt (`$.prompt.submit`, origin `plugin`) asking the model to
   call it. Typed, validated input replaces classic's CLI-and-file fill.
2. **Save.** The shell adds the snapshot it already knows: cwd, branch, dirty
   files (cached git, refreshed only when stale — see below), files edited this
   session (tracked from `tool.call` on Edit/Write), context %. It writes
   `handovers/<session>-<n>.md` and records it pending in `$.state` and
   `$.store`.
3. **Clear.** `$.command.run({ command: 'clear' })` from a `$.clock.after`
   timer — never inside a hook the turn is waiting on — once the guards pass:
   the terminal prompt box is empty (`prompt.read`); the RC rules hold (§2);
   the limit latch is not set (§5). A failing guard waits and re-checks, and
   the person sees a notice for every wait.
4. **Inject and name.** `classic.SessionStart` with `source: 'clear'` returns
   the handover as `additionalContext`, and starts
   `$.command.run({ command: 'rename', args: <session_name> })` on a timer, so
   the new session carries the handover's name (prompt border, `/resume`,
   Remote Control). Every clear that consumes a pending handover is named —
   auto, requested, last light. A rejected rename is logged and noticed, never
   blocks the resume.
   **An existing name is kept.** `/clear` itself carries a session's name
   (`custom-title`) into the new session, so when the session was already
   named — by the person's `/rename` or by an earlier handover — the mod does
   not rename; only an unnamed session gets the handover's name. "Named" means
   the pre-clear transcript holds a `"type":"custom-title"` line (checked with
   `grep` via `$.process.run`, since `$.fs.read` refuses files over 4 MiB);
   Claude Code's own `ai-title` does not count. If the check cannot run, the
   mod does not rename (never overwrite a name it could not see). (Verified live 2026-10-04: a mod-run `/rename` right
   after a mod-run `/clear` writes the title; `sessionTitle` returned from
   `classic.SessionStart` on a clear does NOT.)
5. **Resume.** For auto mode and a requested handover, `$.prompt.submit` sends
   the resume prompt on a short timer after the clear, so work continues.

**Git, cheaply.** Branch / dirty / ahead are refreshed only when stale: after
`tool.call` on Edit, Write or Bash; at `turn.start`; and on `classic.FileChanged`
for `.git/HEAD` and `.git/index` (watched via `watchPaths` from
`classic.SessionStart`, which only takes effect for a freshly started
session). Bursts coalesce; the three `git` runs go in parallel on a
`$.clock.after` timer so no event waits on them (verified: hook returns in
1 ms).

**Failure paths — always visible.**

- The tool is not called within the turn → one retry, then a notice
  "📜 couldn't write a handover"; nothing is cleared.
- `/clear` rejected → notice; the handover stays pending.
- Process restart with a handover pending → it is in `$.store` and offered at
  the next session start.

Every step is logged: trigger, state, handover size, each guard wait, clear and
resume timings.

---

## 4. Last light (drafted from discussion — review)

Last light is the "nothing is happening, hand off now so tomorrow morning does
not pay a big cold cache" job. **It writes the handover only. It never
clears.**

**Why.** An idle session loses its 1-hour prompt cache when the TTL lapses;
the next prompt rewrites the whole context at the cache-write rate (2× input
on the 1-hour TTL, against 0.1× for a read). For a 400k-token context:
returning cold costs ≈ 800k input-equivalents; last light's warm write
(400k × 0.1 = 40k) plus a later resume over a ~10k handover (≈ 20k) costs
≈ 60k — about 92% less, if the person chooses the handover on return.

**Timer.** One `$.clock.after` per idle period, reset on every
`turn.complete`: fire at *last API activity + TTL − lead* (TTL 1 h; lead
300 s). If the TTL in effect is 5 min, last light is inactive.

**Fire conditions (all):** last light is on (§6); the session is in
last-light territory (you idle, agent idle — §2); context ≥ the last-light
threshold (default **25%**); no handover already pending; the limit latch is
not set; **armed** — a real human prompt (`composer`, `bridge`, `slack-ping`)
has arrived since the last fire.

**At fire:** submit the handover instruction (§3 step 1) and save (§3 step 2).
No clear, no resume.

**Loop guard.** Writing the handover is itself an API call that refreshes the
cache for another hour. Firing disarms last light; only a real human prompt
re-arms it. So an untouched session fires at most once.

**On return.** With a last-light handover pending and the cache past its
expiry, the person's next human prompt is held: the `prompt.submit` hook
answers `{ drop }` for it, keeps its text, and asks:
`🌅 A handover is ready — resume from it (cheap) or carry on with the full conversation (pays the cold cache)?`
"Resume" clears and injects (§3 steps 3–4) and then submits the held text as
the first prompt of the fresh session; "Carry on" submits the held text
unchanged into the existing conversation. Either way the held message is
never lost. The same path serves the terminal and the phone (`bridge`). An
edit in the terminal prompt box (`prompt.edit`) may raise the question
early, as a band, before the person sends. The choice is logged.

---

## 5. Limits (drafted from discussion — review)

**Latch.** `classic.StopFailure` with `error: 'rate_limit'`, or a
`session.measure` showing a window at or past its limit, sets the latch with
that window's `resetsAt`. While latched, the mod never clears and never
submits (built-in auto-continue owns the retry); the bar and notices show
`⏳ resumes HH:MM`. The latch clears after `resetsAt`, or when
`session.measure` shows the window has reset.

**Early stop for seven_day and spend_limit** (folding in the behaviour of
`~/.claude-personal/census/five-hour-guard.py`, which itself stays untouched):
when limits are on (§6) and a **watched** window (configured; default both
`seven_day` and `spend_limit`) reaches the **configured trigger %** (default
95%; 90 / 95 / 98 or any value via Other), once per window
(keyed on its `resetsAt`): write a handover (§3 steps 1–2), show a notice, and
arrange the resume for after the reset (a `$.clock.after` to `resetsAt` + 5
min, re-armed in ≤ 1 h hops, which submits the resume prompt if the session
is still open). The 5-hour window is left to Claude Code's built-in graceful
wrap-up and auto-continue.

---

## 6. Setup (drafted from discussion — review)

Every step has the same shape: **its options + "Tell me more"**. "Tell me
more" explains the step (what it does, the trade-off, the default) and then
re-presents the same options.

| Step | Options | Default |
|---|---|---|
| 🎚️ Nudge at | 25% · 35% · 50% · Tell me more | 35% (+5% steps) |
| 🎛️ Vigil bar | On · Off · Tell me more | On |
| 🤖 Auto mode | Off · On · Tell me more | Off |
| ⏱️ Idle window (asked if auto mode on) | 15 · 30 · 60 min · Tell me more | 30 min |
| 🌅 Last light | Off · On · Tell me more | Off |
| 🌅 Threshold (asked if last light on) | 25% · 35% · 50% · Tell me more | 25% |
| ⏳ Limits | On · Off · Tell me more | On |
| ⏳ Trigger % (asked if limits on) | 90% · 95% (Recommended) · 98% · Other · Tell me more | 95% |
| ⏳ Windows (asked if limits on; multiSelect) | seven_day · spend_limit · Tell me more | both |
| 📱 RC auto-clear (asked at the first RC session, §2) | No · Yes · Tell me more | No |

Settings live in `$.store` — per account. Headers fit AskUserQuestion's
12-UTF-16-unit limit.

**Changing a setting later:** `/vsetup` re-runs the whole flow; `/vsetup
<step>` (e.g. `/vsetup bar`, `/vsetup limits` — on/off, trigger % and
windows together) re-asks one step. There is no separate config
command.

**Vigil bar off:** no band is ever drawn; the end-of-turn notice still fires
at the threshold (and every step after), so the nudge is never lost. The
default is **On** — classic defaulted to "No (Recommended)", but the owner has
since seen the bar and likes it.

**How the cards are shown:** through the model's AskUserQuestion, prompted by
the mod at setup (`/vsetup`) and at the first RC session. `$.ui.ask` is not
used: classic found it takes the prompt's place while open, so queued input
lands in it. A "Tell me more" answer is answered by re-asking the same
question with the explanation in the question text.

---

## 7. Coexistence with classic (drafted from discussion — review)

- **Distinct names everywhere:** plugin `context-vigil-mod`; commands `/vho`,
  `/vhandoff`, `/vsetup`; tool `vigil_handover`; state and files under
  `context-vigil-mod/` (classic uses `.vigil/`); its own `$.store`.
- **User-level install only:** the plugin folder is listed in
  `env.CLAUDE_CODE_PLUGIN_DIRS` in the account's own `settings.json` (under
  `$CLAUDE_CONFIG_DIR`), preserving existing entries. Never a repo's
  `.claude/settings.json`, which both accounts would read.
- **Switching an account to the mod is a deliberate install step:** uninstall
  classic's hooks from that account first (classic's own uninstall), then
  install the mod. The interlock below makes the mod stand down while classic
  is installed, so installing it alongside does nothing but say so.
- **Interlock — TEMPORARY.** It exists only for the side-by-side run. Once
  the mod variant is proven (side-by-side run done, owner picks the mod), a
  cleanup step removes the interlock and all classic-detection code, and
  classic is retired.
  **How it works (one-sided in v1, since classic is not changed).** At
  `session.start` and before every clear, the mod checks whether classic is
  active for this session — classic's hooks registered in the account's
  `settings.json`, or a classic session record for this session id under
  `$CLAUDE_CONFIG_DIR/context-vigil/sessions/` — and, if so, stands down: no arming, no clearing, no
  bar, and a one-line notice saying why. The mod records its own activity in
  its event log and `$.state`, so a later classic change can check the other
  way.

---

## 8. Testing (drafted from discussion — review)

- **TDD throughout.** Every core module is written test-first with
  `*.test.ts`, run by `claude plugin test plugins/context-vigil-mod`.
- **Core:** pure functions with table tests — origin classification, every
  §2 transition, threshold and repeat step, handover formatting, last-light
  arithmetic and every fire condition, the loop guard, latch set/clear, early
  stop once per window, RC countdown and holdback, setup step flow including
  "Tell me more".
- **Shell:** driven with the mock engine and mock clock from the typings —
  event in, intents carried out, `$` calls asserted; `$.clock` advanced
  instead of waiting. Includes the bar: shown only from crossing to choice,
  hotkeys 1/2/0, and **"yields to survey, returns after"** (`hasSurvey` true
  → `next(e)`; false again → the bar draws from `$.state` with no new
  crossing needed; a crossing during the survey shows after it).
- **Gates:** `claude plugin validate`, `tsc -p plugins/context-vigil-mod`,
  `claude plugin test`.
- **Live smokes** (owner-run where the auto-mode classifier forbids driving a
  session): handover in a terminal; handover driven from a phone; last light
  with a short TTL override; a forced `rate_limit` StopFailure.
- **Isolation:** per the repo CLAUDE.md, tests never touch a real config dir —
  file writes go to a temp directory supplied by the mock engine.

---

## 9. Verify early

1. Does a notice row added with `$.session.append` reach the phone, as
   classic's Stop `systemMessage` does? If not, find the mod-side equivalent
   before building §2–§4 notices on it.
2. Is a `$.tool.register` tool offered to the model from the next turn, and
   does a plugin-origin prompt reliably get it called?
3. Known: `watchPaths` returned from `classic.SessionStart` take effect only
   for a freshly started session, not on a mod reload.
4. Does `classic.SessionStart` fire with `source: 'clear'` for a `/clear` the
   mod itself ran? (Seen in the spike — confirm in the shell tests.)
