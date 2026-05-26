---
name: review-as
description: Use when the user invokes /review-as-<alias>, says "review as <alias>", asks "would <alias> like X", or runs refresh/chat on an existing review-clone persona. Loads PERSONA.md, dispatches to review/refresh/chat mode.
---

# review-as — run a cloned reviewer persona

You are running an existing `review-clone` persona. The PERSONA.md frontmatter is your single source of truth; the rules + voice live in the body.

## Modes

Dispatch from `$ARGUMENTS`:
- empty → **review**
- `refresh` → **refresh**
- `chat <prompt>` → **chat**
- anything else → **chat** with the full arg string as the prompt

## Step 0 — Load the persona

Read `~/.claude/review-clone/<alias>/PERSONA.md`. Use `scripts/persona_io.read_frontmatter` for the YAML; read the body raw for rules + voice.

**Opening line, every invocation:**

> Running `/review-as-<alias>` against snapshot from `<last_scanned_at>`.

If `last_scanned_at` is more than 30 days old, suggest (don't force) a refresh:

> Snapshot is <N> days old. Consider `/review-as-<alias> refresh` before relying on this review.

---

## Mode: review

### 1 — Compute the diff

```bash
git fetch origin main --quiet
git diff origin/main...HEAD --name-only
```

Filter to files matching the persona's `filters.paths` OR `filters.extensions`. If empty:

> Nothing to review — no files matching <alias>'s scope have changed.

### 2 — For each in-scope changed file

```bash
git diff origin/main...HEAD -- <path>
```

Read the file at HEAD too (not just the hunk) — context matters for rules that point at adjacent code.

### 3 — Walk the rule list

For each rule in the PERSONA body, decide if it applies to any changed file. If yes, draft a finding.

When a finding fires, record its **line anchor** from the hunk it sits in — you need this for inline PR posting (Step 5, `post-inline-pr`):
- `path` — repo-relative file path
- `line` — line number in the file at HEAD the comment points at
- `side` — `RIGHT` for an added or context line, `LEFT` for a removed line

If a finding can't be pinned to a single line in the diff, leave its anchor empty; it becomes a general comment when posted.

### 4 — Verification gate (run BEFORE emitting each finding)

**6a — API reality check.** If the rule names a function/helper/flag/component:
- Use `Grep` (via the Grep tool) to confirm the symbol currently exists (or doesn't, if the rule says so) in the target repo.
- **If the symbol is absent from the target repo:** silently skip this rule. Do NOT emit; do NOT explain to the user. (Locked decision B.)

**6b — Trace-the-fix.** Mentally apply the proposed fix to the diff. If it doesn't compile, doesn't change behaviour, or needs additional unstated changes — downgrade severity to Question, or drop entirely.

**6c — Lets-go check.** If the finding matches anything in the persona's `## What they let go` section, drop it.

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
# /review-as-<alias> — <branch> vs origin/main

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

Only when the selected output is `post-inline-pr`. Every message posted to the PR — inline comment **and** summary — is prefixed `[From <alias>]:` so a human can never mistake the clone for the real reviewer. `<alias>` is the slug verbatim, not a display name.

**1 — Resolve the PR.** 

```bash
gh pr view --json number,headRepositoryOwner,headRepository
```

If there is no open PR for the branch, do NOT post:

> No open PR for `<branch>`. Falling back to chat output.

Then emit via 6a and stop.

**2 — Zero findings.** Do not post anything. Emit the persona's "nothing to say" line and stop.

**3 — Confirmation gate (never auto-post).** Split findings into *anchorable* (have `path`/`line`/`side`) and *un-anchorable*. Print a preview and wait for an explicit yes:

> About to post to PR #`<n>`: `<N>` inline comments + `<M>` general. Proceed? (y/n)

On "no" → fall back to 6a, do not post.

**4 — Post one batched review.** Build each comment body as `[From <alias>]: <severity> — <comment>` followed by a blank line and `Citation: <url>`. Submit all anchorable findings in a single review:

```bash
gh api repos/<owner>/<repo>/pulls/<n>/reviews \
  -f event=COMMENT \
  -f 'comments[][path]=<path>' \
  -F 'comments[][line]=<line>' \
  -f 'comments[][side]=<RIGHT|LEFT>' \
  -f "comments[][body]=[From <alias>]: <severity> — <comment>

Citation: <url>"
```

Repeat the `comments[][...]` field group once per anchorable finding. Use `-F` (not `-f`) for `line` so it is sent as a number.

**5 — Un-anchorable findings.** Bundle them into the review's summary `body` (also prefixed `[From <alias>]:`), passed as `-f 'body=...'` on the same call. If there are *no* anchorable findings, post them instead as a single general comment:

```bash
gh pr comment <n> --body "[From <alias>]: <bundled findings>"
```

**6 — On failure.** If the `gh api` call fails, surface the error verbatim and emit the findings to chat (6a) so nothing is lost.

**7 — Confirm.** On success:

> Posted `<N>` inline + `<M>` general to PR #`<n>` as `[From <alias>]:`.

---

## Mode: refresh

### 1 — Pull since last scan

```bash
python <plugin>/scripts/collect.py \
  --alias <alias> \
  --handles <handles from frontmatter> \
  --repo <repo> \
  --months <months> \
  --paths <paths> \
  --extensions <extensions> \
  --since <last_scanned_at>
```

### 2 — Pre-extract gate

Read the new snapshot.json. Display delta counts. If `new_prs > 100 OR new_comments > 200`, prompt to confirm before extracting.

### 3 — Drift detection (LLM-judged)

For each newly-derived rule:
- Compare against existing rules in PERSONA body. Look for direct contradictions ("use X" vs "use Y" on the same surface area).
- On contradiction: newer wins. Mark old rule with `superseded_by: <new rule id>`. Append drift entry via `persona_io.append_drift_entry`:

  ```python
  {"date": "<iso>", "summary": "Rule X superseded by Y", "url": "<new citation>"}
  ```

- Honor withdrawals from new comment reply threads. Don't derive from withdrawn comments.

### 4 — Update PERSONA.md

- Bump `last_scanned_at`
- Update `snapshot:` counts
- Append/modify rules
- Refresh voice patterns if new openers/quirks emerge
- Drift log auto-caps via `persona_io.append_drift_entry`

### 5 — Print delta

> Refreshed `<alias>` from `<old_scanned>` → `<new_scanned>`.
> +<N> rules · <M> superseded · <K> voice refinements

---

## Mode: chat

The user asks "would `<alias>` like <something>?" or asks for the persona's opinion on a pattern.

**Cite-or-refuse (locked decision G):**

- If you can ground the answer in a real cited rule from PERSONA body → answer in voice + cite the comment URL.
- If you cannot → answer plainly:

  > No signal in the corpus on this. `<alias>` hasn't commented on <topic> in the scanned window.

Do NOT invent opinions. The persona's silence is data.

---

## Constraints

- Never invent symbols. Pull them from the cited comment body.
- Never link a URL that isn't in PERSONA.md or the repo's existing docs.
- Never sandwich criticism with compliments unless the persona's voice section explicitly does that.
- Match the persona's severity-ladder phrasings verbatim.
