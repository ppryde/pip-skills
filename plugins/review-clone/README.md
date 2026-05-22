# review-clone

Clone a reviewer's voice and rules from their public GitHub review history. Every finding cites a real comment. The persona never invents APIs.

## What it does

`/clone-reviewer` → walks you through creating a persona from any GitHub reviewer's public comments.

`/review-as-<alias>` → review the current branch, refresh from new comments, or chat as the persona:
- no args → review the current branch
- `refresh` → pull comments since last scan, fold into rules
- `chat <question>` → ask the persona's opinion (cited or "no signal")

## Storage

Personas are personal and portable across repos:

```
~/.claude/review-clone/<alias>/PERSONA.md         # rules + voice
~/.claude/review-clone/<alias>/raw/               # cached scrape
~/.claude/review-clone/<alias>/snapshot.json      # provenance
~/.claude/commands/review-as-<alias>.md           # auto-registered command
```

## Requirements

- `gh` CLI authenticated (`gh auth status`)
- Python 3.11+
- Repo with `origin` set (for default repo detection at clone time)

## Limits (v1)

- Window capped at 6 months
- Pre-extract gate prompts above 100 PRs or 200 comments
- Drift log capped at 20 entries; older entries archived to `drift.log`

## Privacy

`review-clone` derives personas from **public** GitHub review comments. The cloned person is not notified. A disclaimer line is written into every PERSONA.md.
