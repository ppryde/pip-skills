# census-mod

Records every interactive Claude Code session (context, cost, limits, git, PR) into the census store, and draws the status line above or below the input.

It is a mod, so it acts on events and costs about nothing when idle. It is standalone: it bundles census's store and ingest, and it does not need the census plugin. Install census-mod or the census plugin, never both. Deep detail is in [REFERENCE.md](REFERENCE.md).

## Quick start

<!-- Install lines differ by repo (pip-skills vs wf-claude-market). Keep them in this block only. -->
1. Install it. Use one route only.

   ```bash
   # marketplace, inside a Claude Code session
   /plugin marketplace add ppryde/pip-skills
   /plugin install census-mod@pip-skills

   # or load a checkout for one session
   claude --plugin-dir plugins/census-mod/plugin
   ```

   To load a checkout in every session, add its folder to `CLAUDE_CODE_PLUGIN_DIRS` under `env` in the account's `settings.json`.
2. If the census plugin is enabled, disable it: `claude plugin disable census@<marketplace>`.
3. Start a new session. It offers setup once.
4. Run the guided setup:

   ```
   /census-setup
   ```

5. Check the status line appears. To try shadow mode first, start with `CENSUS_MOD_STORE=~/.claude/census-shadow claude`.

## Commands

| Command | What it does | Example |
|---|---|---|
| `/census-setup [off\|style\|budget]` | Guided setup: record, draw, style, layout, budget, PR lookup. Dialogs only; nothing goes to the model. | `/census-setup` |
| `/census-setup style` | Jumps straight to the Style question only; the saved Layout is kept. Needs drawing on. | `/census-setup style` |
| `/census-setup budget` | Jumps straight to the Budget question. Needs drawing on and a cost bar in the effective segments. | `/census-setup budget` |
| `/census-setup off` | Stops recording and drawing. Puts a removed status line back if settings still have none. | `/census-setup off` |
| `/census-mod:pr-refresh` | Asks `gh` once for this branch's open PR and records it. Does not turn `gh` on. | `/census-mod:pr-refresh` |

## Settings

Answers from `/census-setup` are stored per account. An environment variable beats an answer, and an answer beats the default.

| Setting | Default | What it changes |
|---|---|---|
| Record (setup answer) | Yes if your status line does not already record | Records sessions into the census store. |
| 🕵️ Subagent cost | shown when subagents ran | Beside the session total (which already includes it): `💸 [bar] $3.10 (🕵️ $1.20)`. Priced from the session's subagent transcripts at chronicle's list prices (`core/rates.ts`, generated from chronicle's table), so it is an estimate, capped at the total. |
| 💸 Budget (setup answer) | `$20` | Main-session cost budget the 💸 bar fills to. Asked only when the effective segments include `cost` (the Pac-Man layouts do; the Clean layouts do not, unless `CENSUS_STATUSLINE_SEGMENTS` adds it). Options: `$10`, `$20` (recommended), `$50`, `$100` or any amount. |
| Draw (setup answer) | above the input | Draws the status line: `above`, `below`, or off. |
| 🎨 Style (`style`) | `pacman` | `pacman` (the bars) or `clean` (plain text, ` | ` separators). A missing value means `pacman`. |
| 📐 Layout (setup answer) | Full — two lines | Full, Compact (one line) or Minimal. Applies to both styles. |
| PR lookup (setup answer) | No | Lets the mod call `gh pr list`. PRs the session itself opens still show. |
| `CENSUS_MOD_STORE` | unset | Records to this census dir instead (shadow mode). Forces shadow. |
| `CENSUS_STORE` | `<config dir>/census` | Census dir for the recorder. `~` expands. |
| `CENSUS_MOD_PLACEMENT` | answer, else `above` | `above` or `below`. Overrides the answer. |
| `CENSUS_MOD_PR_HINT` | unset | `1` confirms a grey PR from the prompt hint. |
| `CENSUS_STATUSLINE_SEGMENTS` | `context,cache,limits,cost/model,git,dir,changes,pr` | Segments, for both styles; overrides Style and Layout. `,` joins on a line, `/` starts the next. |
| `CENSUS_STATUSLINE_MASCOT` | bold `✻` in `#D97757` | Mascot string, drawn as given. |
| `CLAUDE_COST_BUDGET` | unset | Cost budget. Overrides the saved Budget answer, which overrides the `$20` default. |
| `CLAUDE_PROFILE` | unset | `personal`, `home` or `p` means a personal account; any other value means work. |
| `CLAUDE_CONFIG_DIR` | `~/.claude` | The account's config dir. |

## How it works

- It runs the bundled `scripts/cli.py ingest` on session events. Writes are coalesced: at most one every 2 s.
- It records interactive main sessions only. `-p` runs and subagents are not recorded.
- Liveness comes from the session's process, not a heartbeat.
- git runs only when something may have changed, at most every 5 s.
- `gh` runs only when the PR lookup is Yes, or once per `/census-mod:pr-refresh`.
- The `pr` segment, such as `🔀 #12 approved`, is hidden without an open PR and grey when unconfirmed.
- The status line draws in one place, above or below the input. A 30 s tick redraws countdowns and never records.
- Shadow mode compares the two views: run with `CENSUS_MOD_STORE`, check `census read` against both dirs, then unset it.

## Styles and layouts

Setup asks **🎨 Style** after Draw: "Pip's Pac-Man flavour" (recommended; the bars), "Dave's Nice 'n' Clean" (plain text, ` | ` separators), or "Show me", which asks again with a sample line of each. Then **📐 Layout**: Full (two lines, recommended), Compact (one line) or Minimal.

Clean style layouts (sample data):

Full, two lines:

```
🤖 Opus 5.5 | 🧠 85k/200k 42% | 💵 $1.37 | 🕔 5h 38% 0.8x | 🗓️ 7d 12% 0.7x
📁 pip-skills | 🌿 feat/x +2 ~3 | 🔀 #187 approved
```

Compact, line one alone:

```
🤖 Opus 5.5 | 🧠 85k/200k 42% | 💵 $1.37 | 🕔 5h 38% 0.8x | 🗓️ 7d 12% 0.7x
```

Minimal:

```
🧠 42% | 🕔 5h 38% | 🗓️ 7d 12%
```

Notes on Clean:

- The pace multiplier (`0.8x`) is used % ÷ the share of the window gone. Under `1.0x` means under even pace.
- The token count is derived from context % × window, so it is approximate.
- Absent data is omitted along with its separator.

## Troubleshooting

- **Nothing is recorded.** Recording needs `python3` (3.9 or later) and the bundled `scripts/cli.py`. A broken install still draws the band and logs one line.
- **Two writers on one store.** The census plugin or your own status line also records. Run `/census-setup` and choose to replace the status line, or disable the census plugin.
- **No PR segment.** Without the PR lookup it follows only PRs the session opens. Run `/census-mod:pr-refresh`, or answer Yes in `/census-setup`.
- **PR segment is grey.** A push marked it unconfirmed. A PR event, a `gh` answer or `/census-mod:pr-refresh` confirms it.
- **Status line shows twice.** Your old `statusLine` is still set. Remove it in `/census-setup`; the backup is `<census dir>/census-mod.statusline.json`.
- **A stopped session still looks live.** Its registry entry never turned up. It is pruned after 24 hours.

Other mods in this family: [context-vigil-mod](../../context-vigil-mod/plugin/README.md), [agent-roster](../../agent-roster/plugin/README.md).
