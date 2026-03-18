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
| `/email-absolution:elder <file>` | Report | Single named template file |
| Called from hook/CI | Report | Changed files |

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

### Step 5: Run Audit

**Report Mode (parallel by doctrine group):**

Audit the templates across all 8 loaded doctrines. For each doctrine, scan each
template file for rule violations using the detection methods specified:

- `detect: regex` — apply the pattern literally; report any match
- `detect: contextual` — apply judgement; cite the specific construct found
- `detect: hybrid` — apply regex first, then confirm contextually

Collect all findings with: rule ID, severity, file, location, what was found,
and what the rule requires.

**Interactive Mode (sequential):**

Present each violation one at a time and offer:
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
