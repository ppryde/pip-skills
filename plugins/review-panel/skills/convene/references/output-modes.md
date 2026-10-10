# Interactive and inline output (convene Step 6)

- **interactive** → walk findings one at a time: fix / explain / skip /
  accept-exception (accept writes an override into `.review-panel/decisions.yml`, keyed by the
  finding's `fingerprint`).
- **inline** → confirmation-gated. Resolve the open PR
  (`gh pr view --json number`). If none, fall back to report. Preview the
  count, wait for an explicit yes, then post one batched review via
  `gh api repos/<owner>/<repo>/pulls/<n>/reviews` — anchorable findings as
  inline comments, the rest bundled into the review summary. Never auto-post.
