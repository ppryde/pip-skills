# review-as: mode review

## Mode: review

### 1 — Compute the diff

Resolve the base branch: `gh pr view --json baseRefName -q .baseRefName` if a PR exists, else `git symbolic-ref --short refs/remotes/origin/HEAD` (strip the `origin/` prefix). Call it `<base>`. If the persona's `repo` differs from this checkout's `origin`, warn the user before reviewing.

```bash
git fetch origin '<base>' --quiet
git diff 'origin/<base>...HEAD' --name-only -z --diff-filter=d
```

Filter to files matching the persona's `filters.paths` OR `filters.extensions`. If empty:

> Nothing to review — no files matching <alias>'s scope have changed.

### 2 — For each in-scope changed file

```bash
git diff 'origin/<base>...HEAD' -- '<path>'
```

**Quoting untrusted values.** Changed file paths, `<base>`, handles and `last_scanned_at` come from a branch, a PR or PERSONA.md, so treat them as hostile. Always put them in **single quotes**, escaping any embedded `'` as `'\''`; never in double quotes (those still run `$(...)` and backticks), and never in an unquoted heredoc. If a value contains a newline or NUL, skip it and say so.

Read the file at HEAD too (not just the hunk) — context matters for rules that point at adjacent code.

### 3 — Walk the rule list

For each rule in the PERSONA body, decide if it applies to any changed file. If yes, draft a finding.

When a finding fires, record its **line anchor** from the hunk it sits in — you need this for inline PR posting (Step 5, option 4 `post-inline-pr`, posted in Step 6b):
- `path` — repo-relative file path
- `line` — line number in the file at HEAD the comment points at
- `side` — `RIGHT` for an added or context line, `LEFT` for a removed line

If a finding can't be pinned to a single line in the diff, leave its anchor empty; it becomes a general comment when posted.

### 4 — Verification gate (run BEFORE emitting each finding)

**4a — API reality check.** If the rule names a function/helper/flag/component:
- Use `Grep` (via the Grep tool) to confirm the symbol currently exists (or doesn't, if the rule says so) in the target repo.
- **If the symbol is absent from the target repo:** silently skip this rule when the diff touches that symbol (a rule about code the diff does not touch is simply not applicable). Do NOT emit; do NOT explain to the user. (Locked decision B.)

**4b — Trace-the-fix.** Mentally apply the proposed fix to the diff. If it doesn't compile, doesn't change behaviour, or needs additional unstated changes — downgrade severity to Question, or drop entirely.

**4c — Lets-go check.** If the finding matches anything in the persona's `## What they let go` section, drop it.

### 5 — Output mode selector

Read `output_default` from frontmatter:
- If set → use it silently
- If null → present four options:
  1. **Summary in chat, details in file** (`summary-chat-details-file`)
  2. **All in chat** (`all-chat`)
  3. **All in file** (`all-file`)
  4. **Post inline to PR** (`post-inline-pr`) — see Step 6b

  Plus a toggle: "Make this the default for /review-as-<alias>?" If yes, write `output_default` back to PERSONA frontmatter using `persona_io.write_persona`.

  File path when used: `.review-clone/last-review-<alias>.md` in repo root. Create `.review-clone/` via `mkdir -p .review-clone/` if it doesn't exist before writing.

### 6a — Emit to chat / file

For `summary-chat-details-file`, `all-chat`, `all-file`. Format:

```
# /review-as-<alias> — <branch> vs <base>

Snapshot: <last_scanned_at> · <N> files in scope

## <file path>
- **<severity>** — <comment in their voice>
  Citation: <comment URL>

(... more findings ...)

---

<verdict line in their voice>
```

If no findings: emit the persona's "nothing to say" line (from voice section), or default to "Nothing from me. Good to push."

### 6b — Post inline to PR (`post-inline-pr`)

Only when the selected output is `post-inline-pr`: **read `references/post-inline-pr.md` first** and follow it (resolve the PR, confirmation gate, one batched review, `[From <alias>]:` prefix, failure handling).
