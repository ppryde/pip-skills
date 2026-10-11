---
name: setup-statusline
description: Preview and install census's status line (context, prompt cache, rate limits, cost, model, git, directory). Use when the user wants a status line that also records to census, asks to set up, change or remove the census status line, or wants to choose which segments it shows. Not for Claude Code's built-in /statusline.
---

# Set up the census status line

`census statusline` records the status-line payload into the census store and
draws the line, in one process. This skill previews it, lets the person choose
segments, then installs it into `settings.json`. Claude Code has its own
built-in `/statusline`; this is census's, as `/census:setup-statusline`.

## Running census

Every command below is complete on its own (nothing carries over between shell calls) and runs this
plugin's own copy, never a `census` on `PATH`, which may be another plugin's launcher. `CENSUS` stands
for `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py"` (`python` on Windows); write it out each time.

Use no shell variables except `${CLAUDE_PLUGIN_ROOT}`, which Claude Code substitutes first, and never
compose a path with a default value (dollar, brace, colon-dash): Claude Code stops to ask even for a read-only check. Every
path you need (config dir, census dir, `settings.json`) comes from `CENSUS where`. To act on another
account add `--config-dir <dir>` to `where`, `install`, `uninstall` and `statusline --preview`; a dry
run's first line says which account it touches.

## Steps

1. **Look around.** Run `CENSUS where`. It is read-only and prints one JSON
   object: `config_dir`, `census_dir`, `settings_path`, the current `status_line`
   command, every census in the plugin cache (`census_installs`, with
   `enabled_census`), and `census_mod` (installed, enabled).
   - **census-mod first.** census and census-mod are alternatives: install one. If
     `notes` says census-mod is installed (or `census_mod.enabled` is true), say so:
     it records and draws from inside Claude Code, above or below the input, with no
     status line command. Recommend `/census-setup` (guided: record, band, placement,
     layout) instead. Carry on here only if the person still wants the command status
     line, and tell them not to run both against one store.
   - **Two censuses.** The plugin is published twice (`census@pip-skills`,
     `census@wf-claude-market`). If `enabled_census` shows both enabled, tell the
     person to disable the other marketplace's copy, not the one you are running:
     both write `~/.local/bin/census` and the last installer wins, so it can end up
     pointing at a copy later disabled or upgraded away. Do not continue until they have.

2. **Preview.** Run `CENSUS statusline --preview` (another account: `CENSUS statusline --preview --config-dir <dir>`) and show the output. It draws a canned payload (with a PR)
   plus the live store (their real rate limits); it ingests nothing and reads no stdin.

3. **Choose segments.** Ask which segments they want and in what order. The names are `context`, `cache`,
   `limits`, `cost`, `model`, `git`, `dir`, `changes`, `pr`. A `/` starts a new line.
   The default is `context,cache,limits,cost/model,git,dir,changes,pr`. `git` is the
   branch; `changes` the uncommitted and unpushed counts; `pr` the branch's open PR
   and review state (from the payload, hidden without one). Re-run
   `CENSUS statusline --preview --segments "<list>"` until they are happy; the
   default needs no `--segments`.

4. **Dry run.** Run `CENSUS install --statusline [--segments "<list>"]` (no
   `--yes`) and show what it would do. It sets `statusLine` in the `settings_path`
   from step 1, with a 60 second refresh interval, and installs the launcher.
   - If it refuses because a `statusLine` exists, say what is there and that
     `--replace` backs it up to `<census dir>/statusline.previous.json` and swaps;
     add it only if they agree.
   - If it refuses because `settings.json` is missing or not valid JSON, report that
     and stop. Do not create or repair the file.

5. **Apply.** On approval re-run it with `--yes`; the line appears after a restart or one refresh.

## Options worth mentioning

Set in `settings.json` under `env`, all optional:

- `CENSUS_STATUSLINE_COLOR`: `auto` (default), `always`, `never` (`NO_COLOR` is honoured).
- `CENSUS_STATUSLINE_GIT_TTL`: seconds git state is cached (default 15, `0` disables).
- `CLAUDE_COST_BUDGET`: the dollar amount the cost bar fills toward (default 20).
- `CENSUS_STATUSLINE_MASCOT`: the glyph before the model name (default a ✻ in Claude's orange).
- `AGENT_UI_STATUSLINE_CACHE`: a directory that also receives each raw payload.

## Undo

Run `CENSUS uninstall` first: it prints the plan and changes nothing. `--yes` then restores the
`statusLine` that was replaced (or removes the one census added), removes `CENSUS_STATUSLINE_SEGMENTS`
if census wrote it, and removes the launcher. If they changed `statusLine` since, it leaves it alone
and says so. If the status line cannot be restored (an unreadable backup or settings file) it stops
and removes nothing. Two questions come before `--yes`, and both are the person's to answer:

1. **Other accounts.** The launcher is one file for every account. If the plan says `needs a choice`
   (another account's `settings.json` still runs it), ask which they want, and never pick for them:
   uninstall for this account only (`--this-account-only`: the launcher stays for the others) or
   everywhere (`--all-accounts`: it also restores those accounts' status lines and removes the
   launcher). `--yes` without one of the two changes nothing. Neither flag touches another account's data.
2. **Saved data. Always ask**, even when nothing is shared: delete this account's saved census data
   (sessions, limits, git cache), or keep it? Warn that if they delete it the history cannot be
   recovered. Keep is the default and needs no flag; delete is `--purge`. When several accounts share
   one `CENSUS_STORE`, `--purge` removes only this account's limits and sessions.

Show the final plan (re-run the dry run with the chosen flags) and apply it with `--yes` once they approve.
