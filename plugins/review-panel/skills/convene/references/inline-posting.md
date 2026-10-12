# Inline PR posting (convene Step 6, `inline` output)

One batched review, anchored to the PR diff by code (`scripts/prreview.py`, stdlib
only; review-clone ships a byte-identical copy for `review-as`). You never build
the GitHub payload or interpolate finding text into a shell: you write one JSON file
with the Write tool and pass paths and a PR number.

1. **Findings file.** Run `mktemp -d -t review-panel.XXXXXX` on its own. Write
   `<dir>/findings.json` with the Write tool, built from the `reconcile` output:

   ```json
   {"prefix": "[review-panel]", "lead": "<strategy> / <scope>: <N> findings",
    "items": [{"id": "<fingerprint>", "path": "<file>", "line": 42,
               "severity": "error", "body": "<severity> — <rule>: <actual>\n\nSuggestion: <suggestion>"}]}
   ```
   `id` is the finding's `fingerprint` (the idempotency marker). `line` may be
   null (then the finding goes to the review summary). Omit `side`; set `"LEFT"`
   only for a finding on a removed line.
2. **Plan (read-only).**
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/prreview.py" plan --findings <dir>/findings.json --out <dir>/plan.json`
   (add `--pr <n>` to name a PR, `--no-dedup` to re-post already-posted findings).
   It resolves the PR and its head SHA, fetches the PR diff and places each
   finding on a line the diff really contains. It prints `status` and a `preview`.
   - `no-pr` → no open PR: say so and fall back to the report. Nothing is posted.
   - `nothing-to-post` → print the no-findings line; never post.
   - `stale` → the PR head moved; run `plan` again.
   - `error` → show the message (an old `gh` needs >= 2.40).
3. **Confirmation gate.** Show the `preview` and wait for an explicit yes from the
   user. `--confirmed` below is a speed bump, not the gate. Never auto-post.
4. **Post.**
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/prreview.py" post --plan <dir>/plan.json --confirmed`
   Result `status`: `posted` (print the URL and counts), `fallback_summary`
   (GitHub rejected an anchor; the whole review went in as one summary, nothing
   lost), `stale` (re-plan), `failed` (show `error` verbatim and emit the findings
   to chat; the report file is always written first).

Rules the code applies, so you do not: a finding is inline only if its path and
line are in the PR diff and local HEAD equals the PR head and the file has no
uncommitted edits; everything else goes to the summary with a reason
(`no-line`, `file-not-in-diff`, `line-not-in-diff`, `side-not-in-diff`,
`local-head-differs`, `working-tree-dirty`, `over-cap`). No line is ever snapped to
a nearby one. At most 50 inline comments (errors first). Event is always
`COMMENT`. `@mentions` are code-spanned. Each comment carries a hidden marker so a
re-run does not double-post; an outdated comment is re-posted.
