# Steps 1–3: gather, check, fetch

## Step 1: Gather PR Details

If the user hasn't provided them, infer or ask for:

- **Repository** — detect from the current git remote with `gh repo view --json nameWithOwner -q .nameWithOwner`
- **PR number** — detect from the current branch with `gh pr view --json number -q .number`

After detecting a PR number via `gh pr view`, verify it's the only PR for this branch: run `git branch --show-current`, validate the branch name as `references/commands.md` ("Quoting and validation") describes, then run `gh pr list --head '{branch_name}' --json number,title --jq 'length'`. If the count is >1, list all PRs (`gh pr list --head '{branch_name}' --json number,title,url`) and ask the user to confirm which one to review, even if `gh pr view` succeeded. If `gh pr view` fails because the branch has multiple associated PRs, do the same listing.

If `gh pr view` fails with "no pull requests found", first check if the repo is a fork (`gh repo view --json isFork -q .isFork`). If it is a fork, retry against the parent repo: use `gh repo view --json parent -q .parent.nameWithOwner` as `{owner}/{repo}` for all subsequent API calls. If it is NOT a fork, inform the user: "No open PR found for branch `{branch_name}`. Would you like to provide a PR number or URL directly?"

Only prompt the user if auto-detection fails. If `gh` is not authenticated (`gh auth status` fails), inform the user: "The GitHub CLI is not authenticated. Please run `gh auth login` first, then re-invoke this skill." Do not attempt to continue. If the current directory is not inside a git repository (`git rev-parse --git-dir` fails), inform the user and ask them to navigate to the project directory or provide the repo and PR number directly.

**PR state check:** After detecting the PR, verify its state: `gh pr view {number} --json state,title -q '.state + " " + .title'`. If the state is `MERGED` or `CLOSED`, confirm with the user before proceeding: "PR #{number} ('{title}') is {state}. Is this the one you want to review, or would you like to provide a different PR number?" Always display the detected PR title so the user can catch detection mistakes.

**Branch verification:** After confirming the PR, compare the local branch (`git branch --show-current`) with the PR's head branch (`gh pr view {number} --json headRefName -q .headRefName`). If they differ, inform the user: "You are on branch `{local}` but PR #{number} is on branch `{pr_branch}`. For accurate validation and code changes, I recommend switching: `gh pr checkout {number}`. Would you like me to do this, or proceed with read-only review?" If the user declines to switch, use `gh api 'repos/{owner}/{repo}/contents/{path}?ref={head_sha}'` for Step 5 validation (only for a `{path}` that passes the validation in `references/commands.md`), and in Step 8 inform the user that code changes require being on the PR branch.

When re-invoked after a prior round (user says "run again", "check for new comments"), re-fetch all comments from GitHub (new comments may have been added). Cross-reference against comments already actioned in this session by matching on the GitHub comment `id` field (unique and stable across fetches). A "session" is the current Claude Code conversation — if the user starts a new conversation, all comments are treated as fresh. Apply the resolved-thread filter (Step 3d) AFTER the session cross-reference — comments that were actioned in this session and are now resolved should appear in the "### Previously Actioned (this session)" section with a `[RESOLVED]` tag, even though they would normally be filtered out by the resolved-thread filter. This ensures the user sees a complete picture of what was addressed. Mark other matched comments with `[ACTIONED this session]`. If a previously actioned comment has new replies since the last fetch (compare `created_at` timestamps), present it with `[ACTIONED — new reply]` and show the new reply text. Previously actioned items should appear in a separate "### Previously Actioned (this session)" section at the end of Step 7 to keep them distinct from new unresolved items.

## Step 2: Check for Pending Bot Reviews

Before fetching comments, check if any bot reviews are still running on the PR's head commit:

Command: `references/commands.md`, section "Step 2: check-runs on the head commit".

Get the head SHA with:

Command: `references/commands.md`, section "Step 2: head SHA".

Filter check runs to identify review-generating bots: compare each check run's `app.slug` or `app.name` against the known agent list (section "Known Agent Usernames" below; e.g., slugs containing "coderabbit", "cubic", "augment", "copilot"). Ignore CI, deploy, and security checks — they don't produce review comments. If you cannot determine whether a check produces review comments, include it with a caveat: "(may not produce review comments)."

Some bots report through the commit-status API rather than as check runs. Also run the commit-status command (`references/commands.md`, section "Step 2: commit statuses"); on a best-effort basis, treat a `state: pending` status whose `context` matches a known agent as a review still running, with the same caveat for contexts you cannot attribute.

If any review-related check runs have `status: "in_progress"` or `status: "queued"`, inform the user:

> "X bot review(s) are still running: [list app names and status]. Would you like to wait or proceed with what's available?"

If the user chooses to wait, stop here. The user can re-run the skill when they're ready — do not poll or block the agent.

If the user chooses to proceed, continue to Step 3 immediately with a note that some feedback may still be incoming.

If all check runs are already completed, or if the check-runs response returns zero check runs (common for draft PRs where CI has not been triggered), skip this step silently.

## Step 3: Fetch All Comments

Three separate API calls are required — GitHub stores these independently. Use the `gh` CLI which handles authentication automatically.

### 3a. PR Review Comments (inline, on specific lines of code)

Command: `references/commands.md`, section 3a.

### 3b. PR Issue Comments (top-level comments on the PR thread)

Command: `references/commands.md`, section 3b.

### 3c. PR Reviews (approve/request changes/comment review submissions)

Command: `references/commands.md`, section 3c.

The `--jq` projections keep only the fields needed below; do not dump full API JSON into context. Parse and merge all three result sets into a unified comment list before proceeding. For each comment, retain at minimum: `source_api` (review_comment | issue_comment | review), `author`, `body`, `path` (if any), `line` (if any), `start_line` (if any — present for multi-line comments), `position` (null means the diff anchor is outdated), `commit_id`, `pull_request_review_id` (if any), `in_reply_to_id` (if any), `created_at`. When processing reviews (3c), deduplicate review submissions by author — keep only the latest review per reviewer whose state is `APPROVED`, `CHANGES_REQUESTED` or `DISMISSED` to determine the effective review state (used in the Step 7 header); ignore `COMMENTED` and `PENDING` reviews for state, so a later comment-only review never masks an earlier `CHANGES_REQUESTED`. However, inline review comments (from 3a) associated with earlier reviews must still be processed — deduplication applies only to the review-level state, not to individual comments. All unresolved inline comments are processed regardless of which review submission they belong to. Group threaded replies using `in_reply_to_id` — review comments that are replies to an earlier comment should be associated with the parent comment rather than treated as independent items. Present only the root comment as the reviewable item; append reply context as conversation history beneath it.

### 3d. Thread resolution status

The REST API does not include whether a review thread has been resolved. Use GraphQL to fetch this before presenting comments:

Command: `references/commands.md`, section 3d.

`--paginate` follows `pageInfo.endCursor` automatically, so all threads are fetched before any stop condition below is evaluated. Variables (not spliced literals) keep owner, repo and number out of the query text. Use `-f` for the string variables (owner, repo) so they are never type-coerced (`-F` would turn a numeric-looking repo name into an Int); `-F` is only for `number`.

Filter out resolved threads — only present unresolved comments in the default triage workflow. If the user explicitly requests to see all comments (e.g., "show all comments", "include resolved"), skip the resolved-thread filter and present all comments, marking resolved threads with a `[RESOLVED]` tag in the Step 7 output under a separate "### Already Resolved" section at the end.

Once ALL pages are fetched, and only in the default triage and "resolve threads" modes (never for the progress report or "show all" requests, which need resolved threads): if zero unresolved review threads remain AND there are no issue comments (from 3b) with actionable content AND there are no review submissions (from 3c) with non-empty bodies containing additional commentary beyond inline comment summaries, inform the user ("No unresolved comments found") along with the current review status from 3c (e.g., "No unresolved comments found. Review status: Approved by @reviewer1, @reviewer2.") and stop. Bot walkthrough or summary issue comments (e.g. CodeRabbit walkthroughs) with no actionable content are non-blocking for this test.

**Correlating REST comments with GraphQL threads:** Join on `databaseId` of the thread's first comment == the REST review comment `id` from 3a. This is exact and survives outdated threads (where `line` is null). Only if no `databaseId` match exists, fall back to the heuristic: `path` + `line` + `author.login` + body prefix (first 100 chars), and label that thread's match "low confidence". Step 9 must not resolve a thread with `viewerCanResolve: false`. The GraphQL thread `id` is needed later for resolving — store the mapping `{thread_id → comment}` in the agent's working context during this step (retain in conversation memory for use in Step 9; for large PRs with >100 review threads, write to a temporary file alongside comment data). The `comments(first: 1)` fetches only the thread-starting comment for matching; full comment details are already available from REST calls 3a–3c. If a GraphQL thread cannot be matched to any REST comment (e.g., comment deleted or review dismissed), present it as a standalone item using the GraphQL thread's first comment data (path, author, body). Mark it as "Unmatched thread" and include the thread ID for potential resolution.

### Preprocessing

Before categorising, strip noise from comment bodies:

- Remove HTML comments (`<!-- ... -->`) using non-greedy matching (per block, not across blocks) — agent tools like Cubic embed verbose metadata, tool call logs, and attribution notices inside these. Multiple disjoint `<!-- -->` blocks may appear with real review text in between
- Remove marketing badges, "Fix All" buttons, and other promotional markup from agent comments
- Extract only the human-readable review text for analysis
- Preserve GitHub suggestion blocks (` ```suggestion ... ``` `) — these contain machine-applicable code changes. In Step 7's proposed fix, note these as "GitHub suggestion — can be applied directly." When actioning in Step 8, verify the suggestion doesn't introduce syntax errors or new issues; if it does, propose a corrected version rather than applying the broken suggestion. For duplicate suggestions from multiple reviewers on overlapping line ranges (compare `start_line` through `line`; if `start_line` is null, treat as single-line at `line`), compare suggestion content: if identical, condense; if different, treat as conflicting feedback
- When a review body (from 3c) substantially repeats content from its associated inline comments (from 3a, matched by `pull_request_review_id`), treat the review body as a summary. Extract any additional commentary not covered by inline comments and discard duplicated portions. If the review body contains only a summary of inline comments with no additional content, omit it entirely.

If the user specifies a particular reviewer (e.g., "show me Cubic's comments", "what did @augmentcode say"), filter comments after Step 3 to include only those from the specified author(s). Match informal names against all fetched comment authors using substring/prefix matching (e.g., "cubic" matches "cubic-dev-ai", "cubic[bot]"). If multiple authors match, list them and ask the user to clarify. If no authors match, list all unique comment authors found. Still show total comment count and review status from all reviewers in the Step 7 header, but present detailed items only for the requested reviewer(s).

#### Known Agent Usernames

Classify the following as `agent` sources automatically:

- `github-actions`, `dependabot`, `renovate`, `codecov`, `sonarcloud`, `coderabbitai`
- `codeclimate`, `snyk-bot`, `lgtm-com`, `imgbot`, `greenkeeper`, `copilot`, `cubic`, `augment`
- Any username ending in `[bot]`, `-bot`, or `_bot` (requires a separator before `bot` to avoid misclassifying human usernames like `abbot`), or starting with `cubic-` or `augment-` (case-insensitive)

## Large PRs and common mistakes

- **Large PRs**: If >100 comments, keep only the `--jq` projections from Step 3 rather than holding raw API output in context (never redirect `gh` output in the shell). Process comments in batches by file or priority tier. In Step 7, present only Critical and High items by default and offer to expand Medium/Low on request. The >50 threshold in Step 5 still applies for validation batching

| Mistake | Fix |
|---------|-----|
| Using `position: null` to mean "resolved" | It means outdated diff position — comment may still be valid |
| Missing paginated results | Always use `--paginate` with `gh api` |
| Ignoring PR-level issue comments | These have no `pull_request_review_id` — group separately |
