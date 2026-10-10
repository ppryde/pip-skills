# Doc mode: output format

Read when `doc` mode is requested. Doc mode writes one doc per template in scope. When more than one template is in scope, also write an index doc, `docs/emails/audits/YYYY-MM-DD-index.md`: one row per template with its mortal, venial and counsel counts and a link to its doc.

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
Base every row on a rule evaluated as clean in Phase 2 or a regex that did not match in Phase 1.
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

**File naming:** use a kebab-case slug of the template name or description; the slug
must match `^[a-z0-9-]+$` (sanitise anything else), and doc files are written only
under `docs/emails/audits/`.
Example: `2026-03-18-order-confirmation-klaviyo.md`

**Found Righteous section:** list the patterns that were checked and found clean
in Phase 1 and Phase 2 (rules recorded as **clean**). Every such confirmed-compliant
pattern deserves acknowledgement; do not praise anything that was not evaluated.
