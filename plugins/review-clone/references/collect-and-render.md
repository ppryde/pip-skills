# review-clone: collect and render (shared by `clone-reviewer` and `review-as`)

One copy of the collector dispatch and the slash-command render, read by `clone-reviewer` (Steps 3 and 7) and by `review-as` refresh (Steps 1 and 4b). `<plugin>` is the absolute path of the `review-clone` plugin directory in this Claude Code install.

## Collect (Haiku subagent)

Data collection is pure I/O — `gh` API calls, file writes, no reasoning. **Dispatch it to a Haiku subagent** so the main (Opus) session keeps its context budget for reasoning (theme extraction in `clone-reviewer` Step 5; drift detection and rule updates in `review-as` refresh Steps 3–4). Do not run `collect.py` directly from this session.

**Quoting untrusted values.** `<handles>`, `<repo>`, `<paths>` and `<extensions>` are user-supplied (or derived from the checkout's `origin`), so treat them as hostile. Put each in **single quotes**, escaping any embedded `'` as `'\''`; never double quotes (those still run `$(...)` and backticks). Before building the command, validate `<repo>` as `owner/name` (`[A-Za-z0-9._-]+/[A-Za-z0-9._-]+`) and each handle as `[A-Za-z0-9-]+`; if a value fails or contains a newline or NUL, stop and say so.

Tell the user before dispatching:

- clone: > Pulling `<handle>`'s comments via a Haiku subagent. No live progress — I'll surface the summary when it finishes.
- refresh: > Refreshing `<alias>` via a Haiku subagent. No live progress — summary on completion.

Then call the `Agent` tool:

- `subagent_type: "general-purpose"`
- `model: "haiku"`
- `description: "Scrape <handle> review history"`
- `prompt`: instruct the subagent to run the exact `collect.py` command below and return its stdout verbatim. **The subagent must not interpret, summarise, diff or post-process the output** — its only job is to run the script and report what came back.

Prompt body to send to the subagent:

> Run this command exactly and return its stdout verbatim — it is a single line of JSON (the snapshot).
>
> ```bash
> python3 <plugin>/scripts/collect.py \
>   --alias '<alias>' \
>   --handles '<handles>' \
>   --repo '<repo>' \
>   --months <months> \
>   --paths='<paths>' \
>   --extensions='<extensions>'
> ```
>
> Pass `--paths=''` / `--extensions=''` (empty strings) when there is no filter — never omit the value after the flag. Requires `gh` >= 2.48.
>
> The script writes raw scrape files and `snapshot.json` to `~/.claude/review-clone/<alias>/` and prints per-PR progress to stderr — you do not need to relay the stderr lines. When the command exits, reply with ONLY the JSON snapshot from stdout. If the command fails, reply with the stderr output prefixed `ERROR:`.

**Refresh variant.** Take `<handles>` from the persona frontmatter, joined with commas, and add one more argument to the command: `--since '<last_scanned_at>'` (only comments created since the last scan are collected). Single-quote every value as above.

**Reading the result.** The subagent's final message is the snapshot JSON. Parse it (or re-read `~/.claude/review-clone/<alias>/snapshot.json` from disk). Haiku fetches, Opus reasons: theme extraction and drift detection stay on the main session.

## Render the per-persona slash command

Render `<plugin>/templates/review-as-command.md.tmpl` and write the result to `~/.claude/commands/review-as-<alias>.md`. Create the `~/.claude/commands/` dir if missing.

The template's `description` field encodes the persona summary so it shows up in the slash-command palette. Substitute every placeholder:

| Placeholder | Source |
|---|---|
| `{{ALIAS}}` | `clone-reviewer` Step 1.1 (refresh: the persona's alias) |
| `{{REPO}}` | Step 1.3 (e.g. `wayflyer/wayflyer`) |
| `{{RULE_COUNT}}` | count of rules derived in Step 5 |
| `{{COMMENT_COUNT}}` | `snapshot.counts.review_comments + snapshot.counts.issue_comments` |
| `{{PR_COUNT}}` | `snapshot.counts.prs` |
| `{{WINDOW_MONTHS}}` | Step 1.6 |
| `{{LAST_SCANNED_AT}}` | the ISO timestamp written into PERSONA frontmatter in Step 6 |

The Source column names the first-run source; on refresh use the updated values (rule count after Step 4, new totals, the new `last_scanned_at`).

The description sits inside a double-quoted YAML string, so substituted values must not contain `"`, `\` or newlines: `{{ALIAS}}` is a validated slug, `{{REPO}}` must match `owner/name` (letters, digits, `.`, `_`, `-`), the counts are integers. If any value fails, stop and ask rather than escaping it.

All placeholders are required — do not leave any unsubstituted, and do not invent extra fields. If `{{RULE_COUNT}}` is 0, the persona is unusable; surface that as a warning before writing the file rather than emitting a zero-rule description.
