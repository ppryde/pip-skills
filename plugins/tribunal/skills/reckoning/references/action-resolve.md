## Step 8: Confirm Before Actioning

**Branch guard:** Before applying any code changes, verify the current branch matches the PR's head branch (`git branch --show-current` vs the head branch detected in Step 1). If they differ, inform the user: "You are on branch `{current}` but the PR targets `{pr_branch}`. Code changes would be applied to the wrong branch. Would you like me to switch to the PR branch first (`gh pr checkout {number}`)?" Do not proceed with code changes without user confirmation to switch or an explicit override.

**Always present the full review first and wait for user approval.**

After presenting, ask:

> "Which of these would you like me to action? You can say 'all critical', list specific items, or approve them one by one."

If the user requests a category (e.g. "all critical") that contains zero items, inform them: "There are no [category] items. Would you like to action a different priority tier?"

For conflicting feedback items, always ask the user which approach to follow before actioning, even if the user said "all" for that priority tier. Present the conflict clearly with both options and wait for a decision.

If the user says "all" without specifying a priority tier, interpret as all items across all tiers. Apply the same conflict-handling rule. For items assessed as "Likely invalid", confirm once before actioning them as a group: "X items were assessed as Likely invalid. Do you still want me to action these?"

Users may reference items by their labels (C1, H2, M3, L1, etc.) for inclusion or exclusion. If the user references a label that was not assigned in Step 7 (e.g., "H3" when only H1 and H2 exist), inform them immediately and list the available items for that tier. Support natural exclusion phrasing like "action everything except H2" or "skip M3, do the rest." "Skip" means do not action the item in this pass — it remains OUTSTANDING for future runs. "Dismiss" means the user explicitly chose not to action — mark as DISMISSED in session tracking with a brief reason. Dismissed items are excluded from the Step 9 resolution offer and will appear as DISMISSED in subsequent PR Progress Summary reports.

Only proceed to make code changes after explicit user confirmation. Never auto-apply fixes.

When actioning approved fixes:

- Make changes in the relevant files using available file tools
- Reference the comment being addressed in any commit message suggestions
- Track which comments were successfully actioned throughout the process
- If a fix cannot be applied (e.g., edit match fails, file is read-only, merge conflict), mark that item as "action failed" with the specific error, inform the user immediately, and continue to the next approved item. Do not offer to resolve threads for items where the action failed. After all items are attempted, report the summary: N succeeded, M failed (with reasons).
- Before modifying a file, check if it appears to be generated or vendored (indicators: `vendor/`, `generated/`, `node_modules/`, `__generated__` directory; "DO NOT EDIT" header; lock files like `package-lock.json` or `poetry.lock`). If so, do not modify it directly — inform the user the fix should be applied to the source that generates the file and mark the proposed fix as "requires upstream change." Note: Alembic migrations are routinely hand-edited — treat them as regular code files.

## Step 9: Resolve Actioned Threads

After all approved fixes have been applied, offer to resolve the actioned comment threads on GitHub. Present this as a single prompt listing only the comments that were actually fixed:

> "I've actioned X comments. Would you like me to resolve these threads on GitHub?" [list the specific comments with file:line and a short description]

Do **not**:

- Resolve comments automatically — always ask once after all fixes are done
- Resolve comments that were not actioned in this session
- Resolve comments where the fix confidence was Medium or lower without explicitly noting this
- Batch-resolve all comments — only the specific ones the user approved and that were successfully applied

When resolving, use the thread `id` values already fetched in Step 3d and the `resolveReviewThread` GraphQL mutation:
Command: `references/commands.md`, section "Step 9: resolve a thread".

Do **not** use `minimizeComment` — that hides comments behind a fold (moderation action), which is not the same as resolving a review thread.

Top-level issue comments (from 3b) have no review thread — they cannot be resolved via GraphQL. Skip them during resolution and inform the user if any actioned items were issue comments.

If the user asks to "resolve all" comments, clarify: "I can resolve the X threads that were actioned in this session. Resolving comments that weren't addressed could hide unactioned feedback. Would you like me to resolve just the actioned ones, or do you specifically want all threads resolved?" If the user confirms all, proceed — the user's explicit instruction overrides the default safeguard.

## Notices and common mistakes

- **Closed or merged PRs**: If `gh pr view` shows state `MERGED` or `CLOSED`, include a notice in the Step 7 header. For merged PRs, proceed normally (user may want to review feedback or resolve threads). For closed (unmerged) PRs, ask before proceeding past Step 7: "This PR is closed and not merged. Code changes would apply to the branch but won't reach the target. Would you like to proceed with actioning, or just review the summary?"

| Mistake | Fix |
|---------|-----|
| Resolving threads before user confirms | Always ask after all fixes are applied |
| Auto-applying fixes without approval | Present first, wait for explicit confirmation |
| Confusing `minimizeComment` with resolve | `minimizeComment` is moderation; use `resolveReviewThread` |
