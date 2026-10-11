# review-as: mode refresh

## Mode: refresh

### 1 — Pull since last scan (Haiku subagent)

Refresh is pure data gathering — no reasoning happens here. Drift detection and rule updates (Steps 3–4) stay on the main Opus session. Dispatch the collector as the **refresh** variant in `<plugin>/references/collect-and-render.md` (read it now): handles from frontmatter joined with commas, `--months`, `--paths`/`--extensions` from the persona's filters, plus `--since '<last_scanned_at>'`. Its reply is the snapshot JSON: parse it (or re-read `~/.claude/review-clone/<alias>/snapshot.json`) and continue from Step 2.

### 2 — Pre-extract gate

Read the new snapshot.json. Display delta counts. If `counts.prs > 100 OR counts.review_comments + counts.issue_comments > 200`, prompt to confirm before extracting.

### 3 — Drift detection (LLM-judged)

For each newly-derived rule:
- Compare against existing rules in PERSONA body. Look for direct contradictions ("use X" vs "use Y" on the same surface area).
- On contradiction: newer wins. Mark old rule with `superseded_by: <new rule id>`. Append drift entry via `persona_io.append_drift_entry`:

  ```python
  {"date": "<iso>", "summary": "Rule X superseded by Y", "url": "<new citation>"}
  ```

- Honor withdrawals from new comment reply threads. Don't derive from withdrawn comments.

### 4 — Update PERSONA.md

- Bump `last_scanned_at`
- Update `snapshot:` counts: new totals = previous totals + the delta from this refresh's snapshot (comments are already limited to those created since the last scan)
- Append/modify rules
- Refresh voice patterns if new openers/quirks emerge
- Drift log auto-caps via `persona_io.append_drift_entry`

### 4b — Re-render the per-persona slash command

The slash-command file at `~/.claude/commands/review-as-<alias>.md` embeds the persona summary in its `description`. After Step 4 changes any of: rule count, snapshot counts, or `last_scanned_at` — re-render it as described under "Render the per-persona slash command" in `<plugin>/references/collect-and-render.md` and overwrite the command file. Do not skip this — a stale description is misleading.

### 5 — Print delta

> Refreshed `<alias>` from `<old_scanned>` → `<new_scanned>`.
> +<N> rules · <M> superseded · <K> voice refinements
