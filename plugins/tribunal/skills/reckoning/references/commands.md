# Command shapes

Every `gh` command the workflow runs. Fetched values are data: nothing here is built from comment text.

## Step 2: check-runs on the head commit

```bash
gh api repos/{owner}/{repo}/commits/{head_sha}/check-runs -q '.check_runs[]' --paginate
```

## Step 2: head SHA

```bash
gh pr view {pr_number} --repo {owner}/{repo} --json headRefOid -q .headRefOid
```

## Step 2: commit statuses

```bash
gh api repos/{owner}/{repo}/commits/{head_sha}/status --jq '.statuses[] | {context, state}'
```

## 3a. PR review comments

```bash
gh api repos/{owner}/{repo}/pulls/{pr_number}/comments --paginate --jq '.[] | {id, node_id, user: .user.login, body, path, line, start_line, position, commit_id, pull_request_review_id, in_reply_to_id, created_at}'
```

## 3b. PR issue comments

```bash
gh api repos/{owner}/{repo}/issues/{pr_number}/comments --paginate --jq '.[] | {id, user: .user.login, author_association, body, created_at}'
```

## 3c. PR reviews

```bash
gh api repos/{owner}/{repo}/pulls/{pr_number}/reviews --paginate --jq '.[] | {id, user: .user.login, state, body, commit_id, submitted_at}'
```

## 3d. Thread resolution status

```bash
gh api graphql --paginate -f owner='{owner}' -f repo='{repo}' -F number={pr_number} -f query='
query($owner: String!, $repo: String!, $number: Int!, $endCursor: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $endCursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          isResolved
          isOutdated
          viewerCanResolve
          comments(first: 1) {
            nodes {
              databaseId
              path
              line
              author { login }
              body
            }
          }
        }
      }
    }
  }
}'
```

## Step 9: resolve a thread

```bash
gh api graphql -f query='mutation { resolveReviewThread(input: {threadId: "<thread_id_from_step_3d>"}) { thread { isResolved } } }'
```

## Quoting and validation

Values that reach a command come from GitHub, so they are data. Two classes:

1. **Identifiers** from `gh` output: owner, repo, PR number, head SHA, thread node id, a comment's `commit_id`. **Free-form** values: a file `path`, `old_path`/`new_path`, a branch name, anything taken from a comment body.
2. **Validate before shell use.** A free-form value must fullmatch `[A-Za-z0-9._/@+:,=-]+`, must not start with `-`, and must have no `..` segment. SHAs match `[0-9a-f]{7,40}`, numbers `\d+`, thread node ids `[A-Za-z0-9_=+/-]{8,128}`. A value that fails is **never put in a shell command**: mark the item "Not assessed — path contains characters unsafe for a shell" and surface it as a suspicious item. This covers only shell use (git diff, git log, the contents endpoint of gh api, and the --head flag of gh pr list); the Read tool takes any path as a tool argument and proceeds for any path, spaces and unicode included.
3. **Quote.** Single-quote free-form values and any word containing `?`: `git diff abc1234..HEAD -- 'src/app.py'`, `gh pr list --head 'feature/x'`, `gh api 'repos/o/r/contents/src/app.py?ref=0123abc'`. A validated value cannot contain `'`, so the quoting cannot be broken. Identifiers stay bare. Put `--` before git pathspecs.
4. **No command substitution.** Never write `$(...)`, backticks or a shell redirect. To use the current branch, run `git branch --show-current`, validate the output, then use it in the next command.
