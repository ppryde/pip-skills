## PR Progress Summary (explicit request only)

This is **not** the default mode — only triggered by the phrases listed in the Mode Selection section of `SKILL.md`. This mode has higher token usage as it covers all review iterations, not just the latest unresolved comments.

Judge each comment's priority directly from its content, using four tiers: Critical = blocks merge or is a security issue; High = a logic error or a missing or wrong test; Medium = style or documentation; Low = a suggestion, question, or praise.

Produce a round-by-round table showing the full lifecycle of PR review feedback.

Group comments by review round — each distinct review submission from a bot or human is a round. PR-level issue comments (from Step 3b) that have no `pull_request_review_id` should be grouped into a separate "General comments" section rather than omitted.

For each round, show:

- **Round header:** reviewer name, number of issues, which commit triggered the review
- **Table columns:** issue number, short issue description with priority, current status

### Status values

| Status | Meaning |
| --- | --- |
| FIXED in {sha} | Fix committed — reference the short SHA |
| RESOLVED | Thread resolved on GitHub (may not have required a code change) |
| OUTSTANDING | Not yet addressed |
| STALE | Comment's target commit differs from HEAD — the code has since changed. Note: this is a semantic assessment based on comparing the review's `commit_id` to the current HEAD, distinct from `position: null` which is a GitHub API detail about diff anchoring. They often correlate but are determined differently. |
| DISMISSED | User explicitly chose not to action (include brief reason) |
| N/A | Not applicable (e.g. docs-only comment on a non-code file) |

### Round format

Use simple markdown tables (not ASCII box-drawing characters — they break across terminals):

```
Review Round 1: reviewer_name (N issues) — on commit abc1234
| # | Issue | Status |
|---|-------|--------|
| 1 | Description (priority) | FIXED in abc1234 |
| 2 | Description (priority) | OUTSTANDING |
```

To build this summary, cross-reference:

1. **Review submissions** — group comments by their `pull_request_review_id` and the review's `commit_id` to determine the round and triggering commit
2. **Thread resolution status** — from the GraphQL reviewThreads query (see "Thread resolution status" section)
3. **Git log** — to determine FIXED status: (a) check if the thread is resolved on GitHub (from GraphQL), (b) check if a subsequent commit modified the file at or near the referenced line range (`git log --oneline <review_commit>..HEAD -- '<path>'` (path validated per `references/commands.md`)), (c) check if the commit message references the issue or review round. Mark as FIXED only if (a) is met, or (b)+(c) together. If only (b) is met, mark as "LIKELY FIXED — file modified in {sha}, thread still open"
4. **Session history** — track which comments were actioned, dismissed, or skipped during the current session

This summary can be requested at any point during the workflow. It does not require re-fetching comments if data is already in context.

## Common mistakes

| Mistake | Fix |
|---------|-----|
| Skipping data fetch in progress report mode | Progress report still needs Steps 1–3 — only Steps 4–9 are skipped |
