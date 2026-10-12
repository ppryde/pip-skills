# review-clone: collect and render (shared by `clone-reviewer` and `review-as`)

One copy of the collector dispatch and the slash-command render, read by `clone-reviewer` (Steps 3 and 7) and by `review-as` refresh (Steps 1 and 4b). `<plugin>` is the absolute path of the `review-clone` plugin directory in this Claude Code install. `<persona dir>`, `<raw dir>`, `<commands dir>` and the persona's other paths come from `python3 <plugin>/scripts/persona_io.py paths --alias '<alias>'` (JSON): they root at `${CLAUDE_CONFIG_DIR:-~/.claude}`, so each account keeps its own personas. Never hardcode `~/.claude`.

## Collect (`pip-agents:gatekeeper`)

Data collection is pure I/O: `gh` API calls and file writes, no reasoning. It runs through the `pip-agents` plugin's **gatekeeper** (a declared dependency; haiku; Bash and Read only), which runs the one command it is briefed with and returns a result envelope holding the snapshot **path and counts**, never the corpus. Do not run `collect.py` directly from this session, and do not pipe its stdout back into it: read `snapshot.json` from disk when you need it.

**Quoting untrusted values.** `<handles>`, `<repo>`, `<paths>` and `<extensions>` are user-supplied (or derived from the checkout's `origin`), so treat them as hostile. Put each in **single quotes**, escaping any embedded `'` as `'\''`; never double quotes (those still run `$(...)` and backticks). `gate.py` re-checks them and refuses: `<repo>` must be `owner/name` (`[A-Za-z0-9._-]+/[A-Za-z0-9._-]+`), each handle `[A-Za-z0-9-]+`, each path or extension `[A-Za-z0-9._/@+-]+`, `--since` an ISO date. If a value fails or contains a newline or NUL, stop and say so.

1. **Brief.** Make a scratch dir (`mktemp -d -t review-clone.XXXXXX`, on its own), then run

   ```bash
   python3 <plugin>/scripts/gate.py brief-collect --alias '<alias>' --handles '<handles>' --repo '<repo>' --months <months> --paths='<paths>' --extensions='<extensions>' --work-dir '<scratch>'
   ```

   Pass `--paths=''` / `--extensions=''` (empty strings) when there is no filter, never omit the value. Add `--incremental` (refresh) or `--since '<iso>'`. It prints `brief` (a path), `prompt` (the brief text) and `out` (the snapshot path), or `{"status":"error"}`: stop and show it. The collector needs `gh` >= 2.48; it writes the raw scrape, `digest.jsonl` and `snapshot.json` to the persona dir (private: 0700/0600), fetches 3 PRs at a time, backs off on rate limits and checkpoints each PR.

2. **Tell the user** before dispatching: clone: > Pulling `<handle>`'s comments via the gatekeeper. No live progress; I'll surface the summary when it finishes. Refresh: > Refreshing `<alias>` via the gatekeeper. No live progress; summary on completion.

3. **Dispatch.** Call `Agent` with `subagent_type: "pip-agents:gatekeeper"`, `description: "Scrape <handle> review history"` and `prompt` = the `prompt` from step 1, unchanged. The gatekeeper runs the command once with a 600000 ms timeout and never retries or alters it.

4. **Check.** Write its final message to a file with the Write tool and run `python3 <plugin>/scripts/gate.py check-collect --brief '<brief path>' --message '<message file>'`:
   - `ok` → `snapshot` (the path) and `counts` (`pr_count`, `comment_count`, `error_count`). Read that file and continue.
   - `failed` → the collector exited non-zero or timed out; show `stderr_tail`. If it was cut off, run step 3 again with the same brief: it resumes from the checkpoint.
   - `refused` → the gatekeeper declined the command (`error` says why): stop and show it.
   - `rejected` → the reply was not a valid envelope (`errors`); dispatch once more with the same brief, then stop and show the errors.

**Refresh variant.** Take `<handles>` from the persona frontmatter, joined with commas, and add `--incremental` to `brief-collect` (starts from the `watermark` in the persona's `snapshot.json`; use `--since '<last_scanned_at>'` instead when there is no snapshot yet). Only comments created since then are collected and merged into `raw/`; nothing old is lost. `digest.jsonl` is rebuilt as the full corpus and `digest-new.jsonl` holds just the new comments. If any PR failed, the watermark is held back so the next run retries them.

**Reading the result.** The snapshot carries `counts`, `errors` (PRs that failed after retries; the rest are kept, re-run the command to retry them), `search_truncated` (a handle hit gh's 1000-result limit: narrow the window), `private_source`/`visibility`, `watermark` (newest comment collected), `digest` (`file`, `items`, `bytes`) and, on a refresh, `digest_new`. Collecting is the gatekeeper's, reasoning is yours: theme extraction and drift detection stay on the main session, reading the digest.

**Other collector commands** (run by absolute path, no subagent needed): `collect.py check --repo '<repo>'` (visibility and your permission, writes nothing), `collect.py digest --alias '<alias>' [--since '<iso>']` (rebuild the digest; with `--since` it writes `digest-new.jsonl` and leaves the full digest alone), `collect.py cleanup --alias '<alias>'` (delete `raw/`, both digests and the checkpoint; only the account's own persona dir, never legacy `~/.claude/review-clone/` data; the persona, snapshot and command stay).

## Render the per-persona slash command

Render `<plugin>/templates/review-as-command.md.tmpl` and write the result to `<commands dir>/review-as-<alias>.md` (`command_file` from `persona_io.py paths`). Create the commands dir if missing.

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
