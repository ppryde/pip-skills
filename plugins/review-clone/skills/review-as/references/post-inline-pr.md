# review-as: post inline to PR (`post-inline-pr`)

Only when the selected output is `post-inline-pr`. Every message posted to the PR is prefixed `[From <alias>]:` so a human can never mistake the clone for the real reviewer. `<alias>` is the slug verbatim, not a display name. Anchoring, the PR/head check, the batched review and the 422 handling are code: `<plugin>/scripts/prreview.py` (a byte-identical copy of review-panel's). You never build the GitHub payload or put finding text in a shell.

**1 — Zero findings.** Post nothing. Emit the persona's "nothing to say" line and stop.

**2 — Findings file.** Run `mktemp -d -t review-as.XXXXXX` on its own. With the **Write tool** (never a heredoc, `echo` or `python -c`), write `<dir>/findings.json`:

```json
{"prefix": "[From <alias>]:", "lead": "<N> findings",
 "items": [{"path": "<repo-relative path>", "line": 42,
            "side": "RIGHT", "body": "<severity> — <comment>\n\nCitation: <url>"}]}
```

`path`/`line`/`side` are the anchor you recorded in Step 3 (`side` `LEFT` for a removed line). `plan` checks them against the PR diff, so a wrong claim just moves the finding to the summary. Do not write an `id`: the script derives a stable one from alias, path, line and body, so a second run on the same PR posts only genuinely new findings. Leave `line` out for a finding with no single line.

**3 — Plan (read-only).**

```bash
python3 <plugin>/scripts/prreview.py plan --findings <dir>/findings.json --out <dir>/plan.json
```

Its `status`: `no-pr` → say "No open PR for `<branch>`. Falling back to chat output.", emit via 6a, stop · `nothing-to-post` → nothing new to post (already posted); say so and stop · `stale` → run `plan` again · `error` → show the message and fall back to 6a.

**4 — Confirmation gate (never auto-post).** Show the `preview` it printed and wait for an explicit yes:

> About to post to PR #`<n>`: `<N>` inline + `<M>` in summary. Proceed? (y/n)

On "no" → fall back to 6a, do not post.

**5 — Post one batched review.**

```bash
python3 <plugin>/scripts/prreview.py post --plan <dir>/plan.json --confirmed
```

`posted` → print the URL. `fallback_summary` → GitHub rejected an anchor, so the whole review went in as one summary; say so. `stale` → re-run `plan`. `failed` → show `error` verbatim and emit the findings to chat (6a) so nothing is lost.

**6 — Confirm.** On success:

> Posted `<N>` inline + `<M>` general to PR #`<n>` as `[From <alias>]:`.
