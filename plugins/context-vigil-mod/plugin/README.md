# context-vigil-mod

Hands your session over before the context window fills up. It watches context use, nudges you at a threshold, and (while you are away) writes a handover, runs `/clear` and resumes from it.

It is a Claude Code mod: no tmux, no status line. Deep detail is in [REFERENCE.md](REFERENCE.md).

## Quick start

<!-- Install lines differ by repo (pip-skills vs wf-claude-market). Keep them in this block only. -->
1. Install it. Use one route only.

   ```bash
   # marketplace, inside a Claude Code session
   /plugin marketplace add ppryde/pip-skills
   /plugin install context-vigil-mod@pip-skills

   # or from a checkout (needs jq; also: status | uninstall)
   bash plugins/context-vigil-mod/plugin/scripts/install.sh install
   ```

2. If classic `context-vigil` hooks are installed, remove them first. The script refuses otherwise, and the mod stands down.
3. Start a new session.
4. Run the setup:

   ```
   /vigil-setup
   ```

5. Try it: `/vho` hands over now.

## Commands

| Command | What it does | Example |
|---|---|---|
| `/vigil-handover` | Hand over now. Writes the handover, clears, resumes. | `/vigil-handover` |
| `/vho` | Short for `/vigil-handover`. | `/vho` |
| `/vigil-setup [step]` | Guided setup, or one step: `nudge`, `bar`, `auto`, `last-light`, `limits`, `rc`. Asks in dialogs; nothing goes to the model. | `/vigil-setup auto` |
| `/vigil-overrides [add\|rm\|check]` | Thresholds per model, per window or both. Bare or `check` lists them and what this session gets. | `/vigil-overrides add` |
| `1` | Vigil bar: hand over now. | press `1` |
| `2` | Vigil bar: remind me at the next step. | press `2` |
| `0` | Vigil bar: dismiss until the next `/clear`. | press `0` |

Short plain-words messages such as "do a handover" run `/vho` too. See [REFERENCE.md](REFERENCE.md#command-details).

The model also has a `vigil_handover` tool. The mod asks it to call the tool; you do not call it yourself.

## Settings

Set these with `/vigil-setup`. They are stored per account and apply to every session.

| Setting | Default | What it changes |
|---|---|---|
| Nudge threshold (`nudgeAt`) | `35` (%) | Context % where the nudge and the bar start. |
| Nudge step (`step`) | `5` (%) | Gap between repeated nudges. Set through overrides only. |
| Bar (`bar`) | On | Shows the vigil bar at the threshold. Off gives a toast and log line. |
| Auto (`auto`) | Off | Hands over and clears by itself while you are away. |
| Idle window (`idleMin`) | `30` (min) | How long you must be idle before auto mode may clear. Setup offers 15, 30 or 60. |
| Remote Control auto-clear (`rcAutoClear`) | follows `auto` | Whether auto may clear when your last message came from the phone. |
| Last light (`lastLight`) | Off | Writes a handover, never clears, before the 1-hour cache lapses. |
| Last light at (`lastLightAt`) | `25` (%) | Lowest context % where last light writes. |
| Limits (`limits`) | On | Early stop before a rate limit. |
| Limit trigger (`limitPct`) | `95` (%) | Window use where early stop fires. |
| Limit windows (`limitWindows`) | `seven_day`, `spend_limit` | Windows early stop watches. |

Default override: a 200k window uses a nudge at 70%.

Files live under `$CLAUDE_CONFIG_DIR/context-vigil-mod/` (else `~/.claude/context-vigil-mod/`):

| Path | Holds |
|---|---|
| `overrides.json` | Per-model and per-window thresholds. Edit by hand or with `/vigil-overrides`. |
| `handovers/<session>-<n>.md` | Saved handovers. |
| `events/<day>/<session>.jsonl` | One line per decision, with its reason. |

Overrides, most specific first:

1. `model` and `window` together (the longer model pattern wins).
2. `window` only.
3. `model` only.
4. Your `/vigil-setup` values.

A model pattern is a family and at most a version: `opus`, `opus5`, `opus5.5`.

```json
{ "overrides": [ { "model": "opus", "window": 1000000, "nudgeAt": 25, "step": 10 } ] }
```

## How it works

Every moment is in one of three states.

| You | The agent | State | At the threshold |
|---|---|---|---|
| engaged | anything | attended | Nudge only. Never clears. |
| idle for the idle window | working | auto armed | Hands over, clears, resumes. |
| idle | idle | last light | Writes the handover only. |

- The bar shows `context 41% · threshold 35%` with the three buttons above. On the phone the same choices arrive as a dialog.
- A handover saves `goal`, `state`, `next_step` and a snapshot of the repo to `handovers/`. The mod then clears and resumes from it.
- A `/clear` you run yourself picks up a saved handover.
- Standing orders (rules for the whole chain of sessions) carry forward from one handover to the next.
- A named session is renamed `Archive: <name>` before the clear; the new session gets the name back.
- A rate-limit failure sets a latch: no clearing until the limit resets.

## Troubleshooting

- **`/vigil-setup` is not found.** The mod is not loaded. Start a new session after install, and run `bash plugins/context-vigil-mod/plugin/scripts/install.sh status`.
- **Install script refuses.** Classic `context-vigil` hooks are present. Uninstall classic first.
- **Nothing happens at the threshold.** The mod stands down when classic is active. Check overrides with `/vigil-overrides check`.
- **Auto mode does not clear.** Auto is Off until you turn it on in `/vigil-setup auto`. It also never clears once you are back or while the prompt box holds a draft.
- **Handover saved but not cleared.** The model wrote it without being asked. Answer the dialog: update it, clear now, or leave it.
- **"Couldn't write a handover".** The model did not call the tool after a retry. Nothing cleared; run `/vho` again.
- **Nothing is written anywhere.** No config dir could be found. Set `CLAUDE_CONFIG_DIR` or `HOME`.

More failure paths: [REFERENCE.md](REFERENCE.md#guards-and-failure-paths). Other mods in this family: [census-mod](../../census-mod/plugin/README.md), [agent-roster](../../agent-roster/plugin/README.md).
