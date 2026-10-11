## Step 6: Prioritise

Assign a priority to each comment:

| Priority | Criteria                                                      |
| -------- | ------------------------------------------------------------- |
| Critical | `blocking` or `security` — must fix before merge              |
| High     | `logic` or `tests` — should fix before merge                  |
| Medium   | `style` or `docs` — fix if time allows                        |
| Low      | `suggestion`, `question`, `praise` — optional / informational |

Also flag:

- **Duplicate concerns** — multiple reviewers flagging the same issue with the same or compatible solutions. Condense duplicates into a single line item noting all sources (e.g. "flagged by @cubic-dev-ai and @augmentcode"). If multiple reviewers identify the same problem but only one proposes a solution, treat as a duplicate using the proposing reviewer's fix
- **Conflicting feedback** — two reviewers suggesting incompatible or mutually exclusive solutions for the same issue on overlapping file+line ranges (surface for user decision). Conflicting items retain their priority labels (C1, H2, etc.) and appear in their priority tier with a cross-reference: "See Conflicts Detected below." The Conflicts Detected section presents the competing fixes side by side using the same labels
- **Patterns** — when multiple comments share a root cause or theme (e.g. "5 comments all relate to version removal"), condense them into a single grouped item rather than listing each individually. Reference all affected files within the group.

## Step 7: Present the Review

Output a structured summary in this format:

```
## PR #[number] Review Summary
**Repo:** owner/repo
**Total comments:** X (Y from agents, Z from humans)
**Review status:** [Changes Requested / Approved / Mixed / No formal reviews yet]
  (Approved = all reviewers approved; Changes Requested = any non-dismissed CHANGES_REQUESTED; Mixed = both exist; No formal reviews yet = only COMMENT-state reviews, no APPROVED or CHANGES_REQUESTED)
  Note: Bot CHANGES_REQUESTED reviews count toward review status. If the only blocking review is from a bot, append "(by bot only — may not block merge depending on branch protection settings)."

### Critical (must fix before merge)
**[C1]** `FILE:LINE[ — on older commit]` or PR-level · [agent|human] · @author · [validity]
> "[comment text]"
**Proposed fix:** [Specific code change or action]

### High Priority
**[H1]** [same format, numbered H1, H2, ...]

### Medium Priority
**[M1]** [same format, numbered M1, M2, ...]

### Low / Informational
**[L1]** [summarised as a group, numbered L1, L2, ...]

### Conflicts Detected
[conflicting feedback surfaced here]

### Patterns
[e.g. "8 comments relate to error handling"]
```

For comments assessed as "Likely invalid", include a brief reason why (e.g. "code has already been updated", "comment references a pattern not present in current diff").

If the user requests a specific category or priority tier (e.g., "just security issues", "show me the critical items"), run Steps 1–6 as normal but present only the requested tier/category in full detail. Include a one-line count summary of other tiers (e.g., "Also found: 3 High, 5 Medium, 2 Low — say 'show all' to expand"). Step 8 actions apply only to the displayed items unless the user expands.

## Notices for the Step 7 header

- **Draft PRs**: If `gh pr view` shows the PR is in draft state, include a notice in the Step 7 summary header: "**Note:** This PR is in draft state. Reviewer feedback may be incomplete." Proceed with the full workflow otherwise — draft PRs can still have actionable review comments
- **Closed or merged PRs**: If `gh pr view` shows state `MERGED` or `CLOSED`, include a notice in the Step 7 header. For merged PRs, proceed normally (user may want to review feedback or resolve threads). For closed (unmerged) PRs, ask before proceeding past Step 7: "This PR is closed and not merged. Code changes would apply to the branch but won't reach the target. Would you like to proceed with actioning, or just review the summary?"
