# context-vigil-mod: reference

Deep detail for [context-vigil-mod](README.md): guards, failure paths, files, interlock, Windows and verification. The README has the quick start, commands and settings.

## What it is

Context handover as a Claude Code mod: a pure-TypeScript set of function hooks. No tmux, no status line, no Python CLI. It watches how full the context window is, nudges you, and (when you are away) hands over, `/clear`s in-process and resumes from the handover.

## Side by side with classic

It is a second implementation of context-vigil (the "classic" tmux + status-line plugin). Classic is untouched. Distinct names everywhere (`/vho` not `/ho`, `vigil_handover`, files under `context-vigil-mod/`), and a temporary interlock (below) makes the mod stand down wherever classic is installed.

## Install details

**Uninstall classic's hooks first** (classic's own uninstall) -- the script refuses otherwise. It lists this folder in `env.CLAUDE_CODE_PLUGIN_DIRS` in your user `settings.json` (`$CLAUDE_CONFIG_DIR`, else `~/.claude`), never a repo's. Then start a **new session** and run `/vigil-setup`.

## Command details

`/vigil-handover`, or `/vho` for short, hands over now.

`/vigil-overrides [add|rm|check]` sets thresholds per model, window size or both. Bare (or `check`) lists the overrides in the order they are tried, what this session gets and from which override, and any faults or ambiguity. `add` asks for an override for the session you are in. `rm model=… window=…` (either or both) takes one out. See **Overrides** below.

- **Plain words.** A short message (12 words or fewer) from you that plainly asks for a handover -- "handover", "do a handover", "hand this off", "time for a handover", "can you do a handover?" -- is not sent to the model: the mod drops it with `📜 Handing over — as /vho` and runs exactly what `/vho` runs (same standdown, latch and in-flight notices). This applies only while the mod is active: when classic is installed and the mod stands down, the words go to the model as usual. Questions and talk about handovers ("how does the handover work", "fix the handover bug", "don't hand over yet") go through untouched, as does anything from a plugin; a last-light hold on your return is checked first.
- **Looser net.** If your latest message mentioned a handover at all (`handover`, `hand over`, `handoff`, ...) and the model then calls `vigil_handover` without the mod having asked, the call counts as asked for: it clears and resumes as `/vho` does. The mention is session state, wiped by a `/clear`, and spent by the call. The mention does not count while the mod stands down. Without a mention, an unrequested call is still the model volunteering: saved, never cleared by itself, and you are asked what to do with it (see **A handover nobody asked for** below). The tool's description tells the model to write a handover only through the tool, never as an ad-hoc file or summary.

- `/vigil-setup [nudge|bar|auto|last-light|limits|rc]` -- the whole setup flow, or one step. `limits` covers on/off, trigger % and windows together. The mod asks each step itself in a dialog (`$.ui.ask`), one at a time: nothing is sent to the model and no prompt appears in the conversation. Options are labels only, the recommended one marked `(Recommended)`; **Tell me more** re-asks the step with its explanation. Dismissing a dialog stops setup and keeps what was already answered.

## Overrides

Per-model and per-window thresholds live in `<config dir>/context-vigil-mod/overrides.json`, yours to edit by hand or through `/vigil-overrides add`. When the file is missing it is written with the default override, so it is there to see:

```json
{
  "overrides": [
    { "window": 200000, "nudgeAt": 70 },
    { "model": "opus", "window": 1000000, "nudgeAt": 25, "step": 10 },
    { "model": "haiku", "nudgeAt": 80, "lastLightAt": 50 }
  ]
}
```

An override has a `model`, a `window` or both, and sets any of `nudgeAt`, `step` and `lastLightAt`. Each value comes from the most specific matching override that sets it, field by field; `/vigil-setup` values are the fallback beneath them all. Most specific first:

1. `model` and `window` -- the longer model pattern first (`opus5.5` before `opus`)
2. `window` only -- any model on that window
3. `model` only -- that model on any window
4. the `/vigil-setup` values

A model pattern is a family and at most a version: `opus` takes every Opus, `opus5` every Opus 5, `opus5.5` (or `opus-5-5`) only Opus 5.5. A window is a whole number of tokens, matched exactly. When a window override and a model override both match a session and both set the same field (whatever their values), the window wins and a notice says so once per session, naming the model+window override that would settle it. The file is checked whenever a threshold is decided: a fault in an override (an unknown key, a bad pattern, a duplicate key) is told once, naming the override, and only that override is ignored. A file that is not valid JSON, or not `{ "overrides": [ … ] }`, names no override: it is told once and the last good read stays in force (the default override if there was none).

**From 0.1.3:** overrides set with the old `/vsetup models` (kept in the settings store) move into `overrides.json` at the next session start, once: `[1m]` becomes `window=1M`, a family such as `opus` a model pattern, `opus-5-5[1m]` both. One already in the file for the same key stands; a pattern that has no equivalent here is named in the notice and not carried over.

The threshold reads the main session's own model and context window from the engine's measure, which fires after main-thread turns only: a subagent's tokens and its smaller window never move it, so a subagent cannot trip a handover.

Settings are per account (`$.store`) and re-read before every decision that matters, so a change made in one session reaches the others. Defaults: nudge 35% (+5% steps), with one default override `window=200k → 70%`, bar On, auto Off, idle window 30 min (15, 30 or 60), last light On (writes its handover only at 25%+ context), limits On (98%, `seven_day` + `spend_limit`; `five_hour` is opt-in), RC auto-clear unanswered (follows auto mode, with the phone safeguards: a 30 s countdown first, nothing within 2 min of your last phone message).

## Three states

Every moment is in exactly one:

| You | The agent | State | At the context threshold |
|---|---|---|---|
| engaged | anything | **attended** | nudge only: with the bar On, the bar in the terminal or a dialog on Remote Control (the phone); with it Off, a terminal toast and log line only; never clears |
| idle >= idle window | working | **auto armed** | with auto mode On (it defaults to Off), hands over, clears and resumes by itself; the normal guards still apply |
| idle | idle | **last-light territory** | no clear; before the cache goes cold, write the handover only |

*Engaged* = a `composer`, `bridge` (Remote Control) or `slack-ping` prompt, a slash command you ran, an answer to one of the mod's questions, a bar button press, or a prompt-box edit/draft, within the idle window. *Working* = agent activity within the last 2 min. Auto mode is off until enabled in `/vigil-setup auto`. `sdk` sessions (`claude -p`) are unattended from the first turn. An `unclassified`, `channel` or `auto-continuation` prompt disarms auto mode but counts for nothing else.

## The handover

The mod registers a `vigil_handover` tool and asks the model to call it. For a threshold or requested handover it asks for the call at the next sensible stopping point (not mid-edit) and the tool result tells the model to stop: the clear follows when the turn ends. While that clear is pending, prompts from other sessions, schedules and background tasks are held (not run) and carried into the resume under "Sent during handover", so they cannot start a turn the clear would wait behind; the person's own prompts are untouched. If the clear then parks (cancelled, skipped, rejected, latched), the held prompts are submitted back to the live session instead. Required fields: `goal`, `state`, `next_step` and `session_name`; optional: `decisions`, `open_questions`, `failed_attempts`, `standing`, `standing_retire`. The mod adds a snapshot (cwd, branch, dirty files, files edited, context %) and saves `handovers/<session>-<n>.md`. It then clears (only when the prompt box is empty, the RC rules hold and no limit latch is set; every wait shows a notice) and submits the resume prompt into the fresh session with the handover itself in its text, the saved path as a reference (nothing is injected: no `SessionStart` reaches a mod an organization does not list, PROBES section 16; and the model is not asked to read the file, since a read outside the project can stop on a permission prompt nobody is there to answer). If you type an ordinary prompt while the resume is still waiting to go out, your message wins and carries the handover instead, once (a slash command does neither: its text is not rewritten, and the resume stays queued and goes out after it); a message the mod drops (a plain-words handover request, a last-light hold) sends the resume on its own. A `/clear` you run yourself picks up a saved handover the same way; the automatic resume is sent only when no turn has run since the handover was written and no usage limit is in force — otherwise a notice names the handover file and asks you where to pick up (held text of your own is still sent, with the handover in it). What happened after the handover was written (your prompts, the assistant's text, one `→ tool: input` line per tool call; at most 20 messages and about 6 KB, newest kept) is read from the old transcript and carried in the resume message as "Since this handover was written"; up to 20 messages it counts as fresh and the resume is sent, over 20 it stays stale. An unreadable transcript falls back to the turn rule. A clear the mod itself issued is judged when it is issued: turns that finish while it is queued behind the running turn do not make it stale.

**Standing orders.** Rules and facts that hold for the whole chain of sessions ("never cd into worktrees", "PR bodies end with the link") go in `standing`, rendered right after the goal. The mod, not the model, carries them forward: the list lives in `$.store` (`standing:<session>`) and moves to the successor session on the clear. Each handover copies the previous list verbatim and appends the model's new items (deduplicated); the model gives only new ones. An item is retired only by naming it in `standing_retire`; each retirement (and any name that matched nothing) is listed in the handover under "Standing orders retired" and in the tool result. Past 40 items or 4 KB (UTF-8 bytes) the tool result warns; nothing is dropped. A `/clear` you run yourself with no handover starts a fresh chain.

**Sent during handover.** A prompt you type while the handover is being written (after it was asked for) or after it is saved and before the clear would otherwise be lost: the handover cannot mention what it did not see. The mod's prompt hook keeps each such prompt (human origin only: not the handover request, not plugin prompts, not `/` commands; at most 10) and the resume message repeats them verbatim under "Sent during handover", to be answered first. On the paths with no automatic resume a notice shows them instead ("📜 Not carried into the new session"), so none is dropped silently.

**Session naming.** Just before the mod's own clear, a **named** session is renamed `Archive: <its name>`, so `/resume` tells each old transcript from the session that carries on; the pending handover records the name first (if that record cannot be saved, nothing is archived). `/clear` carries the archive name across, and a mod-run `/rename` gives the new session its name back. Only a name the mod archived itself is given back: a name that already starts with `Archive: ` (yours, or an old archive you resumed) is never archived again (no `Archive: Archive: ...`) and is carried to the new session unchanged. An **unnamed** session is not archived (nothing else bears its name, and a name once given cannot be removed if the clear is then refused); after the clear it is renamed to the handover's `session_name`. All renames are mod-run `/rename`s (prompt border, `/resume`, Remote Control). Only a transcript `custom-title` counts as a name; Claude Code's own auto title does not. A failed archive rename is a notice and the handover goes on. If the rename back fails, the new session stays `Archive: <name>` (with a notice) and is marked in the account store; its next handover by the mod, after a `/resume`, a restart or a `/clear` of your own (the mark moves with the name), gives its successor the name back. A mark is pruned 14 days after it was set or last moved. A refused clear puts the original name back. If the name cannot be read, nothing is renamed. A `/clear` you run yourself archives nothing; the new session keeps the carried name.

State that must cross a clear (pending handover, limit latch) lives in `$.store`, because `$.state` is wiped by every `/clear` (PROBES section 9).

**How a clear or resume is seen.** Only native events are used, so the mod works the same where an organization manages Claude Code (PROBES section 16): a `/clear` or `/resume` is `session.end` (reason `clear` or `resume`, the old id) followed, 100-600 ms later, by a new `$.session.id()` with `$.state` wiped. The end hook returns at once; a timer polls the id every 50 ms for the first second, then every 250 ms, and, when it moves, runs one handler (clear: resume from the handover; resume: rebind and offer). An id that has not moved after 5 s is logged (`guard.wait` `session-id-unmoved`) and the handler runs on the old id; if it moves later, the drift guard moves the standing orders and stranded mark to it (`session-id-late`) and leaves the resume alone. A drift guard on every `prompt.submit` and main-thread `turn.start` catches a change no end announced (a fork) and handles it as a resume; a change is handled once whichever trigger sees it first. The transcript path is derived (`<config>/projects/<cwd>/<id>.jsonl`) from the cwd the session was bound in (EnterWorktree or a cd moves the live cwd, not the transcript; the live cwd is tried only when no file is there), and the name carried by a `/clear` is read from the old transcript's last title.

## The vigil bar

Terminal only. Shown from the threshold crossing until you choose or a handover happens:
`🕯️ context 41% · threshold 35%   📜 Hand over now · ⏰ Remind me at 45% · ✖ Dismiss`, with hotkeys `1`, `2`, `0` on the three buttons (the label names the absolute next step).

- `1` starts a handover; `2` hides it until the next step; `0` hides it silently until a `/clear`.
- On the phone (last prompt from Remote Control) the bar never arrives, so the same three choices come as a dialog instead ("🕯️ Context is at 41%. Hand over now?"), which raises Remote Control's "action required" push. A dismissed dialog counts as Remind me; one dialog at a time.
- A bare digit typed into an **empty** prompt box presses a button, so the bar is threshold-only, never always-on.
- It **yields to the feedback survey** (`hasSurvey`) and returns after it.
- Off via `/vigil-setup bar`: a toast and log line (fired from the context measure) still mark the threshold and every step after. Notices (`ui.toast`/`ui.log`) show in the terminal only: they do not reach Remote Control yet (PROBES.md §1).

## Guards and failure paths

- **Pause.** `/vigil-pause` pauses the mod for this process, across `/clear`: no nudge, bar, phone dialog or threshold handover (a waiting threshold clear stands down and its handover stays as an offer; held prompts go back to the session). `/vho`, `/vigil-handover`, plain-words requests, last light and limit stops are explicit or write-only and keep working. The band shows "⏸️ vigil paused" when nothing else has it. `/vigil-resume` turns it back on and undoes a bar dismiss; past a threshold it shows the nudge at once. Events: `pause`, `unpause`, `paused.skip`.
- Draft guard: a clear waits while the terminal prompt box holds a draft, rechecked every 2 s. The band shows "⏸️ Auto-clear paused while you're typing" (the threshold bar wins if both are up), and the first wait for each handover asks once: **Clear and resume now** (the draft is taken out of the box, the clear goes, and the draft is sent as your message after the resume) or **Postpone N%** (the handover is dropped and the next one comes one step on). A dismissed dialog postpones. The dialog is asked the same on the phone, where it raises Remote Control's action-required push.
- If the model does not call `vigil_handover`, it is asked once more; then a "couldn't write a handover" notice appears and nothing clears. A request that is lost altogether expires after 10 idle minutes.
- **Your request holds until its clear.** A handover you started -- the bar's `1`, the phone dialog's Hand over now, `/vho`, `/vigil-handover`, plain words, or the dialog's Update it, then clear -- counts as asked for until its clear is issued, not just for the first save: a second save the same request produced while its clear waits (on a draft, say) still clears and resumes, from the newest file. It ends when the clear is issued, when you press Esc on the instruction turn, when the mod tells you the handover failed ("couldn't write a handover": no tool call after a retry, or the instruction refused), after 30 minutes, or with a `/clear` or `/resume`. A save after the clear was issued, while it is still queued, is told as a repeat: the one you asked for stays the one the clear resumes from.
- **A handover nobody asked for.** When the model saves a handover on its own, the mod asks in a dialog (it reaches the phone, like the threshold one): "📜 Handover saved, not requested — the model wrote one on its own (<path>). Use it?"
  - **📝 Update it, then clear** -- the model is asked for a fresh handover with what has happened since; that save counts as asked for, so it clears and resumes.
  - **🧹 Clear now** -- clears and resumes from the saved handover (the usual guards apply: a draft waits, and if turns have run since it was written the resume prompt is not sent automatically).
  - **✋ Leave it** -- saved, nothing cleared; `/vho` or `/clear` later still use it. A dismissed dialog or free text counts as Leave it.
  The dialog never holds up the tool call or the session; one is open at a time and a later save moves it on to the newer file. An answer about a handover that is no longer the latest (a clear, a `/resume` or a newer save in between) changes nothing and says so. Under the stand-down, the limit latch or an early stop's pending resume there is no dialog, only the notice, so a clear never spends what the stop saved. A hot reload offers a volunteered handover; it never clears into it.
- **Slow session starts.** The resume prompt (and any held text) is sent 0.5 s after the clear, and a limit resume when its reset timer fires; if the engine refuses it because the session is still starting (slow SessionStart hooks, as in a container) it is retried 1, 2, 4 and 8 s later -- about 15.5 s from the first attempt -- before the usual "Couldn't resume" notice. Each refusal logs `guard.wait` `resume-retry` with its attempt, and the send logs `resume.sent`. It is never sent twice, anything you type meanwhile cancels the retry, and so does a new `/clear` or `/resume`. The engine offers no readiness signal, so this is a backoff, not a wait.
- **Event log.** If the events file cannot be written, one `$.ui.log` line says so per file. If the engine still answers the old session id 5 s after a clear, a line says that too (the events of that clear then land in the old session's file).
- **Compaction.** No compaction event reaches the mod: a context reading a whole `step` below the last one with a fill, on the same window, is a compaction, and the nudge ladder and bar start over (`compacted` in the log). A smaller dip, or a switch to another window size, is not.
- **Git.** No file events reach the mod: the branch and dirty files in the handover snapshot are re-read after every turn (and file-changing tool call), coalesced to one read per 1.5 s.
- A second `/vho` while one is in flight is refused with a notice, and a clear is never queued twice. `/vho` says plainly when a handover is already running, the mod is standing down or a limit is latched.
- Turning auto off, in any session, stops a clear that is waiting.
- A handover asked for or due while the latch is set waits for it; your next message cancels it. When the latch lifts it runs only if auto mode is on and you are still away, as an unattended handover (attended re-check and RC rules apply); otherwise a notice tells you it was not run. This holds whether the latch landed before or after the handover file was written: a clear the latch parked follows the same rule.
- Attended guard: an auto-mode (unattended) handover never clears once you are back. The mode is re-checked at the moment of clearing; if you have prompted since it began, the handover is kept, the log says `clear.skipped`, and a notice says to `/vho` or `/clear` when ready. `/vho` and the bar's `1` are attended and unaffected.
- Baseline guard: an auto-mode threshold handover fires only once context has grown at least one `step` (default 5) above the session's baseline, its first context reading (a /clear starts a new baseline). This stops a session that resumes just under the threshold from handing over again within a turn; the log says `guard.baseline` when it holds one back. Attended nudges are unaffected.
- A handover still pending when a session restarts is offered at session start with a `/clear` notice. Parked handovers older than 14 days are pruned.
- With no config dir to be found (`CLAUDE_CONFIG_DIR`, `HOME`, `USERPROFILE` and `HOMEDRIVE`+`HOMEPATH` all unset), nothing is written anywhere and a handover is refused with a notice naming those variables.

## Last light

`/vigil-setup last-light` (the setup step's header is "🌅 Lastlight"). When nothing has come from you since the agent's last turn, the agent is idle, the 1 h prompt cache is about to lapse (5 min lead) and context is at or past the last-light threshold, the mod **writes the handover only; it never clears**.

It only works with a 1-hour cache: just before it would fire, the mod reads the latest cache write from the transcript's last 64 KB and does not fire for a 5-minute cache, or when it finds nothing, so it never warms a cold one. Separately, for information only: after the session's first cache-writing response the mod reads the cache type once; for a 5-minute cache it shows a "Last light is off for this session" line above the prompt until your next message (the threshold bar takes precedence). A model switch (a main response from another model than the last one; no switch event reaches the mod) makes the next cache-writing response read it again, announcing when last light is back on. It fires at most once until a human prompt re-arms it. When you return after the cache has expired, your next prompt is held and the mod asks: resume from the handover (cheap) or carry on (pays the cold cache). Your message is re-sent either way.

## Limits

A window at its limit (read from the context measure, or from the limits when a main turn ends on an API error) sets an account-wide **latch** with the reset time; a main turn that ends on an API error while a window reads 90% or more sets a 5-minute one (the error's kind is not known, so it is taken as a likely limit): no clearing and no prompting until it lifts (notices show `⏳ resumes HH:MM`). A full window that reports no reset time latches for an hour at a time. A turn's end names no error kind, so a rate-limit refusal while every window reads under 90% sets no latch (PROBES section 16). **Early stop** (configurable via `/vigil-setup limits`): when a watched window (`seven_day` weekly, `spend_limit` spend cap, and `five_hour` when ticked) reaches the trigger % (default 98; setup offers 95, 98 (recommended) and 99, or any number), once per window, the mod writes a handover and arranges a resume 5 min after the reset if the session is still open and you have not come back in the meantime (then a notice names the handover instead). The latch is account-wide (`$.store`); early-stop marks are per running session. The 5-hour window (`five_hour`) is opt-in and unticked by default: Claude Code already wraps up and auto-continues at the 5-hour limit by itself, and ticking it adds the mod's own handover at the trigger % on top.

## Remote Control

"On the phone" = the last human prompt came from `bridge`. Whether auto-clear may run there is asked in setup (`/vigil-setup`, right after the auto-mode question when auto is on; `/vigil-setup rc` asks it alone) and never during a run. Until it is answered it follows auto mode: on means it clears on the phone too, with the safeguards below, and a single hint per session says so (`/vigil-setup rc` to change). If allowed: a 30 s countdown with Cancel in the terminal bar (any message cancels; the countdown notice does not reach the phone yet, PROBES.md §1), and no clear within 2 min of the last phone prompt. If you answered No, the handover is saved and a notice says why nothing cleared (`/vigil-setup rc` to enable). The countdown and holdback apply only to unattended clears: `/vho` or the bar's `1` from the phone bypass them. The countdown bar draws even with the bar setting Off.

## Files

Under `$CLAUDE_CONFIG_DIR/context-vigil-mod/`, one account only:

- `handovers/<session>-<n>.md`
- `events/<day>/<session>.jsonl` -- one JSON line per decision (`arm`, `threshold`, `handover.written`, `clear`, `resume`, ...) with its reason.

## Temporary interlock

The mod stands down (no arming, clearing or bar; one notice) when classic context-vigil is active for the session: classic hooks in the account's `settings.json`, or a classic session record. **Temporary:** removed, with all classic-detection code, when classic retires.

## Windows

Works on Windows with Claude Code's own shell tools. The config dir is `CLAUDE_CONFIG_DIR`, else `<home>\.claude`, with the home
taken from `HOME`, else `USERPROFILE`, else `HOMEDRIVE`+`HOMEPATH`; paths keep the separator of the base (`C:\Users\you\.claude\context-vigil-mod\...`).
Last light and the session-name check read the transcript with `tail` and `grep`; where `sh` does not run (no Git Bash)
they read the transcript file directly instead, and a transcript over the engine's 4 MiB read cap reads as "cannot tell": last
light then stays off (unknown never fires) and neither session is renamed. Everything else spawns only `git`.

## Development and verification

`SMOKES.md` is the owner-run live checklist; `PROBES.md` records the engine behaviours this relies on. Gates: `claude plugin validate plugins/context-vigil-mod/plugin`, `bash tests/run-mods.sh context-vigil-mod` (the tests live in `plugins/context-vigil-mod/tests/`, beside `plugin/`, so they do not ship), `bash plugins/context-vigil-mod/typecheck.sh` (also typechecks those tests), `pytest plugins/context-vigil-mod/tests`.
