# Interactive and inline output (convene Step 6)

- **interactive** → walk findings one at a time: fix / explain / skip /
  accept-exception (accept writes an override into `.review-panel/decisions.yml`, keyed by the
  finding's `fingerprint`).
- **inline** → confirmation-gated; **read `inline-posting.md`** (same folder)
  and follow it: `prreview.py plan`, show the preview, wait for an explicit yes,
  then `post`. Never auto-post.
