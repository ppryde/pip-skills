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

Every command below is complete on its own: nothing carries over between shell
calls. They run this plugin's own copy, `${CLAUDE_PLUGIN_ROOT}/scripts/cli.py`,
never a `census` already on `PATH`, which may be another plugin's launcher. Use
`python3` on macOS and Linux and `python` on Windows. In the commands, `CENSUS`
stands for `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py"` (or the `python`
form); write the whole thing out each time.

Never build a command from shell variables in braces or with default values
(a dollar sign, a brace and a colon-dash fallback): Claude Code stops to ask about
"a variable in braces" even for a read-only check. Every path you need (the config
dir, the census dir, `settings.json`) comes from `CENSUS where` below.
To act on another account than the one you are running in, add
`--config-dir <dir>` to `where`, `install` and `uninstall`; a dry run's first line
says which account it touches.

## Steps

1. **Look around.** Run `CENSUS where`. It is read-only and prints one JSON
   object: `config_dir`, `census_dir`, `settings_path`, the current `status_line`
   command, every census in the plugin cache (`census_installs`, with
   `enabled_census`), and `census_mod` (installed, enabled).
   - **census-mod first.** If `census_mod.enabled` is true (or it is installed and
     not disabled), say so: census-mod records sessions and draws the status
     line from inside Claude Code, above the input or below it, with no status
     line command at all. Recommend `/census-setup` (its guided setup: record,
     band, placement, layout) instead of installing a command status line. Only
     carry on with this skill if the person still wants the command status line,
     and tell them not to run both against the same store (census-mod's setup
     can remove an existing one).
   - **Two censuses.** The same plugin is published twice, as `census@pip-skills`
     and `census@wf-claude-market`. If `enabled_census` shows both enabled, tell
     the person to disable the one this skill is not part of (the other
     marketplace's, not the copy you are running): both write the same
     launcher, `~/.local/bin/census`, and install refuses a launcher it does
     not own. Do not continue until they have.

2. **Preview.** Run `CENSUS statusline --preview` and show the output. It draws
   a canned payload (including a canned PR, so the `pr` segment shows) plus the
   live census store (their real rate limits). It does not ingest anything and
   reads nothing from stdin (it may cache git state for the current directory).

3. **Choose segments.** Ask which segments they want and in what order. The
   names are `context`, `cache`, `limits`, `cost`, `model`, `git`, `dir`,
   `changes`, `pr`. A `/` starts a new line. The default is
   `context,cache,limits,cost/model,git,dir,changes,pr`. `git` is the branch;
   `changes` is the uncommitted and unpushed counts; `pr` is the branch's open
   PR and its review state (from the payload, hidden without one). Re-run the preview with
   `CENSUS_STATUSLINE_SEGMENTS="<list>" CENSUS statusline --preview` until
   they are happy. Keeping the default is fine: then pass no `--segments`.

4. **Dry run.** Run `CENSUS install --statusline [--segments "<list>"]` (no
   `--yes`) and show what it would do. It sets `statusLine` in the `settings_path`
   from step 1, with a 60 second refresh interval, and installs the launcher.
   - If it refuses because a `statusLine` already exists, say what is there and
     that `--replace` backs it up to `<census dir>/statusline.previous.json` and
     swaps; only add `--replace` if they agree.
   - If it refuses because `settings.json` is missing or not valid JSON, report
     that and stop. Do not create or repair the file.

5. **Apply.** On their approval re-run the same command with `--yes`. Tell them
   to restart Claude Code or wait one refresh for the line to appear.

## Options worth mentioning

Set in `settings.json` under `env`, all optional:

- `CENSUS_STATUSLINE_COLOR`: `auto` (default), `always`, `never` (`NO_COLOR` is honoured).
- `CENSUS_STATUSLINE_GIT_TTL`: seconds git state is cached (default 15, `0` disables).
- `CLAUDE_COST_BUDGET`: the dollar amount the cost bar fills toward (default 20).
- `CENSUS_STATUSLINE_MASCOT`: the glyph before the model name (default a ✻ in Claude's orange).
- `AGENT_UI_STATUSLINE_CACHE`: a directory that also receives each raw payload.

## Undo

`CENSUS uninstall --yes` restores the `statusLine` that was replaced (or removes
the one census added), and removes `CENSUS_STATUSLINE_SEGMENTS` if census wrote it.
If they have changed `statusLine` since, it leaves it alone and says so. Add
`--purge` to also delete this account's census data; when several accounts share
one `CENSUS_STORE`, only this account's limits and sessions are deleted and the
rest is kept. If the status line cannot be restored (an unreadable backup or
settings file) it stops and removes nothing.
