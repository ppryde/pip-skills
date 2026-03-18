# email-absolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `email-absolution` Claude Code plugin — a three-skill, twelve-doctrine HTML email development assistant with Witchfinder persona.

**Architecture:** A sibling to the `puritan` plugin. Twelve doctrine files — six core doctrines (rule catalogs with numbered rules, severity ratings, and regex/contextual detection methods) plus one tooling overview and five per-language doctrines (MJML, Handlebars, Liquid, React Email, Maizzle) — are loaded by three skills (`elder`, `visitation`, `scribe`). Skills load the per-language doctrine matching `stack.templating` in config. A two-tier config system (`.email-absolution/config.yml` + per-email `email.config.yml`) drives behaviour.

**Tech Stack:** Markdown only. No build tooling. No tests beyond structural verification. YAML frontmatter in SKILL.md files. Regex patterns embedded in doctrine rule entries.

**Spec:** `docs/superpowers/specs/2026-03-18-email-absolution-design.md`
**Reference plugin:** `plugins/puritan/` — follow this structure exactly.

---

## File Map

```
plugins/email-absolution/
├── .claude-plugin/plugin.json          TASK 1
├── README.md                           TASK 1
├── doctrines/
│   ├── _template.md                    TASK 1
│   ├── rendering.md                    TASK 2
│   ├── html-css.md                     TASK 3
│   ├── accessibility.md                TASK 4
│   ├── deliverability.md               TASK 5
│   ├── gotchas.md                      TASK 6
│   ├── content-ux.md                   TASK 7
│   ├── tooling.md                      TASK 8  (overview + selection guide)
│   ├── mjml.md                         TASK 9
│   ├── handlebars.md                   TASK 10
│   ├── liquid.md                       TASK 11
│   ├── react-email.md                  TASK 12
│   └── maizzle.md                      TASK 13
└── skills/
    ├── elder/SKILL.md                  TASK 14
    ├── visitation/SKILL.md             TASK 15
    └── scribe/SKILL.md                 TASK 16
```

---

## Rule ID Prefixes

| Doctrine | Prefix | Target rule count |
|----------|--------|------------------|
| rendering | RENDER- | 20–25 |
| html-css | HTML- | 20–25 |
| accessibility | ACCESS- | 20–25 |
| deliverability | DELIV- | 20–25 |
| gotchas | GOTCHA- | 25–30 |
| content-ux | UX- | 15–20 |
| tooling | TOOL- | 10–15 (selection/cross-tool rules) |
| mjml | MJML- | 15–20 |
| handlebars | HBS- | 15–20 |
| liquid | LIQ- | 15–20 |
| react-email | REMAIL- | 15–20 |
| maizzle | MZL- | 15–20 |

---

## Task 1: Plugin Scaffolding

**Files:**
- Create: `plugins/email-absolution/.claude-plugin/plugin.json`
- Create: `plugins/email-absolution/README.md`
- Create: `plugins/email-absolution/doctrines/_template.md`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p plugins/email-absolution/.claude-plugin
mkdir -p plugins/email-absolution/doctrines
mkdir -p plugins/email-absolution/skills/elder
mkdir -p plugins/email-absolution/skills/visitation
mkdir -p plugins/email-absolution/skills/scribe
```

- [ ] **Step 2: Write plugin.json**

Create `plugins/email-absolution/.claude-plugin/plugin.json`:

```json
{
  "name": "email-absolution",
  "version": "0.1.0",
  "description": "Righteous HTML email construction. Doctrines, visitation, and absolution for the transactional email sanctum.",
  "author": {
    "name": "Pip",
    "url": "https://github.com/ppryde/pip-skills"
  },
  "keywords": ["email", "html-email", "transactional", "accessibility", "deliverability", "rendering"]
}
```

- [ ] **Step 3: Write README.md**

Create `plugins/email-absolution/README.md`:

```markdown
# email-absolution

HTML email development under the watchful eye of the Witchfinder.

Twelve doctrines. Three skills. No sinful templates shall pass.

## Skills

- **elder** — Consultation, planning, and routing. Your first port of call.
- **visitation** — Formal inspection of an existing email template against all doctrines.
- **scribe** — Righteous generation of new email templates, correct by construction.

## Usage

```
/email-absolution:elder          # Q&A, planning, config setup
/email-absolution:visitation     # Audit a template
/email-absolution:scribe         # Generate a template
```

## Configuration

On first invocation, `elder` will offer to create `.email-absolution/config.yml` via a setup questionnaire. Individual email templates may have their own `email.config.yml` in their directory. Per-email configs inherit from the project config and only need to specify overrides.

## Persona

All skills speak with the Witchfinder voice. Heresy is found. Absolution is granted. The soul is either clean or it is not.

The Witchfinder persona is fixed at the plugin level and cannot be suppressed via config. The `tone` field in `email_defaults` refers to the email's tone of voice (e.g. `transactional`, `casual`) — not the skill's persona.
```

- [ ] **Step 4: Write doctrine _template.md**

Create `plugins/email-absolution/doctrines/_template.md`:

```markdown
# [Doctrine Name] — Email Doctrine

## Purpose

One paragraph: what this doctrine covers, what category of email heresy it guards against, and why it matters in production.

## Rule Catalog

Rules are numbered, severity-rated, and specify their detection method. Visitation applies all rules in this catalog when auditing a template.

**Severity levels:**
- `mortal` — Must be resolved before the template ships. These break rendering, accessibility, or deliverability.
- `venial` — Should be resolved. Counsel given, not blocking unless strictness is set to `strict`.
- `counsel` — Best practice. Aspirational guidance. Never blocking.

**Detection methods:**
- `detect: regex` — Visitation runs the pattern match mechanically against the HTML source.
- `detect: contextual` — Visitation applies judgment. No single pattern catches this.
- `detect: hybrid` — Regex catches obvious cases; contextual reasoning catches nuanced ones.

---

**[PREFIX-001]** `mortal` — Rule statement here.
> Why it matters. Which client is affected. Source: [source name](url).
> `detect: regex` — pattern: `your-regex-here`

**[PREFIX-002]** `venial` — Rule statement here.
> Why it matters. Source: [source name](url).
> `detect: contextual` — judgment criterion

**[PREFIX-003]** `counsel` — Rule statement here.
> Why it matters. Source: [source name](url).
> `detect: hybrid` — regex: `pattern` + contextual fallback

---

## Support Matrix

Table of client support for key features in this domain. Columns: Feature | Safe (works everywhere) | Partial (works in some) | Risky (avoid).

| Feature | Safe | Partial | Risky |
|---------|------|---------|-------|
| Example | `<table>` layout | CSS Grid | `position: absolute` |

## Patterns & Code Examples

Concrete code examples. Label each CORRECT or INCORRECT. Prefer minimal examples that isolate the point.

```html
<!-- INCORRECT: [reason] -->
<example>bad code here</example>

<!-- CORRECT: [reason] -->
<example>good code here</example>
```

## Known Afflictions

Named client-specific bugs relevant to this doctrine. For each: symptom, affected clients, fix.

**[Affliction name]** — Symptom description.
Affects: [client list]. Source: hteumeuleu/email-bugs #NNN or other source.
Fix: `code or description`

## Sources

1. **Source name** — url. Used for: [which rules].
2. **Source name** — url. Used for: [which rules].
```

- [ ] **Step 5: Verify structure**

```bash
find plugins/email-absolution -type f | sort
```

Expected output:
```
plugins/email-absolution/.claude-plugin/plugin.json
plugins/email-absolution/README.md
plugins/email-absolution/doctrines/_template.md
```

- [ ] **Step 6: Commit**

```bash
git add plugins/email-absolution/
git commit -m "feat(email-absolution): scaffold plugin structure, plugin.json, README, doctrine template"
```

---

## Task 2: Rendering Doctrine

**Source:** `docs/emails/research/email_rendering_compatibility.md`
**File:** `plugins/email-absolution/doctrines/rendering.md`
**Target:** 300–400 lines, 20–25 rules, prefix `RENDER-`

**What to distil from the source:**
- Client landscape: Outlook Word engine, New Outlook (Edge), Gmail desktop/app, Apple Mail, Yahoo, Samsung — key rendering differences
- CSS support matrix: which properties are Safe / Partial / Risky per client
- MSO conditional comment syntax (`<!--[if mso]>`, `<!--[if !mso]><!--`)
- VML for background images and bulletproof buttons
- Gmail 102KB clip limit and 16KB `<style>` block limit
- `url()` in inline styles strips all styles in Gmail (critical)
- New Outlook (Edge) dark mode forced inversion
- Image gaps (`display: block; border: 0` on images)

**Key regex-detectable rules to include:**
- `url()` in inline styles: `style="[^"]*url\s*\(`
- Missing `display: block` on images inside `<td>`: `<td[^>]*>\s*<img(?![^>]*display:\s*block)`
- Missing `border="0"` on images: `<img(?![^>]*\bborder=)[^>]*>`
- `min-height` in inline styles (Outlook ignores): `style="[^"]*min-height\s*:`
- Whitespace RGB syntax: `rgba?\(\s*\d+\s+\d+\s+\d+[^,)]`
- `z-index` in styles (Outlook ignores): `style="[^"]*z-index\s*:`

- [ ] **Step 1: Read source document**

Read `docs/emails/research/email_rendering_compatibility.md` in full before writing.

- [ ] **Step 2: Write rendering.md**

Write `plugins/email-absolution/doctrines/rendering.md` following the `_template.md` structure.

Must include:
- Purpose paragraph covering client rendering engine diversity
- Rule catalog with RENDER-001 through RENDER-NNN covering all items in the "What to distil" list above
- CSS support matrix table (Safe / Partial / Risky for layout, typography, backgrounds, buttons, media queries, interactivity)
- Code examples for MSO conditionals, VML buttons, ghost table structure, `display: block` on images
- Known Afflictions section covering: Gmail `url()` strip, Gmail 102KB clip, Gmail 16KB style limit, Outlook `min-height` ignored, Outlook `z-index` ignored, New Outlook background image collapse, image gaps
- Sources section

- [ ] **Step 3: Verify line count**

```bash
wc -l plugins/email-absolution/doctrines/rendering.md
```

Expected: 300–420 lines. If under 300, the distillation is too thin — add more rules. If over 450, trim prose.

- [ ] **Step 4: Verify regex patterns are syntactically valid**

```bash
python3 -c "
import re
patterns = [
    r'style=\"[^\"]*url\s*\(',
    r'<img(?![^>]*display:\s*block)',
    r'<img(?![^>]*\bborder=)[^>]*>',
    r'style=\"[^\"]*min-height\s*:',
    r'rgba?\(\s*\d+\s+\d+\s+\d+[^,)]',
    r'style=\"[^\"]*z-index\s*:',
]
for p in patterns:
    re.compile(p)
    print(f'OK: {p[:50]}')
print('All patterns valid')
"
```

Expected: `All patterns valid`

- [ ] **Step 5: Commit**

```bash
git add plugins/email-absolution/doctrines/rendering.md
git commit -m "feat(email-absolution): add rendering doctrine (RENDER-001..NNN)"
```

---

## Task 3: HTML/CSS Doctrine

**Source:** `docs/emails/research/email_html_css_practices.md`
**File:** `plugins/email-absolution/doctrines/html-css.md`
**Target:** 300–400 lines, 20–25 rules, prefix `HTML-`

**What to distil:**
- Table-based layout as universal foundation (never rely on CSS for layout structure)
- Ghost table / hybrid layout pattern for multi-column
- Inline styles for critical layout; `<style>` blocks as enhancement only
- `font-size: 0` on wrappers (whitespace gap fix) — side effect on `em` units
- `mso-line-height-rule: exactly` requirement
- Dark mode CSS patterns (`prefers-color-scheme`, `color-scheme` meta tag)
- `<style>` block survival: forwarding strips it, Yahoo Android removes first `<head>`
- Reset styles for consistent baseline
- Safe CSS properties vs risky ones

**Key regex-detectable rules:**
- Flex used for layout structure: `display\s*:\s*flex` (venial — flag for review)
- `font-size: 0` without child reset: contextual hybrid
- Missing `mso-line-height-rule: exactly` when `line-height` set: `line-height\s*:\s*\d+px(?!.*mso-line-height-rule)`
- `<div>` used as primary layout wrapper: contextual
- Relative URLs in src/href: `(src|href)="(?!https?://|mailto:|#|cid:)`

- [ ] **Step 1: Read source document**

Read `docs/emails/research/email_html_css_practices.md` in full.

- [ ] **Step 2: Write html-css.md**

Write `plugins/email-absolution/doctrines/html-css.md`.

Must include:
- Purpose covering CSS isolation and safe-by-default patterns
- Rule catalog HTML-001 through HTML-NNN
- Code examples for: ghost table multi-column, correct `<style>` block structure, dark mode CSS overrides, `font-size: 0` with child reset, `mso-line-height-rule: exactly`
- Known Afflictions: `font-size: 0` `em` unit trap, ghost table whitespace gap, forwarding strips `<style>`, Yahoo Android first `<head>` removal
- Sources

- [ ] **Step 3: Verify line count**

```bash
wc -l plugins/email-absolution/doctrines/html-css.md
```

Expected: 300–420 lines.

- [ ] **Step 4: Verify regex patterns**

```bash
python3 -c "
import re
patterns = [
    r'display\s*:\s*flex',
    r'line-height\s*:\s*\d+px',
    r'(src|href)=\"(?!https?://|mailto:|#|cid:)',
]
for p in patterns:
    re.compile(p)
    print(f'OK: {p[:60]}')
print('All patterns valid')
"
```

- [ ] **Step 5: Commit**

```bash
git add plugins/email-absolution/doctrines/html-css.md
git commit -m "feat(email-absolution): add html-css doctrine (HTML-001..NNN)"
```

---

## Task 4: Accessibility Doctrine

**Source:** `docs/emails/research/email_accessibility_inclusivity.md`
**File:** `plugins/email-absolution/doctrines/accessibility.md`
**Target:** 300–400 lines, 20–25 rules, prefix `ACCESS-`

**What to distil:**
- All images need `alt`; decorative images need `alt=""` (not `alt=" "`, not omitted)
- Layout tables need `role="presentation"`
- WCAG 2.1 contrast requirements (AA: 4.5:1 normal text, 3:1 large text/UI)
- `lang` attribute on `<html>` element
- Tap targets minimum 44×44px (Apple HIG)
- `aria-label` stripped by Outlook 2007–2019 — visible text must carry meaning alone
- `aria-describedby`/`aria-labelledby` broken in Gmail, Fastmail, Outlook.com (id-prefix bug)
- Heading hierarchy (one `<h1>`, no skipped levels)
- EAA June 2025 enforcement now active
- `#999999` on white fails WCAG AA (2.9:1)

**Key regex-detectable rules:**
- Missing `alt` on `<img>`: `<img(?![^>]*\balt=)[^>]*>`
- `alt=" "` (space, not empty): `alt="\s+"`
- Layout tables missing `role="presentation"`: `<table(?![^>]*role=)[^>]*>` (hybrid — contextual to distinguish layout vs data tables)
- Missing `lang` on `<html>`: `<html(?![^>]*\blang=)[^>]*>`
- `aria-describedby` in template (flag for client support warning): `aria-describedby=`
- Colour `#999999` used as text: `color\s*:\s*#999999`

- [ ] **Step 1: Read source document**

Read `docs/emails/research/email_accessibility_inclusivity.md` in full.

- [ ] **Step 2: Write accessibility.md**

Write `plugins/email-absolution/doctrines/accessibility.md`.

Must include:
- Purpose covering WCAG 2.1 AA as minimum baseline + EAA enforcement
- Rule catalog ACCESS-001 through ACCESS-NNN
- Contrast ratio table (specific hex pairs with pass/fail)
- ARIA support matrix per client (from the research doc's verified caniemail.com data)
- Code examples: accessible button pattern (VML + ARIA), data table with `scope`, decorative image `alt=""`
- Known Afflictions: `aria-label` stripped in Outlook 2007–2019, id-prefix bugs in Gmail/Fastmail/Outlook.com breaking `aria-describedby`
- Regulatory context (EAA, ADA, Section 508, AODA) — brief, one paragraph each
- Sources

- [ ] **Step 3: Verify line count**

```bash
wc -l plugins/email-absolution/doctrines/accessibility.md
```

Expected: 300–420 lines.

- [ ] **Step 4: Verify regex patterns**

```bash
python3 -c "
import re
patterns = [
    r'<img(?![^>]*\balt=)[^>]*>',
    r'alt=\"\s+\"',
    r'<table(?![^>]*role=)[^>]*>',
    r'<html(?![^>]*\blang=)[^>]*>',
    r'aria-describedby=',
    r'color\s*:\s*#999999',
]
for p in patterns:
    re.compile(p)
    print(f'OK: {p[:60]}')
print('All patterns valid')
"
```

- [ ] **Step 5: Commit**

```bash
git add plugins/email-absolution/doctrines/accessibility.md
git commit -m "feat(email-absolution): add accessibility doctrine (ACCESS-001..NNN)"
```

---

## Task 5: Deliverability Doctrine

**Source:** `docs/emails/research/email_deliverability_technical_hygiene.md`
**File:** `plugins/email-absolution/doctrines/deliverability.md`
**Target:** 300–400 lines, 20–25 rules, prefix `DELIV-`

**What to distil:**
- Google/Yahoo 2024 bulk sender requirements (SPF + DKIM both required, DMARC p=none minimum, one-click unsubscribe for 5k+/day senders)
- RFC 8058 one-click unsubscribe: exact header syntax, DKIM must cover both headers
- Spam complaint thresholds: 0.10% warning, 0.30% hard rejection
- Text/HTML multipart: real plain text part required (not "this email requires HTML")
- DMARC subdomain alignment trap (relaxed vs strict)
- Reply-To vs From DMARC alignment
- HTML size signals (large HTML = spam signal; 102KB clips in Gmail)
- Pre-send checklist items

**Key regex-detectable rules:**
- Missing `List-Unsubscribe` header in marketing email: contextual (requires email.config.yml `type: marketing` + absence of header)
- Wrong `List-Unsubscribe-Post` syntax: `List-Unsubscribe-Post:(?!\s*List-Unsubscribe=One-Click)`
- `<style>` block size warning (over 16KB): contextual size check
- External images served over HTTP not HTTPS: `src="http://`
- Tracking pixel with no fallback: `<img[^>]*width="1"[^>]*height="1"` (flag MPP note)

- [ ] **Step 1: Read source document**

Read `docs/emails/research/email_deliverability_technical_hygiene.md` in full.

- [ ] **Step 2: Write deliverability.md**

Write `plugins/email-absolution/doctrines/deliverability.md`.

Must include:
- Purpose covering inbox placement as the output metric
- Rule catalog DELIV-001 through DELIV-NNN
- Pre-send QA checklist (distilled from research doc)
- 2024 Google/Yahoo requirements section (exact thresholds, verified from RFC 8058)
- Note on transactional vs marketing classification — Gmail decides, not sender
- Known Afflictions: DMARC subdomain strict alignment trap, Reply-To/From misalignment, transactional classified as promotional
- Sources

- [ ] **Step 3: Verify line count**

```bash
wc -l plugins/email-absolution/doctrines/deliverability.md
```

Expected: 300–420 lines.

- [ ] **Step 4: Verify regex patterns**

```bash
python3 -c "
import re
patterns = [
    r'List-Unsubscribe-Post:(?!\s*List-Unsubscribe=One-Click)',
    r'src=\"http://',
    r'<img[^>]*width=\"1\"[^>]*height=\"1\"',
]
for p in patterns:
    re.compile(p)
    print(f'OK: {p[:60]}')
print('All patterns valid')
"
```

- [ ] **Step 5: Commit**

```bash
git add plugins/email-absolution/doctrines/deliverability.md
git commit -m "feat(email-absolution): add deliverability doctrine (DELIV-001..NNN)"
```

---

## Task 6: Gotchas Doctrine

**Source:** `docs/emails/research/email_gotchas_edge_cases.md`
**File:** `plugins/email-absolution/doctrines/gotchas.md`
**Target:** 350–430 lines, 25–30 rules, prefix `GOTCHA-`

This is the richest doctrine. Prioritise the highest-impact, least-obvious traps. Every rule must have a concrete fix.

**What to distil (prioritised):**
- Gmail `url()` strips ALL inline styles on element (mortal)
- Gmail image cache permanent by URL — must version image URLs (mortal)
- Gmail whitespace RGB syntax strips entire rule — `rgb(0 0 0)` not `rgb(0,0,0)` (mortal)
- Gmail `max-width: 100%` broken on images in mobile webmail (venial)
- Gmail flex/hover only works for Google account holders (venial)
- Outlook 2007–2019: `min-height` ignored, `z-index` ignored, `border-radius` ignored, line-height inflation without `mso-line-height-rule: exactly`
- Outlook 365 (2025 builds) CSS regression in hybrid layouts
- New Outlook: forced dark mode inversion, background image collapse (#146)
- Apple MPP: open tracking pixels fire on download not open (mortal — inform, no fix)
- Apple data detectors: phone/date/address auto-linking overrides styles
- Yahoo/AOL strip `class` from `<img>` — image CSS rules fail
- Yahoo dark mode ignores `#fffffe` escape hack
- Yahoo desktop: CSS rule after comment is dropped
- Yahoo Android removes first `<head>`
- `display: none` unreliable for preheader — use full multi-property hiding
- Relative URLs fail in all email clients
- SVG not supported in Gmail or Outlook Windows
- CSS Custom Properties (`var()`) not supported in Gmail or Outlook
- Ghost table whitespace gap between columns

**Key regex-detectable rules:**
- `url()` in inline style: `style="[^"]*url\s*\(`
- Whitespace RGB: `rgba?\(\s*\d+\s+\d+\s+\d+\s`
- Relative URLs: `(src|href)="(?!https?://|mailto:|#|cid:)`
- `class` on `<img>` (Yahoo/AOL strip it): `<img[^>]*\bclass=`
- SVG in email: `<svg[\s>]|src="[^"]*\.svg"`
- CSS variables: `var\(--`
- `display:\s*none` without `mso-hide:all`: `display:\s*none(?!.*mso-hide)` (hybrid — check both `style=""` and `<style>` block)

- [ ] **Step 1: Read source document**

Read `docs/emails/research/email_gotchas_edge_cases.md` in full.

- [ ] **Step 2: Write gotchas.md**

Write `plugins/email-absolution/doctrines/gotchas.md`.

Must include:
- Purpose: the doctrine of snares — production traps that do not appear in compatibility matrices
- Rule catalog GOTCHA-001 through GOTCHA-NNN (min 25 rules)
- Quick reference table of the top 10 nastiest gotchas (reproduce from research doc, adapt to rule format)
- Known Afflictions section with hteumeuleu/email-bugs issue numbers
- Sources including caniemail.com and hteumeuleu/email-bugs

- [ ] **Step 3: Verify line count**

```bash
wc -l plugins/email-absolution/doctrines/gotchas.md
```

Expected: 350–450 lines.

- [ ] **Step 4: Verify regex patterns**

```bash
python3 -c "
import re
patterns = [
    r'style=\"[^\"]*url\s*\(',
    r'rgba?\(\s*\d+\s+\d+\s+\d+\s',
    r'(src|href)=\"(?!https?://|mailto:|#|cid:)',
    r'<img[^>]*\bclass=',
    r'<svg[\s>]',
    r'var\(--',
    r'display:\s*none',
]
for p in patterns:
    re.compile(p)
    print(f'OK: {p[:60]}')
print('All patterns valid')
"
```

- [ ] **Step 5: Commit**

```bash
git add plugins/email-absolution/doctrines/gotchas.md
git commit -m "feat(email-absolution): add gotchas doctrine (GOTCHA-001..NNN)"
```

---

## Task 7: Content & UX Doctrine

**Source:** `docs/emails/research/email_content_copy_ux.md`
**File:** `plugins/email-absolution/doctrines/content-ux.md`
**Target:** 250–350 lines, 15–20 rules, prefix `UX-`

This doctrine is primarily contextual — it operates on `email.config.yml` fields (subject, preheader) and the content structure of the template, not on HTML patterns.

**What to distil:**
- Subject line 40–50 chars (mobile safe), 60 max
- Preheader under 90 chars; `&#847;` padding to prevent body leaking into preheader slot
- Single CTA per email (transactional); clear hierarchy
- CTA button minimum 44px tap target
- Mobile-first: single column for transactional; two-column requires media queries
- Transactional email differences: no promotional language, clear sender identity, immediate value in first sentence
- Scannability: short paragraphs, bullet lists over prose blocks
- Apple Intelligence summarisation — lead with key fact in first sentence

**Key contextual rules (most are UX-level, not HTML-pattern):**
- Subject line length: `detect: contextual` — check `email.config.yml` subject field character count
- Missing preheader: `detect: regex` — check for preheader `<span>` with hiding styles
- Preheader missing `&#847;` padding: `detect: regex` — pattern: `mso-hide:all[^<]*<\/span>` without padding chars
- Multiple CTAs: `detect: contextual` — count primary `<a>` elements styled as buttons
- Missing plain text MIME part: `detect: contextual` — check MIME structure notes in email config

- [ ] **Step 1: Read source document**

Read `docs/emails/research/email_content_copy_ux.md` in full.

- [ ] **Step 2: Write content-ux.md**

Write `plugins/email-absolution/doctrines/content-ux.md`.

Must include:
- Purpose covering engagement, scannability, and transactional clarity
- Rule catalog UX-001 through UX-NNN
- Note that most rules operate on `email.config.yml` subject/preheader fields and template content, not HTML structure
- Code example for correct preheader hiding with `&#847;` padding
- Known Afflictions: Apple Intelligence overriding preheader, Apple MPP invalidating open-rate engagement signals
- Sources

- [ ] **Step 3: Verify line count**

```bash
wc -l plugins/email-absolution/doctrines/content-ux.md
```

Expected: 250–370 lines.

- [ ] **Step 4: Commit**

```bash
git add plugins/email-absolution/doctrines/content-ux.md
git commit -m "feat(email-absolution): add content-ux doctrine (UX-001..NNN)"
```

---

## Task 8: Tooling Overview Doctrine

**Source:** `docs/emails/research/email_templating_languages_frameworks.md`
**File:** `plugins/email-absolution/doctrines/tooling.md`
**Target:** 200–280 lines, 10–15 rules, prefix `TOOL-`

This doctrine is the **framework selection guide and cross-tool reference**. It is loaded by `elder` and `visitation` alongside the per-language doctrine. It is NOT loaded by `scribe` (the scribe loads the per-language doctrine directly).

**What to include:**
- Framework comparison table: MJML vs React Email vs Maizzle vs Handlebars vs Liquid vs plain-HTML — columns: maturity, abstraction level, Outlook support, ESP compatibility, learning curve, when to choose
- ESP variable syntax reference per platform (sendgrid, mailchimp, postmark, mailgun, ses, sparkpost)
- When to use each tool (decision tree or table form)
- Cross-tool pitfalls: compiled output must always be audited regardless of tool, templating variables vs HTML escaping

**Rules are primarily TOOL-level/counsel (tooling choice is architectural):**
- Using MJML but not auditing compiled output for VML completeness: `detect: contextual`
- Mixing ESP variable syntax (e.g. Handlebars `{{variable}}` used with Postmark which uses Mustache): `detect: contextual`
- No fallback font stack: `detect: regex` — `font-family\s*:\s*'[^']+'(?!\s*,)`

- [ ] **Step 1: Read source document**

Read `docs/emails/research/email_templating_languages_frameworks.md` in full.

- [ ] **Step 2: Write tooling.md**

Write `plugins/email-absolution/doctrines/tooling.md` as the overview/selection guide. Do NOT include deep per-language rules here — those live in the per-language doctrine files (Tasks 9–13).

Must include:
- Purpose covering framework selection and cross-tool correctness
- Framework comparison table
- ESP variable syntax reference per platform
- Rule catalog TOOL-001 through TOOL-NNN
- Sources

- [ ] **Step 3: Verify line count**

```bash
wc -l plugins/email-absolution/doctrines/tooling.md
```

Expected: 200–300 lines.

- [ ] **Step 4: Commit**

```bash
git add plugins/email-absolution/doctrines/tooling.md
git commit -m "feat(email-absolution): add tooling overview doctrine (TOOL-001..NNN)"
```

---

## Task 9: MJML Doctrine

**Source:** `docs/emails/research/email_templating_languages_frameworks.md`
**File:** `plugins/email-absolution/doctrines/mjml.md`
**Target:** 250–350 lines, 15–20 rules, prefix `MJML-`

**What to distil:**
- Current stable version: 4.18.0; v5 beta status and breaking changes (mj-body controls `<body>`, `<mj-include>` disabled by default, new API surface)
- Component reference: mj-section, mj-column, mj-image, mj-button, mj-text, mj-divider, mj-social
- MJML attributes vs inline CSS — when each is appropriate
- Compiled output correctness: MJML outputs table-based HTML, but VML fallbacks must be verified in compiled output — `mj-button` may not include VML for Outlook in all configurations
- `mj-head` / `mj-attributes` for global styles
- Custom components and includes (v4 behaviour)
- MJML CLI vs Node API usage

**Key rules:**
- Always audit compiled output for VML completeness before shipping: `detect: contextual`
- `mj-image` must have `alt` attribute: `detect: regex` — `<mj-image(?![^>]*\balt=)[^>]*/>`
- Do not use `font-size` attribute on `mj-text` without a matching `line-height`: `detect: contextual`
- MJML v5 `<mj-include>` requires explicit opt-in; do not use without confirming version: `detect: contextual`
- Do not inline custom HTML inside `mj-text` without testing Outlook rendering: `detect: contextual`

- [ ] **Step 1: Read source document**

Read `docs/emails/research/email_templating_languages_frameworks.md` in full (already read for Task 8 — skip re-read if in same session).

- [ ] **Step 2: Write mjml.md**

Write `plugins/email-absolution/doctrines/mjml.md`.

Must include:
- Purpose: MJML-specific rules for teams using MJML as their authoring layer
- v4 vs v5 differences table
- Rule catalog MJML-001 through MJML-NNN
- Patterns & Code Examples: correct mj-button with VML, correct mj-image with alt, correct mj-attributes global styles
- Known Afflictions: MJML v5 breaking changes, VML-incomplete compiled output
- Sources

- [ ] **Step 3: Verify line count**

```bash
wc -l plugins/email-absolution/doctrines/mjml.md
```

Expected: 250–370 lines.

- [ ] **Step 4: Commit**

```bash
git add plugins/email-absolution/doctrines/mjml.md
git commit -m "feat(email-absolution): add MJML doctrine (MJML-001..NNN)"
```

---

## Task 10: Handlebars Doctrine

**Source:** `docs/emails/research/email_templating_languages_frameworks.md`
**File:** `plugins/email-absolution/doctrines/handlebars.md`
**Target:** 200–300 lines, 15–20 rules, prefix `HBS-`

**What to distil:**
- Handlebars vs Mustache: same `{{variable}}` syntax but different helpers — SendGrid uses Handlebars, Postmark uses Mustache — critical distinction
- SendGrid-specific: `{{#each}}`, `{{#if}}`, `{{subject}}`, `{{unsubscribe}}`
- Mailgun-specific: `%recipient.name%` syntax (not Handlebars)
- Partials: `{{> partial-name}}` in Handlebars; not supported in all ESPs
- HTML escaping: `{{{unescaped}}}` vs `{{escaped}}` — when each is appropriate
- ESP variable name collisions: reserved variable names per platform

**Key rules:**
- Using `{{#each}}` with Postmark (Mustache, no `#each`): `detect: contextual` — check `stack.esp` in config
- Triple-stash `{{{variable}}}` (unescaped HTML) in user-supplied content fields: `detect: regex` — `\{\{\{`
- Missing fallback value for optional variables: `detect: contextual` — look for `{{variable}}` without `{{variable default="..."}}` pattern in transactional content
- Partial paths that are absolute or environment-specific: `detect: regex` — `\{\{>\s*[/'"]`

- [ ] **Step 1: Write handlebars.md**

Write `plugins/email-absolution/doctrines/handlebars.md`.

Must include:
- Purpose: Handlebars-specific rules, ESP distinction, and security considerations
- ESP syntax comparison table (SendGrid/Handlebars vs Postmark/Mustache vs Mailgun syntax)
- Rule catalog HBS-001 through HBS-NNN
- Patterns & Code Examples: correct `{{#each}}` loop, correct fallback pattern, correct partial usage
- Known Afflictions: SendGrid vs Postmark syntax mismatch, Mailgun's non-Handlebars syntax
- Sources

- [ ] **Step 2: Verify line count**

```bash
wc -l plugins/email-absolution/doctrines/handlebars.md
```

Expected: 200–320 lines.

- [ ] **Step 3: Commit**

```bash
git add plugins/email-absolution/doctrines/handlebars.md
git commit -m "feat(email-absolution): add Handlebars doctrine (HBS-001..NNN)"
```

---

## Task 11: Liquid Doctrine

**Source:** `docs/emails/research/email_templating_languages_frameworks.md`
**File:** `plugins/email-absolution/doctrines/liquid.md`
**Target:** 200–300 lines, 15–20 rules, prefix `LIQ-`

**What to distil:**
- Liquid syntax: `{{ variable }}`, `{% for item in items %}`, `{% if condition %}`, `{% unless %}`, `{% assign %}`, `{% capture %}`
- Shopify Email vs Klaviyo Liquid — differences in available objects and filters
- Filters: `| upcase`, `| downcase`, `| date`, `| money`, `| default`
- `{{ customer.first_name | default: "there" }}` fallback pattern
- Liquid strict mode (Shopify) vs tolerant mode — undefined variables
- Whitespace control: `{%- -%}` trim syntax and when it matters in HTML email

**Key rules:**
- Missing fallback filter on customer-facing personalization: `detect: regex` — `\{\{\s*\w+\.\w+\s*\}\}` (variable without filter)
- Whitespace trim in `<td>` cells causing collapsed content in Outlook: `detect: regex` — `<td[^>]*>\s*{%-`
- Using Shopify-specific objects (`shop.`, `order.`) in Klaviyo context (different object model): `detect: contextual` — check `stack.esp`

- [ ] **Step 1: Write liquid.md**

Write `plugins/email-absolution/doctrines/liquid.md`.

Must include:
- Purpose: Liquid-specific rules for Shopify and Klaviyo email contexts
- Shopify vs Klaviyo object model differences table
- Rule catalog LIQ-001 through LIQ-NNN
- Patterns & Code Examples: correct fallback filter usage, correct loop with `forloop.first`, whitespace control
- Sources

- [ ] **Step 2: Verify line count**

```bash
wc -l plugins/email-absolution/doctrines/liquid.md
```

Expected: 200–320 lines.

- [ ] **Step 3: Commit**

```bash
git add plugins/email-absolution/doctrines/liquid.md
git commit -m "feat(email-absolution): add Liquid doctrine (LIQ-001..NNN)"
```

---

## Task 12: React Email Doctrine

**Source:** `docs/emails/research/email_templating_languages_frameworks.md`
**File:** `plugins/email-absolution/doctrines/react-email.md`
**Target:** 250–350 lines, 15–20 rules, prefix `REMAIL-`

**What to distil:**
- Current version: 5.2.10 (production-ready as of 2024)
- Component library: `<Html>`, `<Head>`, `<Body>`, `<Container>`, `<Section>`, `<Row>`, `<Column>`, `<Button>`, `<Image>`, `<Text>`, `<Link>`, `<Hr>`, `<Preview>`
- Rendering pipeline: React → HTML string via `render()` — compiled output must be inspected
- Outlook limitations: React Email uses modern CSS in some components that degrades in Outlook; `<Button>` generates `<a>` not a VML button
- TypeScript props: all components are strongly typed; missing required props cause build errors
- `tailwindConfig` support: CSS-in-JS via `className` works for preview but compiled CSS may be stripped by clients
- Email client preview: built-in dev server with live preview per client

**Key rules:**
- `<Button>` component does not generate VML Outlook fallback — replace with explicit VML button for Outlook support: `detect: contextual` — check if VML alternative is present in compiled output
- Using `className` with Tailwind CSS without confirming the client supports the compiled output: `detect: contextual`
- `<Image>` without `alt` prop: `detect: regex` — `<Image(?![^>]*\balt=)[^>]*/>`
- Absolute URLs not used on `<Image src>`: `detect: regex` — `<Image\s[^>]*src=["']/(?!/)` (relative path)

- [ ] **Step 1: Write react-email.md**

Write `plugins/email-absolution/doctrines/react-email.md`.

Must include:
- Purpose: React Email-specific rules and Outlook compatibility considerations
- Component reference table (component → rendered HTML element)
- Rule catalog REMAIL-001 through REMAIL-NNN
- Patterns & Code Examples: correct VML button alternative, correct `<Image>` with alt and absolute URL, correct `<Preview>` preheader
- Known Afflictions: VML-missing Button, Tailwind CSS stripping
- Sources

- [ ] **Step 2: Verify line count**

```bash
wc -l plugins/email-absolution/doctrines/react-email.md
```

Expected: 250–370 lines.

- [ ] **Step 3: Commit**

```bash
git add plugins/email-absolution/doctrines/react-email.md
git commit -m "feat(email-absolution): add React Email doctrine (REMAIL-001..NNN)"
```

---

## Task 13: Maizzle Doctrine

**Source:** `docs/emails/research/email_templating_languages_frameworks.md`
**File:** `plugins/email-absolution/doctrines/maizzle.md`
**Target:** 200–300 lines, 15–20 rules, prefix `MZL-`

**What to distil:**
- Current version: 5.5.0; Tailwind CSS v4 integration
- Authoring model: HTML + Tailwind utility classes → inlined CSS via PostCSS + email-specific transforms
- `config.js` (or `config.production.js`) controls inlining, URL rewriting, class removal
- Transformers: `removeUnusedCSS`, `inlineCSS`, `urlParameters`, `attributeToStyle`
- Component system: layouts and components via HTML `<extends>` and `<block>` syntax
- `env` support: development (readable) vs production (minified, inlined) builds

**Key rules:**
- Using Tailwind responsive utilities (`md:`, `lg:`) without confirming `<style>` block support in target clients: `detect: contextual`
- `removeUnusedCSS: false` in production config — unused classes bloat output: `detect: contextual` — check `config.production.js`
- Not running production build before sending (dev build is not inlined): `detect: contextual`
- Tailwind `font-size` without `line-height` pair — Outlook requires both: `detect: contextual`

- [ ] **Step 1: Write maizzle.md**

Write `plugins/email-absolution/doctrines/maizzle.md`.

Must include:
- Purpose: Maizzle-specific rules for Tailwind-based email authoring
- Build pipeline overview (dev vs production build differences)
- Rule catalog MZL-001 through MZL-NNN
- Patterns & Code Examples: correct production config, correct responsive pattern with media query fallback, correct `<extends>` layout usage
- Known Afflictions: dev vs production build confusion, Tailwind responsive utility stripping
- Sources

- [ ] **Step 2: Verify line count**

```bash
wc -l plugins/email-absolution/doctrines/maizzle.md
```

Expected: 200–320 lines.

- [ ] **Step 3: Commit**

```bash
git add plugins/email-absolution/doctrines/maizzle.md
git commit -m "feat(email-absolution): add Maizzle doctrine (MZL-001..NNN)"
```

---

## Task 14: Elder Skill

**File:** `plugins/email-absolution/skills/elder/SKILL.md`

- [ ] **Step 1: Write elder/SKILL.md**

The elder is the entry point and Witchfinder General. Write `plugins/email-absolution/skills/elder/SKILL.md` with the following structure and content:

```markdown
---
name: elder
description: >
  Use for all HTML email questions, planning, template review routing, and template generation.
  Triggers on: "email question", "help with email", "elder", "review my email", "build me an email",
  "does X work in Y client", "email setup", "email config", "email absolution".
---

# The Elder — Witchfinder General of the Email Sanctum

[Persona opening — 2-3 sentences in Witchfinder voice establishing the elder's role]

## On First Invocation

Check for `.email-absolution/config.yml`. If absent:

> "I have not seen your configuration, seeker. Before the scriptures may guide you, we must establish the covenant of your sanctum. Shall I ask the questions now?"

If the user agrees, run the Setup Questionnaire. If they decline, proceed with built-in defaults and note they are in use.

## Setup Questionnaire

Ask in order, one question at a time. Write `.email-absolution/config.yml` on completion.

1. **ESP**: "Which email service provider carries your scripture to the faithful?"
   Options: sendgrid | mailchimp | postmark | mailgun | ses | sparkpost | other

2. **Templating language**: "What tongue does your scribe speak?"
   Options: handlebars | liquid | mjml | react-email | maizzle | plain-html

3. **Template structure**: "How is your sanctum organised?"
   - master-child: A single master layout wrapping one content template per email
   - master-components: A master layout assembling discrete header, footer, and content components
   - plain-html: No abstraction — raw HTML files

4. **Target clients**: "Which congregations must your emails reach?"
   Options: all (recommended) | specific list

5. **Brand**: "The marks of your house — primary colour, font stack, max width?"
   Defaults: #0066cc, Arial/Helvetica/sans-serif, 600px

6. **Strictness per doctrine**: "How strictly shall I judge?"
   Suggest defaults: rendering: strict, html-css: strict, accessibility: pragmatic,
   deliverability: strict, gotchas: strict, content-ux: pragmatic, tooling: aspirational
   (tooling strictness applies to both tooling.md and the per-language doctrine)

## Loaded Doctrines

Load from `${CLAUDE_SKILL_DIR}/../../doctrines/`:

**Core (always):** rendering.md, html-css.md, content-ux.md, accessibility.md, deliverability.md, gotchas.md

**Tooling:** tooling.md (always) + the per-language file matching `stack.templating` in config:
- `handlebars` → handlebars.md
- `liquid` → liquid.md
- `mjml` → mjml.md
- `react-email` → react-email.md
- `maizzle` → maizzle.md
- `plain-html` or absent → tooling.md only

If any doctrine file is missing: warn ("The scripture of [name] could not be found — proceeding without it") and continue.

## Decision Logic

| User intent | Action |
|-------------|--------|
| Question about email (does X work in Y? how do I...?) | Answer directly from loaded doctrines |
| User pastes HTML template | "This template requires a visitation. Invoke `/email-absolution:visitation` and present the template for judgement." |
| User requests template generation | Ask planning questions (email name, type, required content sections, tone), then: "The covenant is set. Summon the scribe: `/email-absolution:scribe [name]`" |
| Config absent | Run setup questionnaire first |

**The elder does not silently invoke other skills.** It tells the user which skill to invoke and why.

## Consultation Guidance

When answering questions from doctrine:
- Cite the specific rule ID (e.g. RENDER-001) when referencing a rule
- Always flag if the answer differs based on target client configuration
- If a gotcha is relevant to the question, surface it proactively
- Keep Witchfinder tone: precise, uncompromising, but never obscure

## Config Merge Resolution

When advising on email-specific questions, resolve config in this order:
1. Per-email `email.config.yml` (if user references a specific email)
2. Project `email_defaults` in `.email-absolution/config.yml`
3. Built-in defaults

## Vocabulary

[Full vocabulary table from spec — Heresy, Mortal sin, Venial sin, Found righteous, etc.]

## Guardrail

The persona is flavour, not a barrier. Every answer must be technically precise and actionable.
```

- [ ] **Step 2: Verify SKILL.md frontmatter is valid YAML**

```bash
python3 -c "
import re
with open('plugins/email-absolution/skills/elder/SKILL.md') as f:
    content = f.read()
match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
if not match:
    print('ERROR: No frontmatter found')
    exit(1)
import yaml
data = yaml.safe_load(match.group(1))
assert 'name' in data, 'Missing name'
assert 'description' in data, 'Missing description'
print(f'OK: name={data[\"name\"]}')
print(f'OK: description starts with: {str(data[\"description\"])[:60]}')
"
```

Expected: `OK: name=elder`

- [ ] **Step 3: Commit**

```bash
git add plugins/email-absolution/skills/elder/SKILL.md
git commit -m "feat(email-absolution): add elder skill"
```

---

## Task 15: Visitation Skill

**File:** `plugins/email-absolution/skills/visitation/SKILL.md`

- [ ] **Step 1: Write visitation/SKILL.md**

```markdown
---
name: visitation
description: >
  Use to audit an existing HTML email template against all email doctrines.
  Triggers on: "audit this email", "check my template", "visitation", "review this template",
  "is this email correct", "check this email for issues".
---

# The Visitation — Formal Inspection of the Email Sanctum

[Persona opening in Witchfinder voice]

## Input Handling

| Input type | Behaviour |
|------------|-----------|
| Inline pasted HTML | Audit the pasted content directly |
| File path (`emails/name/template.hbs`) | Read the file, then audit |
| Directory path (`emails/name/`) | Read all template files in the directory, audit each |
| No argument | Ask: "Present the template for judgement — paste the HTML, or provide a file path." |

## Loaded Doctrines

Load from `${CLAUDE_SKILL_DIR}/../../doctrines/`:

**Core (always):** rendering.md, html-css.md, content-ux.md, accessibility.md, deliverability.md, gotchas.md

**Tooling:** tooling.md (always) + the per-language file matching `stack.templating` in config (handlebars.md / liquid.md / mjml.md / react-email.md / maizzle.md). If `plain-html` or config absent, load tooling.md only.

If any doctrine file is missing: warn ("The scripture of [name] could not be found — proceeding without it") and continue.

## Config Loading

1. Load `.email-absolution/config.yml` — if absent, note it and use built-in defaults
2. If template path was provided, look for `email.config.yml` in the same directory — if absent, note it
3. Resolve strictness: per-email → project → pragmatic default

## Audit Process

For each doctrine, apply all rules in its catalog:

**For `detect: regex` rules:**
Run the pattern against the full template source. Flag every match.

**For `detect: contextual` rules:**
Reason about the template structure, content, and loaded configs. Apply judgment.

**For `detect: hybrid` rules:**
Run the regex first. For any non-matches, apply contextual reasoning to catch nuanced violations.

Apply strictness from config:
- `strict`: All violations from this doctrine are mortal sins
- `pragmatic`: `mortal`-severity rules remain mortal; `venial` rules become counsel
- `aspirational`: All violations become counsel (guidance only)

## Output Format

```
The Verdict — [template name or "unnamed template"]
====================================================
Doctrines applied: rendering, html-css, accessibility, deliverability, gotchas, content-ux, tooling
Heresies found: N (M mortal, K venial)

Mortal sins (must be resolved before this template ships):
──────────────────────────────────────────────────────────
[RENDER-001] url() found in inline style on line N
  The affliction: Gmail strips ALL inline styles from this element.
  The absolution: Move background-image to a <style> block class.

[GOTCHA-007] Relative URL found: src="/images/logo.png"
  The affliction: All email clients require absolute URLs. This image will not load.
  The absolution: Use https://yourdomain.com/images/logo.png

Venial sins (counsel from the elders):
───────────────────────────────────────
[ACCESS-003] Layout table missing role="presentation"
  The affliction: Screen readers announce table structure to visually impaired users.
  The absolution: Add role="presentation" to all layout tables.

Found righteous:
────────────────
  ✓ Deliverability — No HTTP image URLs; all images served over HTTPS
  ✓ Rendering — MSO conditional comments present for multi-column layout
  ✓ Accessibility — All img elements have alt attributes

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The soul is [clean. Go forth and send without sin. | not yet clean. Absolution awaits.]
```

## Error Handling

[Error handling table from spec — missing config, missing doctrine, no argument]

## Vocabulary

[Vocabulary table — same as elder]
```

- [ ] **Step 2: Verify frontmatter**

```bash
python3 -c "
import re, yaml
with open('plugins/email-absolution/skills/visitation/SKILL.md') as f:
    content = f.read()
match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
data = yaml.safe_load(match.group(1))
assert data['name'] == 'visitation'
print('OK:', data['name'])
"
```

- [ ] **Step 3: Commit**

```bash
git add plugins/email-absolution/skills/visitation/SKILL.md
git commit -m "feat(email-absolution): add visitation skill"
```

---

## Task 16: Scribe Skill

**File:** `plugins/email-absolution/skills/scribe/SKILL.md`

- [ ] **Step 1: Write scribe/SKILL.md**

```markdown
---
name: scribe
description: >
  Use to generate a new HTML email template or component built to doctrine.
  Triggers on: "write an email", "generate a template", "scribe", "build a receipt email",
  "create an email template", "write me an order confirmation".
---

# The Scribe — Builder of Righteous Email Scripture

[Persona opening in Witchfinder voice]

## Loaded Doctrines

Load from `${CLAUDE_SKILL_DIR}/../../doctrines/`:

**Core:** rendering.md, html-css.md, accessibility.md, deliverability.md, gotchas.md

**Tooling:** the per-language file matching `stack.templating` in config (handlebars.md / liquid.md / mjml.md / react-email.md / maizzle.md). If `plain-html` or config absent, skip tooling doctrine.

(content-ux is a planning concern addressed upstream by elder. tooling.md overview is selection guidance not needed during generation — the per-language doctrine gives the scribe what it needs.)

## Config Loading

1. Load `.email-absolution/config.yml` — if absent, ask the 6 setup questions inline before generating
2. Load `emails/<name>/email.config.yml` if it exists — if absent, ask questions and create it

**Per-email config questions (when email.config.yml absent):**
1. Email name (used as directory name)
2. Email type: transactional | marketing | notification
3. Subject line
4. Preheader text
5. Required content sections (e.g. order summary table, CTA button, address block)
6. Any tone or from-address overrides

**Config merge precedence:**
1. Per-email `email.config.yml`
2. Project `email_defaults` in `.email-absolution/config.yml`
3. Built-in defaults

## Generation Rules

Every generated template MUST include — non-negotiable:

**Structure:**
- `<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" ...>`
- `<html xmlns="..." lang="en" xml:lang="en">`
- `<meta charset="utf-8">`
- `<meta name="viewport" content="width=device-width, initial-scale=1">`
- `<meta name="color-scheme" content="light dark">`
- `<meta name="supported-color-schemes" content="light dark">`
- `<title>` element matching email subject
- Max width wrapper table at configured `brand.max_width` (default 600px)

**Layout:**
- Table-based layout only (`<table role="presentation">` for all layout tables)
- Ghost table pattern for multi-column (`<!--[if mso]><table><tr><td>...<![endif]-->`)
- No `position`, `float`, or `display: flex` for structural layout

**Images:**
- All `<img>` elements: `alt=""` or descriptive alt text, `display: block`, `border: 0`
- All image URLs absolute (`https://`)
- 2× dimensions served, `width` attribute at display size

**Outlook compatibility:**
- VML fallbacks for buttons and background images
- `mso-line-height-rule: exactly` on all elements with explicit `line-height`
- MSO conditional wrappers for multi-column layouts

**Preheader:**
```html
<span style="display:none; visibility:hidden; opacity:0; color:transparent;
             height:0; width:0; font-size:0; max-height:0; overflow:hidden; mso-hide:all;">
  [preheader text] &#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;[repeat to ~90 chars total]
</span>
```

**Accessibility:**
- `lang="en"` on `<html>`
- `role="presentation"` on all layout `<table>` elements
- Logical heading hierarchy (one `<h1>`, `<h2>` for sections)
- Minimum 44px tap targets for buttons
- Contrast ratios: body text minimum 4.5:1

**Deliverability:**
- Include `List-Unsubscribe` headers if `unsubscribe: true` in email config
- All images over HTTPS
- Templating variable syntax matching configured ESP

**Templating language:**
Output variables, loops, and conditionals in the syntax of the configured templating language:
- handlebars: `{{variable}}`, `{{#each items}}`, `{{#if condition}}`
- liquid: `{{ variable }}`, `{% for item in items %}`, `{% if condition %}`
- mjml: `<mj-text>{{variable}}</mj-text>` (MJML source, not compiled output)
- plain-html: no variables

## Output

Generate the full template file(s) based on `template.structure` config:
- `master-child`: one master layout file + one content file
- `master-components`: master layout + header, footer, CTA button, content components
- `plain-html`: single self-contained HTML file

After generating, offer:
> "The writ is complete. Shall I summon a visitation to confirm the soul is clean? Invoke `/email-absolution:visitation emails/[name]/template.[ext]`"

## Error Handling

[Error handling table from spec]

## Vocabulary

[Vocabulary table — same as elder and visitation]
```

- [ ] **Step 2: Verify frontmatter**

```bash
python3 -c "
import re, yaml
with open('plugins/email-absolution/skills/scribe/SKILL.md') as f:
    content = f.read()
match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
data = yaml.safe_load(match.group(1))
assert data['name'] == 'scribe'
print('OK:', data['name'])
"
```

- [ ] **Step 3: Final structural check — all files present**

```bash
find plugins/email-absolution -name "*.md" -o -name "*.json" | sort
```

Expected:
```
plugins/email-absolution/.claude-plugin/plugin.json
plugins/email-absolution/README.md
plugins/email-absolution/doctrines/_template.md
plugins/email-absolution/doctrines/accessibility.md
plugins/email-absolution/doctrines/content-ux.md
plugins/email-absolution/doctrines/deliverability.md
plugins/email-absolution/doctrines/gotchas.md
plugins/email-absolution/doctrines/handlebars.md
plugins/email-absolution/doctrines/html-css.md
plugins/email-absolution/doctrines/liquid.md
plugins/email-absolution/doctrines/maizzle.md
plugins/email-absolution/doctrines/mjml.md
plugins/email-absolution/doctrines/react-email.md
plugins/email-absolution/doctrines/rendering.md
plugins/email-absolution/doctrines/tooling.md
plugins/email-absolution/skills/elder/SKILL.md
plugins/email-absolution/skills/visitation/SKILL.md
plugins/email-absolution/skills/scribe/SKILL.md
```

- [ ] **Step 4: Commit**

```bash
git add plugins/email-absolution/skills/scribe/SKILL.md
git commit -m "feat(email-absolution): add scribe skill — plugin complete"
```

- [ ] **Step 5: Final commit — tag v0.1.0**

```bash
git tag email-absolution-v0.1.0
```

---

## Smoke Test

After all tasks are complete, manually verify the plugin loads correctly:

- [ ] Invoke `/email-absolution:elder` — should greet and check for config
- [ ] Ask "does flex work in Gmail?" — should answer from rendering + gotchas doctrines citing RENDER- or GOTCHA- rule IDs
- [ ] Invoke `/email-absolution:visitation` with no argument — should ask for template
- [ ] Invoke `/email-absolution:scribe` with no argument — should ask for email type

---

## Notes for Implementer

- **Do not copy-paste from the research docs verbatim** — distil to rule catalog format. A doctrine is a checklist, not an essay.
- **Every `detect: regex` rule must have a tested pattern** — run the verify step before committing.
- **Rule IDs must be unique and sequential** within each doctrine. No gaps, no duplicates.
- **The vocabulary table must appear in all three skills** — copy it identically. Consistency matters.
- **Scribe generates templating-language-aware output** — the Handlebars syntax for a loop differs from Liquid. The skill must switch based on config.
- **When in doubt about persona tone**: read `plugins/puritan/skills/inquisition/SKILL.md` — that is the gold standard for Witchfinder voice.
