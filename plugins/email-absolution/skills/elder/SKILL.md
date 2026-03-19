---
name: elder
description: Use when auditing an email template or email codebase for rendering, accessibility, deliverability, and templating violations. Triggers on "audit my email", "check my email template", "review this email", "email audit", "check email compliance", "review for email issues", "audit email templates".
---

# Elder — Full Email Audit

The Elder convenes a full Inquisition of the email sanctum. Every template is
examined against all doctrines: rendering safety, HTML and CSS discipline,
content and UX covenant, accessibility law, deliverability law, and the
grimoire of known afflictions. No heresy escapes the Elder's eye.

## Prerequisites

Before the Inquisition begins:
1. `.email-absolution/config.yml` must exist — if absent, offer to scaffold it
2. Doctrine files must be present in `${CLAUDE_SKILL_DIR}/../../doctrines/`
3. For changed-files mode: git repository with identifiable base branch
4. `stack.templating` must be set in config — determines which per-language doctrine is loaded

## Mode Detection

| Invocation | Mode | Scope |
|---|---|---|
| `/email-absolution:elder` (no args) | Report | Changed files (git diff against base branch) |
| `/email-absolution:elder full` | Report | All email templates in configured paths |
| `/email-absolution:elder interactive` | Interactive | All templates — violation-by-violation fix loop |
| `/email-absolution:elder doc` | Doc | Changed files — saves rich markdown report to `docs/emails/audits/` |
| `/email-absolution:elder <file>` | Report | Single named template file |
| `/email-absolution:elder <file> doc` | Doc | Single template — saves rich markdown report |
| Called from hook/CI | Report | Changed files |

**Doc mode** outputs a structured markdown file with summary tables and full explainers
rather than a terminal report. See Step 7b for the doc format specification.

## When NOT to Use

- Reviewing only changed files in a PR or branch — use `/email-absolution:visitation` instead
- Generating a new email template — use `/email-absolution:scribe`
- No email template files exist yet — nothing to audit

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Auditing compiled/dist output | Audit source templates only — compiled HTML is generated artefact |
| Treating all venial sins as blockers | `mortal` = must fix before send; `venial` = should fix; `counsel` = advisory |
| Skipping the per-language doctrine | Always load the doctrine matching `stack.templating` |
| Auditing with incomplete config | `stack.esp` and `stack.templating` both affect rule applicability |
| Running full audit on every save | Default mode scans changed files only — reserve `full` for release gates |
| Reporting violations without file and line | Every finding must cite the file, line or block, and the rule ID |

## Workflow

### Step 1: Load Configuration

Read `.email-absolution/config.yml`:

```yaml
# .email-absolution/config.yml (required)
stack:
  esp: klaviyo            # klaviyo | sendgrid | postmark | mailchimp | resend | custom
  templating: liquid      # liquid | handlebars | mjml | react-email | maizzle | html
  rendering_targets:
    - outlook-2019        # outlook-2019 | outlook-new | gmail | apple-mail | yahoo
    - gmail
    - apple-mail

email_paths:
  - src/emails/
  - templates/email/

exclude:
  - "**/dist/**"
  - "**/build/**"
  - "**/*.compiled.html"
```

If `.email-absolution/config.yml` is not found:

> "The Elder cannot convene without a doctrine manifest. No `.email-absolution/config.yml` was found.
>
> Shall I scaffold one? I will ask a few questions about your ESP, templating stack, and email directory paths — then the Inquisition may begin in earnest."

If the user agrees, scaffold the config interactively. If they decline, show the template above.

### Step 2: Load Doctrines

Load these 8 doctrine files from the plugin's `doctrines/` directory.
This SKILL.md lives at `<plugin-root>/skills/elder/SKILL.md` —
the doctrines directory is at `<plugin-root>/doctrines/`:

| Doctrine File | Always Loaded |
|---|---|
| `rendering.md` | Yes |
| `html-css.md` | Yes |
| `content-ux.md` | Yes |
| `accessibility.md` | Yes |
| `deliverability.md` | Yes |
| `gotchas.md` | Yes |
| `tooling.md` | Yes |
| `[stack.templating].md` | Yes — determined by config |

`[stack.templating].md` maps as:
- `liquid` → `liquid.md`
- `handlebars` → `handlebars.md`
- `mjml` → `mjml.md`
- `react-email` → `react-email.md`
- `maizzle` → `maizzle.md`
- `html` → no per-language doctrine (skip gracefully)

Warn if any doctrine file is missing — continue with available doctrines.

### Step 3: Determine Scope

**Default (changed files):**
```bash
git diff --name-only $(git merge-base HEAD main) HEAD
```
Filter to files matching `email_paths` patterns and known email extensions
(`.html`, `.mjml`, `.hbs`, `.liquid`, `.tsx`, `.jsx`, `.njk`).

**Full mode:** All files under `email_paths` matching email extensions, excluding `exclude` patterns.

**Single file:** The named file only.

### Step 3b: Pre-flight Size Check

After determining scope, count files.

If scope exceeds **50 templates**, pause:

> "The Elder has found **N templates** awaiting examination. This Inquisition may consume considerable time and tokens.
>
> 1. Proceed with full audit
> 2. Focus on specific paths (specify them)
> 3. Audit changed files only
> 4. Audit a single doctrine only (which?)"

If ≤ 50 templates, proceed silently.

### Step 4: Apply Config-Conditional Rules

Before auditing, note which rules are conditionally active based on config:

- Rules marked `stack.esp == "klaviyo"` — active only when ESP is klaviyo (e.g. LIQ-012, DELIV-015 BIMI)
- Rules marked `stack.esp == "sendgrid"` — active only for sendgrid (e.g. HBS-003 @index)
- Rules marked `stack.esp == "postmark"` — active only for postmark (e.g. HBS-004 Mustache)
- `rendering_targets` governs which Outlook/Gmail/Apple Mail rules fire
- Disable per-language rules that don't match `stack.templating`

### Step 4b: Build Rule Checklist

Parse all loaded doctrine files to build a complete rule inventory before any
audit work begins. This must happen before touching any template file.

For each doctrine, scan for entries matching `**[RULE-ID]**` and extract:
- **Regex rules** — rule ID + pattern(s) from the `detect: regex` line
- **Contextual rules** — rule ID + detection instruction from the `detect: contextual` line

Apply Step 4 config-conditional filters to both lists. Remove rules whose
condition doesn't match config (wrong ESP, wrong templating stack, wrong
rendering targets). The result is two filtered checklists derived fresh from
the doctrines on every run.

**Do not hardcode rule IDs in this skill.** The checklists are always generated
at audit time — never stored, never assumed.

### Step 5: Run Audit

Audit proceeds in two sequential phases. Complete both phases across all
templates in scope before moving to Step 6.

#### Phase 1 — Regex Pass (run first)

For each rule in the **regex checklist** (from Step 4b), apply its pattern
to each template file. This pass is mechanical — no LLM judgment required.

**Presence patterns** (a match = violation): apply the pattern; any match is
a confirmed finding.

**Absence patterns** (detect lines containing "absence check" or "flag if file
contains X but not Y"):
- Condition met: file matches the trigger (e.g. contains `<mjml`) AND does NOT
  match the required tag/pattern → flag as violation
- If trigger condition not met: rule does not apply to this file — skip silently

**Conditional patterns** (detect lines with `when stack.esp = X`):
- Apply only when `stack.esp` in config matches; skip otherwise

Collect all regex findings as confirmed violations before starting Phase 2.

#### Phase 2 — Contextual Pass (run second)

Take the **contextual checklist** (from Step 4b) and work through **every rule
in order**. Do not skip any rule — a skipped rule is a missed heresy.

For each contextual rule:
1. State the rule ID
2. Apply the detection instruction to each template in scope
3. Record the outcome explicitly: **violation** (with file, location, evidence)
   or **clean** (no violation found)

**Completing the full checklist is mandatory.** If a rule is not applicable
(filtered in Step 4b), it should not appear here — but every rule that survived
filtering must be checked. Do not exit Phase 2 early.

In **report mode**: collect all findings silently, output in Step 7.
In **interactive mode**: present each violation as it is found, then continue.

**Interactive Mode violation prompt:**
1. Fix this heresy (apply the correction)
2. Explain why this is a mortal sin (expand the rule reasoning)
3. Skip for now
4. Mark as approved exception (note in `.email-absolution/decisions.yml`)

### Step 6: Apply Overrides

Check `.email-absolution/decisions.yml` for approved exceptions before reporting:

```yaml
# .email-absolution/decisions.yml (optional)
overrides:
  RENDER-015:           # VML background images not required
    severity: warning
    reason: "Targeting Gmail and Apple Mail only — no Outlook in audience"
  ACCESS-005:           # Minimum font size waived
    severity: info
    reason: "Legal reviewed; brand font minimum is 13px"
```

Findings with a matching override are downgraded and annotated — not suppressed.

### Step 7: Output the Verdict

```
Email Inquisition — Full Audit Report
======================================

Doctrines applied: rendering, html-css, content-ux, accessibility,
                   deliverability, gotchas, tooling, liquid
Templates examined: 8
Stack: Klaviyo / Liquid / Outlook 2019 + Gmail + Apple Mail

MORTAL SINS — must be absolved before send (3):
------------------------------------------------
[LIQ-001] Missing default filter
  File: src/emails/order-confirmation.liquid:14
  Found: {{ first_name }}
  Requires: {{ first_name | default: "Valued Customer" }}

[RENDER-014] Bulletproof button absent
  File: src/emails/welcome.liquid:67
  Found: <a href="..."> styled as button — no VML fallback
  Requires: VML conditional comment wrapping for Outlook 2007–2019

[DELIV-003] DKIM record not confirmed
  Config: stack.esp = klaviyo
  Found: No DKIM domain record in config or documentation
  Requires: DKIM configured on sending domain before deployment

VENIAL SINS — should be absolved (5):
--------------------------------------
[ACCESS-003] Missing role="presentation" on layout table
  File: src/emails/order-confirmation.liquid:28
  Found: <table width="600"> with no role attribute
  Requires: role="presentation" on all layout tables

[UX-002] Subject line exceeds 50 characters
  File: src/emails/welcome.liquid (front matter)
  Found: "Welcome to Acme — your account is ready to use!" (51 chars)
  Requires: Subject ≤ 50 chars for reliable inbox preview

... (3 more venial sins)

COUNSEL FROM THE ELDERS — advisory (2):
-----------------------------------------
[LIQ-016] cycle tag not used for alternating rows
  File: src/emails/order-confirmation.liquid:100
  Advisory: Use {% cycle "#f4f4f4", "#ffffff" %} for alternating row colours

[TOOL-008] No ADR documenting ESP selection
  Advisory: Document why Klaviyo was chosen in an architecture decision record

FOUND RIGHTEOUS (2 templates):
  src/emails/shipping-notification.liquid
  src/emails/password-reset.liquid

VERDICT: The sanctum is not clean. Absolve 3 mortal sins before sending.
```

### Step 7b: Doc Output Format

When `doc` mode is requested, save the report as a markdown file to
`docs/emails/audits/YYYY-MM-DD-<template-slug>.md` (create the directory if absent).

The doc format uses the structure below. Follow this layout exactly — do not
collapse sections or revert to the terminal format.

```markdown
# Email Audit — <Template Name>
**Date:** YYYY-MM-DD
**Skill:** email-absolution:elder
**Stack:** <ESP> / <Templating> / <Rendering targets>
**Template:** <filename or description>

> **Note:** <Any context the user provides about the template — e.g. "example template,
> copy is illustrative". Omit this block if no context was given.>

---

## Strengths — Found Righteous

<Table of everything the template gets RIGHT. Two columns: Area | What's right.
Be thorough — this section matters. A long table here is a compliment, not padding.
Group by theme: Document structure / Outlook MSO / Table layout / Images / etc.>

| Area | What's right |
|------|-------------|
| ... | ... |

---

## Issues at a Glance

<All three summary tables together — mortal sins first, then venial, then counsel.
This gives the reader a complete picture before diving into any detail.>

### Mortal Sins — Must Be Absolved Before Send (N)

| Rule | Location | Issue |
|------|----------|-------|
| HBS-002 | `<title>` | Triple-stache on `{{{subject}}}` — XSS risk |
| ... | ... | ... |

### Venial Sins — Should Be Absolved (N)

| Rule | Location | Issue |
|------|----------|-------|
| ... | ... | ... |

### Counsel from the Elders (N)

| Rule | Advisory |
|------|---------|
| ... | ... |

---

## Mortal Sins — Detail

<Full explainer for every mortal sin. Each explainer has:
- Heading: ### [RULE-ID] Short description
- Location line
- What was found (quote the actual code where possible)
- Why it matters (one sentence)
- Fix: code block showing the corrected pattern>

### [RULE-ID] Description

**Location:** file / element

Found: `<actual code>`

Why it matters: <one sentence>.

**Fix:**
    ```language
    <corrected code>
    ```

---

## Venial Sins — Detail

<Explainers in the same format as mortal sins. Fix blocks shown only when a
code example adds meaningful clarity — otherwise a prose fix is sufficient.>

---

## Counsel — Detail

<Brief explainers — 2–4 sentences each. No code block required unless
the counsel is actionable with a specific snippet.>

---

## Summary

| Category | Count |
|----------|-------|
| Mortal sins | N |
| Venial sins | N |
| Counsel | N |
| Found righteous | N |

<One short paragraph: overall verdict on the template's state, what the
concentrations of violations tell us, and what fixing the mortals unlocks.>
```

**File naming:** use a kebab-case slug of the template name or description.
Example: `2026-03-18-order-confirmation-klaviyo.md`

**Found Righteous section:** populate generously. Every confirmed-compliant pattern
deserves acknowledgement — it gives the recipient useful signal about what to
replicate in other templates.

## Subagent Contract

If dispatching subagents per doctrine, each must return:

```json
{
  "doctrine": "rendering",
  "templates_scanned": 8,
  "violations": [
    {
      "id": "RENDER-014",
      "file": "src/emails/welcome.liquid",
      "line": 67,
      "rule": "CTA buttons must use VML bulletproof pattern for Outlook 2007-2019",
      "actual": "<a href=\"...\"> styled as button with no VML",
      "severity": "mortal",
      "category": "outlook-rendering"
    }
  ],
  "clean_templates": ["src/emails/password-reset.liquid"],
  "notes": []
}
```

## Integration Points

### Pre-send Hook
```bash
#!/bin/bash
# Run before deploying compiled email templates
echo "The Elder convenes..."
# claude -p "/email-absolution:elder full" — adapt to your CI tooling
```

### GitHub Actions
```yaml
name: Email Audit
on: [pull_request]
jobs:
  email-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Convene the Elder
        run: echo "Run /email-absolution:elder in your Claude Code workflow"
```

## Error Handling

### Missing `stack.templating`
> "The Elder cannot determine which templating language governs this sanctum.
> Set `stack.templating` in `.email-absolution/config.yml` to one of:
> `liquid | handlebars | mjml | react-email | maizzle | html`."

### Per-language doctrine file missing
```
Warning: No doctrine file found for templating stack "maizzle"
   Expected: doctrines/maizzle.md
   Continuing without per-language audit.
```

### No email templates found
> "No email templates were found in the configured paths. Check `email_paths`
> in `.email-absolution/config.yml` and ensure source templates are not
> inside `exclude` patterns."

## Customization

### Excluding files
```yaml
# .email-absolution/config.yml
exclude:
  - "**/dist/**"
  - "**/build/**"
  - "**/*.compiled.html"
  - "templates/email/legacy/**"   # Archived templates
```

### Downgrading rules
```yaml
# .email-absolution/decisions.yml
overrides:
  RENDER-015:
    severity: info
    reason: "No Outlook users in audience — VML not required"
```

## FAQ

**Q: Can I audit a single doctrine?**
A: Specify the doctrine prefix: `/email-absolution:elder rendering` audits
rendering.md rules only.

**Q: How do I suppress a false positive?**
A: Add an override in `.email-absolution/decisions.yml` with your reasoning.
Documented exceptions are righteous — undocumented ones are not.

**Q: Which rules fire for Klaviyo vs SendGrid?**
A: Rules with `stack.esp == "klaviyo"` in their detect notes fire only when
`stack.esp: klaviyo` is set. The Elder respects context.

**Q: Should I run `full` on every commit?**
A: No. Default changed-files mode is fast enough for commits. Run `full`
at release gates and after significant template changes.

## Exit Codes

- `0` — No mortal sins found (venial sins and counsel allowed)
- `1` — Mortal sins found — do not send
- `2` — Configuration or setup error
- `3` — Doctrine loading failure

## Voice

Deliver all findings as the Witchfinder — uncompromising, dramatically precise,
formally correct. Violations are heresies. A clean template is found righteous.
Fixing a violation is absolution. The email codebase is the sanctum.

Severity vocabulary:
- `mortal` → mortal sin — must be absolved before the email is sent
- `venial` → venial sin — should be corrected; tolerated but not approved
- `counsel` → counsel from the elders — advisory; wisdom offered, not commanded
