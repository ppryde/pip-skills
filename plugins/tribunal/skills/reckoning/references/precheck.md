# Step 0: has anything changed?

One small, pre-approved command decides whether the full workflow needs to run at all. It runs in
the main session, before any subagent.

## The command

Command: `references/commands.md`, section "Step 0: activity pre-check". It returns the head SHA,
review and comment counts, and the newest review or comment timestamp. Every inline comment,
reply included, belongs to a review, so `newest` covers inline threads too.

## The state file

`~/.local/state/reckoning/<owner>-<repo>-<pr_number>.json`, outside the plugin folder because
plugin updates replace it. Read it with the Read tool; a missing file means "never checked".

```json
{"checked_at": "...", "head_sha": "...", "newest_activity": "...",
 "unresolved": 3, "summary": "3 unresolved: 1 High, 2 Low"}
```

The subagent writes it with the Write tool at the end of Step 7 (and progress mode's report),
using the pre-check values and its own unresolved count and one-line summary.

## Deciding

| Pre-check vs state | Do |
|---|---|
| No state file | Full run |
| `newest` is later than `newest_activity` | Full run |
| Same `newest`, same head SHA | **Stop.** Reply: "No new comments or reviews since `<checked_at>` — `<summary>`." |
| Same `newest`, new head SHA | Run Step 2 (bot check) only. A bot still running → ask whether to wait, as Step 2 does. None → stop as above. |

Always do the full run, skipping this step, when the user asks for a progress report, a full
history, or says "check again from scratch", and in resolve-threads mode.

The shortcut misses edits to an existing comment and threads resolved on GitHub since the last
run. Both mean nothing new to triage, so the stored summary may overcount; say "as of
`<checked_at>`".
