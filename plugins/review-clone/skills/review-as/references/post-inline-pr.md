# review-as: post inline to PR (`post-inline-pr`)

Only when the selected output is `post-inline-pr`. Every message posted to the PR — inline comment **and** summary — is prefixed `[From <alias>]:` so a human can never mistake the clone for the real reviewer. `<alias>` is the slug verbatim, not a display name.

**1 — Resolve the PR.** 

```bash
gh pr view --json number,url
```

The PR `url` (`https://github.com/<owner>/<repo>/pull/<n>`) is on the repo the PR targets (the base repo, not the head fork); take `<owner>` and `<repo>` from it below.

If there is no open PR for the branch, do NOT post:

> No open PR for `<branch>`. Falling back to chat output.

Then emit via 6a and stop.

**2 — Zero findings.** Do not post anything. Emit the persona's "nothing to say" line and stop.

**3 — Confirmation gate (never auto-post).** Split findings into *anchorable* (have `path`/`line`/`side`) and *un-anchorable*. Print a preview and wait for an explicit yes:

> About to post to PR #`<n>`: `<N>` inline comments + `<M>` general. Proceed? (y/n)

On "no" → fall back to 6a, do not post.

**4 — Post one batched review.** Build each comment body as `[From <alias>]: <severity> — <comment>` followed by a blank line and `Citation: <url>`. **Never interpolate finding text into a shell string** (backticks and `$(...)` would be executed): create a temp path by running `mktemp -t review-as.XXXXXX` on its own, then write the review payload (valid JSON, finding text as JSON strings) to that path with the **Write tool**, never via a bash heredoc, `echo`, or `python -c` with the text inline. Submit it with `--input`:

```bash
gh api repos/<owner>/<repo>/pulls/<n>/reviews --input <payload.json>
```

Payload shape: `{"event": "COMMENT", "body": "<summary>", "comments": [{"path": ..., "line": <number>, "side": "RIGHT"|"LEFT", "body": ...}, ...]}`. `line` is a number; for `LEFT` it is the line in the old file.

**5 — Un-anchorable findings.** Bundle them into the review's summary `body` (also prefixed `[From <alias>]:`) in the same payload. If there are *no* anchorable findings, create another temp path with `mktemp -t review-as.XXXXXX` (run on its own), write the bundled text there with the **Write tool**, and post it as a single general comment:

```bash
gh pr comment <n> --body-file <body.md>
```

**6 — On failure.** If the call returns 422 because an anchor is not in the diff, retry once with the unplaceable findings moved into the summary `body`. For any other failure, or if the retry fails, surface the error verbatim and emit the findings to chat (6a) so nothing is lost.

**7 — Confirm.** On success:

> Posted `<N>` inline + `<M>` general to PR #`<n>` as `[From <alias>]:`.
