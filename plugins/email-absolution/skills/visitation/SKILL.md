---
name: visitation
description: Use when reviewing changed email templates in a PR or branch, or spot-checking a specific email file. Triggers on "check my email PR", "review email changes", "spot-check this template", "email visitation", "audit email diff", "what's wrong with this email", "review this email file".
---

# Visitation — Email Spot-Check and PR Review

The Visitation is a targeted audit — scoped to changed templates in a branch
or a single file named by the caller. It applies the full doctrine set but
confines its gaze to the templates actually in play. Faster than the Elder.
No less exacting.

## Prerequisites

1. `.email-absolution/config.yml` must exist with `stack.templating` set
2. Doctrine files must be present in the `doctrines/` directory within this plugin (sibling to the `skills/` directory)
3. For PR/branch mode: git repository with identifiable base branch or PR number

## Mode Detection

| Invocation | Mode | Scope |
|---|---|---|
| `/email-absolution:visitation` (no args) | PR/Branch | Changed email files vs base branch |
| `/email-absolution:visitation <file>` | Single file | Named file only |
| `/email-absolution:visitation pr <number>` | PR | Files changed in named PR |
| `/email-absolution:visitation interactive` | Interactive | Changed files — fix loop |

## When NOT to Use

- Auditing the entire email template directory — use `/email-absolution:elder full`
- Generating a new email template — use `/email-absolution:scribe`
- No templates have changed in this branch (nothing to review)

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Treating visitation as a light check | All 8 doctrines apply — scope is smaller, standards are not |
| Forgetting config-conditional rules | `stack.esp` still governs which ESP-specific rules fire |
| Reporting on compiled output | Review source templates, not build artefacts |
| Missing new templates added in PR | `git diff --name-status` catches new files (`A` status) — include them |
| Citing line numbers from diff hunks | Cite line numbers from the actual file, not the diff |

## Workflow

### Step 1: Load Configuration

Read `.email-absolution/config.yml`. Same requirements as the Elder.
If absent, offer to scaffold. See the `email-absolution:elder` skill, Step 1, for the scaffold flow.

### Step 2: Load Doctrines

Same 8 doctrines as the Elder — no reduction in scope:

| Doctrine File | Loaded |
|---|---|
| `rendering.md` | Yes |
| `html-css.md` | Yes |
| `content-ux.md` | Yes |
| `accessibility.md` | Yes |
| `deliverability.md` | Yes |
| `gotchas.md` | Yes |
| `tooling.md` | Yes |
| `[stack.templating].md` | Yes |

### Step 3: Determine Scope

**Branch/PR mode (default):**
```bash
git diff --name-status $(git merge-base HEAD main) HEAD
```
Include files with status `A` (added) and `M` (modified).
Exclude files with status `D` (deleted) — deleted templates have no violations.
Filter to `email_paths` and known email extensions.

**PR number mode:**
```bash
gh pr diff <number> --name-only
```
Filter same as above.

**Single file mode:** Named file only.

If no email template files are found in scope:
> "The Visitation finds no email templates in this branch's changes.
> If templates were moved rather than modified, they may appear as
> delete + add — check `git diff --name-status` manually."

### Step 4: Apply Config-Conditional Rules

Identical to the Elder — see Step 4 of the `email-absolution:elder` skill.

### Step 5: Run Audit

For each template in scope, apply all loaded doctrines:

- `detect: regex` — scan the file content with the pattern
- `detect: contextual` — inspect structure and logic for the described issue
- `detect: hybrid` — regex first, then contextual confirmation

Focus additional attention on the changed hunks — violations introduced in this
diff are the primary concern. Pre-existing violations in unchanged lines may be
noted as existing debt but are not the focus of the Visitation.

**Interactive mode:** As per the Elder's interactive flow — present each finding,
offer fix / explain / skip / note-as-exception.

### Step 6: Apply Overrides

Check `.email-absolution/decisions.yml`. Downgrade approved exceptions.
Same logic as the Elder — see Step 6 of the `email-absolution:elder` skill.

### Step 7: Output the Verdict

The Visitation report is scoped and concise:

```
Email Visitation — PR Review
=============================

Branch: feat/order-confirmation-redesign → main
Doctrines: rendering, html-css, content-ux, accessibility,
           deliverability, gotchas, tooling, liquid
Templates in scope: 2 changed, 1 added

MORTAL SINS — must be absolved before merge (2):
-------------------------------------------------
[HTML-008] Inline style uses CSS shorthand padding
  File: src/emails/order-confirmation.liquid:45 (modified)
  Found: style="padding: 16px 24px"
  Requires: padding-top/right/bottom/left longhand for Outlook 2007-2019

[LIQ-001] Missing default filter on output variable
  File: src/emails/new-template.liquid:12 (added)
  Found: {{ customer.company }}
  Requires: {{ customer.company | default: "" }}

VENIAL SINS — should be absolved (1):
--------------------------------------
[ACCESS-003] Layout table missing role="presentation"
  File: src/emails/new-template.liquid:8 (added)
  Found: <table width="600" cellpadding="0" cellspacing="0" border="0">
  Requires: role="presentation" attribute added

EXISTING DEBT (not introduced in this diff):
  src/emails/order-confirmation.liquid — 2 pre-existing venial sins
  (run /email-absolution:elder to see full list)

FOUND RIGHTEOUS in this diff:
  src/emails/shipping-notification.liquid (modified — clean)

VERDICT: The Visitation finds 2 mortal sins in this branch.
Absolve them before this branch earns its place in the sanctum.
```

## Integration Points

### Pre-push Hook
```bash
#!/bin/bash
# .git/hooks/pre-push
echo "The Visitation begins..."
# Adapt to your tooling: run /email-absolution:visitation
```

### PR Description Template
After running visitation, offer to generate a PR checklist:

```markdown
## Email Template Checklist
- [ ] No mortal sins (run `/email-absolution:visitation`)
- [ ] Tested in Outlook 2019, Gmail, Apple Mail
- [ ] Plain-text version generated
- [ ] Subject and preheader reviewed
- [ ] Unsubscribe link present and tested
```

## Error Handling

### Not in a git repository
> "The Visitation requires a git repository to determine scope.
> Name a specific file to audit: `/email-absolution:visitation <path/to/template>`"

### PR not found
> "PR #N was not found or is not accessible.
> Check the PR number or use `/email-absolution:visitation` to audit
> the current branch's changes instead."

### Changed files include no email templates
> "This branch's changes contain no email templates in the configured paths.
> All is quiet in the sanctum — no templates to examine."

## FAQ

**Q: Does the Visitation check the whole file or only changed lines?**
A: The whole file. Violations do not respect diff boundaries. A mortal sin
on an unchanged line is still a mortal sin.

**Q: How do I distinguish new violations from existing debt?**
A: The Visitation labels findings as `(added)` or `(modified)` and separates
pre-existing violations into an "Existing Debt" section — present but not
blocking the current change.

**Q: Can I run the Visitation on a feature branch before opening a PR?**
A: Yes. Without a PR number it diffs against the base branch automatically.

## Voice

As the Elder — the Witchfinder's vocabulary applies in full.
The Visitation is a targeted examination, not a lighter one.
Two mortal sins in a single added template are two mortal sins.
