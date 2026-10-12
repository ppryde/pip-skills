# Arguments (convene Step 0)

`$ARGUMENTS` is split on whitespace into tokens. `cli.py resolve --args <tokens...>`
validates every token (letters, digits, `.` `_` `:` `-`; no shell characters) and
applies one precedence, so you never interpret a token yourself:

1. **Reserved words**: `reviewers` / `strategies` (list and stop, must be alone),
   `full` (scope), `interactive` / `inline` (output). They beat any name.
2. **Profile name** from `.review-panel/config.yml` (one profile, with optional `full`
   and one output word). A profile that shares a reviewer's name wins.
3. **Reviewer keys**: built-in names or `clone:<alias>`, run ad hoc over changed files
   on the default strategy. This works with no config file.
4. Anything else: an `error` that lists every valid profile, reviewer and word. Show it.

Empty arguments mean the default profile. Status `config-missing` (a profile
form with no config file) → offer to seed `.review-panel/config.yml` from
`../../../templates/config.yml`, then stop.

Run it as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" resolve --args <tokens...>`.
If a token fails validation the CLI refuses it; do not rewrite or quote it to get it through.
