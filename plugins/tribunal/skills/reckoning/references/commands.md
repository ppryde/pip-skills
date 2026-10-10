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
