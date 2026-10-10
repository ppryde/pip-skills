# context-vigil-mod

Context handover as a Claude Code **mod**: a pure-TypeScript set of function hooks. No tmux, no status line, no Python CLI. It watches how full the context window is, nudges you, and (when you are away) hands over, `/clear`s in-process and resumes from the handover.

## Side by side with classic

It is a second implementation of context-vigil (the "classic" tmux + status-line plugin). Classic is untouched. Distinct names everywhere (`/vho` not `/ho`, `vigil_handover`, files under `context-vigil-mod/`), and a temporary interlock (below) makes the mod stand down wherever classic is installed.

## Install

Load it **one way only**, never both:

```bash
# from the marketplace, in a Claude Code session
/plugin marketplace add ppryde/pip-skills
/plugin install context-vigil-mod@pip-skills

# or straight from a checkout
bash plugins/context-vigil-mod/plugin/scripts/install.sh install     # also: status | uninstall
```

**Uninstall classic's hooks first** (classic's own uninstall) -- the script refuses otherwise. It lists this folder in `env.CLAUDE_CODE_PLUGIN_DIRS` in your user `settings.json` (`$CLAUDE_CONFIG_DIR`, else `~/.claude`), never a repo's. Then start a **new session** and run `/vigil-setup`.

## Commands

- `/vigil-handover`, or `/vho` for short -- hand over now.
- **Plain words.** A short message (12 words or fewer) from you that plainly asks for a handover -- "handover", "do a handover", "hand this off", "time for a handover", "can you do a handover?" -- is not sent to the model: the mod drops it with `📜 Handing over — as /vho` and runs exactly what `/vho` runs (same standdown, latch and in-flight notices). This applies only while the mod is active: when classic is installed and the mod stands down, the words go to the model as usual. Questions and talk about handovers ("how does the handover work", "fix the handover bug", "don't hand over yet") go through untouched, as does anything from a plugin; a last-light hold on your return is checked first.
- **Looser net.** If your latest message mentioned a handover at all (`handover`, `hand over`, `handoff`, ...) and the model then calls `vigil_handover` without the mod having asked, the call counts as asked for: it clears and resumes as `/vho` does. The mention is session state, wiped by a `/clear`, and spent by the call. The mention does not count while the mod stands down. Without a mention, an unrequested call is still the model volunteering: saved and offered, never cleared. The tool's description tells the model to write a handover only through the tool, never as an ad-hoc file or summary.
- `/vigil-overrides [add|rm|check]` -- thresholds per model, window size or both. Bare (or `check`) lists the overrides in the order they are tried, what this session gets and from which override, and any faults or ambiguity; `add` asks for an override for the session you are in; `rm model=… window=…` (either or both) takes one out. See **Overrides** below.
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

Settings are per account (`$.store`) and re-read before every decision that matters, so a change made in one session reaches the others. Defaults: nudge 35% (+5% steps), with one default override `window=200k → 70%`, bar On, auto Off, idle window 30 min (15, 30 or 60), last light Off (writes its handover only at 25%+ context), limits On (95%, `seven_day` + `spend_limit`), RC auto-clear unanswered (treated as No).

## Three states

Every moment is in exactly one:

| You | The agent | State | At the context threshold |
|---|---|---|---|
| engaged | anything | **attended** | nudge only (bar and notice in the terminal); never clears |
| idle >= idle window | working | **auto armed** | hands over, clears, resumes by itself |
| idle | idle | **last-light territory** | no clear; before the cache goes cold, write the handover only |

*Engaged* = a `composer`, `bridge` (Remote Control) or `slack-ping` prompt, a slash command you ran, an answer to one of the mod's questions, a bar button press, or a prompt-box edit/draft, within the idle window. *Working* = agent activity within the last 2 min. Auto mode is off until enabled in `/vigil-setup auto`. `sdk` sessions (`claude -p`) are unattended from the first turn. An `unclassified`, `channel` or `auto-continuation` prompt disarms auto mode but counts for nothing else.

## The handover

The mod registers a `vigil_handover` tool and asks the model to call it. Required fields: `goal`, `state`, `next_step` and `session_name`; optional: `decisions`, `open_questions`, `failed_attempts`. The mod adds a snapshot (cwd, branch, dirty files, files edited, context %) and saves `handovers/<session>-<n>.md`. It then clears (only when the prompt box is empty, the RC rules hold and no limit latch is set; every wait shows a notice), injects the handover into the fresh session and submits the resume prompt. A `/clear` you run yourself picks up a saved handover the same way; the automatic resume is sent only when no turn has run since the handover was written and no usage limit is in force — otherwise the handover is injected and a notice asks you where to pick up.

**Session naming.** After the clear, an **unnamed** session is renamed to the handover's `session_name` (a mod-run `/rename`: prompt border, `/resume`, Remote Control). A session that already has a name (a `/rename` of yours, or an earlier handover) **keeps its name** -- `/clear` carries it. Only a transcript `custom-title` counts as named; Claude Code's own auto title does not. If the check cannot run, no rename is attempted.

State that must cross a clear (pending handover, limit latch) lives in `$.store`, because `$.state` is wiped by every `/clear` (PROBES section 9).

## The vigil bar

Terminal only. Shown from the threshold crossing until you choose or a handover happens:
`🕯️ context 41% · threshold 35%   📜 Hand over now · ⏰ Remind me at 45% · ✖ Dismiss`, with hotkeys `1`, `2`, `0` on the three buttons (the label names the absolute next step).

- `1` starts a handover; `2` hides it until the next step; `0` hides it silently until a `/clear`.
- A bare digit typed into an **empty** prompt box presses a button, so the bar is threshold-only, never always-on.
- It **yields to the feedback survey** (`hasSurvey`) and returns after it.
- Off via `/vigil-setup bar`: a toast and log line (fired from the context measure) still mark the threshold and every step after. Notices (`ui.toast`/`ui.log`) show in the terminal only: they do not reach Remote Control yet (PROBES.md §1).

## Guards and failure paths

- Draft guard: a clear waits while the terminal prompt box holds a draft, rechecked every 2 s, with a notice.
- If the model does not call `vigil_handover`, it is asked once more; then a "couldn't write a handover" notice appears and nothing clears. A request that is lost altogether expires after 10 idle minutes.
- A handover the model writes without being asked is saved but never cleared into.
- **Slow session starts.** The resume prompt (and any held text) is sent 0.5 s after the clear, and a limit resume when its reset timer fires; if the engine refuses it because the session is still starting (slow SessionStart hooks, as in a container) it is retried 1, 2, 4 and 8 s later -- about 15.5 s from the first attempt -- before the usual "Couldn't resume" notice. Each refusal logs `guard.wait` `resume-retry` with its attempt, and the send logs `resume.sent`. It is never sent twice, anything you type meanwhile cancels the retry, and so does a new `/clear` or `/resume`. The engine offers no readiness signal, so this is a backoff, not a wait.
- **Event log.** If the events file cannot be written, one `$.ui.log` line says so per file. If the engine still answers the old session id right after a clear, a line says that too (the events of that clear then land in the old session's file).
- A second `/vho` while one is in flight is refused with a notice, and a clear is never queued twice. `/vho` says plainly when a handover is already running, the mod is standing down or a limit is latched.
- Turning auto off, in any session, stops a clear that is waiting.
- A handover asked for or due while the latch is set waits for it; your next message cancels it. When the latch lifts it runs only if auto mode is on and you are still away, as an unattended handover (attended re-check and RC rules apply); otherwise a notice tells you it was not run. This holds whether the latch landed before or after the handover file was written: a clear the latch parked follows the same rule.
- Attended guard: an auto-mode (unattended) handover never clears once you are back. The mode is re-checked at the moment of clearing; if you have prompted since it began, the handover is kept, the log says `clear.skipped`, and a notice says to `/vho` or `/clear` when ready. `/vho` and the bar's `1` are attended and unaffected.
- Baseline guard: an auto-mode threshold handover fires only once context has grown at least one `step` (default 5) above the session's baseline, its first context reading (a /clear starts a new baseline). This stops a session that resumes just under the threshold from handing over again within a turn; the log says `guard.baseline` when it holds one back. Attended nudges are unaffected.
- A handover still pending when a session restarts is offered at session start with a `/clear` notice. Parked handovers older than 14 days are pruned.
- With no config dir to be found (`CLAUDE_CONFIG_DIR`, `HOME`, `USERPROFILE` and `HOMEDRIVE`+`HOMEPATH` all unset), nothing is written anywhere and a handover is refused with a notice naming those variables.

## Last light

`/vigil-setup last-light`. When nothing has come from you since the agent's last turn, the agent is idle, the 1 h prompt cache is about to lapse (5 min lead) and context is at or past the last-light threshold, the mod **writes the handover only; it never clears**.

It only works with a 1-hour cache: just before it would fire, the mod reads the latest cache write from the transcript's last 64 KB and does not fire for a 5-minute cache, or when it finds nothing, so it never warms a cold one. Separately, for information only: after the session's first cache-writing response the mod reads the cache type once; for a 5-minute cache it shows a "Last light is off for this session" line above the prompt until your next message (the threshold bar takes precedence). A model switch's `cache_ttl` updates it, announcing when last light is back on. It fires at most once until a human prompt re-arms it. When you return after the cache has expired, your next prompt is held and the mod asks: resume from the handover (cheap) or carry on (pays the cold cache). Your message is re-sent either way.

## Limits

A rate-limit failure or a window at its limit sets an account-wide **latch** with the reset time: no clearing and no prompting until it lifts (notices show `⏳ resumes HH:MM`). A full window that reports no reset time latches for an hour at a time. **Early stop** (configurable via `/vigil-setup limits`): when a watched window (`seven_day`, `spend_limit`) reaches the trigger % (default 95), once per window, the mod writes a handover and arranges a resume 5 min after the reset if the session is still open and you have not come back in the meantime (then a notice names the handover instead). The latch is account-wide (`$.store`); early-stop marks are per running session. The 5-hour window is left to Claude Code's own wrap-up and auto-continue.

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
Last light and the "is this session named" check read the transcript with `tail` and `grep`; where `sh` does not run (no Git Bash)
they read the transcript file directly instead, and a transcript over the engine's 4 MiB read cap reads as "cannot tell": last
light then stays off (unknown never fires) and the session is left unrenamed. Everything else spawns only `git`.

## Verify

`SMOKES.md` is the owner-run live checklist; `PROBES.md` records the engine behaviours this relies on. Gates: `claude plugin validate plugins/context-vigil-mod/plugin`, `bash tests/run-mods.sh context-vigil-mod` (the tests live in `plugins/context-vigil-mod/tests/`, beside `plugin/`, so they do not ship), `bash plugins/context-vigil-mod/typecheck.sh` (also typechecks those tests), `pytest plugins/context-vigil-mod/tests`.
