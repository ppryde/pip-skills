---
description: Run a composable code review — pick a profile (strategy × reviewers) or name reviewers ad-hoc.
argument-hint: [profile] [full|interactive|inline] | <reviewer…> | reviewers | strategies
---

Invoke the review-panel orchestrator (`skills/convene/SKILL.md`) with
`$ARGUMENTS`. Resolve arguments as follows:

- empty → the default profile from `.review-panel/config.yml`.
- a known profile name → that profile; a trailing `full` overrides scope to
  the whole repo; a trailing `interactive` or `inline` overrides output.
- one or more known reviewer names (built-in or `clone:<alias>`) → an ad-hoc
  committee over changed files.
- `reviewers` → list available reviewers (built-in + clone personas).
- `strategies` → list available strategies.

Follow the workflow in `skills/convene/SKILL.md` exactly.
