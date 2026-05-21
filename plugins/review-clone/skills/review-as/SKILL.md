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

### 4 — Verification gate (run BEFORE emitting each finding)

**6a — API reality check.** If the rule names a function/helper/flag/component:
- Use `Grep` (via the Grep tool) to confirm the symbol currently exists (or doesn't, if the rule says so) in the target repo.
- **If the symbol is absent from the target repo:** silently skip this rule. Do NOT emit; do NOT explain to the user. (Locked decision B.)

**6b — Trace-the-fix.** Mentally apply the proposed fix to the diff. If it doesn't compile, doesn't change behaviour, or needs additional unstated changes — downgrade severity to Question, or drop entirely.

**6c — Lets-go check.** If the finding matches anything in the persona's `## What they let go` section, drop it.

### 5 — Output mode selector

Read `output_default` from frontmatter:
- If set → use it silently
- If null → present three options:
  1. **Summary in chat, details in file** (`summary-chat-details-file`)
  2. **All in chat** (`all-chat`)
  3. **All in file** (`all-file`)

  Plus a toggle: "Make this the default for /review-as-<alias>?" If yes, write `output_default` back to PERSONA frontmatter using `persona_io.write_persona`.

  File path when used: `.review-clone/last-review-<alias>.md` in repo root.

### 6 — Emit

Format:

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
