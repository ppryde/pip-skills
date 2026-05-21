---
name: clone-reviewer
description: Use when the user wants to create a new "review-as-X" persona by cloning a reviewer's public GitHub comment history. Triggers on "clone reviewer", "create review persona", "make a reviewer bot for X", "review-clone setup", or the slash command /clone-reviewer.
---

# Clone Reviewer — derive a persona from real review history

You are setting up a new `review-clone` persona. The user wants you to derive a "review-as-X" voice + ruleset from one or more GitHub reviewers' public comment history, and register a slash command `/review-as-<alias>` for future use.

## Storage (locked)

- Persona files: `~/.claude/review-clone/<alias>/PERSONA.md`
- Raw scrape: `~/.claude/review-clone/<alias>/raw/pr-<n>.json`
- Snapshot: `~/.claude/review-clone/<alias>/snapshot.json`
- Per-persona slash command: `~/.claude/commands/review-as-<alias>.md`
- Drift log overflow: `~/.claude/review-clone/<alias>/drift.log`

## Procedure

### Step 0 — Re-clone check

Check if any personas already exist. Run:

```bash
python3 -c "from scripts.persona_io import list_personas; print('\n'.join(list_personas()))"
```

(or, equivalent: `ls ~/.claude/review-clone/` filtered to dirs containing `PERSONA.md`).

If the user's intended alias is taken, present this 3-way prompt:

> A persona `<alias>` already exists (last scanned <last_scanned_at>).
> 1. **Refresh** — pull comments since last scan, fold into existing rules
> 2. **Modify handles & re-extract** — add/remove handles, full re-pull for added handles
> 3. **Fork to new alias** — create a separate persona under a different name

Only proceed to Step 1 after the user picks. If they pick **Refresh**, hand off to the `review-as` skill's refresh flow.

### Step 1 — Conversational setup (one question at a time)

Ask each of these in turn, accepting defaults shown in brackets:

1. **Alias** — kebab-case, unique. Becomes the slash command name (`jen` → `/review-as-jen`).
2. **GitHub handle(s)** — one or more, comma-separated. Multi-handle personas aggregate across all listed handles.
3. **Repo scope** [defaults to the current repo's `origin` if any] — e.g. `wayflyer/wayflyer`.
4. **Path filters** [empty = all] — comma-separated path prefixes (`frontend/, packages/`).
5. **Extension filters** [empty = all] — comma-separated extensions (`.ts, .tsx, .css, .scss`).
6. **Time window** [6 months] — hard cap at 6 in v1.
7. **Tone** [`copy`] — `copy` (mimic voice) or `neutral` (rules in plain prose).
8. **Authoring voice** [yes if tone=copy, else no] — include their PR descriptions as input for an "author-as-X" sub-mode.
9. **Lets-go calibration** [skippable] — "Anything you've seen <handle> explicitly NOT care about?" Free text, used as anti-rules.

### Step 2 — Privacy notice (non-blocking)

After answers, before scraping, print:

> 🔔 This will derive a persona from <handle>'s **public** GitHub review comments. They will not be notified. A disclaimer line stating the derived nature will be written into PERSONA.md.

Continue without confirmation — non-blocking by design.

### Step 3 — Run the collector

Invoke the scraper:

```bash
python <plugin>/scripts/collect.py \
  --alias <alias> \
  --handles <handles> \
  --repo <repo> \
  --months <months> \
  --paths <paths> \
  --extensions <extensions>
```

Capture stdout (the JSON snapshot). Stream stderr to the user so they see progress.

### Step 4 — Pre-extract gate

Read `snapshot.json.counts`. Display:

> Scraped **<prs> PRs**, **<review_comments + issue_comments> comments**, **<pr_descriptions> PR descriptions** for `<alias>`.

If `prs > 100 OR (review_comments + issue_comments) > 200`, prompt:

> This is a large corpus. Theme extraction will use significant context tokens. Proceed? [y/N]

If user declines, leave the raw data in place (they can re-run later) and stop.

### Step 5 — Theme extraction (LLM-driven, you do this)

Read every `~/.claude/review-clone/<alias>/raw/pr-*.json`. For each comment:

- **Honor withdrawals.** If a comment's `reply_thread` shows the author conceding (e.g. "good point, ignore my last", "Ha, I conflicted myself!"), mark that comment as withdrawn — do NOT derive a rule from it.
- **Multi-handle conflict resolution.** When two handles' comments contradict, pick the rule with the most citations across the corpus. Preserve losers under an `also_seen:` field on the rule.

Derive:

1. **Rules.** Cluster comments by topic. For each cluster, write a rule with: title, topic tags, severity (use the reviewer's actual phrasings to calibrate), citation URL (the strongest-anchor comment), one positive + one negative example pulled directly from the corpus.
2. **Voice patterns.** Openers, severity ladder (block/strong/suggest/question/non-blocking), quirks (e.g. "Needs reverted" without "to be"), what they NEVER say.
3. **Lets-go.** From the corpus + the user's Step 1.9 input.

### Step 6 — Write PERSONA.md

Use the persona_io helpers (`from scripts.persona_io import write_persona, persona_path`). Frontmatter shape:

```yaml
alias: <alias>
handles:
  - <handle1>
repo: <repo>
filters:
  paths: [...]
  extensions: [...]
window:
  months: <n>
  since: "<iso>"
tone: <copy|neutral>
authoring_voice: <true|false>
last_scanned_at: "<iso>"
snapshot:
  prs: <n>
  review_comments: <n>
  issue_comments: <n>
  pr_descriptions: <n>
output_default: null
drift_log: []
drift_log_archived_count: 0
disclaimer: "Derived from public GitHub review history of <handles>. Not endorsed by them."
```

Body sections: `## Voice & tone`, `## Rules` (one ### per rule, with severity/citation/examples), `## What they let go`, `## Drift log`.

### Step 7 — Write the per-persona slash command

Render `<plugin>/templates/review-as-command.md.tmpl` substituting `<alias>` and `<last_scanned_at>`. Write to `~/.claude/commands/review-as-<alias>.md`. Create the `~/.claude/commands/` dir if missing.

### Step 8 — Final summary

Print:

> ✅ Persona `<alias>` cloned.
> - <N> rules derived from <M> comments across <P> PRs
> - Slash command `/review-as-<alias>` ready
> - Window: <months> months · last scanned <last_scanned_at>
>
> Try it: `/review-as-<alias>` to review the current branch, or `/review-as-<alias>` chat "would they like X?".

## Constraints

- Do NOT scrape outside the user's stated window. Hard cap 6 months in v1.
- Do NOT skip the withdrawal pass — false rules from softened comments are the #1 quality problem.
- Do NOT invent rules without a citation URL. Every rule must point at a real comment.
- Do NOT fabricate symbols/APIs in examples. Quote the comment's body verbatim where it names anything.
