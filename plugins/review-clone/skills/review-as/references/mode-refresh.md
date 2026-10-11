# review-as: mode refresh

## Mode: refresh

### 1 — Pull since last scan (Haiku subagent)

Refresh is pure data gathering — no reasoning happens here. Drift detection and rule updates (Steps 3–4) stay on the main Opus session. Dispatch the collector as the **refresh** variant in `<plugin>/references/collect-and-render.md` (read it now): alias and repo from the persona frontmatter (`<repo>` is validated as the reference requires), handles from frontmatter joined with commas, `--months`, `--paths`/`--extensions` from the persona's filters, plus `--since '<last_scanned_at>'`. Its reply is the snapshot JSON: parse it (or re-read `snapshot.json` in the persona dir; `persona_io.py paths --alias '<alias>'` prints it) and continue from Step 2. New comments are merged into `raw/`; nothing old is lost.

### 2 — Pre-extract gate

Read the new snapshot.json. Display delta counts, and `errors` if any (PRs that failed; re-running the collector retries only those). Read the new comments from `snapshot.digest.file` (`digest.jsonl`: only comments since the last scan), not from `raw/`; open one `raw/pr-<n>.json` only when a comment needs its full text. If `counts.prs > 100 OR counts.review_comments + counts.issue_comments > 200`, prompt to confirm before extracting.

### 3 — Drift detection (LLM-judged)

For each newly-derived rule:
- Compare against existing rules in PERSONA body. Look for direct contradictions ("use X" vs "use Y" on the same surface area).
- On contradiction: newer wins. Mark old rule with `superseded_by: <new rule id>`. Record it as a drift entry: write this JSON to a temp file with the Write tool (`mktemp -d -t review-clone.XXXXXX` on its own), then run `python3 <plugin>/scripts/persona_io.py drift --alias '<alias>' --entry <entry.json>` (the log is capped at 20; older entries archive to `drift.log`):

  ```json
  {"date": "<iso>", "summary": "Rule X superseded by Y", "url": "<new citation>"}
  ```

- Honor withdrawals from new comment reply threads. Don't derive from withdrawn comments.

### 4 — Update PERSONA.md

Take frontmatter and body from `persona_io.py read`, edit them, then save with `persona_io.py write` (frontmatter JSON file + body file written with the Write tool). Writes always land in the account's persona dir, so a persona found under the old `~/.claude/review-clone/` location moves there on its first refresh; the old copy is left untouched. For the frontmatter alone, `persona_io.py update --alias '<alias>' --set <part.json>` merges top-level keys.

- Bump `last_scanned_at`
- Update `snapshot:` counts: new totals = previous totals + the delta from this refresh's snapshot (comments are already limited to those created since the last scan)
- Append/modify rules
- Refresh voice patterns if new openers/quirks emerge
- The drift log caps itself (see Step 3)

### 4b — Re-render the per-persona slash command

The slash-command file (`command_file` from `persona_io.py paths`) embeds the persona summary in its `description`. After Step 4 changes any of: rule count, snapshot counts, or `last_scanned_at` — re-render it as described under "Render the per-persona slash command" in `<plugin>/references/collect-and-render.md` and overwrite the command file. Do not skip this — a stale description is misleading.

### 5 — Print delta

> Refreshed `<alias>` from `<old_scanned>` → `<new_scanned>`.
> +<N> rules · <M> superseded · <K> voice refinements
