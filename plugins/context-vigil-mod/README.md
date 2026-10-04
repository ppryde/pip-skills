# context-vigil-mod

Context handover as a Claude Code **mod**: a pure-TypeScript set of function hooks. No tmux, no status line, no Python CLI. It watches how full the context window is, nudges you, and (when you are away) hands over, `/clear`s in-process and resumes from the handover.

## Side by side with classic

It is a second implementation of context-vigil, run beside the classic one so the two can be compared on real work: **personal account = mod, work account = classic**. Classic is untouched. Distinct names everywhere (`/vho` not `/ho`, `vigil_handover`, files under `context-vigil-mod/`), and a temporary interlock (below) makes the mod stand down wherever classic is installed.

## Install

```bash
bash plugins/context-vigil-mod/scripts/install.sh install     # also: status | uninstall
```

Run it in the account you are switching. **Uninstall classic's hooks from that account first** (classic's own uninstall) -- the script refuses otherwise. It lists this folder in `env.CLAUDE_CODE_PLUGIN_DIRS` in that account's own `settings.json` (`$CLAUDE_CONFIG_DIR`, else `~/.claude`), never a repo's. Then start a **new session** and run `/vsetup`.

## Commands

- `/vho`, `/vhandoff` -- hand over now (the same command twice).
- `/vsetup [nudge|bar|auto|last-light|limits|rc]` -- the whole setup flow, or one step. `limits` covers on/off, trigger % and windows together.

Settings are per account (`$.store`). Defaults: nudge 35% (+5% steps), bar On, auto Off, idle window 30 min, last light Off (threshold 25%), limits On (95%, `seven_day` + `spend_limit`), RC auto-clear unanswered (treated as No).

## Three states

Every moment is in exactly one:

| You | The agent | State | At the context threshold |
|---|---|---|---|
| engaged | anything | **attended** | nudge only (bar in the terminal, notice on the phone); never clears |
| idle >= idle window | working | **auto armed** | hands over, clears, resumes by itself |
| idle | idle | **last-light territory** | no clear; before the cache goes cold, write the handover only |

*Engaged* = a `composer`, `bridge` (Remote Control) or `slack-ping` prompt, a slash command you ran, or a prompt-box edit/draft, within the idle window. *Working* = agent activity within the last 2 min. Auto mode is off until enabled in `/vsetup auto`. `sdk` sessions (`claude -p`) are unattended from the first turn.

## The handover

The mod registers a `vigil_handover` tool and asks the model to call it. Required fields: `goal`, `state`, `next_step` and `session_name`; optional: `decisions`, `open_questions`, `failed_attempts`. The mod adds a snapshot (cwd, branch, dirty files, files edited, context %) and saves `handovers/<session>-<n>.md`. It then clears (only when the prompt box is empty, the RC rules hold and no limit latch is set; every wait shows a notice), injects the handover into the fresh session and submits the resume prompt.

**Session naming.** After the clear, an **unnamed** session is renamed to the handover's `session_name` (a mod-run `/rename`: prompt border, `/resume`, Remote Control). A session that already has a name (a `/rename` of yours, or an earlier handover) **keeps its name** -- `/clear` carries it. Only a transcript `custom-title` counts as named; Claude Code's own auto title does not. If the check cannot run, no rename is attempted.

State that must cross a clear (pending handover, limit latch) lives in `$.store`, because `$.state` is wiped by every `/clear` (PROBES section 9).

## The vigil bar

Terminal only. Shown from the threshold crossing until you choose or a handover happens:
`🕯️ context 41% · threshold 35%   📜 Hand over now · ⏰ Remind me at 40% · ✖ Dismiss`, with hotkeys `1`, `2`, `0` on the three buttons (the label names the absolute next step).

- `1` starts a handover; `2` hides it until the next step; `0` hides it silently until a `/clear`.
- A bare digit typed into an **empty** prompt box presses a button, so the bar is threshold-only, never always-on.
- It **yields to the feedback survey** (`hasSurvey`) and returns after it.
- Off via `/vsetup bar`: a toast and log line (fired from the context measure) still mark the threshold and every step after. Phone sessions get the notice, not the bar.

## Guards and failure paths

- Draft guard: a clear waits while the terminal prompt box holds a draft, rechecked every 2 s, with a notice.
- If the model does not call `vigil_handover`, it is asked once more; then a "couldn't write a handover" notice appears and nothing clears.
- A handover asked for while the limit latch is set is deferred and starts when the latch lifts.
- A handover still pending when a session restarts is offered at session start with a `/clear` notice.

## Last light

`/vsetup last-light`. When you and the agent are both idle, shortly before the 1 h prompt cache lapses (5 min lead) and context is at or past the last-light threshold, the mod **writes the handover only; it never clears**. It fires at most once until a human prompt re-arms it. When you return after the cache has expired, your next prompt is held and the mod asks: resume from the handover (cheap) or carry on (pays the cold cache). Your message is re-sent either way.

## Limits

A rate-limit failure or a window at its limit sets an account-wide **latch** with the reset time: no clearing and no prompting until it lifts (notices show `⏳ resumes HH:MM`). **Early stop** (configurable via `/vsetup limits`): when a watched window (`seven_day`, `spend_limit`) reaches the trigger % (default 95), once per window, the mod writes a handover and arranges a resume 5 min after the reset if the session is still open. The latch is account-wide (`$.store`); early-stop marks are per running session. The 5-hour window is left to Claude Code's own wrap-up and auto-continue.

## Remote Control

"On the phone" = the last human prompt came from `bridge`. The first time auto mode would arm there, a one-off question asks whether to allow auto-clear in RC sessions (`/vsetup rc` re-asks). If allowed: a 30 s countdown with Cancel (any message cancels), and no clear within 2 min of the last phone prompt. Otherwise the handover is saved and a notice says why nothing cleared (`/vsetup rc` to enable, or auto-clear is off for RC). The countdown and holdback apply only to unattended clears: `/vho` or the bar's `1` from the phone bypass them. The countdown bar draws even with the bar setting Off.

## Files

Under `$CLAUDE_CONFIG_DIR/context-vigil-mod/`, one account only:

- `handovers/<session>-<n>.md`
- `events/<day>/<session>.jsonl` -- one JSON line per decision (`arm`, `threshold`, `handover.written`, `clear`, `resume`, ...) with its reason.

## Temporary interlock

The mod stands down (no arming, clearing or bar; one notice) when classic context-vigil is active for the session: classic hooks in the account's `settings.json`, or a classic session record. **Temporary:** removed, with all classic-detection code, when classic retires.

## Verify

`SMOKES.md` is the owner-run live checklist; `PROBES.md` records the engine behaviours this relies on. Gates: `claude plugin validate`, `claude plugin test`, `bash scripts/typecheck.sh`, `pytest tests/context_vigil_mod`.
